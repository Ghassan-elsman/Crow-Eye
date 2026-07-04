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
from typing import Dict, List, Optional

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
    """Lazy pool of read-only connections keyed by logical DB name.

    Missing databases are remembered as None so rules can degrade cleanly
    without repeated filesystem probing.
    """

    def __init__(self, artifacts_dir: str):
        self.artifacts_dir = artifacts_dir
        self._conns: Dict[str, Optional[sqlite3.Connection]] = {}
        self._paths: Dict[str, Optional[str]] = {}

    def path(self, logical_name: str) -> Optional[str]:
        if logical_name not in self._paths:
            self._paths[logical_name] = resolve_db_path(self.artifacts_dir, logical_name)
        return self._paths[logical_name]

    def get(self, logical_name: str) -> Optional[sqlite3.Connection]:
        if logical_name in self._conns:
            return self._conns[logical_name]
        path = self.path(logical_name)
        conn = None
        if path:
            try:
                conn = open_ro(path)
            except sqlite3.Error as e:
                logger.warning("UBA: cannot open %s (%s): %s", logical_name, path, e)
                conn = None
        self._conns[logical_name] = conn
        return conn

    def has_table(self, logical_name: str, table: str) -> bool:
        conn = self.get(logical_name)
        return bool(conn) and table_exists(conn, table)

    def close(self):
        for conn in self._conns.values():
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
        self._conns.clear()


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
