r"""`query_timeline` must be wired everywhere, and answer honestly.

A tool in Crow-Eye's Eye is wired in six places and missing any one of them
fails quietly rather than loudly:

  * absent from `configs/llm_config.json` -> the model never sees it exists;
  * absent from `_initialize_tool_handlers` -> the call is refused as unknown;
  * absent from `essential_names` -> constrained models silently lose it,
    which is precisely where a time question hurts most;
  * absent from `_INVESTIGATIVE_TOOLS` -> GEP-1 records the turn as
    unproactive even though the model went looking;
  * absent from `extract_evidence_refs` -> the rows carry no provenance into
    the sealed record, so GEP-2 traceability finds nothing to point at;
  * absent from the docs -> nobody knows it is there.

The registration checks read the source, so a half-wired tool fails here
instead of at the first time question. The behaviour checks need a parsed case
and skip without one.
"""
import io
import json
import os
import sqlite3
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

TOOL = "query_timeline"


def _read(*parts):
    return io.open(os.path.join(REPO, *parts), encoding="utf-8",
                   errors="replace").read()


class TheToolIsRegisteredEverywhere(unittest.TestCase):

    def test_the_model_is_told_it_exists(self):
        cfg = json.loads(_read("configs", "llm_config.json"))
        names = [t.get("name") for t in cfg.get("tools", [])]
        self.assertIn(TOOL, names,
                      "not in llm_config.json tools[], so no model can call it")

    def test_its_schema_is_usable(self):
        cfg = json.loads(_read("configs", "llm_config.json"))
        tool = next(t for t in cfg["tools"] if t.get("name") == TOOL)
        props = tool["parameters"]["properties"]
        for p in ("start_time", "end_time", "around", "window_minutes",
                  "include_bounded"):
            self.assertIn(p, props, "%s is not offered to the model" % p)
        self.assertGreater(
            len(tool.get("description", "")), 200,
            "the description is what decides whether the model reaches for "
            "this instead of guessing a database, so it has to say when to "
            "use it and what the rows mean")

    def test_it_is_dispatched(self):
        src = _read("eye", "services", "context_manager.py")
        self.assertIn('"%s": f.handle_%s' % (TOOL, TOOL), src,
                      "no handler is mapped, so the call is refused")

    def test_constrained_models_keep_it(self):
        """A small local model is exactly who needs one call, not eleven."""
        src = _read("eye", "services", "context_manager.py")
        block = src[src.index("essential_names = ["):]
        self.assertIn(TOOL, block[:block.index("]")],
                      "dropped for constrained models")

    def test_it_counts_as_investigation(self):
        src = _read("eye", "services", "query_processor.py")
        block = src[src.index("_INVESTIGATIVE_TOOLS = {"):]
        self.assertIn(TOOL, block[:block.index("}")],
                      "GEP-1 would score a turn that used it as unproactive")

    def test_its_results_carry_provenance(self):
        src = _read("eye", "services", "evidence_seal.py")
        self.assertIn('name == "%s"' % TOOL, src,
                      "extract_evidence_refs has no branch, so the sealed "
                      "record gets no handle on the rows")

    def test_it_is_documented(self):
        self.assertIn(TOOL, _read("eye", "docs", "eye_tools_reference.md"))

    def test_the_handler_exists(self):
        from eye.services.forensic_handlers import ForensicHandlers
        self.assertTrue(hasattr(ForensicHandlers, "handle_%s" % TOOL))


def _find_case():
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
            # is NEWER than any real case, so it wins the `max()` below and
            # this suite then runs against four empty tables.
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


CASE = _find_case()


class _Stub:
    """The two attributes the handler actually reaches for."""

    def __init__(self, case):
        from eye.services.database_service import ForensicDatabaseService
        self.database_service = ForensicDatabaseService(case)
        self.case_directory = case


