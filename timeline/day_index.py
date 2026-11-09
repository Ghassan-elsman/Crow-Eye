"""A one-time day map of a large table's time columns, so a timeline day
click reads the rows of that day instead of scanning the whole table.

Why: the MFT/USN lane asks for the records with ANY of nine time columns in
the day. Six of the nine have no index, so the question was a full scan of
mft_usn_correlated on every day click: 3.9 M rows, a 3 GB file, 12-14 s even
with the file cached (23 s for the lane in all). An index per column would
cost about 21 s and 97 MB each, seven of them. One scan builds this map
instead (about 50 s and 100 MB for 3.9 M rows, once per case), and a day is
then a lookup: 0.03 s for the same 67,092 rows.

The map lives beside the case, ``<case>/Timeline/day_index.db``, the way the
UBA keeps ``<case>/UBA/uba_events.db``: nothing is written into the parsers'
databases. It is stamped with the source database's size and mtime (and its
WAL's), and a stamp that no longer matches is never read: a re-parse that
changes the table rebuilds it.

Days are whole UTC days numbered from 1970-01-01. A window that is part of a
day gets that day's rows, and the caller keeps the ones whose times fall in
the window.
"""

import datetime as _dt
import json
import logging
import os
import sqlite3
import threading

logger = logging.getLogger(__name__)

DIRNAME = "Timeline"
FILENAME = "day_index.db"
FORMAT = 1
# Below this the full scan is quick enough that a map would not pay for itself.
MIN_ROWS = 300_000

_EPOCH = _dt.date(1970, 1, 1)
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_BUILDING = set()


def map_path(artifacts_dir):
    """``<case>/Timeline/day_index.db`` for a case's Target_Artifacts folder."""
    base = os.path.abspath(artifacts_dir or ".")
    if os.path.basename(base.rstrip("\\/")).lower() == "target_artifacts":
        base = os.path.dirname(base.rstrip("\\/"))
    return os.path.join(base, DIRNAME, FILENAME)


def day_number(text):
    """'2026-10-30...' -> days since 1970-01-01, or None."""
    try:
        return (_dt.date.fromisoformat(str(text)[:10]) - _EPOCH).days
    except ValueError:
        return None


def _uri(path, mode=None):
    """A SQLite URI for a file path: percent-encoded, so a space or a '#' in
    a case folder's name cannot cut the path short."""
    from urllib.request import pathname2url
    uri = "file:" + pathname2url(os.path.abspath(path))
    return uri + ("?mode=%s" % mode if mode else "")


def _sig(path):
    # Size only. A re-parse grows the source database; merely opening and
    # reading the case bumps mtime and the -wal file (a loader checkpoints the
    # WAL on close), which used to rebuild the day index on every open.
    try:
        return [os.stat(path).st_size]
    except OSError:
        return [0]


def _stamp(source_db, table, columns):
    return json.dumps({"format": FORMAT, "source": os.path.basename(source_db),
                       "table": table, "columns": list(columns),
                       "sig": _sig(source_db)}, sort_keys=True)


def _lock(path):
    key = os.path.normcase(os.path.abspath(path))
    with _LOCKS_GUARD:
        lk = _LOCKS.get(key)
        if lk is None:
            lk = _LOCKS[key] = threading.Lock()
        return lk


def _key(table):
    return "days_" + "".join(ch for ch in table if ch.isalnum() or ch == "_")


def ready(artifacts_dir, source_db, table, columns):
    """True when the map for this table is built and still matches its source."""
    path = map_path(artifacts_dir)
    if not os.path.exists(path):
        return False
    try:
        conn = sqlite3.connect(_uri(path, "ro"), uri=True)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key = ?",
                               (_key(table),)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return bool(row) and row[0] == _stamp(source_db, table, columns)


def rowids(artifacts_dir, table, first_day, last_day):
    """Row ids with any mapped time on a day in [first_day, last_day]."""
    path = map_path(artifacts_dir)
    conn = sqlite3.connect(_uri(path, "ro"), uri=True)
    try:
        return sorted({r[0] for r in conn.execute(
            'SELECT rid FROM "%s" WHERE day BETWEEN ? AND ?' % _key(table),
            (first_day, last_day))})
    finally:
        conn.close()


def build(artifacts_dir, source_db, table, columns):
    """Build (or rebuild) the map for one table. One scan of the source: each
    row's nine times unpivoted to the distinct days they touch, then written
    in key order into a WITHOUT ROWID table. Returns True when it is ready."""
    path = map_path(artifacts_dir)
    with _lock(path):
        if ready(artifacts_dir, source_db, table, columns):
            return True
        stamp = _stamp(source_db, table, columns)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        key = _key(table)
        # Opened as a URI so the source can be attached read-only.
        conn = sqlite3.connect(_uri(path), uri=True)
        try:
            for p in ("journal_mode=WAL", "synchronous=NORMAL", "temp_store=FILE",
                      "cache_size=-200000"):
                conn.execute("PRAGMA " + p)
            conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("ATTACH DATABASE ? AS src", (_uri(source_db, "ro"),))
            cases = " ".join('WHEN %d THEN "%s"' % (i + 1, c) for i, c in enumerate(columns))
            picks = ",".join("(%d)" % (i + 1) for i in range(len(columns)))
            conn.execute("DROP TABLE IF EXISTS temp.raw")
            conn.execute(
                "CREATE TEMP TABLE raw AS SELECT DISTINCT "
                "CAST(julianday(substr(d, 1, 10)) - 2440587.5 AS INTEGER) AS day, rid FROM "
                "(SELECT t.rowid AS rid, CASE k.column1 %s END AS d "
                'FROM src."%s" AS t, (VALUES %s) AS k) WHERE d >= \'1601\''
                % (cases, table, picks))
            with conn:
                conn.execute('DROP TABLE IF EXISTS "%s"' % key)
                conn.execute('CREATE TABLE "%s" (day INTEGER NOT NULL, rid INTEGER NOT NULL, '
                             'PRIMARY KEY (day, rid)) WITHOUT ROWID' % key)
                conn.execute('INSERT INTO "%s" SELECT day, rid FROM temp.raw '
                             'WHERE day IS NOT NULL ORDER BY day, rid' % key)
                conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, stamp))
            conn.execute("DROP TABLE IF EXISTS temp.raw")
            conn.execute("DETACH DATABASE src")
        finally:
            conn.close()
        # The source changed while it was read: the stamp written was taken
        # before the scan, so it no longer matches and the next use rebuilds.
        return ready(artifacts_dir, source_db, table, columns)


def build_in_background(artifacts_dir, source_db, table, columns):
    """Start build() on a daemon thread unless one is running or the map is
    ready. Small tables are left to the scan."""
    path = map_path(artifacts_dir)
    tag = (os.path.normcase(path), table)
    if tag in _BUILDING or ready(artifacts_dir, source_db, table, columns):
        return False
    try:
        conn = sqlite3.connect(_uri(source_db, "ro"), uri=True)
        try:
            top = conn.execute('SELECT MAX(rowid) FROM "%s"' % table).fetchone()[0] or 0
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    if top < MIN_ROWS:
        return False
    _BUILDING.add(tag)

    def run():
        try:
            build(artifacts_dir, source_db, table, columns)
            logger.info("Timeline day map ready for %s (%s)", table, path)
        except Exception as exc:  # the scan is still there; never fatal
            logger.warning("Timeline day map for %s not built: %s", table, exc)
        finally:
            _BUILDING.discard(tag)

    threading.Thread(target=run, name="timeline-day-map", daemon=True).start()
    return True
