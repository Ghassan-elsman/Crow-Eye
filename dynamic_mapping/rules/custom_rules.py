"""
Custom rules manager for the Dynamic Linking Intelligence Engine.

This module provides the CustomRule class and CustomRulesManager class
for creating, storing, and managing custom intelligence gathering rules.
"""

import os
import sqlite3
from typing import List, Optional, Tuple

from dynamic_mapping.rules.base import CustomRule


class CustomRulesManager:
    """
    Manages custom intelligence gathering rules.
    
    Provides CRUD operations for custom rules and stores them
    in the Crow_Intelligence.db database.
    
    Custom rules are created through GUI dropdown selections (db_name, table_name,
    value_column, key_column) and automatically generate SQL queries for execution.
    """
    
    def __init__(self, intelligence_db_path: str):
        """
        Initialize custom rules manager.
        
        Args:
            intelligence_db_path: Path to Crow_Intelligence.db
        """
        self.db_path = intelligence_db_path
        self._db_connection: Optional[sqlite3.Connection] = None
    
    def _get_connection(self) -> Optional[sqlite3.Connection]:
        """Get database connection, opening if necessary."""
        if not self._db_connection:
            if not os.path.exists(self.db_path):
                return None
            try:
                self._db_connection = sqlite3.connect(self.db_path)
                self._db_connection.row_factory = sqlite3.Row
            except Exception:
                return None
        return self._db_connection
    
    def create_rule(self, rule: CustomRule) -> bool:
        """
        Create and store a custom rule.
        
        Validates the rule before storing it in the database.
        
        Args:
            rule: CustomRule instance
        
        Returns:
            True if rule created successfully, False otherwise
        """
        # Validate rule
        is_valid, error_msg = rule.validate()
        if not is_valid:
            return False
        
        conn = self._get_connection()
        if not conn:
            return False
        
        try:
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
    
    def get_rule(self, name: str) -> Optional[CustomRule]:
        """
        Retrieve a custom rule by name.
        
        Args:
            name: Rule identifier
        
        Returns:
            CustomRule instance or None if not found
        """
        conn = self._get_connection()
        if not conn:
            return None
        
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM CustomRules WHERE name = ?", (name,))
            row = cursor.fetchone()
            
            if row:
                return CustomRule(
                    name=row['name'],
                    category=row['category'],
                    db_name=row['db_name'],
                    table_name=row['table_name'],
                    value_column=row['value_column'],
                    key_column=row['key_column'],
                    description=row['description']
                )
            return None
        except Exception:
            return None
    
    def list_rules(self) -> List[CustomRule]:
        """
        List all custom rules.
        
        Returns:
            List of CustomRule instances
        """
        conn = self._get_connection()
        if not conn:
            return []
        
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM CustomRules WHERE enabled = 1")
            rules = []
            
            for row in cursor.fetchall():
                rules.append(CustomRule(
                    name=row['name'],
                    category=row['category'],
                    db_name=row['db_name'],
                    table_name=row['table_name'],
                    value_column=row['value_column'],
                    key_column=row['key_column'],
                    description=row['description']
                ))
            
            return rules
        except Exception:
            return []
    
    def delete_rule(self, name: str) -> bool:
        """
        Delete a custom rule.
        
        Args:
            name: Rule identifier
        
        Returns:
            True if rule deleted successfully
        """
        conn = self._get_connection()
        if not conn:
            return False
        
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM CustomRules WHERE name = ?", (name,))
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            return False
    
    def get_rule_templates(self) -> List[dict]:
        """
        Get predefined rule templates for common patterns.
        
        Returns:
            List of template dictionaries with name, description, and query
        """
        return [
            {
                "name": "Registry Key to Value",
                "category": "Registry",
                "description": "Map registry keys to their values",
                "db_name": "registry_data.db",
                "table_name": "registry_values",
                "value_column": "key_path",
                "key_column": "value_data"
            },
            {
                "name": "File Path to Hash",
                "category": "Hash",
                "description": "Map file paths to their hash values",
                "db_name": "file_artifacts.db",
                "table_name": "file_hashes",
                "value_column": "file_path",
                "key_column": "hash_value"
            },
            {
                "name": "User SID to Full Name",
                "category": "User",
                "description": "Map SIDs to user full names",
                "db_name": "user_data.db",
                "table_name": "user_info",
                "value_column": "sid",
                "key_column": "full_name"
            }
        ]
    
    def cleanup(self) -> None:
        """Close database connection."""
        if self._db_connection:
            try:
                self._db_connection.close()
            except:
                pass
            self._db_connection = None