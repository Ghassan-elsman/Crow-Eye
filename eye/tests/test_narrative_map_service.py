"""
Tests for NarrativeMapService — the Eye's persistent, sealed working memory.

Covers: GEP validation (R9 hard / R10 soft + exemption / eye-authorship), the
decomposition → narrative auto-sync + evidence attach/state-flip, investigator notes
flowing into the Tier A overview + Tier B slice, and the hash-chained audit
(append, verify, cross-session recovery, and seed normalization).
"""

import json
import tempfile
import unittest
from pathlib import Path

from eye.services.narrative_map_service import NarrativeMapService


class TestNarrativeMapGEP(unittest.TestCase):
    def setUp(self):
        self.svc = NarrativeMapService(None, model_name="gemma-test")

    def test_r9_reasonless_rejected(self):
        res = self.svc.commit({"action": "CREATE", "actor": "investigator",
                               "kind": "narrative", "id": "n1", "reason": "",
                               "object": {"id": "n1", "title": "x", "state": "needs",
                                          "authoredBy": "investigator", "evs": []}})
        self.assertFalse(res["ok"])
        self.assertEqual(res.get("rule"), "r9")

    def test_eye_proven_without_evidence_blocked(self):
        res = self.svc.commit({"action": "CREATE", "actor": "eye", "kind": "narrative",
                               "id": "n1", "reason": "should fail",
                               "object": {"id": "n1", "title": "x", "state": "proven",
                                          "authoredBy": "eye:m", "evs": []}})
        self.assertFalse(res["ok"])
        self.assertEqual(res.get("rule"), "r10")

    def test_eye_open_without_evidence_allowed(self):
        # A provisional 'open' theme is the investigating state — allowed empty.
        res = self.svc.commit({"action": "CREATE", "actor": "eye", "kind": "narrative",
                               "id": "n1", "reason": "provisional theme",
                               "object": {"id": "n1", "title": "x", "state": "open",
                                          "authoredBy": "eye:m", "evs": []}})
        self.assertTrue(res["ok"])

    def test_investigator_absolute_exempt_from_r10(self):
        res = self.svc.commit({"action": "CREATE", "actor": "investigator",
                               "kind": "narrative", "id": "n1",
                               "reason": "stipulated fact", "evidence": [],
                               "object": {"id": "n1", "title": "host is the suspect's",
                                          "state": "absolute", "authoredBy": "investigator",
                                          "evs": []}})
        self.assertTrue(res["ok"])
        self.assertEqual(res["audit"]["gep"]["r10"], "PASS")  # sanctioned exemption


class TestAutoSyncAndFlip(unittest.TestCase):
    def setUp(self):
        self.svc = NarrativeMapService(None, model_name="gemma-test")

    def test_sync_from_plan_creates_open_narratives(self):
        out = self.svc.sync_from_plan([
            {"q": "Was Discord installed?", "why": "presence"},
            {"q": "Did it run on 06-12?", "why": "timeline"},
        ])
        self.assertTrue(all(r["ok"] for r in out))
        g = self.svc.load_graph()
        self.assertEqual(len(g["narratives"]), 2)
        self.assertTrue(all(n["state"] == "open" for n in g["narratives"]))
        # idempotent by title
        self.svc.sync_from_plan([{"q": "Was Discord installed?", "why": "dup"}])
        self.assertEqual(len(self.svc.load_graph()["narratives"]), 2)

    def test_attach_evidence_flips_to_proven(self):
        self.svc.sync_from_plan([{"q": "Was Discord installed?", "why": "presence"}])
        self.svc.attach_evidence("Was Discord installed?", {
            "kicker": "amcache", "data": "Discord.exe present", "ref": "amcache:app:5"})
        n = self.svc._narrative_by_title("Was Discord installed?")
        self.assertEqual(n["state"], "proven")
        self.assertEqual(len(n["evs"]), 1)

    def test_detach_last_evidence_from_proven_eye_narrative_auto_negative(self):
        self.svc.sync_from_plan([{"q": "Did it run?", "why": "x"}])
        self.svc.attach_evidence("Did it run?", {"kicker": "prefetch", "data": "ran 3x", "ref": "pf:1"})
        n = self.svc._narrative_by_title("Did it run?")
        eid = n["evs"][0]
        res = self.svc.commit({"action": "DETACH", "actor": "investigator", "kind": "narrative",
                               "id": n["id"], "evidenceId": eid, "reason": "remove"})
        self.assertTrue(res["ok"])
        self.assertEqual(self.svc._narrative_by_title("Did it run?")["state"], "negative")


