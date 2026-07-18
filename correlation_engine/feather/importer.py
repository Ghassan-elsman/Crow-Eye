"""
FeatherImporter — headless import of external forensic data into a case.

Brings third-party evidence (Plaso / Autopsy / Volatility / custom exports) into
an open Crow-Eye case so the Eye AI and the Timeline can use it:

* A SQLite ``.db`` / ``.sqlite`` is validated and copied verbatim into the case's
  ``Imported_Evidence/`` folder (schema untouched).
* A ``.csv`` / ``.json`` is auto-converted to a feather-shaped SQLite database using
  the canonical :class:`~correlation_engine.feather.writer.FeatherWriter`, so it carries
  ``feather_metadata`` (declaring the table's primary timestamp) exactly like a
  natively-collected feather.

Everything here is stdlib-only (``sqlite3`` / ``csv`` / ``json``) — no pandas, no GUI
coupling — so it can run on a background worker thread. The GUI layer (Eye bridge)
just calls :meth:`FeatherImporter.import_file` with the picked path.

Because ``data/database_manager.py`` auto-discovers any ``.db`` under the case tree
(its "recursive discovery protocol"), dropping the output here is all the Eye needs;
the caller is responsible for invalidating the Eye's cached schema manifest afterwards.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from correlation_engine.feather.writer import FeatherWriter, ColumnSpec

logger = logging.getLogger(__name__)

# Subfolder (under the case artifacts dir) that holds all imported evidence.
IMPORTED_SUBDIR = "Imported_Evidence"

# Column-name hints used to auto-detect the primary timestamp of a converted table.
_TIMESTAMP_NAME_RE = re.compile(
    r"(time|date|timestamp|created|modified|accessed|executed|deleted|installed|"
    r"connected|logon|logoff|start|end|when|_at$|_on$)",
    re.IGNORECASE,
)

# Reserved words that must not be used as bare SQLite identifiers.
_RESERVED = {
    "abort", "action", "add", "after", "all", "alter", "analyze", "and", "as", "asc",
    "attach", "autoincrement", "before", "begin", "between", "by", "cascade", "case",
    "cast", "check", "collate", "column", "commit", "conflict", "constraint", "create",
    "cross", "current_date", "current_time", "current_timestamp", "database", "default",
    "deferrable", "deferred", "delete", "desc", "detach", "distinct", "drop", "each",
    "else", "end", "escape", "except", "exclusive", "exists", "explain", "fail", "for",
    "foreign", "from", "full", "glob", "group", "having", "if", "ignore", "immediate",
    "in", "index", "indexed", "initially", "inner", "insert", "instead", "intersect",
    "into", "is", "isnull", "join", "key", "left", "like", "limit", "match", "natural",
    "no", "not", "notnull", "null", "of", "offset", "on", "or", "order", "outer", "plan",
    "pragma", "primary", "query", "raise", "recursive", "references", "regexp", "reindex",
    "release", "rename", "replace", "restrict", "right", "rollback", "row", "savepoint",
    "select", "set", "table", "temp", "temporary", "then", "to", "transaction", "trigger",
    "union", "unique", "update", "using", "vacuum", "values", "view", "virtual", "when",
    "where", "with", "without",
}


class ImportError_(Exception):
    """Raised when an evidence file cannot be imported/converted."""


def sanitize_identifier(name: str) -> str:
    """Return a safe SQLite identifier (mirrors FeatherDatabase.sanitize_identifier)."""
    name = re.sub(r"[^\w]", "_", str(name)).strip("_")
    if name and name[0].isdigit():
        name = f"col_{name}"
    if not name:
        name = "column"
    if name.lower() in _RESERVED:
        name = f"{name}_col"
    return name


def _looks_like_timestamp(value: Any) -> bool:
    """Best-effort check that a scalar value is parseable as a date/time."""
    if value is None:
        return False
    if isinstance(value, datetime):
        return True
    s = str(value).strip()
    if not s:
        return False
    # ISO-8601 (allow a trailing 'Z' and a space instead of 'T').
    iso = s.replace("Z", "").replace("z", "")
    if " " in iso and "T" not in iso:
        iso = iso.replace(" ", "T", 1)
    try:
        datetime.fromisoformat(iso)
        return True
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%d/%m/%Y %H:%M:%S",
        "%Y/%m/%d %H:%M:%S", "%b %d %Y %H:%M:%S", "%a %b %d %H:%M:%S %Y",
    ):
        try:
            datetime.strptime(s, fmt)
            return True
        except ValueError:
            continue
    return False


def _normalize_timestamp(value: Any) -> Any:
    """Normalize a recognised timestamp to ISO-8601; return the original on failure."""
    if value is None or value == "":
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    s = str(value).strip()
    iso = s.replace("Z", "").replace("z", "")
    if " " in iso and "T" not in iso:
        iso = iso.replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(iso).isoformat()
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%d/%m/%Y %H:%M:%S",
        "%Y/%m/%d %H:%M:%S", "%b %d %Y %H:%M:%S", "%a %b %d %H:%M:%S %Y",
    ):
        try:
            return datetime.strptime(s, fmt).isoformat()
        except ValueError:
            continue
    return value  # leave untouched if we can't confidently parse it


def _infer_sql_type(values: List[Any]) -> str:
    """Infer a SQLite storage type from a sample of a column's values."""
    seen = [v for v in values if v not in (None, "")]
    if not seen:
        return "TEXT"
    all_int = True
    all_real = True
    for v in seen:
        s = str(v).strip()
        try:
            int(s)
        except (ValueError, TypeError):
            all_int = False
        try:
            float(s)
        except (ValueError, TypeError):
            all_real = False
        if not all_int and not all_real:
            break
    if all_int:
        return "INTEGER"
    if all_real:
        return "REAL"
    return "TEXT"


