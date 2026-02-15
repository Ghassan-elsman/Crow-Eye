"""
SQL-Based Semantic Mapper

This module implements semantic mapping using proper regex pattern matching.

Approach:
1. Create semantic_rules table with full regex patterns
2. Load all matches from database
3. Apply regex patterns to matched_application field
4. Update matches with semantic data

Key Fix: Uses proper regex matching instead of substring search to avoid over-matching.
"""

import sqlite3
import json
import time
import logging
import os
from typing import Dict, List, Any, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


class SQLSemanticMapper:
    """
    SQL-based semantic mapper that uses proper regex pattern matching.
    
    This fixes the over-matching issue by:
    - Keeping full regex patterns intact (not splitting into terms)
    - Using re.search() for proper regex matching
    - Matching against the actual field value (matched_application)
    - Not using substring search which caused false positives
    """
    
    def __init__(self, database_path: str, execution_id: int, config: Dict[str, Any] = None, config_path: Optional[str] = None):
        """
        Initialize SQL semantic mapper.
        
        Args:
            database_path: Path to correlation database
            execution_id: Execution ID to process
            config: Optional configuration dictionary (takes precedence over config_path)
            config_path: Optional path to configuration JSON file
        """
        self.database_path = database_path
        self.execution_id = execution_id
        self.conn = None
        self.cursor = None
        
        # Load configuration from file or use provided config
        if config is not None:
            self.config = config
        else:
            self.config = self._load_config(config_path)
        
        # Validate configuration and log warnings
        warnings = self._validate_config(self.config)
        for warning in warnings:
            logger.warning(f"Configuration validation warning: {warning}")
        
        # Pattern caching for performance
        self._pattern_cache = {}  # pattern_str -> compiled re.Pattern
        self._pattern_cache_access_order = []  # Track access order for LRU
        self._pattern_cache_max_size = self.config.get('pattern_cache_size', 10000)
        
        # Debug logging for false positive debugging
        self._debug_log_file = None
        self._init_debug_logging()
    
    def connect(self):
        """Connect to database with timeout."""
        # Use a longer timeout to avoid lock issues
        self.conn = sqlite3.connect(self.database_path, timeout=30.0)
        self.cursor = self.conn.cursor()
        
        # Enable WAL mode for better concurrency
        self.cursor.execute("PRAGMA journal_mode=WAL")
        
        # Optimize for bulk operations
        self.cursor.execute("PRAGMA synchronous=NORMAL")
        self.cursor.execute("PRAGMA cache_size=10000")
    
    def close(self):
        """Close database connection and debug log file."""
        if self.conn:
            self.conn.close()
        self._close_debug_log()
    
    def _load_config(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Load configuration from JSON file with defaults.
        
        Args:
            config_path: Optional path to configuration JSON file.
                        If None, uses default path: configs/semantic_mapping_config.json
        
        Returns:
            Configuration dictionary with defaults applied
        """
        # Default configuration values
        default_config = {
            'batch_size': 1000,
            'worker_count': 4,
            'min_indicators_default': 1,
            'pattern_cache_size': 10000,
            'max_pattern_matches': 100,
            'debug_mode': False,
            'log_file_path': 'correlation_engine/semantic_mapping_debug.log'
        }
        
        # If no config path provided, use default
        if config_path is None:
            config_path = 'configs/semantic_mapping_config.json'
        
        # Try to load configuration from file
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    loaded_config = json.load(f)
                    # Merge with defaults (loaded values take precedence)
                    config = {**default_config, **loaded_config}
                    logger.info(f"Loaded configuration from {config_path}")
                    return config
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse configuration file {config_path}: {e}. Using defaults.")
                return default_config
            except Exception as e:
                logger.warning(f"Failed to load configuration file {config_path}: {e}. Using defaults.")
                return default_config
        else:
            logger.info(f"Configuration file {config_path} not found. Using defaults.")
            return default_config
    
    def _validate_config(self, config: Dict[str, Any]) -> List[str]:
        """
        Validate configuration values and return list of warnings.
        
        Args:
            config: Configuration dictionary to validate
        
        Returns:
            List of warning messages for invalid values
        """
        warnings = []
        
        # Validate batch_size
        if config.get('batch_size', 1) < 1:
            warnings.append("batch_size must be >= 1, using default: 1000")
            config['batch_size'] = 1000
        
        # Validate worker_count
        if config.get('worker_count', 1) < 1:
            warnings.append("worker_count must be >= 1, using default: 4")
            config['worker_count'] = 4
        
        # Validate min_indicators_default
        if config.get('min_indicators_default', 1) < 1:
            warnings.append("min_indicators_default must be >= 1, using default: 1")
            config['min_indicators_default'] = 1
        
        # Validate pattern_cache_size
        if config.get('pattern_cache_size', 1) < 1:
            warnings.append("pattern_cache_size must be >= 1, using default: 10000")
            config['pattern_cache_size'] = 10000
        
        # Validate max_pattern_matches
        if config.get('max_pattern_matches', 1) < 1:
            warnings.append("max_pattern_matches must be >= 1, using default: 100")
            config['max_pattern_matches'] = 100
        
        # Validate debug_mode
        if not isinstance(config.get('debug_mode', False), bool):
            warnings.append("debug_mode must be a boolean, using default: False")
            config['debug_mode'] = False
        
        # Apply debug mode settings
        if config.get('debug_mode', False):
            logger.info("Debug mode enabled: setting batch_size=1 and worker_count=1")
            config['batch_size'] = 1
            config['worker_count'] = 1
        
        return warnings
    
    def _get_cached_pattern(self, pattern_str: str, rule_id: str = None):
        """
        Get compiled regex pattern from cache, compiling if needed.
        
        Implements LRU eviction when cache exceeds max size.
        Flags generic patterns during compilation.
        
        Args:
            pattern_str: Regex pattern string to compile
            rule_id: Optional rule identifier for logging warnings
            
        Returns:
            Compiled re.Pattern object, or None if pattern is invalid
        """
        import re
        
        # Check if pattern is in cache
        if pattern_str in self._pattern_cache:
            # Update access order (move to end = most recently used)
            if pattern_str in self._pattern_cache_access_order:
                self._pattern_cache_access_order.remove(pattern_str)
            self._pattern_cache_access_order.append(pattern_str)
            return self._pattern_cache[pattern_str]
        
        # Pattern not in cache, compile it
        try:
            compiled_pattern = re.compile(pattern_str, re.IGNORECASE)
            
            # Flag generic patterns during compilation
            if rule_id and self._is_generic_pattern(pattern_str):
                logger.debug(
                    f"[Pattern Cache] Generic pattern detected in rule {rule_id}: {pattern_str[:100]}. "
                    f"Consider enabling multi-indicator validation."
                )
            
            # Check if cache is full
            if len(self._pattern_cache) >= self._pattern_cache_max_size:
                # Evict least recently used pattern
                lru_pattern = self._pattern_cache_access_order.pop(0)
                del self._pattern_cache[lru_pattern]
                logger.debug(f"[Pattern Cache] Evicted LRU pattern: {lru_pattern[:50]}...")
            
            # Add to cache
            self._pattern_cache[pattern_str] = compiled_pattern
            self._pattern_cache_access_order.append(pattern_str)
            
            return compiled_pattern
            
        except re.error as e:
            # Invalid pattern - log and return None
            error_message = str(e)
            logger.warning(f"[Pattern Cache] Invalid regex pattern: {pattern_str[:100]} - {error_message}")
            
            # Log to debug file
            if rule_id:
                self._log_compilation_error(rule_id, pattern_str, error_message)
            
            return None
    
    def _clear_pattern_cache(self):
        """Clear all cached patterns."""
        self._pattern_cache.clear()
        self._pattern_cache_access_order.clear()
    
    def _init_debug_logging(self):
        """
        Initialize debug log file in the case directory.
        
        Creates a log file at: {case_directory}/correlation_engine/semantic_mapping_debug.log
        
        Handles file I/O errors gracefully by logging warnings and continuing without debug logging.
        """
        try:
            # Get log file path from configuration
            log_file_path = self.config.get('log_file_path', 'correlation_engine/semantic_mapping_debug.log')
            
            # Extract case directory from database path
            # Database path format: {case_directory}/correlation_engine/correlation.db
            case_directory = os.path.dirname(os.path.dirname(self.database_path))
            
            # Build full log file path
            full_log_path = os.path.join(case_directory, log_file_path)
            
            # Create directory if it doesn't exist
            log_dir = os.path.dirname(full_log_path)
            os.makedirs(log_dir, exist_ok=True)
            
            # Open log file in append mode
            self._debug_log_file = open(full_log_path, 'a', encoding='utf-8')
            
            # Write header with timestamp
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._debug_log_file.write(f"\n{'='*80}\n")
            self._debug_log_file.write(f"[{timestamp}] Semantic Mapping Debug Log - Execution ID: {self.execution_id}\n")
            self._debug_log_file.write(f"{'='*80}\n")
            self._debug_log_file.flush()
            
            logger.info(f"Debug logging initialized: {full_log_path}")
            
        except Exception as e:
            logger.warning(f"Failed to initialize debug logging: {e}. Continuing without debug log file.")
            self._debug_log_file = None
    
    def _log_rule_match(
        self, 
        rule_id: str, 
        matched_conditions: List[str],
        matched_feathers: List[str],
        confidence: float
    ):
        """
        Log successful rule match to debug file.
        
        Args:
            rule_id: Rule identifier
            matched_conditions: List of condition names that matched
            matched_feathers: List of feather names that matched
            confidence: Confidence score for the match
        """
        if self._debug_log_file is None:
            return
        
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Format matched conditions and feathers
            conditions_str = ",".join(matched_conditions) if matched_conditions else "none"
            feathers_str = ",".join(matched_feathers) if matched_feathers else "none"
            
            log_entry = (
                f"[{timestamp}] MATCH | "
                f"rule_id={rule_id} | "
                f"conditions={len(matched_conditions)} | "
                f"condition_names=[{conditions_str}] | "
                f"feathers=[{feathers_str}] | "
                f"confidence={confidence:.2f}\n"
            )
            
            self._debug_log_file.write(log_entry)
            self._debug_log_file.flush()
            
        except Exception as e:
            logger.warning(f"Failed to write rule match to debug log: {e}")
    
    def _log_compilation_error(self, rule_id: str, pattern: str, error_message: str):
        """
        Log regex compilation error to debug file.
        
        Args:
            rule_id: Rule identifier
            pattern: Pattern string that failed to compile
            error_message: Error message from regex compiler
        """
        if self._debug_log_file is None:
            return
        
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Truncate pattern if too long
            pattern_display = pattern[:100] + "..." if len(pattern) > 100 else pattern
            
            log_entry = (
                f"[{timestamp}] COMPILATION_ERROR | "
                f"rule_id={rule_id} | "
                f"pattern={pattern_display} | "
                f"error={error_message}\n"
            )
            
            self._debug_log_file.write(log_entry)
            self._debug_log_file.flush()
            
        except Exception as e:
            logger.warning(f"Failed to write compilation error to debug log: {e}")
    
    def _log_fts5_unavailable(self, error_message: str):
        """
        Log FTS5 unavailability warning to debug file.
        
        Args:
            error_message: Error message from FTS5 initialization
        """
        if self._debug_log_file is None:
            return
        
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            log_entry = (
                f"[{timestamp}] FTS5_UNAVAILABLE | "
                f"error={error_message} | "
                f"fallback=regex_only_matching\n"
            )
            
            self._debug_log_file.write(log_entry)
            self._debug_log_file.flush()
            
        except Exception as e:
            logger.warning(f"Failed to write FTS5 unavailable warning to debug log: {e}")
    
    def _log_fts5_zero_results(self, term_count: int):
        """
        Log FTS5 zero results fallback to debug file.
        
        Args:
            term_count: Number of FTS5 terms that were used in the query
        """
        if self._debug_log_file is None:
            return
        
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            log_entry = (
                f"[{timestamp}] FTS5_ZERO_RESULTS | "
                f"terms={term_count} | "
                f"fallback=process_all_matches\n"
            )
            
            self._debug_log_file.write(log_entry)
            self._debug_log_file.flush()
            
        except Exception as e:
            logger.warning(f"Failed to write FTS5 zero results warning to debug log: {e}")
    
    def _log_database_error(self, operation: str, batch_num: int, error_message: str):
        """
        Log database operation error to debug file.
        
        Args:
            operation: Operation that failed (e.g., "batch_update", "commit", "rollback")
            batch_num: Batch number where error occurred
            error_message: Error message from database
        """
        if self._debug_log_file is None:
            return
        
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            log_entry = (
                f"[{timestamp}] DATABASE_ERROR | "
                f"operation={operation} | "
                f"batch={batch_num} | "
                f"error={error_message}\n"
            )
            
            self._debug_log_file.write(log_entry)
            self._debug_log_file.flush()
            
        except Exception as e:
            logger.warning(f"Failed to write database error to debug log: {e}")
    
    def _log_worker_error(self, worker_id: int, error_message: str):
        """
        Log worker thread error to debug file.
        
        Args:
            worker_id: Worker thread identifier
            error_message: Error message from worker
        """
        if self._debug_log_file is None:
            return
        
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            log_entry = (
                f"[{timestamp}] WORKER_ERROR | "
                f"worker_id={worker_id} | "
                f"error={error_message}\n"
            )
            
            self._debug_log_file.write(log_entry)
            self._debug_log_file.flush()
            
        except Exception as e:
            logger.warning(f"Failed to write worker error to debug log: {e}")
    
    def _log_summary(self, stats: Dict[str, Any]):
        """
        Log summary statistics to debug file.
        
        Args:
            stats: Dictionary containing summary statistics:
                - rules_evaluated: Number of rules evaluated
                - matches_found: Number of matches found
                - processing_time: Processing time in seconds
                - throughput: Matches per second
                - validation_failures: Number of multi-indicator validation failures
                - pattern_warnings: Number of pattern warnings
                - compilation_errors: Number of compilation errors
        """
        if self._debug_log_file is None:
            return
        
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            log_entry = (
                f"[{timestamp}] SUMMARY | "
                f"rules_evaluated={stats.get('rules_evaluated', 0)} | "
                f"matches_found={stats.get('matches_found', 0)} | "
                f"time={stats.get('processing_time', 0):.2f}s | "
                f"throughput={stats.get('throughput', 0):.1f}/s"
            )
            
            # Add optional statistics if present
            if 'validation_failures' in stats:
                log_entry += f" | validation_failures={stats['validation_failures']}"
            if 'pattern_warnings' in stats:
                log_entry += f" | pattern_warnings={stats['pattern_warnings']}"
            if 'compilation_errors' in stats:
                log_entry += f" | compilation_errors={stats['compilation_errors']}"
            
            log_entry += "\n"
            
            self._debug_log_file.write(log_entry)
            self._debug_log_file.flush()
            
        except Exception as e:
            logger.warning(f"Failed to write summary to debug log: {e}")

    def _log_batch_progress(self, batch_num: int, total_batches: int, batch_size: int, total_updated: int):
        """
        Log batch processing progress to debug file.

        Args:
            batch_num: Current batch number (1-indexed)
            total_batches: Total number of batches
            batch_size: Number of records in this batch
            total_updated: Total number of records updated so far
        """
        if self._debug_log_file is None:
            return

        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            log_entry = (
                f"[{timestamp}] BATCH_PROGRESS | "
                f"batch={batch_num}/{total_batches} | "
                f"batch_size={batch_size} | "
                f"total_updated={total_updated}\n"
            )

            self._debug_log_file.write(log_entry)
            self._debug_log_file.flush()

        except Exception as e:
            logger.warning(f"Failed to write batch progress to debug log: {e}")

    
    def _close_debug_log(self):
        """Close debug log file."""
        if self._debug_log_file is not None:
            try:
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._debug_log_file.write(f"[{timestamp}] Debug logging session ended\n")
                self._debug_log_file.write(f"{'='*80}\n\n")
                self._debug_log_file.close()
                self._debug_log_file = None
            except Exception as e:
                logger.warning(f"Failed to close debug log file: {e}")
        logger.info("[Pattern Cache] Cache cleared")

    def _validate_multi_indicator_rule(self, rule: Dict[str, Any], matched_conditions_count: int) -> Tuple[bool, str]:
        """
        Validate that rule has sufficient indicators.

        This method enforces multi-indicator validation for rules that require
        multiple independent indicators to match before triggering an alert.

        Args:
            rule: Dictionary containing rule data with fields:
                  - rule_id: Rule identifier
                  - _requires_multi_indicator: Boolean flag (optional, default: False)
                  - _min_indicators: Minimum required indicators (optional, default: 1)
                  - conditions_json: JSON string of conditions
            matched_conditions_count: Number of conditions that matched

        Returns:
            Tuple of (is_valid, reason):
                - is_valid: True if rule passes validation, False otherwise
                - reason: String explaining validation result
        """
        # Extract rule fields
        rule_id = rule.get('rule_id', 'unknown')
        requires_multi = rule.get('_requires_multi_indicator', False)
        min_indicators = rule.get('_min_indicators', self.config.get('min_indicators_default', 1))

        # Backward compatibility: if _requires_multi_indicator is not set, allow single-indicator matching
        if not requires_multi:
            return (True, "Single-indicator matching (backward compatibility)")

        # Parse conditions to get total count
        try:
            conditions = json.loads(rule.get('conditions_json', '[]'))
            total_conditions = len(conditions)
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"[Multi-Indicator] Rule {rule_id}: Failed to parse conditions_json")
            return (False, "Failed to parse conditions")

        # Edge case: _min_indicators > total conditions
        if min_indicators > total_conditions:
            logger.warning(
                f"[Multi-Indicator] Rule {rule_id}: _min_indicators ({min_indicators}) "
                f"> total conditions ({total_conditions}). Rule is unmatchable."
            )
            return (False, f"Unmatchable: requires {min_indicators} indicators but only has {total_conditions} conditions")

        # Validate threshold
        if matched_conditions_count >= min_indicators:
            return (True, f"Matched {matched_conditions_count}/{min_indicators} required indicators")
        else:
            # Log validation failure
            self._log_validation_failure(rule_id, matched_conditions_count, min_indicators)
            return (False, f"Insufficient indicators: {matched_conditions_count}/{min_indicators}")

    def _log_validation_failure(self, rule_id: str, matched_count: int, required_count: int):
        """
        Log multi-indicator validation failure.

        Args:
            rule_id: Rule identifier
            matched_count: Number of indicators that matched
            required_count: Number of indicators required
        """
        logger.info(
            f"[Multi-Indicator] VALIDATION_FAIL | rule_id={rule_id} | "
            f"matched={matched_count} | required={required_count}"
        )
        
        # Also write to debug log file
        if self._debug_log_file is not None:
            try:
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                log_entry = (
                    f"[{timestamp}] VALIDATION_FAIL | "
                    f"rule_id={rule_id} | "
                    f"matched={matched_count} | "
                    f"required={required_count}\n"
                )
                
                self._debug_log_file.write(log_entry)
                self._debug_log_file.flush()
                
            except Exception as e:
                logger.warning(f"Failed to write validation failure to debug log: {e}")

    def _is_generic_pattern(self, pattern_str: str) -> bool:
        """
        Detect if a regex pattern is overly generic.

        Generic patterns are those that match very broadly and should require
        multi-indicator validation to avoid false positives.

        Examples of generic patterns:
        - ".*" - matches anything
        - ".+" - matches any non-empty string
        - "\\w+" - matches any word
        - ".*CHROME.*" - matches anything containing CHROME

        Args:
            pattern_str: Regex pattern string to check

        Returns:
            True if pattern is generic, False otherwise
        """
        import re

        # Patterns that are purely generic
        purely_generic = [
            r'^\.[\*\+]$',  # .* or .+
            r'^\\w[\*\+]$',  # \w* or \w+
            r'^\\d[\*\+]$',  # \d* or \d+
            r'^\\s[\*\+]$',  # \s* or \s+
            r'^\.\*$',       # .*
            r'^\.\+$',       # .+
        ]

        for generic_pattern in purely_generic:
            if re.match(generic_pattern, pattern_str):
                return True

        # Patterns that start and end with .* or .+ (e.g., ".*CHROME.*")
        if re.match(r'^\.\*.*\.\*$', pattern_str) or re.match(r'^\.\+.*\.\+$', pattern_str):
            return True

        # Count the ratio of specific characters to wildcards
        # If more than 50% of the pattern is wildcards, it's generic
        wildcard_chars = pattern_str.count('.*') + pattern_str.count('.+') + pattern_str.count('\\w+') + pattern_str.count('\\d+')
        total_length = len(pattern_str)

        if total_length > 0 and (wildcard_chars * 2) / total_length > 0.5:
            return True

        return False

    def _validate_pattern_specificity(self, operator: str, value: str, rule_id: str) -> bool:
        """
        Validate pattern specificity and log warnings for overly broad patterns.

        Checks:
        - For "contains" operator: string should be at least 3 characters
        - For "regex" operator: pattern should not be purely generic

        Args:
            operator: Condition operator (regex, contains, equals)
            value: Pattern or string value
            rule_id: Rule identifier for logging

        Returns:
            True if pattern passes validation, False if warning was logged
        """
        has_warning = False

        # Check "contains" operator for short strings
        if operator == "contains":
            if len(value) < 3:
                logger.warning(
                    f"[Pattern Validation] Rule {rule_id}: 'contains' operator with short string "
                    f"(length={len(value)}). This may cause false positives. "
                    f"Consider using longer strings (>= 3 characters)."
                )
                has_warning = True

        # Check "regex" operator for generic patterns
        elif operator == "regex":
            if self._is_generic_pattern(value):
                logger.warning(
                    f"[Pattern Validation] Rule {rule_id}: Generic regex pattern detected: {value[:100]}. "
                    f"Consider enabling multi-indicator validation for this rule."
                )
                has_warning = True

        return not has_warning

    def _log_pattern_warning(self, rule_id: str, pattern: str, match_count: int):
        """
        Log warning for patterns that match too many identities.

        This helps identify overly generic patterns that may cause false positives.

        Args:
            rule_id: Rule identifier
            pattern: Pattern string that matched too broadly
            match_count: Number of distinct identities matched
        """
        max_matches = self.config.get('max_pattern_matches', 100)

        logger.warning(
            f"[Pattern Validation] PATTERN_WARNING | rule_id={rule_id} | "
            f"pattern={pattern[:100]} | matches={match_count} | "
            f"threshold={max_matches} | "
            f"This pattern matches too many identities and may cause false positives."
        )
        
        # Also write to debug log file
        if self._debug_log_file is not None:
            try:
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Truncate pattern if too long
                pattern_display = pattern[:100] + "..." if len(pattern) > 100 else pattern
                
                log_entry = (
                    f"[{timestamp}] PATTERN_WARNING | "
                    f"rule_id={rule_id} | "
                    f"pattern={pattern_display} | "
                    f"matches={match_count} | "
                    f"threshold={max_matches}\n"
                )
                
                self._debug_log_file.write(log_entry)
                self._debug_log_file.flush()
                
            except Exception as e:
                logger.warning(f"Failed to write pattern warning to debug log: {e}")

    def _process_match_batch(
        self,
        matches_batch: List[Tuple],
        rules: List[Tuple],
        worker_id: int,
        progress_callback=None
    ) -> Tuple[List[Tuple[str, str]], int, Dict[str, set]]:
        """
        Process a batch of matches in a worker thread.
        Called by ThreadPoolExecutor workers.
        
        Args:
            matches_batch: List of (match_id, feather_records, matched_application) tuples
            rules: List of rule tuples (rule_id, logic_operator, conditions_json, requires_multi_indicator, min_indicators)
            worker_id: Worker thread identifier for logging
            progress_callback: Optional callback function to report progress
            
        Returns:
            Tuple of (results, errors, pattern_match_counts) where:
            - results: List of (match_id, matched_rule_ids) tuples
            - errors: Number of errors encountered
            - pattern_match_counts: Dict of pattern -> set of match_ids
        """
        import re
        
        # Each worker needs its own database connection for thread safety
        worker_conn = sqlite3.connect(self.database_path, timeout=30.0)
        worker_cursor = worker_conn.cursor()
        
        # Enable WAL mode for better concurrency
        worker_cursor.execute("PRAGMA journal_mode=WAL")
        worker_cursor.execute("PRAGMA synchronous=NORMAL")
        
        results = []
        errors = 0
        pattern_match_counts = {}
        
        # Progress reporting interval (every 100 matches for consistent reporting)
        batch_size = len(matches_batch)
        progress_interval = 100  # Report every 100 matches for consistent progress updates
        last_reported_idx = 0
        
        try:
            for idx, (match_id, feather_records, matched_application) in enumerate(matches_batch):
                try:
                    if not feather_records:
                        continue
                    
                    # Report progress periodically (report the INCREMENT since last report)
                    if progress_callback and (idx + 1) % progress_interval == 0:
                        increment = (idx + 1) - last_reported_idx
                        progress_callback(worker_id, increment)
                        last_reported_idx = idx + 1
                    
                    # Parse feather_records JSON (Requirement 8.1: Graceful handling of malformed JSON)
                    try:
                        feather_data = json.loads(feather_records)
                    except json.JSONDecodeError as e:
                        # Log malformed JSON with match_id and continue processing (Requirement 8.1)
                        logger.warning(f"[Worker {worker_id}] Malformed JSON in match {match_id}: {e}")
                        errors += 1
                        continue
                    except Exception as e:
                        # Catch any other JSON parsing errors
                        logger.warning(f"[Worker {worker_id}] Error parsing JSON in match {match_id}: {e}")
                        errors += 1
                        continue
                    
                    # Validate feather_data is a dict (Requirement 8.2: Handle non-dict data)
                    if not isinstance(feather_data, dict):
                        logger.warning(f"[Worker {worker_id}] Non-dict feather_records in match {match_id}: {type(feather_data)}")
                        errors += 1
                        continue
                    
                    # Find matching rules
                    matched_rules = set()
                    
                    for rule_id, logic_operator, conditions_json, requires_multi_indicator, min_indicators in rules:
                        try:
                            conditions = json.loads(conditions_json)
                        except json.JSONDecodeError as e:
                            # Log malformed JSON in rule and continue (Requirement 8.1)
                            logger.error(f"[Worker {worker_id}] Malformed JSON in rule {rule_id}: {e}")
                            errors += 1
                            continue
                        except Exception as e:
                            # Catch any other JSON parsing errors
                            logger.error(f"[Worker {worker_id}] Error parsing rule {rule_id}: {e}")
                            errors += 1
                            continue
                        
                        # Skip rules with no valid conditions
                        if not conditions:
                            continue
                        
                        # Check ALL conditions with AND logic
                        all_conditions_met = True
                        has_non_wildcard = False
                        matched_conditions_count = 0
                        
                        for condition in conditions:
                            # Requirement 8.3: Graceful handling of condition evaluation exceptions
                            try:
                                field_name = condition['field_name']
                                pattern = condition['value']
                                operator = condition['operator']
                                
                                # Skip wildcard, empty, and invalid conditions
                                if not pattern or pattern == "*" or operator == "wildcard":
                                    continue
                                
                                has_non_wildcard = True
                                
                                # For each condition, check MULTIPLE strategies (OR logic within condition)
                                condition_met = False
                                
                                # STRATEGY 1: Check matched_application column directly (FASTEST)
                                if field_name == 'matched_application' and matched_application:
                                    matched_app_upper = str(matched_application).upper()
                                    
                                    if operator == "regex":
                                        compiled_pattern = self._get_cached_pattern(pattern, rule_id)
                                        if compiled_pattern:
                                            try:
                                                if compiled_pattern.search(matched_app_upper):
                                                    condition_met = True
                                            except Exception as e:
                                                # Log regex matching error and treat condition as not matched (Requirement 8.3)
                                                logger.warning(f"[Worker {worker_id}] Error matching pattern in rule {rule_id}: {e}")
                                    
                                    elif operator == "contains":
                                        if pattern.upper() in matched_app_upper:
                                            condition_met = True
                                    
                                    elif operator == "equals":
                                        if pattern.upper() == matched_app_upper:
                                            condition_met = True
                            
                                # STRATEGY 2: Check the specific field in feather_records
                                if not condition_met:
                                    field_value = None
                                    for feather_name, feather_content in feather_data.items():
                                        if isinstance(feather_content, list):
                                            for record in feather_content:
                                                if isinstance(record, dict) and field_name in record:
                                                    field_value = record[field_name]
                                                    break
                                            if field_value:
                                                break
                                    
                                    if field_value:
                                        field_value_str = str(field_value).upper()
                                        
                                        if operator == "regex":
                                            compiled_pattern = self._get_cached_pattern(pattern, rule_id)
                                            if compiled_pattern:
                                                try:
                                                    if compiled_pattern.search(field_value_str):
                                                        condition_met = True
                                                except Exception as e:
                                                    # Log regex matching error and treat condition as not matched (Requirement 8.3)
                                                    logger.warning(f"[Worker {worker_id}] Error matching pattern in rule {rule_id}: {e}")
                                        
                                        elif operator == "contains":
                                            if pattern.upper() in field_value_str:
                                                condition_met = True
                                        
                                        elif operator == "equals":
                                            if pattern.upper() == field_value_str:
                                                condition_met = True
                            
                                # STRATEGY 3: Check ALL field values in feather_records
                                if not condition_met:
                                    all_values = []
                                    for feather_name, feather_content in feather_data.items():
                                        if isinstance(feather_content, list):
                                            for record in feather_content:
                                                if isinstance(record, dict):
                                                    for key, value in record.items():
                                                        if isinstance(value, str):
                                                            all_values.append(value.upper())
                                    
                                    if operator == "regex":
                                        compiled_pattern = self._get_cached_pattern(pattern, rule_id)
                                        if compiled_pattern:
                                            try:
                                                for value in all_values:
                                                    if compiled_pattern.search(value):
                                                        condition_met = True
                                                        break
                                            except Exception as e:
                                                # Log regex matching error and treat condition as not matched (Requirement 8.3)
                                                logger.warning(f"[Worker {worker_id}] Error matching pattern in rule {rule_id}: {e}")
                                    
                                    elif operator == "contains":
                                        pattern_upper = pattern.upper()
                                        for value in all_values:
                                            if pattern_upper in value:
                                                condition_met = True
                                                break
                                    
                                    elif operator == "equals":
                                        pattern_upper = pattern.upper()
                                        for value in all_values:
                                            if pattern_upper == value:
                                                condition_met = True
                                                break
                                
                                # If this condition is not met by ANY strategy, the rule fails
                                if not condition_met:
                                    all_conditions_met = False
                                    break
                                else:
                                    matched_conditions_count += 1
                                    
                                    # Track pattern matches for validation
                                    if operator == "regex":
                                        if pattern not in pattern_match_counts:
                                            pattern_match_counts[pattern] = set()
                                        pattern_match_counts[pattern].add(match_id)
                            
                            except KeyError as e:
                                # Handle missing keys in condition dict (Requirement 8.3)
                                logger.warning(f"[Worker {worker_id}] Missing key in condition for rule {rule_id}: {e}")
                                errors += 1
                                # Treat condition as not matched and continue
                                all_conditions_met = False
                                break
                            except Exception as e:
                                # Catch any other condition evaluation errors (Requirement 8.3)
                                logger.warning(f"[Worker {worker_id}] Error evaluating condition in rule {rule_id}: {e}")
                                errors += 1
                                # Treat condition as not matched and continue
                                all_conditions_met = False
                                break
                        
                        # Only add rule if it has non-wildcard conditions AND all are met
                        if has_non_wildcard and all_conditions_met:
                            # Validate multi-indicator rule before adding
                            rule_dict = {
                                'rule_id': rule_id,
                                '_requires_multi_indicator': bool(requires_multi_indicator),
                                '_min_indicators': min_indicators,
                                'conditions_json': conditions_json
                            }
                            is_valid, reason = self._validate_multi_indicator_rule(rule_dict, matched_conditions_count)
                            
                            if is_valid:
                                matched_rules.add(rule_id)
                    
                    if matched_rules:
                        sorted_rules = sorted(matched_rules)
                        results.append((match_id, ','.join(sorted_rules)))
                        
                except Exception as e:
                    errors += 1
                    logger.error(f"[Worker {worker_id}] Error processing match {match_id}: {e}")
                    if errors <= 5:
                        print(f"[Worker {worker_id}] ERROR processing match {match_id}: {e}")
        
        finally:
            # Report final progress for any remaining matches
            if progress_callback and last_reported_idx < batch_size:
                final_increment = batch_size - last_reported_idx
                progress_callback(worker_id, final_increment)
            
            # Close worker's database connection
            worker_conn.close()
        
        return results, errors, pattern_match_counts

    def _process_matches_parallel(
        self,
        candidate_matches: List[Tuple],
        rules: List[Tuple]
    ) -> Tuple[List[Tuple[str, str]], int, Dict[str, set]]:
        """
        Process matches in parallel across worker threads.
        
        Args:
            candidate_matches: List of (match_id, feather_records, matched_application) tuples
            rules: List of rule tuples
            
        Returns:
            Tuple of (results, total_errors, pattern_match_counts) where:
            - results: List of (match_id, matched_rule_ids) tuples
            - total_errors: Total number of errors across all workers
            - pattern_match_counts: Aggregated pattern match counts
        """
        # Handle empty matches early
        if not candidate_matches:
            print("[SQL Semantic] No candidate matches to process")
            return [], 0, {}
        
        worker_count = self.config.get('worker_count', 4)
        
        # If worker_count is 1, process sequentially (no parallelization)
        if worker_count == 1:
            print("[SQL Semantic] Processing sequentially (worker_count=1)")
            logger.info("[SQL Semantic] Processing sequentially with worker_count=1")
            
            # Create progress tracking for sequential mode
            from threading import Lock
            import time as time_module
            progress_lock = Lock()
            processed_count = [0]
            last_report_pct = [0]
            last_report_time = [time_module.time()]
            total_matches_to_process = len(candidate_matches)
            
            def sequential_progress_callback(worker_id, count_increment):
                """Progress callback for sequential processing."""
                with progress_lock:
                    processed_count[0] += count_increment
                    current_pct = (processed_count[0] / total_matches_to_process) * 100
                    current_time = time_module.time()
                    time_since_last = current_time - last_report_time[0]
                    
                    # Report every 5% OR every 5 minutes
                    should_report = False
                    if current_pct - last_report_pct[0] >= 5:
                        should_report = True
                    elif time_since_last >= 300:  # 5 minutes
                        should_report = True
                    
                    if should_report and processed_count[0] < total_matches_to_process:
                        print(f"[SQL Semantic] Progress: {current_pct:.0f}% ({processed_count[0]:,}/{total_matches_to_process:,} matches processed)")
                        logger.info(f"[SQL Semantic] Progress: {current_pct:.0f}% - {processed_count[0]} matches processed")
                        
                        # Force GUI update to prevent freezing
                        try:
                            from PyQt5.QtWidgets import QApplication
                            QApplication.processEvents()
                        except:
                            pass  # Ignore if not in GUI context
                        
                        last_report_pct[0] = current_pct
                        last_report_time[0] = current_time
            
            results, errors, pattern_match_counts = self._process_match_batch(
                candidate_matches, rules, worker_id=0, progress_callback=sequential_progress_callback
            )
            return results, errors, pattern_match_counts
        
        # Distribute matches across workers
        batch_size = max(1, len(candidate_matches) // worker_count)
        batches = []
        
        for i in range(worker_count):
            start_idx = i * batch_size
            if i == worker_count - 1:
                # Last worker gets remaining matches
                end_idx = len(candidate_matches)
            else:
                end_idx = start_idx + batch_size
            
            if start_idx < len(candidate_matches):
                batches.append(candidate_matches[start_idx:end_idx])
        
        print(f"[SQL Semantic] Processing with {len(batches)} workers ({batch_size} matches per worker)")
        logger.info(f"[SQL Semantic] Starting parallel processing with {len(batches)} workers")
        
        # Calculate total matches for progress tracking
        total_matches_to_process = len(candidate_matches)
        
        # Process batches in parallel with progress tracking
        all_results = []
        total_errors = 0
        aggregated_pattern_counts = {}
        
        # Shared progress tracking using a simple counter
        from threading import Lock
        import time as time_module
        progress_lock = Lock()
        processed_count = [0]  # Use list to allow modification in nested function
        last_report_pct = [0]  # Track last reported percentage
        last_report_time = [time_module.time()]  # Track last report time
        
        def worker_progress_callback(worker_id, count_increment):
            """Called by workers to report progress incrementally."""
            with progress_lock:
                processed_count[0] += count_increment
                current_pct = (processed_count[0] / total_matches_to_process) * 100
                current_time = time_module.time()
                time_since_last = current_time - last_report_time[0]
                
                # Report every 5% OR every 5 minutes
                should_report = False
                if current_pct - last_report_pct[0] >= 5:
                    should_report = True
                elif time_since_last >= 300:  # 5 minutes
                    should_report = True
                
                if should_report and processed_count[0] < total_matches_to_process:
                    print(f"[SQL Semantic] Worker progress: {current_pct:.0f}% ({processed_count[0]:,}/{total_matches_to_process:,} matches processed)")
                    logger.info(f"[SQL Semantic] Worker progress: {current_pct:.0f}% - {processed_count[0]} matches processed")
                    
                    # Force GUI update to prevent freezing
                    try:
                        from PyQt5.QtWidgets import QApplication
                        QApplication.processEvents()
                    except:
                        pass  # Ignore if not in GUI context
                    
                    last_report_pct[0] = current_pct
                    last_report_time[0] = current_time
        
        # No need for separate monitoring thread since workers report directly
        
        try:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                # Submit all batches to workers with progress callback
                future_to_worker = {}
                for worker_id, batch in enumerate(batches):
                    future = executor.submit(self._process_match_batch, batch, rules, worker_id, worker_progress_callback)
                    future_to_worker[future] = worker_id
                
                # Collect results as workers complete
                completed_workers = 0
                for future in as_completed(future_to_worker):
                    worker_id = future_to_worker[future]
                    try:
                        results, errors, pattern_counts = future.result()
                        all_results.extend(results)
                        total_errors += errors
                        
                        # Aggregate pattern match counts
                        for pattern, match_ids in pattern_counts.items():
                            if pattern not in aggregated_pattern_counts:
                                aggregated_pattern_counts[pattern] = set()
                            aggregated_pattern_counts[pattern].update(match_ids)
                        
                        # Worker completed - show completion message
                        completed_workers += 1
                        with progress_lock:
                            final_pct = (processed_count[0] / total_matches_to_process) * 100
                        
                        print(f"[SQL Semantic] Worker {worker_id} completed ({completed_workers}/{len(batches)}) - "
                              f"Found {len(results):,} matches - Overall: {final_pct:.0f}%")
                        logger.info(f"[SQL Semantic] Worker {worker_id} completed with {len(results)} matches")
                        
                    except Exception as e:
                        # Requirement 8.4: Graceful handling of worker thread failures
                        # Log error with context and continue with remaining workers
                        error_msg = str(e)
                        logger.error(f"[SQL Semantic] Worker {worker_id} failed with error: {error_msg}", exc_info=True)
                        print(f"[SQL Semantic] ERROR: Worker {worker_id} failed: {error_msg}")
                        self._log_worker_error(worker_id, error_msg)
                        total_errors += 1
                        # Continue processing with remaining workers (Requirement 8.4)
        finally:
            # No monitoring thread to stop
            pass
        
        print(f"[SQL Semantic] All workers completed - Total matches: {len(all_results):,}")
        logger.info(f"[SQL Semantic] Parallel processing complete: {len(all_results)} total matches")
        
        return all_results, total_errors, aggregated_pattern_counts

    
    def create_semantic_rules_table(self, rules: List[Any]) -> int:
        """
        Create and populate semantic_rules table with full rule data including ALL conditions.
        
        Args:
            rules: List of semantic rules
            
        Returns:
            Number of rules indexed
        """
        print("[SQL Semantic] Creating semantic_rules index table...")
        
        # Drop existing table if it exists (with retry logic)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.cursor.execute("DROP TABLE IF EXISTS semantic_rules")
                self.conn.commit()
                break
            except sqlite3.OperationalError as e:
                if attempt < max_retries - 1:
                    print(f"[SQL Semantic] Retry {attempt + 1}/{max_retries}: {e}")
                    time.sleep(1)
                else:
                    raise
        
        # Create table to store full rule data with ALL conditions as JSON
        self.cursor.execute("""
            CREATE TABLE semantic_rules (
                rule_id TEXT PRIMARY KEY,
                semantic_value TEXT NOT NULL,
                rule_name TEXT,
                category TEXT,
                severity TEXT,
                confidence REAL,
                logic_operator TEXT,
                conditions_json TEXT NOT NULL,
                _requires_multi_indicator INTEGER DEFAULT 0,
                _min_indicators INTEGER DEFAULT 1
            )
        """)
        
        self.conn.commit()
        
        print("[SQL Semantic] Extracting rule patterns...")
        
        # Extract rule patterns (keep ALL conditions)
        rules_data = []
        
        for rule in rules:
            # Skip disabled rules
            if hasattr(rule, 'disabled') and rule.disabled:
                continue
            
            if not rule.conditions:
                continue
            
            # Store ALL conditions as JSON
            conditions = []
            for cond in rule.conditions:
                conditions.append({
                    'field_name': cond.field_name,
                    'value': cond.value,
                    'operator': cond.operator
                })
            
            rules_data.append((
                rule.rule_id,
                rule.semantic_value,
                rule.name,
                rule.category,
                rule.severity,
                rule.confidence,
                rule.logic_operator,
                json.dumps(conditions),
                1 if getattr(rule, '_requires_multi_indicator', False) else 0,
                getattr(rule, '_min_indicators', 1)
            ))
        
        print(f"[SQL Semantic] Inserting {len(rules_data):,} rules...")
        
        # Insert all rules
        self.cursor.executemany("""
            INSERT OR IGNORE INTO semantic_rules 
            (rule_id, semantic_value, rule_name, category, severity, confidence, logic_operator, conditions_json, _requires_multi_indicator, _min_indicators)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rules_data)
        
        self.conn.commit()
        
        # Get rule count
        self.cursor.execute("SELECT COUNT(*) FROM semantic_rules")
        rule_count = self.cursor.fetchone()[0]
        
        print(f"[SQL Semantic] Indexed {rule_count:,} rules")
        print("")
        
        return rule_count
    
    def find_matches_with_semantic_rules(self) -> List[Tuple[str, str]]:
        """
        Use FTS5 + proper regex matching to find all matches that satisfy semantic rules.
        
        Step 1: Use FTS5 to quickly filter candidates
        Step 2: Apply full regex matching with AND logic on candidates
        
        Returns:
            List of (match_id, matched_rule_ids) tuples
        """
        print("[SQL Semantic] Finding matches using FTS5 + regex pattern matching...")
        logger.info("[SQL Semantic] Starting semantic rule matching")
        
        start_time = time.time()
        
        # Track pattern match counts for validation (pattern -> set of match_ids)
        pattern_match_counts = {}
        
        # Load all rules with their conditions
        self.cursor.execute("""
            SELECT rule_id, logic_operator, conditions_json, _requires_multi_indicator, _min_indicators
            FROM semantic_rules
        """)
        rules = self.cursor.fetchall()
        
        print(f"[SQL Semantic] Loaded {len(rules):,} semantic rules")
        logger.info(f"[SQL Semantic] Loaded {len(rules)} semantic rules")
        
        # Check if we have any rules
        if not rules:
            print("[SQL Semantic] ❌ ERROR: No semantic rules found!")
            logger.error("[SQL Semantic] No semantic rules found - cannot perform semantic mapping")
            return []
        
        # Get total match count for progress reporting
        self.cursor.execute("""
            SELECT COUNT(*)
            FROM matches m
            INNER JOIN results r ON m.result_id = r.result_id
            WHERE r.execution_id = ?
        """, (self.execution_id,))
        total_matches = self.cursor.fetchone()[0]
        
        print(f"[SQL Semantic] Total matches to process: {total_matches:,}")
        logger.info(f"[SQL Semantic] Total matches in database: {total_matches}")
        print("")
        
        # STEP 1: Build FTS5 index for fast filtering
        print("[SQL Semantic] Step 1/2: Building FTS5 index...")
        fts_available = True
        
        try:
            # Check if FTS5 index already exists (Requirement 6.2)
            self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='matches_fts'")
            fts_exists = self.cursor.fetchone() is not None
            
            if fts_exists:
                # Reuse existing FTS5 index
                print("[SQL Semantic] Reusing existing FTS5 index")
                logger.info("[SQL Semantic] Reusing existing FTS5 index")
            else:
                # Create new FTS5 index with porter stemmer and unicode61 tokenizer (Requirement 6.1)
                self.cursor.execute("""
                    CREATE VIRTUAL TABLE matches_fts USING fts5(
                        match_id UNINDEXED,
                        feather_records,
                        tokenize='porter unicode61 remove_diacritics 1'
                    )
                """)
                
                self.cursor.execute("""
                    INSERT INTO matches_fts(match_id, feather_records)
                    SELECT m.match_id, m.feather_records
                    FROM matches m
                    INNER JOIN results r ON m.result_id = r.result_id
                    WHERE r.execution_id = ?
                """, (self.execution_id,))
                
                fts_count = self.cursor.rowcount
                self.conn.commit()
                print(f"[SQL Semantic] FTS5 index built with {fts_count:,} matches")
                logger.info(f"[SQL Semantic] FTS5 index built with {fts_count} matches")
        
        except Exception as e:
            # FTS5 not available - log warning and fall back to regex matching (Requirement 6.3)
            fts_available = False
            print(f"[SQL Semantic] WARNING: FTS5 not available - {str(e)}")
            print("[SQL Semantic] Falling back to regex-only matching (slower)")
            logger.warning(f"[SQL Semantic] FTS5 not available: {str(e)} - falling back to regex matching")
            self._log_fts5_unavailable(str(e))
        
        print("")
        
        # STEP 2: Extract search terms from rules for FTS5 filtering
        print("[SQL Semantic] Step 2/2: Matching rules with FTS5 + regex...")
        
        import re
        
        # Build FTS5 query from all regex patterns with improved term extraction
        fts_terms = set()
        for rule_id, logic_operator, conditions_json, requires_multi_indicator, min_indicators in rules:
            try:
                conditions = json.loads(conditions_json)
                for cond in conditions:
                    if cond['operator'] == 'regex' and cond['value'] != '*':
                        # Extract alternatives from regex (split on |)
                        alternatives = cond['value'].split('|')
                        for alt in alternatives:
                            # Improved cleaning: handle common patterns like CHROME\.EXE
                            # First, replace escaped dots with spaces to separate words
                            clean = alt.replace('\\.', ' ')
                            # Remove other regex special characters but keep the content
                            clean = re.sub(r'[\\+*?\[\](){}^$.]', '', clean)
                            # Split on spaces and extract individual words
                            words = clean.split()
                            for word in words:
                                word = word.strip()
                                # Only add words that are 3+ characters and alphanumeric
                                if len(word) >= 3 and word.replace('_', '').replace('-', '').isalnum():
                                    fts_terms.add(word.lower())
                    elif cond['operator'] == 'contains' and cond['value'] != '*':
                        # Also extract terms from 'contains' operators
                        value = cond['value'].strip()
                        if len(value) >= 3:
                            fts_terms.add(value.lower())
            except Exception as e:
                logger.debug(f"[FTS5] Error extracting terms from rule {rule_id}: {e}")
                continue
        
        # Determine which filtering strategy to use
        if not fts_available:
            # FTS5 not available - process all matches
            print("[SQL Semantic] Processing all matches (FTS5 unavailable)")
            self.cursor.execute("""
                SELECT m.match_id, m.feather_records, m.matched_application
                FROM matches m
                INNER JOIN results r ON m.result_id = r.result_id
                WHERE r.execution_id = ?
            """, (self.execution_id,))
            candidate_matches = self.cursor.fetchall()
        elif not fts_terms:
            # No FTS terms extracted - process all matches
            print("[SQL Semantic] WARNING: No FTS terms extracted, processing all matches")
            logger.warning("[SQL Semantic] No FTS terms extracted from rules")
            self.cursor.execute("""
                SELECT m.match_id, m.feather_records, m.matched_application
                FROM matches m
                INNER JOIN results r ON m.result_id = r.result_id
                WHERE r.execution_id = ?
            """, (self.execution_id,))
            candidate_matches = self.cursor.fetchall()
        else:
            # Use FTS5 to filter candidates (Requirement 6.4: limit to 1000 terms)
            print(f"[SQL Semantic] Extracted {len(fts_terms)} FTS5 search terms")
            logger.info(f"[SQL Semantic] Extracted {len(fts_terms)} FTS5 search terms")
            
            # Log sample of terms for debugging
            sample_terms = list(fts_terms)[:10]
            logger.debug(f"[SQL Semantic] Sample FTS5 terms: {', '.join(sample_terms)}")
            
            fts_query = " OR ".join(f'"{term}"' for term in list(fts_terms)[:1000])
            
            if len(fts_terms) > 1000:
                print(f"[SQL Semantic] WARNING: Limited FTS5 query to 1000 terms (from {len(fts_terms)})")
                logger.warning(f"[SQL Semantic] FTS5 query limited to 1000 terms from {len(fts_terms)} total terms")
            
            self.cursor.execute("""
                SELECT m.match_id, m.feather_records, m.matched_application
                FROM matches_fts mf
                INNER JOIN matches m ON mf.match_id = m.match_id
                INNER JOIN results r ON m.result_id = r.result_id
                WHERE r.execution_id = ?
                  AND mf.feather_records MATCH ?
            """, (self.execution_id, fts_query))
            
            candidate_matches = self.cursor.fetchall()
            
            # Requirement 6.5: Fallback to all matches if FTS5 returns zero candidates
            if len(candidate_matches) == 0 and total_matches > 0:
                print("[SQL Semantic] WARNING: FTS5 returned zero candidates, falling back to all matches")
                logger.warning("[SQL Semantic] FTS5 returned zero candidates - falling back to processing all matches")
                self._log_fts5_zero_results(len(fts_terms))
                
                self.cursor.execute("""
                    SELECT m.match_id, m.feather_records, m.matched_application
                    FROM matches m
                    INNER JOIN results r ON m.result_id = r.result_id
                    WHERE r.execution_id = ?
                """, (self.execution_id,))
                candidate_matches = self.cursor.fetchall()
        
        coverage_pct = (len(candidate_matches)/total_matches*100) if total_matches > 0 else 0
        print(f"[SQL Semantic] FTS5 filtered to {len(candidate_matches):,} candidates ({coverage_pct:.1f}%)")
        print("")
        
        # STEP 3: Apply full regex matching with AND logic (parallel or sequential based on config)
        worker_count = self.config.get('worker_count', 4)
        
        if worker_count > 1:
            print(f"[SQL Semantic] Applying full regex matching with parallel processing ({worker_count} workers)...")
        else:
            print("[SQL Semantic] Applying full regex matching with AND logic...")
        
        # Use parallel processing if worker_count > 1, otherwise sequential
        results, errors, pattern_match_counts = self._process_matches_parallel(
            candidate_matches, rules
        )
        
        elapsed = time.time() - start_time
        
        print("")
        print(f"[SQL Semantic] Rule matching complete in {elapsed:.2f}s")
        print(f"[SQL Semantic] Found {len(results):,} matches with semantic data")
        coverage_pct = (len(results)/total_matches*100) if total_matches > 0 else 0
        print(f"[SQL Semantic] Coverage: {coverage_pct:.1f}%")
        
        if errors > 0:
            print(f"[SQL Semantic] WARNING: {errors} errors occurred during matching")
            logger.warning(f"[SQL Semantic] {errors} errors occurred during matching")
        
        # Validate pattern match counts and log warnings for overly generic patterns
        max_pattern_matches = self.config.get('max_pattern_matches', 100)
        generic_patterns_found = 0
        
        for pattern, match_ids in pattern_match_counts.items():
            match_count = len(match_ids)
            if match_count > max_pattern_matches:
                # Find which rule(s) use this pattern
                for rule_id, logic_operator, conditions_json, requires_multi_indicator, min_indicators in rules:
                    try:
                        conditions = json.loads(conditions_json)
                        for cond in conditions:
                            if cond.get('operator') == 'regex' and cond.get('value') == pattern:
                                self._log_pattern_warning(rule_id, pattern, match_count)
                                generic_patterns_found += 1
                                break
                    except:
                        continue
        
        if generic_patterns_found > 0:
            print(f"[SQL Semantic] WARNING: {generic_patterns_found} patterns exceeded match threshold ({max_pattern_matches})")
            logger.warning(f"[SQL Semantic] {generic_patterns_found} patterns exceeded match threshold")
        
        logger.info(f"[SQL Semantic] Matching complete: {len(results)} matches with semantic data")
        
        return results
    
    def build_and_update_semantic_data(self, matches_with_rules: List[Tuple[str, str]]) -> int:
        """
        Build semantic data and update matches in bulk.
        
        Args:
            matches_with_rules: List of (match_id, matched_rule_ids) tuples
            
        Returns:
            Number of matches updated
        """
        print("")
        print("[SQL Semantic] Building semantic data...")
        logger.info("[SQL Semantic] Starting semantic data building")
        
        start_time = time.time()
        
        # Get rule metadata
        self.cursor.execute("""
            SELECT rule_id, semantic_value, rule_name, category, severity, confidence, conditions_json
            FROM semantic_rules
        """)
        
        rule_metadata = {}
        for row in self.cursor.fetchall():
            rule_id, semantic_value, rule_name, category, severity, confidence, conditions_json = row
            
            # Extract the main pattern from conditions for display
            try:
                conditions = json.loads(conditions_json)
                # Find the matched_application or identity_value condition
                technical_value = ""
                for cond in conditions:
                    if cond['field_name'] in ('matched_application', 'identity_value'):
                        technical_value = cond['value'][:100] if len(cond['value']) < 100 else cond['value'][:100]
                        break
            except:
                technical_value = ""
            
            rule_metadata[rule_id] = {
                'semantic_value': semantic_value,
                'rule_name': rule_name,
                'category': category,
                'severity': severity,
                'confidence': confidence,
                'technical_value': technical_value
            }
        
        print(f"[SQL Semantic] Loaded metadata for {len(rule_metadata):,} rules")
        logger.info(f"[SQL Semantic] Loaded metadata for {len(rule_metadata)} rules")
        
        # Build semantic data for each match with progress reporting
        print("[SQL Semantic] Building semantic data...")
        
        update_data = []
        build_errors = 0
        total_matches = len(matches_with_rules)
        
        # Guard against empty matches
        if total_matches == 0:
            print("[SQL Semantic] No matches to process")
            return {
                'identities_processed': 0,
                'mappings_applied': 0,
                'matches_updated': 0,
                'processing_time': 0,
                'errors': 0
            }
        
        progress_interval = max(1, total_matches // 20)  # 5% increments (100% / 20 = 5%)
        
        for idx, (match_id, matched_rules_str) in enumerate(matches_with_rules):
            try:
                if not matched_rules_str:
                    continue
                
                matched_rules = matched_rules_str.split(',')
                
                # Build semantic data JSON
                semantic_data = {}
                
                for rule_id in matched_rules:
                    if rule_id not in rule_metadata:
                        logger.warning(f"[SQL Semantic] Rule {rule_id} not found in metadata")
                        continue
                    
                    meta = rule_metadata[rule_id]
                    semantic_value_key = f"{meta['semantic_value']}_{rule_id}"
                    
                    semantic_data[semantic_value_key] = {
                        'identity_value': meta['technical_value'],
                        'identity_type': meta['category'] or 'unknown',
                        'semantic_mappings': [{
                            'semantic_value': meta['semantic_value'],
                            'technical_value': meta['technical_value'],
                            'rule_name': meta['rule_name'],
                            'category': meta['category'],
                            'severity': meta['severity'],
                            'confidence': meta['confidence'],
                            'rule_id': rule_id,
                            'matched_feathers': ['_identity']
                        }],
                        'feather_id': '_identity'
                    }
                
                if semantic_data:
                    update_data.append((json.dumps(semantic_data), match_id))
                    
            except Exception as e:
                build_errors += 1
                logger.error(f"[SQL Semantic] Error building data for match {match_id}: {e}")
                if build_errors <= 5:
                    print(f"[SQL Semantic] ERROR building data for match {match_id}: {e}")
            
            # Progress reporting every 5%
            if (idx + 1) % progress_interval == 0 or idx == total_matches - 1:
                progress_pct = ((idx + 1) / total_matches) * 100
                print(f"[SQL Semantic] Building progress: {progress_pct:.0f}% ({idx + 1:,}/{total_matches:,} processed, {len(update_data):,} with semantic data)")
                logger.info(f"[SQL Semantic] Build progress: {progress_pct:.0f}% - {len(update_data)} matches with semantic data")
                
                # Force GUI update to prevent freezing
                try:
                    from PyQt5.QtWidgets import QApplication
                    QApplication.processEvents()
                except:
                    pass  # Ignore if not in GUI context
        
        if build_errors > 0:
            print(f"[SQL Semantic] WARNING: {build_errors} errors occurred during data building")
            logger.warning(f"[SQL Semantic] {build_errors} errors during data building")
        
        print("")
        print(f"[SQL Semantic] Built semantic data for {len(update_data):,} matches")
        logger.info(f"[SQL Semantic] Built semantic data for {len(update_data)} matches")
        print(f"[SQL Semantic] Updating database...")
        
        # Update in batches with progress reporting and error handling
        # Commit per batch for better error recovery and memory management (Requirement 4.2)
        
        # Guard against empty update_data
        if not update_data:
            print("[SQL Semantic] No semantic data to update")
            return {
                'identities_processed': 0,
                'mappings_applied': 0,
                'matches_updated': 0,
                'processing_time': time.time() - start_time,
                'errors': build_errors
            }
        
        batch_size = self.config.get('batch_size', 1000)
        total_batches = (len(update_data) + batch_size - 1) // batch_size
        update_errors = 0
        successful_updates = 0
        progress_interval = max(1, total_batches // 20)  # 5% increments (100% / 20 = 5%)
        
        for i in range(0, len(update_data), batch_size):
            batch_num = i // batch_size + 1
            try:
                batch = update_data[i:i + batch_size]
                
                # Execute batch update (Requirement 8.5: Graceful handling of database failures)
                try:
                    self.cursor.executemany("""
                        UPDATE matches 
                        SET semantic_data = ? 
                        WHERE match_id = ?
                    """, batch)
                    
                    # Commit after each batch (Requirement 4.2)
                    self.conn.commit()
                    
                    successful_updates += len(batch)
                    
                    # Log batch completion
                    self._log_batch_progress(batch_num, total_batches, len(batch), successful_updates)
                    
                    # Progress reporting every 5%
                    if batch_num % progress_interval == 0 or batch_num == total_batches:
                        progress_pct = (successful_updates / len(update_data)) * 100
                        print(f"[SQL Semantic] Database update progress: {progress_pct:.0f}% ({successful_updates:,}/{len(update_data):,} records updated)")
                        logger.info(f"[SQL Semantic] Update progress: {progress_pct:.0f}% - {successful_updates} records updated")
                        
                        # Force GUI update to prevent freezing
                        try:
                            from PyQt5.QtWidgets import QApplication
                            QApplication.processEvents()
                        except:
                            pass  # Ignore if not in GUI context
                
                except sqlite3.OperationalError as e:
                    # Database lock or operational error (Requirement 8.5)
                    update_errors += 1
                    error_msg = str(e)
                    logger.error(f"[SQL Semantic] Database operational error in batch {batch_num}/{total_batches}: {error_msg}")
                    print(f"[SQL Semantic] ERROR: Database operational error in batch {batch_num}/{total_batches}: {error_msg}")
                    self._log_database_error("batch_update", batch_num, error_msg)
                    
                    # Rollback failed batch (Requirement 8.5)
                    try:
                        self.conn.rollback()
                        logger.info(f"[SQL Semantic] Rolled back batch {batch_num}")
                    except Exception as rollback_error:
                        logger.error(f"[SQL Semantic] Error rolling back batch {batch_num}: {rollback_error}")
                        self._log_database_error("rollback", batch_num, str(rollback_error))
                    
                    # Continue with next batch (Requirement 8.5)
                    continue
                
                except sqlite3.IntegrityError as e:
                    # Integrity constraint violation (Requirement 8.5)
                    update_errors += 1
                    error_msg = str(e)
                    logger.error(f"[SQL Semantic] Integrity error in batch {batch_num}/{total_batches}: {error_msg}")
                    print(f"[SQL Semantic] ERROR: Integrity error in batch {batch_num}/{total_batches}: {error_msg}")
                    self._log_database_error("batch_update", batch_num, error_msg)
                    
                    # Rollback failed batch (Requirement 8.5)
                    try:
                        self.conn.rollback()
                        logger.info(f"[SQL Semantic] Rolled back batch {batch_num}")
                    except Exception as rollback_error:
                        logger.error(f"[SQL Semantic] Error rolling back batch {batch_num}: {rollback_error}")
                        self._log_database_error("rollback", batch_num, str(rollback_error))
                    
                    # Continue with next batch (Requirement 8.5)
                    continue
                
                except sqlite3.DatabaseError as e:
                    # General database error (Requirement 8.5)
                    update_errors += 1
                    error_msg = str(e)
                    logger.error(f"[SQL Semantic] Database error in batch {batch_num}/{total_batches}: {error_msg}")
                    print(f"[SQL Semantic] ERROR: Database error in batch {batch_num}/{total_batches}: {error_msg}")
                    self._log_database_error("batch_update", batch_num, error_msg)
                    
                    # Rollback failed batch (Requirement 8.5)
                    try:
                        self.conn.rollback()
                        logger.info(f"[SQL Semantic] Rolled back batch {batch_num}")
                    except Exception as rollback_error:
                        logger.error(f"[SQL Semantic] Error rolling back batch {batch_num}: {rollback_error}")
                        self._log_database_error("rollback", batch_num, str(rollback_error))
                    
                    # Continue with next batch (Requirement 8.5)
                    continue
                    
            except Exception as e:
                # Catch any other unexpected errors (Requirement 8.5)
                update_errors += 1
                error_msg = str(e)
                logger.error(f"[SQL Semantic] Unexpected error updating batch {batch_num}/{total_batches}: {error_msg}", exc_info=True)
                print(f"[SQL Semantic] ERROR: Unexpected error in batch {batch_num}/{total_batches}: {error_msg}")
                self._log_database_error("batch_update", batch_num, error_msg)
                
                # Rollback failed batch (Requirement 8.5)
                try:
                    self.conn.rollback()
                    logger.info(f"[SQL Semantic] Rolled back batch {batch_num}")
                except Exception as rollback_error:
                    logger.error(f"[SQL Semantic] Error rolling back batch {batch_num}: {rollback_error}")
                    self._log_database_error("rollback", batch_num, str(rollback_error))
                
                # Continue with next batch (Requirement 8.5)
                continue
        
        # Final commit to ensure all successful batches are saved
        try:
            self.conn.commit()
            logger.info(f"[SQL Semantic] Final commit completed")
        except Exception as e:
            logger.error(f"[SQL Semantic] Error during final commit: {e}")
        
        elapsed = time.time() - start_time
        
        print("")
        print(f"[SQL Semantic] Database update complete in {elapsed:.2f} seconds")
        print(f"[SQL Semantic] Successfully updated {successful_updates:,} matches with semantic data")
        
        if update_errors > 0:
            print(f"[SQL Semantic] WARNING: {update_errors} batch errors occurred during database update")
            logger.warning(f"[SQL Semantic] {update_errors} batch errors during database update")
        
        logger.info(f"[SQL Semantic] Database update complete: {successful_updates} matches updated in {elapsed:.2f}s")
        
        return successful_updates
    
    def apply_semantic_mapping(self, rules: List[Any]) -> Dict[str, Any]:
        """
        Apply semantic mapping using SQL-based approach with proper regex matching.
        
        Args:
            rules: List of semantic rules
            
        Returns:
            Statistics dictionary
        """
        total_start = time.time()
        
        try:
            self.connect()
            
            # Get total match count for statistics
            self.cursor.execute("""
                SELECT COUNT(*)
                FROM matches m
                INNER JOIN results r ON m.result_id = r.result_id
                WHERE r.execution_id = ?
            """, (self.execution_id,))
            total_matches = self.cursor.fetchone()[0]
            
            # Step 1: Create semantic rules table
            rule_count = self.create_semantic_rules_table(rules)
            
            # Step 2: Find matches using proper regex matching
            matches_with_rules = self.find_matches_with_semantic_rules()
            
            # Step 3: Build and update semantic data
            matches_updated = self.build_and_update_semantic_data(matches_with_rules)
            
            total_time = time.time() - total_start
            
            print(f"\n{'='*80}")
            print(f"[SQL Semantic] COMPLETE in {total_time:.2f} seconds")
            print(f"{'='*80}")
            print(f"  Rules indexed: {rule_count:,}")
            print(f"  Total matches: {total_matches:,}")
            print(f"  Matches with semantic data: {matches_updated:,}")
            print(f"  Semantic coverage: {matches_updated/total_matches*100:.1f}%")
            print(f"  Matches without semantic data: {total_matches - matches_updated:,}")
            print(f"  Processing time: {total_time:.2f} seconds")
            print(f"  Throughput: {matches_updated/total_time:.0f} matches/second")
            print(f"{'='*80}\n")
            
            # Log summary statistics to debug file
            summary_stats = {
                'rules_evaluated': rule_count,
                'matches_found': matches_updated,
                'processing_time': total_time,
                'throughput': matches_updated/total_time if total_time > 0 else 0
            }
            self._log_summary(summary_stats)
            
            return {
                'identities_processed': matches_updated,
                'mappings_applied': matches_updated,
                'matches_updated': matches_updated,
                'processing_time': total_time,
                'rules_indexed': rule_count,
                'total_matches': total_matches,
                'semantic_coverage_percent': matches_updated/total_matches*100 if total_matches > 0 else 0
            }
            
        finally:
            self.close()