class TestNotesIntoContext(unittest.TestCase):
    def setUp(self):
        self.svc = NarrativeMapService(None, model_name="gemma-test")
        self.svc.sync_from_plan([
            {"q": "Was Discord used to exfiltrate files?", "why": "exfil"},
        ])
        self.svc.attach_evidence("Was Discord used to exfiltrate files?",
                                 {"kicker": "srum", "data": "4MB sent", "ref": "srum:net:1"})
        n = self.svc._narrative_by_title("Was Discord used to exfiltrate files?")
        self.svc.commit({"action": "NOTE", "actor": "investigator", "kind": "narrative",
                         "id": n["id"], "reason": "context",
                         "note": {"by": "investigator", "text": "this is the suspect's primary laptop"}})

    def test_overview_has_states_and_note_flag(self):
        ov = self.svc.overview_block()
        self.assertIn("Case Memory", ov)
        self.assertIn("VERDICT", ov)
        self.assertIn("PROVEN", ov)
        self.assertIn("note", ov.lower())  # the 📝note flag

    def test_relevant_slice_includes_investigator_note_verbatim(self):
        sl = self.svc.relevant_slice("did the suspect exfiltrate files via discord")
        self.assertIn("suspect's primary laptop", sl)
        self.assertIn("Investigator note", sl)

    def test_relevant_slice_empty_when_no_overlap(self):
        self.assertEqual(self.svc.relevant_slice("registry run keys persistence"), "")


class TestAuditChainPersistence(unittest.TestCase):
    def test_chain_verifies_and_recovers_across_sessions(self):
        with tempfile.TemporaryDirectory() as d:
            svc = NarrativeMapService(d, model_name="gemma-test")
            svc.sync_from_plan([{"q": "Q1?", "why": "a"}, {"q": "Q2?", "why": "b"}])
            self.assertTrue(svc.verify_chain())
            audit_path = Path(d) / "EYE_Logs" / "narrative_map_audit.jsonl"
            self.assertTrue(audit_path.exists())
            first_count = len(svc.recent_audit())

            # New instance over the same case dir resumes the chain continuously.
            svc2 = NarrativeMapService(d, model_name="gemma-test")
            self.assertTrue(svc2.verify_chain())
            svc2.commit({"action": "EDIT", "actor": "investigator", "kind": "verdict",
                         "id": "verdict", "reason": "tighten", "patch": {"title": "Final verdict"}})
            self.assertTrue(svc2.verify_chain())
            self.assertGreater(len(svc2.recent_audit()), first_count)

    def test_tamper_breaks_chain(self):
        with tempfile.TemporaryDirectory() as d:
            svc = NarrativeMapService(d, model_name="gemma-test")
            svc.sync_from_plan([{"q": "Q1?", "why": "a"}])
            p = Path(d) / "EYE_Logs" / "narrative_map_audit.jsonl"
            lines = p.read_text(encoding="utf-8").splitlines()
            rec = json.loads(lines[0]); rec["reason"] = "TAMPERED"
            lines[0] = json.dumps(rec)
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertFalse(NarrativeMapService(d, model_name="gemma-test").verify_chain())


