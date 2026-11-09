"""The one seam Eye's tools reach evidence through (Sentinel 17.1):
eye/services/case_data_source.py and its desktop implementation,
database_service.SqliteCaseDataSource.

What it promises: the scope lives in the instance (no method takes an agent, a
tenant or a case); query() is one read-only statement, bounded by timeout_s,
with an error_kind on every failure; evidence references are built and read
only through row_ref / parse_row_ref; the semantic index's store and the
behaviour analysis are injectable; and the tools really go through it - a
source handed to the handlers is what they read. Each test fails before 17.1:
none of these existed, and four tool families opened SQLite themselves.
"""
import inspect
import os
import sqlite3
import sys
import tempfile
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from eye.services import case_data_source as cds  # noqa: E402
from eye.services.database_service import ForensicDatabaseService, SqliteCaseDataSource  # noqa: E402


@pytest.fixture
def ds(tmp_path):
    con = sqlite3.connect(str(tmp_path / "Log_Claw.db"))
    con.execute("CREATE TABLE SecurityLogs (EventID INTEGER, EventTimestampUTC TEXT, "
                "User TEXT, Source TEXT)")
    con.executemany("INSERT INTO SecurityLogs VALUES (?,?,?,?)", [
        (4624, "2026-10-01 10:00:00", "alice", "Security"),
        (5379, "2026-10-01 10:05:00", "bob", "Security"),
        (4688, "2026-10-01 11:00:00", "carol", None)])
    con.commit()
    con.close()
    return SqliteCaseDataSource(str(tmp_path))


def test_the_desktop_source_is_the_protocol_and_keeps_its_old_name(ds):
    assert isinstance(ds, cds.CaseDataSource)
    assert ForensicDatabaseService is SqliteCaseDataSource
    assert ds.dialect() == "sqlite"


def test_no_method_takes_a_scope():
    for name, fn in inspect.getmembers(cds.CaseDataSource, inspect.isfunction):
        params = set(inspect.signature(fn).parameters)
        assert not params & {"agent_id", "agent", "tenant", "tenant_id", "case", "case_id"}, name


def test_query_is_one_read_only_statement(ds):
    assert ds.query("Log_Claw.db", "SELECT count(*) AS n FROM SecurityLogs;")["data"] == [{"n": 3}]
    two = ds.query("Log_Claw.db", "SELECT 1; SELECT 2")
    assert not two["success"] and two["error_kind"] == "refused"
    write = ds.query("Log_Claw.db", "DELETE FROM SecurityLogs")
    assert write["error_kind"] == "refused"
    # A ';' inside a string or a comment is not a second statement.
    ok = ds.query("Log_Claw.db", "SELECT ';' AS s -- ; not a statement\n FROM SecurityLogs LIMIT 1")
    assert ok["success"], ok
    assert cds.single_statement("SELECT 'a;b' /* ; */") is None
    assert cds.single_statement("  ") == "empty query"


def test_every_failure_has_a_kind(ds):
    assert ds.query("Log_Claw.db", "SELECT nope FROM SecurityLogs")["error_kind"] == "no_column"
    assert ds.query("Log_Claw.db", "SELECT * FROM no_such_table_here")["error_kind"] == "no_table"
    assert ds.query("Log_Claw.db", "SELEC * FROM SecurityLogs")["error_kind"] == "syntax"
    slow = ds.query("Log_Claw.db",
                    "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) "
                    "SELECT count(*) FROM n", timeout_s=0.2)
    assert not slow["success"] and slow["error_kind"] == "timeout"
    for kind in ("no_table", "no_column", "syntax", "refused", "timeout", "other"):
        assert kind in cds.ERROR_KINDS


def test_row_references(ds):
    ref = ds.row_ref("Imported_Evidence/my export.db", "events", 42)
    assert ref == "Imported_Evidence/my export.db:events:42"
    assert ds.parse_row_ref(ref) == ("Imported_Evidence/my export.db", "events", 42)
    assert ds.parse_row_ref("not a ref") is None
    assert ds.fetch_row("Log_Claw.db", "SecurityLogs", 2)["User"] == "bob"
    assert ds.fetch_row("Log_Claw.db", "SecurityLogs", 99) is None


def test_time_window(ds):
    rows, total = ds.time_window("Log_Claw.db", "SecurityLogs", "EventTimestampUTC",
                                 "2026-10-01 09:00:00", "2026-10-01 10:30:00",
                                 columns=["User"], name_from=["Source", "User"])
    assert total == 2 and [r["User"] for r in rows] == ["alice", "bob"]
    assert rows[0]["_name"] == "Security" and rows[0]["_rowid"] == 1
    rows, total = ds.time_window("Log_Claw.db", "SecurityLogs", "EventTimestampUTC",
                                 "2026-10-01 09:00:00", "2026-10-01 12:00:00",
                                 name_from=["Source", "User"], event_ids=["4624", "4688"])
    assert total == 2 and rows[1]["_name"] == "carol"          # Source empty: the next one
    assert ds.time_window("Log_Claw.db", "SecurityLogs", "missing", "a", "b") == ([], 0)


def test_the_index_store_is_injectable(tmp_path):
    from eye.services.evidence_index_service import EvidenceIndexService

    class Store:
        def __init__(self):
            self.saved = {}

        def load(self, model):
            return list(self.saved.get(model, []))

        def save(self, model, entries):
            self.saved[model] = list(entries)

    store = Store()
    emb = types.SimpleNamespace(model_name="nomic-embed-text")
    svc = EvidenceIndexService(str(tmp_path), None, emb, index_store=store)
    svc.index = [{"database": "a.db", "table": "t", "rowid": 1, "text": "x", "embedding": [1.0]}]
    svc._save()
    assert store.saved["nomic-embed-text"][0]["rowid"] == 1
    again = EvidenceIndexService(str(tmp_path), None, emb, index_store=store)
    assert again.load() and again.index[0]["text"] == "x"
    assert not (tmp_path / "EYE_Logs").exists()                 # nothing beside the case
    default = EvidenceIndexService(str(tmp_path), None, emb)
    assert isinstance(default.index_store, cds.JsonlIndexStore)
    default.index = svc.index
    default._save()
    assert default._index_file().exists()


def _handlers(source, behavior_store=None):
    from eye.services.forensic_handlers import ForensicHandlers
    cm = types.SimpleNamespace(database_service=source, case_directory=None,
                               behavior_store=behavior_store)
    h = ForensicHandlers.__new__(ForensicHandlers)
    h.cm = cm
    import logging
    h.logger = logging.getLogger("test")
    return h


def test_the_tools_read_through_the_source_they_are_given():
    class Source:
        calls = []

        def text_search(self, term, use_regex=False, max_results=50):
            self.calls.append(("text_search", term))
            return {"results": [{"database": "x.db", "table": "t", "row_id": 7}], "total_matches": 1}

        def correlation(self, kind, **args):
            self.calls.append(("correlation", kind))
            return {"success": True, "exists": True} if kind == "exists" else {"success": True,
                                                                               "kind": kind}

    src = Source()
    h = _handlers(src)
    found = h.handle_search_artifacts({"search_term": "mimikatz"})
    assert found["results"][0]["row_id"] == 7 and ("text_search", "mimikatz") in src.calls
    assert h.handle_query_correlation_results({"query_type": "statistics"})["kind"] == "statistics"


def test_the_behaviour_analysis_comes_from_the_store_given():
    class Store:
        def engine(self):
            return "the server's engine", None, False

    h = _handlers(object(), behavior_store=Store())
    assert h._uba_engine() == ("the server's engine", None, False)
