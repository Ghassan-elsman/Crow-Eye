"""
Query Builder for Semantic Rule Evaluation

Translates semantic rules into SQL queries for database-level evaluation.
This provides significant performance improvements over in-memory evaluation
by pushing computation to SQLite where it can leverage indexes and optimized
query execution.

Key Features:
- Translates semantic rule conditions to SQL WHERE clauses
- Supports parameterized queries to prevent SQL injection
- Handles cross-feather queries with JOIN on identity_key
- Provides intelligent fallback detection for untranslatable rules
- Registers custom REGEXP function for SQLite

Performance Benefits:
- Query-based evaluation: O(log N) with indexes vs O(N*M) in-memory
- Expected 5-10x improvement on large datasets
- Leverages SQLite's query optimizer and indexes

Thread Safety:
- QueryBuilder instances are thread-safe (no shared mutable state)
- REGEXP function must be registered per connection
- Each thread should have its own database connection

Usage:
    builder = QueryBuilder()
    
    # Check if rule can be translated
    if builder.can_translate_rule(rule):
        # Build and execute query
        query, params = builder.build_query_from_rule(rule)
        connection = sqlite3.connect(db_path)
        builder.setup_regexp_function(connection)
        cursor = connection.execute(query, params)
        results = cursor.fetchall()
    else:
        # Fall back to in-memory evaluation
        results = evaluate_in_memory(rule)
"""

