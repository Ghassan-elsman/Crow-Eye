r"""Database Search must reach every database in the case, not a list of names.

The dialog used to build its tree by iterating a hard-coded
`DATABASE_CATEGORIES` and keeping only databases whose name appeared in one of
its five lists. Everything else - every database the investigator imported,
every third-party export dropped beside the native ones - was discovered,
enhanced, and then dropped before it reached the tree. It could not be checked,
so it was never searched, and nothing anywhere said so. `DatabaseManager` had
been labelling those `Imported Evidence` and `Custom/Other Artifacts` the whole
time; nothing read the label.

Two more things this file holds the line on:

  * one physical file is READ once per search. Six configured names -
    jumplist, eventlog, shellbags, userassist, muicache, bam_dam - resolve to
    the one `Log_Claw.db`, so its 43,802 rows were read six times and every hit
    reported six times.
  * the time filter's idea of a timestamp column agrees with
    `timeline/data/artifact_map.py`. A column it does not recognise means the
    whole table is silently skipped from a time-filtered search.

Everything here builds its own case out of empty SQLite files, so it runs with
no evidence on the machine.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from data.database_manager import DatabaseManager           # noqa: E402
from data.timestamp_detector import TimestampDetector       # noqa: E402
from timeline.data import artifact_map as M                 # noqa: E402


def _close_everything():
    """Let Windows delete the fixture.

    `DatabaseManager` and `DatabaseDiscoveryManager` cache open connections,
    and Windows refuses to unlink a file another handle still holds - so a
    temp-directory teardown fails with PermissionError while every assertion
    in the test passed. Close them before the directory goes.
    """
    import gc
    import sqlite3 as _sqlite
    from data.database_manager import DatabaseManager as _DM
    from data.database_discovery_manager import DatabaseDiscoveryManager as _DD

    for obj in gc.get_objects():
        try:
            if isinstance(obj, _DM):
                obj.close_all()
            elif isinstance(obj, _DD):
                obj.close()
        except Exception:
            pass
    # Anything still holding a raw connection - a probe, a loader, a manager
    # already unreachable but not yet finalised.
    gc.collect()
    for obj in gc.get_objects():
        if isinstance(obj, _sqlite.Connection):
            try:
                obj.close()
            except Exception:
                pass
    gc.collect()


def _make_case(root):
    """A case with native artifacts, one imported database, and one custom.

    Table names matter: `DatabaseManager` resolves an unfound logical name by
    matching table signatures, so the natives have to look like themselves.
    """
    art = os.path.join(root, "Target_Artifacts")
    imported = os.path.join(art, "Imported_Evidence")
    os.makedirs(imported)

    # Say out loud that this is a fixture. Every case-dependent test in
    # the tree finds its case by walking %TEMP% for a `registry_data.db`,
    # and a synthetic one left behind by a failed cleanup is newer than
    # any real case - so it wins, and unrelated suites then fail against
    # four empty tables. Two of them did exactly that while this was
    # being written.
    with open(os.path.join(art, "NOT_A_REAL_CASE"), "w") as fh:
        fh.write("Synthetic fixture from data/tests. Case finders skip"
                 " any directory holding this file.\n")

    def db(path, tables):
        con = sqlite3.connect(path)
        for table, columns in tables:
            con.execute('CREATE TABLE "%s" (%s)' % (table, columns))
        con.commit()
        con.close()

    # The registry holds four artifacts that have their OWN entry in the
    # search tree - Shellbags, UserAssist, MUICache, BAM/DAM - which is what
    # the scoping is about, so they have to be here.
    db(os.path.join(art, "registry_data.db"), [
        ("registry_value_changes",
         "key_path TEXT, value_name TEXT, changed_at TEXT, parsed_at TEXT"),
        ("Shellbags", "file_name TEXT, modified_date TEXT"),
        ("UserAssist", "program_path TEXT, last_execution TEXT"),
        ("MUICache", "name TEXT, parsed_at TEXT"),
        ("BAM", "app_path TEXT, last_execution TEXT"),
        ("DAM", "app_path TEXT, last_execution TEXT"),
        ("FirewallRules", "rule_name TEXT, last_written TEXT"),
        ("winevt_channels", "channel TEXT, last_written TEXT"),
    ])
    db(os.path.join(art, "prefetch_data.db"),
       [("prefetch_data", "filename TEXT, last_executed TEXT")])
    db(os.path.join(art, "Log_Claw.db"), [
        ("SystemLogs", "EventID INTEGER, EventTimestampUTC TEXT"),
        ("SecurityLogs", "EventID INTEGER, EventTimestampUTC TEXT"),
        ("ApplicationLogs", "EventID INTEGER, EventTimestampUTC TEXT"),
    ])
    db(os.path.join(art, "LnkDB.db"), [
        ("LNK_Files", "Source_Name TEXT, Time_Access TEXT"),
        ("Automatic_JumpLists", "Source_Name TEXT, Time_Access TEXT"),
        ("Custom_JumpLists", "Source_Name TEXT, Time_Access TEXT"),
    ])
    db(os.path.join(art, "srum_data.db"),
       [("srum_application_usage", "app_name TEXT, timestamp TEXT")])
    # The two that used to be dropped.
    db(os.path.join(imported, "browser_history.db"),
       [("visits", "url TEXT, visit_time TEXT")])
    db(os.path.join(art, "vendor_export.db"),
       [("findings", "detail TEXT, seen_at TEXT")])
    return art


class EveryDiscoveredDatabaseReachesTheTree(unittest.TestCase):
    """The single assertion that would have caught the whole gap."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.case = _make_case(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        _close_everything()
        cls._tmp.cleanup()

    def _tree_names(self):
        """What the real grouping function puts in the tree."""
        from data.database_discovery_manager import DatabaseDiscoveryManager
        from ui.database_search_dialog import DatabaseSearchDialog

        enhanced = DatabaseDiscoveryManager(self.case).\
            discover_databases_with_metadata(
                verify_timestamps=False, sample_size=5, force_refresh=True)
        names = set()
        for _category, dbs in DatabaseSearchDialog._group_databases_for_tree(
                enhanced):
            names.update(d.name for d in dbs)
        return enhanced, names

    def test_the_case_fixture_is_discovered(self):
        # A discovery that finds nothing makes every check below vacuous.
        found = DatabaseManager(self.case).discover_databases()
        got = {d.path.name for d in found if d.exists}
        self.assertIn("browser_history.db", got,
                      "the fixture's imported database was not even discovered")
        self.assertIn("vendor_export.db", got)

    def test_nothing_discovered_is_dropped(self):
        enhanced, names = self._tree_names()
        dropped = sorted(d.name for d in enhanced if d.name not in names)
        self.assertEqual(
            [], dropped,
            "these databases are discovered and then dropped before they reach "
            "the tree, so they cannot be checked and are never searched: %s"
            % dropped)

    def test_imported_evidence_is_reachable(self):
        _enhanced, names = self._tree_names()
        self.assertIn(
            "browser_history.db", names,
            "an imported-evidence database cannot be selected, so evidence the "
            "investigator added by hand is unsearchable")

    def test_a_custom_database_is_reachable(self):
        _enhanced, names = self._tree_names()
        self.assertIn("vendor_export.db", names)

    def test_the_known_categories_still_come_first(self):
        """Those five names are how an examiner narrows a search."""
        from data.database_discovery_manager import DatabaseDiscoveryManager
        from ui.database_search_dialog import DatabaseSearchDialog as D

        enhanced = DatabaseDiscoveryManager(self.case).\
            discover_databases_with_metadata(
                verify_timestamps=False, sample_size=5, force_refresh=True)
        order = [c for c, _dbs in D._group_databases_for_tree(enhanced)]
        known = [c for c in order if c in D.DATABASE_CATEGORIES]
        self.assertEqual(
            known, [c for c in D.DATABASE_CATEGORIES if c in order],
            "the configured categories are out of their configured order")
        self.assertTrue(
            order.index("Imported Evidence") > max(
                order.index(c) for c in known),
            "Imported Evidence should follow the configured categories")


