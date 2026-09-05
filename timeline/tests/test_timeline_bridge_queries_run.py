r"""Every SQL statement in the timeline bridge must run against a real case.

The React timeline gets everything through `timeline_bridge.py`, and each
artifact is one hand-written statement. A statement naming a column the parser
renamed raises inside the bridge's own `try/except`, which logs a line and
returns `[]` - so the panel shows an empty section and nothing anywhere reads
as an error. Three statements were in that state when this file was written:

  * `recent_docs_sql` selected `file_name`, which RecentDocs has never had;
  * `auto_sql` read `Auto`, an abandoned draft of WindowsUpdateInfo that
    nothing has ever inserted into;
  * one `bam_sql` variant selected `run_count`, which BAM does not record.

and six more ran but returned nothing across the entire date range, because
they were keyed on `access_date` - a column the MRU parser deliberately leaves
empty, since assigning the key's write time to whichever entry looks newest
would be an invention.

This needs a parsed case and SKIPS without one. That is the weaker half of the
pair on purpose: the structural checks in
`test_artifact_map_is_consistent.py` run with no evidence at all.

Point it at a specific case with CROW_EYE_CASE_ROOT.
"""
import io
import os
import re
import sqlite3
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

BRIDGE = os.path.join(REPO, "timeline", "timeline_bridge.py")

# The whole range, so "returned nothing" means the query, not the window.
WIDE = ("1970-01-01 00:00:00", "2099-01-01 00:00:00")

# Columns whose name says "time" without being one.
TIME_ISH = re.compile(
    r"(^|_)(time|date|when|written|executed|created|modified|accessed|"
    r"deleted|installed|connected|removed|registered|run|completed|changed|"
    r"stamp|last_write)", re.I)
NOT_A_TIME = frozenset((
    "parsed_at",                    # when the parser ran
    "analyzing_date",               # ditto, under an older name
    "time_basis", "timezone", "time_zone_name",
    "run_context", "last_result", "run_count", "modified_count",
    "scheduled_install_time",       # Windows Update's policy HOUR, 0-23
    "focus_time",                   # a duration, stored as "0.00s"
))

# `timestamp` means opposite things in different databases, and deciding by the
# NAME is exactly the mistake this codebase keeps making. In srum_data.db and
# USN_journal.db it is the event time. In registry_data.db it is the legacy
# spelling of `parsed_at` - an archived case has
# `UserAssist.timestamp = 2026-02-16T02:14:02.574145` on every row, to the
# microsecond, which is when the parser ran and not when anything happened.
# Counting it as a real time made this check report five perfectly good
# mappings as mis-keyed.
PARSE_TIME_BY_DB = {
    "registry_data.db": {"timestamp"},
    "shimcache.db": {"parsed_timestamp"},
    "srum_data.db": {"parse_timestamp"},
}


# Mapped columns the parser fills only for a subset of records, so "empty on
# every row" is expected on some machines and says nothing about the mapping.
# Named here, one line each with the reason, rather than being quietly tolerated
# by a rule - a rule broad enough to excuse these would excuse the next
# `access_date` too.
KNOWN_EMPTY = {
    # `SRUM_Claw` writes this only where the SRUM record carries a battery
    # state transition. Empty on every desktop, populated on a laptop.
    ("srum_energy_usage", "event_timestamp"),
}


def _populated_time_columns(conn, table, db_name=""):
    """Time-ish columns in `table` that hold a value on at least one row.

    This is what separates a broken mapping from an honest blank. A column
    empty on every row is only evidence of a mistake if some OTHER column in
    the same table is full - that is the `access_date` case exactly, where the
    MRU tables carry a populated `key_last_write` right beside the empty
    column the timeline was reading. A machine that has never checked for
    Windows updates has a WindowsUpdateInfo row with no times at all, and
    nothing about that is a bug.
    """
    try:
        cols = [r[1] for r in conn.execute('PRAGMA table_info("%s")' % table)]
    except sqlite3.Error:
        return []
    bookkeeping = PARSE_TIME_BY_DB.get(db_name, frozenset())
    out = []
    for c in cols:
        if not TIME_ISH.search(c) or c.lower() in NOT_A_TIME:
            continue
        if c.lower() in bookkeeping:
            continue
        try:
            n = conn.execute(
                'SELECT count(*) FROM "%s" WHERE "%s" IS NOT NULL '
                'AND trim("%s") <> "" AND "%s" <> 0' % (table, c, c, c)
            ).fetchone()[0]
        except sqlite3.Error:
            continue
        if n:
            out.append(c)
    return out


