r"""The map and the bridge must describe the same timeline, both directions.

`artifact_map.py` says what the timeline plots. `timeline_bridge.py` is what
the React app actually calls. Nothing checked that the two agreed, and they
did not:

  * `getMftUsnData` selected three of the nine time columns the map names, so
    every $FILE_NAME time on 202,729 correlated records was fetched by nothing;
  * `Log_Claw.db` was queried for eighteen hard-coded EventIDs and appeared in
    the map not at all;
  * `getTimeBounds` named AmCache's raw `link_date`, which the map does not
    plot because it holds version strings.

None of that raises. A mapped column no query reads is simply absent from the
screen, and a query reading a column the map does not know about is evidence
nothing else in the system - Eye's `query_timeline`, the heatmap, the tests -
can account for.

Reads source only: no case database, no PyQt window.
"""
import io
import os
import re
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from timeline.data import artifact_map as M      # noqa: E402

BRIDGE_SRC = io.open(os.path.join(REPO, "timeline", "timeline_bridge.py"),
                     encoding="utf-8", errors="replace").read()

# Mapped columns no bridge query is expected to read, each with its reason.
# An exemption is a decision, so it is written down where it can be argued
# with - not inferred from a pattern that would also excuse the next mistake.
NOT_FETCHED_BY_THE_BRIDGE = {
    # The MFT lane is served by `mft_usn_correlated`, which carries the same
    # per-file times already correlated with the USN journal. Querying
    # `mft_claw_analysis.db` as well would draw 205,052 records twice. The
    # mapping stays because Eye's time sweep reads it directly.
    ("mft_records", "created_time"),
    ("mft_records", "modified_time"),
    ("mft_records", "accessed_time"),
    ("mft_records", "mft_modified_time"),
    ("mft_file_names", "created"),
    ("mft_file_names", "modified"),
    ("mft_file_names", "accessed"),
    ("mft_file_names", "mft_modified"),
    ("filename_changes", "change_timestamp"),
    # Supplementary SRUM tables. `getSrumEnergyData` exists as a slot but the
    # React app never calls it, and `srum_app_timeline` has no lane at all.
    ("srum_energy_usage", "timestamp"),
    ("srum_energy_usage", "event_timestamp"),
    ("srum_app_timeline", "timestamp"),
    # Windows install date, shown in the case header rather than plotted.
    ("ComputerNameInfo", "installation_date"),
    # Second-hand copies: `USBDevices` duplicates USBStorageDevices, and
    # `NetworkProfiles.last_written` is drawn through the key-time path.
    ("USBDevices", "last_connected"),
}


def _map_driven_tables():
    """Tables the bridge queries through `_mapped_rows` / `_mapped_query`.

    Those build their column list from the map itself, so every mapped column
    of such a table is read by construction - that is the point of them.
    """
    tables = set()
    for m in re.finditer(
            r'_mapped_(?:rows|query)\(\s*\n?\s*(?:"[^"]+",\s*)?'
            r'"(\w+)",\s*"(\w+)"', BRIDGE_SRC):
        tables.add(m.group(2))
    # `getEventLogData` loops over EVENT_LOG_TABLES rather than naming each.
    if "EVENT_LOG_TABLES" in BRIDGE_SRC:
        tables.update(M.EVENT_LOG_TABLES)
    return tables


def _columns_named_in_raw_sql():
    """{(table, column)} a hand-written bridge statement filters or selects.

    Crude on purpose: a statement mentioning both the table and the column is
    treated as reading it. The check this backs is "is anything reading this at
    all", and a looser match there fails safe - it can miss a query, never
    invent one.
    """
    pairs = set()
    for m in re.finditer(r'"""(.*?)"""', BRIDGE_SRC, re.S):
        sql = m.group(1)
        if "SELECT" not in sql.upper():
            continue
        tables = re.findall(r"FROM\s+\[?(\w+)\]?", sql, re.I)
        words = set(re.findall(r"\w+", sql))
        for t in tables:
            for w in words:
                pairs.add((t, w))
    return pairs


