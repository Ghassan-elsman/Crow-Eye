"""
Core IntelligenceEngine class for the Dynamic Linking Intelligence Engine.
"""

import logging
import os
import sqlite3
import time
from typing import Dict, List, Optional, Tuple

from dynamic_mapping.core.base import BaseComponent
from dynamic_mapping.core.database import DatabaseManager
from dynamic_mapping.core.run_stats import (DUPLICATE, INSERTED, MERGED, REJECTED, LinkRun,
                                            RuleResult, log_rule, log_run)
from dynamic_mapping.rules.base import CustomRule


class IntelligenceEngine(BaseComponent):
    """
    Core orchestrator for intelligence gathering, storage, and retrieval operations.
    
    This class manages the Crow_Intelligence.db database and provides methods for:
    - Intelligence gathering from forensic artifacts
    - IOC file ingestion (CSV/JSON formats)
    - Mapping CRUD operations
    - Custom rule registration and execution
    """
    
    def __init__(self, case_directory: str):
        """
        Initialize intelligence engine for a case.

        Args:
            case_directory: Path to active case directory
        """
        super().__init__("IntelligenceEngine")
        self.logger = logging.getLogger(__name__)
        self.case_directory = case_directory
        self.intelligence_db_path = os.path.join(case_directory, "Crow_Intelligence.db")
        self._db_manager: Optional[DatabaseManager] = None
        self._is_initialized = False
        self._custom_rules_manager = None  # Lazy-initialized CustomRulesManager
        # The latest LinkRun (run_stats): what each rule read and added.
        self.last_run: Optional[LinkRun] = None
    
    def ensure_db(self) -> bool:
        """
        Ensure intelligence database exists and is properly initialized.
        
        Returns:
            True if database is ready, False otherwise
        """
        if self._is_initialized and self._db_manager and self._db_manager.connection:
            return True

        try:
            # Create case directory if it doesn't exist
            if not os.path.exists(self.case_directory):
                os.makedirs(self.case_directory, exist_ok=True)
            
            # Initialize DatabaseManager
            self._db_manager = DatabaseManager(self.case_directory)
            db_ready = self._db_manager.ensure_db()
            
            if db_ready:
                self._is_initialized = True
                # Automatically populate Well-Known SIDs so they are always available
                # We don't need a UI button for these; they are Windows standards.
                # Its own "auto" run, so it never shows up as the investigator's.
                self.gather_intelligence(["Well_Known_SIDs"], custom_rules=False,
                                         run=LinkRun(kind="auto"))
                
            return db_ready
            
        except Exception:
            self._is_initialized = False
            return False
    
    def close(self) -> bool:
        """
        Close database connection.
        
        Returns:
            True if connection closed successfully, False otherwise
        """
        if self._db_manager:
            return self._db_manager.close()
        return True
    
    def gather_intelligence(self, rules: List[str], custom_rules: bool = True,
                            run: Optional[LinkRun] = None) -> Dict[str, int]:
        """
        Execute intelligence gathering using specified default rules and (optionally)
        every enabled CustomRule stored in the CustomRules table.

        Args:
            rules: List of default-rule names to execute (e.g., ["SID_to_Username",
                "MAC_to_NetworkName"]). Pass an empty list to skip default rules.
            custom_rules: If True (default), also runs every enabled CustomRule
                stored in CustomRules against the same artifacts directory.
            run: The LinkRun to add each rule's RuleResult to (the statistics
                dialog reads it). A run of its own is used when none is given;
                either way it is left in ``self.last_run``.

        Returns:
            Dictionary mapping rule names to the links each one ADDED (new
            values plus new keys on known values). It used to count every
            mapping accepted, so a value already in the database counted again
            on every run.
        """
        results = {}
        if run is None:
            run = LinkRun(kind="gather")
        self.last_run = run

        # Import here to avoid circular imports
        from dynamic_mapping.rules.default_rules import DEFAULT_RULES

        # Verify database availability
        if not self.ensure_db():
            for rule_name in rules:
                res = run.add(RuleResult(rule_name, "default", status="failed",
                                         reason="intelligence database unavailable"))
                log_rule(res)
            return {rule: 0 for rule in rules}

        for rule_name in rules:
            if rule_name not in DEFAULT_RULES:
                res = run.add(RuleResult(rule_name, "default", status="skipped",
                                         reason="no such rule"))
                log_rule(res)
                results[rule_name] = 0
                continue

            rule = DEFAULT_RULES[rule_name]
            internal = getattr(rule, 'target_db_name', None) is None
            res = RuleResult(rule_name, "internal" if internal else "default",
                             category=getattr(rule, 'category', '') or '',
                             description=getattr(rule, 'description', '') or '',
                             **rule.source_info())
            run.add(res)
            t0 = time.perf_counter()
            try:
                # Support for internal rules that don't require an external database
                # These can run even without an artifacts directory
                if internal:
                    extracted = rule.extract_mappings([])
                    res.rows_read = len(extracted)
                    self._store_mappings(extracted, res)
                else:
                    # Determine artifacts directory for database-backed rules
                    artifacts_dir = self._find_artifacts_directory()
                    target_db_path = rule.get_target_db(artifacts_dir) if artifacts_dir else None
                    conn = self._db_manager.connection
                    if not artifacts_dir:
                        res.status, res.reason = "skipped", "no artifacts directory in this case"
                    elif not target_db_path or not os.path.exists(target_db_path):
                        res.status = "skipped"
                        res.reason = "%s not parsed in this case" % rule.target_db_name
                    elif not conn:
                        res.status, res.reason = "failed", "intelligence database unavailable"
                    else:
                        self._run_default_rule(rule, target_db_path, conn, res)
            except Exception as e:
                res.status = "failed"
                res.reason = "%s: %s" % (type(e).__name__, e)
            res.duration_ms = int((time.perf_counter() - t0) * 1000)
            results[rule_name] = res.new_links
            self._log_gather_history(res, run)
            log_rule(res)

        # ---- Custom rules ------------------------------------------------
        # Every enabled CustomRule stored in CustomRules is executed against
        # the same artifacts directory. Failures are isolated per rule so a
        # bad custom rule cannot kill the whole gather.
        if custom_rules:
            artifacts_dir = self._find_artifacts_directory()
            manager = self._get_custom_rules_manager()
            stored_rules = manager.list_rules() if manager else []
            for rule in stored_rules:
                res = run.add(RuleResult(rule.name, "custom", category=rule.category or "",
                                         description=rule.description or "",
                                         **rule.source_info()))
                t0 = time.perf_counter()
                try:
                    missing = rule.missing_source(artifacts_dir)
                    if missing:
                        res.status, res.reason = "skipped", missing
                    else:
                        extracted = rule.execute(artifacts_dir, raise_errors=True)
                        res.rows_read = len(extracted)
                        self._store_mappings(extracted, res)
                except Exception as e:
                    res.status = "failed"
                    res.reason = "%s: %s" % (type(e).__name__, e)
                res.duration_ms = int((time.perf_counter() - t0) * 1000)
                results[rule.name] = res.new_links
                self._log_gather_history(res, run)
                log_rule(res)

        return results

    def _run_default_rule(self, rule, target_db_path: str, conn, res: RuleResult) -> None:
        """ATTACH the rule's database, run its query, store what it finds."""
        cursor = conn.cursor()
        # Check if TargetDB is already attached to prevent conflicts
        cursor.execute("PRAGMA database_list")
        if 'TargetDB' in [row[1] for row in cursor.fetchall()]:
            cursor.execute("DETACH DATABASE TargetDB")
        cursor.execute("ATTACH DATABASE ? AS TargetDB", (str(target_db_path),))
        try:
            try:
                cursor.execute(rule.get_query())
            except sqlite3.OperationalError as e:
                # The database is there but the parser did not create the
                # table (or the column): the artifact was not on the evidence.
                if "no such table" in str(e) or "no such column" in str(e):
                    res.status, res.reason = "skipped", str(e)
                    return
                raise
            rows = cursor.fetchall()
            res.rows_read = len(rows)
            extracted = rule.extract_mappings(rows)
            # Rows the rule itself dropped (an empty name, a placeholder) are
            # rejected too, so every row read is accounted for.
            res.rejected += max(0, len(rows) - len(extracted))
            self._store_mappings(extracted, res)
        finally:
            cursor.execute("DETACH DATABASE TargetDB")

    def finish_run(self, run: Optional[LinkRun] = None) -> Optional[LinkRun]:
        """Close a run: count the database and write its summary line."""
        run = run or getattr(self, "last_run", None)
        if run is None:
            return None
        run.finished = time.time()
        try:
            conn = self._db_manager.connection if self._db_manager else None
            if conn:
                run.mappings_total = conn.execute("SELECT COUNT(*) FROM Mapping").fetchone()[0]
        except Exception:
            pass
        log_run(run)
        return run

    def load_run(self, run_id: Optional[str] = None) -> Optional[LinkRun]:
        """A past run rebuilt from GatherHistory (the latest when run_id is None)."""
        if not self.ensure_db():
            return None
        conn = self._db_manager.connection
        try:
            if run_id is None:
                row = conn.execute("SELECT run_id FROM GatherHistory WHERE run_id IS NOT NULL "
                                   "AND COALESCE(run_kind, '') != 'auto' "
                                   "ORDER BY id DESC LIMIT 1").fetchone()
                if not row:
                    return None
                run_id = row[0]
            rows = conn.execute("SELECT * FROM GatherHistory WHERE run_id = ? ORDER BY id",
                                (run_id,)).fetchall()
        except sqlite3.Error:
            return None
        if not rows:
            return None
        run = LinkRun(run_id=run_id, kind=rows[0]["run_kind"] or "gather")
        for r in rows:
            run.add(RuleResult(
                r["rule_name"], r["rule_type"], category=r["category"] or "",
                source_db=r["source_db"] or "", source_table=r["source_table"] or "",
                value_column=r["value_column"] or "", key_column=r["key_column"] or "",
                status={"success": "ok"}.get(r["status"], r["status"]),
                reason=r["error_message"] or "", rows_read=r["rows_read"] or 0,
                inserted=r["inserted"] or 0, merged=r["merged"] or 0,
                duplicate=r["duplicate"] or 0, rejected=r["rejected"] or 0,
                duration_ms=r["execution_time_ms"] or 0))
        try:
            run.mappings_total = conn.execute("SELECT COUNT(*) FROM Mapping").fetchone()[0]
        except sqlite3.Error:
            pass
        # When it ran, not when it was rebuilt: executed_at is SQLite's
        # CURRENT_TIMESTAMP (UTC). Without this a reopened run said "now".
        import calendar
        stamps = []
        for r in rows:
            try:
                stamps.append(calendar.timegm(time.strptime(str(r["executed_at"])[:19],
                                                            "%Y-%m-%d %H:%M:%S")))
            except (TypeError, ValueError, IndexError, KeyError):
                continue
        if stamps:
            run.started = min(stamps)
            run.finished = max(stamps) + sum((r.duration_ms for r in run.rules[-1:]), 0) / 1000.0
        else:
            run.finished = run.started
        return run

    def _get_custom_rules_manager(self):
        """Lazily build (and cache) a CustomRulesManager tied to this engine's intel DB."""
        if self._custom_rules_manager is None:
            from dynamic_mapping.rules.custom_rules import CustomRulesManager
            self._custom_rules_manager = CustomRulesManager(self.intelligence_db_path)
        return self._custom_rules_manager
    
    def ingest_ioc_file(self, file_path: str, ioc_type: str = "auto") -> int:
        """
        Ingest IOC file and create intelligence mappings.

        Args:
            file_path: Path to IOC file (CSV or JSON)
            ioc_type: Type of IOC (e.g. "hash", "ip", "domain") used as the
                Mapping.source value so the Live Intelligence Registry can
                show what kind of indicator each row came from. Pass "auto"
                (the default) to keep the generic "IOC_File" source.

        Returns:
            Count of mappings created
        """
        count = 0

        if not os.path.exists(file_path):
            return count

        # Resolve the source label once so both CSV and JSON paths agree.
        ioc_label = (ioc_type or "auto").strip().lower()
        source = "IOC_File" if not ioc_label or ioc_label == "auto" else ioc_label

        # Determine file type
        file_ext = os.path.splitext(file_path)[1].lower()

        if file_ext == '.csv':
            count = self._ingest_csv(file_path, source=source)
        elif file_ext == '.json':
            count = self._ingest_json(file_path, source=source)
        else:
            # Try to detect format
            try:
                count = self._ingest_csv(file_path, source=source)
            except Exception:
                count = self._ingest_json(file_path, source=source)

        return count
    
    def _parse_csv(self, file_path: str) -> List[Tuple[str, str]]:
        """
        Parse CSV file and extract value-key mapping pairs.
        
        Args:
            file_path: Path to CSV file
        
        Returns:
            List of tuples (value, key)
        """
        import csv
        
        mappings = []
        with open(file_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            # Map of common header names (case-insensitive) for flexible ingestion
            val_headers = ['value', 'ioc', 'indicator', 'address', 'id', 'raw']
            key_headers = ['key', 'description', 'name', 'comment', 'context', 'user']
            
            # Detect actual fieldnames
            fields = [fn.lower() for fn in (reader.fieldnames or [])]
            v_field = next((f for f in reader.fieldnames if f.lower() in val_headers), None)
            k_field = next((f for f in reader.fieldnames if f.lower() in key_headers), None)
            
            # Fallback to first two columns if headers are unrecognizable
            if not v_field or not k_field:
                f.seek(0)
                next(f) # skip header row
                reader = csv.reader(f)
                for row in reader:
                    if len(row) >= 2:
                        value = row[0].strip()
                        key = row[1].strip()
                        if value and key:
                            mappings.append((value, key))
                return mappings

            for row in reader:
                value = row.get(v_field, '').strip()
                key = row.get(k_field, '').strip()
                if value and key:
                    mappings.append((value, key))
        
        return mappings
    
    def _parse_json(self, file_path: str) -> List[Tuple[str, str]]:
        """
        Parse JSON file and extract value-key mapping pairs.
        
        Args:
            file_path: Path to JSON file
        
        Returns:
            List of tuples (value, key)
        """
        import json
        
        mappings = []
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            if isinstance(data, list):
                for item in data:
                    value = item.get('value', '').strip()
                    key = item.get('key', '').strip()
                    if value and key:
                        mappings.append((value, key))
            elif isinstance(data, dict):
                for value, key in data.items():
                    v = str(value).strip()
                    k = str(key).strip()
                    if v and k:
                        mappings.append((v, k))
        
        return mappings
    
    def add_mapping(self, value: str, key: str, source: str, commit: bool = True) -> bool:
        """
        Add a single intelligence mapping.

        Returns True when the pair is in the database afterwards (new, merged
        or already there) - the old contract. ``upsert_mapping`` says which.
        """
        return self.upsert_mapping(value, key, source, commit) in (INSERTED, MERGED, DUPLICATE)

    @staticmethod
    def _key_present(stored: str, key: str) -> bool:
        r"""Is ``key`` one of the comma-joined names in ``stored``?

        Matched as a whole name between separators, not by splitting: names
        can contain commas themselves (a service's display name is often
        ``@%SystemRoot%\system32\x.dll,-101``), and splitting those never
        matched - so every run appended the same name again and the stored
        key grew without end.
        """
        stored = stored or ""
        if stored == key:
            return True
        padded = "," + ",".join(p.strip() for p in stored.split(",")) + ","
        return ("," + ",".join(p.strip() for p in key.split(",")) + ",") in padded

    def upsert_mapping(self, value: str, key: str, source: str, commit: bool = True) -> str:
        """
        Add a single intelligence mapping and say what it did.

        Args:
            value: Raw forensic value (e.g., "S-1-5-21-1001")
            key: Human-readable context (e.g., "Admin_Ghassan")
            source: Source of mapping (e.g., "Registry", "IOC_File", "Manual")
            commit: Whether to commit immediately (False for bulk operations)

        Returns:
            "inserted" (a new value), "merged" (a new key on a known value),
            "duplicate" (the value already had this key), "rejected" (empty
            value or key), or "error".
        """
        if not self._db_manager:
            return "error"
        
        try:
            conn = self._db_manager.connection
            if not conn:
                return "error"

            cursor = conn.cursor()

            # Sanitization: No empty values or keys allowed in our brain.
            value = str(value).strip() if value else ""
            key = str(key).strip() if key else ""
            if not value or not key:
                return REJECTED
            cursor.execute("SELECT id, key FROM Mapping WHERE value = ?", (value,))
            existing = cursor.fetchone()
            
            if existing:
                # Append to existing key and sanitize input
                if not existing['key']:
                    new_key = key
                else:
                    if not self._key_present(existing['key'], key):
                        new_key = existing['key'] + ',' + key
                    else:
                        return DUPLICATE  # Mapping already exists

                cursor.execute(
                    "UPDATE Mapping SET key = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (new_key, existing['id'])
                )
                outcome = MERGED
            else:
                cursor.execute(
                    "INSERT INTO Mapping (value, key, source) VALUES (?, ?, ?)",
                    (value, key, source)
                )
                outcome = INSERTED

            if commit:
                conn.commit()
            return outcome

        except Exception as e:
            self.logger.debug("Mapping %r not stored: %s", value, e)
            return "error"
    
    def get_mapping(self, value: str) -> Optional[str]:
        """
        Retrieve intelligence mapping for a value.
        
        Args:
            value: Raw forensic value to look up
        
        Returns:
            Human-readable context or None if not found
        """
        if not self._db_manager:
            return None
        
        try:
            conn = self._db_manager.connection
            if not conn:
                return None
                
            cursor = conn.cursor()
            cursor.execute("SELECT key FROM Mapping WHERE value = ?", (value,))
            result = cursor.fetchone()
            return result['key'] if result else None
        except Exception:
            return None
    
    def get_all_mappings(self) -> Dict[str, str]:
        """
        Retrieve all intelligence mappings as a dictionary.

        Returns:
            Dictionary mapping values to keys {value: key}
        """
        if not self._db_manager:
            return {}

        try:
            conn = self._db_manager.connection
            if not conn:
                return {}

            cursor = conn.cursor()
            cursor.execute("SELECT value, key FROM Mapping")
            return {row['value']: row['key'] for row in cursor.fetchall()}
        except Exception:
            return {}

    def get_all_mappings_with_source(self) -> List[Tuple[str, str, str]]:
        """
        Retrieve every intelligence mapping along with its source.

        Unlike get_all_mappings (which collapses duplicates because the value is
        the dict key), this returns the full (value, key, source) tuple so the
        Live Intelligence Registry can display the actual provenance per row
        instead of a hard-coded "Artifact Extraction" label.

        Returns:
            List of tuples (value, key, source). Empty list on any failure.
        """
        if not self._db_manager:
            return []
        try:
            conn = self._db_manager.connection
            if not conn:
                return []
            cursor = conn.cursor()
            cursor.execute("SELECT value, key, source FROM Mapping ORDER BY value")
            return [(row['value'], row['key'], row['source'] or "") for row in cursor.fetchall()]
        except Exception:
            return []
    
    def delete_mapping(self, value: str) -> bool:
        """
        Delete an intelligence mapping.
        
        Args:
            value: Raw forensic value to delete
        
        Returns:
            True if mapping deleted successfully
        """
        if not self._db_manager:
            return False
        
        try:
            conn = self._db_manager.connection
            if not conn:
                return False
                
            cursor = conn.cursor()
            cursor.execute("DELETE FROM Mapping WHERE value = ?", (value,))
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            return False
    
    def register_custom_rule(self, rule: CustomRule) -> bool:
        """
        Register a custom intelligence gathering rule.

        Delegates to CustomRulesManager so all CustomRules writes go through a
        single authoritative path (no parallel INSERT statements scattered
        across modules).

        Args:
            rule: CustomRule instance with query and mapping logic

        Returns:
            True if rule registered successfully
        """
        if not self.ensure_db():
            return False
        manager = self._get_custom_rules_manager()
        if not manager:
            return False
        return manager.create_rule(rule)
    
    def _validate_custom_rule(self, rule: CustomRule) -> Tuple[bool, str]:
        """
        Validate custom rule schema references.
        
        Args:
            rule: CustomRule instance to validate
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        return rule.validate()
    
    def validate(self) -> bool:
        """Validate component configuration."""
        return os.path.exists(self.case_directory)
    
    def initialize(self) -> bool:
        """Initialize component for use."""
        return self.ensure_db()
    
    def cleanup(self) -> None:
        """Clean up component resources — closes the intel DB and the custom-rules manager."""
        if self._db_manager:
            try:
                self._db_manager.close()
            except Exception:
                pass
            self._db_manager = None
        if self._custom_rules_manager:
            try:
                self._custom_rules_manager.cleanup()
            except Exception:
                pass
            self._custom_rules_manager = None
        self._is_initialized = False
    
    def _find_artifacts_directory(self) -> Optional[str]:
        """Find artifacts directory (Target_Artifacts, live_acquisition, or root).
        
        Verifies that the directory actually contains at least one .db file before
        designating it as the source.
        """
        if hasattr(self, "_artifacts_dir_cache"):
            return self._artifacts_dir_cache

        self.logger.debug(f"Searching for artifacts in: {self.case_directory}")

        result = None
        target_dir = os.path.join(self.case_directory, "Target_Artifacts")
        live_dir = os.path.join(self.case_directory, "live_acquisition")
        
        # Check standard directories first, but VERIFY they contain data
        for candidate in [target_dir, live_dir]:
            if os.path.exists(candidate) and os.path.isdir(candidate):
                db_files = [f for f in os.listdir(candidate) if f.endswith('.db')]
                if db_files:
                    self.logger.info(f"Found artifacts directory with {len(db_files)} DBs: {candidate}")
                    result = candidate
                    break
        
        # Fallback to case root
        if result is None and os.path.exists(self.case_directory):
            db_files = [f for f in os.listdir(self.case_directory)
                        if f.endswith('.db') and f != "Crow_Intelligence.db"]
            if db_files:
                self.logger.info(f"Found {len(db_files)} .db files in case root: {self.case_directory}")
                result = self.case_directory

        if result is None:
            self.logger.warning("No artifacts directory found containing .db files.")

        self._artifacts_dir_cache = result
        return result

    def _store_mappings(self, mappings: List[Tuple[str, str, str]],
                        result: Optional[RuleResult] = None) -> int:
        """Store mappings in database, handling conflicts with a single transaction.

        Uses a single explicit transaction bracket so the whole batch is atomic.
        The inner add_mapping() calls use commit=False so they never issue an
        intermediate COMMIT that would conflict with the outer transaction.

        Returns the links ADDED (new values + new keys). With ``result``, every
        outcome (inserted / merged / duplicate / rejected) is counted on it.
        """
        count = 0
        if not mappings:
            return 0

        conn = self._db_manager.connection
        if not conn:
            return 0

        # Save the current isolation level and switch to deferred autocommit
        # mode so we control the transaction boundaries ourselves.
        old_isolation = conn.isolation_level
        try:
            # Temporarily disable Python's automatic transaction management so
            # that explicit BEGIN / COMMIT below are the only boundary markers.
            conn.isolation_level = None   # autocommit mode
            conn.execute("BEGIN DEFERRED")

            for value, key, source in mappings:
                # Skip non-informative mappings. "Description not available" is the
                # placeholder WinLog_Claw stores for unknown Event IDs; persisting it
                # pollutes the intelligence DB and enriches unrelated numeric columns
                # with a meaningless label.
                if key is None or str(key).strip().lower() in ("", "description not available"):
                    if result is not None:
                        result.count(REJECTED)
                    continue
                outcome = self.upsert_mapping(value, key, source, commit=False)
                if result is not None:
                    result.count(outcome)
                if outcome in (INSERTED, MERGED):
                    count += 1

            conn.execute("COMMIT")

        except Exception as e:
            self.logger.error("Bulk storage failed: %s", e)
            if result is not None:
                result.status, result.reason = "failed", "storing mappings failed: %s" % e
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
        finally:
            # Always restore the isolation level so subsequent callers don't
            # find the connection unexpectedly in autocommit mode.
            conn.isolation_level = old_isolation

        return count
    
    def _ingest_csv(self, file_path: str, source: str = "IOC_File") -> int:
        """Ingest mappings from CSV file using bulk transaction.

        Args:
            file_path: Path to CSV file
            source: Mapping.source value to attach to each row. Defaults to the
                generic "IOC_File" but ingest_ioc_file overrides it with the
                user-selected IOC type (hash / ip / domain) so the source
                column reflects the indicator kind.
        """
        mappings = self._parse_csv(file_path)
        source_mappings = [(v, k, source) for v, k in mappings]
        return self._store_mappings(source_mappings)

    def _ingest_json(self, file_path: str, source: str = "IOC_File") -> int:
        """Ingest mappings from JSON file using bulk transaction. See _ingest_csv for source semantics."""
        mappings = self._parse_json(file_path)
        source_mappings = [(v, k, source) for v, k in mappings]
        return self._store_mappings(source_mappings)
    
    def _log_gather_history(self, res: RuleResult, run: LinkRun) -> None:
        """One GatherHistory row per rule, with the run it belongs to.

        Skipped rules are recorded too: a rule whose database was missing used
        to leave no trace at all.
        """
        try:
            conn = self._db_manager.connection if self._db_manager else None
            if not conn:
                return
            conn.execute(
                """
                INSERT INTO GatherHistory
                (rule_name, rule_type, mappings_count, execution_time_ms, status, error_message,
                 run_id, run_kind, category, source_db, source_table, value_column, key_column,
                 rows_read, inserted, merged, duplicate, rejected)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (res.rule, res.rule_type, res.new_links, res.duration_ms,
                 {"ok": "success"}.get(res.status, res.status), res.reason or None,
                 run.run_id, run.kind, res.category, res.source_db, res.source_table,
                 res.value_column, res.key_column, res.rows_read, res.inserted, res.merged,
                 res.duplicate, res.rejected))
            conn.commit()
        except Exception as e:
            # WARNING, not DEBUG: a lost row is a rule missing from the
            # statistics of every later look at this run.
            self.logger.warning("GatherHistory row not written for %s: %s", res.rule, e)