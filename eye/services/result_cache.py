"""
Result cache — structured reuse of forensic query results within a case.

The case's forensic SQLite databases are READ-ONLY and static for the lifetime of
an investigation, so an identical SQL query always yields an identical result.
This cache lets the Eye reuse a prior result instead of re-running (and
re-reasoning over) the same query, and surfaces "reused prior result" provenance.

Only fully-captured results (≤ ``ROW_CAP`` rows) are served from cache; larger
results store metadata only (for the reuse hint) and are re-run on demand so the
TOON/map-reduce paths stay authoritative for big data.
"""

import json
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional


class ResultCache:
    ROW_CAP = 1000  # full results up to this size are served from cache

    def __init__(self, case_directory):
        self.case_directory = Path(case_directory) if case_directory else None
        self.logger = logging.getLogger(self.__class__.__name__)
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._load()

    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_sql(sql: str) -> str:
        """Conservative normalization: collapse whitespace, drop a trailing
        semicolon, strip. Case is preserved (identifiers can be case-sensitive)."""
        return re.sub(r"\s+", " ", (sql or "").strip()).rstrip(";").strip()

    def _key(self, database: str, sql: str) -> str:
        return f"{database}::{self._normalize_sql(sql)}"

    def _file(self) -> Optional[Path]:
        if not self.case_directory:
            return None
        return self.case_directory / "EYE_Logs" / "eye_result_cache.jsonl"

    # ------------------------------------------------------------------
    def _load(self):
        path = self._file()
        if not path or not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if rec.get("key"):
                        self._cache[rec["key"]] = rec
        except Exception as e:
            self.logger.debug(f"Result cache load failed: {e}")

    def _append(self, rec: Dict[str, Any]):
        path = self._file()
        if not path:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            self.logger.debug(f"Result cache append failed: {e}")

    # ------------------------------------------------------------------
    def get(self, database: str, sql: str) -> Optional[Dict[str, Any]]:
        return self._cache.get(self._key(database, sql))

    def put(self, database: str, sql: str, result: Dict[str, Any]):
        """Store a successful query result. Full data is kept only up to ROW_CAP;
        larger results store metadata + a small sample for the reuse hint."""
        try:
            if not result or not result.get("success"):
                return
            key = self._key(database, sql)
            if key in self._cache:
                return  # already cached (static DBs → identical result)
            data = result.get("data") or []
            row_count = int(result.get("row_count") or len(data))
            columns = result.get("columns") or []
            full = row_count <= self.ROW_CAP
            rec = {
                "key": key,
                "database": database,
                "sql": self._normalize_sql(sql),
                "columns": columns,
                "row_count": row_count,
                "ts": datetime.now().isoformat(),
                "full": full,
                "data": data if full else (data[:5] if data else []),
            }
            self._cache[key] = rec
            self._append(rec)
        except Exception as e:
            self.logger.debug(f"Result cache put failed: {e}")

    def recent(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Most-recently-cached entries (compact handles for the prior-findings
        block) so the model knows what it can reuse instead of re-querying."""
        items = sorted(self._cache.values(), key=lambda r: r.get("ts", ""), reverse=True)
        out = []
        for r in items[: max(0, limit)]:
            out.append({"database": r.get("database"), "sql": r.get("sql"),
                        "row_count": r.get("row_count")})
        return out
