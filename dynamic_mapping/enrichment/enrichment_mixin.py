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
    
    # Enrichment Target Columns: Column indices that should be enriched
    # This allows selective enrichment of specific columns in a table
    ENRICHMENT_TARGET_COLUMNS = {
        0,  # First column typically contains values to enrich
        1,  # Second column often contains related values
    }
    
    def __init__(self):
        """Initialize the enrichment mixin."""
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
        2. Performs a LEFT JOIN on the Mapping table
        3. Enforces Source Exclusion Rule natively by filtering out mappings where source = current_table
        4. Returns the original data plus the Dynamic_Key column
        
        Args:
            base_query: The base SQL query to enrich
            table_name: Name of the table being queried
            value_column: Name of the column containing values to enrich
            
        Returns:
            Enriched SQL query string with LEFT JOIN
            
        Example:
            Input:  "SELECT * FROM LNK_table"
            Output: "SELECT L.*, Intel.Mapping.Key AS Dynamic_Key 
                     FROM LNK_table L 
                     LEFT JOIN Intel.Mapping ON L.target_column = Intel.Mapping.Value AND Intel.Mapping.source != 'LNK_table'"
        """
        if not base_query or not table_name or not value_column:
            return base_query
        
        # Check if intelligence database exists
        if not self._intelligence_db_path or not os.path.exists(self._intelligence_db_path):
            # Graceful degradation: return base query without enrichment
            return base_query
        
        # Generate enriched query with LEFT JOIN
        # Use table alias to avoid column name conflicts
        alias = table_name[:1].upper()  # Use first letter as alias
        
        # Parse the base query to add enrichment
        query_upper = base_query.upper().strip()
        
        if query_upper.startswith("SELECT"):
            # Find FROM clause
            from_pos = query_upper.find(" FROM ")
            if from_pos > 0:
                # Extract SELECT and FROM parts
                select_part = base_query[:from_pos].strip()
                from_part = base_query[from_pos + 6:].strip()  # Skip " FROM "
                
                # Build enriched query
                # Enforce Source Exclusion explicitly in the ON clause
                # We use a unique alias to avoid clashing with the user's existing aliases
                # Because databases hate it when they don't know who they are.
                alias = f"{table_name[:3]}_tbl"
                
                # To avoid ambiguous columns (like 'Source'), we try to prefix them
                select_cols = select_part
                if "*" in select_part:
                    select_cols = f"{alias}.*"
                elif "," in select_part and not any(f"{alias}." in col for col in select_part.split(",")):
                    # Simple prefixing for simple column lists
                    if "(" not in select_part: # Avoid breaking complex SQL magic
                        cols = [c.strip() for c in select_part.split(",")]
                        select_cols = ", ".join([f"{alias}.{c}" for c in cols])
                
                enriched_query = (
                    f"{select_cols}, Intel.Mapping.Key AS Dynamic_Key "
                    f"FROM {from_part} AS {alias} "
                    f"LEFT JOIN Intel.Mapping ON {alias}.{value_column} = Intel.Mapping.Value "
                    f"AND Intel.Mapping.source != '{table_name}'"
                )
                
                return enriched_query
        
        # Fallback: return base query unchanged
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
                self.logger.debug("Intel DB is already invited to the party. No need to re-invite.")
                self._intelligence_db_attached = True
                return True
                
            cursor.execute(f"ATTACH DATABASE '{self._intelligence_db_path}' AS Intel")
            self._intelligence_db_attached = True
            return True
        except Exception as e:
            # Maybe it's already attached under a different name? Or SQLite is just having a Monday.
            if "already in use" in str(e).lower() or "already attached" in str(e).lower():
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
