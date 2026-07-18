"""
Forensic Tool Handlers for EYE AI Assistant.

This module contains the implementation of core forensic tools:
- Database querying (with TOON compression)
- Schema discovery
- Artifact searching
- Correlation analysis
- Case file navigation
- Internet forensic research
- Live Forensic Intelligence (LOLBAS, LOLDrivers, etc.)
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
import urllib.request
import urllib.parse
import requests

class ForensicHandlers:
    """
    Implementation of forensic investigative tools.
    """
    
    def __init__(self, context_manager):
        self.cm = context_manager
        self.logger = logging.getLogger(__name__)
        # Session-level intelligence cache to avoid repeated downloads
        self._intel_cache: Dict[str, List[Dict]] = {}
        self._intel_cache_time: Dict[str, float] = {}
        self._intel_urls = {
            "loldrivers": "https://www.loldrivers.io/api/drivers.json",
            "bootloaders": "https://www.bootloaders.io/api/bootloaders.json",
            "lolbas": "https://lolbas-project.github.io/api/lolbas.json",
            "lofl": "https://lofl-project.github.io/api/loflcab.json"
        }
        self._fetching_thread = None

    def handle_query_database(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute SQL SELECT query against forensic database."""
        db = params.get("database_name")
        sql = params.get("sql_query")

        if not db or not sql:
            return {"success": False, "error": "Missing database_name or sql_query"}

        # Reuse a prior identical result when available (case DBs are read-only
        # and static, so the result is guaranteed identical). Only fully-captured
        # results are served from cache; large results fall through to a fresh run
        # so the TOON/map-reduce paths still govern big data.
        cache = getattr(self.cm, "result_cache", None)
        if cache is not None:
            hit = cache.get(db, sql)
            if isinstance(hit, dict) and hit.get("full"):
                res = {
                    "success": True,
                    "columns": hit.get("columns", []),
                    "data": hit.get("data", []),
                    "row_count": hit.get("row_count", len(hit.get("data", []))),
                    "cached": True,
                }
                if res["row_count"] > 200:
                    out = self._apply_toon_compression(res)
                    out["cached"] = True
                    return out
                return res

        res = self.cm.database_service.execute_query(db, sql)

        # Persist successful results for reuse within the case.
        if cache is not None and res.get("success"):
            cache.put(db, sql, res)

        # Compress only when the result is large enough to threaten the context
        # window. Below this, the model sees EVERY row so its chat answer is
        # complete (the system-prompt TOON docs document this same threshold).
        if res.get("row_count", 0) > 200:
            return self._apply_toon_compression(res)
        return res

    def _apply_toon_compression(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Compress large results for LLM consumption while keeping full data for UI."""
        full_rows = results.get("data", []) or results.get("rows", [])
        

        # AI sees first 10 and last 10
        sample_rows = full_rows[:10] + full_rows[-10:] if len(full_rows) > 20 else full_rows
        

        # but apply a safe hard limit for the AI's "back-of-napkin" memory if needed
        return {
            # Preserve success so the pipeline's status step (result.get("success"))
            # does not mislabel a successful large query as an "error".
            "success": results.get("success", True),
            "columns": results.get("columns", []),
            "rows": sample_rows,             # The AI sees this in context
            "full_rows": full_rows,          # The UI Data Viewer (bridge) sees this
            "row_count": results.get("row_count"),
            "compressed": True,
            "toon_summary": (
                f"COMPRESSED RESULT — this is a SAMPLE, not the full data. "
                f"Total rows: {results.get('row_count')}; only the first 10 and last 10 are shown here. "
                f"Do NOT present this sample as the complete result. For any answer that needs ALL rows "
                f"(enumeration, per-category counts, a full timeline), call analyze_large_dataset (map-reduce "
                f"over the whole result), or report_add_data_table (persists the FULL result to the report), "
                f"or re-query with a tighter WHERE/LIMIT. Always state the true total row count."
            )
        }

    def handle_analyze_large_dataset(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Map-Reduce analysis over a WHOLE large artifact (no silent truncation)."""
        db = params.get("database_name")
        sql = params.get("sql_query")
        instruction = params.get("instruction")
        if not db or not sql or not instruction:
            return {"success": False, "error": "Missing database_name, sql_query, or instruction."}
        from eye.services.map_reduce_service import MapReduceService
        try:
            budget = int(params.get("chunk_token_budget", 3000) or 3000)
        except (TypeError, ValueError):
            budget = 3000
        return MapReduceService(self.cm).analyze(db, sql, instruction, chunk_token_budget=budget)

    def handle_get_schema(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get table schema information for database discovery."""
        db = params.get("database_name")
        table = params.get("table_name")
        return self.cm.database_service.get_schema(db, table)

    def handle_search_artifacts(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Search across all forensic databases using text or regex.

        ``SearchResults.results`` is ``Dict[str, List[SearchResult]]`` where
        ``SearchResult`` is a dataclass (NOT JSON-serializable). We flatten it
        into plain dicts using the real field names and cap by total match ROWS
        (not by table count) so a successful search can never crash the turn or
        blow the context window.
        """
        from eye.services.search_service import SearchConfig
        term = params.get("search_term")
        use_regex = params.get("use_regex", False)

        if not term:
            return {"success": False, "error": "Missing search_term parameter."}

        config = SearchConfig(search_term=term, use_regex=use_regex)
        results = self.cm.search_service.search(config)

        MAX_ROWS = 50
        flattened: List[Dict[str, Any]] = []
        for table_name, table_results in (results.results or {}).items():
            for sr in table_results:
                if len(flattened) >= MAX_ROWS:
                    break
                flattened.append({
                    "database": getattr(sr, "database", None),
                    "table": getattr(sr, "table_name", table_name),
                    "row_id": getattr(sr, "row_id", None),
                    "matched_columns": getattr(sr, "matched_columns", []),
                    "record": getattr(sr, "record_data", {}),
                    "relevance": getattr(sr, "relevance_score", 1.0),
                })
            if len(flattened) >= MAX_ROWS:
                break

        total = getattr(results, "total_matches", len(flattened))
        return {
            "success": True,
            "results": flattened,
            "total_matches": total,
            "note": (f"Showing {len(flattened)} of {total} matches (capped for context efficiency)."
                     if total > len(flattened) else ""),
        }

    def handle_query_correlation_results(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Query the Crow-eye Correlation Engine output."""
        if not self.cm.correlation_service or not self.cm.correlation_service.database_exists():
            return {
                "success": False, 
                "error": "Correlation database not found. Run the Correlation Engine in Crow-eye first."
            }
            
        qtype = params.get("query_type")
        if qtype == "statistics":
            return self.cm.correlation_service.get_correlation_statistics()
        if qtype == "time":
            return self.cm.correlation_service.query_time_correlations(
                params.get("start_time"), 
                params.get("end_time")
            )
        if qtype == "identity":
            return self.cm.correlation_service.query_identity_correlations(
                params.get("identity_type"), 
                params.get("identity_value")
            )
        return {"success": False, "error": f"Unsupported correlation query type: {qtype}"}

    def handle_correlate_imported_evidence(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Tool entry: check whether imported external evidence correlates with native artifacts."""
        try:
            max_values = int(params.get("max_values", 25) or 25)
        except (TypeError, ValueError):
            max_values = 25
        try:
            window = int(params.get("time_window_minutes", 60) or 60)
        except (TypeError, ValueError):
            window = 60
        return self.correlate_imported_evidence_core(
            database=params.get("database"),
            max_values=max(1, min(max_values, 200)),
            time_window_minutes=max(1, window),
        )

    # Timestamp-ish column names looked at when extracting a time from a native hit.
    _NATIVE_TS_FIELDS = (
        "timestamp", "last_executed", "last_execution", "created_on", "modified_on",
        "accessed_on", "Time_Creation", "Time_Modification", "Time_Access",
        "deletion_time", "last_modified", "install_date", "event_time",
        "EventTimestampUTC", "created_time", "modified_time", "usn_timestamp",
    )

    def correlate_imported_evidence_core(self, database: Optional[str] = None,
                                         max_values: int = 25,
                                         time_window_minutes: int = 60,
                                         max_matches: int = 40) -> Dict[str, Any]:
        """Cross-reference imported evidence against native artifacts.

        Extracts identity values (filenames/users/IPs/hashes) from imported-evidence
        databases and searches native artifact tables (their identity-ish columns) for
        the same values via read-only SQL, returning whether correlations exist plus
        concrete native matches (database:table:rowid). Self-contained (uses
        database_service.execute_query only). Reused by the tool AND case-open triage.
        """
        ds = getattr(self.cm, "database_service", None)
        if ds is None:
            return {"success": False, "error": "Database service unavailable."}

        try:
            dbs = ds.discover_databases()
        except Exception as e:
            return {"success": False, "error": f"Database discovery failed: {e}"}

        imported = [d for d in dbs if d.get("category") == "Imported Evidence" and d.get("accessible")]
        if database:
            want = database.lower()
            imported = [d for d in imported
                        if (d.get("name") or "").lower() == want
                        or Path(d.get("path") or "").name.lower() == want]
        if not imported:
            return {
                "success": True, "correlation_found": False, "imported_databases": [],
                "identity_matches": [], "time_overlap": None,
                "summary": ("No imported-evidence databases found in this case."
                            if not database else f"No imported database named '{database}'."),
            }

        imported_tables = {t for d in imported for t in (d.get("tables") or [])}

        # 1) Collect distinct identity values (+ their imported timestamp/source) to test.
        #    Search terms are capped to keep the cross-DB scan bounded.
        value_ts: Dict[str, Optional[str]] = {}
        value_source: Dict[str, str] = {}
        tables_meta: List[Dict[str, Any]] = []
        for d in imported:
            dbname = d.get("name")
            for table in (d.get("tables") or []):
                id_cols, ts_col = self._imported_table_columns(dbname, table)
                tables_meta.append({"database": dbname, "table": table,
                                    "identity_columns": id_cols, "timestamp_column": ts_col})
                if not id_cols:
                    continue
                for val, vts in self._sample_identity_values(dbname, table, id_cols, ts_col, max_values):
                    if val not in value_ts:
                        value_ts[val] = vts
                        value_source[val] = f"{dbname}:{table}"

        # Cap the number of search terms actually run against native tables (perf guard).
        search_values = list(value_ts.items())[: min(max_matches, 20)]

        # 2) Build native search targets (identity-ish columns of non-imported tables).
        targets = self._native_targets(dbs, imported_tables)

        # 3) One bounded OR-LIKE scan per native table for the whole batch of values.
        matches_by_value = self._find_native_matches(targets, search_values, time_window_minutes)

        identity_matches: List[Dict[str, Any]] = []
        for val, _vts in search_values:
            hits = matches_by_value.get(val)
            if hits:
                identity_matches.append({
                    "value": val,
                    "imported_source": value_source.get(val),
                    "imported_timestamp": value_ts.get(val),
                    "native_hits": hits[:8],
                })

        correlation_found = bool(identity_matches)
        temporal_hits = sum(1 for m in identity_matches for h in m["native_hits"] if h.get("temporal_match"))

        # Consult the Correlation Engine's own output if it exists (separate subsystem).
        note = None
        try:
            cs = getattr(self.cm, "correlation_service", None)
            if cs is not None and cs.database_exists():
                note = ("The Crow-Eye Correlation Engine output is also available — use "
                        "`query_correlation_results` for its precomputed native-artifact correlations.")
        except Exception:
            pass

        if correlation_found:
            summary = (f"Imported evidence CORRELATES with native artifacts: "
                       f"{len(identity_matches)} shared identity value(s) found across "
                       f"{len({d.get('name') for d in imported})} imported database(s)"
                       + (f", {temporal_hits} within {time_window_minutes} min of a native event." if temporal_hits
                          else "."))
        else:
            summary = ("No shared identities found between the imported evidence and native "
                       "artifacts (checked filenames/users/IPs/hashes). The imported data may be "
                       "independent, or use identifiers not present in native artifacts.")

        return {
            "success": True,
            "correlation_found": correlation_found,
            "imported_databases": sorted({d.get("name") for d in imported}),
            "imported_tables": tables_meta,
            "identity_matches": identity_matches,
            "temporal_matches": temporal_hits,
            "time_window_minutes": time_window_minutes,
            "summary": summary,
            "note": note,
        }

    def _imported_table_columns(self, dbname: str, table: str):
        """Return (identity_columns, primary_timestamp_column) for an imported table.

        Prefers the feather_metadata stamped by FeatherImporter/FeatherWriter; falls back
        to column-name heuristics for directly-imported (metadata-less) SQLite files."""
        import re as _re
        ds = self.cm.database_service
        id_cols: List[str] = []
        ts_col = None
        # 1. feather_metadata (converted CSV/JSON imports declare these explicitly)
        try:
            res = ds.execute_query(dbname, f"SELECT value FROM feather_metadata WHERE key = 'table:{table}'")
            if res.get("success") and res.get("data"):
                blob = json.loads(res["data"][0].get("value") or "{}")
                id_cols = list(blob.get("identity_columns") or [])
                ts_col = blob.get("primary_timestamp_column")
        except Exception:
            pass
        # 2. Fall back to name heuristics over the real columns
        try:
            cols_res = ds.execute_query(dbname, f'PRAGMA table_info("{table}")')
            cols = [r.get("name") for r in (cols_res.get("data") or []) if r.get("name")]
        except Exception:
            cols = []
        id_cols = [c for c in id_cols if c in cols]  # keep only real columns
        if not id_cols and cols:
            id_re = _re.compile(r"(name|path|file|host|user|sid|hash|process|image|url|ip|account|email|domain)", _re.I)
            id_cols = [c for c in cols if id_re.search(c)]
        if not ts_col and cols:
            ts_re = _re.compile(r"(time|date|timestamp|created|modified|accessed|executed)", _re.I)
            ts_col = next((c for c in cols if ts_re.search(c)), None)
        return id_cols, ts_col

    def _sample_identity_values(self, dbname: str, table: str, id_cols: List[str],
                                ts_col: Optional[str], max_values: int):
        """Yield up to max_values distinct (value, timestamp) pairs from the imported table."""
        out = []
        seen = set()
        for id_col in id_cols[:3]:  # a couple of identity columns is plenty
            if len(out) >= max_values:
                break
            select_ts = f', "{ts_col}" AS ts' if ts_col else ""
            sql = (f'SELECT DISTINCT "{id_col}" AS v{select_ts} FROM "{table}" '
                   f'WHERE "{id_col}" IS NOT NULL LIMIT {max_values * 2}')
            try:
                res = self.cm.database_service.execute_query(dbname, sql)
            except Exception:
                continue
            if not res.get("success"):
                continue
            for row in (res.get("data") or []):
                v = row.get("v")
                if v is None:
                    continue
                sval = str(v).strip()
                # Skip empty / very short / purely-numeric-tiny / generic values to avoid noise.
                if len(sval) < 3 or sval.lower() in seen:
                    continue
                seen.add(sval.lower())
                out.append((sval, row.get("ts") if ts_col else None))
                if len(out) >= max_values:
                    break
        return out

    # Column-name hint for identity-bearing columns (native + imported).
    import re as _re_mod
    _IDENTITY_RE = _re_mod.compile(
        r"(name|path|file|host|user|sid|hash|process|image|url|ip|account|email|domain|exe|command)",
        _re_mod.I,
    )

    def _native_targets(self, dbs, imported_tables, max_tables: int = 40, max_cols: int = 6):
        """Build (dbname, table, [identity-ish columns]) for non-imported tables.

        Restricting to identity-ish columns keeps the OR-LIKE scan cheap and semantically
        aligned with 'shared identity' correlation. Falls back to a few text columns."""
        targets = []
        for d in dbs:
            if d.get("category") == "Imported Evidence" or not d.get("accessible"):
                continue
            dbname = d.get("name")
            for table in (d.get("tables") or []):
                if table in imported_tables:
                    continue
                cols = self._table_columns(dbname, table)
                if not cols:
                    continue
                id_cols = [c for c in cols if self._IDENTITY_RE.search(c)]
                use = (id_cols or cols)[:max_cols]
                targets.append((dbname, table, use))
                if len(targets) >= max_tables:
                    return targets
        return targets

    def _table_columns(self, dbname: str, table: str) -> List[str]:
        try:
            res = self.cm.database_service.execute_query(dbname, f'PRAGMA table_info("{table}")')
            return [r.get("name") for r in (res.get("data") or []) if r.get("name")]
        except Exception:
            return []

    def _find_native_matches(self, targets, search_values, window_minutes):
        """One bounded OR-LIKE query per native target; return {value: [hit, ...]}."""
        from collections import defaultdict
        out = defaultdict(list)
        if not search_values:
            return out
        vals = [v for v, _ in search_values]
        ts_map = {v: t for v, t in search_values}
        for dbname, table, cols in targets:
            terms, params = [], []
            for c in cols:
                for v in vals:
                    terms.append(f'"{c}" LIKE ?')
                    params.append(f"%{v}%")
            if not terms:
                continue
            sql = (f'SELECT rowid AS __rid, * FROM "{table}" '
                   f'WHERE {" OR ".join(terms)} LIMIT 100')
            try:
                res = self.cm.database_service.execute_query(dbname, sql, params)
            except TypeError:
                # execute_query without param support — inline is unsafe, so skip.
                continue
            except Exception:
                continue
            if not res.get("success"):
                continue
            for row in (res.get("data") or []):
                rid = row.get("__rid")
                native_ts = self._extract_native_ts(row)
                # Determine which value(s) this row actually matched.
                lowered = {k: str(v).lower() for k, v in row.items() if v is not None}
                for v in vals:
                    vl = v.lower()
                    mcols = [c for c in cols if c in lowered and vl in lowered[c]]
                    if mcols:
                        out[v].append({
                            "database": dbname, "table": table, "row_id": rid,
                            "matched_columns": mcols, "timestamp": native_ts,
                            "temporal_match": self._within_window(ts_map.get(v), native_ts, window_minutes),
                        })
        return out

    def _extract_native_ts(self, record: Dict[str, Any]) -> Optional[str]:
        for f in self._NATIVE_TS_FIELDS:
            v = record.get(f)
            if v:
                return str(v)
        return None

    @staticmethod
    def _parse_dt(value):
        if value in (None, ""):
            return None
        s = str(value).strip().replace("Z", "").replace("z", "")
        if " " in s and "T" not in s:
            s = s.replace(" ", "T", 1)
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d",
                        "%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
                try:
                    return datetime.strptime(str(value).strip(), fmt)
                except ValueError:
                    continue
        return None

    def _within_window(self, ts1, ts2, minutes) -> bool:
        d1, d2 = self._parse_dt(ts1), self._parse_dt(ts2)
        if not d1 or not d2:
            return False
        return abs((d1 - d2).total_seconds()) <= minutes * 60

    def handle_semantic_search_artifacts(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Semantic (embedding) discovery over forensic data rows.

        Returns ranked CANDIDATE rows with database/table/rowid provenance for a
        natural-language concept ("remote access tools", "powershell download
        cradle"). This is a DISCOVERY aid — candidates are approximate and not
        complete; the model must confirm them with exact SQL (`query_database`).
        """
        svc = getattr(self.cm, "evidence_index_service", None)
        if svc is None or not svc.available():
            return {
                "success": False,
                "error": ("Semantic search is unavailable — no embedding server is configured. "
                          "Enable it in Settings (Semantic Retrieval) or use query_database / "
                          "search_artifacts instead."),
            }
        query = params.get("query") or params.get("search_term")
        if not query:
            return {"success": False, "error": "Missing 'query' parameter."}
        try:
            top_k = int(params.get("top_k", 10) or 10)
        except (TypeError, ValueError):
            top_k = 10
        tables = params.get("tables")
        if isinstance(tables, str):
            tables = [t.strip() for t in tables.split(",") if t.strip()]
        return svc.search(query, top_k=min(50, max(1, top_k)), tables=tables)

    def handle_list_case_files(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Navigate and list files in the case directory."""
        if not self.cm.case_directory:
            return {"success": False, "error": "No case directory configured."}
            
        sub_path = params.get("sub_path", "")

        case_root = Path(self.cm.case_directory).resolve()
        target = (case_root / sub_path).resolve()
        
        # Security: Prevent path traversal using Path.relative_to (robust on Windows)
        try:
            target.relative_to(case_root)
        except ValueError:
            return {"success": False, "error": "Access denied: Path is outside case directory."}
            
        files = []
        total_files = 0
        if target.exists() and target.is_dir():
            for item in target.iterdir():
                try:
                    total_files += 1
                    if len(files) < 50:
                        stat = item.stat()
                        files.append({
                            "name": item.name,
                            "type": "directory" if item.is_dir() else "file",
                            "size": stat.st_size if item.is_file() else 0,
                            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                        })
                except Exception:
                    continue
                    
        result = {"success": True, "files": files}
        if total_files > 50:
            result["note"] = f"List truncated. Showing 50 of {total_files} items to protect context limits."
        return result

    def handle_internet_search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Perform internet forensic research using the dedicated service."""
        query = params.get("query")
        if not query:
            return {"success": False, "error": "Missing search query."}
            
        return self.cm.internet_search_service.search(query)

    def handle_fetch_web_content(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handler for fetching specific forensic technical pages (Anatomy)."""
        url = params.get("url")
        if not url:
            return {"success": False, "error": "URL is required."}
            
        # Security: allow only http(s) URLs whose HOST is an approved forensic/
        # anatomy domain. Hostname matching (exact or subdomain), NOT substring —
        # a substring check let "crow-eye.com.attacker.com" or
        # "evil.test/?x=github.com" through (SSRF), and an unrestricted scheme let
        # "file://" read local files.
        domain_whitelist = ["crow-eye.com", "loldrivers.io", "lolbas-project.github.io", "github.com", "microsoft.com", "msdn.microsoft.com", "learn.microsoft.com"]

        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https") or not host:
            return {
                "success": False,
                "error": "Access Denied: only http(s) URLs are permitted.",
            }
        if not any(host == d or host.endswith("." + d) for d in domain_whitelist):
            return {
                "success": False,
                "error": "Access Denied: URL host not in forensic whitelist. Only technical/anatomy domains are permitted for deep analysis.",
            }

        return self.cm.internet_search_service.fetch_page_content(url)

    def handle_switch_model(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Switch the active LLM model."""
        model_name = params.get("model_name")
        if not model_name:
            return {"success": False, "error": "Missing model_name parameter."}
            
        self.cm.model_router.switch_model(model_name)
        # Re-size the context window to the new model so a larger backend isn't
        # left capped at the previous model's (or default) limit, and rescale
        # the per-component token budget to match the new window.
        self.cm.max_total_tokens = self.cm._resolve_context_window(
            getattr(self.cm, "default_max_total_tokens", 64000)
        )
        self.cm.token_budget = self.cm._resolve_token_budget()
        return {
            "success": True,
            "message": f"Successfully switched to model: {model_name}",
            "max_total_tokens": self.cm.max_total_tokens,
            "token_budget": self.cm.token_budget,
        }

    def handle_query_threat_intel(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Query external threat intelligence (VirusTotal) for indicator reputation."""
        indicator = params.get("indicator")
        indicator_type = params.get("indicator_type", "auto")
        
        if not indicator:
            return {"success": False, "error": "Missing indicator parameter."}
            
        return self.cm.threat_intel_service.query_threat_intel(indicator, indicator_type)

    def handle_query_living_off_the_land_intel(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Query live intel for binaries, scripts, or drivers."""
        binary_name = params.get("binary_name", "").upper()
        if not binary_name:
            return {"success": False, "error": "Missing binary_name parameter."}

        self._ensure_intel_fetched()

        # If the feeds genuinely could not be loaded (offline / sources down),
        # do NOT report an authoritative "no match" — that would falsely clear a
        # potential LOLBIN. Return an explicit unavailable status so the model
        # tells the investigator to retry instead of concluding the binary is safe.
        if not any(self._intel_cache.get(k) for k in self._intel_urls):
            return {
                "success": False,
                "intel_unavailable": True,
                "error": (
                    "Live Living-off-the-Land intelligence feeds (LOLBAS / LOLDrivers / "
                    "Bootloaders / LOFL) could not be loaded — likely no network access to "
                    f"the sources. I cannot confirm OR rule out '{binary_name}' as a LOLBIN "
                    "right now; retry when connectivity is available."
                ),
                "matches": [],
            }

        matches = []

        # 1. Search LOLBAS
        for item in self._intel_cache.get("lolbas", []):
            if binary_name in item.get("Name", "").upper():
                matches.append({
                    "source": "LOLBAS",
                    "name": item.get("Name"),
                    "description": item.get("Description"),
                    "commands": [c.get("Category") for c in item.get("Commands", [])]
                })

        # 2. Search LOLDrivers
        for item in self._intel_cache.get("loldrivers", []):
            if binary_name in item.get("Name", "").upper():
                matches.append({
                    "source": "LOLDrivers",
                    "name": item.get("Name"),
                    "description": item.get("Overview"),
                    "tags": item.get("Tags", [])
                })

        # 3. Search Bootloaders
        for item in self._intel_cache.get("bootloaders", []):
            if binary_name in item.get("Name", "").upper():
                matches.append({
                    "source": "Bootloaders",
                    "name": item.get("Name"),
                    "description": item.get("Description")
                })

        # 4. Search LOFL
        for item in self._intel_cache.get("lofl", []):
            if binary_name in item.get("Name", "").upper():
                matches.append({
                    "source": "LOFL",
                    "name": item.get("Name"),
                    "description": item.get("Description")
                })

        if not matches:
            return {
                "success": True, 
                "message": f"No direct matches found for '{binary_name}' in the live intelligence databases.",
                "matches": []
            }

        return {
            "success": True,
            "message": f"Found {len(matches)} intelligence matches for '{binary_name}'.",
            "matches": matches
        }

    def _ensure_intel_fetched(self):
        """
        Ensure the intelligence feeds are loaded.

        On a COLD cache (no feed has any data yet) we fetch SYNCHRONOUSLY so the
        very first lookup has real data — otherwise the handler would
        authoritatively report a known LOLBIN as "no match" simply because the
        async download hadn't finished (a dangerous false negative for a forensic
        tool). When the cache is merely STALE (warm but past TTL) we refresh in a
        background thread so the investigator isn't blocked.
        """
        import time
        import threading

        current_time = time.time()
        expiry_seconds = 24 * 3600  # 24 hours

        needs_fetch = False
        for key in self._intel_urls:
            last_fetch = self._intel_cache_time.get(key, 0)
            if key not in self._intel_cache or (current_time - last_fetch) > expiry_seconds:
                needs_fetch = True
                break

        if not needs_fetch:
            return

        # Cold = not a single feed currently holds data (covers first-use and the
        # case where every prior fetch failed and left empty lists).
        cold = not any(self._intel_cache.get(k) for k in self._intel_urls)

        if cold:
            self.logger.info("Cold intelligence cache — fetching synchronously before lookup...")
            self._fetch_intel_worker()
        elif self._fetching_thread is None or not self._fetching_thread.is_alive():
            self.logger.info("Starting background intelligence refresh...")
            self._fetching_thread = threading.Thread(target=self._fetch_intel_worker, daemon=True)
            self._fetching_thread.start()

    def _fetch_intel_worker(self):
        """Worker thread to fetch intel without blocking."""
        import time
        for key, url in self._intel_urls.items():
            try:
                self.logger.info(f"Fetching live intelligence: {key}")
                response = requests.get(url, timeout=15)
                if response.status_code == 200:
                    self._intel_cache[key] = response.json()
                    self._intel_cache_time[key] = time.time()
            except Exception as e:
                self.logger.error(f"Failed to fetch {key} intelligence: {e}")
                if key not in self._intel_cache:
                    self._intel_cache[key] = []