class EachArtifactPointsAtItsOwnData(unittest.TestCase):
    """ShellBags must search shellbags, not the Windows Event Log.

    `ALT_NAME_MAP` listed `Log_Claw.db` as the alternative file for almost
    everything, and it is tried BEFORE the table signatures - so five entries
    named after registry and LNK artifacts each resolved to the event log and
    offered its three tables. Ticking "ShellBags" searched the event log.
    """

    # (logical name, must offer, must not offer — a table in ANOTHER file,
    #  must not offer — a SIBLING table in the same file)
    #
    # Both negatives are needed and they catch different bugs. The cross-file
    # one catches the resolution being wrong (ShellBags landing on the event
    # log); the sibling one catches the entry being unscoped (ShellBags
    # offering every other registry table beside it), which the cross-file
    # check cannot see because those tables are not in that file either way.
    ARTIFACTS = [
        ("shellbags_data.db", "Shellbags", "SecurityLogs", "FirewallRules"),
        ("userassist_data.db", "UserAssist", "SecurityLogs", "FirewallRules"),
        ("muicache_data.db", "MUICache", "SecurityLogs", "FirewallRules"),
        ("bam_dam_data.db", "BAM", "SecurityLogs", "FirewallRules"),
        ("jumplist_data.db", "Automatic_JumpLists", "SecurityLogs",
         "LNK_Files"),
        ("lnk_data.db", "LNK_Files", "SecurityLogs", "Automatic_JumpLists"),
        # The event log owns its whole file, so it has no sibling to exclude.
        ("eventlog_data.db", "SecurityLogs", "Shellbags", None),
    ]

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.case = _make_case(cls._tmp.name)
        cls.found = {d.name: d for d in
                     DatabaseManager(cls.case).discover_databases()}

    @classmethod
    def tearDownClass(cls):
        _close_everything()
        cls._tmp.cleanup()

    def test_every_artifact_resolved_to_something(self):
        # A fixture where these do not resolve at all makes the rest vacuous.
        missing = [name for name, _t, _n, _s in self.ARTIFACTS
                   if not self.found.get(name)
                   or not self.found[name].exists]
        self.assertEqual([], missing,
                         "these did not resolve in the fixture: %s" % missing)

    def test_each_resolves_to_the_file_holding_its_artifact(self):
        wrong = []
        for name, must_have, _cross, _sibling in self.ARTIFACTS:
            info = self.found[name]
            con = sqlite3.connect(
                "file:" + str(info.path).replace("\\", "/") + "?mode=ro",
                uri=True)
            try:
                real = {t for (t,) in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                con.close()
            if must_have not in real:
                wrong.append("%s -> %s, which has no %s"
                             % (name, info.path.name, must_have))
        self.assertEqual([], wrong, "\n  ".join([""] + wrong))

    def test_each_offers_only_its_own_tables(self):
        wrong = []
        for name, must_have, cross, sibling in self.ARTIFACTS:
            offered = set(self.found[name].tables)
            if must_have not in offered:
                wrong.append("%s does not offer %s" % (name, must_have))
            if cross in offered:
                wrong.append("%s offers %s, which is in a different database"
                             % (name, cross))
            if sibling and sibling in offered:
                wrong.append("%s offers %s, a different artifact in the same "
                             "database - the entry is not scoped"
                             % (name, sibling))
        self.assertEqual([], wrong, "\n  ".join([""] + wrong))

    def test_scoping_did_not_leak_onto_a_whole_file(self):
        """`registry_data.db` owns its file and must keep all of its tables.

        Its own signatures (`registry_`, `reg_`, `hive_`) match a handful of
        the 124, so scoping every name by signature would gut the Registry
        entry - which is why membership is explicit.
        """
        registry = self.found["registry_data.db"]
        for table in ("Shellbags", "UserAssist", "BAM", "FirewallRules",
                      "winevt_channels", "registry_value_changes"):
            self.assertIn(
                table, registry.tables,
                "the Registry entry lost %s to artifact scoping" % table)

    def test_log_claw_is_only_the_event_log(self):
        """It is the alternative for exactly one logical name now."""
        others = sorted(n for n, alts in DatabaseManager.ALT_NAME_MAP.items()
                        if "Log_Claw.db" in alts and n != "eventlog_data.db")
        self.assertEqual(
            [], others,
            "these resolve to the Windows Event Log and are not event log "
            "artifacts: %s" % others)

    def test_a_legacy_lnk_case_still_resolves(self):
        """An archived case wrote `JLCE` / `Custom_JLCE` instead."""
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_case(tmp)
            os.remove(os.path.join(art, "LnkDB.db"))
            con = sqlite3.connect(os.path.join(art, "LnkDB.db"))
            con.execute("CREATE TABLE JLCE (Source_Name TEXT)")
            con.execute("CREATE TABLE Custom_JLCE (Source_Name TEXT)")
            con.commit()
            con.close()

            found = {d.name: d for d in
                     DatabaseManager(art).discover_databases()}
            self.assertIn(
                "JLCE", set(found["lnk_data.db"].tables),
                "an archived LNK case shows no tables, so its evidence is "
                "unreachable from that entry")
            _close_everything()


class OneReadPerFile(unittest.TestCase):
    """Six logical names, one `Log_Claw.db`, one read."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.case = _make_case(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        _close_everything()
        cls._tmp.cleanup()

    def test_the_fixture_really_does_collapse(self):
        """If nothing resolved to a shared file the check proves nothing."""
        found = [d for d in DatabaseManager(self.case).discover_databases()
                 if d.exists]
        by_path = {}
        for d in found:
            by_path.setdefault(str(d.path).lower(), []).append(d.name)
        shared = [v for v in by_path.values() if len(v) > 1]
        self.assertTrue(
            shared,
            "no file in the fixture resolves from several logical names, so "
            "the de-duplication below is untested")

    def test_unified_engine_reads_each_file_once(self):
        from data.unified_search_engine import UnifiedDatabaseSearchEngine

        found = [d for d in DatabaseManager(self.case).discover_databases()
                 if d.exists and d.accessible]
        kept, _tables, aliases = \
            UnifiedDatabaseSearchEngine._one_entry_per_file(found, None)
        paths = [str(d.path).lower() for d in kept]
        self.assertEqual(
            len(paths), len(set(paths)),
            "the same file is searched more than once: %s" % paths)
        self.assertLess(len(kept), len(found),
                        "nothing was collapsed, so nothing was proved")
        # Provenance survives: the survivor names the artifacts it stands for.
        multi = [v for v in aliases.values() if len(v) > 1]
        self.assertTrue(multi, "the alias list lost which artifacts collapsed")

    def test_a_collapsed_entry_is_named_for_its_file(self):
        """Which logical name survives is an accident of iteration order.

        An event log hit reported under "jumplist_data.db" tells the examiner
        something untrue about where the evidence is.
        """
        from data.unified_search_engine import UnifiedDatabaseSearchEngine

        found = [d for d in DatabaseManager(self.case).discover_databases()
                 if d.exists and d.accessible]
        kept, _t, aliases = \
            UnifiedDatabaseSearchEngine._one_entry_per_file(found, None)
        for info in kept:
            if len(aliases.get(info.name, [])) > 1:
                self.assertEqual(
                    os.path.basename(str(info.path)), info.name,
                    "a collapsed entry is reported under a logical name "
                    "rather than the file the evidence is actually in")

    def test_selected_tables_survive_the_collapse(self):
        """A table checked under ANY of the six names has to still be searched."""
        from data.unified_search_engine import UnifiedDatabaseSearchEngine

        found = [d for d in DatabaseManager(self.case).discover_databases()
                 if d.exists and d.accessible]
        by_path = {}
        for d in found:
            by_path.setdefault(str(d.path).lower(), []).append(d.name)
        shared = next(v for v in by_path.values() if len(v) > 1)
        tables = {shared[0]: ["SecurityLogs"], shared[1]: ["SystemLogs"]}
        kept, merged, _a = UnifiedDatabaseSearchEngine._one_entry_per_file(
            [d for d in found if d.name in shared[:2]], tables)
        self.assertEqual(1, len(kept))
        self.assertEqual(
            ["SecurityLogs", "SystemLogs"], merged[kept[0].name],
            "a table selected under one of the collapsed names was lost")

    def test_no_restriction_beats_a_restriction(self):
        """One name checked whole means every table, not the other's subset."""
        from data.unified_search_engine import UnifiedDatabaseSearchEngine

        found = [d for d in DatabaseManager(self.case).discover_databases()
                 if d.exists and d.accessible]
        by_path = {}
        for d in found:
            by_path.setdefault(str(d.path).lower(), []).append(d.name)
        shared = next(v for v in by_path.values() if len(v) > 1)
        kept, merged, _a = UnifiedDatabaseSearchEngine._one_entry_per_file(
            [d for d in found if d.name in shared[:2]],
            {shared[0]: ["SecurityLogs"]})
        self.assertNotIn(
            kept[0].name, merged,
            "one name was checked with no table restriction, so every table "
            "should be searched")

    def test_eye_search_service_dedupes_too(self):
        src = open(os.path.join(REPO, "eye", "services", "search_service.py"),
                   encoding="utf-8", errors="replace").read()
        self.assertIn(
            "resolve()", src,
            "Eye's cross-database search still iterates the logical list, so "
            "it reads the event log six times and the duplicates eat five "
            "other databases' share of max_total")


class TheTimeFilterAgreesWithTheMap(unittest.TestCase):
    """A column the detector misses means its whole table is skipped."""

    @classmethod
    def setUpClass(cls):
        cls.det = TimestampDetector()

    def test_every_mapped_time_column_is_recognised(self):
        missed = sorted({
            "%s.%s" % (e[0], e[1])
            for entries in M.TIMESTAMP_MAPPINGS.values() for e in entries
            if e[1] not in self.det.detect_timestamp_columns(e[0], [e[1]])})
        self.assertEqual(
            [], missed,
            "these columns are plotted by the timeline and unknown to the "
            "search's time filter, so their tables are silently dropped from "
            "every time-filtered search:\n  " + "\n  ".join(missed))

    def test_things_that_are_not_times_are_refused(self):
        for table, column, what in (
                ("UserAssist", "focus_time", 'a duration, "0.00s"'),
                ("BAM", "time_basis", 'a label, "key upper bound"'),
                ("WindowsUpdateInfo", "scheduled_install_time",
                 "an hour of day, 0-23"),
                ("BAM", "parsed_at", "when the parser ran"),
                ("ScheduledTasks", "last_result", "an exit code")):
            self.assertEqual(
                [], self.det.detect_timestamp_columns(table, [column]),
                "%s.%s is %s; a time filter keyed on it matches nothing"
                % (table, column, what))

    def test_a_table_the_map_does_not_know_falls_back_to_patterns(self):
        """Every imported and custom database is in this position."""
        self.assertEqual(
            ["visit_time"],
            self.det.detect_timestamp_columns("visits",
                                              ["url", "visit_time", "title"]))

    def test_the_map_adds_and_never_removes(self):
        """`UserAccounts.account_expires` is a real time the map does not plot.

        The map says what the TIMELINE draws, which is not everything a table
        times, so it has to widen the detector and never narrow it.
        """
        got = self.det.detect_timestamp_columns(
            "UserAccounts",
            ["username", "last_logon", "account_expires", "parsed_at"])
        self.assertIn("last_logon", got)      # from the map
        self.assertIn("account_expires", got)  # from the patterns
        self.assertNotIn("parsed_at", got)

    def test_account_columns_are_not_read_as_counters(self):
        """`.*count.*` also matched `account_expires`, because "account" does."""
        self.assertIn(
            "account_created",
            self.det.detect_timestamp_columns("X", ["account_created"]))
        self.assertEqual(
            [], self.det.detect_timestamp_columns("X", ["run_count"]))

    def test_exactness_comes_from_the_map(self):
        self.assertEqual("key upper bound",
                         self.det.exactness("OpenSaveMRU", "key_last_write"))
        self.assertEqual("exact", self.det.exactness("BAM", "last_execution"))
        self.assertEqual("", self.det.exactness("visits", "visit_time"))


class BlankIsMissingNotUnparseable(unittest.TestCase):
    """Half a column of real timestamps is a timestamp column with gaps.

    `registry_value_changes.changed_at` is exact on the 552 values recovered
    from the transaction log and empty on the other 491. Scoring the blanks as
    parse failures gave 66%, under the 80% bar, and dropped the whole table
    from every time-filtered search - including the one registry time that is
    not an upper bound.
    """

    def test_a_half_empty_column_is_still_a_timestamp_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.db")
            con = sqlite3.connect(path)
            con.execute("CREATE TABLE t (changed_at TEXT)")
            con.executemany("INSERT INTO t VALUES (?)",
                            [("2026-02-14 04:30:00",)] * 34 + [("",)] * 66)
            con.commit()
            con.close()

            got = TimestampDetector().analyze_column_data(path, "t",
                                                          "changed_at", 200)
            self.assertTrue(
                got["is_timestamp"],
                "a column that is one third real timestamps and two thirds "
                "blank was read as not a timestamp column at all")
            self.assertEqual(100.0, got["parse_success_rate"])
            self.assertEqual(66, got["blank_samples"])

    def test_a_column_of_junk_is_still_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.db")
            con = sqlite3.connect(path)
            con.execute("CREATE TABLE t (changed_at TEXT)")
            con.executemany("INSERT INTO t VALUES (?)",
                            [("not a date",)] * 50)
            con.commit()
            con.close()

            got = TimestampDetector().analyze_column_data(path, "t",
                                                          "changed_at", 200)
            self.assertFalse(got["is_timestamp"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
