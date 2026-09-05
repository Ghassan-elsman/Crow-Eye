r"""Break the search guarantees; every check must catch its own break.

`test_search_reaches_every_database.py` guards behaviour that was broken for a
long time without anyone noticing - an imported database that could not be
selected, a file read six times, a table dropped from every time-filtered
search. Nothing complained about any of it, so "the check passes" is worth
exactly as much as evidence that the check can fail.

Each mutation below is one of those failures, put back.
"""
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from data.tests import test_search_reaches_every_database as T   # noqa: E402


def _run(cls, name):
    with open(os.devnull, "w") as devnull:
        res = unittest.TextTestRunner(verbosity=0, stream=devnull).run(
            unittest.TestSuite([cls(name)]))
    return len(res.failures) + len(res.errors)


class TheSearchChecksCanFail(unittest.TestCase):

    def setUp(self):
        from data.timestamp_detector import TimestampDetector
        from ui.database_search_dialog import DatabaseSearchDialog
        self.det_cls = TimestampDetector
        self.dlg_cls = DatabaseSearchDialog
        self.saved_group = DatabaseSearchDialog._group_databases_for_tree
        self.saved_not_ts = TimestampDetector.NOT_TIMESTAMPS
        self.saved_map = TimestampDetector._MAP_CACHE

    def tearDown(self):
        self.dlg_cls._group_databases_for_tree = self.saved_group
        self.det_cls.NOT_TIMESTAMPS = self.saved_not_ts
        self.det_cls._MAP_CACHE = self.saved_map

    def test_baseline_is_clean(self):
        for cls, name in (
                (T.EveryDiscoveredDatabaseReachesTheTree,
                 "test_nothing_discovered_is_dropped"),
                (T.EveryDiscoveredDatabaseReachesTheTree,
                 "test_imported_evidence_is_reachable"),
                (T.TheTimeFilterAgreesWithTheMap,
                 "test_every_mapped_time_column_is_recognised"),
                (T.TheTimeFilterAgreesWithTheMap,
                 "test_things_that_are_not_times_are_refused"),
                (T.BlankIsMissingNotUnparseable,
                 "test_a_half_empty_column_is_still_a_timestamp_column")):
            self.assertEqual(0, _run(cls, name), "%s failed clean" % name)

    def test_the_old_name_list_behaviour_is_caught(self):
        """Put back the loop that dropped everything it had no name for."""
        def only_configured(cls, enhanced_databases):
            out = []
            for category, db_names in cls.DATABASE_CATEGORIES.items():
                dbs = [d for d in enhanced_databases if d.name in db_names]
                if dbs:
                    out.append((category, dbs))
            return out

        self.dlg_cls._group_databases_for_tree = classmethod(only_configured)
        self.assertTrue(_run(T.EveryDiscoveredDatabaseReachesTheTree,
                             "test_nothing_discovered_is_dropped"))
        self.assertTrue(_run(T.EveryDiscoveredDatabaseReachesTheTree,
                             "test_imported_evidence_is_reachable"))

    def test_a_missed_map_column_is_caught(self):
        """The state `changed_at` and `key_last_write` were in."""
        cache = dict(self.det_cls._map_columns())
        broken = {t: dict(cols) for t, cols in cache.items()}
        broken.pop("registry_value_changes", None)
        self.det_cls._MAP_CACHE = broken
        # `changed_at` matches no pattern either, so removing it from the map
        # is exactly the old behaviour.
        self.assertTrue(_run(T.TheTimeFilterAgreesWithTheMap,
                             "test_every_mapped_time_column_is_recognised"))

    def test_a_non_time_accepted_is_caught(self):
        """`focus_time` is a duration; the patterns matched it."""
        self.det_cls.NOT_TIMESTAMPS = frozenset(
            c for c in self.saved_not_ts if c != "focus_time")
        self.assertTrue(_run(T.TheTimeFilterAgreesWithTheMap,
                             "test_things_that_are_not_times_are_refused"))

    def test_scoring_blanks_as_failures_is_caught(self):
        """The 66% that dropped `registry_value_changes` from time filtering."""
        import data.timestamp_detector as mod
        real = mod.TimestampDetector.analyze_column_data

        def counts_blanks(self, db_path, table_name, column_name,
                          sample_size=100):
            got = real(self, db_path, table_name, column_name, sample_size)
            blanks = got.get("blank_samples", 0)
            kept = len(got.get("parsed_samples", []))
            total = blanks + max(kept, 1)
            got["parse_success_rate"] = (max(kept, 1) / total) * 100
            got["is_timestamp"] = got["parse_success_rate"] >= 80.0
            return got

        mod.TimestampDetector.analyze_column_data = counts_blanks
        try:
            self.assertTrue(_run(
                T.BlankIsMissingNotUnparseable,
                "test_a_half_empty_column_is_still_a_timestamp_column"))
        finally:
            mod.TimestampDetector.analyze_column_data = real

    def test_reading_a_file_twice_is_caught(self):
        """Six logical names, six reads - what both search paths used to do."""
        import data.unified_search_engine as mod
        real = mod.UnifiedDatabaseSearchEngine._one_entry_per_file

        def no_dedupe(infos, tables):
            return list(infos), tables, {i.name: [i.name] for i in infos}

        mod.UnifiedDatabaseSearchEngine._one_entry_per_file = staticmethod(
            no_dedupe)
        try:
            self.assertTrue(_run(T.OneReadPerFile,
                                 "test_unified_engine_reads_each_file_once"))
        finally:
            mod.UnifiedDatabaseSearchEngine._one_entry_per_file = real

    def test_the_log_claw_misresolution_is_caught(self):
        """Put `Log_Claw.db` back as the ShellBags alternative."""
        from data.database_manager import DatabaseManager
        saved = dict(DatabaseManager.ALT_NAME_MAP)
        try:
            DatabaseManager.ALT_NAME_MAP = dict(saved)
            DatabaseManager.ALT_NAME_MAP["shellbags_data.db"] = ["Log_Claw.db"]
            self.assertTrue(_run(
                T.EachArtifactPointsAtItsOwnData,
                "test_each_resolves_to_the_file_holding_its_artifact"))
            self.assertTrue(_run(
                T.EachArtifactPointsAtItsOwnData,
                "test_log_claw_is_only_the_event_log"))
        finally:
            DatabaseManager.ALT_NAME_MAP = saved

    def test_an_unscoped_artifact_entry_is_caught(self):
        """Without scoping, ShellBags offers every table beside it."""
        from data.database_manager import DatabaseManager
        saved = DatabaseManager.SHARED_DB_ARTIFACTS
        try:
            DatabaseManager.SHARED_DB_ARTIFACTS = frozenset()
            self.assertTrue(_run(T.EachArtifactPointsAtItsOwnData,
                                 "test_each_offers_only_its_own_tables"))
        finally:
            DatabaseManager.SHARED_DB_ARTIFACTS = saved

    def test_scoping_the_whole_registry_is_caught(self):
        """Scoping by signature across the board guts the Registry entry."""
        from data.database_manager import DatabaseManager
        saved = DatabaseManager.SHARED_DB_ARTIFACTS
        try:
            DatabaseManager.SHARED_DB_ARTIFACTS = frozenset(
                set(saved) | {"registry_data.db"})
            self.assertTrue(_run(T.EachArtifactPointsAtItsOwnData,
                                 "test_scoping_did_not_leak_onto_a_whole_file"))
        finally:
            DatabaseManager.SHARED_DB_ARTIFACTS = saved

    def test_dropping_the_legacy_lnk_name_is_caught(self):
        from data.database_manager import DatabaseManager
        saved = dict(DatabaseManager.TABLE_SIGNATURES)
        try:
            DatabaseManager.TABLE_SIGNATURES = dict(saved)
            DatabaseManager.TABLE_SIGNATURES["lnk_data.db"] = [
                s for s in saved["lnk_data.db"] if s != "jlce"]
            self.assertTrue(_run(T.EachArtifactPointsAtItsOwnData,
                                 "test_a_legacy_lnk_case_still_resolves"))
        finally:
            DatabaseManager.TABLE_SIGNATURES = saved

    def test_a_fixture_that_proves_nothing_is_caught(self):
        """Both fixtures assert they are exercising the thing they check."""
        import data.database_manager as mod
        real = mod.DatabaseManager.discover_databases

        def nothing(self):
            return []

        mod.DatabaseManager.discover_databases = nothing
        try:
            self.assertTrue(_run(T.EveryDiscoveredDatabaseReachesTheTree,
                                 "test_the_case_fixture_is_discovered"))
            self.assertTrue(_run(T.OneReadPerFile,
                                 "test_the_fixture_really_does_collapse"))
        finally:
            mod.DatabaseManager.discover_databases = real


if __name__ == "__main__":
    unittest.main(verbosity=2)
