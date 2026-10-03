"""
Read-only access to the case's parsed artifact databases.

Every connection is opened with the SQLite URI ``mode=ro`` so writing to (or
indexing) evidence databases is impossible by construction. Database file
names vary slightly between Crow-Eye versions (e.g. ``prefetch_data.db`` at
the artifacts root vs inside ``Prefetch/``), so each logical database has an
ordered list of candidate relative paths and the first existing one wins.
"""

import os
import sqlite3
import logging
import threading
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Logical DB name -> candidate paths relative to Target_Artifacts, in
# priority order. Verified against a real case (Discord 2 26.6.26) plus the
# alternates used by older parser versions / the offline importer.
DB_CANDIDATES: Dict[str, List[str]] = {
    "registry": ["registry_data.db"],
    "lnk": ["LnkDB.db"],
    "logs": ["Log_Claw.db", os.path.join("event_logs", "event_logs.db")],
    "prefetch": ["prefetch_data.db", os.path.join("Prefetch", "prefetch_data.db")],
    "shimcache": ["shimcache.db"],
    "amcache": ["amcache.db"],
    "recyclebin": ["recyclebin_analysis.db"],
    "srum": ["srum_data.db", os.path.join("srum_database", "srum_data.db")],
    "mft": ["mft_claw_analysis.db", os.path.join("MFT_USN", "MFT_data.db")],
    "usn": ["USN_journal.db", os.path.join("MFT_USN", "USN_journal.db")],
    "mft_usn_correlated": ["mft_usn_correlated_analysis.db"],
    # Browser_Claw writes this flat in Target_Artifacts (Browser_Claw.py's
    # OUTPUT_DB_NAME beside case_artifacts_dir), the same place the timeline
    # module resolves it from.
    "browser": ["browser_analysis.db"],
}

# Tables whose row counts indicate "there is parsed data" for getStatus().
KEY_TABLES: Dict[str, List[str]] = {
    "registry": ["UserAssist", "BAM", "Shellbags", "UserProfiles", "USBDevices",
                 "InstalledSoftware", "SystemServices", "MUICache"],
    "lnk": ["LNK_Files", "Automatic_JumpLists", "Custom_JumpLists"],
    "logs": ["SecurityLogs", "SystemLogs", "ApplicationLogs"],
    "prefetch": ["prefetch_data"],
    "shimcache": ["shimcache_entries"],
    "amcache": ["InventoryApplication", "InventoryApplicationFile",
                "InventoryApplicationShortcut", "InventoryDriverBinary",
                "InventoryDevicePnp"],
    "recyclebin": ["recycle_bin_entries"],
    "srum": ["srum_application_usage", "srum_network_data_usage",
             "srum_network_connectivity"],
    "mft": ["mft_records", "filename_changes"],
    "usn": ["journal_events"],
    "mft_usn_correlated": ["mft_usn_correlated"],
    # Chromium and Gecko side by side: a case can have either, or both. Without
    # an entry here data_status() reports the database present with zero rows,
    # and the React empty state says the case has no parsed data.
    "browser": ["browser_history", "browser_downloads", "browser_cookies",
                "browser_extensions", "browser_sessions",
                "browser_gecko_history"],
}


def resolve_db_path(artifacts_dir: str, logical_name: str) -> Optional[str]:
    """Return the absolute path of a logical database, or None if absent."""
    for rel in DB_CANDIDATES.get(logical_name, []):
        path = os.path.join(artifacts_dir, rel)
        if os.path.isfile(path):
            return path
    return None


def open_ro(db_path: str) -> sqlite3.Connection:
    """Open a SQLite database strictly read-only, rows accessible by name."""
    uri = "file:{}?mode=ro".format(db_path.replace("\\", "/"))
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    return [r[1] for r in conn.execute('PRAGMA table_info("{}")'.format(table))]


def row_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return conn.execute('SELECT COUNT(*) FROM "{}"'.format(table)).fetchone()[0]
    except sqlite3.Error:
        return 0


