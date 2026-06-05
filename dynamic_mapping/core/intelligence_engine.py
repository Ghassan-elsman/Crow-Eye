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
        self.logger = logging.getLogger(self.__class__.__name__)
        self.case_directory = case_directory
        self.intelligence_db_path = os.path.join(case_directory, "Crow_Intelligence.db")
        self._db_manager: Optional[DatabaseManager] = None
        self._is_initialized = False
        self._custom_rules_manager = None  # Lazy-initialized CustomRulesManager
    
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
                self.gather_intelligence(["Well_Known_SIDs"])
                
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
    
    def gather_intelligence(self, rules: List[str], custom_rules: bool = True) -> Dict[str, int]:
        """
        Execute intelligence gathering using specified default rules and (optionally)
        every enabled CustomRule stored in the CustomRules table.

        Args:
            rules: List of default-rule names to execute (e.g., ["SID_to_Username",
                "MAC_to_NetworkName"]). Pass an empty list to skip default rules.
            custom_rules: If True (default), also runs every enabled CustomRule
                stored in CustomRules against the same artifacts directory.

        Returns:
            Dictionary mapping rule names to count of mappings gathered. Includes
            both default and custom rule names.
        """
        results = {}
        
        # Import here to avoid circular imports
        from dynamic_mapping.rules.default_rules import DEFAULT_RULES
        
        # Verify database availability
        if not self.ensure_db():
            return {rule: 0 for rule in rules}
            
        for rule_name in rules:
            if rule_name not in DEFAULT_RULES:
                results[rule_name] = 0
                continue
            
            rule = DEFAULT_RULES[rule_name]
            t0 = time.perf_counter()
            try:
                # Support for internal rules that don't require an external database
                # These can run even without an artifacts directory
                if getattr(rule, 'target_db_name', None) is None:
                    extracted = rule.extract_mappings([])
                    results[rule_name] = self._store_mappings(extracted)
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    self._log_gather_history(rule_name, "internal", results[rule_name], "success", None, elapsed_ms)
                    continue

                # Determine artifacts directory for database-backed rules
                artifacts_dir = self._find_artifacts_directory()
                
                if not artifacts_dir:
                    print(f"[IntelligenceEngine] Skipping rule {rule_name}: No artifacts directory found.")
                    results[rule_name] = 0
                    continue
                
                # Get target DB and attach it
                target_db_path = rule.get_target_db(artifacts_dir)

                if not target_db_path or not os.path.exists(target_db_path):
                    print(f"[IntelligenceEngine] Skipping rule {rule_name}: Target DB {target_db_path} not found.")
                    results[rule_name] = 0
                    continue
                conn = self._db_manager.connection
                if not conn:
                    results[rule_name] = 0
                    continue
                    
                cursor = conn.cursor()
                
                # Check if TargetDB is already attached (safety first!)
                # Check if TargetDB is already attached to prevent conflicts
                cursor.execute("PRAGMA database_list")
                attached_dbs = [row[1] for row in cursor.fetchall()]
                if 'TargetDB' in attached_dbs:
                    cursor.execute("DETACH DATABASE TargetDB")
                
                # Attach target database for extraction
                cursor.execute("ATTACH DATABASE ? AS TargetDB", (str(target_db_path),))
                
                try:
                    # Execute extraction query
                    query = rule.get_query()
                    cursor.execute(query)
                    
                    # Extract and store mappings
                    extracted = rule.extract_mappings(cursor.fetchall())
                    results[rule_name] = self._store_mappings(extracted)
                    
                    # Log to GatherHistory
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    self._log_gather_history(rule_name, "default", results[rule_name], "success", None, elapsed_ms)
                finally:
                    # Detach database after processing
                    cursor.execute("DETACH DATABASE TargetDB")

            except Exception as e:
                print(f"[IntelligenceEngine] Error executing rule {rule_name}: {str(e)}")
                results[rule_name] = 0
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                self._log_gather_history(rule_name, "default", 0, "failed", str(e), elapsed_ms)

        # ---- Custom rules ------------------------------------------------
        # Every enabled CustomRule stored in CustomRules is executed against
        # the same artifacts directory. Failures are isolated per rule so a
        # bad custom rule cannot kill the whole gather.
        if custom_rules:
            artifacts_dir = self._find_artifacts_directory()
            manager = self._get_custom_rules_manager()
            stored_rules = manager.list_rules() if manager else []
            for rule in stored_rules:
                t0 = time.perf_counter()
                try:
                    if not artifacts_dir:
                        results[rule.name] = 0
                        elapsed_ms = int((time.perf_counter() - t0) * 1000)
                        self._log_gather_history(rule.name, "custom", 0, "skipped",
                                                 "no artifacts directory", elapsed_ms)
                        continue
                    extracted = rule.execute(artifacts_dir)
                    stored = self._store_mappings(extracted)
                    results[rule.name] = stored
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    self._log_gather_history(rule.name, "custom", stored, "success", None, elapsed_ms)
                except Exception as e:
                    print(f"[IntelligenceEngine] Custom rule {rule.name} failed: {e}")
                    results[rule.name] = 0
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    self._log_gather_history(rule.name, "custom", 0, "failed", str(e), elapsed_ms)

        return results

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
        
        Args:
            value: Raw forensic value (e.g., "S-1-5-21-1001")
            key: Human-readable context (e.g., "Admin_Ghassan")
            source: Source of mapping (e.g., "Registry", "IOC_File", "Manual")
            commit: Whether to commit immediately (False for bulk operations)
        
        Returns:
            True if mapping added successfully
        """
        if not self._db_manager:
            return False
        
        try:
            conn = self._db_manager.connection
            if not conn:
                return False
                
            cursor = conn.cursor()
            
            # Sanitization: No empty values or keys allowed in our brain.
            value = str(value).strip() if value else ""
            key = str(key).strip() if key else ""
            if not value or not key:
                return False
            cursor.execute("SELECT id, key FROM Mapping WHERE value = ?", (value,))
            existing = cursor.fetchone()
            
            if existing:
                # Append to existing key and sanitize input
                if not existing['key']:
                    new_key = key
                else:
                    existing_keys = [k.strip() for k in existing['key'].split(',')]
                    if key not in existing_keys:
                        new_key = existing['key'] + ',' + key
                    else:
                        return True # Mapping already exists
                
                cursor.execute(
                    "UPDATE Mapping SET key = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (new_key, existing['id'])
                )
            else:
                cursor.execute(
                    "INSERT INTO Mapping (value, key, source) VALUES (?, ?, ?)",
                    (value, key, source)
                )
            
            if commit:
                conn.commit()
            return True
            
        except Exception:
            return False
    
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

    def _store_mappings(self, mappings: List[Tuple[str, str, str]]) -> int:
        """Store mappings in database, handling conflicts with a single transaction.

        Uses a single explicit transaction bracket so the whole batch is atomic.
        The inner add_mapping() calls use commit=False so they never issue an
        intermediate COMMIT that would conflict with the outer transaction.
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
                    continue
                if self.add_mapping(value, key, source, commit=False):
                    count += 1

            conn.execute("COMMIT")

        except Exception as e:
            print(f"[IntelligenceEngine] Bulk storage failed: {e}")
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
    
    def _log_gather_history(self, rule_name: str, rule_type: str,
                           mappings_count: int, status: str,
                           error_message: Optional[str],
                           execution_time_ms: Optional[int] = None) -> None:
        """
        Log gather operation to GatherHistory table.

        Args:
            rule_name: Name of rule executed
            rule_type: Type of rule ("default" or "custom")
            mappings_count: Number of mappings gathered
            status: Execution status ("success", "failed", "partial", "skipped")
            error_message: Error details if failed
            execution_time_ms: Wall-clock duration of the rule run, in milliseconds
        """
        try:
            conn = self._db_manager.connection
            if not conn:
                return

            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO GatherHistory
                (rule_name, rule_type, mappings_count, execution_time_ms, status, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (rule_name, rule_type, mappings_count, execution_time_ms, status, error_message)
            )
            conn.commit()
        except Exception:
            pass