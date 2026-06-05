"""
FeatherWriter — canonical write-side contract for Crow-Eye feathers.

Background
----------
Today the artifact parsers (``Artifacts_Collectors/*claw*.py``) each
``sqlite3.connect()`` their output file directly and write rows one at a
time. The Feather Builder GUI writes to a *different* schema with
``feather_metadata`` / ``import_history`` / ``data_lineage`` tables that
the engine doesn't currently read. Both paths emit valid SQLite, but
neither path uses transactional batching — 220k MFT rows takes minutes
when it could take seconds — and neither stamps the metadata the engine
needs to know the table's primary timestamp column or multi-timestamp
JSON columns without re-detecting them from sample values.

This module gives parsers and the GUI a single, opinionated writer that:

* Wraps every batch insert in an explicit transaction with
  ``executemany()`` — expected 50-200× speedup over single-row inserts.
* Stamps schema metadata (``feather_metadata`` table) the engine can
  read instead of guessing.
* Creates indexes on declared timestamp + identity columns at write
  time, so the engine doesn't pay the lazy-index cost on first query.
* Declares multi-timestamp JSON columns so the engine doesn't need
  hardcoded ``MULTI_TIMESTAMP_FIELDS`` constants.
* Stays SQLite-only — no new dependencies.

Usage
-----
::

    from correlation_engine.feather.writer import FeatherWriter, ColumnSpec

    writer = FeatherWriter()
    writer.open("prefetch_data.db", artifact_type="Prefetch")
    writer.declare_table(
        "prefetch_data",
        columns=[
            ColumnSpec("filename", "TEXT"),
            ColumnSpec("executable_name", "TEXT"),
            ColumnSpec("last_executed", "TEXT", is_timestamp=True, is_primary_timestamp=True),
            ColumnSpec("run_times", "TEXT"),
            # ... etc
        ],
    )
    writer.declare_multi_timestamp_json("run_times", format="datetime_string")
    writer.write_batch(rows) # rows = iterable of dicts
    writer.add_lineage(source_path="C:/.../Prefetch", row_count=491)
    writer.close()

Migration
---------
Existing parsers can adopt the writer incrementally. They keep their
custom schemas; the writer just provides the safe transaction path and
the metadata stamping. The engine's ``OptimizedFeatherQuery`` consults
``feather_metadata`` when present and falls back to its existing
heuristics when not — so a single parser switching to FeatherWriter
benefits immediately without breaking the other 7 still on the old
path.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, List, Optional

logger = logging.getLogger(__name__)


# Batch size for executemany INSERTs. 5000 is a sweet spot for SQLite —
# large enough to amortize transaction overhead, small enough to keep
# memory bounded for million-row tables.
DEFAULT_BATCH_SIZE = 5000

# Stamped into feather_metadata so the engine can detect older files
# that pre-date the writer and apply migration on first open.
FEATHER_SCHEMA_VERSION = 2


@dataclass
class ColumnSpec:
    """One column in a feather table.

    ``is_timestamp`` Index the column for time-range queries.
    ``is_primary_timestamp`` Treat this column as the engine's default
                               window-filter target (only one per table).
    ``is_identity`` Index for identity-extraction lookups.
    ``json_timestamp_list`` The column stores a JSON array of
                               timestamps (Prefetch ``run_times`` shape).
                               Implies ``is_timestamp``.
    """

    name: str
    sql_type: str = "TEXT"
    is_timestamp: bool = False
    is_primary_timestamp: bool = False
    is_identity: bool = False
    json_timestamp_list: bool = False
    nullable: bool = True
    default: Optional[str] = None

    def to_ddl(self) -> str:
        """Render this column as a SQL DDL fragment."""
        parts = [f'"{self.name}"', self.sql_type]
        if not self.nullable:
            parts.append("NOT NULL")
        if self.default is not None:
            parts.append(f"DEFAULT {self.default}")
        return " ".join(parts)


@dataclass
class TableDeclaration:
    """Bookkeeping for one declared table during a writer session."""

    name: str
    columns: List[ColumnSpec]
    multi_timestamp_json_columns: List[dict] = field(default_factory=list)

    def primary_timestamp(self) -> Optional[str]:
        for col in self.columns:
            if col.is_primary_timestamp:
                return col.name
        return None

    def timestamp_columns(self) -> List[str]:
        return [c.name for c in self.columns if c.is_timestamp and not c.json_timestamp_list]

    def identity_columns(self) -> List[str]:
        return [c.name for c in self.columns if c.is_identity]


class FeatherWriter:
    """Canonical SQLite feather writer with transactional batching.

    One instance per output ``.db`` file. Not thread-safe — give each
    parser its own writer (parallel dispatch is at the parser level,
    not within one parser's write loop).
    """

    def __init__(self, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
        self.batch_size = batch_size
        self._conn: Optional[sqlite3.Connection] = None
        self._db_path: Optional[Path] = None
        self._artifact_type: str = "Unknown"
        self._table: Optional[TableDeclaration] = None
        self._pending_lineage: List[dict] = []

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def open(self, db_path: str, artifact_type: str) -> None:
        """Open ``db_path`` for writing. Creates the file if needed."""
        if self._conn is not None:
            raise RuntimeError("FeatherWriter already open — close() first")
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._artifact_type = artifact_type
        # isolation_level=None turns OFF sqlite3's implicit transactions
        # so we have full manual control via BEGIN/COMMIT in _flush_batch.
        # Without this, sqlite3 wraps the first DML in an implicit txn
        # and our manual BEGIN raises "cannot start a transaction within
        # a transaction".
        self._conn = sqlite3.connect(str(self._db_path), isolation_level=None)
        # WAL improves write throughput and lets readers query during
        # writes — important once parsers run concurrently in Phase 10.
        try:
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
        except sqlite3.Error as e:
            logger.warning("Could not enable WAL on %s: %s", self._db_path, e)
        self._create_metadata_tables()

    def close(self) -> None:
        """Flush pending writes and close the connection."""
        if self._conn is None:
            return
        try:
            self._flush_pending_lineage()
            # Manual-txn mode: no implicit COMMIT to call. Pending
            # writes have already been COMMITted by the batch helpers.
        finally:
            try:
                self._conn.close()
            finally:
                self._conn = None
                self._table = None

    def __enter__(self) -> "FeatherWriter":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Schema declaration
    # ------------------------------------------------------------------ #

    def declare_table(self, name: str, columns: List[ColumnSpec]) -> None:
        """Create ``name`` if missing and create indexes on declared
        timestamp + identity columns. Stamps the table's schema into
        ``feather_metadata`` so the engine can discover it on next open
        without sniffing sample values.
        """
        self._require_open()
        if not columns:
            raise ValueError("declare_table requires at least one column")

        self._table = TableDeclaration(name=name, columns=columns)
        ddl_columns = ", ".join(c.to_ddl() for c in columns)
        self._conn.execute("BEGIN")
        try:
            self._conn.execute(f'CREATE TABLE IF NOT EXISTS "{name}" ({ddl_columns})')
            # Index timestamp + identity columns immediately so the
            # engine doesn't pay the cost on first query.
            for col in columns:
                if col.is_timestamp and not col.json_timestamp_list:
                    self._conn.execute(
                        f'CREATE INDEX IF NOT EXISTS "idx_{name}_{col.name}_ts" '
                        f'ON "{name}" ("{col.name}")'
                    )
                if col.is_identity:
                    self._conn.execute(
                        f'CREATE INDEX IF NOT EXISTS "idx_{name}_{col.name}_id" '
                        f'ON "{name}" ("{col.name}")'
                    )
            self._stamp_table_schema()
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            self._conn.execute("ROLLBACK")
            raise

    def declare_multi_timestamp_json(self, column: str, format: str = "datetime_string") -> None:
        """Declare a JSON-list-of-timestamps column on the current table.

        The engine reads this metadata to know it should fan out each
        row into one virtual record per timestamp in the list.
        """
        if self._table is None:
            raise RuntimeError("call declare_table() before declare_multi_timestamp_json()")
        self._table.multi_timestamp_json_columns.append({"column": column, "format": format})
        self._conn.execute("BEGIN")
        try:
            self._stamp_table_schema()
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            self._conn.execute("ROLLBACK")
            raise

    # ------------------------------------------------------------------ #
    # Bulk insert
    # ------------------------------------------------------------------ #

    def write_batch(self, rows: Iterable[dict]) -> int:
        """Insert ``rows`` into the active table using executemany() in
        ``self.batch_size`` chunks wrapped in explicit transactions.

        Returns the number of rows actually inserted.
        """
        self._require_open()
        if self._table is None:
            raise RuntimeError("call declare_table() before write_batch()")

        col_names = [c.name for c in self._table.columns]
        placeholders = ",".join("?" for _ in col_names)
        col_list = ",".join(f'"{c}"' for c in col_names)
        insert_sql = (
            f'INSERT INTO "{self._table.name}" ({col_list}) VALUES ({placeholders})'
        )

        total = 0
        batch: List[tuple] = []
        for row in rows:
            batch.append(tuple(row.get(c) for c in col_names))
            if len(batch) >= self.batch_size:
                self._flush_batch(insert_sql, batch)
                total += len(batch)
                batch = []
        if batch:
            self._flush_batch(insert_sql, batch)
            total += len(batch)
        return total

    def _flush_batch(self, insert_sql: str, batch: List[tuple]) -> None:
        """One transaction per batch — committed before returning."""
        try:
            self._conn.execute("BEGIN")
            self._conn.executemany(insert_sql, batch)
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise

    # ------------------------------------------------------------------ #
    # Lineage / provenance
    # ------------------------------------------------------------------ #

    def add_lineage(self, source_path: str, row_count: int, notes: str = "") -> None:
        """Record where the rows in this feather came from."""
        self._pending_lineage.append({
            "source_path": source_path,
            "row_count": int(row_count),
            "imported_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "notes": notes,
        })

    def _flush_pending_lineage(self) -> None:
        if not self._conn or not self._pending_lineage:
            return
        self._conn.execute("BEGIN")
        try:
            self._conn.executemany(
                """INSERT INTO feather_lineage
                   (source_path, row_count, imported_at, notes)
                   VALUES (:source_path, :row_count, :imported_at, :notes)""",
                self._pending_lineage,
            )
            self._conn.execute("COMMIT")
            self._pending_lineage = []
        except sqlite3.Error:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _require_open(self) -> None:
        if self._conn is None:
            raise RuntimeError("FeatherWriter not open — call open() first")

    def _create_metadata_tables(self) -> None:
        """Create the bookkeeping tables the engine reads on open."""
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS feather_metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )"""
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS feather_lineage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_path TEXT NOT NULL,
                row_count INTEGER,
                imported_at TEXT NOT NULL,
                notes TEXT
            )"""
        )
        self._conn.execute("BEGIN")
        try:
            self._upsert_metadata(
                schema_version=str(FEATHER_SCHEMA_VERSION),
                artifact_type=self._artifact_type,
                writer_version=str(FEATHER_SCHEMA_VERSION),
                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            self._conn.execute("ROLLBACK")
            raise

    def _stamp_table_schema(self) -> None:
        """Store the active table's declared schema as JSON in metadata."""
        if self._table is None:
            return
        schema_blob = {
            "name": self._table.name,
            "primary_timestamp_column": self._table.primary_timestamp(),
            "timestamp_columns": self._table.timestamp_columns(),
            "identity_columns": self._table.identity_columns(),
            "multi_timestamp_json_columns": list(self._table.multi_timestamp_json_columns),
            "columns": [
                {
                    "name": c.name,
                    "sql_type": c.sql_type,
                    "is_timestamp": c.is_timestamp,
                    "is_primary_timestamp": c.is_primary_timestamp,
                    "is_identity": c.is_identity,
                    "json_timestamp_list": c.json_timestamp_list,
                }
                for c in self._table.columns
            ],
        }
        self._upsert_metadata(**{f"table:{self._table.name}": json.dumps(schema_blob)})

    def _upsert_metadata(self, **kv: str) -> None:
        rows = [(k, v) for k, v in kv.items()]
        self._conn.executemany(
            "INSERT INTO feather_metadata(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            rows,
        )


__all__ = ["FeatherWriter", "ColumnSpec", "TableDeclaration", "FEATHER_SCHEMA_VERSION"]
