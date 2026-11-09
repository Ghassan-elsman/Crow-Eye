"""The one place Eye's tools reach a case's evidence (Sentinel 17.1).

``CaseDataSource`` is what every tool goes through: tables, columns and
schema, read-only queries, the full-text search, single rows, time windows and
the correlation results. The desktop's implementation is
``eye.services.database_service.SqliteCaseDataSource`` (the case's SQLite
databases). A server supplies its own (Crow-Eye Sentinel: PostgreSQL), and the
tools do not change.

Rules every implementation keeps:

1. **Scope lives in the instance.** A data source is built for one scope - the
   desktop's case, or on a server a machine, a set of machines or the server -
   and no method takes an agent, a tenant or a case. Fencing is the
   instance's (on PostgreSQL: the role it connects as and row-level security).
2. **query() is read-only by contract.** It refuses text that is not one
   statement (``single_statement``), reports its ``dialect()`` so the model
   writes the SQL that source runs, and bounds a query by ``timeout_s``.
3. **Errors carry a kind** (``ERROR_KINDS``): no_table, no_column, syntax,
   refused, timeout, other. Callers key on ``error_kind``, never on the text.
4. **Row identity.** A row is referred to as ``database:table:row_id`` and only
   ever built and read through ``row_ref`` / ``parse_row_ref``; ``fetch_row``
   takes that row_id. The database is a logical name (``Log_Claw.db``) the
   source maps.

Two providers sit beside it: ``SemanticIndexStore`` (where the semantic
search's index is kept: ``JsonlIndexStore`` by default, one per scope) and
``BehaviorStore`` (the case's behaviour analysis, a separate engine with its
own store).
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple, runtime_checkable

ERROR_KINDS = ("no_table", "no_column", "syntax", "refused", "timeout", "other")

# database:table:row_id. The database is matched greedily: imported-evidence
# databases carry spaces, dots and a subpath under Imported_Evidence/.
_ROW_REF_RE = re.compile(r'^(?P<db>.+):(?P<table>[A-Za-z_]\w*):(?P<row_id>\d+)$')


def row_ref(database: str, table: str, row_id: Any) -> str:
    """The reference form of one row."""
    return "%s:%s:%d" % (database, table, int(row_id))


def parse_row_ref(ref: str) -> Optional[Tuple[str, str, int]]:
    """(database, table, row_id) of a reference, or None when it is not one."""
    if not isinstance(ref, str):
        return None
    m = _ROW_REF_RE.match(ref.strip())
    if not m:
        return None
    return m.group("db").strip(), m.group("table"), int(m.group("row_id"))


def _strip_literals(sql: str) -> str:
    """The SQL with comments and quoted text replaced by spaces, so a ';' or a
    keyword inside a string or a comment is not read as SQL."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j
            out.append(" ")
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
            out.append(" ")
        elif c in ("'", '"', "`", "["):
            close = "]" if c == "[" else c
            j = i + 1
            while j < n:
                if sql[j] == close:
                    if close != "]" and j + 1 < n and sql[j + 1] == close:
                        j += 2
                        continue
                    break
                j += 1
            out.append(" ")
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def single_statement(sql: str) -> Optional[str]:
    """None when ``sql`` is one statement (a trailing ';' allowed), otherwise
    why it is refused."""
    if not isinstance(sql, str) or not sql.strip():
        return "empty query"
    body = _strip_literals(sql).strip()
    while body.endswith(";"):
        body = body[:-1].rstrip()
    if ";" in body:
        return "more than one statement: send one SELECT at a time"
    if not body:
        return "empty query"
    return None


def classify_sqlite_error(message: str) -> str:
    """The error kind of an SQLite error message."""
    low = (message or "").lower()
    if "no such table" in low:
        return "no_table"
    if "no such column" in low:
        return "no_column"
    if "interrupted" in low or "timed out" in low or "timeout" in low:
        return "timeout"
    if "syntax error" in low or "incomplete input" in low or "unrecognized token" in low:
        return "syntax"
    if "readonly" in low or "read-only" in low or "not authorized" in low \
            or "one statement at a time" in low:
        return "refused"
    return "other"


