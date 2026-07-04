"""
Tests for:
- Part 1: _build_report_evidence_block — inject ACTUAL Living Report block data.
- Part 2: _build_subquestion_context — per-sub-question knowledge + related evidence.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from eye.services.context_manager import ContextManager
from eye.services.query_processor import QueryProcessor


def _block(**kw):
    kw.setdefault("metadata", {})
    kw.setdefault("category", "")
    return SimpleNamespace(**kw)


class TestReportEvidenceBlock(unittest.TestCase):
    def _cm(self, blocks):
        cm = ContextManager.__new__(ContextManager)
        cm.report_engine = SimpleNamespace(blocks=blocks)
        return cm

    def test_table_block_data_injected(self):
        cm = self._cm([_block(
            block_id="b3", block_type="table", title="Prefetch executions",
            sql_query="SELECT * FROM prefetch_data", columns=["path", "run_count"],
            rows=[{"path": "C:/anydesk.exe", "run_count": 5}],
        )])
        out = cm._build_report_evidence_block()
        self.assertIn("Living Report Evidence", out)
        self.assertIn("[table b3]", out)
        self.assertIn("anydesk.exe", out)        # the actual row data, not just the title
        self.assertIn("SELECT * FROM prefetch_data", out)

    def test_reference_and_chain_and_timeline(self):
        cm = self._cm([
            _block(block_id="b5", block_type="reference", reference_text="Dropper artifacts",
                   columns=["file"], evidence_data=[{"file": "evil.exe"}]),
            _block(block_id="b7", block_type="chain_of_custody",
                   entries=[{"evidence_id": "E1", "action": "examined",
                             "handler_name": "GE", "timestamp": "t"}]),
            _block(block_id="b9", block_type="timeline",
                   events=[{"timestamp": "t1", "label": "first exec"}]),
        ])
        out = cm._build_report_evidence_block()
        self.assertIn("evil.exe", out)
        self.assertIn("examined", out)
        self.assertIn("first exec", out)

    def test_empty_when_no_blocks(self):
        self.assertEqual(self._cm([])._build_report_evidence_block(), "")

    def test_bounded_block_count(self):
        blocks = [_block(block_id=f"b{i}", block_type="text", markdown_content=f"note {i}")
                  for i in range(20)]
        out = self._cm(blocks)._build_report_evidence_block(max_blocks=5)
        self.assertIn("+15 more", out)

    def test_excludes_auto_triage_blocks(self):
        cm = self._cm([
            _block(block_id="t1", block_type="table", title="Triage sweep",
                   columns=["x"], rows=[{"x": "TRIAGE_ROW"}],
                   metadata={"source_query": "Eye Automated Triage"}),
            _block(block_id="t2", block_type="table", title="Triage by category",
                   columns=["x"], rows=[{"x": "TRIAGE_CAT_ROW"}], category="Automated Triage"),
            _block(block_id="q1", block_type="table", title="Answer to question",
                   columns=["x"], rows=[{"x": "REAL_ROW"}],
                   metadata={"source_query": "did anydesk run"}),
        ])
        out = cm._build_report_evidence_block()
        self.assertIn("REAL_ROW", out)
        self.assertIn("[table q1]", out)
        self.assertNotIn("TRIAGE_ROW", out)
        self.assertNotIn("TRIAGE_CAT_ROW", out)

    def test_empty_when_only_triage_blocks(self):
        cm = self._cm([
            _block(block_id="t1", block_type="table", rows=[{"x": "y"}],
                   metadata={"source_query": "Eye Automated Triage"}),
        ])
        self.assertEqual(cm._build_report_evidence_block(), "")


class TestSubquestionContext(unittest.TestCase):
    def _cm(self, *, with_semantic=False):
        cm = MagicMock()
        cm.intent_engine.detect_keywords.return_value = []
        cm.rag_service.retrieve_context.return_value = "Prefetch proves execution."
        cm.rag_service.retrieve_conversation.return_value = ""
        cm.case_context_manager.get_recent_question_memory.return_value = []
        cm.report_engine.blocks = [
            _block(block_id="b3", block_type="table", title="AnyDesk executions",
                   caption="", sql_query="", reference_text="", markdown_content="")
        ]
        cm.token_counter.truncate_text.side_effect = lambda s, n: s
        cm.token_budget = {"system_prompt": 4000}
        if with_semantic:
            esvc = MagicMock()
            esvc.available.return_value = True
            esvc.search.return_value = {"candidates": [
                {"database": "prefetch.db", "table": "prefetch_data", "rowid": 5}]}
            cm.evidence_index_service = esvc
        else:
            cm.evidence_index_service = None
        return cm

    def test_structured_per_subquestion_with_knowledge_and_evidence(self):
        cm = self._cm(with_semantic=True)
        qp = QueryProcessor(cm)
        out = qp._build_subquestion_context(
            ["did anydesk run on the host", "what files were deleted"],
            history_snapshot=[], user_query="anydesk + deletions",
            rag_params={"top_k": 2, "min_score": 0.05, "semantic_min_score": 0.4, "max_qs": 6},
            emit_step=lambda *a, **k: None,
        )
        self.assertIn("## Per Sub-Question Context", out)
        self.assertEqual(out.count("### SubQ:"), 2)
        self.assertIn("Knowledge: Prefetch proves execution.", out)
        # report-block evidence matched the 'anydesk' sub-question by token overlap
        self.assertIn("report [table b3]", out)
        # semantic candidate provenance present
        self.assertIn("prefetch.db:prefetch_data#5", out)

    def test_pinned_chat_evidence_matched(self):
        cm = self._cm()
        qp = QueryProcessor(cm)
        history = [{"role": "user", "content": "the anydesk binary was at C:/temp",
                    "metadata": {"pinned": True}}]
        out = qp._build_subquestion_context(
            ["did anydesk run", "unrelated second part here"],
            history_snapshot=history, user_query="q",
            rag_params={"top_k": 2}, emit_step=lambda *a, **k: None,
        )
        self.assertIn("pinned: the anydesk binary", out)

    def test_triage_block_not_cited_as_related_evidence(self):
        cm = self._cm()
        # A triage block that token-matches the sub-question must NOT be cited,
        # but a normal matching block should be.
        cm.report_engine.blocks = [
            _block(block_id="t1", block_type="table", title="anydesk triage", caption="",
                   sql_query="", reference_text="", markdown_content="",
                   metadata={"source_query": "Eye Automated Triage"}),
            _block(block_id="q1", block_type="table", title="anydesk answer", caption="",
                   sql_query="", reference_text="", markdown_content="",
                   metadata={"source_query": "did anydesk run"}),
        ]
        qp = QueryProcessor(cm)
        out = qp._build_subquestion_context(
            ["did anydesk run", "second unrelated part"],
            history_snapshot=[], user_query="q",
            rag_params={"top_k": 2}, emit_step=lambda *a, **k: None,
        )
        self.assertIn("report [table q1]", out)
        self.assertNotIn("[table t1]", out)

    def test_empty_when_nothing_relevant(self):
        cm = self._cm()
        cm.rag_service.retrieve_context.return_value = ""
        cm.report_engine.blocks = []
        qp = QueryProcessor(cm)
        out = qp._build_subquestion_context(
            ["aaa", "bbb"], history_snapshot=[], user_query="q",
            rag_params={}, emit_step=lambda *a, **k: None,
        )
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
