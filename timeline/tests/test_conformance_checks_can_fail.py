r"""Break the map/bridge/front-end agreement; every check must catch its own.

`test_bridge_and_map_agree.py` is the file that found the gaps this round -
the whole event log, the $FILE_NAME times, AmCache's device installs, the SAM
account times. All of it was invisible precisely because nothing looked, so
"the check passes" is worth exactly as much as evidence that the check can
fail.

Each mutation below is one of those gaps, put back.
"""
import io
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from timeline.data import artifact_map as M                  # noqa: E402
from timeline.tests import test_bridge_and_map_agree as T     # noqa: E402


def _run(cls, name):
    with open(os.devnull, "w") as devnull:
        res = unittest.TextTestRunner(verbosity=0, stream=devnull).run(
            unittest.TestSuite([cls(name)]))
    return len(res.failures) + len(res.errors)


class TheConformanceChecksCanFail(unittest.TestCase):

    def setUp(self):
        self.saved_reg = list(M.TIMESTAMP_MAPPINGS["Registry"])
        self.saved_db = dict(M.ARTIFACT_DB_MAPPING)
        self.saved_exempt = set(T.NOT_FETCHED_BY_THE_BRIDGE)
        # `setUpClass` re-reads the source every time a check runs, so a
        # mutation has to go into what it READS. Assigning the class attribute
        # it sets is silently undone - and that made three of these mutations
        # look caught when nothing had changed at all.
        self.saved_driven_fn = T._map_driven_tables
        self.saved_formatters = T.TheFrontEndReadsEveryMappedTime.FORMATTERS

    def tearDown(self):
        M.TIMESTAMP_MAPPINGS["Registry"][:] = self.saved_reg
        M.ARTIFACT_DB_MAPPING.clear()
        M.ARTIFACT_DB_MAPPING.update(self.saved_db)
        T.NOT_FETCHED_BY_THE_BRIDGE.clear()
        T.NOT_FETCHED_BY_THE_BRIDGE.update(self.saved_exempt)
        T._map_driven_tables = self.saved_driven_fn
        T.TheFrontEndReadsEveryMappedTime.FORMATTERS = self.saved_formatters

    def _formatters_without(self, *drop):
        """A copy of formatters.js with some time fields removed."""
        import tempfile
        src = io.open(self.saved_formatters, encoding="utf-8").read()
        for name in drop:
            src = src.replace("'%s'," % name, "")
        fd, path = tempfile.mkstemp(suffix=".js")
        os.close(fd)
        io.open(path, "w", encoding="utf-8").write(src)
        self.addCleanup(os.unlink, path)
        T.TheFrontEndReadsEveryMappedTime.FORMATTERS = path

    def _formatters_plus(self, name):
        import tempfile
        src = io.open(self.saved_formatters, encoding="utf-8").read()
        src = src.replace("FORENSIC_TS_FIELDS = [",
                          "FORENSIC_TS_FIELDS = [\n  '%s'," % name)
        fd, path = tempfile.mkstemp(suffix=".js")
        os.close(fd)
        io.open(path, "w", encoding="utf-8").write(src)
        self.addCleanup(os.unlink, path)
        T.TheFrontEndReadsEveryMappedTime.FORMATTERS = path

    def test_baseline_is_clean(self):
        self.assertEqual(0, _run(T.EveryMappedColumnIsRead,
                                 "test_every_mapped_column_reaches_the_timeline"))
        self.assertEqual(0, _run(T.TheFrontEndReadsEveryMappedTime,
                                 "test_every_mapped_column_is_listed"))
        self.assertEqual(0, _run(T.EveryQueriedTimeColumnIsMapped,
                                 "test_bounds_sources_are_mapped"))

    def test_a_mapped_column_no_query_reads_is_caught(self):
        """A column plotted by nothing - the state Log_Claw.db was in."""
        M.TIMESTAMP_MAPPINGS["Registry"].append(
            ("ShutdownInfo", "boot_time", "executed", "invented"))
        self.assertTrue(_run(T.EveryMappedColumnIsRead,
                             "test_every_mapped_column_reaches_the_timeline"))

    def test_a_column_the_front_end_cannot_read_is_caught(self):
        """The $FILE_NAME state: fetched, handed over, and drawn as nothing."""
        self._formatters_without("EventTimestampUTC")
        self.assertTrue(_run(T.TheFrontEndReadsEveryMappedTime,
                             "test_every_mapped_column_is_listed"))

    def test_a_duration_listed_as_a_time_is_caught(self):
        self._formatters_plus("focus_time")
        self.assertTrue(_run(T.TheFrontEndReadsEveryMappedTime,
                             "test_a_duration_is_not_listed_as_a_time"))

    def test_bounds_on_an_unmapped_column_is_caught(self):
        """AmCache's raw `link_date` set the case span to 2000-2028."""
        from timeline.timeline_bridge import TimelineBridge
        saved = list(TimelineBridge._BOUNDS_SOURCES)
        try:
            TimelineBridge._BOUNDS_SOURCES = saved + [
                ("amcache.db", "InventoryApplicationFile", "link_date")]
            self.assertTrue(_run(T.EveryQueriedTimeColumnIsMapped,
                                 "test_bounds_sources_are_mapped"))
        finally:
            TimelineBridge._BOUNDS_SOURCES = saved

    def test_bounds_on_a_key_time_is_caught(self):
        """A key upper bound must never set the visible window."""
        from timeline.timeline_bridge import TimelineBridge
        saved = list(TimelineBridge._BOUNDS_SOURCES)
        try:
            TimelineBridge._BOUNDS_SOURCES = saved + [
                ("registry_data.db", "FirewallRules", "last_written")]
            self.assertTrue(_run(T.EveryQueriedTimeColumnIsMapped,
                                 "test_bounds_avoid_key_times"))
        finally:
            TimelineBridge._BOUNDS_SOURCES = saved

    def test_a_scan_that_finds_nothing_is_caught(self):
        """Both scans are regex-based; one matching nothing passes silently."""
        T._map_driven_tables = lambda: set()
        self.assertTrue(_run(T.EveryMappedColumnIsRead,
                             "test_the_scan_found_the_map_driven_tables"))
        self._formatters_without(*sorted(
            T.TheFrontEndReadsEveryMappedTime.__dict__.get("fields", ())
            or [e[1] for entries in M.TIMESTAMP_MAPPINGS.values()
                for e in entries]))
        self.assertTrue(_run(T.TheFrontEndReadsEveryMappedTime,
                             "test_the_scan_found_the_list"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
