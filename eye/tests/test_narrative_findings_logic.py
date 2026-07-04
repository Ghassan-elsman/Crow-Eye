"""
Logic test for the narrative-tree builder
(`QueryProcessor._sync_narratives_from_findings`).

Regression: an INCONCLUSIVE sub-question must become a `negative` finding — never
`proven` — even when its reasoning-trace conclusion text is non-empty and a tool
result keyword-matches it (the `or conclusion` clause used to defeat the
inconclusive guard). An `answered` sub-question with matching evidence stays
`proven`.
"""

import logging
import types
import unittest

from eye.services.query_processor import QueryProcessor
from eye.services.narrative_map_service import NarrativeMapService


def _make_qp():
    qp = QueryProcessor.__new__(QueryProcessor)
    qp.logger = logging.getLogger("test-qp")
    cm = types.SimpleNamespace()
    cm.narrative_map_service = NarrativeMapService(None, model_name="gemma-test")
    cm.model_router = types.SimpleNamespace(config={"model_name": "gemma-test"})
    qp.cm = cm
    return qp, cm.narrative_map_service


class TestClaimify(unittest.TestCase):
    """A card title must be a clean CLAIM — never the raw, possibly typo-ridden question."""

    def test_interrogative_becomes_whether_claim(self):
        self.assertEqual(QueryProcessor._claimify("Is X malicious?"), "Whether X malicious")
        self.assertEqual(QueryProcessor._claimify("did the user run powershell?"),
                         "Whether the user run powershell")

    def test_declarative_passes_through_capitalized(self):
        self.assertEqual(QueryProcessor._claimify("the binary established persistence"),
                         "The binary established persistence")

    def test_strips_markdown_quotes_and_whitespace(self):
        self.assertEqual(QueryProcessor._claimify('  **"is  x   bad?"**  '), "Whether x bad")

    def test_empty_returns_empty(self):
        self.assertEqual(QueryProcessor._claimify(""), "")
        self.assertEqual(QueryProcessor._claimify("???"), "")


class TestFourLevelHierarchy(unittest.TestCase):
    """Verdict(goal-claim) → main(sub-question claim) → sub(behavior) → evidence,
    and NO card title ever equals the raw user question."""

    def test_behaviors_build_sub_narratives_and_roll_up(self):
        qp, nms = _make_qp()
        raw_q = "is x.exe malisous??"  # intentionally messy/typo
        checklist = [{"q": raw_q, "status": "answered", "kind": "question", "why": ""}]
        all_tool_results = [
            {"tool_name": "query_database", "success": True,
             "result": {"columns": ["v"], "data": [{"v": "run key persistence x.exe"}]},
             "parameters": {"sql_query": "SELECT v FROM reg", "database_name": "reg.db"}},
        ]
        trace = {"sub_questions": [{
            "conclusion": "x.exe established persistence",
            "status": "answered",
            "behaviors": [
                {"claim": "wrote a Run registry key for persistence", "why": "key present",
                 "evidence": [{"ref": "reg.db:run:1", "note": "HKCU\\...\\Run\\x"}]},
                {"claim": "set itself to auto-start at logon", "why": "logon scope",
                 "evidence": [{"ref": "reg.db:run:2", "note": "logon"}]},
            ],
        }]}
        qp._sync_narratives_from_findings(
            checklist, all_tool_results, trace, lambda *a, **k: None,
            "is x.exe malisous??", "x.exe is malicious.")

        g = nms.load_graph()
        narrs = g["narratives"]
        titles = [n.get("title", "") for n in narrs]
        # The raw question text must NEVER appear as a card title.
        self.assertNotIn(raw_q, titles)
        # Main narrative = the conclusion claim, created_from = raw question (provenance).
        main = next(n for n in narrs if (n.get("meta") or {}).get("created_from") == raw_q)
        self.assertEqual(main["title"], "x.exe established persistence")
        self.assertEqual(main["state"], "proven")  # rolled up from proven behaviors
        # Two behavior sub-narratives, each proven, linked UNDER the main.
        subs = [n for n in narrs if (n.get("meta") or {}).get("parent") == main["id"]]
        self.assertEqual(len(subs), 2)
        self.assertTrue(all(s["state"] == "proven" for s in subs))
        self.assertIn("wrote a Run registry key for persistence",
                      [s["title"] for s in subs])

    def test_verdict_becomes_goal_claim_and_proven(self):
        qp, nms = _make_qp()
        raw_q = "is x.exe malisous??"
        checklist = [{"q": raw_q, "status": "answered", "kind": "question", "why": ""}]
        all_tool_results = [
            {"tool_name": "query_database", "success": True,
             "result": {"columns": ["v"], "data": [{"v": "persistence x.exe run key"}]},
             "parameters": {"sql_query": "SELECT v FROM reg", "database_name": "reg.db"}},
        ]
        trace = {"sub_questions": [{
            "conclusion": "x.exe established persistence", "status": "answered",
            "behaviors": [{"claim": "wrote a Run registry key", "why": "k",
                           "evidence": [{"ref": "reg.db:run:1", "note": "x"}]}],
        }]}
        qp._sync_narratives_from_findings(
            checklist, all_tool_results, trace, lambda *a, **k: None, raw_q, "x.exe is malicious.")
        # No AI VERDICT directive → goal-claim derived from the question.
        qp._finalize_verdict("x.exe is malicious.", raw_q)

        v = nms.load_graph()["verdict"]
        self.assertEqual(v["title"], "Whether x.exe malisous")  # claim, not the raw question
        self.assertNotIn("?", v["title"])
        self.assertEqual(v["state"], "proven")

    def test_verdict_unproven_when_no_main_established(self):
        qp, nms = _make_qp()
        raw_q = "did x.exe exfiltrate data?"
        checklist = [{"q": raw_q, "status": "answered", "kind": "question", "why": ""}]
        trace = {"sub_questions": [{"conclusion": "no evidence of exfiltration",
                                    "status": "inconclusive", "behaviors": []}]}
        qp._sync_narratives_from_findings(
            checklist, [], trace, lambda *a, **k: None, raw_q, "No exfiltration found.")
        qp._finalize_verdict("No exfiltration found.", raw_q)
        v = nms.load_graph()["verdict"]
        self.assertEqual(v["state"], "unproven")


