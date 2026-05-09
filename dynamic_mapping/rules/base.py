"""
Base classes for rules in the Dynamic Linking Intelligence Engine.
"""

from abc import ABC, abstractmethod
from typing import List, Tuple, Optional


class DefaultRule(ABC):
    """
    Base class for default intelligence gathering rules.
    
    All default rules must inherit from this class and implement
    the required methods for SQL query generation and mapping extraction.
    """
    
    def __init__(self, name: str, category: str, description: str, target_db_name: str):
        """
        Initialize a default rule.
        
        Args:
            name: Rule identifier (e.g., "SID_to_Username")
            category: Forensic category (e.g., "SID", "MAC", "Hash")
            description: Human-readable description of what the rule does
            target_db_name: Name of the target database file (e.g., 'registry_data.db')
        """
        self.name = name
        self.category = category
        self.description = description
        self.target_db_name = target_db_name
    
    def get_target_db(self, artifacts_dir: str) -> Optional[str]:
        """Find the target database file in the artifacts directory."""
        import os
        if self.target_db_name is None:
            return None
        db_path = os.path.join(artifacts_dir, self.target_db_name)
        if os.path.exists(db_path):
            return db_path
        return None

    @abstractmethod
    def get_query(self) -> str:
        """
        Generate SQL SELECT query for intelligence gathering.
        The query should assume the target database is attached as 'TargetDB'.
        
        Returns:
            SQL SELECT query string
        """
        pass
    
    @abstractmethod
    def extract_mappings(self, query_results: List[Tuple]) -> List[Tuple[str, str, str]]:
        """
        Extract intelligence mappings from query results.
        
        Args:
            query_results: Raw query results from database
        
        Returns:
            List of tuples (value, key, source)
        """
        pass


class CustomRule:
    """
    Represents a custom intelligence gathering rule defined via GUI dropdowns.
    
    Custom rules allow investigators to create intelligence gathering rules
    for any forensic artifact table by specifying database, table, and column names.
    """
    
    def __init__(
        self,
        name: str,
        category: str,
        db_name: str,
        table_name: str,
        value_column: str,
        key_column: str,
        description: Optional[str] = None
    ):
        """
        Initialize a custom rule.
        
        Args:
            name: Rule identifier
            category: Forensic category
            db_name: Source database file (e.g., 'registry_data.db')
            table_name: Target table within DB
            value_column: Column name for raw values
            key_column: Column name for human-readable keys
            description: Human-readable description (optional)
        """
        self.name = name
        self.category = category
        self.db_name = db_name
        self.table_name = table_name
        self.value_column = value_column
        self.key_column = key_column
        self.description = description or f"Custom rule for {category} mappings"
    
    def validate(self) -> Tuple[bool, str]:
        """
        Validate custom rule schema references.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Basic validation - check required fields are not empty
        required_fields = {
            'name': self.name,
            'category': self.category,
            'db_name': self.db_name,
            'table_name': self.table_name,
            'value_column': self.value_column,
            'key_column': self.key_column
        }
        
        missing_fields = [field for field, value in required_fields.items() if not value or not value.strip()]
        
        if missing_fields:
            return False, f"Missing required fields: {', '.join(missing_fields)}"
        
        return True, ""
    
    def generate_query(self) -> str:
        """
        Automatically generate the SQL query needed to extract this data.
        
        Returns:
            SQL query string
        """
        return f"""
        SELECT 
            {self.value_column} AS value,
            {self.key_column} AS key,
            '{self.table_name}' AS source
        FROM {self.table_name}
        """
    
    def execute(self, artifacts_dir: str) -> List[Tuple[str, str, str]]:
        """
        Execute custom rule and extract mappings.
        
        Args:
            artifacts_dir: Path to artifacts directory
        
        Returns:
            List of tuples (value, key, source)
        """
        # This will be implemented in the full custom rules module
        # For now, return empty list as placeholder
        return []