import logging
import sqlite3
import re
import os
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class QueryBuilder:
    """
    Builds SQL queries from semantic rule conditions.
    
    Translates semantic rule conditions into SQL WHERE clauses with proper
    escaping and operator mapping. Supports parameterized queries to prevent
    SQL injection.
    
    This class handles the complexity of translating semantic rule conditions
    into safe, efficient SQL queries for query-based semantic evaluation.
    
    Supported Operators:
        - equals: Field equals exact value (=)
        - contains: Field contains substring (LIKE with wildcards)
        - regex: Field matches regular expression (REGEXP)
        - wildcard: Field is not null and not empty (IS NOT NULL AND != '')
        - greater_than: Field is greater than value (>)
        - less_than: Field is less than value (<)
        - greater_equal: Field is greater than or equal to value (>=)
        - less_equal: Field is less than or equal to value (<=)
        - not_equals: Field does not equal value (!=)
    
    Design Principles:
        1. Security: Always use parameterized queries (? placeholders)
        2. Performance: Generate efficient SQL that leverages indexes
        3. Correctness: Proper operator translation and logic combination
        4. Fallback: Return None for untranslatable rules
        5. Logging: Comprehensive logging for debugging
    
    Thread Safety:
        - QueryBuilder instances are stateless and thread-safe
        - No shared mutable state between method calls
        - Can be safely used across multiple threads
    
    Example:
        builder = QueryBuilder()
        
        # Single-feather query
        query, params = builder.build_query_from_rule(rule)
        # Returns: ("SELECT * FROM feather_data WHERE (name = ?)", ["chrome.exe"])
        
        # Cross-feather query
        query, params = builder.build_cross_feather_query(rule, feather_tables)
        # Returns: ("SELECT * FROM prefetch p JOIN browser b ON p.identity_key = b.identity_key WHERE ...", [...])
    """
    
    def __init__(self):
        """
        Initialize QueryBuilder with operator mappings.
        
        The operator_map defines how semantic rule operators are translated
        to SQL operators. This centralized mapping makes it easy to add new
        operators or modify existing translations.
        
        Operator Mappings:
            equals -> =          (exact match)
            contains -> LIKE     (substring match with % wildcards)
            regex -> REGEXP      (regular expression match, custom function)
            greater_than -> >    (numeric/string comparison)
            less_than -> <       (numeric/string comparison)
            greater_equal -> >=  (numeric/string comparison)
            less_equal -> <=     (numeric/string comparison)
            not_equals -> !=     (inequality)
            wildcard -> special  (IS NOT NULL AND != '', no parameter)
        
        Design Note:
            The wildcard operator is handled specially in translate_condition()
            because it doesn't require a parameter value.
        """
        self.operator_map = {
            'equals': '=',
            'contains': 'LIKE',
            'regex': 'REGEXP',
            'greater_than': '>',
            'less_than': '<',
            'greater_equal': '>=',
            'less_equal': '<=',
            'not_equals': '!='
        }
        
        logger.debug("QueryBuilder initialized with operator mappings")
    
    def can_translate_rule(self, rule) -> bool:
        """
        Check if rule can be translated to SQL.
        
        Args:
            rule: SemanticRule instance to check
            
        Returns:
            True if rule can be translated, False otherwise
            
        Cannot translate if:
            - Uses unsupported operators
            - Has complex nested logic (more than 2 levels)
            - References custom Python functions in conditions
            - Has more than 10 conditions (complexity threshold)
            - Has invalid field names or values
        
        Design Note:
            Conservative approach - if unsure, return False to trigger
            fallback to in-memory evaluation. This ensures correctness
            over performance optimization.
        
        Complexity Threshold:
            Rules with >10 conditions are considered too complex for
            query-based evaluation. This threshold balances:
            - Query complexity and execution time
            - SQL query size and readability
            - Risk of SQL injection or errors
            
            Most semantic rules have 1-5 conditions, so 10 is a safe limit.
        
        Example:
            rule = SemanticRule(
                conditions=[
                    SemanticCondition(feather_id="Prefetch", field_name="name", operator="equals", value="chrome.exe")
                ],
                logic_operator="AND"
            )
            builder.can_translate_rule(rule)  # Returns: True
            
            rule_complex = SemanticRule(
                conditions=[...],  # 15 conditions
                logic_operator="AND"
            )
            builder.can_translate_rule(rule_complex)  # Returns: False (too complex)
        """
        # Check if rule has conditions
        if not rule.conditions:
            logger.info(
                f"[SQL Translation] Query translation failed for rule '{rule.rule_id}': "
                f"No conditions defined. Fallback to in-memory evaluation."
            )
            return False
        
        # Check logic operator is supported (only AND/OR at single level)
        logic_operator = rule.logic_operator.upper()
        if logic_operator not in ['AND', 'OR']:
            logger.info(
                f"[SQL Translation] Query translation failed for rule '{rule.rule_id}': "
                f"Unsupported logic operator '{logic_operator}'. Fallback to in-memory evaluation."
            )
            return False
        
        # Check complexity threshold
        if len(rule.conditions) > 10:
            logger.info(
                f"[SQL Translation] Query translation failed for rule '{rule.rule_id}': "
                f"Too complex ({len(rule.conditions)} conditions > 10 threshold). "
                f"Fallback to in-memory evaluation."
            )
            return False
        
        # Check each condition
        for condition in rule.conditions:
            # Check if operator is supported
            if condition.operator not in self.operator_map and condition.operator != 'wildcard':
                logger.info(
                    f"[SQL Translation] Query translation failed for rule '{rule.rule_id}': "
                    f"Unsupported operator '{condition.operator}' in condition. "
                    f"Fallback to in-memory evaluation."
                )
                return False
            
            # Check for empty or invalid field names
            if not condition.field_name or not isinstance(condition.field_name, str):
                logger.info(
                    f"[SQL Translation] Query translation failed for rule '{rule.rule_id}': "
                    f"Invalid field name in condition. Fallback to in-memory evaluation."
                )
                return False
            
            # Check for custom Python functions in field names (e.g., "len(field_name)")
            # These would indicate programmatic evaluation rather than simple field comparison
            if '(' in condition.field_name or ')' in condition.field_name:
                logger.info(
                    f"[SQL Translation] Query translation failed for rule '{rule.rule_id}': "
                    f"Custom function in field name '{condition.field_name}'. "
                    f"Fallback to in-memory evaluation."
                )
                return False
            
            # Check for complex nested logic indicators in field names
            # (e.g., field names with dots that aren't simple feather.field references)
            if condition.field_name.count('.') > 1:
                logger.info(
                    f"[SQL Translation] Query translation failed for rule '{rule.rule_id}': "
                    f"Complex nested field reference '{condition.field_name}'. "
                    f"Fallback to in-memory evaluation."
                )
                return False
            
            # For operators that require a value, check that value is present and valid
            if condition.operator != 'wildcard':
                if condition.value is None:
                    logger.info(
                        f"[SQL Translation] Query translation failed for rule '{rule.rule_id}': "
                        f"Condition with operator '{condition.operator}' has no value. "
                        f"Fallback to in-memory evaluation."
                    )
                    return False
                
                # Check for callable values (custom Python functions)
                if callable(condition.value):
                    logger.info(
                        f"[SQL Translation] Query translation failed for rule '{rule.rule_id}': "
                        f"Callable value (custom function) detected. "
                        f"Fallback to in-memory evaluation."
                    )
                    return False
        
        # All checks passed - rule can be translated
        logger.debug(f"Rule '{rule.rule_id}' can be translated to SQL")
        return True
    
    def setup_regexp_function(self, connection: sqlite3.Connection):
        """
        Setup REGEXP function for SQLite connection.
        
        Args:
            connection: SQLite database connection
            
        Design Note:
            SQLite doesn't have REGEXP by default. This method adds a custom
            REGEXP function using Python's re module. Must be called once per
            connection before executing regex queries.
        
        Implementation:
            Creates a custom function that:
            1. Takes pattern and value as arguments
            2. Uses Python's re.search() for matching
            3. Returns True/False for SQL WHERE clause
            4. Handles None values and invalid patterns gracefully
            5. Uses case-insensitive matching (re.IGNORECASE)
        
        Thread Safety:
            Each thread must call this on its own connection.
            SQLite connections are not thread-safe.
        
        Error Handling:
            - Invalid regex patterns return False (no match)
            - None values return False (no match)
            - Exceptions are caught and logged
        
        Example:
            connection = sqlite3.connect('feather.db')
            builder.setup_regexp_function(connection)
            cursor = connection.execute(
                "SELECT * FROM feather_data WHERE name REGEXP ?",
                ["chrome.*"]
            )
        """
        def regexp(pattern, value):
            """
            Custom REGEXP function for SQLite.
            
            Args:
                pattern: Regular expression pattern
                value: Value to match against
                
            Returns:
                True if pattern matches value, False otherwise
            """
            if pattern is None or value is None:
                return False
            
            try:
                # Convert to strings and perform case-insensitive match
                return re.search(str(pattern), str(value), re.IGNORECASE) is not None
            except re.error as e:
                # Invalid regex pattern (Requirement 9.6)
                logger.error(
                    f"[SQL Execution] REGEXP function error: Invalid regex pattern '{pattern}'. "
                    f"Error: {e}. This condition will not match."
                )
                return False
            except Exception as e:
                # Unexpected error (Requirement 9.6)
                logger.error(
                    f"[SQL Execution] REGEXP function unexpected error: {e}. "
                    f"Pattern: '{pattern}', Value: '{value}'"
                )
                return False
        
        try:
            connection.create_function("REGEXP", 2, regexp)
            logger.debug("REGEXP function registered with SQLite connection")
        except Exception as e:
            # Use error level for SQL execution failures (Requirement 9.6)
            logger.error(
                f"[SQL Execution] Failed to register REGEXP function with SQLite: {e}. "
                f"Regex-based queries will not work."
            )

    
    def translate_condition(self, condition) -> Optional[Tuple[str, Any]]:
        """
        Translate single condition to SQL WHERE clause.
        
        Args:
            condition: SemanticCondition instance to translate
            
        Returns:
            Tuple of (WHERE clause string, parameter value), or None if cannot translate
            
        Operator Mapping:
            equals -> field = ?
            contains -> field LIKE ?  (value wrapped with %)
            regex -> field REGEXP ?
            wildcard -> field IS NOT NULL AND field != ''  (no parameter)
            greater_than -> field > ?
            less_than -> field < ?
            greater_equal -> field >= ?
            less_equal -> field <= ?
            not_equals -> field != ?
        
        Design Note:
            Uses parameterized queries (? placeholders) for security.
            Special handling for 'contains' operator (adds % wildcards).
            Special handling for 'wildcard' operator (no parameter needed).
        
        Security:
            All values are passed as parameters, never concatenated into SQL.
            This prevents SQL injection attacks.
        
        Performance:
            Parameterized queries allow SQLite to cache query plans,
            improving performance for repeated queries.
        
        Example:
            condition = SemanticCondition(
                feather_id="Prefetch",
                field_name="name",
                operator="equals",
                value="chrome.exe"
            )
            builder.translate_condition(condition)
            # Returns: ("name = ?", "chrome.exe")
            
            condition = SemanticCondition(
                feather_id="Prefetch",
                field_name="path",
                operator="contains",
                value="windows"
            )
            builder.translate_condition(condition)
            # Returns: ("path LIKE ?", "%windows%")
            
            condition = SemanticCondition(
                feather_id="Prefetch",
                field_name="eventid",
                operator="wildcard",
                value="*"
            )
            builder.translate_condition(condition)
            # Returns: ("eventid IS NOT NULL AND eventid != ''", None)
        """
        operator = condition.operator
        field_name = condition.field_name
        value = condition.value
        
        # Handle wildcard operator specially - no parameter needed
        if operator == 'wildcard':
            where_clause = f"{field_name} IS NOT NULL AND {field_name} != ''"
            return (where_clause, None)
        
        # Check if operator is supported
        if operator not in self.operator_map:
            logger.info(
                f"[SQL Translation] Query translation failed: "
                f"Unsupported operator '{operator}' for field '{field_name}'. "
                f"Fallback to in-memory evaluation."
            )
            return None
        
        sql_operator = self.operator_map[operator]
        
        # Handle contains operator - add % wildcards
        if operator == 'contains':
            param_value = f"%{value}%"
            where_clause = f"{field_name} {sql_operator} ?"
            return (where_clause, param_value)
        
        # Standard operators with parameterized value
        where_clause = f"{field_name} {sql_operator} ?"
        return (where_clause, value)

    
    def combine_conditions(self, clauses: List[Tuple[str, Any]], logic_operator: str) -> Tuple[str, List[Any]]:
        """
        Combine WHERE clauses with AND/OR logic.
        
        Args:
            clauses: List of (WHERE clause, parameter) tuples
            logic_operator: "AND" or "OR"
            
        Returns:
            Tuple of (combined WHERE clause, parameters list)
        
        Design Note:
            Properly handles parentheses for complex logic.
            Flattens parameter lists for SQLite parameter binding.
            Filters out None parameters (from wildcard operator).
        
        Parentheses:
            Each clause is wrapped in parentheses to ensure correct
            precedence when combining with AND/OR operators.
            
            Without parentheses:
                field1 = ? AND field2 LIKE ? OR field3 > ?
                Could be interpreted as: (field1 = ? AND field2 LIKE ?) OR field3 > ?
                Or as: field1 = ? AND (field2 LIKE ? OR field3 > ?)
            
            With parentheses:
                (field1 = ?) AND (field2 LIKE ?) OR (field3 > ?)
                Clear precedence, no ambiguity
        
        Parameter Handling:
            - Wildcard operator returns None as parameter
            - None parameters are filtered out
            - Remaining parameters are flattened into a list
            - Order is preserved for SQLite parameter binding
        
        Example:
            clauses = [
                ("field1 = ?", "value1"),
                ("field2 LIKE ?", "%value2%"),
                ("field3 IS NOT NULL AND field3 != ''", None)
            ]
            logic_operator = "AND"
            
            builder.combine_conditions(clauses, logic_operator)
            # Returns: (
            #     "(field1 = ?) AND (field2 LIKE ?) AND (field3 IS NOT NULL AND field3 != '')",
            #     ["value1", "%value2%"]
            # )
        """
        if not clauses:
            return ("", [])
        
        # Separate WHERE clauses and parameters
        where_parts = []
        params = []
        
        for clause, param in clauses:
            # Wrap each clause in parentheses for proper precedence
            where_parts.append(f"({clause})")
            
            # Only add parameter if it's not None (wildcard operator has no parameter)
            if param is not None:
                params.append(param)
        
        # Join clauses with the logic operator
        combined_where = f" {logic_operator} ".join(where_parts)
        
        return (combined_where, params)

    
    def build_query_from_rule(self, rule, table_name: str = "feather_data") -> Optional[Tuple[str, List[Any]]]:
        """
        Build complete SQL query from semantic rule.
        
        Args:
            rule: SemanticRule instance to translate
            table_name: Name of table to query (default: "feather_data")
            
        Returns:
            Tuple of (SQL query string, parameters list), or None if cannot translate
        
        Design Note:
            Returns parameterized query to prevent SQL injection.
            Uses ? placeholders for SQLite parameter binding.
            Returns None if any condition fails translation (triggers fallback).
        
        Query Structure:
            SELECT * FROM {table_name} WHERE {combined_conditions}
            
            Example:
                SELECT * FROM feather_data WHERE (name = ?) AND (run_count > ?)
        
        Fallback Trigger:
            Returns None if:
            - Rule has no conditions
            - Any condition cannot be translated
            - Logic operator is unsupported
            - WHERE clause generation fails
            
            This triggers fallback to in-memory evaluation.
        
        Performance:
            Query-based evaluation is significantly faster than in-memory:
            - Leverages SQLite indexes
            - Optimized query execution
            - Reduced data transfer (only matching rows)
            - Expected 5-10x improvement on large datasets
        
        Example:
            rule = SemanticRule(
                rule_id="rule1",
                conditions=[
                    SemanticCondition(
                        feather_id="Prefetch",
                        field_name="executable_name",
                        operator="equals",
                        value="chrome.exe"
                    ),
                    SemanticCondition(
                        feather_id="Prefetch",
                        field_name="run_count",
                        operator="greater_than",
                        value="5"
                    )
                ],
                logic_operator="AND"
            )
            
            builder.build_query_from_rule(rule)
            # Returns: (
            #     "SELECT * FROM feather_data WHERE (executable_name = ?) AND (run_count > ?)",
            #     ["chrome.exe", "5"]
            # )
        """
        if not rule.conditions:
            logger.info(
                f"[SQL Translation] Query translation failed for rule '{rule.rule_id}': "
                f"No conditions defined. Fallback to in-memory evaluation."
            )
            return None
        
        # Translate all conditions
        translated_clauses = []
        for condition in rule.conditions:
            clause = self.translate_condition(condition)
            if clause is None:
                # Cannot translate this condition - return None to trigger fallback
                logger.info(
                    f"[SQL Translation] Query translation failed for rule '{rule.rule_id}': "
                    f"Cannot translate condition for field '{condition.field_name}' "
                    f"with operator '{condition.operator}'. Fallback to in-memory evaluation."
                )
                return None
            translated_clauses.append(clause)
        
        # Combine conditions using rule's logic operator
        logic_operator = rule.logic_operator.upper()
        if logic_operator not in ['AND', 'OR']:
            logger.info(
                f"[SQL Translation] Query translation failed for rule '{rule.rule_id}': "
                f"Unsupported logic operator '{logic_operator}'. Fallback to in-memory evaluation."
            )
            return None
        
        where_clause, params = self.combine_conditions(translated_clauses, logic_operator)
        
        if not where_clause:
            logger.info(
                f"[SQL Translation] Query translation failed for rule '{rule.rule_id}': "
                f"Failed to build WHERE clause. Fallback to in-memory evaluation."
            )
            return None
        
        # Build complete SELECT query
        query = f"SELECT * FROM {table_name} WHERE {where_clause}"
        
        logger.debug(
            f"Built query for rule '{rule.rule_id}': {query} with {len(params)} parameters"
        )
        
        return (query, params)

    
    def build_cross_feather_query(self, rule, feather_tables: Dict[str, str]) -> Optional[Tuple[str, List[Any]]]:
        """
        Build SQL query for cross-feather rules using identity_key joins.
        
        Args:
            rule: SemanticRule instance to translate
            feather_tables: Dict mapping feather_id to table name
                           Example: {"Prefetch": "prefetch_data", "BrowserHistory": "browser_history_data"}
            
        Returns:
            Tuple of (SQL query with JOINs, parameters list), or None if cannot translate
        
        Design Note:
            Cross-feather queries join multiple feather tables on identity_key.
            This allows correlating records from different artifact types that
            share the same identity (e.g., same application name).
        
        Query Structure:
            SELECT * FROM {table1} t1
            JOIN {table2} t2 ON t1.identity_key = t2.identity_key
            JOIN {table3} t3 ON t1.identity_key = t3.identity_key
            WHERE {combined_conditions}
        
        Identity Key:
            The identity_key column links records across feathers.
            Format: "type:normalized_value" (e.g., "name:chrome.exe")
            
            All feather tables must have an identity_key column for
            cross-feather queries to work.
        
        Table Aliases:
            Each table gets a short alias (t1, t2, t3, ...) to:
            - Simplify query syntax
            - Avoid ambiguity in field references
            - Improve readability
        
        Field Qualification:
            Conditions are qualified with table aliases:
            - condition.feather_id maps to table alias
            - field_name becomes alias.field_name
            - Example: "Prefetch.name" becomes "t1.name"
        
        Performance:
            Cross-feather queries can be slower than single-feather queries
            due to JOIN operations. However, they're still much faster than
            in-memory evaluation because:
            - SQLite optimizes JOIN operations
            - identity_key should be indexed
            - Only matching rows are transferred
        
        Example:
            rule = SemanticRule(
                rule_id="rule1",
                conditions=[
                    SemanticCondition(
                        feather_id="Prefetch",
                        field_name="name",
                        operator="equals",
                        value="chrome.exe"
                    ),
                    SemanticCondition(
                        feather_id="BrowserHistory",
                        field_name="url",
                        operator="wildcard",
                        value="*"
                    )
                ],
                logic_operator="AND"
            )
            
            feather_tables = {
                "Prefetch": "prefetch_data",
                "BrowserHistory": "browser_history_data"
            }
            
            builder.build_cross_feather_query(rule, feather_tables)
            # Returns: (
            #     "SELECT * FROM prefetch_data t1 "
            #     "JOIN browser_history_data t2 ON t1.identity_key = t2.identity_key "
            #     "WHERE (t1.name = ?) AND (t2.url IS NOT NULL AND t2.url != '')",
            #     ["chrome.exe"]
            # )
        """
        if not rule.conditions:
            logger.warning(f"Rule '{rule.rule_id}' has no conditions")
            return None
        
        # Identify feathers referenced in rule conditions
        feather_ids = set()
        for condition in rule.conditions:
            # Skip special "_identity" feather (used for identity-level conditions)
            if condition.feather_id != "_identity":
                feather_ids.add(condition.feather_id)
        
        # Check if we have table names for all feathers
        missing_feathers = feather_ids - set(feather_tables.keys())
        if missing_feathers:
            logger.warning(
                f"Missing table names for feathers: {missing_feathers} in rule '{rule.rule_id}'"
            )
            return None
        
        # Single feather - use simple query
        if len(feather_ids) <= 1:
            # Use build_query_from_rule for single-feather queries
            if len(feather_ids) == 1:
                feather_id = list(feather_ids)[0]
                table_name = feather_tables[feather_id]
                return self.build_query_from_rule(rule, table_name)
            else:
                # No feathers (all conditions are identity-level)
                logger.warning(
                    f"Rule '{rule.rule_id}' has no feather-specific conditions"
                )
                return None
        
        # Multiple feathers - build cross-feather query with JOINs
        feather_list = sorted(list(feather_ids))  # Sort for consistent ordering
        
        # Create table aliases (t1, t2, t3, ...)
        feather_to_alias = {feather_id: f"t{i+1}" for i, feather_id in enumerate(feather_list)}
        
        # Build FROM clause with first table
        first_feather = feather_list[0]
        first_table = feather_tables[first_feather]
        first_alias = feather_to_alias[first_feather]
        from_clause = f"{first_table} {first_alias}"
        
        # Build JOIN clauses for remaining tables
        join_clauses = []
        for feather_id in feather_list[1:]:
            table_name = feather_tables[feather_id]
            alias = feather_to_alias[feather_id]
            join_clause = f"JOIN {table_name} {alias} ON {first_alias}.identity_key = {alias}.identity_key"
            join_clauses.append(join_clause)
        
        # Translate conditions with table aliases
        translated_clauses = []
        for condition in rule.conditions:
            # Skip identity-level conditions (no table reference)
            if condition.feather_id == "_identity":
                logger.debug(
                    f"Skipping identity-level condition in cross-feather query: "
                    f"{condition.field_name}"
                )
                continue
            
            # Get table alias for this feather
            if condition.feather_id not in feather_to_alias:
                logger.warning(
                    f"Condition references unknown feather '{condition.feather_id}' "
                    f"in rule '{rule.rule_id}'"
                )
                return None
            
            alias = feather_to_alias[condition.feather_id]
            
            # Create a modified condition with qualified field name
            # We need to qualify the field name with the table alias
            qualified_field_name = f"{alias}.{condition.field_name}"
            
            # Translate condition with qualified field name
            # We'll temporarily modify the condition's field_name
            original_field_name = condition.field_name
            condition.field_name = qualified_field_name
            
            clause = self.translate_condition(condition)
            
            # Restore original field name
            condition.field_name = original_field_name
            
            if clause is None:
                logger.warning(
                    f"Cannot translate condition for field '{original_field_name}' "
                    f"with operator '{condition.operator}' in rule '{rule.rule_id}'"
                )
                return None
            
            translated_clauses.append(clause)
        
        if not translated_clauses:
            logger.warning(
                f"No translatable conditions in cross-feather rule '{rule.rule_id}'"
            )
            return None
        
        # Combine conditions using rule's logic operator
        logic_operator = rule.logic_operator.upper()
        if logic_operator not in ['AND', 'OR']:
            logger.warning(
                f"Unsupported logic operator '{logic_operator}' in rule '{rule.rule_id}'"
            )
            return None
        
        where_clause, params = self.combine_conditions(translated_clauses, logic_operator)
        
        if not where_clause:
            logger.warning(
                f"Failed to build WHERE clause for cross-feather rule '{rule.rule_id}'"
            )
            return None
        
        # Build complete cross-feather query
        query_parts = [
            "SELECT *",
            f"FROM {from_clause}"
        ]
        
        # Add JOIN clauses
        query_parts.extend(join_clauses)
        
        # Add WHERE clause
        query_parts.append(f"WHERE {where_clause}")
        
        query = " ".join(query_parts)
        
        logger.debug(
            f"Built cross-feather query for rule '{rule.rule_id}': "
            f"{query} with {len(params)} parameters"
        )
        
        return (query, params)

    
    @staticmethod
    def get_feather_table_name(feather_path: str) -> Optional[str]:
        """
        Get the data table name from a feather database.
        
        Args:
            feather_path: Path to feather database file
            
        Returns:
            Name of the data table, or None if cannot be determined
        
        Design Note:
            Feather databases can have different table names depending on how they
            were created. This method determines the actual table name by:
            1. Checking if 'feather_data' table exists (preferred)
            2. Using the first non-metadata table found
            
            This matches the logic in FeatherLoader.connect() to ensure consistency.
        
        Table Selection Logic:
            - Prefer 'feather_data' if it exists (standard table name)
            - Otherwise use first data table (excluding 'feather_metadata')
            - System tables (sqlite_*) are automatically excluded by SQLite
        
        Error Handling:
            Returns None if:
            - File doesn't exist
            - Cannot connect to database
            - No data tables found
            - Any database error occurs
        
        Example:
            table_name = QueryBuilder.get_feather_table_name('/path/to/prefetch.db')
            if table_name:
                query, params = builder.build_query_from_rule(rule, table_name)
        """
        if not feather_path or not os.path.exists(feather_path):
            logger.debug(f"Feather path does not exist: {feather_path}")
            return None
        
        try:
            connection = sqlite3.connect(feather_path)
            cursor = connection.cursor()
            
            # Get all tables except feather_metadata
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'feather_metadata'"
            )
            data_tables = [row[0] for row in cursor.fetchall()]
            
            connection.close()
            
            if not data_tables:
                logger.debug(f"No data tables found in {feather_path}")
                return None
            
            # Prefer 'feather_data' if it exists
            if 'feather_data' in data_tables:
                logger.debug(f"Using standard table name 'feather_data' for {feather_path}")
                return 'feather_data'
            
            # Otherwise use first data table
            table_name = data_tables[0]
            logger.debug(f"Using data table '{table_name}' for {feather_path}")
            return table_name
            
        except sqlite3.Error as e:
            logger.warning(f"Error getting table name from {feather_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting table name from {feather_path}: {e}")
            return None
