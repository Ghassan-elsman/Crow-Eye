"""
Forensic Search Service

This module provides a service layer for forensic database search operations,
wrapping Crow-eye's SearchEngine with natural language query support.

The ForensicSearchService integrates with Crow-eye's SearchEngine from
data/search_engine.py to provide:
- Direct search with SearchConfig objects
- Natural language query conversion to SearchConfig
- Regex pattern detection
- Case sensitivity detection
- Search term extraction from natural language

"""

import re
import logging
from typing import Optional, List, Dict
from dataclasses import dataclass

from data.search_engine import DatabaseSearchEngine, SearchConfig, SearchResults
from data.database_manager import DatabaseManager


class ForensicSearchService:
    """
    Service layer for forensic database search.
    
    Wraps Crow-eye's DatabaseSearchEngine to provide:
    - Direct search execution with SearchConfig
    - Natural language query conversion
    - Intelligent parameter detection (regex, case sensitivity)
    """
    
    def __init__(self, database_manager: DatabaseManager):
        """
        Initialize the forensic search service.
        
        Args:
            database_manager: DatabaseManager instance for database access
        """
        self.database_manager = database_manager
        self.search_engine = DatabaseSearchEngine(database_manager)
        self.logger = logging.getLogger(__name__)
    
    def search(self, search_config: SearchConfig) -> SearchResults:
        """
        Execute search across forensic databases.
        
        Args:
            search_config: SearchConfig with parameters:
                - search_term: str - The term to search for
                - tables: Optional[List[str]] - Tables to search (None for all)
                - columns: Optional[Dict[str, List[str]]] - Columns to search per table
                - case_sensitive: bool - Whether to perform case-sensitive search
                - exact_match: bool - Whether to match exact term (no wildcards)
                - use_regex: bool - Whether to interpret search_term as regex
                - max_results: int - Maximum total results to return
                - timeout_seconds: float - Maximum time to spend searching
        
        Returns:
            SearchResults with:
                - results: Dict[str, List[SearchResult]] - Results by table
                - total_matches: int - Total number of matches
                - search_time: float - Time taken for search
                - truncated: bool - Whether results were truncated
                - tables_searched: int - Number of tables searched
                - tables_with_results: int - Number of tables with results
        """
        self.logger.info(
            f"Executing search: term='{search_config.search_term}', "
            f"regex={search_config.use_regex}, case_sensitive={search_config.case_sensitive}"
        )
        
        try:
            results = self.search_engine.search(
                search_term=search_config.search_term,
                tables=search_config.tables,
                columns=search_config.columns,
                case_sensitive=search_config.case_sensitive,
                exact_match=search_config.exact_match,
                max_results=search_config.max_results,
                timeout_seconds=search_config.timeout_seconds
            )
            
            self.logger.info(
                f"Search completed: {results.total_matches} matches in "
                f"{results.search_time:.2f}s across {results.tables_with_results} tables"
            )
            
            return results
            
        except Exception as e:
            self.logger.error(f"Search failed: {e}", exc_info=True)
            raise
    
    def search_natural_language(self, query: str) -> SearchResults:
        """
        Convert natural language query to SearchConfig and execute.
        
        This method analyzes the natural language query to:
        - Extract the search term
        - Detect regex intent (patterns like *.exe, [0-9]+, etc.)
        
        Examples:
            "Find all chrome.exe executions" 
                -> SearchConfig(search_term="chrome.exe", use_regex=False)
            
            "Search for *.exe files"
                -> SearchConfig(search_term=".*\\.exe", use_regex=True)
            
            "Case-sensitive search for Password"
                -> SearchConfig(search_term="Password", case_sensitive=True)
        
        Args:
            query: Natural language search query
            
        Returns:
            SearchResults from the executed search
        """
        self.logger.info(f"Processing natural language query: '{query}'")
        
        # Parse natural language to extract search parameters
        search_term = self._extract_search_term(query)
        use_regex = self._detect_regex_intent(query)
        case_sensitive = self._detect_case_sensitivity(query)
        
        # Create search configuration
        config = SearchConfig(
            search_term=search_term,
            use_regex=use_regex,
            case_sensitive=case_sensitive,
            max_results=1000
        )
        
        self.logger.debug(
            f"Converted to SearchConfig: term='{search_term}', "
            f"regex={use_regex}, case_sensitive={case_sensitive}"
        )
        
        return self.search(config)
    
    def _extract_search_term(self, query: str) -> str:
        """
        Extract the search term from a natural language query.
        
        This method identifies the core search term by:
        - Removing common query prefixes (find, search, look for, etc.)
        - Extracting quoted strings as exact terms
        - Identifying file names, paths, and technical terms
        
        Examples:
            "Find all chrome.exe" -> "chrome.exe"
            "Search for 'malicious.dll'" -> "malicious.dll"
            "Look for files matching *.exe" -> "*.exe"
        
        Args:
            query: Natural language query string
            
        Returns:
            Extracted search term
        """
        # Remove common query prefixes
        query_lower = query.lower()
        prefixes = [
            "find all", "find", "search for", "search", "look for", "look up",
            "show me", "show", "get", "list", "display"
        ]
        
        cleaned = query
        for prefix in prefixes:
            if query_lower.startswith(prefix):
                cleaned = query[len(prefix):].strip()
                break
        
        # Extract quoted strings (exact terms)
        quoted_match = re.search(r'["\']([^"\']+)["\']', cleaned)
        if quoted_match:
            return quoted_match.group(1)
        
        # Extract potential Windows paths
        path_match = re.search(r'\b[A-Za-z]:\\[\w\\\.\-\s]+', cleaned)
        if path_match:
            return path_match.group(0).strip()

        # Extract MD5/SHA hashes
        hash_match = re.search(r'\b[a-fA-F0-9]{32,64}\b', cleaned)
        if hash_match:
            return hash_match.group(0)

        # Extract file patterns (*.exe, *.dll, etc.)
        file_pattern_match = re.search(r'\*\.\w+', cleaned)
        if file_pattern_match:
            return file_pattern_match.group(0)
        
        # Extract file names (word.extension)
        filename_match = re.search(r'\b[\w-]+\.\w+\b', cleaned)
        if filename_match:
            return filename_match.group(0)
        
        # Extract technical terms (alphanumeric with underscores, hyphens)
        technical_match = re.search(r'\b[\w-]+\b', cleaned)
        if technical_match:
            return technical_match.group(0)
        
        # Fallback: return cleaned query
        return cleaned.strip()
    
    def _detect_regex_intent(self, query: str) -> bool:
        """
        Detect if the query intends to use regex patterns.
        
        This method looks for indicators that the user wants regex matching:
        - Wildcard patterns (*.exe, file*.txt)
        - Regex keywords (regex, pattern, matching)
        - Regex special characters ([0-9], \\d, \\w, etc.)
        
        Examples:
            "Find *.exe files" -> True
            "Search for pattern [0-9]+" -> True
            "Find chrome.exe" -> False
        
        Args:
            query: Natural language query string
            
        Returns:
            True if regex intent detected, False otherwise
        """
        query_lower = query.lower()
        
        # Check for regex keywords
        regex_keywords = ["regex", "pattern", "matching", "matches", "wildcard"]
        if any(keyword in query_lower for keyword in regex_keywords):
            return True
        
        # Check for wildcard patterns
        if "*" in query or "?" in query:
            return True
        
        # Check for regex special characters
        regex_chars = [r"\d", r"\w", r"\s", "[", "]", "(", ")", "|", "^", "$"]
        if any(char in query for char in regex_chars):
            return True
        
        return False
    
    def _detect_case_sensitivity(self, query: str) -> bool:
        """
        Detect if the query requires case-sensitive search.
        
        This method looks for indicators that the user wants case-sensitive matching:
        - Explicit keywords (case-sensitive, case sensitive, exact case)
        - Mixed case in quoted terms
        
        Examples:
            "Case-sensitive search for Password" -> True
            "Find 'MyFile.txt' exact case" -> True
            "Find chrome.exe" -> False
        
        Args:
            query: Natural language query string
            
        Returns:
            True if case sensitivity detected, False otherwise
        """
        query_lower = query.lower()
        
        # Check for case sensitivity keywords
        case_keywords = [
            "case-sensitive", "case sensitive", "exact case", 
            "case matters", "preserve case"
        ]
        if any(keyword in query_lower for keyword in case_keywords):
            return True
        
        # Check for mixed case in quoted strings (indicates intent)
        quoted_match = re.search(r'["\']([^"\']+)["\']', query)
        if quoted_match:
            quoted_text = quoted_match.group(1)
            # If quoted text has mixed case, assume case sensitivity
            if quoted_text != quoted_text.lower() and quoted_text != quoted_text.upper():
                return True
        
        return False
