"""Insert only the rows a table does not already hold - and count both.

Running the live parser twice on the same machine must ADD what is new and
nothing else. Three parsers duplicated every row instead (AmCache's existence
check compared raw value names with column names and never matched; SRUM only
removed duplicates inside one run; the MFT's child tables were a plain
INSERT), and two deleted the previous run's rows to avoid it (Event Logs
dropped their tables, Browsers cleared each profile), losing what had since
rolled out of the live source.

``insert_new`` writes a row only when no row with the same identity exists:

    INSERT INTO t(...) SELECT ?, ... WHERE NOT EXISTS
        (SELECT 1 FROM t WHERE k1 IS ? AND k2 IS ? ...)

``IS`` makes NULL equal NULL (``=`` never matches a NULL, so a guard written
with ``=`` lets every row with an empty column through again). The identity
columns get a plain - not UNIQUE - index: a UNIQUE index cannot be created on a
table that already holds duplicates, and cases parsed before this change keep
theirs (the investigator's choice), while new rows are still checked.

No bookkeeping column is added: ``parsed_at`` stays the only one, and it is
never part of an identity (it differs on every run by design).

Counts: ``parsed`` rows offered, ``inserted`` rows written, ``duplicates`` =
the difference. A ``Tally`` sums them per table for the run's result dict,
which Parse Status, the loading dialog and the custody record read.
"""
import re
import sqlite3

_SAFE = re.compile(r"[^0-9A-Za-z_]+")


def _q(name):
    return '"%s"' % str(name).replace('"', '""')


def identity_index_name(table):
    return "idx_%s_identity" % _SAFE.sub("_", str(table))


# Identity indexes this process created, "<db file>: <index> on <table>(cols)".
# Adding one changes the case database, so the run says so: each Tally hands
# back the ones created since it started (its result's "indexes_created"),
# and that list reaches Parse Status and the custody record.
CREATED_INDEXES = []


def _db_file(conn):
    try:
        row = conn.execute("PRAGMA database_list").fetchone()
        return (row[2] if row else "") or ":memory:"
    except sqlite3.Error:
        return "?"


def ensure_identity_index(conn, table, key_cols, name=None):
    """A plain index on the identity columns (created once, kept)."""
    if not key_cols:
        return None
    name = name or identity_index_name(table)
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
                          (name,)).fetchone()
    if exists:
        return name
    conn.execute("CREATE INDEX IF NOT EXISTS %s ON %s (%s)"
                 % (_q(name), _q(table), ", ".join(_q(c) for c in key_cols)))
    import os
    CREATED_INDEXES.append("%s: %s on %s(%s)" % (
        os.path.basename(_db_file(conn)), name, table, ", ".join(key_cols)))
    return name


def table_is_empty(conn, table):
    try:
        return conn.execute("SELECT 1 FROM %s LIMIT 1" % _q(table)).fetchone() is None
    except sqlite3.Error:
        return True


class Tally:
    """Per-table parsed / inserted / duplicates for one run."""

    def __init__(self):
        self.tables = {}
        self._indexes_from = len(CREATED_INDEXES)

    def indexes_created(self):
        return list(CREATED_INDEXES[self._indexes_from:])

    def add(self, table, parsed, inserted):
        t = self.tables.setdefault(table, {"parsed": 0, "inserted": 0, "duplicates": 0})
        t["parsed"] += int(parsed)
        t["inserted"] += int(inserted)
        t["duplicates"] += max(0, int(parsed) - int(inserted))

    def skipped(self, table, n=1):
        """Rows a parser's own guard skipped as already present."""
        self.add(table, n, 0)

    def inserted(self, table, n=1):
        self.add(table, n, n)

    def totals(self):
        out = {"parsed": 0, "inserted": 0, "duplicates": 0}
        for t in self.tables.values():
            for k in out:
                out[k] += t[k]
        return out

    def as_result(self, primary=None, **extra):
        """The dict a parser returns: records / inserted / duplicates + per table.

        ``primary`` names the table whose rows ARE the records (the MFT's
        mft_records): the counts are that table's, and the sum over every
        table is kept as ``rows``. Summed, one MFT record read as five or six
        (3.3 M records reported as 18 M)."""
        tot = self.totals()
        if primary is not None:
            p = self.tables.get(primary, {"parsed": 0, "inserted": 0, "duplicates": 0})
            res = {"records": p["parsed"], "inserted": p["inserted"],
                   "duplicates": p["duplicates"], "rows": tot["parsed"],
                   "tables": {k: dict(v) for k, v in self.tables.items()}}
        else:
            res = {"records": tot["parsed"], "inserted": tot["inserted"],
                   "duplicates": tot["duplicates"],
                   "tables": {k: dict(v) for k, v in self.tables.items()}}
        if self.indexes_created():
            res["indexes_created"] = self.indexes_created()
        res.update(extra)
        return res


def insert_new(conn, table, columns, rows, key_cols=None, tally=None, fast_if_empty=False):
    """Insert the rows whose identity is not in ``table`` yet. Returns inserted.

    ``columns`` names every value in a row; ``key_cols`` (default: all of
    them) is the identity. Rows inside the same batch are checked against each
    other too: each executemany step sees the rows written before it.
    ``fast_if_empty``: when the table holds nothing yet, a plain INSERT -
    for very large first parses (the MFT) whose rows cannot repeat inside
    one run.
    """
    rows = [tuple(r) for r in rows]
    if not rows:
        return 0
    cols = list(columns)
    keys = list(key_cols or cols)
    kidx = [cols.index(k) for k in keys]
    col_sql = ", ".join(_q(c) for c in cols)
    marks = ", ".join("?" for _ in cols)
    before = conn.total_changes
    if fast_if_empty and table_is_empty(conn, table):
        conn.executemany("INSERT INTO %s (%s) VALUES (%s)" % (_q(table), col_sql, marks), rows)
    else:
        where = " AND ".join("%s IS ?" % _q(k) for k in keys)
        sql = ("INSERT INTO %s (%s) SELECT %s WHERE NOT EXISTS (SELECT 1 FROM %s WHERE %s)"
               % (_q(table), col_sql, marks, _q(table), where))
        conn.executemany(sql, [r + tuple(r[i] for i in kidx) for r in rows])
    inserted = conn.total_changes - before
    if tally is not None:
        tally.add(table, len(rows), inserted)
    return inserted


def row_exists(conn, table, values):
    """NULL-safe existence check for a single row ({column: value})."""
    where = " AND ".join("%s IS ?" % _q(k) for k in values)
    return conn.execute("SELECT 1 FROM %s WHERE %s LIMIT 1" % (_q(table), where),
                        tuple(values.values())).fetchone() is not None
