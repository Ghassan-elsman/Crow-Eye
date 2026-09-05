r"""Break the artifact map nine ways; every check must catch its own break.

A check that has never been seen to fail is a check nobody has a reason to
trust - and the checks in `test_artifact_map_is_consistent.py` guard a file
that drifted for a long time without a single complaint, so "it passes" is not
evidence of anything on its own.

Each mutation below is a drift that actually happened, or the exact inverse of
one. They are applied in memory and undone in `tearDown`; nothing on disk
changes.
"""
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from timeline.data import artifact_map as M                      # noqa: E402
from timeline.tests import test_artifact_map_is_consistent as T   # noqa: E402


def _run(*names):
    """Run named checks and return how many failed."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (T.MapsAgree, T.EntriesAreWellFormed,
                T.MappingsResolveAgainstTheParserSource,
                T.BridgeKeyTimeSourcesMatchTheMap):
        for n in loader.getTestCaseNames(cls):
            if n in names:
                suite.addTest(cls(n))
    with open(os.devnull, "w") as devnull:
        res = unittest.TextTestRunner(verbosity=0, stream=devnull).run(suite)
    return len(res.failures) + len(res.errors)


class BreakingTheMapIsCaught(unittest.TestCase):

    def setUp(self):
        from timeline.timeline_bridge import TimelineBridge
        self.bridge_cls = TimelineBridge
        self.saved_db = dict(M.ARTIFACT_DB_MAPPING)
        self.saved_reg = list(M.TIMESTAMP_MAPPINGS["Registry"])
        self.saved_cols = M.KEY_TIME_COLUMNS
        self.saved_labels = dict(TimelineBridge._KEY_TIME_LABELS)

    def tearDown(self):
        M.ARTIFACT_DB_MAPPING.clear()
        M.ARTIFACT_DB_MAPPING.update(self.saved_db)
        M.TIMESTAMP_MAPPINGS["Registry"][:] = self.saved_reg
        M.KEY_TIME_COLUMNS = self.saved_cols
        self.bridge_cls._KEY_TIME_LABELS = self.saved_labels
        T.BridgeKeyTimeSourcesMatchTheMap.labels = self.saved_labels

    def _labels(self, **override):
        merged = dict(self.saved_labels, **override)
        self.bridge_cls._KEY_TIME_LABELS = merged
        T.BridgeKeyTimeSourcesMatchTheMap.labels = merged

    # -- the checks pass when nothing is broken -----------------------------

    def test_baseline_is_clean(self):
        self.assertEqual(0, _run(
            "test_every_timestamp_key_has_a_database",
            "test_registry_tables_and_columns_exist",
            "test_parsed_at_is_never_plotted",
            "test_every_key_write_column_is_marked_bounded",
            "test_record_times_are_not_marked_bounded",
            "test_label_and_path_columns_exist",
            "test_every_labelled_table_is_a_key_time_table",
            "test_mru_tables_are_not_drawn_twice"))

    # -- and fail, for the right reason, when something is --------------------

    def test_an_artifact_losing_its_database_is_caught(self):
        """The Shellbags orphaning: times defined, no database, never loaded."""
        M.ARTIFACT_DB_MAPPING.pop("Shellbags")
        self.assertTrue(_run("test_every_timestamp_key_has_a_database"))

    def test_a_dead_table_in_the_map_is_caught(self):
        """`Auto` is an abandoned draft of WindowsUpdateInfo. Nothing writes it."""
        M.TIMESTAMP_MAPPINGS["Registry"].append(
            ("Auto", "install_date", "installed", "gone"))
        self.assertTrue(_run("test_registry_tables_and_columns_exist"))

    def test_parsed_at_as_an_event_time_is_caught(self):
        M.TIMESTAMP_MAPPINGS["Registry"].append(
            ("BAM", "parsed_at", "modified", "when the parser ran"))
        self.assertTrue(_run("test_parsed_at_is_never_plotted"))

    def test_a_key_time_left_unmarked_is_caught(self):
        M.KEY_TIME_COLUMNS = frozenset(
            p for p in self.saved_cols if p[0] != "FirewallRules")
        self.assertTrue(_run("test_every_key_write_column_is_marked_bounded"))

    def test_a_record_time_marked_bounded_is_caught(self):
        """The inverse, which is where NetworkProfiles nearly went wrong."""
        M.KEY_TIME_COLUMNS = frozenset(
            set(self.saved_cols) | {("NetworkProfiles", "date_created")})
        self.assertTrue(_run("test_record_times_are_not_marked_bounded"))

    def test_a_misspelt_bridge_column_is_caught(self):
        self._labels(FirewallRules=("Firewall rule", "rule_nmae", "key_path"))
        self.assertTrue(_run("test_label_and_path_columns_exist"))

    def test_a_key_path_assumed_where_there_is_none_is_caught(self):
        """`local_groups` has no `key_path`, and SELECTing it raises."""
        self._labels(local_groups=("Local group", "group_name", "key_path"))
        self.assertTrue(_run("test_label_and_path_columns_exist"))

    def test_an_exact_time_table_drawn_as_bounded_is_caught(self):
        self._labels(ScheduledTasks=("Scheduled task", "task_path", "key_path"))
        self.assertTrue(_run("test_every_labelled_table_is_a_key_time_table"))

    def test_an_mru_table_plotted_twice_is_caught(self):
        self._labels(OpenSaveMRU=("Open/Save MRU", "file_name", "key_path"))
        self.assertTrue(_run("test_mru_tables_are_not_drawn_twice"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