def _find_case_dir():
    """Newest directory holding a `registry_data.db`.

    CROW_EYE_CASE_ROOT is authoritative when set - not merely tried first. It
    used to be one root among several with the newest match winning, so a
    fixture written minutes later anywhere under TEMP could silently override
    the case the caller pointed at.
    """
    explicit = os.environ.get("CROW_EYE_CASE_ROOT")
    roots = [explicit] if explicit else [os.path.join(REPO, "cases"),
                                         os.environ.get("TEMP", "")]
    found = []
    for base in roots:
        if not base or not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            # pytest's own tmp dirs hold deliberately-broken fixtures, and a
            # synthetic case marks itself: one left behind by a failed cleanup
            # is NEWER than any real case, so it wins the `max()` below.
            if "pytest-of-" in dirpath:
                continue
            if "NOT_A_REAL_CASE" in files:
                continue
            if "registry_data.db" in files:
                p = os.path.join(dirpath, "registry_data.db")
                try:
                    found.append((os.path.getmtime(p), dirpath))
                except OSError:
                    pass
    return max(found)[1] if found else None


CASE = _find_case_dir()


# Columns the CURRENT parser writes. A case missing any of them was parsed by
# an older build, and every check in this file would then report the old
# parser's gaps as if they were mapping errors: `UserAssist.last_execution`
# blank on all 127 rows, `OpenSaveMRU.key_last_write` "no such column",
# Shellbags with only one of its three dates. None of that says anything about
# the map, and a check that fails against every archived case is a check
# nobody runs.
#
# `parsed_at` is the giveaway: the whole tree moved to it as the one
# bookkeeping column, and an older case still spells it `timestamp`.
_CURRENT_PARSER_SENTINELS = [
    ("registry_data.db", "UserAssist", "parsed_at"),
    ("registry_data.db", "OpenSaveMRU", "key_last_write"),
]


def _stale_case_reason():
    """Why this case predates the parser, or "" if it does not."""
    if CASE is None:
        return ""
    for db_name, table, column in _CURRENT_PARSER_SENTINELS:
        path = os.path.join(CASE, db_name)
        if not os.path.exists(path):
            continue
        conn = sqlite3.connect(
            "file:" + path.replace("\\", "/") + "?mode=ro", uri=True)
        try:
            cols = [r[1] for r in
                    conn.execute('PRAGMA table_info("%s")' % table)]
        except sqlite3.Error:
            continue
        finally:
            conn.close()
        if cols and column not in cols:
            return ("%s has no %s.%s, so this case was parsed by an older "
                    "build; re-parse it to run the case-dependent checks"
                    % (db_name, table, column))
    return ""


STALE = _stale_case_reason()
SKIP_CASE_CHECKS = CASE is None or bool(STALE)
SKIP_WHY = ("no parsed case found; set CROW_EYE_CASE_ROOT to run these"
            if CASE is None else STALE)


def _sql_blocks():
    """Every `name = \"\"\"...\"\"\"` SELECT in the bridge, with its database.

    The database comes from the `_query_db("<name>", ...)` call that follows,
    which is how the bridge itself decides.
    """
    src = io.open(BRIDGE, encoding="utf-8", errors="replace").read()
    blocks = []
    for m in re.finditer(
            r'(\w+)\s*=\s*"""(.*?)"""(.*?)(?=\n\s*\w+\s*=\s*"""|\Z)', src, re.S):
        name, sql, tail = m.group(1), m.group(2), m.group(3)
        if "SELECT" not in sql.upper():
            continue
        db = re.search(r'_query(?:_db|_time_sliced)\(\s*"([^"]+)"', tail)
        db_name = db.group(1) if db else "registry_data.db"

        # One statement is a `.format()` template covering every key-time
        # table. Expanding it here is the whole point: a template run once
        # against one table proves nothing about the other twenty-two, and
        # each names its own label, path and time columns - `local_groups`
        # has no `key_path` at all.
        # `_mapped_query`'s own template. Its placeholders are filled from the
        # map per table, so it is exercised by `MapDrivenQueriesRun` below
        # against every table that uses it - running the template itself would
        # only prove that a format string is a format string.
        if "{selected}" in sql:
            continue

        if "{table}" in sql:
            from timeline.timeline_bridge import TimelineBridge
            bridge = TimelineBridge.__new__(TimelineBridge)
            for (label, table, name_col, time_col, path_col,
                 basis) in bridge._key_time_sources:
                blocks.append((
                    "%s[%s]" % (name, table),
                    sql.format(name=name_col, table=table, time=time_col,
                               path=path_col or "''",
                               basis=basis or "'key upper bound'",
                               label=label.replace("'", "")),
                    db_name))
            continue

        blocks.append((name, sql, db_name))
    return blocks


