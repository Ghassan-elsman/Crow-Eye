r"""`query_user_behavior` - Eye runs UBA, wired everywhere.

An Eye tool lives in six places, and missing one fails quietly (see
test_query_timeline_tool.py for what each absence does). The registration
checks read the source; the behaviour checks run the handler on the UBA
suite's own schema-accurate fixture case.
"""
import io
import json
import os
import pathlib
import sys
import threading
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

TOOL = "query_user_behavior"


def _read(*parts):
    return io.open(os.path.join(REPO, *parts), encoding="utf-8", errors="replace").read()


class TheToolIsRegisteredEverywhere(unittest.TestCase):

    def test_the_model_is_told_it_exists(self):
        cfg = json.loads(_read("configs", "llm_config.json"))
        tool = next((t for t in cfg["tools"] if t.get("name") == TOOL), None)
        self.assertIsNotNone(tool, "not in llm_config.json tools[]")
        props = tool["parameters"]["properties"]
        for p in ("day", "start_time", "end_time", "users", "activities",
                  "severities", "summary_only", "limit"):
            self.assertIn(p, props, "%s is not offered to the model" % p)
        self.assertGreater(len(tool["description"]), 300)

    def test_it_is_dispatched(self):
        self.assertIn('"%s": f.handle_%s' % (TOOL, TOOL),
                      _read("eye", "services", "context_manager.py"))

    def test_constrained_models_keep_it(self):
        src = _read("eye", "services", "context_manager.py")
        block = src[src.index("essential_names = ["):]
        self.assertIn(TOOL, block[:block.index("]")])

    def test_it_counts_as_investigation(self):
        src = _read("eye", "services", "query_processor.py")
        block = src[src.index("_INVESTIGATIVE_TOOLS = {"):]
        self.assertIn(TOOL, block[:block.index("}")])

    def test_its_results_carry_provenance(self):
        self.assertIn('name == "%s"' % TOOL, _read("eye", "services", "evidence_seal.py"))

    def test_it_is_documented(self):
        self.assertIn(TOOL, _read("eye", "docs", "eye_tools_reference.md"))
        # The EXE tree (the one with update/) keeps an old README snapshot by design.
        if not os.path.isdir(os.path.join(REPO, "update")):
            self.assertIn(TOOL, _read("README.md"))

    def test_the_prompt_says_when_to_use_it(self):
        self.assertIn("USE `%s`" % TOOL, _read("eye", "services", "context_manager.py"))


class _Cm:
    """What the handler reaches for on the ContextManager."""

    def __init__(self, case):
        self.case_directory = case


class TheHandlerAnswers(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import tempfile
        from uba.tests import conftest
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="eye_uba_"))
        conftest.artifacts_dir.__wrapped__(tmp)          # writes tmp/Target_Artifacts
        # Marked synthetic: test_query_timeline_tool picks "the newest case" in
        # TEMP, and this one would win with nothing but a few fixture rows.
        (tmp / "Target_Artifacts" / "NOT_A_REAL_CASE").write_text("fixture", encoding="utf-8")
        cls.tmp = tmp
        cls.case = str(tmp)
        from eye.services.forensic_handlers import ForensicHandlers
        cls.cm = _Cm(cls.case)
        cls.h = ForensicHandlers(cls.cm)
        cls.all = cls.h.handle_query_user_behavior({"limit": 300})

    @classmethod
    def tearDownClass(cls):
        import shutil
        engine = (getattr(cls.cm, "_uba_cache", None) or {}).get("engine")
        if engine is not None:
            engine.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_it_runs_once_and_finds_behaviour(self):
        r = self.all
        self.assertTrue(r["success"], r.get("error"))
        self.assertGreater(r["total_matching"], 0)
        again = self.h.handle_query_user_behavior({"summary_only": True})
        self.assertFalse(again["analysis"]["ran_now"], "the analysis ran twice")

    def test_a_day_filter_keeps_to_that_day(self):
        days = sorted({e["time"][:10] for e in self.all["events"] if e.get("time")})
        self.assertTrue(days)
        r = self.h.handle_query_user_behavior({"day": days[0]})
        self.assertTrue(r["success"], r.get("error"))
        self.assertTrue(r["events"])
        self.assertTrue(all(e["time"][:10] == days[0] for e in r["events"]))
        self.assertEqual(r["window"]["start"], days[0] + " 00:00:00")

    def test_summary_only_has_no_events(self):
        r = self.h.handle_query_user_behavior({"summary_only": True})
        self.assertNotIn("events", r)
        self.assertTrue(r["summary"]["by_activity"])

    def test_every_event_points_at_its_rows(self):
        with_ev = [e for e in self.all["events"] if e["evidence"]]
        self.assertTrue(with_ev, "no event carries evidence")
        ev = with_ev[0]["evidence"][0]
        self.assertTrue(ev["database"].endswith(".db"),
                        "a logical name ('registry') cannot be handed to query_database")
        self.assertTrue(ev["table"])

    def test_the_seal_records_it(self):
        from eye.services.evidence_seal import EvidenceSeal
        refs = EvidenceSeal.extract_evidence_refs(
            [{"tool_name": TOOL, "success": True, "result": self.all}])
        ref = next(r for r in refs if r.get("tool") == TOOL)
        self.assertEqual(ref["row_count"], len(self.all["events"]))
        self.assertTrue(ref["rules_fired"])
        self.assertTrue(ref["evidence_pointers"])

    def test_a_reparse_reruns_the_analysis(self):
        db = next(pathlib.Path(self.case, "Target_Artifacts").glob("*.db"))
        st = db.stat()
        os.utime(db, (st.st_atime, st.st_mtime + 10))
        r = self.h.handle_query_user_behavior({"summary_only": True})
        self.assertTrue(r["analysis"]["ran_now"])

    def test_each_call_closes_its_thread_connections(self):
        out = {}

        def worker():
            out["r"] = self.h.handle_query_user_behavior({"summary_only": True})
        t = threading.Thread(target=worker)
        t.start(); t.join()
        self.assertTrue(out["r"]["success"])
        engine = self.cm._uba_cache["engine"]
        idents = {k[0] for k in getattr(engine.db_pool, "_conns", {})}
        self.assertNotIn(t.ident, idents, "a finished Eye thread left connections open")

    def test_no_case_is_an_error_not_a_crash(self):
        from eye.services.forensic_handlers import ForensicHandlers
        r = ForensicHandlers(_Cm(None)).handle_query_user_behavior({})
        self.assertFalse(r["success"])