class EveryMappedColumnIsRead(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.driven = _map_driven_tables()
        cls.raw = _columns_named_in_raw_sql()

    def test_the_scan_found_the_map_driven_tables(self):
        # A regex that matches nothing would make the check below vacuous.
        self.assertGreater(
            len(self.driven), 4,
            "only %d map-driven tables were found in the bridge; the scan is "
            "broken and everything below passes by finding nothing"
            % len(self.driven))

    def test_every_mapped_column_reaches_the_timeline(self):
        missing = []
        for artifact, entries in M.TIMESTAMP_MAPPINGS.items():
            for entry in entries:
                table, column = entry[0], entry[1]
                if (table, column) in NOT_FETCHED_BY_THE_BRIDGE:
                    continue
                if table in self.driven:
                    continue                     # read from the map itself
                if M.is_key_time(entry):
                    continue                     # the key-time template
                if (table, column) in self.raw:
                    continue
                missing.append("%s: %s.%s" % (artifact, table, column))
        self.assertEqual(
            [], missing,
            "these columns are mapped and no bridge query reads them, so they "
            "are plotted nowhere and nothing reports it:\n  "
            + "\n  ".join(missing))


class TheFrontEndReadsEveryMappedTime(unittest.TestCase):
    """`FORENSIC_TS_FIELDS` in the React app must know every mapped column.

    The bridge fetches a column, hands it to the front end, and
    `getForensicTimestamps` walks a hand-written list of field names to find
    the times in each row. A column absent from that list arrives in the
    payload and draws no dot: no error, no warning, no empty section - the row
    is simply on screen carrying a time nothing renders.

    Twenty-three mapped columns were in that state, every $FILE_NAME time
    among them.
    """

    FORMATTERS = os.path.join(
        REPO, "timeline", "react-timeline", "src", "utils", "formatters.js")

    @classmethod
    def setUpClass(cls):
        src = io.open(cls.FORMATTERS, encoding="utf-8",
                      errors="replace").read()
        block = src[src.index("FORENSIC_TS_FIELDS = ["):]
        cls.fields = set(re.findall(r"'(\w+)'", block[:block.index("]")]))

    def test_the_scan_found_the_list(self):
        self.assertGreater(
            len(self.fields), 20,
            "only %d field names were read out of FORENSIC_TS_FIELDS; the "
            "scan is broken" % len(self.fields))

    def test_every_mapped_column_is_listed(self):
        need = {e[1] for entries in M.TIMESTAMP_MAPPINGS.values()
                for e in entries}
        missing = sorted(need - self.fields)
        self.assertEqual(
            [], missing,
            "these columns are plotted by the map and unknown to the React "
            "app, so their rows arrive and draw nothing:\n  "
            + "\n  ".join(missing))

    def test_a_duration_is_not_listed_as_a_time(self):
        """`focus_time` is UserAssist's dwell time, stored as "0.00s"."""
        for bad in ("focus_time", "parsed_at", "scheduled_install_time"):
            self.assertNotIn(
                bad, self.fields,
                "%s is not an event time and listing it invites the front end "
                "to plot it" % bad)


class EveryQueriedTimeColumnIsMapped(unittest.TestCase):
    """The other direction: a query reading a time the map does not know.

    That column's rows reach the screen carrying a time nothing else in the
    system can account for - not the heatmap, not Eye's sweep, not the
    coverage audit.
    """

    def test_bounds_sources_are_mapped(self):
        from timeline.timeline_bridge import TimelineBridge

        mapped = set()
        for artifact, entries in M.TIMESTAMP_MAPPINGS.items():
            db = M.ARTIFACT_DB_MAPPING.get(artifact)
            for e in entries:
                mapped.add((db, e[0], e[1]))
        bad = [s for s in TimelineBridge._BOUNDS_SOURCES if s not in mapped]
        self.assertEqual(
            [], bad,
            "the case span is computed from columns the map does not plot, so "
            "the visible window can be set by evidence the timeline then "
            "cannot show: %s" % bad)

    def test_bounds_avoid_key_times(self):
        """A key upper bound must not set the visible window.

        4,294 of them cluster on install day; letting one be the left edge
        opens every case years before its evidence.
        """
        from timeline.timeline_bridge import TimelineBridge

        bad = [(t, c) for _db, t, c in TimelineBridge._BOUNDS_SOURCES
               if (t, c) in M.KEY_TIME_COLUMNS]
        self.assertEqual([], bad, "bounded times used as case bounds: %s" % bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