class DbPool:
    """Lazy pool of read-only connections, one per thread per logical DB.

    Missing databases are remembered as None so rules can degrade cleanly
    without repeated filesystem probing.

    **Why the pool is keyed by thread.** A ``sqlite3.Connection`` may only be
    used by the thread that opened it. UBA runs its analysis on
    ``AnalysisWorker`` (a QThread) and then answers the React UI from the GUI
    thread, so a pool keyed on the logical name alone hands the GUI thread a
    connection the worker opened. That is not theoretical - it crashed
    Crow-Eye on UBA -> Sessions:

        sqlite3.ProgrammingError: SQLite objects created in a thread can only
        be used in that same thread.

    ``check_same_thread=False`` would silence it and is the wrong answer: it
    permits two threads to interleave on one connection. The timeline module
    reached the same conclusion and wrote it down - see
    ``timeline/data/timeline_data_manager.py`` line 373, "BUG FIX #1: Removed
    check_same_thread=False for thread safety". This is that module's
    ``(thread_id, key)`` pool, scaled down to UBA's needs.
    """

    def __init__(self, artifacts_dir: str):
        self.artifacts_dir = artifacts_dir
        # (thread id, logical name) -> connection or None. Never keyed on the
        # name alone; see the class docstring.
        self._conns: Dict[Tuple[int, str], Optional[sqlite3.Connection]] = {}
        # Resolved paths are just strings, so they are shared across threads -
        # a database that is missing is missing for everyone, and probing the
        # filesystem once per thread would be waste.
        self._paths: Dict[str, Optional[str]] = {}
        self._lock = threading.Lock()

    def path(self, logical_name: str) -> Optional[str]:
        with self._lock:
            if logical_name not in self._paths:
                self._paths[logical_name] = resolve_db_path(self.artifacts_dir, logical_name)
            return self._paths[logical_name]

    def get(self, logical_name: str) -> Optional[sqlite3.Connection]:
        """The connection for this logical DB **on the calling thread**."""
        key = (threading.get_ident(), logical_name)
        with self._lock:
            if key in self._conns:
                return self._conns[key]
        # Resolve and open outside the lock: opening a file should not block
        # another thread that only wants a connection it already has.
        path = self.path(logical_name)
        conn = None
        if path:
            try:
                conn = open_ro(path)
            except sqlite3.Error as e:
                logger.warning("UBA: cannot open %s (%s): %s", logical_name, path, e)
                conn = None
        with self._lock:
            # Another call on this same thread may have won the race; keep the
            # first connection so the thread only ever has one per database.
            if key in self._conns:
                existing = self._conns[key]
                if conn is not None and conn is not existing:
                    try:
                        conn.close()
                    except sqlite3.Error:
                        pass
                return existing
            self._conns[key] = conn
        return conn

    def has_table(self, logical_name: str, table: str) -> bool:
        conn = self.get(logical_name)
        return bool(conn) and table_exists(conn, table)

    def has_column(self, logical_name: str, table: str, column: str) -> bool:
        """Whether a case is new enough to carry this column.

        An extractor that selects a column an older case does not have gets an
        empty result and a log line, because _rows() catches the error - so the
        whole behaviour disappears from the report with nothing on screen to
        say why. Asking first is the difference between a degraded answer and
        a missing one.
        """
        conn = self.get(logical_name)
        if not conn or not table_exists(conn, table):
            return False
        try:
            return column in table_columns(conn, table)
        except sqlite3.Error:
            return False

    def cleanup_thread_connections(self, thread_id: Optional[int] = None):
        """Close the connections belonging to one thread. Defaults to this one.

        A worker calls this as it finishes, so its connections go away with it
        rather than lingering until the pool is dropped - the same contract as
        ``timeline/data/query_worker.py``, which calls the timeline manager's
        method of this name at the end of ``run()``.
        """
        if thread_id is None:
            thread_id = threading.get_ident()
        with self._lock:
            keys = [k for k in self._conns if k[0] == thread_id]
            conns = [self._conns.pop(k) for k in keys]
        mine = threading.get_ident() == thread_id
        for conn in conns:
            if conn is None:
                continue
            if not mine:
                # Closing another thread's connection raises ProgrammingError.
                # Dropping the reference is the whole job: CPython finalises it
                # when the last reference goes.
                continue
            try:
                conn.close()
            except sqlite3.Error as e:
                logger.warning("UBA: closing a pooled connection failed: %s", e)

    def close(self):
        """Release every connection this pool holds, from any thread.

        Connections owned by other threads are dropped rather than closed. The
        previous version called ``close()`` on them inside ``except
        sqlite3.Error``, which also catches ProgrammingError - so every
        cross-thread close failed silently and the handles leaked while the
        code looked like it was tidying up.
        """
        with self._lock:
            keys = list(self._conns)
            conns = [self._conns.pop(k) for k in keys]
        me = threading.get_ident()
        for (thread_id, name), conn in zip(keys, conns):
            if conn is None:
                continue
            if thread_id != me:
                logger.debug("UBA: leaving %s to thread %s to finalise", name, thread_id)
                continue
            try:
                conn.close()
            except sqlite3.Error as e:
                logger.warning("UBA: closing %s failed: %s", name, e)


def data_status(artifacts_dir: str) -> dict:
    """Summarize which parsed databases exist and how much data they hold.

    Drives the React empty-state: if no known database contains rows, the UI
    tells the user to parse the computer data or add artifact evidence first.
    """
    status = {"artifacts_dir": artifacts_dir, "databases": {}, "parsed_data_available": False}
    if not artifacts_dir or not os.path.isdir(artifacts_dir):
        return status
    for name in DB_CANDIDATES:
        path = resolve_db_path(artifacts_dir, name)
        entry = {"present": path is not None, "path": path, "tables": {}, "total_rows": 0}
        if path:
            try:
                conn = open_ro(path)
                try:
                    for table in KEY_TABLES.get(name, []):
                        if table_exists(conn, table):
                            n = row_count(conn, table)
                            entry["tables"][table] = n
                            entry["total_rows"] += n
                finally:
                    conn.close()
            except sqlite3.Error as e:
                logger.warning("UBA: status probe failed for %s: %s", path, e)
        status["databases"][name] = entry
        if entry["total_rows"] > 0:
            status["parsed_data_available"] = True
    return status