class TestReorderLinkVerdict(unittest.TestCase):
    """Narrative reorder (MOVE), narrative<->narrative LINK/UNLINK, and Eye-authored verdict."""

    def setUp(self):
        self.svc = NarrativeMapService(None, model_name="gemma-test")
        self.svc.sync_from_plan([
            {"q": "A?", "why": "x"}, {"q": "B?", "why": "y"}, {"q": "C?", "why": "z"}])
        self.ids = [n["id"] for n in self.svc.load_graph()["narratives"]]

    def test_move_narrative_stores_xy(self):
        res = self.svc.commit({"action": "MOVE", "actor": "investigator",
                               "kind": "narrative", "id": self.ids[2], "x": 420, "y": 260,
                               "reason": "moved on the board"})
        self.assertTrue(res["ok"])
        n = next(x for x in self.svc.load_graph()["narratives"] if x["id"] == self.ids[2])
        self.assertEqual((n["x"], n["y"]), (420, 260))
        # order is unchanged (free placement, not reorder)
        self.assertEqual([x["id"] for x in self.svc.load_graph()["narratives"]], self.ids)

    def test_move_verdict_stores_xy(self):
        vid = self.svc.load_graph()["verdict"]["id"]
        res = self.svc.commit({"action": "MOVE", "actor": "investigator",
                               "kind": "verdict", "id": vid, "x": 900, "y": 300,
                               "reason": "moved verdict"})
        self.assertTrue(res["ok"])
        v = self.svc.load_graph()["verdict"]
        self.assertEqual((v["x"], v["y"]), (900, 300))

    def test_link_narrative_to_narrative_and_unlink(self):
        frm, to = self.ids[0], self.ids[1]
        res = self.svc.commit({"action": "LINK", "actor": "investigator", "kind": "narrative",
                               "id": frm, "from": frm, "to": to, "reason": "A supports B"})
        self.assertTrue(res["ok"])
        links = self.svc.load_graph()["links"]
        match = [l for l in links if l["from"] == frm and l["to"] == to]
        self.assertEqual(len(match), 1)

        res2 = self.svc.commit({"action": "UNLINK", "actor": "investigator", "kind": "narrative",
                                "id": frm, "link_id": match[0]["id"], "reason": "remove link"})
        self.assertTrue(res2["ok"])
        self.assertFalse(any(l["from"] == frm and l["to"] == to
                             for l in self.svc.load_graph()["links"]))

    def test_link_rejects_self_link(self):
        before = len(self.svc.load_graph()["links"])
        self.svc.commit({"action": "LINK", "actor": "investigator", "kind": "narrative",
                         "id": self.ids[0], "from": self.ids[0], "to": self.ids[0],
                         "reason": "self"})
        self.assertEqual(len(self.svc.load_graph()["links"]), before)

    def test_set_verdict_is_eye_authored_and_editable(self):
        res = self.svc.set_verdict("Discord exfiltrated files",
                                   "Based on SRUM egress + prefetch execution")
        self.assertTrue(res["ok"])
        v = self.svc.load_graph()["verdict"]
        self.assertEqual(v["title"], "Discord exfiltrated files")
        self.assertIn("SRUM", v["reason"])
        self.assertTrue(str(v["authoredBy"]).startswith("eye"))
        # Investigator can still override it via the normal EDIT path.
        self.svc.commit({"action": "EDIT", "actor": "investigator", "kind": "verdict",
                         "id": v["id"], "reason": "manual", "patch": {"title": "Investigator verdict"}})
        self.assertEqual(self.svc.load_graph()["verdict"]["title"], "Investigator verdict")


