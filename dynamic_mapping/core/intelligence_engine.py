"""
Core IntelligenceEngine class for the Dynamic Linking Intelligence Engine.
"""

import os
import sqlite3
import time
from typing import Dict, List, Optional, Tuple

from dynamic_mapping.core.base import BaseComponent
from dynamic_mapping.core.database import DatabaseManager
from dynamic_mapping.rules.base import DefaultRule, CustomRule


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
        self.case_directory = case_directory
        self.intelligence_db_path = os.path.join(case_directory, "Crow_Intelligence.db")
        self._db_manager: Optional[DatabaseManager] = None
        self._is_initialized = False
    
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
    
    def gather_intelligence(self, rules: List[str]) -> Dict[str, int]:
        """
        Execute intelligence gathering using specified default rules.
        
        Args:
            rules: List of rule names to execute (e.g., ["SID_to_Username", "MAC_to_NetworkName"])
        
        Returns:
            Dictionary mapping rule names to count of mappings gathered
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
            try:
                # Support for internal rules that don't require an external database
                # These can run even without an artifacts directory
                if getattr(rule, 'target_db_name', None) is None:
                    extracted = rule.extract_mappings([])
                    results[rule_name] = self._store_mappings(extracted)
                    self._log_gather_history(rule_name, "internal", results[rule_name], "success", None)
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
                safe_db_path = str(target_db_path).replace("'", "''")
                cursor.execute(f"ATTACH DATABASE '{safe_db_path}' AS TargetDB")
                
                try:
                    # Execute extraction query
                    query = rule.get_query()
                    cursor.execute(query)
                    
                    # Extract and store mappings
                    extracted = rule.extract_mappings(cursor.fetchall())
                    results[rule_name] = self._store_mappings(extracted)
                    
                    # Log to GatherHistory
                    self._log_gather_history(rule_name, "default", results[rule_name], "success", None)
                finally:
                    # Detach database after processing
                    cursor.execute("DETACH DATABASE TargetDB")
                
            except Exception as e:
                print(f"[IntelligenceEngine] Error executing rule {rule_name}: {str(e)}")
                results[rule_name] = 0
                self._log_gather_history(rule_name, "default", 0, "failed", str(e))
        
        return results
    
    def _execute_rule(self, rule: DefaultRule) -> int:
        """
        Execute a single default rule and return mapping count.
        
        Args:
            rule: DefaultRule instance to execute
        
        Returns:
            Count of mappings gathered
        """
        try:
            artifacts_dir = self._find_artifacts_directory()
            if not artifacts_dir:
                return 0
            
            target_db_path = rule.get_target_db(artifacts_dir)
            if not target_db_path:
                return 0
                
            conn = self._db_manager.connection
            if not conn:
                return 0
            
            cursor = conn.cursor()
            cursor.execute(f"ATTACH DATABASE '{target_db_path}' AS TargetDB")
            try:
                query = rule.get_query()
                cursor.execute(query)
                mappings = rule.extract_mappings(cursor.fetchall())
                return self._store_mappings(mappings)
            finally:
                cursor.execute("DETACH DATABASE TargetDB")
            
        except Exception:
            return 0
    
    def _handle_conflict(self, value: str, new_key: str) -> str:
        """
        Handle conflict resolution for duplicate values.
        
        Args:
            value: The value that has conflicting mappings
            new_key: The new key to add
        
        Returns:
            Combined key string with comma-separated values
        """
        existing = self.get_mapping(value)
        if existing:
            existing_keys = existing.split(',')
            if new_key not in existing_keys:
                return existing + ',' + new_key
        return new_key
    
    def ingest_ioc_file(self, file_path: str, ioc_type: str = "auto") -> int:
        """
        Ingest IOC file and create intelligence mappings.
        
        Args:
            file_path: Path to IOC file (CSV or JSON)
            ioc_type: Type of IOC (hash, ip, domain, etc.) or "auto" to detect
        
        Returns:
            Count of mappings created
        """
        count = 0
        
        if not os.path.exists(file_path):
            return count
        
        # Determine file type
        file_ext = os.path.splitext(file_path)[1].lower()
        
        if file_ext == '.csv':
            count = self._ingest_csv(file_path)
        elif file_ext == '.json':
            count = self._ingest_json(file_path)
        else:
            # Try to detect format
            try:
                count = self._ingest_csv(file_path)
            except:
                count = self._ingest_json(file_path)
        
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
        
        Args:
            rule: CustomRule instance with query and mapping logic
        
        Returns:
            True if rule registered successfully
        """
        if not self._db_manager:
            return False
        
        # Validate rule
        is_valid, error_msg = self._validate_custom_rule(rule)
        if not is_valid:
            return False
        
        try:
            conn = self._db_manager.connection
            if not conn:
                return False
                
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO CustomRules 
                (name, category, description, db_name, table_name, value_column, key_column, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (rule.name, rule.category, rule.description, rule.db_name, 
                 rule.table_name, rule.value_column, rule.key_column)
            )
            conn.commit()
            return True
        except Exception:
            return False
    
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
        """Clean up component resources."""
        if self._db_manager:
            try:
                self._db_manager.close()
            except:
                pass
            self._db_manager = None
    
    def _find_artifacts_directory(self) -> Optional[str]:
        """Find artifacts directory (Target_Artifacts, live_acquisition, or root)."""
        print(f"[IntelligenceEngine] Searching for artifacts in: {self.case_directory}")

        # Check standard locations
        target_dir = os.path.join(self.case_directory, "Target_Artifacts")
        if os.path.exists(target_dir):
            print(f"[IntelligenceEngine] Found artifacts in Target_Artifacts: {target_dir}")
            return target_dir

        live_dir = os.path.join(self.case_directory, "live_acquisition")
        if os.path.exists(live_dir):
            print(f"[IntelligenceEngine] Found artifacts in live_acquisition: {live_dir}")
            return live_dir

        # Fallback to case root itself (useful for testing)
        if os.path.exists(self.case_directory):
            # Check for database files in case root
            # Exclude intelligence database from artifact scanning
            db_files = [f for f in os.listdir(self.case_directory) 
                       if f.endswith('.db') and f != "Crow_Intelligence.db"]
            if db_files:
                print(f"[IntelligenceEngine] Found {len(db_files)} .db files in case root: {self.case_directory}")
                return self.case_directory

        print("[IntelligenceEngine] Warning: No artifacts directory found.")
        return None    
    def _store_mappings(self, mappings: List[Tuple[str, str, str]]) -> int:
        """Store mappings in database, handling conflicts with a single transaction."""
        count = 0
        if not mappings: return 0
        
        try:
            conn = self._db_manager.connection
            # Use transaction for optimized ingestion
            cursor = conn.cursor()
            cursor.execute("BEGIN TRANSACTION")
            
            for value, key, source in mappings:
                if self.add_mapping(value, key, source, commit=False):
                    count += 1
            
            conn.commit()
        except Exception as e:
            print(f"[IntelligenceEngine] Bulk storage failed: {e}")
            if self._db_manager.connection:
                self._db_manager.connection.rollback()
        return count
    
    def _ingest_csv(self, file_path: str) -> int:
        """Ingest mappings from CSV file using bulk transaction."""
        mappings = self._parse_csv(file_path)
        # Add the "IOC_File" source to each mapping
        source_mappings = [(v, k, "IOC_File") for v, k in mappings]
        return self._store_mappings(source_mappings)
    
    def _ingest_json(self, file_path: str) -> int:
        """Ingest mappings from JSON file using bulk transaction."""
        mappings = self._parse_json(file_path)
        # Add the "IOC_File" source to each mapping
        source_mappings = [(v, k, "IOC_File") for v, k in mappings]
        return self._store_mappings(source_mappings)
    
    def _log_gather_history(self, rule_name: str, rule_type: str, 
                           mappings_count: int, status: str, 
                           error_message: Optional[str]) -> None:
        """
        Log gather operation to GatherHistory table.
        
        Args:
            rule_name: Name of rule executed
            rule_type: Type of rule ("default" or "custom")
            mappings_count: Number of mappings gathered
            status: Execution status ("success", "failed", "partial")
            error_message: Error details if failed
        """
        try:
            conn = self._db_manager.connection
            if not conn:
                return
                
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO GatherHistory 
                (rule_name, rule_type, mappings_count, status, error_message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (rule_name, rule_type, mappings_count, status, error_message)
            )
            conn.commit()
        except Exception:
            pass