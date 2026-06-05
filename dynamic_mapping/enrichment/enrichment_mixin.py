"""
Enrichment Mixin for the Dynamic Linking Intelligence Engine.

This module provides the EnrichmentMixin class that adds data enrichment capabilities
to Crow Eye's data display methods. The mixin enables inline cell enrichment at the
SQL query level using SQLite's ATTACH mechanism for high-performance enrichment.
"""

import os
from typing import Optional


class EnrichmentMixin:
    """
    Mixin class that provides data enrichment capabilities for Crow Eye display methods.
    
    This mixin enables:
    - Source Exclusion Rule enforcement (prevents circular enrichment dynamically via SQL)
    - Inline cell enrichment format: "Value [Dynamic_Key]"
    - Graceful degradation if intelligence DB is missing
    - Support for multiple comma-separated keys
    
    The enrichment is applied at the SQL query level using LEFT JOIN operations
    with the Crow_Intelligence.db database, ensuring high performance without
    memory overhead from Python dictionary lookups.
    """
    
    # Enrichment Target Columns: Common forensic column names that should be enriched.
    # VirtualTableWidget._initialize_intelligence iterates self.columns and checks
    # `if candidate in self.ENRICHMENT_TARGET_COLUMNS` — so this must be a set of
    # STRINGS, not a set of integer indices.
    ENRICHMENT_TARGET_COLUMNS = {
        # Identity / SID
        'user_sid', 'SID', 'sid',
        # Paths / executables
        'profile_path', 'target_path', 'Local_Path', 'executable_path', 'process_path',
        'program_path', 'app_path', 'key_path', 'path', 'filename', 'Filename',
        # Network
        'mac_address', 'MAC_Address', 'gateway_mac', 'Tracker_MAC',
        'ip_address', 'IP_Address',
        # Device identifiers
        'serial_number', 'device_id', 'volume_guid', 'Volume_Serial', 'AppID',
        # Application / service
        'Source_Name', 'service_name', 'app_name', 'display_name', 'Name',
        # Generic value columns
        'Value', 'value', 'Name', 'name', 'id', 'ID',
    }
    
    def __init__(self):
        """Initialize the enrichment mixin."""
        import logging
        if not hasattr(self, 'logger'):
            self.logger = logging.getLogger(self.__class__.__name__)
        self._intelligence_db_path: Optional[str] = None
        self._intelligence_db_attached = False
    
    def is_enrichment_target_column(self, col_idx: int) -> bool:
        """
        Check if a column should be enriched.
        
        This allows selective enrichment of specific columns in a table,
        enabling fine-grained control over which fields receive inline enrichment.
        
        Args:
            col_idx: Zero-based column index
            
        Returns:
            True if the column should be enriched, False otherwise
        """
        return col_idx in self.ENRICHMENT_TARGET_COLUMNS
    
    def get_enrichment_query(self, base_query: str, table_name: str, 
                            value_column: str) -> str:
        """
        Generate an enrichment query that ATTACHs the intelligence database.
        
        This method creates a smart SQL query that:
        1. ATTACHs the Crow_Intelligence.db database
        2. Uses a correlated subquery with GROUP_CONCAT to fetch mappings
        3. Enforces Source Exclusion Rule natively
        4. Guarantees 1-to-1 row results to prevent row-shifting in virtual tables
        """
        if not base_query or not table_name or not value_column:
            return base_query
        
        # Check if intelligence database exists
        if not self._intelligence_db_path or not os.path.exists(self._intelligence_db_path):
            return base_query
        
        query_upper = base_query.upper().strip()
        
        if query_upper.startswith("SELECT"):
            from_pos = query_upper.find(" FROM ")
            if from_pos > 0:
                select_part = base_query[:from_pos].strip()
                from_part = base_query[from_pos + 6:].strip()

                alias = f"{table_name[:3]}_tbl"
                quoted_alias = f'"{alias}"'
                quoted_value_column = f'"{value_column}"'
                table_literal = table_name.replace("'", "''")

                # Prefix columns properly, handling the SELECT keyword correctly
                # To avoid ambiguous columns (like 'Source'), we try to prefix them
                select_cols = select_part
                # Strip "SELECT" from select_part to prefix columns properly without prefixing the SELECT keyword itself
                if select_part.upper().startswith("SELECT "):
                    cols_part = select_part[7:].strip()
                    if "*" in cols_part:
                        select_cols = f"SELECT {quoted_alias}.*"
                    elif "," in cols_part and not any(f"{alias}." in col for col in cols_part.split(",")):
                        # Simple prefixing for simple column lists
                        if "(" not in cols_part:  # Avoid breaking complex SQL magic
                            cols = [c.strip() for c in cols_part.split(",")]
                            prefixed = ", ".join([f"{quoted_alias}.{c}" for c in cols])
                            select_cols = "SELECT " + prefixed
                    else:
                        # Fallback for complex SELECT parts
                        select_cols = select_part
                else:
                    select_cols = select_part

                # Use a correlated subquery with GROUP_CONCAT. 
                # This is critical: if a value has multiple mappings, we MUST 
                # concatenate them into one string rather than returning 
                # multiple rows, which would shift indices in our virtual table.
                subquery = (
                    f"(SELECT GROUP_CONCAT(Key, ', ') FROM Intel.Mapping "
                    f"WHERE REPLACE({quoted_alias}.{quoted_value_column}, 'PySID:', '') = Intel.Mapping.Value "
                    f"AND Intel.Mapping.source != '{table_literal}')"
                )

                enriched_query = (
                    f"{select_cols}, {subquery} AS Dynamic_Key "
                    f"FROM {from_part} AS {quoted_alias}"
                )

                return enriched_query

        return base_query
    
    def format_enriched_value(self, value: str, dynamic_key: Optional[str]) -> str:
        """
        Format a cell value with inline enrichment.
        
        This method applies the inline enrichment format:
        - "Value [Dynamic_Key]" when a mapping exists
        - Raw value without brackets when no mapping exists
        - Support for multiple comma-separated keys
        
        Args:
            value: The raw value from the database
            dynamic_key: The enriched key from the Mapping table (may be None)
            
        Returns:
            Formatted string with inline enrichment
            
        Examples:
            >>> format_enriched_value("S-1-5-21-1001", "Admin_Ghassan")
            'S-1-5-21-1001 [Admin_Ghassan]'
            
            >>> format_enriched_value("00:1A:2B:3C:4D:5E", None)
            '00:1A:2B:3C:4D:5E'
            
            >>> format_enriched_value("S-1-5-21-1001", "Admin_Ghassan,LocalAdmin")
            'S-1-5-21-1001 [Admin_Ghassan,LocalAdmin]'
        """
        # Handle None value
        if value is None:
            return ""
        
        # Convert to string
        value_str = str(value)
        
        # Handle empty string
        if not value_str or not value_str.strip():
            return value_str
        
        if not dynamic_key:
            # No mapping exists - return raw value
            return value_str

        # Multi-key mappings (e.g. a SID that resolves to BOTH a username and a
        # profile path) are stored comma-joined in Mapping.key. Render them with
        # a pipe separator so cells read cleanly: "S-... [Admin | C:\\Users\\..]"
        # instead of "[Admin,C:\\Users\\..]".
        if "," in dynamic_key:
            parts = [p.strip() for p in dynamic_key.split(",") if p.strip()]
            if parts:
                return f"{value_str} [{' | '.join(parts)}]"

        # Apply inline enrichment format: "Value [Dynamic_Key]"
        return f"{value_str} [{dynamic_key}]"
    
    def attach_intelligence_db(self, cursor) -> bool:
        """
        ATTACH the intelligence database to the current connection.
        
        This method must be called before executing enriched queries.
        
        Args:
            cursor: Database cursor to use for ATTACH command
            
        Returns:
            True if database attached successfully, False otherwise
        """
        if not self._intelligence_db_path:
            return False
        
        if not os.path.exists(self._intelligence_db_path):
            return False
        
        try:
            # Check if already attached by querying database_list
            cursor.execute("PRAGMA database_list")
            attached_dbs = [row[1] for row in cursor.fetchall()]

            if 'Intel' in attached_dbs:
                self._intelligence_db_attached = True
                return True

            # Use parameterized ATTACH to safely handle paths with special chars.
            cursor.execute("ATTACH DATABASE ? AS Intel", (self._intelligence_db_path,))
            self._intelligence_db_attached = True

            # Index the enrichment lookup column so the per-row correlated subquery
            # (… WHERE base.col = Intel.Mapping.Value AND source != …) is an index
            # seek rather than a full scan of Mapping — a big speedup when scrolling
            # enriched tables (e.g. SRUM). Idempotent and best-effort.
            try:
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS Intel.idx_mapping_value_source "
                    "ON Mapping(Value, source)"
                )
            except Exception:
                pass  # read-only intel DB or older schema — enrichment still works

            return True
        except Exception as e:
            err = str(e).lower()
            if "already in use" in err or "already attached" in err or "already" in err:
                self._intelligence_db_attached = True
                return True
            return False
    
    def detach_intelligence_db(self, cursor) -> bool:
        """
        DETACH the intelligence database from the current connection.
        
        This method should be called after enrichment operations complete
        to free database resources.
        
        Args:
            cursor: Database cursor to use for DETACH command
            
        Returns:
            True if database detached successfully, False otherwise
        """
        if not self._intelligence_db_attached:
            return True  # Already detached
        
        try:
            cursor.execute("DETACH DATABASE Intel")
            self._intelligence_db_attached = False
            return True
        except Exception:
            return False
    
    def set_intelligence_db_path(self, case_directory: str) -> None:
        """
        Set the path to the intelligence database.
        
        Args:
            case_directory: Path to the case directory containing Crow_Intelligence.db
        """
        self._intelligence_db_path = os.path.join(case_directory, "Crow_Intelligence.db")
    
    def get_intelligence_db_path(self) -> Optional[str]:
        """
        Get the path to the intelligence database.
        
        Returns:
            Full path to Crow_Intelligence.db or None if not set
        """
        return self._intelligence_db_path