class TestFindingNarratives(unittest.TestCase):
    """Findings-not-questions: upsert_finding_narrative + meta.created_from provenance."""

    def setUp(self):
        self.svc = NarrativeMapService(None, model_name="gemma-test")

    def test_created_evidence_is_stamped_with_chain_of_custody_seal(self):
        # Every evidence card must carry the seal hash of its CREATE audit record
        # so the map/Compliance view shows it sealed (and it ties back to the log).
        n1 = self.svc.upsert_finding_narrative(
            "Finding 1", "r", "Q1?", evidence=[{"kicker": "pf", "data": "a", "ref": "pf:1"}])
        n2 = self.svc.upsert_finding_narrative(
            "Finding 2", "r", "Q2?", evidence=[{"kicker": "amcache", "data": "b", "ref": "am:2"}])
        evs = list(self.svc.load_graph()["evidence"].values())
        self.assertEqual(len(evs), 2)
        for e in evs:
            self.assertTrue(e.get("sealed"), "evidence card is missing its chain-of-custody seal")
        # Distinct seals → the hash chain advanced between the two creates.
        self.assertNotEqual(evs[0]["sealed"], evs[1]["sealed"])
        # The seal is a 16-char SHA-256 prefix (a real handle into the audit chain).
        for e in evs:
            self.assertEqual(len(e["sealed"]), 16)
            int(e["sealed"], 16)  # raises ValueError if not hex

    def test_created_evidence_seal_matches_audit_log(self):
        # With a case dir, the stamped seal is a real prefix of the CREATE audit hash.
        with tempfile.TemporaryDirectory() as d:
            svc = NarrativeMapService(d, model_name="gemma-test")
            svc.upsert_finding_narrative("F", "r", "Q?",
                                         evidence=[{"kicker": "pf", "data": "a", "ref": "pf:1"}])
            ev = next(iter(svc.load_graph()["evidence"].values()))
            self.assertTrue(ev.get("sealed"))
            audit_hashes = {a.get("hash", "")[:16] for a in svc.recent_audit()}
            self.assertIn(ev["sealed"], audit_hashes)

    def test_evidence_carries_source_query_and_database(self):
        # The Eye stores the SQL + database so the map can reload the source rows.
        nid = self.svc.upsert_finding_narrative(
            "Discord ran", "why", "Was Discord run?",
            evidence=[{"kicker": "prefetch", "data": "rows", "ref": "query_database",
                       "query": "SELECT * FROM prefetch_runs", "database": "prefetch_data.db"}])
        ev = next(iter(self.svc.load_graph()["evidence"].values()))
        self.assertEqual(ev["query"], "SELECT * FROM prefetch_runs")
        self.assertEqual(ev["database"], "prefetch_data.db")

    def test_proven_finding_with_evidence(self):
        nid = self.svc.upsert_finding_narrative(
            "Discord ran 3× on 06-12", "Prefetch shows 3 executions",
            "Was Discord run?",
            evidence=[{"kicker": "prefetch", "data": "DISCORD.EXE x3", "ref": "pf:1"}])
        n = next(x for x in self.svc.load_graph()["narratives"] if x["id"] == nid)
        self.assertEqual(n["title"], "Discord ran 3× on 06-12")  # finding, NOT the question
        self.assertEqual(n["state"], "proven")
        self.assertEqual(n["meta"]["created_from"], "Was Discord run?")
        self.assertEqual(len(n["evs"]), 1)

    def test_negative_finding_without_evidence(self):
        nid = self.svc.upsert_finding_narrative(
            "No persistence established", "Checked Run keys",
            "Any persistence?", evidence=[], state="negative")
        n = next(x for x in self.svc.load_graph()["narratives"] if x["id"] == nid)
        self.assertEqual(n["state"], "negative")
        self.assertEqual(n["meta"]["created_from"], "Any persistence?")

    def test_idempotent_by_created_from(self):
        a = self.svc.upsert_finding_narrative("Finding A", "r", "Q?",
                                              evidence=[{"kicker": "x", "data": "d", "ref": "x:1"}])
        b = self.svc.upsert_finding_narrative("Finding A (updated)", "r2", "Q?")
        self.assertEqual(a, b)  # same originating question → same narrative, updated
        self.assertEqual(len(self.svc.load_graph()["narratives"]), 1)
        self.assertEqual(self.svc.load_graph()["narratives"][0]["title"], "Finding A (updated)")

    def test_meta_survives_normalize(self):
        seed = {
            "narratives": [{"id": "n1", "title": "Finding", "state": "proven",
                            "authoredBy": "eye:m", "evs": [], "meta": {"created_from": "Orig Q?"}}],
            "evidence": {}, "links": [], "verdict": {"id": "verdict", "title": "V"},
        }
        g = NarrativeMapService._normalize_graph(seed)
        self.assertEqual(g["narratives"][0]["meta"]["created_from"], "Orig Q?")