@runtime_checkable
class CaseDataSource(Protocol):
    """See the module docstring. Return shapes are dicts, as the tools use them."""

    def dialect(self) -> str:
        """'sqlite' or 'postgresql': the SQL ``query`` runs."""

    def list_databases(self) -> List[Dict[str, Any]]:
        """[{name, category, tables, exists, accessible, ...}] in this scope."""

    def list_tables(self, database: str) -> List[str]:
        """The tables of one logical database."""

    def table_columns(self, database: str, table: str) -> List[str]:
        """A table's columns, in order; [] when the table is not there."""

    def table_schema(self, database: str, table: Optional[str] = None) -> Dict[str, Any]:
        """{success, schema, row_counts, sample_data, tables, ...} for a database or one table."""

    def query(self, database: str, sql: str, params: Sequence[Any] = (),
              timeout_s: Optional[float] = None) -> Dict[str, Any]:
        """One read-only statement. {success, data, columns, row_count, error,
        error_kind}; error_kind is one of ERROR_KINDS when success is False."""

    def text_search(self, term: str, use_regex: bool = False,
                    max_results: int = 50) -> Dict[str, Any]:
        """{results: [{database, table, row_id, matched_columns, record,
        relevance}], total_matches} over every table in scope."""

    def fetch_row(self, database: str, table: str, row_id: int) -> Optional[Dict[str, Any]]:
        """One row by the row_id its reference carries, or None."""

    def time_window(self, database: str, table: str, time_column: str, start: str, end: str,
                    columns: Sequence[str] = (), name_from: Sequence[str] = (),
                    event_ids: Optional[Sequence[str]] = None, row_filter: Optional[str] = None,
                    text_time: bool = False, limit: int = 100) -> Tuple[List[Dict[str, Any]], int]:
        """The rows of one table whose ``time_column`` falls in [start, end],
        oldest first, each with _rowid, _when and _name (the first non-empty
        of ``name_from``) plus ``columns``; and how many there were in all."""

    def correlation(self, kind: str, **args) -> Dict[str, Any]:
        """The correlation engine's results: kind 'exists', 'statistics',
        'time' (start_time, end_time) or 'identity' (identity_type, identity_value)."""

    def row_ref(self, database: str, table: str, row_id: Any) -> str:
        """The reference form of one row (the module's row_ref by default)."""

    def parse_row_ref(self, ref: str) -> Optional[Tuple[str, str, int]]:
        """(database, table, row_id), or None (the module's parse_row_ref by default)."""

    # Optional (``source_dialect`` reads them with their defaults):
    #   row_id_column() -> str       the column a row's id is read from ('rowid')
    #   translate_filter(sql) -> str | None
    #       a row filter written in SQLite SQL (timeline/data/artifact_map
    #       ROW_FILTERS) in this source's dialect, or None when it cannot be
    #       translated - the tool then runs without it and says so.


# ----------------------------------------------------- the dialect, told --
# What the model is told about the SQL a source runs. A SQLite source whose row
# id is ``rowid`` - the desktop - gets every description and the prompt exactly
# as written in configs/llm_config.json; any other source gets them reworded.
SQL_TOOLS = ("query_database", "analyze_large_dataset", "report_add_data_table", "get_schema")

POSTGRES_GUIDANCE = (
    " SQL DIALECT: PostgreSQL. One SELECT per call. Columns are listed in "
    "information_schema.columns (there is no PRAGMA and no sqlite_master). Match text "
    "without case with ILIKE (LIKE is case-sensitive here). Read JSON with the -> and ->> "
    "operators (there is no json_extract). Timestamps are timestamptz: compare them with "
    "timestamp literals ('2026-10-01 10:00:00+00') and use date_trunc and interval, not "
    "datetime(). A row's id is the column {row_id}.")


