"""The model never reads `full_rows`: a compressed result keeps the whole row set
for the data viewer and map-reduce, but the history and the synthesis prompt got
it too, so one big query filled the synthesis window (2026-11-02 review)."""

from eye.services.query_processor import QueryProcessor


def test_full_rows_are_hidden_at_any_depth():
    results = [{"tool_name": "query_database", "success": True,
                "result": {"rows": [{"a": 1}], "full_rows": [{"a": i} for i in range(5000)],
                           "row_count": 5000, "compressed": True}}]
    view = QueryProcessor._model_view(results)
    assert "full_rows" not in view[0]["result"]
    assert view[0]["result"]["rows"] == [{"a": 1}] and view[0]["result"]["row_count"] == 5000
    assert "full_rows" in results[0]["result"]          # the original is untouched


def test_correlation_authoring_tools_only_for_engine_questions():
    import logging
    from eye.services.context_manager import ContextManager
    cm = ContextManager.__new__(ContextManager)
    cm.logger = logging.getLogger("t")
    cm.max_total_tokens = 200_000
    cm.evidence_index_service = None
    cm.llm_config = {"tools": [{"name": "query_database"}, {"name": "correlation_create_wing"},
                               {"name": "correlation_edit_semantic_mapping"}]}
    cm._active_query = "Which USB devices were connected?"
    assert [t["name"] for t in cm._get_tool_definitions()] == ["query_database"]
    cm._active_query = "Build a wing that links prefetch and amcache"
    assert len(cm._get_tool_definitions()) == 3