class TestHierarchy(unittest.TestCase):
    """Tree: a main narrative with sub-narrative children (parent links + proven-by-children)."""

    def setUp(self):
        self.svc = NarrativeMapService(None, model_name="gemma-test")

    def test_child_links_to_parent_not_verdict(self):
        main = self.svc.upsert_finding_narrative("Main finding", "overall", "MAIN?",
                                                 evidence=[], state="open")
        sub = self.svc.upsert_finding_narrative(
            "Sub finding", "why", "SUB?",
            evidence=[{"kicker": "pf", "data": "x", "ref": "pf:1"}],
            state="proven", parent=main)
        self.assertNotEqual(main, sub)  # collision-proof ids
        g = self.svc.load_graph()
        sub_n = next(n for n in g["narratives"] if n["id"] == sub)
        self.assertEqual(sub_n["meta"]["parent"], main)
        # child links to its parent; main links to the verdict
        self.assertTrue(any(l["from"] == sub and l["to"] == main for l in g["links"]))
        self.assertTrue(any(l["from"] == main and l["to"] == g["verdict"]["id"] for l in g["links"]))

    def test_main_can_be_proven_by_children(self):
        main = self.svc.upsert_finding_narrative("Main", "overall", "MAIN?", evidence=[], state="open")
        self.svc.upsert_finding_narrative(
            "Sub", "why", "SUB?",
            evidence=[{"kicker": "pf", "data": "x", "ref": "pf:1"}], state="proven", parent=main)
        res = self.svc.set_state(main, "proven", reason="Supported by proven sub-findings.")
        self.assertTrue(res and res["ok"])
        self.assertEqual(next(n for n in self.svc.load_graph()["narratives"] if n["id"] == main)["state"], "proven")

    def test_edit_cannot_change_state(self):
        # EDIT owns title/reason; an EDIT carrying patch.state must NOT flip state
        # (that would bypass the R10 authorship guard). State goes via STATE_CHANGE.
        nid = self.svc.upsert_finding_narrative("Main", "overall", "MAIN?", evidence=[], state="open")
        res = self.svc.commit({"action": "EDIT", "actor": "eye", "kind": "narrative", "id": nid,
                               "reason": "tweak", "patch": {"title": "Main (edited)", "state": "proven"}})
        self.assertTrue(res["ok"])
        n = next(x for x in self.svc.load_graph()["narratives"] if x["id"] == nid)
        self.assertEqual(n["title"], "Main (edited)")   # title patched
        self.assertEqual(n["state"], "open")            # state UNCHANGED by EDIT

    def test_main_with_no_proven_child_cannot_be_proven(self):
        # An Eye main narrative with no evidence and no proven child auto-flips to negative.
        main = self.svc.upsert_finding_narrative("Main", "overall", "MAIN?", evidence=[], state="open")
        self.svc.set_state(main, "proven", reason="try")
        self.assertEqual(next(n for n in self.svc.load_graph()["narratives"] if n["id"] == main)["state"], "negative")


class TestNormalize(unittest.TestCase):
    def test_accepts_seed_parser_shape(self):
        seed = {
            "narratives": [{"id": "b1", "data": "Theme", "summary": "why",
                            "authoredBy": "eye:m", "evs": ["e1"]}],
            "evidence": {"e1": {"id": "e1", "kicker": "prefetch", "data": "ran",
                                "evidence": ["prefetch:rows"], "authoredBy": "system"}},
            "conclusions": [{"id": "verdict", "data": "Overall", "reason": "synthesis"}],
            "links": [{"id": "l0", "from": "b1", "to": "verdict"}],
        }
        g = NarrativeMapService._normalize_graph(seed)
        self.assertEqual(g["verdict"]["title"], "Overall")
        self.assertEqual(g["narratives"][0]["title"], "Theme")
        self.assertEqual(g["narratives"][0]["state"], "open")
        self.assertEqual(g["evidence"]["e1"]["ref"], "prefetch:rows")