@unittest.skipIf(SKIP_CASE_CHECKS, SKIP_WHY)
class BridgeQueriesRun(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.blocks = _sql_blocks()

    def _run(self, sql, db_name):
        path = os.path.join(CASE, db_name)
        if not os.path.exists(path):
            return None
        conn = sqlite3.connect(
            "file:" + path.replace("\\", "/") + "?mode=ro", uri=True)
        try:
            # `PARSABLE_NUM` is the bridge's own function, registered on every
            # connection it opens. Without it three statements raise here and
            # nowhere else, which would be the test lying about the product.
            conn.create_function("PARSABLE_NUM", 1, lambda v: v)
            params = [WIDE[i % 2] for i in range(sql.count("?"))]
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def test_the_scan_found_the_statements(self):
        # A regex that quietly matches nothing makes every check below pass.
        self.assertGreater(
            len(self.blocks), 25,
            "only %d SQL statements were found in the bridge - the scan is "
            "broken, and the checks below are passing by finding nothing"
            % len(self.blocks))

    def test_every_statement_executes(self):
        """`no such column` is drift. `no such table` is usually an old case.

        A case parsed by an earlier build has none of the tables added since -
        no ScheduledTasks, no registry_value_changes, no SECURITY-hive tables.
        Reporting those as broken queries makes the check cry wolf against
        every archived case, and a check that cries wolf gets ignored. That the
        parser writes the table is already proved structurally, from source, by
        `test_artifact_map_is_consistent`; what only a case can prove is that
        the COLUMN names still line up.
        """
        broken, absent = [], []
        for name, sql, db_name in self.blocks:
            try:
                self._run(sql, db_name)
            except Exception as exc:
                if "no such table" in str(exc):
                    absent.append("%s (%s)" % (name, db_name))
                    continue
                broken.append("%s (%s): %s" % (name, db_name, exc))
        if absent:
            print("\n  tables absent from this case (older parse), skipped: %s"
                  % ", ".join(absent))
        self.assertEqual(
            [], broken,
            "these queries raise inside the bridge's try/except, so the "
            "timeline shows an empty section and reports nothing:\n  "
            + "\n  ".join(broken))

    def test_no_statement_is_empty_across_all_of_time(self):
        """A query returning nothing over 1970-2099 is keyed on a blank column.

        Skipped where the table has no populated time column at all: a machine
        with no scheduled tasks, or one that has never checked for updates, is
        not a broken query. Failed where a populated time column is sitting
        right there - which is the `access_date` mistake exactly.
        """
        empty = []
        for name, sql, db_name in self.blocks:
            try:
                rows = self._run(sql, db_name)
            except Exception:
                continue        # the check above owns this
            if rows is None or rows:
                continue        # absent database, or the query works
            have = self._other_populated_times(sql, db_name)
            if have:
                empty.append("%s (%s): the table has %s populated"
                             % (name, db_name, ", ".join(have)))
        self.assertEqual(
            [], empty,
            "these queries run and return nothing across the whole of time, "
            "while a filled time column sits beside the one they read:\n  "
            + "\n  ".join(empty))

    def _other_populated_times(self, sql, db_name):
        m = re.search(r"FROM\s+(\w+)", sql, re.I)
        if not m:
            return []
        table = m.group(1)
        path = os.path.join(CASE, db_name)
        conn = sqlite3.connect(
            "file:" + path.replace("\\", "/") + "?mode=ro", uri=True)
        try:
            named = set(re.findall(r"\w+", sql))
            return [c for c in _populated_time_columns(conn, table, db_name)
                    if c not in named]
        finally:
            conn.close()


@unittest.skipIf(SKIP_CASE_CHECKS, SKIP_WHY)
class MapDrivenQueriesRun(unittest.TestCase):
    """Every table the bridge queries through the map must actually query.

    `_mapped_query` builds its column list from `artifact_map`, so a mapping
    naming a column the parser renamed becomes a query that raises - swallowed
    by the bridge's try/except, shown as an empty section. Reading the template
    proves nothing; each table has to be run.
    """

    def test_each_map_driven_table_executes(self):
        import re as _re
        from timeline.timeline_bridge import TimelineBridge
        from timeline.data import artifact_map as _am

        src = io.open(BRIDGE, encoding="utf-8", errors="replace").read()
        calls = set(_re.findall(
            r'_mapped_rows\(\s*\n?\s*"([^"]+)",\s*"(\w+)",\s*"(\w+)"', src))
        # `getEventLogData` loops the three log tables rather than naming them.
        for t in _am.EVENT_LOG_TABLES:
            calls.add(("Log_Claw.db", "Logs", t))

        self.assertGreater(
            len(calls), 4,
            "only %d map-driven calls found; the scan is broken" % len(calls))

        bridge = TimelineBridge(CASE)
        broken, absent, ran = [], [], []
        for db_name, artifact, table in sorted(calls):
            if not os.path.exists(os.path.join(CASE, db_name)):
                continue
            sql, n_pairs, cols = bridge._mapped_query(artifact, table)
            if not sql:
                broken.append("%s.%s: the map defines no record time for it"
                              % (artifact, table))
                continue
            try:
                self._run(sql, db_name, n_pairs)
                ran.append("%s.%s" % (db_name, table))
            except Exception as exc:
                if "no such table" in str(exc):
                    absent.append(table)
                    continue
                broken.append("%s.%s: %s" % (db_name, table, exc))
        if absent:
            print("\n  absent from this case, skipped: %s" % ", ".join(absent))
        self.assertEqual([], broken, "\n  ".join([""] + broken))
        self.assertGreater(len(ran), 3, "almost nothing ran: %s" % ran)

    def _run(self, sql, db_name, n_pairs):
        path = os.path.join(CASE, db_name)
        conn = sqlite3.connect(
            "file:" + path.replace("\\", "/") + "?mode=ro", uri=True)
        try:
            conn.create_function("PARSABLE_NUM", 1, lambda v: v)
            conn.create_function("NORM_TS", 1, lambda v: v)
            return conn.execute(sql, tuple(WIDE * n_pairs)).fetchall()
        finally:
            conn.close()


@unittest.skipIf(SKIP_CASE_CHECKS, SKIP_WHY)
class MappingsHaveDataInThisCase(unittest.TestCase):
    """Report a mapped column that is empty on every row of a real case.

    Not every empty column is a bug - a machine with no USB history has none -
    so this reports rather than judging, and fails only where the table itself
    has rows and the mapped column is blank in all of them.
    """

    def test_mapped_columns_are_not_universally_blank(self):
        from timeline.data import artifact_map as M

        blank = []
        for artifact, entries in M.TIMESTAMP_MAPPINGS.items():
            db_name = M.ARTIFACT_DB_MAPPING.get(artifact)
            path = os.path.join(CASE, db_name or "")
            if not db_name or not os.path.exists(path):
                continue
            conn = sqlite3.connect(
                "file:" + path.replace("\\", "/") + "?mode=ro", uri=True)
            try:
                for entry in entries:
                    table, column = entry[0], entry[1]
                    if (table, column) in KNOWN_EMPTY:
                        continue
                    try:
                        n = conn.execute(
                            'SELECT count(*) FROM "%s"' % table).fetchone()[0]
                        if not n:
                            continue
                        filled = conn.execute(
                            'SELECT count(*) FROM "%s" WHERE "%s" IS NOT NULL '
                            'AND trim("%s") <> ""'
                            % (table, column, column)).fetchone()[0]
                    except sqlite3.Error as exc:
                        # A table this case does not have is an older parse,
                        # not a broken mapping - the structural check already
                        # proved the parser writes it. A missing COLUMN is real.
                        if "no such table" in str(exc):
                            continue
                        blank.append("%s.%s.%s: %s"
                                     % (artifact, table, column, exc))
                        continue
                    if filled:
                        continue
                    # Blank is only evidence of a mistake when a populated
                    # time column sits beside it. WindowsUpdateInfo on a
                    # machine that has never checked for updates has none,
                    # and that is not a broken mapping.
                    beside = [c for c in _populated_time_columns(conn, table,
                                                                 db_name)
                              if c != column]
                    if beside:
                        blank.append(
                            "%s.%s.%s: blank on all %d rows, while %s is "
                            "populated" % (artifact, table, column, n,
                                           ", ".join(beside)))
            finally:
                conn.close()
        self.assertEqual(
            [], blank,
            "these columns are mapped and plot nothing:\n  " + "\n  ".join(blank))


if __name__ == "__main__":
    unittest.main(verbosity=2)