class FeatherImporter:
    """Import/convert external evidence into a case's ``Imported_Evidence/`` folder."""

    SQLITE_EXTS = {".db", ".sqlite", ".sqlite3", ".db3"}
    CSV_EXTS = {".csv", ".tsv", ".txt"}
    JSON_EXTS = {".json", ".jsonl", ".ndjson"}

    def __init__(self, case_artifacts_dir: str):
        self.artifacts_dir = Path(case_artifacts_dir)
        self.dest_dir = self.artifacts_dir / IMPORTED_SUBDIR

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #
    def import_file(self, src_path: str, progress=None) -> Dict[str, Any]:
        """Import ``src_path`` (dispatch by extension). Returns a result dict:

        ``{ok, source_type, dest_db, table, row_count, primary_timestamp, display_name, error}``
        """
        src = Path(src_path)
        if not src.is_file():
            return self._fail(f"File not found: {src_path}")
        ext = src.suffix.lower()
        try:
            self.dest_dir.mkdir(parents=True, exist_ok=True)
            if ext in self.SQLITE_EXTS:
                return self._import_sqlite(src, progress)
            if ext in self.CSV_EXTS:
                return self._convert_csv(src, progress)
            if ext in self.JSON_EXTS:
                return self._convert_json(src, progress)
            return self._fail(f"Unsupported file type '{ext}'. Use .db/.sqlite, .csv or .json.")
        except ImportError_ as e:
            return self._fail(str(e))
        except Exception as e:  # defensive: never crash the caller
            logger.exception("Import failed for %s", src_path)
            return self._fail(f"Import failed: {e}")

    # ------------------------------------------------------------------ #
    # SQLite: validate + copy
    # ------------------------------------------------------------------ #
    def _import_sqlite(self, src: Path, progress=None) -> Dict[str, Any]:
        self._emit(progress, f"Validating SQLite database '{src.name}'…")
        self._validate_sqlite(src)
        dest = self._unique_dest(src.stem)
        self._emit(progress, f"Copying into case ({dest.name})…")
        shutil.copy2(src, dest)
        # Best-effort: report the largest user table + a row count for the toast.
        table, rows = self._largest_table(dest)
        return {
            "ok": True,
            "source_type": "sqlite",
            "dest_db": str(dest),
            "table": table,
            "row_count": rows,
            "primary_timestamp": None,
            "display_name": dest.stem,
            "error": None,
        }

    @staticmethod
    def _validate_sqlite(src: Path) -> None:
        try:
            conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
            try:
                cur = conn.execute("PRAGMA schema_version")
                cur.fetchone()
                names = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                if not names:
                    raise ImportError_("SQLite database contains no tables.")
            finally:
                conn.close()
        except sqlite3.DatabaseError as e:
            raise ImportError_(f"Not a valid SQLite database: {e}")

    @staticmethod
    def _largest_table(db: Path) -> Tuple[Optional[str], int]:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'feather_%'"
                ).fetchall()
            ]
            best, best_n = None, -1
            for t in tables:
                try:
                    n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                except sqlite3.Error:
                    continue
                if n > best_n:
                    best, best_n = t, n
            return best, max(best_n, 0)
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # CSV → feather
    # ------------------------------------------------------------------ #
    def _convert_csv(self, src: Path, progress=None) -> Dict[str, Any]:
        import csv

        self._emit(progress, f"Reading CSV '{src.name}'…")
        with open(src, "r", encoding="utf-8-sig", newline="") as f:
            sample = f.read(8192)
            f.seek(0)
            delimiter = ","
            has_header = True
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
                delimiter = dialect.delimiter
            except csv.Error:
                if src.suffix.lower() == ".tsv":
                    delimiter = "\t"
            try:
                has_header = csv.Sniffer().has_header(sample)
            except csv.Error:
                has_header = True

            reader = csv.reader(f, delimiter=delimiter)
            try:
                first = next(reader)
            except StopIteration:
                raise ImportError_("CSV file is empty.")
            if has_header:
                headers = first
                data_iter = reader
            else:
                headers = [f"column_{i + 1}" for i in range(len(first))]
                data_iter = self._chain_first(first, reader)

            rows = [dict(zip(headers, r)) for r in data_iter]

        if not rows:
            raise ImportError_("CSV file has no data rows.")
        return self._write_feather(src, headers, rows, "csv", progress)

    @staticmethod
    def _chain_first(first, reader):
        yield first
        for r in reader:
            yield r

    # ------------------------------------------------------------------ #
    # JSON → feather
    # ------------------------------------------------------------------ #
    def _convert_json(self, src: Path, progress=None) -> Dict[str, Any]:
        self._emit(progress, f"Reading JSON '{src.name}'…")
        records: List[Dict[str, Any]]
        if src.suffix.lower() in (".jsonl", ".ndjson"):
            records = []
            with open(src, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        else:
            with open(src, "r", encoding="utf-8") as f:
                doc = json.load(f)
            records = self._extract_records(doc)

        if not records:
            raise ImportError_("JSON file contained no importable records.")

        flat = [self._flatten(r) for r in records if isinstance(r, dict)]
        if not flat:
            raise ImportError_("JSON records were not objects; cannot map to columns.")

        # Column order = first-seen order across the union of all record keys.
        headers: List[str] = []
        seen = set()
        for r in flat:
            for k in r.keys():
                if k not in seen:
                    seen.add(k)
                    headers.append(k)
        return self._write_feather(src, headers, flat, "json", progress)

    @staticmethod
    def _extract_records(doc: Any) -> List[Any]:
        if isinstance(doc, list):
            return doc
        if isinstance(doc, dict):
            # Prefer the largest top-level array (common export shape).
            best: List[Any] = []
            for v in doc.values():
                if isinstance(v, list) and len(v) > len(best):
                    best = v
            if best:
                return best
            return [doc]  # single-object document
        return []

    @classmethod
    def _flatten(cls, obj: Any, prefix: str = "") -> Dict[str, Any]:
        """Flatten nested dicts with dot→underscore keys; JSON-encode lists/leftover dicts."""
        out: Dict[str, Any] = {}
        if not isinstance(obj, dict):
            return {"value": obj}
        for k, v in obj.items():
            key = f"{prefix}_{k}" if prefix else str(k)
            if isinstance(v, dict):
                out.update(cls._flatten(v, key))
            elif isinstance(v, list):
                out[key] = json.dumps(v, ensure_ascii=False, default=str)
            else:
                out[key] = v
        return out

    # ------------------------------------------------------------------ #
    # Shared write path (CSV + JSON)
    # ------------------------------------------------------------------ #
    def _write_feather(
        self, src: Path, headers: List[str], rows: List[Dict[str, Any]],
        source_type: str, progress=None,
    ) -> Dict[str, Any]:
        # Map raw header -> unique sanitized column name.
        colmap: Dict[str, str] = {}
        used = set()
        for h in headers:
            base = sanitize_identifier(h)
            name = base
            i = 2
            while name.lower() in used:
                name = f"{base}_{i}"
                i += 1
            used.add(name.lower())
            colmap[h] = name

        # Sample values per sanitized column for type inference + timestamp detection.
        sample = rows[: min(len(rows), 500)]
        samples: Dict[str, List[Any]] = {c: [] for c in colmap.values()}
        for r in sample:
            for h, c in colmap.items():
                samples[c].append(r.get(h))

        ts_col = self._detect_timestamp_column(colmap, samples)

        specs: List[ColumnSpec] = []
        for h in headers:
            c = colmap[h]
            if c == ts_col:
                specs.append(ColumnSpec(c, "TEXT", is_timestamp=True, is_primary_timestamp=True))
            else:
                specs.append(ColumnSpec(c, _infer_sql_type(samples[c]), is_identity=self._is_identity(c)))

        table = sanitize_identifier(src.stem) or "imported_data"
        dest = self._unique_dest(src.stem)

        self._emit(progress, f"Writing {len(rows):,} rows to feather '{dest.name}'…")
        writer = FeatherWriter()
        writer.open(str(dest), artifact_type="Imported")
        try:
            writer.declare_table(table, specs)

            def _row_gen():
                for r in rows:
                    out = {}
                    for h, c in colmap.items():
                        v = r.get(h)
                        out[c] = _normalize_timestamp(v) if c == ts_col else v
                    yield out

            count = writer.write_batch(_row_gen())
            writer.add_lineage(source_path=str(src), row_count=count,
                               notes=f"Imported from {source_type.upper()} via FeatherImporter")
        finally:
            writer.close()

        return {
            "ok": True,
            "source_type": source_type,
            "dest_db": str(dest),
            "table": table,
            "row_count": count,
            "primary_timestamp": ts_col,
            "display_name": dest.stem,
            "error": None,
        }

    @staticmethod
    def _detect_timestamp_column(colmap: Dict[str, str], samples: Dict[str, List[Any]]) -> Optional[str]:
        """Pick the primary timestamp: prefer a name-hinted column whose values parse."""
        candidates = [c for c in colmap.values() if _TIMESTAMP_NAME_RE.search(c)]
        ordered = candidates + [c for c in colmap.values() if c not in candidates]
        for c in ordered:
            vals = [v for v in samples.get(c, []) if v not in (None, "")]
            if not vals:
                continue
            hits = sum(1 for v in vals[:50] if _looks_like_timestamp(v))
            if hits and hits >= max(1, int(0.6 * min(len(vals), 50))):
                return c
        return None

    @staticmethod
    def _is_identity(col: str) -> bool:
        return bool(re.search(r"(name|path|file|host|user|sid|hash|process|image)", col, re.IGNORECASE))

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _unique_dest(self, stem: str) -> Path:
        base = sanitize_identifier(stem) or "imported"
        dest = self.dest_dir / f"{base}.db"
        i = 2
        while dest.exists():
            dest = self.dest_dir / f"{base}_{i}.db"
            i += 1
        return dest

    @staticmethod
    def _emit(progress, msg: str) -> None:
        if progress:
            try:
                progress(msg)
            except Exception:
                pass
        logger.info("[FeatherImporter] %s", msg)

    @staticmethod
    def _fail(msg: str) -> Dict[str, Any]:
        logger.warning("[FeatherImporter] %s", msg)
        return {
            "ok": False, "source_type": None, "dest_db": None, "table": None,
            "row_count": 0, "primary_timestamp": None, "display_name": None, "error": msg,
        }