class TestPhase1GlobalsAndVerdictState(unittest.TestCase):
    """Phase 1: floating global cards + the verdict's 3-state lifecycle."""

    def setUp(self):
        self.svc = NarrativeMapService(None, model_name="gemma-test")

    def test_default_graph_has_globals_and_open_verdict(self):
        g = self.svc.load_graph()
        self.assertEqual(g["globals"], [])
        self.assertEqual(g["verdict"]["state"], "open")

    def test_upsert_global_creates_then_updates_same_card(self):
        gid = self.svc.upsert_global("system identity", "System Identity",
                                     "host=PC1", card_id="g_sys_identity")
        self.assertEqual(gid, "g_sys_identity")
        cards = self.svc.load_graph()["globals"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["kicker"], "system identity")
        self.assertEqual(cards[0]["body"], "host=PC1")
        # Re-running with the same card_id UPDATES, never duplicates.
        self.svc.upsert_global("system identity", "System Identity",
                               "host=PC1; tz=UTC", card_id="g_sys_identity")
        cards = self.svc.load_graph()["globals"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["body"], "host=PC1; tz=UTC")

    def test_global_create_needs_no_evidence_r10_na(self):
        res = self.svc.commit({
            "action": "CREATE", "actor": "eye", "kind": "global", "id": "g1",
            "reason": "Recorded an observation.", "evidence": [],
            "object": {"id": "g1", "kicker": "note", "title": "Obs", "body": "x"},
        })
        self.assertTrue(res["ok"])
        self.assertEqual(res["audit"]["gep"]["r10"], "N-A")  # globals aren't evidence claims
        self.assertEqual(res["audit"]["gep"]["r9"], "PASS")

    def test_global_move_persists_position(self):
        self.svc.upsert_global("note", "N", "b", card_id="gm")
        self.svc.commit({"action": "MOVE", "actor": "investigator", "kind": "global",
                         "id": "gm", "x": 42, "y": 99, "reason": "Moved."})
        c = self.svc.load_graph()["globals"][0]
        self.assertEqual((c["x"], c["y"]), (42, 99))

    def test_set_verdict_state_proven_then_unproven(self):
        self.svc.set_verdict_state("proven", reason="All narratives proven.")
        self.assertEqual(self.svc.load_graph()["verdict"]["state"], "proven")
        self.svc.set_verdict_state("unproven", reason="Evidence contradicts.")
        self.assertEqual(self.svc.load_graph()["verdict"]["state"], "unproven")

    def test_invalid_verdict_state_rejected(self):
        self.assertIsNone(self.svc.set_verdict_state("bogus"))
        self.assertEqual(self.svc.load_graph()["verdict"]["state"], "open")

    def test_remove_narratives_by_title_dedupes_triage_globals(self):
        # A verdict-linked narrative copy (from the seed) + a real finding.
        keep = self.svc.upsert_finding_narrative("Discord exfiltrated data", "r", "Q1?",
                                                 evidence=[{"kicker": "srum", "data": "4MB", "reason": "x"}])
        dup = self.svc.upsert_finding_narrative("System Identity", "r", "Q2?", evidence=[], state="open")
        self.assertIsNotNone(dup)
        n = self.svc.remove_narratives_by_title(
            ["System Identity", "Immediate Technical Observations"])
        self.assertEqual(n, 1)
        titles = [x.get("title") for x in self.svc.load_graph()["narratives"]]
        self.assertNotIn("System Identity", titles)
        self.assertIn("Discord exfiltrated data", titles)
        # Its links are gone too (no dangling link to the removed node).
        links = self.svc.load_graph()["links"]
        self.assertFalse(any(l.get("from") == dup or l.get("to") == dup for l in links))

    def test_remove_narratives_by_title_empty_is_noop(self):
        self.svc.upsert_finding_narrative("Real finding", "r", "Q?",
                                          evidence=[{"kicker": "k", "data": "d", "reason": "x"}])
        self.assertEqual(self.svc.remove_narratives_by_title([]), 0)
        self.assertEqual(len(self.svc.load_graph()["narratives"]), 1)


if __name__ == "__main__":
    unittest.main()
