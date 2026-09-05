r"""The timeline plots exactly what `timeline/data/artifact_map.py` names.

Nothing guarded that file, and it drifted far enough that six artifact types
could never load at all. `TIMESTAMP_MAPPINGS` defined times for Shellbags,
Amcache, Shimcache, RecycleBin, DAM and USBStorageDevices while
`ARTIFACT_DB_MAPPING` named none of them - and `_detect_available_artifacts()`
iterates the DB map, so those types were never even considered. 804 Shellbags
rows with three date columns each appeared nowhere. The only complaint anywhere
was one debug line reading `No timestamp mappings defined for ShellBag`, which
is what the two maps disagreeing about a capital B looks like.

Every check here runs with no evidence on the machine. The schema comes out of
the PARSER SOURCE, the way
`correlation_engine/tests/test_eye_schema_reference_is_current.py` does it - a
guard that skips for want of a case database is exactly how this went unnoticed
for as long as it did.

Three DDL shapes have to be understood, because Regclaw uses all three and the
timeline's key-time tables are spread across them:

  1. a literal `CREATE TABLE ... ( ... )`;
  2. the `("name", "col TEXT, ...")` pair list that builds ten tables at once;
  3. the ASEP `for _t in (...)` loop with one f-string DDL for 28 tables.
"""
import io
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sys
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from timeline.data import artifact_map  # noqa: E402

# Registry tables are NOT all created by Regclaw. The SECURITY-hive tables -
# audit_policy, local_groups, lsa_policy, lsa_secrets - live in
# `security_hive.py`, and the account tables in `user_identity.py`. Reading one
# file per family is exactly the blind spot that keeps `UserAccounts` out of
# Sentinel's schema to this day; a check that reads only Regclaw would report
# four perfectly good mappings as broken.
def _p(*parts):
    return os.path.join(REPO, "Artifacts_Collectors", *parts)


REGISTRY_PARSERS = [
    _p("Regclaw.py"),
    _p("security_hive.py"),
    _p("user_identity.py"),
    _p("offline_parsers", "offline_RegClaw.py"),
]

# The rest of the map's databases, by the parser that writes each. Checking
# only the registry left `Log_Claw.db`, `mft_claw_analysis.db` and
# `mft_usn_correlated_analysis.db` unguarded - which is where the map was
# missing three real time sources, including the entire Windows event log.
OTHER_PARSERS = {
    "Log_Claw.db": [_p("WinLog_Claw.py"),
                    _p("offline_parsers", "offline_WinLog_Claw.py")],
    "prefetch_data.db": [_p("Prefetch_claw.py")],
    "LnkDB.db": [_p("A_CJL_LNK_Claw.py")],
    "amcache.db": [_p("amcacheparser.py")],
    "shimcache.db": [_p("shimcash_claw.py")],
    "recyclebin_analysis.db": [_p("recyclebin_claw.py")],
    "srum_data.db": [_p("SRUM_Claw.py"),
                     _p("offline_parsers", "offline_SRUM_Claw.py")],
    "mft_claw_analysis.db": [_p("MFT and USN journal", "MFT_Claw.py"),
                             _p("MFT and USN journal", "mft_usn_correlator.py")],
    "mft_usn_correlated_analysis.db": [
        _p("MFT and USN journal", "mft_usn_correlator.py")],
    "USN_journal.db": [_p("MFT and USN journal", "USN_Claw.py"),
                       _p("offline_parsers", "offline_USNClaw.py")],
}

BRIDGE = os.path.join(REPO, "timeline", "timeline_bridge.py")

# The kinds the front end knows how to draw. A kind outside this set reaches
# `forensicMap` in TimelineView.jsx, misses, and renders as an anonymous dot.
KNOWN_KINDS = frozenset((
    "created", "modified", "accessed", "executed", "installed",
    "linked", "deleted", "mft_modified", "various",
))


# --------------------------------------------------------------------------
#  Schema, read out of the parser source
# --------------------------------------------------------------------------

