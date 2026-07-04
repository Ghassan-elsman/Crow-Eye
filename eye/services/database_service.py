"""
ForensicDatabaseService - Read-only database access service for EYE AI Assistant.

This service provides secure, read-only access to Crow-eye's forensic databases
with multiple layers of security enforcement:
- PRAGMA query_only = ON at connection level
- SQL keyword validation to reject write operations
- Schema introspection for LLM context
- Integration with Crow-eye's DatabaseManager

"""

import difflib
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# Import Crow-eye's DatabaseManager
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from data.database_manager import DatabaseManager


class ForensicDatabaseService:
    """
    Provides read-only access to forensic databases with security enforcement.
    
    This service wraps Crow-eye's DatabaseManager and adds additional security
    layers to ensure evidence integrity during AI-assisted analysis.
    
    Security Features:
    - Read-only PRAGMA enforcement at connection level
    - SQL keyword validation (rejects DROP, UPDATE, DELETE, INSERT, ALTER, CREATE)
    - Connection-level read-only file permissions
    - Comprehensive error handling and logging
    
    Attributes:
        case_directory: Path to the case directory containing databases
        db_manager: Instance of Crow-eye's DatabaseManager
        logger: Logger instance for audit trail
    """
    
    # Forbidden SQL keywords that would modify data or perform unsafe operations.
    # NOTE: 'REPLACE' is deliberately NOT here — it is a common read-only scalar
    # function (e.g. SELECT REPLACE(path,'\','/')). Its dangerous statement form
    # (REPLACE INTO) is blocked separately below, and the connection is opened
    # read-only (mode=ro + PRAGMA query_only) which prevents writes regardless.
    FORBIDDEN_KEYWORDS = [
        'DROP', 'UPDATE', 'DELETE', 'INSERT', 'ALTER', 'CREATE',
        'TRUNCATE', 'ATTACH', 'DETACH', 'GRANT', 'REVOKE',
        'LOAD_EXTENSION', 'EXECUTE', 'VACUUM', 'REINDEX'
    ]
    # Statement-position write patterns that aren't single keywords.
    FORBIDDEN_PATTERNS = [
        r'\bREPLACE\s+INTO\b',   # REPLACE INTO ... (write); REPLACE(...) is allowed
    ]
    
    def __init__(self, case_directory: Union[str, Path]):
        """
        Initialize the ForensicDatabaseService.
        
        Args:
            case_directory: Path to the case directory containing artifact databases
        """
        self.case_directory = Path(case_directory)
        self.db_manager = DatabaseManager(case_directory)
        self.logger = logging.getLogger(self.__class__.__name__)
        # Cache of successfully discovered schemas, keyed by (db, table_or_None),
        # so a learned schema is never re-discovered (and can serve as a fallback
        # if a later live fetch fails).
        self._schema_cache: Dict[tuple, Dict[str, Any]] = {}

        # Validate case directory
        if not self.case_directory.exists():
            self.logger.warning(f"Case directory does not exist: {self.case_directory}")
    
    def get_connection(self, database_name: str) -> Optional[sqlite3.Connection]:
        """
        Get a read-only connection to a forensic database.
        
        This method enforces read-only access at multiple layers:
        1. Opens database with read-only URI mode
        2. Sets PRAGMA query_only = ON
        3. Returns connection for direct use if needed
        
        Args:
            database_name: Name of the database file (e.g., 'registry_data.db')
            
        Returns:
            Read-only SQLite connection, or None if connection fails
            
        """
        try:
            return self._open_ro(database_name)
        except Exception as e:
            self.logger.error(f"Failed to open read-only connection to {database_name}: {e}")
            return None

    # ------------------------------------------------------------------
    # Thread-safe read-only access
    #
    # The Eye runs every query in a fresh QueryWorker QThread, so it must NOT
    # reuse the host db_manager's cached connections (created on another thread)
    # — that raises "SQLite objects created in a thread can only be used in that
    # same thread". Instead we open a short-lived read-only connection in the
    # CALLING thread for each operation. db_manager is used only to resolve the
    # file path. check_same_thread=False is belt-and-suspenders (queries are
    # serialized per turn anyway).
    # ------------------------------------------------------------------
    def _resolve_db_path(self, database_name: str) -> Optional[Path]:
        """Resolve a database name to its on-disk file path."""
        try:
            p = self.case_directory / database_name
            if p.exists():
                return p
        except Exception:
            pass
        try:
            resolved = getattr(self.db_manager, "resolved_paths", {}) or {}
            rp = resolved.get(database_name)
            if rp and Path(rp).exists():
                return Path(rp)
        except Exception:
            pass
        try:
            for d in self.discover_databases():
                if d.get("name") == database_name and d.get("path") and Path(d["path"]).exists():
                    return Path(d["path"])
        except Exception:
            pass
        return None

    def _open_ro(self, database_name: str) -> sqlite3.Connection:
        """Open a fresh read-only SQLite connection in the current thread."""
        path = self._resolve_db_path(database_name)
        if path is None:
            raise FileNotFoundError(f"Database not found: {database_name}")
        conn = sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro", uri=True,
            check_same_thread=False, timeout=30.0,
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA query_only = ON")
        except sqlite3.Error:
            pass
        return conn

    def _get_tables_safe(self, database_name: str) -> List[str]:
        """List user tables via a per-call read-only connection (thread-safe)."""
        try:
            conn = self._open_ro(database_name)
        except Exception:
            return []
        try:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            return [r[0] for r in cur.fetchall()]
        except Exception:
            return []
        finally:
            conn.close()

    def _get_columns_safe(self, database_name: str, table: str) -> List[str]:
        """List a table's columns via a per-call read-only connection."""
        try:
            conn = self._open_ro(database_name)
        except Exception:
            return []
        try:
            cur = conn.execute(f'PRAGMA table_info("{table}")')
            return [r[1] for r in cur.fetchall()]
        except Exception:
            return []
        finally:
            conn.close()

    def _all_database_tables(self) -> Dict[str, List[str]]:
        """Map of ``{database_name: [tables]}`` for EVERY existing case database
        (known artifacts + correlation feathers), so a missing table/column can be
        searched across all databases — not just the one the model named."""
        out: Dict[str, List[str]] = {}
        try:
            for d in self.discover_databases():
                name = d.get("name")
                if not name or not d.get("exists", True):
                    continue
                tables = d.get("tables") or self._get_tables_safe(name)
                if tables:
                    out[name] = tables
        except Exception as e:
            self.logger.debug(f"cross-database table map skipped: {e}")
        return out

    def execute_query(
        self,
        database_name: str,
        sql_query: str,
        params: Tuple = (),
        timeout: Optional[float] = 30.0,
        _is_heal_retry: bool = False
    ) -> Dict[str, Any]:
        """
        Execute a SQL query with read-only validation.
        
        This method validates that the query is read-only before execution:
        1. Checks for forbidden keywords (DROP, UPDATE, DELETE, etc.)
        2. Executes query through DatabaseManager
        3. Returns results with metadata
        
        Args:
            database_name: Name of the database to query
            sql_query: SQL SELECT query to execute
            params: Query parameters for parameterized queries
            timeout: Query timeout in seconds (default 30.0)
            
        Returns:
            Dictionary containing:
                - success: bool indicating if query succeeded
                - data: List of result rows (as dictionaries)
                - row_count: Number of rows returned
                - error: Error message if query failed
                
        """
        # Validate query is read-only
        if not self._is_readonly_query(sql_query):
            error_msg = (
                f"Query rejected: Contains forbidden keywords. "
                f"Only SELECT queries are allowed for evidence integrity. "
                f"Query: {sql_query[:100]}..."
            )
            self.logger.warning(error_msg)
            return {
                "success": False,
                "data": [],
                "row_count": 0,
                "error": error_msg
            }
        
        try:
            conn = self._open_ro(database_name)
        except Exception as e:
            # ---- Database-name self-heal: the model named a database that doesn't
            # resolve (wrong/misspelled, e.g. "srum.db" vs "srum_data.db"). Auto-retry
            # against an unambiguous close match, or hand back the real database list so
            # the model corrects itself — mirroring the table/column self-heal. ----
            if not _is_heal_retry:
                healed = self._self_heal_missing_database(
                    database_name, sql_query, params, timeout
                )
                if healed is not None:
                    return healed
            return {
                "success": False,
                "data": [],
                "row_count": 0,
                "error": f"Failed to connect to database: {database_name} ({e})",
            }

        try:
            cur = conn.execute(sql_query, params)
            rows = [dict(r) for r in cur.fetchall()]
            columns = [d[0] for d in cur.description] if cur.description else []

            self.logger.info(
                f"Query executed successfully on {database_name}: "
                f"{len(rows)} rows returned"
            )

            return {
                "success": True,
                "data": rows,
                "row_count": len(rows),
                "columns": columns,
                "error": None,
                "database_name": database_name,
                "sql_query": sql_query,
            }

        except Exception as e:
            error_msg = str(e)
            low = error_msg.lower()

            # ---- Schema self-heal: discover the real schema and either safely
            # auto-retry an unambiguous near-match, or hand the model the tables/
            # columns it needs so it corrects itself instead of looping. ----
            if "no such table" in low and not _is_heal_retry:
                healed = self._self_heal_missing_table(
                    database_name, sql_query, error_msg, params, timeout
                )
                if healed is not None:
                    return healed
            elif "no such column" in low:
                self.logger.warning(f"Schema mismatch on {database_name}: {error_msg}")
                return self._self_heal_missing_column(
                    database_name, sql_query, error_msg, params, timeout, _is_heal_retry)

            self.logger.error(f"Error executing query on {database_name}: {e}")
            return {
                "success": False,
                "data": [],
                "row_count": 0,
                "error": f"Database Error: {error_msg}"
            }
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # Sentinel marker name extracted from common SQLite errors, e.g.
    # "no such table: security_event" -> "security_event".
    @staticmethod
    def _identifier_after(error_msg: str, marker: str) -> str:
        low = error_msg.lower()
        idx = low.find(marker.lower())
        if idx == -1:
            return ""
        tail = error_msg[idx + len(marker):].strip()
        # The bad identifier is the first token (may be schema.table).
        token = tail.split()[0] if tail else ""
        return token.strip().strip('"').strip("'").split(".")[-1]

    @staticmethod
    def _tables_in_query(sql_query: str) -> List[str]:
        """Best-effort extraction of table names from FROM / JOIN clauses."""
        names = re.findall(
            r'(?:FROM|JOIN)\s+["\'`]?([A-Za-z_][A-Za-z0-9_]*)["\'`]?',
            sql_query or "",
            flags=re.IGNORECASE,
        )
        seen, out = set(), []
        for n in names:
            if n.lower() not in seen:
                seen.add(n.lower())
                out.append(n)
        return out

    @staticmethod
    def _norm_db_name(s: str) -> str:
        """Normalize a database name for fuzzy matching: lowercase, drop a trailing
        ``.db``/``.sqlite`` extension (so 'srum.db' compares to 'srum_data.db')."""
        s = (s or "").strip().lower()
        for ext in (".sqlite3", ".sqlite", ".db3", ".db"):
            if s.endswith(ext):
                return s[: -len(ext)]
        return s

    def _available_db_names(self) -> List[str]:
        """Names of the case databases that actually exist on disk."""
        try:
            return [d.get("name") for d in self.discover_databases()
                    if d.get("name") and d.get("exists")]
        except Exception:
            return []

    def _self_heal_missing_database(
        self, database_name, sql_query, params, timeout
    ) -> Optional[Dict[str, Any]]:
        """Auto-recover from a database that does not resolve. Returns a result dict
        (auto-retried rows against the closest DB, or an enriched error with the real
        database list), or None to fall through to the bare connect error."""
        available = self._available_db_names()
        bad = database_name or ""
        nbad = self._norm_db_name(bad)

        # Guarded transparent auto-retry: exactly one strong match. A DB filename
        # often differs from what the model guesses by an extension or a '_data'
        # suffix, so match on the normalized base via prefix/containment OR a high
        # difflib ratio — never silently swap when it's ambiguous.
        if nbad and available:
            strong = []
            for name in available:
                nn = self._norm_db_name(name)
                if (nn == nbad or nn.startswith(nbad) or nbad.startswith(nn)
                        or difflib.SequenceMatcher(None, nbad, nn).ratio() >= 0.8):
                    strong.append(name)
            if len(strong) == 1 and strong[0] != bad:
                used = strong[0]
                self.logger.info(
                    f"Self-heal: database '{bad}' not found; retrying against '{used}'."
                )
                retry = self.execute_query(used, sql_query, params, timeout, _is_heal_retry=True)
                if retry.get("success"):
                    retry["self_healed"] = True
                    retry["note"] = (
                        f"Database '{bad}' was not found; automatically used the closest "
                        f"match '{used}'."
                    )
                    return retry

        suggestions = difflib.get_close_matches(bad, available, n=3, cutoff=0.3) if bad else []
        self.logger.warning(
            f"Database '{bad}' not found; self-heal among {len(available)} databases."
        )
        return {
            "success": False,
            "data": [],
            "row_count": 0,
            "error": f"Database not found: {bad}",
            "available_databases": available,
            "did_you_mean": suggestions,
            "hint": (
                f"Database '{bad}' does not exist in this case. Re-issue query_database using one "
                f"of available_databases (see did_you_mean), or call list_case_files to browse the "
                f"artifacts. Do not repeat the same failing query."
            ),
        }

    def _self_heal_missing_table(
        self, database_name, sql_query, error_msg, params, timeout
    ) -> Optional[Dict[str, Any]]:
        """Auto-discover tables for a 'no such table' error. Returns a result dict
        (auto-retried rows or an enriched error), or None to fall through."""
        bad = self._identifier_after(error_msg, "no such table:")
        available = self._get_tables_safe(database_name)
        self.logger.warning(
            f"Table '{bad}' missing in {database_name}; self-heal among {len(available)} tables."
        )

        # Guarded transparent auto-retry: exactly one strong match (e.g.
        # 'security_event' -> 'security_events'). Never silently swaps tables.
        if bad and available:
            scored = sorted(
                ((difflib.SequenceMatcher(None, bad.lower(), t.lower()).ratio(), t)
                 for t in available),
                reverse=True,
            )
            strong = [t for r, t in scored if r >= 0.85]
            if len(strong) == 1 and strong[0] != bad:
                used = strong[0]
                healed_sql = re.sub(
                    rf'\b{re.escape(bad)}\b', f'"{used}"', sql_query
                )
                if healed_sql != sql_query:
                    self.logger.info(
                        f"Self-heal: retrying query with table '{used}' (was '{bad}')."
                    )
                    retry = self.execute_query(
                        database_name, healed_sql, params, timeout, _is_heal_retry=True
                    )
                    if retry.get("success"):
                        retry["self_healed"] = True
                        retry["note"] = (
                            f"Table '{bad}' was not found; automatically used the closest "
                            f"match '{used}'."
                        )
                        return retry

        # ---- Cross-database search: the table may live in a DIFFERENT database.
        # Walk every database and collect where the table actually is, then auto-retry
        # against the right one when unambiguous. ----
        found_in: Dict[str, List[str]] = {}
        exact_hits, fuzzy_hits = [], []  # (db, table) / (db, table, ratio)
        if bad:
            for db, tbls in self._all_database_tables().items():
                if db == database_name:
                    continue
                for t in tbls:
                    if t.lower() == bad.lower():
                        exact_hits.append((db, t))
                        found_in.setdefault(db, []).append(t)
                    elif difflib.SequenceMatcher(None, bad.lower(), t.lower()).ratio() >= 0.85:
                        fuzzy_hits.append((db, t))
                        found_in.setdefault(db, []).append(t)

            target = None
            if len(exact_hits) == 1:
                target = exact_hits[0]
            elif not exact_hits and len({(db, t) for db, t in fuzzy_hits}) == 1:
                target = fuzzy_hits[0]
            if target:
                tdb, ttbl = target
                healed_sql = (sql_query if ttbl.lower() == bad.lower()
                              else re.sub(rf'\b{re.escape(bad)}\b', f'"{ttbl}"', sql_query))
                self.logger.info(
                    f"Self-heal: table '{bad}' not in {database_name}; retrying in database '{tdb}'.")
                retry = self.execute_query(tdb, healed_sql, params, timeout, _is_heal_retry=True)
                if retry.get("success"):
                    retry["self_healed"] = True
                    retry["note"] = (
                        f"Table '{bad}' was not in '{database_name}'; found it in database '{tdb}'"
                        + (f" as '{ttbl}'" if ttbl.lower() != bad.lower() else "")
                        + " and queried there.")
                    return retry

        suggestions = difflib.get_close_matches(bad, available, n=3, cutoff=0.5) if bad else []
        # Columns of the top suggestion(s) so the model can rewrite in one step.
        suggested_schema = {}
        for t in suggestions[:2]:
            cols = self._get_columns_safe(database_name, t)
            if cols:
                suggested_schema[t] = cols
        _where = (f" It WAS found in: {found_in}. Re-issue with that database_name."
                  if found_in else "")
        return {
            "success": False,
            "data": [],
            "row_count": 0,
            "error": f"Database Error: {error_msg}",
            "available_tables": available,
            "did_you_mean": suggestions,
            "suggested_schema": suggested_schema,
            "found_in": found_in,
            "hint": (
                f"Table '{bad}' does not exist in {database_name}.{_where} "
                f"Otherwise re-issue query_database using one of available_tables "
                f"(see did_you_mean / suggested_schema). Do not repeat the same failing query."
            ),
        }

    def _self_heal_missing_column(self, database_name, sql_query, error_msg,
                                  params=(), timeout=30.0, _is_heal_retry=False) -> Dict[str, Any]:
        """Recover from a 'no such column' error. Discovers the real columns of the
        referenced table(s) in the named DB AND walks every OTHER database that holds
        the same table to find where the column actually lives — auto-retrying against
        that database when unambiguous."""
        bad = self._identifier_after(error_msg, "no such column:")
        referenced = self._tables_in_query(sql_query)
        if not referenced:
            referenced = self._get_tables_safe(database_name)

        schema, all_cols = {}, []          # current-DB referenced-table columns
        column_found_in: Dict[str, Dict[str, List[str]]] = {}  # {db: {table: [cols]}}
        auto = None                        # (db) where a referenced table has the exact column
        db_tables = self._all_database_tables()
        for t in referenced:
            for db, tbls in db_tables.items():
                match = next((x for x in tbls if x.lower() == t.lower()), None)
                if not match:
                    continue
                cols = self._get_columns_safe(db, match)
                if not cols:
                    continue
                if db == database_name:
                    schema[match] = cols
                    all_cols.extend(cols)
                exact = [c for c in cols if c.lower() == bad.lower()]
                close = difflib.get_close_matches(bad, cols, n=2, cutoff=0.6)
                if exact or close:
                    column_found_in.setdefault(db, {})[match] = (
                        exact + [c for c in close if c not in exact]) or cols[:8]
                if exact and db != database_name and auto is None:
                    auto = db

        # Auto-retry: the model used the right table but the WRONG database — the
        # column exists in that same table in another database. Switch and retry.
        if auto and not _is_heal_retry:
            self.logger.info(
                f"Self-heal: column '{bad}' not in {database_name}; retrying in database '{auto}'.")
            retry = self.execute_query(auto, sql_query, params, timeout, _is_heal_retry=True)
            if retry.get("success"):
                retry["self_healed"] = True
                retry["note"] = (
                    f"Column '{bad}' was not in '{database_name}'; the referenced table with that "
                    f"column is in database '{auto}' — queried there.")
                return retry

        if not all_cols:  # fallback: at least the named DB's referenced tables' columns
            for t in referenced:
                cols = self._get_columns_safe(database_name, t)
                if cols:
                    schema[t] = cols
                    all_cols.extend(cols)
        suggestions = difflib.get_close_matches(bad, all_cols, n=3, cutoff=0.5) if bad else []
        _where = (f" The column was discovered in: {column_found_in}."
                  if column_found_in else "")
        return {
            "success": False,
            "data": [],
            "row_count": 0,
            "error": f"Database Error: {error_msg}",
            "schema": schema,
            "column_found_in": column_found_in,
            "did_you_mean": suggestions,
            "hint": (
                f"Column '{bad}' does not exist in {database_name}.{_where} Use a real column from "
                f"schema (see did_you_mean / column_found_in) and the right database_name, then "
                f"retry. Do not repeat the same failing query."
            ),
        }
    
    def get_schema(
        self,
        database_name: str,
        table_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get schema information for database introspection.
        
        This method provides schema information to help the LLM understand
        available data structures and generate valid SQL queries.
        
        Args:
            database_name: Name of the database
            table_name: Optional specific table name. If None, returns all tables.
            
        Returns:
            Dictionary containing:
                - success: bool indicating if schema retrieval succeeded
                - database: Database name
                - tables: List of table names (if table_name is None)
                - schema: Dict mapping table names to column lists
                - sample_data: Dict with sample rows for each table (first 3 rows)
                - row_counts: Dict with row counts for each table
                - error: Error message if retrieval failed
                
        """
        # Normalize "all tables" sentinels the model commonly invents (the tool
        # uses get_schema to *discover* tables, so models pass "_all_"/"*"/etc.
        # to mean "list everything"). Treat those as "no specific table".
        if table_name is not None and str(table_name).strip().lower() in (
            "", "_all_", "__all__", "all", "*", "%", "none", "null"
        ):
            table_name = None

        cache_key = (database_name, table_name)
        try:
            conn = self._open_ro(database_name)
        except Exception as e:
            # Live fetch failed — serve a cached schema if we learned it earlier
            # (avoids re-discovering / looping on a transient error).
            cached = self._schema_cache.get(cache_key) or self._schema_cache.get((database_name, None))
            if cached:
                served = dict(cached)
                served["from_cache"] = True
                return served
            self.logger.error(f"Error getting schema for {database_name}: {e}")
            return {"success": False, "database": database_name,
                    "error": f"Schema retrieval failed: {e}"}

        try:
            all_tables = [
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            ]

            if table_name:
                if table_name not in all_tables:
                    return {
                        "success": False,
                        "database": database_name,
                        "error": f"Table '{table_name}' not found in {database_name}.",
                        "available_tables": all_tables,
                        "did_you_mean": difflib.get_close_matches(
                            table_name, all_tables, n=3, cutoff=0.5
                        ),
                    }
                tables = [table_name]
            else:
                tables = all_tables

            if not tables:
                return {"success": False, "database": database_name,
                        "error": f"No tables found in database: {database_name}"}

            schema, sample_data, row_counts = {}, {}, {}
            for table in tables:
                schema[table] = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
                try:
                    row_counts[table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                except Exception as e:
                    self.logger.warning(f"Could not get row count for {table}: {e}")
                    row_counts[table] = 0
                try:
                    cur = conn.execute(f'SELECT * FROM "{table}" LIMIT 3')
                    sample_data[table] = [dict(r) for r in cur.fetchall()]
                except Exception as e:
                    self.logger.warning(f"Could not get sample data for {table}: {e}")
                    sample_data[table] = []

            self.logger.info(f"Schema retrieved for {database_name}: {len(tables)} tables")
            result = {
                "success": True,
                "database": database_name,
                "tables": all_tables if not table_name else None,
                "all_tables": all_tables,  # always present (multi-table awareness)
                "schema": schema,
                "sample_data": sample_data,
                "row_counts": row_counts,
                "error": None,
            }
            self._schema_cache[cache_key] = result
            return result

        except Exception as e:
            error_msg = f"Schema retrieval failed: {str(e)}"
            self.logger.error(f"Error getting schema for {database_name}: {e}")
            cached = self._schema_cache.get(cache_key) or self._schema_cache.get((database_name, None))
            if cached:
                served = dict(cached)
                served["from_cache"] = True
                return served
            return {"success": False, "database": database_name, "error": error_msg}
        finally:
            try:
                conn.close()
            except Exception:
                pass
    
    def _is_readonly_query(self, sql: str) -> bool:
        """
        Validate that SQL query is read-only.
        
        Checks for forbidden keywords that would modify the database.
        Uses case-insensitive regex matching to catch variations.
        Removes string literals and comments before checking to avoid false positives/bypasses.
        
        Args:
            sql: SQL query string to validate
            
        Returns:
            True if query is read-only (safe), False if it contains forbidden keywords
            
        """
        # 1. Remove SQL comments (both -- and /* */) to prevent bypasses
        # Remove multi-line comments
        sql_clean = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
        # Remove single-line comments
        sql_clean = re.sub(r'--.*$', '', sql_clean, flags=re.MULTILINE)
        
        # 2. Remove string literals to avoid false positives
        # (e.g., "WHERE name LIKE '%UPDATE%'" should not trigger)
        # Remove single-quoted strings
        sql_without_strings = re.sub(r"'[^']*'", "''", sql_clean)
        # Remove double-quoted strings
        sql_without_strings = re.sub(r'"[^"]*"', '""', sql_without_strings)
        
        # Normalize SQL: convert to uppercase and remove extra whitespace
        normalized_sql = ' '.join(sql_without_strings.upper().split())
        
        # Check for forbidden keywords using word boundaries
        for keyword in self.FORBIDDEN_KEYWORDS:
            # Use word boundary regex to avoid false positives
            # (e.g., "DESCRIPTION" should not match "DELETE")
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, normalized_sql):
                self.logger.warning(
                    f"Forbidden keyword detected: {keyword} in query: {sql[:100]}..."
                )
                return False

        # Check statement-position write patterns (e.g. REPLACE INTO) that must
        # NOT be tripped by the same-named read-only scalar function.
        for pat in self.FORBIDDEN_PATTERNS:
            if re.search(pat, normalized_sql):
                self.logger.warning(
                    f"Forbidden write pattern detected ({pat}) in query: {sql[:100]}..."
                )
                return False

        return True
    
    def discover_databases(self) -> List[Dict[str, Any]]:
        """
        Discover all available forensic databases in the case directory.
        
        Returns:
            List of dictionaries containing database information:
                - name: Database filename
                - path: Full path to database
                - category: Artifact category
                - display_name: Human-readable name
                - exists: Whether file exists
                - accessible: Whether database can be opened
                - tables: List of table names (if accessible)
                - error: Error message (if not accessible)
        """
        db_infos = self.db_manager.discover_databases()

        # Convert DatabaseInfo objects to dictionaries
        result = []
        for db_info in db_infos:
            result.append({
                "name": db_info.name,
                "path": str(db_info.path),
                "category": db_info.category,
                "display_name": db_info.display_name,
                "exists": db_info.exists,
                "accessible": db_info.accessible,
                "tables": db_info.tables if db_info.tables else [],
                "error": db_info.error
            })

        # Also surface the Correlation Engine's normalized "feather" databases (which
        # may be imported from external tools) so the Eye can query them too. They are
        # arbitrary SQLite files NOT in the known-artifact set, so the manager's
        # discovery skips them — we add them by walking the feathers directory.
        known = {r.get("name") for r in result}
        for feather in self._discover_feather_databases():
            if feather.get("name") not in known:
                result.append(feather)
                known.add(feather.get("name"))

        return result

    def _tables_at_path(self, db_path: Path) -> List[str]:
        """List user tables of a SQLite file by absolute path (read-only)."""
        try:
            conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=10.0)
        except Exception:
            return []
        try:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            return [r[0] for r in cur.fetchall()]
        except Exception:
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _discover_feather_databases(self) -> List[Dict[str, Any]]:
        """Walk ``<case>/Correlation/feathers/*.db`` (normalized correlation-engine
        databases, possibly imported from external tools) and return DatabaseInfo-shaped
        dicts with their real tables, so they appear in the schema manifest and are
        queryable/resolvable. Returns [] when the directory is absent."""
        out: List[Dict[str, Any]] = []
        try:
            feather_dir = self.case_directory / "Correlation" / "feathers"
            if not feather_dir.is_dir():
                return out
            for db in sorted(feather_dir.glob("*.db")):
                if not db.is_file():
                    continue
                tables = self._tables_at_path(db)
                out.append({
                    "name": db.name,
                    "path": str(db),
                    "category": "Correlation Feather",
                    "display_name": f"Feather: {db.stem}",
                    "exists": True,
                    "accessible": bool(tables),
                    "tables": tables,
                    "error": None if tables else "no readable tables",
                })
        except Exception as e:
            self.logger.debug(f"feather database discovery skipped: {e}")
        return out
    
    def close_all(self):
        """Close all open database connections."""
        self.db_manager.close_all()
        self.logger.debug("All database connections closed")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close all connections."""
        self.close_all()