def source_dialect(source) -> Tuple[str, str]:
    """(dialect, row id column) of a data source, with the desktop's defaults."""
    dialect, row_id = "sqlite", "rowid"
    try:
        dialect = (source.dialect() or "sqlite") if hasattr(source, "dialect") else "sqlite"
    except Exception:
        dialect = "sqlite"
    try:
        row_id = (source.row_id_column() or "rowid") if hasattr(source, "row_id_column") else "rowid"
    except Exception:
        row_id = "rowid"
    return str(dialect).lower(), str(row_id)


def _is_default(dialect, row_id):
    return dialect == "sqlite" and row_id == "rowid"


def dialect_text(text: str, dialect: str, row_id: str) -> str:
    """``text`` for a source of ``dialect`` whose row id is ``row_id``; the same
    text, untouched, for SQLite with rowid."""
    if _is_default(dialect, row_id) or not isinstance(text, str):
        return text
    out = re.sub(r"\browid\b", row_id, text)
    if dialect == "postgresql":
        out = out.replace("`LIKE`", "`ILIKE`")
        out = re.sub(r"\bSQLite\b", "PostgreSQL", out)
    return out


def dialect_tools(tools: List[Dict[str, Any]], dialect: str, row_id: str) -> List[Dict[str, Any]]:
    """The tool definitions for the source: the same list for SQLite with rowid;
    otherwise every description reworded and the SQL tools told the dialect."""
    if _is_default(dialect, row_id):
        return tools
    import copy

    def walk(node):
        if isinstance(node, dict):
            return {k: (dialect_text(v, dialect, row_id) if k == "description" else walk(v))
                    for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    out = []
    for tool in tools:
        t = walk(copy.deepcopy(tool))
        if t.get("name") in SQL_TOOLS and dialect == "postgresql":
            t["description"] = (t.get("description") or "") + POSTGRES_GUIDANCE.format(row_id=row_id)
        elif t.get("name") in SQL_TOOLS:
            t["description"] = (t.get("description") or "") + (
                " SQL DIALECT: %s. A row's id is the column %s." % (dialect, row_id))
        out.append(t)
    return out


# ------------------------------------------------------------- the index --
@runtime_checkable
class SemanticIndexStore(Protocol):
    """Where the semantic search's index is kept - one per scope, so an index
    never mixes two scopes' evidence."""

    def load(self, model: str) -> List[Dict[str, Any]]:
        """The stored entries built with ``model``; [] when there are none."""

    def save(self, model: str, entries: List[Dict[str, Any]]) -> None:
        """Replace the stored entries for ``model``."""


class JsonlIndexStore:
    """The desktop's store: <case>/EYE_Logs/eye_evidence_index/<model>.jsonl."""

    def __init__(self, case_directory):
        self.case_directory = Path(case_directory) if case_directory else None

    def path(self, model: str) -> Optional[Path]:
        if not self.case_directory:
            return None
        safe = re.sub(r"[^a-z0-9._-]+", "_", (model or "emb").lower())
        return self.case_directory / "EYE_Logs" / "eye_evidence_index" / ("%s.jsonl" % safe)

    def load(self, model: str) -> List[Dict[str, Any]]:
        path = self.path(model)
        if not path or not path.exists():
            return []
        out = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("embedding"):
                    out.append(rec)
        return out

    def save(self, model: str, entries: List[Dict[str, Any]]) -> None:
        path = self.path(model)
        if not path:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for rec in entries:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        tmp.replace(path)


# ------------------------------------------------------------ behaviour --
@runtime_checkable
class BehaviorStore(Protocol):
    """The scope's behaviour analysis (UBA): a separate engine with its own store."""

    def engine(self) -> Tuple[Any, Optional[str], bool]:
        """(engine, error, ran_now): the loaded analysis, or None and why."""