@unittest.skipIf(CASE is None, "no parsed case; set CROW_EYE_CASE_ROOT")
class TheSweepAnswersHonestly(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from eye.services.forensic_handlers import ForensicHandlers
        cls.h = ForensicHandlers(_Stub(CASE))
        cls.span = cls._case_span()

    @staticmethod
    def _case_span():
        """A window that actually contains something, whatever the case."""
        con = sqlite3.connect(
            "file:" + os.path.join(CASE, "registry_data.db").replace("\\", "/")
            + "?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT min(last_execution), max(last_execution) FROM BAM "
                "WHERE last_execution IS NOT NULL "
                "AND trim(last_execution) <> ''").fetchone()
        except sqlite3.Error:
            row = None
        finally:
            con.close()
        if not row or not row[0]:
            return None
        return {"start_time": row[0], "end_time": row[1]}

    def test_it_returns_events_from_more_than_one_source(self):
        """One call, several databases - that is the whole point of it."""
        if not self.span:
            self.skipTest("this case has no BAM execution times to span")
        r = self.h.handle_query_timeline(dict(self.span, limit=300))
        self.assertTrue(r["success"], r.get("error"))
        self.assertGreater(len(r["events"]), 0, "swept the case and found nothing")
        tables = {e["table"] for e in r["events"]}
        self.assertGreater(
            len(tables), 1,
            "every row came from %s - a sweep that reaches one table is a "
            "query_database call with extra steps" % tables)

    def test_events_come_back_in_time_order(self):
        """Formats differ per parser; sorting the raw strings interleaves them.

        The event log stores `2026-02-14 04:33:18` and the MFT stores
        `2026-02-14T04:26:23.916647+00:00`; as strings every `T` sorts after
        every space, so the chronology comes out wrong while looking fine.
        """
        if not self.span:
            self.skipTest("this case has no BAM execution times to span")
        r = self.h.handle_query_timeline(dict(self.span, limit=300))
        stamps = [e["timestamp"] for e in r["events"] if e["timestamp"]]
        self.assertEqual(sorted(stamps), stamps, "not in chronological order")

    def test_bounded_times_are_excluded_by_default(self):
        if not self.span:
            self.skipTest("this case has no BAM execution times to span")
        r = self.h.handle_query_timeline(dict(self.span, limit=300))
        bounded = [e for e in r["events"] if e["exactness"] != "exact"]
        self.assertEqual(
            [], bounded,
            "key upper bounds are in the default answer, where they read as "
            "moments: %s" % bounded[:3])
        self.assertIn("include_bounded", r["note"])

    def test_bounded_times_are_offered_and_labelled(self):
        r = self.h.handle_query_timeline({
            "start_time": "1970-01-01 00:00:00",
            "end_time": "2099-01-01 00:00:00",
            "include_bounded": True, "artifact_types": ["Registry"],
            "limit": 50})
        self.assertTrue(r["success"], r.get("error"))
        kinds = {e["exactness"] for e in r["events"]}
        self.assertIn(
            "key upper bound", kinds,
            "include_bounded returned no bounded rows from the registry, "
            "which holds thousands of them")

    def test_around_and_window_minutes_centre_correctly(self):
        r = self.h.handle_query_timeline(
            {"around": "2026-02-14 04:30:00", "window_minutes": 10})
        self.assertTrue(r["success"], r.get("error"))
        self.assertEqual("2026-02-14 04:20:00", r["window"]["start"])
        self.assertEqual("2026-02-14 04:40:00", r["window"]["end"])

    def test_it_says_what_it_searched(self):
        """"Nothing happened then" is a claim about what was looked at."""
        r = self.h.handle_query_timeline(
            {"around": "2026-02-14 04:30:00", "window_minutes": 1})
        self.assertTrue(r["success"], r.get("error"))
        self.assertIn("artifacts_searched", r)
        self.assertGreater(len(r["artifacts_searched"]), 1)

    def test_the_total_is_not_the_capped_count(self):
        """A cap that reports itself as the total tells the model it is done."""
        r = self.h.handle_query_timeline({
            "start_time": "1970-01-01 00:00:00",
            "end_time": "2099-01-01 00:00:00", "limit": 5})
        self.assertEqual(5, len(r["events"]))
        self.assertGreater(r["total_in_window"], 5)
        self.assertIn("of", r["note"])

    def test_bad_input_is_refused_rather_than_guessed(self):
        for params in ({}, {"around": "sometime last week"},
                       {"start_time": "yesterday", "end_time": "today"}):
            r = self.h.handle_query_timeline(params)
            self.assertFalse(r["success"], "accepted %r" % params)
            self.assertTrue(r.get("error"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
