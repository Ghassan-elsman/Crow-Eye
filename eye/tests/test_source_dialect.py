"""The tool descriptions and the system prompt follow the data source's dialect
(Sentinel 17.1): a SQLite source whose row id is rowid - the desktop - gets
them exactly as configs/llm_config.json writes them; a PostgreSQL source gets
them reworded (its row-id column, ILIKE, information_schema, json operators,
timestamptz). A row filter the source cannot translate is not run, and the
timeline says so. Each test fails before: the descriptions were fixed text and
no source could say what it speaks.
"""
import json
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from eye.services import case_data_source as cds  # noqa: E402
from eye.services.database_service import SqliteCaseDataSource  # noqa: E402

CONFIG = json.load(open(os.path.join(ROOT, "configs", "llm_config.json"), encoding="utf-8"))


class PostgresStub:
    def dialect(self):
        return "postgresql"

    def row_id_column(self):
        return "event_row_id"


def _cm(source):
    from eye.services.context_manager import ContextManager
    cm = ContextManager.__new__(ContextManager)
    cm.database_service = source
    cm.llm_config = CONFIG
    cm.evidence_index_service = None
    cm._active_query = "create a correlation wing"      # every tool, authoring included
    cm.max_total_tokens = 200000
    return cm


def test_a_sqlite_source_gets_the_tools_exactly_as_written(tmp_path):
    cm = _cm(SqliteCaseDataSource(str(tmp_path)))
    told = cm._get_tool_definitions()
    raw = cm._tool_definitions_for_model()
    assert json.dumps(told, sort_keys=True) == json.dumps(raw, sort_keys=True)
    expected = [t for t in CONFIG["tools"] if t.get("name") != "semantic_search_artifacts"]
    assert json.dumps(told, sort_keys=True) == json.dumps(expected, sort_keys=True)


def test_a_sqlite_source_gets_the_prompt_text_untouched():
    text = "\n".join(CONFIG["system_prompt_template"])
    assert cds.dialect_text(text, "sqlite", "rowid") is text
    tools = CONFIG["tools"]
    assert cds.dialect_tools(tools, "sqlite", "rowid") is tools
    assert cds.source_dialect(object()) == ("sqlite", "rowid")       # an older source


def test_a_postgresql_source_is_told_its_dialect():
    cm = _cm(PostgresStub())
    told = cm._get_tool_definitions()
    text = json.dumps(told)
    assert not re.search(r"\browid\b", text)
    assert "event_row_id" in text
    by_name = {t["name"]: t for t in told}
    q = by_name["query_database"]["description"]
    for word in ("PostgreSQL", "information_schema", "ILIKE", "->>", "timestamptz", "event_row_id"):
        assert word in q, word
    assert "information_schema" not in by_name["query_timeline"]["description"]
    wing = by_name["correlation_create_wing"]["parameters"]["properties"]["related_evidence"]
    assert "database:table:event_row_id" in wing["description"]
    prompt = cds.dialect_text("\n".join(CONFIG["system_prompt_template"]), "postgresql",
                              "event_row_id")
    assert "`ILIKE`" in prompt and "`LIKE`" not in prompt


def test_the_system_prompt_goes_through_the_source(monkeypatch):
    from eye.services.context_manager import ContextManager
    monkeypatch.setattr(ContextManager, "_build_system_prompt_text",
                        lambda self, *a, **k: "confirm by rowid with a `LIKE` query")
    assert _cm(PostgresStub())._build_system_prompt("", []) == \
        "confirm by event_row_id with a `ILIKE` query"
    sqlite = _cm(SqliteCaseDataSource("."))
    assert sqlite._build_system_prompt("", []) == "confirm by rowid with a `LIKE` query"


def test_a_filter_the_source_cannot_translate_is_not_run_and_is_named():
    from eye.services.forensic_handlers import ForensicHandlers

    class Source:
        windows = []

        def list_tables(self, db):
            return ["ai_agent_steps"] if db == "ai_agents.db" else []

        def table_columns(self, db, table):
            return ["ts", "command", "target", "kind", "role", "agent"]

        def translate_filter(self, sql):
            return None

        def time_window(self, db, table, column, start, end, **kw):
            self.windows.append(kw.get("row_filter"))
            return [{"_rowid": 1, "_when": "2026-10-01 10:00:00", "_name": "dir",
                     "kind": "command"}], 1

    src = Source()
    h = ForensicHandlers.__new__(ForensicHandlers)
    h.cm = types.SimpleNamespace(database_service=src)
    out = h.handle_query_timeline({"start_time": "2026-10-01 09:00:00",
                                   "end_time": "2026-10-01 11:00:00",
                                   "artifact_types": ["AIAgents"]})
    assert out["success"] and src.windows == [None]
    assert out["row_filters_not_applied"] == ["ai_agent_steps"]
    assert "could not be run" in out["note"]
    assert SqliteCaseDataSource(".").translate_filter("kind = 'x'") == "kind = 'x'"