def _split_top_level(body):
    """Split a DDL body on commas that are not inside parentheses."""
    out, depth, cur = [], 0, ""
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def _columns_from(body):
    cols = []
    for part in _split_top_level(re.sub(r"--[^\n]*", "", body)):
        part = part.strip()
        if not part:
            continue
        # `UNIQUE(hive, key_path)` and friends are constraints, not columns.
        # Split the keyword off its paren first, or `UNIQUE(hive` is read as a
        # column named UNIQUE.
        head = re.split(r"[\s(]", part, 1)[0].strip('"[]`').upper()
        if head in ("PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "CONSTRAINT"):
            continue
        m = re.match(r'[\["`]?(\w+)[\]"`]?', part)
        if m:
            cols.append(m.group(1))
    return cols


def registry_schema():
    """{table: [column, ...]} for the registry parsers, from source."""
    return _schema_from(REGISTRY_PARSERS)


def _schema_from(paths):
    """{table: [column, ...]} across all three DDL shapes."""
    schema = {}
    for path in paths:
        if not os.path.exists(path):
            continue
        src = io.open(path, encoding="utf-8", errors="replace").read()

        # 1. literal CREATE TABLE, balanced on parentheses rather than on a
        #    closing quote - the parsers quote their SQL several ways.
        for m in re.finditer(
                r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+\[?(\w+)\]?\s*\(", src):
            name, i, depth, end = m.group(1), m.end() - 1, 0, None
            for j in range(i, len(src)):
                if src[j] == "(":
                    depth += 1
                elif src[j] == ")":
                    depth -= 1
                    if depth == 0:
                        end = j
                        break
            if end is None:
                continue
            cols = _columns_from(src[i + 1:end])
            if cols:
                schema.setdefault(name, cols)

        # 2. the ("name", "col TEXT, ...") pair list.
        for m in re.finditer(
                r'\(\s*"(\w+)"\s*,\s*"([^"]*\bTEXT\b[^"]*)"\s*\)', src):
            cols = _columns_from(m.group(2))
            if len(cols) > 1:
                schema.setdefault(m.group(1), cols)

        # 3. the ASEP loop: one f-string DDL for 28 tables. Strip `#` comments
        #    from the tuple first - it carries a note about naming a table for
        #    the artifact and not the technique, and a bare findall reads the
        #    quoted word out of that comment as another table.
        for m in re.finditer(
                r"for _t in \(([^)]*)\):\s*\n\s*cursor\.execute\(\s*\n"
                r"\s*f'CREATE TABLE IF NOT EXISTS \{_t\} \('((?:[^)]|\)(?!'\)))*)",
                src):
            names = re.findall(
                r'"(\w+)"', re.sub(r"#[^\n]*", "", m.group(1)))
            ddl = "".join(re.findall(r"'([^']*)'", m.group(2)))
            cols = _columns_from(ddl)
            for name in names:
                if cols:
                    schema.setdefault(name, list(cols))

        # 4. AmCache's `AMCACHE_SCHEMAS = {table: [column, ...]}` dict, turned
        #    into DDL by an f-string at run time. A `CREATE TABLE` regex sees
        #    none of its seventeen tables - this is the shape that had the
        #    architecture claiming AmCache has eleven.
        m = re.search(r"AMCACHE_SCHEMAS\s*=\s*\{", src)
        if m:
            i, depth, end = m.end() - 1, 0, None
            for j in range(i, len(src)):
                if src[j] == "{":
                    depth += 1
                elif src[j] == "}":
                    depth -= 1
                    if depth == 0:
                        end = j
                        break
            body = src[i:end] if end else ""
            for tm in re.finditer(r'"(\w+)"\s*:\s*\[([^\]]*)\]', body):
                cols = re.findall(r'"(\w+)"', tm.group(2))
                if cols:
                    schema.setdefault(tm.group(1), ["id"] + cols)

        # 5. ALTER TABLE ... ADD COLUMN lands at the end of the table.
        for m in re.finditer(
                r"ALTER TABLE\s+\[?(\w+)\]?\s+ADD COLUMN\s+\[?(\w+)\]?", src):
            if m.group(1) in schema and m.group(2) not in schema[m.group(1)]:
                schema[m.group(1)].append(m.group(2))
    return schema


class MapsAgree(unittest.TestCase):
    """The two halves of the map must name the same artifacts."""

    def test_every_timestamp_key_has_a_database(self):
        missing = sorted(set(artifact_map.TIMESTAMP_MAPPINGS)
                         - set(artifact_map.ARTIFACT_DB_MAPPING))
        self.assertEqual(
            [], missing,
            "these artifact types define times but name no database, so "
            "_detect_available_artifacts() never considers them and they plot "
            "nothing: %s" % missing)

    def test_every_database_key_has_timestamps(self):
        missing = sorted(set(artifact_map.ARTIFACT_DB_MAPPING)
                         - set(artifact_map.TIMESTAMP_MAPPINGS))
        self.assertEqual(
            [], missing,
            "these artifact types name a database but define no times, which "
            "logs one debug line and shows an empty lane: %s" % missing)

    def test_the_duplicate_maps_are_gone(self):
        """Both consumers must read this module, not a copy of their own.

        The manager and the indexer each carried their own literal, and the two
        drifted - different Shellbags spelling, different artifact sets, and a
        `UserAssist.focus_time` entry in one of them that is a DURATION.
        """
        for rel in (os.path.join("timeline", "data", "timeline_data_manager.py"),
                    os.path.join("timeline", "data", "timestamp_indexer.py")):
            path = os.path.join(REPO, rel)
            src = io.open(path, encoding="utf-8", errors="replace").read()
            self.assertIn(
                "_artifact_map.TIMESTAMP_MAPPINGS", src,
                "%s defines its own copy of the timestamp map instead of "
                "reading artifact_map" % rel)


class EntriesAreWellFormed(unittest.TestCase):

    def test_shapes_and_kinds(self):
        for artifact, entries in artifact_map.TIMESTAMP_MAPPINGS.items():
            for entry in entries:
                self.assertIn(
                    len(entry), (3, 4, 5),
                    "%s: %r is not (table, column, kind[, description"
                    "[, basis]])" % (artifact, entry))
                self.assertIn(
                    entry[2], KNOWN_KINDS,
                    "%s.%s: kind %r is not one the front end can draw"
                    % (artifact, entry[0], entry[2]))

    def test_no_duplicate_table_column_within_an_artifact(self):
        for artifact, entries in artifact_map.TIMESTAMP_MAPPINGS.items():
            seen = [(e[0], e[1]) for e in entries]
            dupes = sorted({p for p in seen if seen.count(p) > 1})
            self.assertEqual(
                [], dupes,
                "%s plots the same column twice, so every one of those rows "
                "gets two markers: %s" % (artifact, dupes))

    def test_every_key_write_column_is_marked_bounded(self):
        """A key write time has to say it is one.

        `is_key_time` is what makes a row arrive at the front end tagged
        `bounded_time`, which is what draws it hollow. An entry that is not
        marked is plotted as an exact moment, which is a claim the evidence
        does not support: writing any value under a key updates the whole key,
        so the time belongs to all of them and dates none of them.
        """
        for artifact, entries in artifact_map.TIMESTAMP_MAPPINGS.items():
            for entry in entries:
                if entry[1] in ("last_written", "last_write", "key_last_write"):
                    self.assertTrue(
                        artifact_map.is_key_time(entry),
                        "%s.%s.%s is a KEY write time and is not marked as "
                        "one, so it would be drawn as an exact time"
                        % (artifact, entry[0], entry[1]))

    def test_record_times_are_not_marked_bounded(self):
        """And the converse, which is how NetworkProfiles nearly went wrong.

        That table carries both: `date_created` and `date_last_connected` are
        the profile's own times, `last_written` is its key's. Marking the whole
        TABLE bounded would have drawn the two exact ones hollow.
        """
        for artifact, entries in artifact_map.TIMESTAMP_MAPPINGS.items():
            for entry in entries:
                if entry[1] in ("last_written", "last_write", "key_last_write"):
                    continue
                self.assertFalse(
                    artifact_map.is_key_time(entry),
                    "%s.%s.%s is the record's own time and is marked as a key "
                    "upper bound" % (artifact, entry[0], entry[1]))


class MappingsResolveAgainstTheParserSource(unittest.TestCase):
    """Every registry mapping must name a table and column Regclaw writes.

    Five did not: `MUICache.timestamp` (the legacy name for what is now
    `parsed_at`, and never an event time), `Auto.*` (an abandoned draft of
    WindowsUpdateInfo that nothing inserts into), `NetworkListProfiles`, and
    `NetworkInterfacesInfo.timestamp`. Each plotted nothing and reported
    nothing.
    """

    @classmethod
    def setUpClass(cls):
        cls.schema = registry_schema()

    def test_schema_extraction_found_the_registry_tables(self):
        # A silent extraction failure would make every check below vacuous.
        self.assertGreater(
            len(self.schema), 80,
            "only %d registry tables came out of the parser source - the DDL "
            "scan is broken, and every check that reads it is passing by "
            "finding nothing" % len(self.schema))

    def test_registry_tables_and_columns_exist(self):
        bad = []
        for entry in artifact_map.TIMESTAMP_MAPPINGS["Registry"]:
            table, column = entry[0], entry[1]
            if table not in self.schema:
                bad.append("%s: no such table in the parser" % table)
            elif column not in self.schema[table]:
                bad.append("%s.%s: no such column" % (table, column))
        self.assertEqual([], bad, "\n  ".join([""] + bad))

    def test_basis_columns_exist_where_named(self):
        """An entry may name no basis column; naming a missing one is fatal.

        Selecting a column the table does not have raises inside the bridge's
        try/except: one log line, an empty section, and no error anywhere the
        analyst can see.
        """
        bad = []
        for entry in artifact_map.TIMESTAMP_MAPPINGS["Registry"]:
            basis = artifact_map.basis_column(entry)
            if basis and basis not in self.schema.get(entry[0], []):
                bad.append("%s.%s names basis column %s, which the parser "
                           "does not write" % (entry[0], entry[1], basis))
        self.assertEqual([], bad, "\n  ".join([""] + bad))

    def test_parsed_at_is_never_plotted(self):
        """`parsed_at` is when the parser ran, not when anything happened."""
        for artifact, entries in artifact_map.TIMESTAMP_MAPPINGS.items():
            for entry in entries:
                self.assertNotIn(
                    entry[1], ("parsed_at", "timestamp_parsed"),
                    "%s.%s plots the parser's own bookkeeping column as an "
                    "event time" % (artifact, entry[0]))


class EveryOtherDatabaseResolvesToo(unittest.TestCase):
    """The same check, for the databases that are not the registry.

    Only the registry was guarded, and the three gaps found when this was
    written were all outside it: the whole of `Log_Claw.db` (43,802 event log
    records), `mft_usn_correlated_analysis.db`, and `mft_file_names` - the
    $FILE_NAME times, which is the pair an examiner compares against $SI to
    spot timestomping.
    """

    @classmethod
    def setUpClass(cls):
        cls.schemas = {db: _schema_from(paths)
                       for db, paths in OTHER_PARSERS.items()}

    def test_the_scan_read_each_parser(self):
        empty = sorted(db for db, sch in self.schemas.items() if not sch)
        self.assertEqual(
            [], empty,
            "no tables came out of the parser source for these databases, so "
            "every check below passes by finding nothing: %s" % empty)

    def test_tables_and_columns_exist(self):
        bad = []
        for artifact, entries in artifact_map.TIMESTAMP_MAPPINGS.items():
            db = artifact_map.ARTIFACT_DB_MAPPING.get(artifact)
            schema = self.schemas.get(db)
            if schema is None:
                continue        # the registry, covered by the class above
            for entry in entries:
                table, column = entry[0], entry[1]
                if table not in schema:
                    bad.append("%s: %s: no such table in %s"
                               % (artifact, table, db))
                elif column not in schema[table]:
                    bad.append("%s: %s.%s: no such column in %s"
                               % (artifact, table, column, db))
        self.assertEqual([], bad, "\n  ".join([""] + bad))

    def test_mft_standard_info_is_not_mapped(self):
        """It duplicates `mft_records` exactly - 199,533 of 199,533 rows agree.

        Mapping it would draw every MFT marker twice, and the second copy would
        look like corroboration from a second source rather than the same
        four values read out of the same attribute.
        """
        mapped = {e[0] for e in artifact_map.TIMESTAMP_MAPPINGS["MFT"]}
        self.assertNotIn(
            "mft_standard_info", mapped,
            "mft_standard_info holds the same $SI times as mft_records; "
            "mapping it doubles every MFT marker")


class SignificantEventIdsAreUsable(unittest.TestCase):
    """The curated event IDs must name a real log table and say what they mean.

    An ID filed under the wrong table produces a query that runs, matches
    nothing, and reports nothing.
    """

    def test_every_id_names_a_real_log_table(self):
        bad = [(i, log) for i, (log, _label)
               in artifact_map.SIGNIFICANT_EVENT_IDS.items()
               if log not in artifact_map.EVENT_LOG_TABLES]
        self.assertEqual([], bad, "unknown log table for: %s" % bad)

    def test_every_id_has_a_label_in_words(self):
        """`7045` on a marker tells an examiner nothing."""
        bad = [i for i, (_log, label)
               in artifact_map.SIGNIFICANT_EVENT_IDS.items()
               if not label or label.strip().isdigit() or len(label) < 4]
        self.assertEqual([], bad, "no usable label for: %s" % bad)

    def test_the_log_tables_are_mapped(self):
        mapped = {e[0] for e in artifact_map.TIMESTAMP_MAPPINGS.get("Logs", [])}
        self.assertEqual(
            set(artifact_map.EVENT_LOG_TABLES), mapped,
            "the event log tables the curated IDs name are not the ones the "
            "map plots")


class BridgeKeyTimeSourcesMatchTheMap(unittest.TestCase):
    """`_KEY_TIME_LABELS` in the bridge is the React half of the same list.

    The bridge builds one query per table from the map's time column and this
    dict's label and path columns. A column the parser renamed makes that
    query raise inside the bridge's try/except: one log line, an empty
    section, and nothing that reads as an error.
    """

    @classmethod
    def setUpClass(cls):
        cls.schema = registry_schema()
        from timeline.timeline_bridge import TimelineBridge
        cls.labels = TimelineBridge._KEY_TIME_LABELS

    def test_every_labelled_table_is_a_key_time_table(self):
        key_tables = {t for t, _c, _k, _b in artifact_map._KEY_TIME_TABLES}
        bad = sorted(set(self.labels) - key_tables)
        self.assertEqual(
            [], bad,
            "the bridge would draw these as bounded key times, but the map "
            "does not list them as key-time tables - so either they are exact "
            "times being drawn hollow, or they are drawn by rules nothing "
            "else agrees with: %s" % bad)

    def test_label_and_path_columns_exist(self):
        """Both columns the query names, checked against the parser source.

        `local_groups` has no `key_path`, which is why the path column is
        per-table and nullable rather than assumed. Selecting `key_path` from
        it unconditionally is exactly the kind of thing that fails in silence.
        """
        bad = []
        for table, (label, name_col, path_col) in sorted(self.labels.items()):
            cols = self.schema.get(table)
            if cols is None:
                bad.append("%s (%s): no such table" % (table, label))
                continue
            if name_col not in cols:
                bad.append("%s.%s (%s): no such column"
                           % (table, name_col, label))
            if path_col is not None and path_col not in cols:
                bad.append("%s.%s (%s): no such path column"
                           % (table, path_col, label))
        self.assertEqual([], bad, "\n  ".join([""] + bad))

    def test_mru_tables_are_not_drawn_twice(self):
        """The MRU tables are key times AND have their own bridge queries.

        Giving one a label here would draw every MRU row a second time, once
        under its own name and once as a generic key time.
        """
        mru = {"OpenSaveMRU", "LastSaveMRU", "RunMRU", "WordWheelQuery",
               "TypedPaths", "RecentDocs"}
        clash = sorted(mru & set(self.labels))
        self.assertEqual(
            [], clash,
            "these tables have a dedicated bridge query already, so a label "
            "here plots each of their rows twice: %s" % clash)


if __name__ == "__main__":
    unittest.main(verbosity=2)