class TestMapChecklistForSimpleQuestions(unittest.TestCase):
    """A non-decomposed but investigative turn must still reach the map: the Eye's
    logical thinking is linked even when the planner produced no sub-question."""

    _OK = [{"tool_name": "query_database", "success": True,
            "result": {"columns": ["v"], "data": [{"v": "x"}]}}]

    def test_no_decomposition_with_results_adds_one_synthetic_claim(self):
        out = QueryProcessor._build_map_checklist([], "is x.exe malisous??", self._OK)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["q"], "is x.exe malisous??")
        self.assertEqual(out[0]["kind"], "question")

    def test_no_results_stays_off_the_map(self):
        self.assertEqual(QueryProcessor._build_map_checklist([], "hello", []), [])
        # A failed tool call is not a result either.
        failed = [{"tool_name": "query_database", "success": False, "result": {"success": False}}]
        self.assertEqual(QueryProcessor._build_map_checklist([], "hello", failed), [])

    def test_premise_only_checklist_still_gets_a_claim(self):
        premises = [{"q": "verify: user said X", "status": "open", "kind": "premise"}]
        out = QueryProcessor._build_map_checklist(premises, "is x bad?", self._OK)
        self.assertEqual(len(out), 2)  # premise preserved + synthetic question
        self.assertTrue(any(c.get("kind") == "question" for c in out))

    def test_decomposed_checklist_is_untouched(self):
        decomposed = [
            {"q": "did it persist?", "status": "open", "kind": "question", "why": ""},
            {"q": "did it exfiltrate?", "status": "open", "kind": "question", "why": ""},
        ]
        out = QueryProcessor._build_map_checklist(decomposed, "overall?", self._OK)
        self.assertEqual([c["q"] for c in out], ["did it persist?", "did it exfiltrate?"])

    def test_full_simple_question_path_builds_verdict_and_claim(self):
        """End-to-end: the synthetic claim flows through the real sync + finalize."""
        qp, nms = _make_qp()
        raw_q = "is x.exe malisous??"
        all_tool_results = [
            {"tool_name": "query_database", "success": True,
             "result": {"columns": ["v"], "data": [{"v": "run key persistence x.exe"}]},
             "parameters": {"sql_query": "SELECT v FROM reg", "database_name": "reg.db"}},
        ]
        map_checklist = QueryProcessor._build_map_checklist([], raw_q, all_tool_results)
        trace = {"sub_questions": [{
            "conclusion": "x.exe established persistence", "status": "answered",
            "behaviors": [{"claim": "wrote a Run registry key", "why": "k",
                           "evidence": [{"ref": "reg.db:run:1", "note": "x"}]}],
        }]}
        qp._sync_narratives_from_findings(
            map_checklist, all_tool_results, trace, lambda *a, **k: None, raw_q, "x.exe is malicious.")
        qp._finalize_verdict("x.exe is malicious.", raw_q)

        g = nms.load_graph()
        titles = [n.get("title", "") for n in g["narratives"]]
        self.assertNotIn(raw_q, titles)  # never the raw question
        main = next(n for n in g["narratives"]
                    if (n.get("meta") or {}).get("created_from") == raw_q)
        self.assertEqual(main["title"], "x.exe established persistence")
        self.assertEqual(main["state"], "proven")
        self.assertEqual(g["verdict"]["title"], "Whether x.exe malisous")
        self.assertEqual(g["verdict"]["state"], "proven")


class TestInconclusiveIsNotProven(unittest.TestCase):
    def test_inconclusive_subquestion_is_negative_answered_is_proven(self):
        qp, nms = _make_qp()
        checklist = [
            {"q": "Did Discord exfiltrate files?", "status": "answered", "kind": "question", "why": ""},
            {"q": "Was the account the suspect?", "status": "answered", "kind": "question", "why": ""},
        ]
        all_tool_results = [
            {"tool_name": "query_database", "success": True,
             "result": {"columns": ["info"], "data": [{"info": "discord exfiltrate files srum egress"}]},
             "parameters": {"sql_query": "SELECT info FROM srum", "database_name": "srum.db"}},
            {"tool_name": "query_database", "success": True,
             "result": {"columns": ["info"], "data": [{"info": "account suspect attribution match"}]},
             "parameters": {"sql_query": "SELECT info FROM acct", "database_name": "reg.db"}},
        ]
        # Sub-question 1 has a NON-EMPTY conclusion but status=inconclusive → must be negative.
        trace = {"sub_questions": [
            {"conclusion": "Discord may have exfiltrated files but it is unconfirmed",
             "status": "inconclusive"},
            {"conclusion": "The account belongs to the suspect", "status": "answered"},
        ]}
        qp._sync_narratives_from_findings(
            checklist, all_tool_results, trace, lambda *a, **k: None,
            "Investigate Discord exfiltration overall", "Discord exfiltration is unconfirmed.")

        by_origin = {(n.get("meta") or {}).get("created_from"): n
                     for n in nms.load_graph()["narratives"]}
        self.assertEqual(by_origin["Did Discord exfiltrate files?"]["state"], "negative")
        self.assertEqual(by_origin["Was the account the suspect?"]["state"], "proven")


if __name__ == "__main__":
    unittest.main()
