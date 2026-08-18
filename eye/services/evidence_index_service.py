"""
Evidence Semantic Index — per-case semantic retrieval over forensic data rows.

This is an **additive discovery layer**: it embeds a curated, text-ish subset of
forensic rows so the model can find candidate evidence by concept ("remote access
tools", "powershell download cradle") without authoring perfect SQL. It returns
CANDIDATE rows with full `database:table:rowid` provenance that the model then
**confirms with exact SQL** — semantic hits are approximate and never complete, so
SQL stays the authoritative path, traceable to source records.

Design constraints (OSS Crow-Eye):
- Dependency-light: brute-force cosine over embeddings persisted on disk; no faiss/
  hnswlib. Sized for the open-source build; very large tables are sampled/capped and
  the gap is surfaced (so the human reviewer sees what was NOT fully indexed).
- Strictly optional: requires an embedding client; degrades to "unavailable" with a
  clear message when none is configured.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from eye.services.rag_service import cosine_similarity


class EvidenceIndexService:
    """Builds and queries a per-case semantic index over forensic data rows."""

    # Per-table row cap (sampled when exceeded) and per-row serialized text cap.
    DEFAULT_PER_TABLE_CAP = 3000
    DEFAULT_MAX_TEXT_CHARS = 512
    # Global ceiling so a giant case can't exhaust memory / the embedding server.
    DEFAULT_MAX_TOTAL_ROWS = 50000

    def __init__(self, case_directory, database_service, embedding_client,
                 per_table_cap: int = DEFAULT_PER_TABLE_CAP,
                 max_text_chars: int = DEFAULT_MAX_TEXT_CHARS,
                 max_total_rows: int = DEFAULT_MAX_TOTAL_ROWS):
        self.case_directory = Path(case_directory) if case_directory else None
        self.database_service = database_service
        self.embedding_client = embedding_client
        self.per_table_cap = per_table_cap
        self.max_text_chars = max_text_chars
        self.max_total_rows = max_total_rows
        self.logger = logging.getLogger(self.__class__.__name__)

        self.index: List[Dict[str, Any]] = []   # {database, table, rowid, text, embedding}
        self.capped_tables: List[Dict[str, Any]] = []  # {database, table, total, indexed}
        self.built = False

    # ------------------------------------------------------------------
    def available(self) -> bool:
        """Whether semantic indexing/search is possible (embedding client present)."""
        return self.embedding_client is not None and self.case_directory is not None

    def _index_file(self) -> Optional[Path]:
        if not self.case_directory:
            return None
        model = getattr(self.embedding_client, "model_name", "emb") or "emb"
        safe = re.sub(r"[^a-z0-9._-]+", "_", model.lower())
        return self.case_directory / "EYE_Logs" / "eye_evidence_index" / f"{safe}.jsonl"

    # ------------------------------------------------------------------
    @staticmethod
    def _is_textish(value: Any) -> bool:
        """A value worth embedding: a non-trivial string with letters (paths,
        commands, names, URLs, registry values) — not a pure number/timestamp."""
        if not isinstance(value, str):
            return False
        v = value.strip()
        if len(v) < 2 or len(v) > 400:
            return False
        return bool(re.search(r"[A-Za-z]", v))

    def _row_to_text(self, table: str, row: Dict[str, Any]) -> str:
        """Serialize the text-ish columns of a row into one compact string."""
        parts = []
        for col, val in row.items():
            if col == "rowid":
                continue
            if self._is_textish(val):
                parts.append(f"{col}={val.strip()}")
        if not parts:
            return ""
        text = f"{table}: " + "; ".join(parts)
        return text[: self.max_text_chars]

    # ------------------------------------------------------------------
    def load(self) -> bool:
        """Load a previously persisted index from disk. Returns True if non-empty."""
        path = self._index_file()
        if not path or not path.exists():
            return False
        try:
            loaded = []
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
                        loaded.append(rec)
            if loaded:
                self.index = loaded
                self.built = True
                self.logger.info(f"Loaded evidence index with {len(loaded)} rows from {path}.")
                return True
        except Exception as e:
            self.logger.debug(f"Evidence index load failed: {e}")
        return False

    def _save(self):
        path = self._index_file()
        if not path:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".jsonl.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                for rec in self.index:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            tmp.replace(path)
        except Exception as e:
            self.logger.debug(f"Evidence index save failed: {e}")

    # ------------------------------------------------------------------
    def build(self, force: bool = False, progress=None) -> Dict[str, Any]:
        """Build (or load) the per-case evidence semantic index.

        Returns a summary dict ``{built, indexed_rows, capped_tables, error?}``.
        Best-effort: a failure on one table never aborts the whole build.
        """
        if not self.available():
            return {"built": False, "error": "embedding_unavailable", "indexed_rows": 0}
        if self.built and not force:
            return {"built": True, "indexed_rows": len(self.index),
                    "capped_tables": self.capped_tables}
        if not force and self.load():
            return {"built": True, "indexed_rows": len(self.index),
                    "capped_tables": self.capped_tables, "from_cache": True}

        self.index = []
        self.capped_tables = []
        total = 0
        try:
            dbs = self.database_service.discover_databases() if self.database_service else []
        except Exception as e:
            return {"built": False, "error": f"discover_failed: {e}", "indexed_rows": 0}

        for d in dbs:
            if not (d.get("accessible") and d.get("exists")):
                continue
            db_name = d.get("name")
            try:
                sch = self.database_service.get_schema(db_name)
            except Exception:
                continue
            if not sch or not sch.get("success"):
                continue
            schema = sch.get("schema") or {}
            row_counts = sch.get("row_counts") or {}
            for table in (sch.get("tables") or list(schema.keys())):
                if total >= self.max_total_rows:
                    break
                if progress:
                    try:
                        progress(db_name, table)
                    except Exception:
                        pass
                try:
                    res = self.database_service.execute_query(
                        db_name, f'SELECT rowid, * FROM "{table}" LIMIT {self.per_table_cap}'
                    )
                except Exception:
                    continue
                if not res or not res.get("success"):
                    continue
                rows = res.get("data") or []
                grand_total = row_counts.get(table)
                if isinstance(grand_total, int) and grand_total > len(rows):
                    self.capped_tables.append({
                        "database": db_name, "table": table,
                        "total": grand_total, "indexed": len(rows),
                    })
                for row in rows:
                    if total >= self.max_total_rows:
                        break
                    text = self._row_to_text(table, row)
                    if not text:
                        continue
                    emb = self.embedding_client.embed_text(text, is_query=False)
                    if not emb:
                        continue
                    self.index.append({
                        "database": db_name, "table": table,
                        "rowid": row.get("rowid"), "text": text, "embedding": emb,
                    })
                    total += 1

        self.built = True
        self._save()
        self.logger.info(
            f"Built evidence semantic index: {len(self.index)} rows, "
            f"{len(self.capped_tables)} capped table(s)."
        )
        return {"built": True, "indexed_rows": len(self.index),
                "capped_tables": self.capped_tables}

    # ------------------------------------------------------------------
    def search(self, query: str, top_k: int = 10,
               tables: Optional[List[str]] = None) -> Dict[str, Any]:
        """Return semantic CANDIDATE rows for ``query`` with full provenance.

        Builds the index lazily on first use. Candidates are ranked by cosine
        similarity and carry ``database``/``table``/``rowid`` so the model can
        confirm them with exact SQL.
        """
        if not self.available():
            return {"success": False, "error": "Semantic search unavailable (no embedding server configured).",
                    "candidates": []}
        if not self.built:
            self.build()
        if not self.index:
            return {"success": True, "candidates": [], "note": "Evidence index is empty."}

        qemb = self.embedding_client.embed_text(query, is_query=True)
        if not qemb:
            return {"success": False, "error": "Failed to embed query.", "candidates": []}

        tset = {t.lower() for t in tables} if tables else None
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for item in self.index:
            if tset and (item.get("table") or "").lower() not in tset:
                continue
            scored.append((cosine_similarity(qemb, item["embedding"]), item))
        scored.sort(key=lambda x: x[0], reverse=True)

        candidates = []
        for score, item in scored[: max(1, int(top_k))]:
            candidates.append({
                "database": item.get("database"),
                "table": item.get("table"),
                "rowid": item.get("rowid"),
                "score": round(float(score), 4),
                "preview": item.get("text", "")[:300],
            })
        return {
            "success": True,
            "candidates": candidates,
            "total_indexed": len(self.index),
            "capped_tables": self.capped_tables,
            "guidance": (
                "These are SEMANTIC CANDIDATES (approximate, ranked by similarity) — NOT a "
                "complete result set. Confirm each with query_database using its database/table/rowid "
                "(e.g. SELECT * FROM <table> WHERE rowid=<rowid>), and use exact SQL for any "
                "enumeration, count, or timeline. Do not present these as exhaustive."
            ),
        }
