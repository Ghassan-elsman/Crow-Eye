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
import time
import logging
from pathlib import Path
from typing import Optional, List, Dict, Union
from dataclasses import dataclass

from data.search_engine import DatabaseSearchEngine, SearchConfig, SearchResults
from data.database_manager import DatabaseManager
from data.base_loader import BaseDataLoader


class ForensicSearchService:
    """
    Service layer for forensic database search.
    
    Wraps Crow-eye's DatabaseSearchEngine to provide:
    - Direct search execution with SearchConfig
    - Natural language query conversion
    - Intelligent parameter detection (regex, case sensitivity)
    """
    
    def __init__(self, database_manager: Union[DatabaseManager, str, Path]):
        """
        Initialize the forensic search service.

        Args:
            database_manager: Either the case artifacts DIRECTORY (str/Path) — the way
                the app constructs this service — or a ready ``DatabaseManager``. Accept
                both so existing call sites (``ForensicSearchService(artifacts_dir)``)
                keep working while search now spans every discovered database.
        """
        if isinstance(database_manager, (str, Path)):
            self.artifacts_dir = Path(database_manager)
            self.database_manager = DatabaseManager(str(database_manager))
        else:
            self.database_manager = database_manager
            self.artifacts_dir = Path(getattr(database_manager, "case_directory", "."))
        self.logger = logging.getLogger(__name__)

    def search(self, search_config: SearchConfig) -> SearchResults:
        """
        Execute a text search across ALL discovered forensic databases in the case.

        Historically this wrapped a single-database ``DatabaseSearchEngine``, but the
        engine expects a per-database ``BaseDataLoader`` while the service is handed the
        case directory — so the old code searched nothing. We now enumerate every
        accessible database (``DatabaseManager.discover_databases`` — which already
        excludes Correlation feathers and includes imported evidence) and run the engine
        against each, tagging every hit with its source ``database`` and merging into one
        ``SearchResults``.

        Returns a ``SearchResults`` (``results`` keyed by table; each ``SearchResult``
        gains a ``database`` attribute for provenance).
        """
        self.logger.info(
            f"Executing cross-database search: term='{search_config.search_term}', "
            f"case_sensitive={search_config.case_sensitive}"
        )
        agg = SearchResults(search_term=search_config.search_term)
        start = time.time()

        try:
            db_infos = self.database_manager.discover_databases()
        except Exception as e:
            self.logger.error(f"Search DB discovery failed: {e}", exc_info=True)
            return agg

        usable = [d for d in db_infos if getattr(d, "accessible", False) and getattr(d, "exists", False)]
        if not usable:
            return agg

        max_total = search_config.max_results or 1000
        per_db = max(50, max_total // len(usable))

        for info in usable:
            if agg.total_matches >= max_total:
                agg.truncated = True
                break
            loader = BaseDataLoader(str(info.path))
            try:
                if not loader.connect(read_only=True):
                    continue
                engine = DatabaseSearchEngine(loader, enable_cache=False)
                res = engine.search(
                    search_term=search_config.search_term,
                    tables=search_config.tables,
                    columns=search_config.columns,
                    case_sensitive=search_config.case_sensitive,
                    exact_match=search_config.exact_match,
                    max_results=per_db,
                    timeout_seconds=search_config.timeout_seconds,
                )
            except Exception as e:
                self.logger.debug(f"Search skipped for {info.name}: {e}")
                continue
            finally:
                try:
                    loader.disconnect()
                except Exception:
                    pass

            agg.tables_searched += getattr(res, "tables_searched", 0)
            for table_name, table_results in (res.results or {}).items():
                for sr in table_results:
                    try:
                        setattr(sr, "database", info.name)
                    except Exception:
                        pass
                    agg.add_result(sr)  # buckets by table + increments total_matches
                    if agg.total_matches >= max_total:
                        agg.truncated = True
                        break
                if agg.total_matches >= max_total:
                    break

        agg.tables_with_results = len(agg.results)
        agg.search_time = time.time() - start
        self.logger.info(
            f"Search completed: {agg.total_matches} matches in {agg.search_time:.2f}s "
            f"across {agg.tables_with_results} tables / {len(usable)} databases"
        )
        return agg
    
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
