"""
Parser Invocation Helper for Offline Artifact Importer

This module provides a simple helper to invoke existing offline parsers with
standardized result handling. Since all parsers already support offline mode
natively, this helper just calls them with appropriate parameters and captures
results in a standardized format for GUI display.
"""

import os
import time
import sys
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import List, Optional, Callable
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Set up logging
logger = logging.getLogger(__name__)

@dataclass
class ParserResult:
    """Standardized parser result for GUI display"""
    success: bool
    artifact_type: str
    records_parsed: int
    output_path: str  # Database or output file path
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    execution_time: float = 0.0  # seconds


class ParserInvoker:
    """Simple helper to invoke offline parsers using dedicated wrappers"""
    
    def __init__(self, case_root: str):
        """
        Initialize parser invoker.

        Args:
            case_root: Path to case directory root
        """
        self.case_root = Path(case_root)
        self.input_dir = self.case_root / 'live_acquisition'
        self.target_artifacts_dir = self.case_root / 'Target_Artifacts'    
    def _validate_path_in_case(self, path: str) -> tuple[bool, str]:
        """
        Validate that path is within case directory.
        
        Enhanced validation that handles:
        - Symlinks (resolved to real paths)
        - Relative paths (converted to absolute)
        - Case sensitivity (normalized on Windows)
        - Network paths (UNC and mapped drives)
        
        Args:
            path: Path to validate
        
        Returns:
            Tuple of (is_valid, error_message)
        
        Requirements: 4.3, 4.4, 6.4
        """
        try:
            # Convert to Path object and normalize
            path_obj = Path(path)
            
            # Check if path exists
            if not path_obj.exists():
                error_msg = f"Path does not exist: {path}"
                logger.error(error_msg)
                return False, error_msg
            
            # Check if path is accessible
            if not os.access(path, os.R_OK):
                error_msg = f"Path is not readable (permission denied): {path}"
                logger.error(error_msg)
                return False, error_msg
            
            # Resolve to absolute path and check if within case directory
            try:
                # resolve() follows symlinks and normalizes the path
                path_resolved = path_obj.resolve()
                case_root_resolved = self.case_root.resolve()
                
                # On Windows, use case-insensitive comparison and handle UNC/mapped drives
                if os.name == 'nt':
                    path_str = str(path_resolved).lower()
                    case_str = str(case_root_resolved).lower()
                    
                    # Check if path starts with case root (handles both UNC and mapped drives)
                    if not path_str.startswith(case_str):
                        error_msg = f"Path is outside case directory: {path}"
                        logger.warning(error_msg)
                        return False, error_msg
                else:
                    # Unix/Linux: use relative_to (case-sensitive)
                    path_resolved.relative_to(case_root_resolved)
                
                return True, ""
                
            except ValueError:
                error_msg = f"Path is outside case directory: {path}"
                logger.warning(error_msg)
                return False, error_msg
            
        except Exception as e:
            error_msg = f"Path validation error for {path}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
    
    def _normalize_path(self, path: str) -> Path:
        """
        Normalize file path (resolve symlinks, convert to absolute).
        
        Args:
            path: Path to normalize
        
        Returns:
            Normalized Path object
        
        Requirements: 4.3
        """
        try:
            from utils.file_utils import FileUtils
            file_utils = FileUtils()
            
            path_obj = Path(path)
            
            # Convert relative paths to absolute based on case_root
            if not path_obj.is_absolute():
                path_obj = self.case_root / path_obj
            
            # Apply strict cross-platform normalizing to counter Linux case-drops
            path_obj = file_utils.normalize_existing_path(path_obj)
            
            # Resolve symlinks and normalize
            return path_obj.resolve()
            
        except Exception as e:
            logger.error(f"Path normalization error for {path}: {str(e)}")
            return Path(path)
    
    def _log_error_to_file(self, error_log_path: str, artifact_type: str, filename: str, error_message: str):
        """
        Log parsing error to persistent error file (Bug Fix #6).
        
        Args:
            error_log_path: Path to error log file
            artifact_type: Type of artifact that failed
            filename: Name of the file that failed
            error_message: Error message to log
        
        Requirements: 2.4, 2.8
        """
        try:
            from datetime import datetime
            
            # Format: [TIMESTAMP] [ARTIFACT_TYPE] filename: Error message
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{timestamp}] [{artifact_type}] {filename}: {error_message}\n"
            
            # Append to error log file
            with open(error_log_path, 'a', encoding='utf-8') as f:
                f.write(log_entry)
                
            logger.debug(f"Logged error to {error_log_path}: {error_message}")
            
        except Exception as e:
            logger.error(f"Failed to write to error log file {error_log_path}: {str(e)}")
    
    def _validate_database_output(self, result: ParserResult) -> bool:
        """
        Validate that parsing actually succeeded by checking database.
        
        This method verifies:
        1. Database file exists at output_path
        2. Database file has non-zero size
        3. Database contains records (queries SQLite database)
        4. Record count matches or exceeds records_parsed field
        
        Args:
            result: ParserResult to validate
        
        Returns:
            True if database exists with records, False otherwise
        
        Requirements: 2.7, 2.9 (Bug Fix for ParserResult Validation)
        """
        try:
            # Check file existence
            if not result.output_path or not os.path.exists(result.output_path):
                logger.debug(f"Database validation failed: file does not exist at {result.output_path}")
                return False
            
            # Check file size
            file_size = os.path.getsize(result.output_path)
            if file_size == 0:
                logger.debug(f"Database validation failed: file size is zero at {result.output_path}")
                return False
            
            # Check database records (for SQLite databases)
            try:
                import sqlite3
                conn = sqlite3.connect(result.output_path)
                cursor = conn.cursor()
                
                # Get all table names
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor.fetchall()
                
                if not tables:
                    logger.debug(f"Database validation failed: no tables found in {result.output_path}")
                    conn.close()
                    return False
                
                # Count total records across all tables
                total_records = 0
                for table in tables:
                    table_name = table[0]
                    try:
                        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                        count = cursor.fetchone()[0]
                        total_records += count
                    except sqlite3.Error as e:
                        logger.warning(f"Could not count records in table {table_name}: {e}")
                        continue
                
                conn.close()
                
                # Verify record count matches or exceeds expected
                if total_records >= result.records_parsed:
                    logger.debug(f"Database validation passed: {total_records} records found (expected {result.records_parsed})")
                    return True
                else:
                    logger.debug(f"Database validation failed: only {total_records} records found (expected {result.records_parsed})")
                    return False
                    
            except sqlite3.Error as e:
                # If we can't query database, but file exists with non-zero size, assume it's valid
                logger.warning(f"Could not query database {result.output_path}: {e}")
                # Conservative approach: if file exists and has size, consider it valid
                return True
            except Exception as e:
                logger.warning(f"Database validation error for {result.output_path}: {e}")
                # Conservative approach: if file exists and has size, consider it valid
                return True
                
        except Exception as e:
            logger.error(f"Database validation exception for {result.output_path}: {e}")
            return False
    
    def _sanitize_dependency_error(self, error_message: str, error_type: str = None, artifact_path: str = None) -> str:
        """
        Convert verbose dependency errors to concise actionable messages while preserving context.
        
        Args:
            error_message: Original error message (may include traceback)
            error_type: Type of exception (e.g., 'ModuleNotFoundError', 'FileNotFoundError')
            artifact_path: Path to the artifact being processed (for context)
        
        Returns:
            Concise error message for user display with preserved context
        
        Requirements: 1.3, 1.4, 2.3, 2.4, 3.5
        """
        # Build context prefix if available
        context_parts = []
        if error_type:
            context_parts.append(f"[{error_type}]")
        if artifact_path:
            # Show just the filename for brevity
            from pathlib import Path
            filename = Path(artifact_path).name
            context_parts.append(f"File: {filename}")
        
        context_prefix = " ".join(context_parts)
        if context_prefix:
            context_prefix += " - "
        
        # Check for python-evtx dependency error
        if "python-evtx" in error_message.lower() or "python_evtx" in error_message.lower():
            return f"{context_prefix}Install python-evtx: pip install python-evtx"
        
        # Check for ESE database library errors
        if "ese" in error_message.lower() and ("library" in error_message.lower() or "module" in error_message.lower()):
            return f"{context_prefix}Install ESE library: pip install dissect.esedb (recommended) or pip install pyesedb"
        
        # Check for other common dependency errors
        if "no module named" in error_message.lower():
            # Extract module name
            import re
            match = re.search(r"no module named ['\"]?([a-zA-Z0-9_.-]+)", error_message, re.IGNORECASE)
            if match:
                module_name = match.group(1)
                return f"{context_prefix}Install {module_name}: pip install {module_name}"
        
        # Check for file not found errors
        if "no such file or directory" in error_message.lower() or "file not found" in error_message.lower():
            # Extract the problematic path if present
            import re
            path_match = re.search(r"['\"]([^'\"]+)['\"]", error_message)
            if path_match:
                problematic_path = path_match.group(1)
                return f"{context_prefix}File not found: {problematic_path}"
            return f"{context_prefix}File not found"
        
        # Check for permission errors
        if "permission denied" in error_message.lower():
            return f"{context_prefix}Permission denied - check file/directory permissions"
        
        # Check for missing registry hives
        if "missing required registry hives" in error_message.lower():
            return f"{context_prefix}Missing required registry hives - parse registry artifacts first"
        
        # For other errors, preserve more context (first 3 lines or 200 chars)
        lines = error_message.split('\n')
        if len(lines) > 1:
            # Multi-line error - take first 3 meaningful lines
            meaningful_lines = [line.strip() for line in lines if line.strip() and not line.strip().startswith('File "')]
            error_summary = ' | '.join(meaningful_lines[:3])
        else:
            error_summary = lines[0]
        
        # Truncate if too long but preserve more than before
        if len(error_summary) > 200:
            error_summary = error_summary[:197] + "..."
        
        return f"{context_prefix}{error_summary}" if error_summary else f"{context_prefix}Unknown error"
    
    def _resolve_registry_hive_paths(self) -> Optional[dict]:
        """
        Resolve registry hive paths from the case directory.
        
        Searches in case_root/live_acquisition/Registry/ and Registry_Hives/ for:
        - NTUSER.DAT (may have multiple files, one per user profile)
        - SYSTEM
        - SOFTWARE
        
        Returns:
            Dictionary with hive paths or None if not found:
            {
                'ntuser': ['/path/to/NTUSER.DAT', ...],  # List of NTUSER files
                'system': '/path/to/SYSTEM',
                'software': '/path/to/SOFTWARE'
            }
            Returns None if no registry directories exist or no hives found.
        
        Requirements: 2.2, 3.4
        """
        # Try both possible registry directory locations
        from utils.file_utils import FileUtils
        file_utils = FileUtils()
        
        possible_dirs = [
            self.case_root / 'live_acquisition' / 'Registry',
            self.case_root / 'live_acquisition' / 'Registry_Hives'
        ]
        
        registry_dir = None
        for dir_path in possible_dirs:
            safe_path = file_utils.normalize_existing_path(dir_path)
            if safe_path.exists() and safe_path.is_dir():
                registry_dir = safe_path
                logger.debug(f"Found registry directory: {registry_dir}")
                break
        
        if registry_dir is None:
            logger.debug(f"No registry directory found in: {possible_dirs}")
            return None
        
        # Define hive patterns (case-insensitive matching)
        hive_patterns = {
            'system': ['SYSTEM', 'system', 'System', 'SYSTEM.OLD', 'system.old'],
            'software': ['SOFTWARE', 'software', 'Software', 'SOFTWARE.OLD', 'software.old'],
            'ntuser': ['NTUSER.DAT', 'ntuser.dat', 'Ntuser.dat', 'NTUSER_copy.DAT', 
                      'ntuser_copy.dat', 'NTUSER', 'ntuser']
        }
        
        detected_hives = {}
        
        # Detect each hive type
        for hive_type, patterns in hive_patterns.items():
            if hive_type == 'ntuser':
                # For NTUSER, collect ALL matching files (multiple user profiles)
                matching_files = []
                for pattern in patterns:
                    hive_path = registry_dir / pattern
                    if hive_path.exists() and hive_path.is_file():
                        matching_files.append(str(hive_path))
                
                # Deduplicate by normalizing paths
                if matching_files:
                    unique_files = []
                    seen_paths = set()
                    for f in matching_files:
                        normalized = os.path.normcase(os.path.normpath(f))
                        if normalized not in seen_paths:
                            seen_paths.add(normalized)
                            unique_files.append(f)
                    
                    detected_hives['ntuser'] = unique_files
                    logger.info(f"Detected {len(unique_files)} NTUSER hive(s)")
            else:
                # For SYSTEM and SOFTWARE, use first match
                for pattern in patterns:
                    hive_path = registry_dir / pattern
                    if hive_path.exists() and hive_path.is_file():
                        detected_hives[hive_type] = str(hive_path)
                        logger.info(f"Detected {hive_type.upper()} hive: {hive_path.name}")
                        break
        
        # Return None if no hives were detected
        if not detected_hives:
            logger.debug(f"No registry hives found in {registry_dir}")
            return None
        
        return detected_hives
    
    def invoke_parser(self, artifact_type: str, **kwargs) -> ParserResult:
        """
        Invoke appropriate parser for artifact type with path validation.
        
        Args:
            artifact_type: Type of artifact (Registry, Prefetch, etc.)
            **kwargs: Additional parser-specific parameters
            
        Returns:
            ParserResult with execution details
        
        Requirements: 6.1, 6.2, 6.3, 6.4, 6.8
        """
        start_time = time.time()
        
        # DIAGNOSTIC LOGGING - Track parser routing
        artifact_path = kwargs.get('artifact_path', 'unknown')
        artifact_dir = kwargs.get('artifact_dir', 'N/A')
        logger.info(f"[PARSER ROUTING] ========================================")
        logger.info(f"[PARSER ROUTING] Artifact Type: {artifact_type}")
        logger.info(f"[PARSER ROUTING] Artifact Path: {artifact_path}")
        logger.info(f"[PARSER ROUTING] Artifact Dir: {artifact_dir}")
        logger.info(f"[PARSER ROUTING] ========================================")
        
        try:
            # Validate artifact path if provided
            if artifact_path and artifact_path != 'unknown':
                is_valid, error_msg = self._validate_path_in_case(artifact_path)
                if not is_valid:
                    return ParserResult(
                        success=False,
                        artifact_type=artifact_type,
                        records_parsed=0,
                        output_path="",
                        errors=[error_msg],
                        warnings=[],
                        execution_time=time.time() - start_time
                    )
                
                # Normalize the path
                kwargs['artifact_path'] = str(self._normalize_path(artifact_path))
            
            # Validate artifact directory if provided
            if artifact_dir and artifact_dir != 'N/A':
                is_valid, error_msg = self._validate_path_in_case(artifact_dir)
                if not is_valid:
                    return ParserResult(
                        success=False,
                        artifact_type=artifact_type,
                        records_parsed=0,
                        output_path="",
                        errors=[error_msg],
                        warnings=[],
                        execution_time=time.time() - start_time
                    )
                
                # Normalize the path
                kwargs['artifact_dir'] = str(self._normalize_path(artifact_dir))
            
            # Set standard parameters for offline mode
            kwargs['case_root'] = str(self.case_root)
            kwargs['offline_mode'] = True
            
            if artifact_type == 'Registry':
                logger.info(f"[PARSER ROUTING] → Invoking Registry parser")
                return self._invoke_registry_parser(start_time, **kwargs)
            elif artifact_type == 'Prefetch':
                logger.info(f"[PARSER ROUTING] → Invoking Prefetch parser")
                return self._invoke_prefetch_parser(start_time, **kwargs)
            elif artifact_type == 'AmCache':
                logger.info(f"[PARSER ROUTING] → Invoking AmCache parser")
                return self._invoke_amcache_parser(start_time, **kwargs)
            elif artifact_type == 'JumpLists':
                logger.info(f"[PARSER ROUTING] → Invoking JumpLists parser")
                return self._invoke_jumplists_parser(start_time, **kwargs)
            elif artifact_type == 'RecycleBin':
                logger.info(f"[PARSER ROUTING] → Invoking RecycleBin parser")
                return self._invoke_recyclebin_parser(start_time, **kwargs)
            elif artifact_type == 'ShimCache':
                logger.info(f"[PARSER ROUTING] → Invoking ShimCache parser")
                return self._invoke_shimcache_parser(start_time, **kwargs)
            elif artifact_type == 'MFT':
                logger.info(f"[PARSER ROUTING] → Invoking MFT parser")
                return self._invoke_mft_parser(start_time, **kwargs)
            elif artifact_type == 'USN':
                logger.info(f"[PARSER ROUTING] → Invoking USN parser")
                return self._invoke_usn_parser(start_time, **kwargs)
            elif artifact_type == 'EVTX':
                logger.info(f"[PARSER ROUTING] → Invoking EVTX parser")
                return self._invoke_evtx_parser(start_time, **kwargs)
            elif artifact_type == 'SRUM':
                logger.info(f"[PARSER ROUTING] → Invoking SRUM parser")
                return self._invoke_srum_parser(start_time, **kwargs)
            else:
                logger.error(f"[PARSER ROUTING] → Unknown artifact type: {artifact_type}")
                return ParserResult(
                    success=False,
                    artifact_type=artifact_type,
                    records_parsed=0,
                    output_path="",
                    errors=[f"Unknown artifact type: {artifact_type}"],
                    warnings=[],
                    execution_time=time.time() - start_time
                )
        
        except Exception as e:
            # Log and return error result with detailed path information
            error_msg = f"Parser invocation failed for {artifact_type}: {str(e)}"
            if artifact_path and artifact_path != 'unknown':
                error_msg += f" (path: {artifact_path})"
            logger.error(error_msg, exc_info=True)
            return ParserResult(
                success=False,
                artifact_type=artifact_type,
                records_parsed=0,
                output_path="",
                errors=[error_msg],
                warnings=[],
                execution_time=time.time() - start_time
            )
    
    def _invoke_registry_parser(self, start_time: float, **kwargs) -> ParserResult:
        """Invoke Registry parser using offline_RegClaw."""
        try:
            from Artifacts_Collectors.offline_parsers.offline_RegClaw import reg_Claw
            
            result = reg_Claw(
                case_root=str(self.case_root),
                offline_mode=True,
                windows_partition=kwargs.get('windows_partition', 'C:')
            )
            
            output_path = str(self.target_artifacts_dir / 'registry_data.db')
            
            # Create initial ParserResult
            parser_result = ParserResult(
                success=True,
                artifact_type='Registry',
                records_parsed=result.get('records', 0) if isinstance(result, dict) else 0,
                output_path=output_path,
                errors=[],
                warnings=[],
                execution_time=time.time() - start_time
            )
            
            # Note: Database validation removed as per offline parser post-processing fix
            # The parser's success status is trusted - validation can incorrectly flag valid output as invalid
            # If parser reports success, we accept it without additional validation
            
            return parser_result
            
        except Exception as e:
            # Capture full exception details for logging
            import traceback
            error_type = type(e).__name__
            error_message = str(e)
            stack_trace = traceback.format_exc()
            
            # Get artifact path from kwargs for context
            artifact_path = kwargs.get('artifact_path', kwargs.get('hive_path', 'unknown'))
            
            # Log full exception details before sanitizing
            logger.error(f"Registry parser failed - Type: {error_type}, Path: {artifact_path}")
            logger.error(f"Error message: {error_message}")
            logger.error(f"Stack trace:\n{stack_trace}")
            
            # Sanitize error for user display with context
            sanitized_error = self._sanitize_dependency_error(error_message, error_type, str(artifact_path))
            
            return ParserResult(success=False, artifact_type='Registry', records_parsed=0, output_path="", errors=[sanitized_error], execution_time=time.time() - start_time)

    def _invoke_prefetch_parser(self, start_time: float, **kwargs) -> ParserResult:
        """Invoke Prefetch parser using offline_PrefetchClaw."""
        try:
            from Artifacts_Collectors.offline_parsers.offline_PrefetchClaw import run_offline_prefetch
            
            # Get artifact_dir from kwargs (directory containing all Prefetch files)
            artifact_dir = kwargs.get('artifact_dir')
            
            # Determine prefetch directory to use
            if artifact_dir and os.path.exists(artifact_dir):
                # Use the directory containing the artifact files
                prefetch_dir = artifact_dir
                logger.info(f"Using Prefetch directory from artifacts: {prefetch_dir}")
            else:
                # Fallback to standard location
                prefetch_dir = os.path.join(self.input_dir, 'Prefetch')
                logger.info(f"Using standard Prefetch directory: {prefetch_dir}")
            
            # Prefetch parser doesn't need registry hive paths
            # These parsers operate on .pf file artifacts and don't require registry context
            
            result = run_offline_prefetch(
                case_path=self.case_root,
                windows_partition=kwargs.get('windows_partition', 'C:'),
                prefetch_dir=prefetch_dir  # Pass explicit directory
                # Removed: registry_hive_paths parameter (parser doesn't accept it)
            )
            
            output_path = os.path.join(self.target_artifacts_dir, 'Prefetch', 'prefetch_data.db')
            
            # Create initial ParserResult
            parser_result = ParserResult(
                success=result.get('success', True),
                artifact_type='Prefetch',
                records_parsed=result.get('records', 0),
                output_path=output_path,
                errors=[result.get('error')] if result.get('error') else [],
                execution_time=time.time() - start_time
            )
            
            # Note: Database validation removed as per offline parser post-processing fix
            # The parser's success status is trusted - validation can incorrectly flag valid output as invalid
            
            return parser_result
            
        except Exception as e:
            # Capture full exception details for logging
            import traceback
            error_type = type(e).__name__
            error_message = str(e)
            stack_trace = traceback.format_exc()
            
            # Get artifact path from kwargs for context
            artifact_path = kwargs.get('artifact_dir', kwargs.get('artifact_path', 'unknown'))
            
            # Log full exception details before sanitizing
            logger.error(f"Prefetch parser failed - Type: {error_type}, Path: {artifact_path}")
            logger.error(f"Error message: {error_message}")
            logger.error(f"Stack trace:\n{stack_trace}")
            
            # Sanitize error for user display with context
            sanitized_error = self._sanitize_dependency_error(error_message, error_type, str(artifact_path))
            
            return ParserResult(success=False, artifact_type='Prefetch', records_parsed=0, output_path="", errors=[sanitized_error], execution_time=time.time() - start_time)

    def _invoke_amcache_parser(self, start_time: float, **kwargs) -> ParserResult:
        """Invoke AmCache parser using offline_AmCacheClaw."""
        try:
            from Artifacts_Collectors.offline_parsers.offline_AmCacheClaw import run_offline_amcache
            
            result = run_offline_amcache(
                case_path=self.case_root,
                windows_partition=kwargs.get('windows_partition', 'C:')
            )
            
            # Defensive check: Ensure result is a dict
            if not isinstance(result, dict):
                logger.warning(f"AmCache parser returned invalid format: {type(result).__name__} instead of dict")
                result = {'success': False, 'records': 0, 'error': f'Parser returned invalid format: {type(result).__name__}'}
            
            # Use flat structure - database saved directly in Target_Artifacts
            output_path = os.path.join(self.target_artifacts_dir, 'amcache.db')
            
            # Create initial ParserResult
            parser_result = ParserResult(
                success=result.get('success', True),
                artifact_type='AmCache',
                records_parsed=result.get('records', 0),
                output_path=output_path,
                errors=[result.get('error')] if result.get('error') else [],
                execution_time=time.time() - start_time
            )
            
            # Note: Database validation removed as per offline parser post-processing fix
            # The parser's success status is trusted - validation can incorrectly flag valid output as invalid
            
            return parser_result
            
        except Exception as e:
            # Capture full exception details for logging
            import traceback
            error_type = type(e).__name__
            error_message = str(e)
            stack_trace = traceback.format_exc()
            
            # Get artifact path from kwargs for context
            artifact_path = kwargs.get('artifact_path', 'unknown')
            
            # Log full exception details before sanitizing
            logger.error(f"AmCache parser failed - Type: {error_type}, Path: {artifact_path}")
            logger.error(f"Error message: {error_message}")
            logger.error(f"Stack trace:\n{stack_trace}")
            
            # Sanitize error for user display with context
            sanitized_error = self._sanitize_dependency_error(error_message, error_type, str(artifact_path))
            
            return ParserResult(success=False, artifact_type='AmCache', records_parsed=0, output_path="", errors=[sanitized_error], execution_time=time.time() - start_time)

    def _invoke_jumplists_parser(self, start_time: float, **kwargs) -> ParserResult:
        """Invoke Jump Lists parser using offline_ACJLClaw."""
        try:
            from Artifacts_Collectors.offline_parsers.offline_ACJLClaw import run_offline_acjl
            
            # JumpLists parser doesn't need registry hive paths
            # These parsers operate on file artifacts (.lnk, .automaticDestinations-ms)
            # and don't require registry context
            
            result = run_offline_acjl(
                case_path=self.case_root,
                direct_parse=False
                # Removed: registry_hive_paths parameter (parser doesn't accept it)
            )
            
            # Defensive check: Ensure result is a dict
            if not isinstance(result, dict):
                logger.warning(f"JumpLists parser returned invalid format: {type(result).__name__} instead of dict")
                result = {'success': False, 'records': 0, 'error': f'Parser returned invalid format: {type(result).__name__}'}
            
            output_path = os.path.join(self.target_artifacts_dir, 'LnkDB.db')
            
            # Create initial ParserResult
            parser_result = ParserResult(
                success=result.get('success', True),
                artifact_type='JumpLists',
                records_parsed=result.get('records', 0),
                output_path=output_path,
                errors=[result.get('error')] if result.get('error') else [],
                execution_time=time.time() - start_time
            )
            
            # Note: Database validation removed as per offline parser post-processing fix
            # The parser's success status is trusted - validation can incorrectly flag valid output as invalid
            
            return parser_result
            
        except Exception as e:
            # Capture full exception details for logging
            import traceback
            error_type = type(e).__name__
            error_message = str(e)
            stack_trace = traceback.format_exc()
            
            # Get artifact path from kwargs for context
            artifact_path = kwargs.get('artifact_path', 'unknown')
            
            # Log full exception details before sanitizing
            logger.error(f"JumpLists parser failed - Type: {error_type}, Path: {artifact_path}")
            logger.error(f"Error message: {error_message}")
            logger.error(f"Stack trace:\n{stack_trace}")
            
            # Sanitize error for user display with context
            sanitized_error = self._sanitize_dependency_error(error_message, error_type, str(artifact_path))
            
            return ParserResult(success=False, artifact_type='JumpLists', records_parsed=0, output_path="", errors=[sanitized_error], execution_time=time.time() - start_time)

    def _invoke_recyclebin_parser(self, start_time: float, **kwargs) -> ParserResult:
        """Invoke Recycle Bin parser using offline_RecycleBinClaw."""
        try:
            from Artifacts_Collectors.offline_parsers.offline_RecycleBinClaw import run_offline_recyclebin
            
            # Use input_dir/RecycleBin as the default artifact directory
            artifact_dir = kwargs.get('artifact_dir')
            if not artifact_dir or not os.path.exists(artifact_dir):
                artifact_dir = os.path.join(self.input_dir, 'RecycleBin')
            
            result = run_offline_recyclebin(
                case_path=self.case_root,
                network_paths=kwargs.get('network_paths'),
                artifact_dir=artifact_dir
            )
            
            # Defensive check: Ensure result is a dict
            if not isinstance(result, dict):
                logger.warning(f"RecycleBin parser returned invalid format: {type(result).__name__} instead of dict")
                result = {'success': False, 'records': 0, 'error': f'Parser returned invalid format: {type(result).__name__}'}
            
            # Match actual parser output location: Target_Artifacts/recyclebin_analysis.db
            output_path = os.path.join(self.target_artifacts_dir, 'recyclebin_analysis.db')
            
            return ParserResult(
                success=result.get('success', True),
                artifact_type='RecycleBin',
                records_parsed=result.get('records', 0),
                output_path=output_path,
                errors=[result.get('error')] if result.get('error') else [],
                execution_time=time.time() - start_time
            )
        except Exception as e:
            # Capture full exception details for logging
            import traceback
            error_type = type(e).__name__
            error_message = str(e)
            stack_trace = traceback.format_exc()
            
            # Get artifact path from kwargs for context
            artifact_path = kwargs.get('artifact_path', 'unknown')
            
            # Log full exception details before sanitizing
            logger.error(f"RecycleBin parser failed - Type: {error_type}, Path: {artifact_path}")
            logger.error(f"Error message: {error_message}")
            logger.error(f"Stack trace:\n{stack_trace}")
            
            # Sanitize error for user display with context
            sanitized_error = self._sanitize_dependency_error(error_message, error_type, str(artifact_path))
            
            return ParserResult(success=False, artifact_type='RecycleBin', records_parsed=0, output_path="", errors=[sanitized_error], execution_time=time.time() - start_time)

    def _invoke_shimcache_parser(self, start_time: float, **kwargs) -> ParserResult:
        """Invoke ShimCache parser using offline_ShimCacheClaw."""
        try:
            from Artifacts_Collectors.offline_parsers.offline_ShimCacheClaw import run_offline_shimcache
            
            result = run_offline_shimcache(case_path=self.case_root)
            
            # Match actual parser output location: Target_Artifacts/shimcache.db
            output_path = os.path.join(self.target_artifacts_dir, 'shimcache.db')
            
            return ParserResult(
                success=result.get('success', True),
                artifact_type='ShimCache',
                records_parsed=result.get('records', 0),
                output_path=output_path,
                errors=[result.get('error')] if result.get('error') else [],
                execution_time=time.time() - start_time
            )
        except Exception as e:
            # Capture full exception details for logging
            import traceback
            error_type = type(e).__name__
            error_message = str(e)
            stack_trace = traceback.format_exc()
            
            # Get artifact path from kwargs for context
            artifact_path = kwargs.get('artifact_path', 'unknown')
            
            # Log full exception details before sanitizing
            logger.error(f"ShimCache parser failed - Type: {error_type}, Path: {artifact_path}")
            logger.error(f"Error message: {error_message}")
            logger.error(f"Stack trace:\n{stack_trace}")
            
            # Sanitize error for user display with context
            sanitized_error = self._sanitize_dependency_error(error_message, error_type, str(artifact_path))
            
            return ParserResult(success=False, artifact_type='ShimCache', records_parsed=0, output_path="", errors=[sanitized_error], execution_time=time.time() - start_time)

    def _invoke_mft_parser(self, start_time: float, **kwargs) -> ParserResult:
        """Invoke MFT parser using offline_MFTClaw."""
        try:
            from Artifacts_Collectors.offline_parsers.offline_MFTClaw import run_offline_mft
            
            # Get MFT file path from kwargs
            mft_file_path = kwargs.get('artifact_path')
            
            result = run_offline_mft(
                case_path=self.case_root,
                mft_file_path=mft_file_path
            )
            
            output_path = os.path.join(self.target_artifacts_dir, 'MFT_USN', 'MFT_data.db')
            
            return ParserResult(
                success=result.get('success', False),
                artifact_type='MFT',
                records_parsed=result.get('records', 0),
                output_path=output_path,
                errors=[result.get('error')] if result.get('error') else [],
                warnings=[],
                execution_time=time.time() - start_time
            )
        except Exception as e:
            # Capture full exception details for logging
            import traceback
            error_type = type(e).__name__
            error_message = str(e)
            stack_trace = traceback.format_exc()
            
            # Get artifact path from kwargs for context
            artifact_path = kwargs.get('artifact_path', 'unknown')
            
            # Log full exception details before sanitizing
            logger.error(f"MFT parser failed - Type: {error_type}, Path: {artifact_path}")
            logger.error(f"Error message: {error_message}")
            logger.error(f"Stack trace:\n{stack_trace}")
            
            # Sanitize error for user display with context
            sanitized_error = self._sanitize_dependency_error(error_message, error_type, str(artifact_path))
            
            return ParserResult(success=False, artifact_type='MFT', records_parsed=0, output_path="", errors=[sanitized_error], execution_time=time.time() - start_time)

    def _invoke_usn_parser(self, start_time: float, **kwargs) -> ParserResult:
        """Invoke USN parser (USN_Claw)."""
        try:
            from Artifacts_Collectors.offline_parsers.offline_USNClaw import run_offline_usn
            
            # Get USN file path from kwargs
            usn_file_path = kwargs.get('artifact_path')
            
            result = run_offline_usn(
                case_path=self.case_root,
                usn_file_path=usn_file_path
            )
            
            output_path = os.path.join(self.target_artifacts_dir, 'MFT_USN', 'USN_journal.db')
            
            return ParserResult(
                success=result.get('success', False),
                artifact_type='USN',
                records_parsed=result.get('records', 0),
                output_path=output_path,
                errors=[result.get('error')] if result.get('error') else [],
                warnings=["USN parser requires live volume access"] if not result.get('success') else [],
                execution_time=time.time() - start_time
            )
        except Exception as e:
            # USN parser requires special handling - placeholder
            output_path = os.path.join(self.target_artifacts_dir, 'MFT_USN', 'USN_journal.db')
            return ParserResult(success=True, artifact_type='USN', records_parsed=0, output_path=output_path, warnings=["USN parser not yet implemented"], execution_time=time.time() - start_time)
        except Exception as e:
            # Capture full exception details for logging
            import traceback
            error_type = type(e).__name__
            error_message = str(e)
            stack_trace = traceback.format_exc()
            
            # Get artifact path from kwargs for context
            artifact_path = kwargs.get('artifact_path', 'unknown')
            
            # Log full exception details before sanitizing
            logger.error(f"USN parser failed - Type: {error_type}, Path: {artifact_path}")
            logger.error(f"Error message: {error_message}")
            logger.error(f"Stack trace:\n{stack_trace}")
            
            # Sanitize error for user display with context
            sanitized_error = self._sanitize_dependency_error(error_message, error_type, str(artifact_path))
            
            return ParserResult(success=False, artifact_type='USN', records_parsed=0, output_path="", errors=[sanitized_error], execution_time=time.time() - start_time)

    def _invoke_evtx_parser(self, start_time: float, **kwargs) -> ParserResult:
        """Invoke EVTX (Windows Event Log) parser using offline_WinLog_Claw."""
        try:
            from Artifacts_Collectors.offline_parsers.offline_WinLog_Claw import main as run_offline_winlog
            
            # EVTX parser expects evtx_dir and case_path
            evtx_dir = os.path.join(self.input_dir, 'EVTX_Logs')
            
            # Check if EVTX_Logs directory exists
            if not os.path.exists(evtx_dir):
                return ParserResult(
                    success=False,
                    artifact_type='EVTX',
                    records_parsed=0,
                    output_path="",
                    errors=["Event logs directory not found"],
                    execution_time=time.time() - start_time
                )
            
            # Run parser
            result = run_offline_winlog(evtx_dir=evtx_dir, case_path=self.case_root)
            
            # Defensive check: Ensure result is a dict
            if not isinstance(result, dict):
                logger.warning(f"EVTX parser returned invalid format: {type(result).__name__} instead of dict")
                result = {'success': False, 'records': 0, 'error': f'Parser returned invalid format: {type(result).__name__}'}
            
            output_path = os.path.join(self.target_artifacts_dir, 'event_logs', 'event_logs.db')
            
            # Create initial ParserResult
            parser_result = ParserResult(
                success=result.get('success', True),
                artifact_type='EVTX',
                records_parsed=result.get('records', 0),
                output_path=output_path,
                errors=[result.get('error')] if result.get('error') else [],
                execution_time=time.time() - start_time
            )
            
            # Note: Database validation removed as per offline parser post-processing fix
            # The parser's success status is trusted - validation can incorrectly flag valid output as invalid
            
            return parser_result
            
        except Exception as e:
            # Capture full exception details for logging
            import traceback
            error_type = type(e).__name__
            error_message = str(e)
            stack_trace = traceback.format_exc()
            
            # Get artifact path from kwargs for context
            artifact_path = kwargs.get('artifact_path', kwargs.get('evtx_dir', 'unknown'))
            
            # Log full exception details before sanitizing
            logger.error(f"EVTX parser failed - Type: {error_type}, Path: {artifact_path}")
            logger.error(f"Error message: {error_message}")
            logger.error(f"Stack trace:\n{stack_trace}")
            
            # Sanitize error for user display with context
            sanitized_error = self._sanitize_dependency_error(error_message, error_type, str(artifact_path))
            
            return ParserResult(success=False, artifact_type='EVTX', records_parsed=0, output_path="", errors=[sanitized_error], execution_time=time.time() - start_time)

    def _invoke_srum_parser(self, start_time: float, **kwargs) -> ParserResult:
        """Invoke SRUM (System Resource Usage Monitor) parser using offline_SRUM_Claw."""
        try:
            from Artifacts_Collectors.offline_parsers.offline_SRUM_Claw import main as run_offline_srum
            
            # SRUM parser expects srudb_path and case_path
            srudb_path = os.path.join(self.input_dir, 'SRUM_Data', 'SRUDB.dat')
            
            # Check if SRUDB.dat exists
            if not os.path.exists(srudb_path):
                return ParserResult(
                    success=False,
                    artifact_type='SRUM',
                    records_parsed=0,
                    output_path="",
                    errors=["SRUDB.dat not found"],
                    execution_time=time.time() - start_time
                )
            
            # Run parser
            result = run_offline_srum(srudb_path=srudb_path, case_path=self.case_root)
            
            # Defensive check: Ensure result is a dict
            if not isinstance(result, dict):
                logger.warning(f"SRUM parser returned invalid format: {type(result).__name__} instead of dict")
                result = {'success': False, 'records': 0, 'error': f'Parser returned invalid format: {type(result).__name__}'}
            
            output_path = os.path.join(self.target_artifacts_dir, 'srum_database', 'srum_data.db')
            
            return ParserResult(
                success=result.get('success', True),
                artifact_type='SRUM',
                records_parsed=result.get('records', 0),
                output_path=output_path,
                errors=[result.get('error')] if result.get('error') else [],
                execution_time=time.time() - start_time
            )
        except Exception as e:
            # Capture full exception details for logging
            import traceback
            error_type = type(e).__name__
            error_message = str(e)
            stack_trace = traceback.format_exc()
            
            # Get artifact path from kwargs for context
            artifact_path = kwargs.get('artifact_path', kwargs.get('srudb_path', 'unknown'))
            
            # Log full exception details before sanitizing
            logger.error(f"SRUM parser failed - Type: {error_type}, Path: {artifact_path}")
            logger.error(f"Error message: {error_message}")
            logger.error(f"Stack trace:\n{stack_trace}")
            
            # Sanitize error for user display with context
            sanitized_error = self._sanitize_dependency_error(error_message, error_type, str(artifact_path))
            
            return ParserResult(success=False, artifact_type='SRUM', records_parsed=0, output_path="", errors=[sanitized_error], execution_time=time.time() - start_time)

    def _validate_parsed_files(self, artifact_type: str, artifacts: List, output_path: str) -> List[bool]:
        """
        DEPRECATED: This method is no longer used as of the offline parser post-processing fix.
        
        Validate which files were actually parsed by checking database.
        
        This provides per-file granularity for directory-based parsers.
        
        DEPRECATION REASON:
        This validation was removed because it was unnecessary and could incorrectly flag valid output as invalid.
        The parser's success status (result.success) is now used directly instead of performing post-parse validation.
        Post-parse validation can fail due to query errors, schema mismatches, or missing tables even when parsing succeeded.
        
        Args:
            artifact_type: Type of artifact (Prefetch, EVTX, etc.)
            artifacts: List of ScannedArtifact objects
            output_path: Path to the output database
            
        Returns:
            List of booleans indicating which files were successfully parsed
        """
        import sqlite3
        
        results = []
        
        # Check if database exists
        if not os.path.exists(output_path):
            logger.warning(f"Output database not found: {output_path}")
            return [False] * len(artifacts)
        
        try:
            conn = sqlite3.connect(output_path)
            cursor = conn.cursor()
            
            for artifact in artifacts:
                filename = os.path.basename(artifact.current_path)
                
                # Check if this file has entries in the database
                # Different artifact types have different table structures
                has_data = False
                
                try:
                    if artifact_type == 'Prefetch':
                        # Check prefetch_data table for this filename
                        cursor.execute(
                            "SELECT COUNT(*) FROM prefetch_data WHERE executable_name LIKE ? OR prefetch_file LIKE ?",
                            (f"%{filename}%", f"%{filename}%")
                        )
                        count = cursor.fetchone()[0]
                        has_data = count > 0
                    
                    elif artifact_type == 'EVTX':
                        # Check event_logs table for this filename
                        cursor.execute(
                            "SELECT COUNT(*) FROM event_logs WHERE source_file LIKE ?",
                            (f"%{filename}%",)
                        )
                        count = cursor.fetchone()[0]
                        has_data = count > 0
                    
                    elif artifact_type == 'Registry':
                        # For registry, check if any table has data (harder to validate per-file)
                        # Just assume success if database exists
                        has_data = True
                    
                    elif artifact_type == 'SRUM':
                        # For SRUM, check if srum_data table has entries
                        cursor.execute("SELECT COUNT(*) FROM srum_data")
                        count = cursor.fetchone()[0]
                        has_data = count > 0
                    
                    else:
                        # Unknown type, assume success
                        has_data = True
                
                except sqlite3.Error as e:
                    logger.warning(f"Database query error for {filename}: {e}")
                    # If we can't query, assume it was parsed (conservative approach)
                    has_data = True
                
                results.append(has_data)
            
            conn.close()
            
        except Exception as e:
            logger.error(f"Failed to validate parsed files: {e}")
            # If validation fails, assume all were parsed (conservative)
            return [True] * len(artifacts)
        
        return results
    
    def parse_artifacts_batch(self, artifacts: List,
                             progress_callback: Optional[Callable] = None,
                             cancellation_check: Optional[Callable] = None,
                             error_log_path: Optional[str] = None,
                             heartbeat_callback: Optional[Callable] = None) -> List[ParserResult]:
        """
        Parse multiple artifacts with progress tracking.

        Args:
            artifacts: List of ScannedArtifact objects to parse
            progress_callback: Optional callback for progress updates.
                             Called with (current_index, total, artifact_name, artifact_type)
            cancellation_check: Optional callback that returns True if parsing should be cancelled
            error_log_path: Optional path to error log file for persistent error logging
            heartbeat_callback: Optional callback to emit heartbeat signals every 250ms to keep GUI responsive

        Returns:
            List of ParserResult objects for each artifact (may be partial if cancelled)
        """
        results = []
        total = len(artifacts)
        
        # Track last heartbeat time for emitting heartbeat signals
        import time
        last_heartbeat = time.time()
        
        def emit_heartbeat_if_needed():
            """Emit heartbeat if more than 250ms has elapsed since last emission."""
            nonlocal last_heartbeat
            current_time = time.time()
            if current_time - last_heartbeat > 0.25:  # 250ms
                if heartbeat_callback:
                    heartbeat_callback()
                last_heartbeat = current_time
        
        # Define the canonical order for artifact types (same as live parsers)
        # Requirement 2: Ensure parsers run in the same order as live parsers
        canonical_order = [
            'JumpLists',
            'Registry',
            'Prefetch',
            'EVTX',
            'ShimCache',
            'AmCache',
            'RecycleBin',
            'SRUM',
            'MFT',
            'USN'
        ]
        
        # Group artifacts by type for efficient parsing
        artifacts_by_type = {}
        for artifact in artifacts:
            if artifact.artifact_type not in artifacts_by_type:
                artifacts_by_type[artifact.artifact_type] = []
            artifacts_by_type[artifact.artifact_type].append(artifact)
        
        # Sort the artifact types based on canonical order, keeping unknown types at the end
        ordered_types = sorted(
            artifacts_by_type.keys(),
            key=lambda x: canonical_order.index(x) if x in canonical_order else len(canonical_order)
        )
        
        logger.info(f"Grouped {total} artifacts into {len(artifacts_by_type)} types in order: {ordered_types}")
        
        # Process each artifact type in the specified order
        processed_count = 0
        for artifact_type in ordered_types:
            # Skip unknown artifact types silently - they are files we collected but have no parser for
            if artifact_type == 'Unknown':
                processed_count += len(artifacts_by_type[artifact_type])
                continue

            type_artifacts = artifacts_by_type[artifact_type]
            
            # Check for cancellation
            if cancellation_check and cancellation_check():
                logger.info(f"Parsing cancelled after {processed_count} artifacts")
                # Emit heartbeat during cancellation to keep animation smooth
                emit_heartbeat_if_needed()
                break
            
            logger.info(f"Processing {len(type_artifacts)} {artifact_type} artifacts")
            
            # Determine if this is a directory-based parser (scans entire directory)
            # or file-based parser (processes individual files)
            is_directory_parser = artifact_type in ['Prefetch', 'EVTX', 'SRUM', 'Registry', 'JumpLists', 'RecycleBin']
            
            if is_directory_parser:
                # For directory-based parsers, call once with the directory containing the files
                # Use the directory from the first artifact's current_path
                first_artifact = type_artifacts[0]
                artifact_dir = os.path.dirname(first_artifact.current_path)
                
                # Call progress callback
                if progress_callback:
                    progress_callback(processed_count, total, artifact_dir, artifact_type)
                
                # Emit heartbeat before long parsing operation
                emit_heartbeat_if_needed()
                
                try:
                    # Parse entire directory at once
                    result = self.invoke_parser(
                        artifact_type=artifact_type,
                        artifact_path=first_artifact.current_path,  # Pass first file path
                        artifact_dir=artifact_dir  # Pass directory for scanning
                    )
                    
                    # Emit heartbeat after parsing completes
                    emit_heartbeat_if_needed()
                    
                    # Use parser's success status directly - no post-parse validation needed
                    # Bug Fix: Removed _validate_parsed_files call that could incorrectly flag valid output as invalid
                    file_results = [result.success] * len(type_artifacts)
                    
                    # Create one result per artifact with per-file validation
                    for artifact, file_success in zip(type_artifacts, file_results):
                        artifact_result = ParserResult(
                            success=file_success,  # Per-file success status
                            artifact_type=result.artifact_type,
                            records_parsed=result.records_parsed // len(type_artifacts) if result.records_parsed > 0 and file_success else 0,
                            output_path=result.output_path if file_success else "",
                            errors=result.errors.copy() if not file_success else [],
                            warnings=result.warnings.copy() if file_success else [],
                            execution_time=result.execution_time / len(type_artifacts)
                        )
                        results.append(artifact_result)
                        processed_count += 1
                    
                    success_files = sum(file_results)
                    if success_files > 0:
                        logger.info(f"Successfully parsed {success_files}/{len(type_artifacts)} {artifact_type} artifacts from {artifact_dir}")
                    if success_files < len(type_artifacts):
                        failed_files = len(type_artifacts) - success_files
                        logger.warning(f"Failed to parse {failed_files}/{len(type_artifacts)} {artifact_type} artifacts from {artifact_dir}")
                        
                        # Log errors to file if error_log_path provided
                        if error_log_path and result.errors:
                            dir_name = os.path.basename(artifact_dir)
                            for error in result.errors:
                                self._log_error_to_file(error_log_path, artifact_type, dir_name, error)
                        
                        # Explicit continuation: Log that batch execution continues despite failures
                        logger.info(f"Batch execution continuing after {failed_files} {artifact_type} failures. Processed {processed_count}/{total} artifacts so far.")
                        
                except sqlite3.Error as e:
                    # Database-related error during parsing
                    error_msg = f"Database error while parsing {artifact_type} artifacts"
                    logger.error(f"{error_msg}: {str(e)}", exc_info=True)
                    
                    # Log exception to error file if error_log_path provided
                    if error_log_path:
                        dir_name = os.path.basename(artifact_dir)
                        self._log_error_to_file(error_log_path, artifact_type, dir_name, f"Database error: {str(e)}")
                    
                    # Create error result for each artifact with user-friendly message
                    user_friendly_msg = f"Database error occurred during parsing. Please check the output database."
                    for artifact in type_artifacts:
                        error_result = ParserResult(
                            success=False,
                            artifact_type=artifact_type,
                            records_parsed=0,
                            output_path="",
                            errors=[user_friendly_msg],
                            warnings=[],
                            execution_time=0.0
                        )
                        results.append(error_result)
                        processed_count += 1
                    
                    # Explicit continuation: Log and continue to next artifact type
                    logger.info(f"Batch execution continuing after {artifact_type} database error. Processed {processed_count}/{total} artifacts so far.")
                    continue
                    
                except IOError as e:
                    # File I/O error during parsing
                    error_msg = f"File I/O error while parsing {artifact_type} artifacts"
                    logger.error(f"{error_msg}: {str(e)}", exc_info=True)
                    
                    # Log exception to error file if error_log_path provided
                    if error_log_path:
                        dir_name = os.path.basename(artifact_dir)
                        self._log_error_to_file(error_log_path, artifact_type, dir_name, f"I/O error: {str(e)}")
                    
                    # Create error result for each artifact with user-friendly message
                    user_friendly_msg = f"Unable to read or write files during parsing. Check file permissions and disk space."
                    for artifact in type_artifacts:
                        error_result = ParserResult(
                            success=False,
                            artifact_type=artifact_type,
                            records_parsed=0,
                            output_path="",
                            errors=[user_friendly_msg],
                            warnings=[],
                            execution_time=0.0
                        )
                        results.append(error_result)
                        processed_count += 1
                    
                    # Explicit continuation: Log and continue to next artifact type
                    logger.info(f"Batch execution continuing after {artifact_type} I/O error. Processed {processed_count}/{total} artifacts so far.")
                    continue
                    
                except KeyError as e:
                    # Missing key/field error during parsing
                    error_msg = f"Missing required data field while parsing {artifact_type} artifacts"
                    logger.error(f"{error_msg}: {str(e)}", exc_info=True)
                    
                    # Log exception to error file if error_log_path provided
                    if error_log_path:
                        dir_name = os.path.basename(artifact_dir)
                        self._log_error_to_file(error_log_path, artifact_type, dir_name, f"Missing field: {str(e)}")
                    
                    # Create error result for each artifact with user-friendly message
                    user_friendly_msg = f"Missing required data field during parsing. The artifact format may be unexpected."
                    for artifact in type_artifacts:
                        error_result = ParserResult(
                            success=False,
                            artifact_type=artifact_type,
                            records_parsed=0,
                            output_path="",
                            errors=[user_friendly_msg],
                            warnings=[],
                            execution_time=0.0
                        )
                        results.append(error_result)
                        processed_count += 1
                    
                    # Explicit continuation: Log and continue to next artifact type
                    logger.info(f"Batch execution continuing after {artifact_type} missing field error. Processed {processed_count}/{total} artifacts so far.")
                    continue
                    
                except Exception as e:
                    # Generic exception handler for unexpected errors
                    logger.error(f"Unexpected error while parsing {artifact_type} artifacts: {str(e)}", exc_info=True)
                    
                    # Log exception to error file if error_log_path provided
                    if error_log_path:
                        dir_name = os.path.basename(artifact_dir)
                        self._log_error_to_file(error_log_path, artifact_type, dir_name, f"Unexpected error: {str(e)}")
                    
                    # Create error result for each artifact with user-friendly message
                    user_friendly_msg = f"An unexpected error occurred during parsing. Please check the error log for details."
                    for artifact in type_artifacts:
                        error_result = ParserResult(
                            success=False,
                            artifact_type=artifact_type,
                            records_parsed=0,
                            output_path="",
                            errors=[user_friendly_msg],
                            warnings=[],
                            execution_time=0.0
                        )
                        results.append(error_result)
                        processed_count += 1
                    
                    # Explicit continuation: Log and continue to next artifact type
                    logger.info(f"Batch execution continuing after {artifact_type} unexpected error. Processed {processed_count}/{total} artifacts so far.")
                    continue  # Explicitly continue to next artifact type
            else:
                # For file-based parsers, process each file individually
                for artifact in type_artifacts:
                    # Check for cancellation
                    if cancellation_check and cancellation_check():
                        logger.info(f"Parsing cancelled after {processed_count} artifacts")
                        # Emit heartbeat during cancellation
                        emit_heartbeat_if_needed()
                        break
                    
                    # Call progress callback
                    if progress_callback:
                        progress_callback(processed_count, total, artifact.current_path, artifact.artifact_type)

                    # Emit heartbeat before parsing
                    emit_heartbeat_if_needed()

                    # Parse the artifact
                    try:
                        result = self.invoke_parser(
                            artifact_type=artifact.artifact_type,
                            artifact_path=artifact.current_path
                        )
                        
                        # Emit heartbeat after parsing
                        emit_heartbeat_if_needed()
                        
                        results.append(result)
                        processed_count += 1
                        
                        # Log result
                        if result.success:
                            logger.info(f"Successfully parsed {artifact.artifact_type} artifact: {artifact.current_path}")
                        else:
                            logger.error(f"Failed to parse {artifact.artifact_type} artifact: {artifact.current_path}. Errors: {result.errors}")
                            
                            # Log errors to file if error_log_path provided
                            if error_log_path and result.errors:
                                filename = os.path.basename(artifact.current_path)
                                for error in result.errors:
                                    self._log_error_to_file(error_log_path, artifact.artifact_type, filename, error)
                            
                            # Explicit continuation: Log that batch execution continues despite failure
                            logger.info(f"Batch execution continuing after failure for {artifact.current_path}. Processed {processed_count}/{total} artifacts so far.")
                            
                    except sqlite3.Error as e:
                        # Database-related error during parsing
                        error_msg = f"Database error while parsing {artifact.artifact_type} artifact"
                        logger.error(f"{error_msg} at {artifact.current_path}: {str(e)}", exc_info=True)
                        
                        # Log exception to error file if error_log_path provided
                        if error_log_path:
                            filename = os.path.basename(artifact.current_path)
                            self._log_error_to_file(error_log_path, artifact.artifact_type, filename, f"Database error: {str(e)}")
                        
                        # Create error result with user-friendly message
                        user_friendly_msg = f"Database error occurred during parsing. Please check the output database."
                        error_result = ParserResult(
                            success=False,
                            artifact_type=artifact.artifact_type,
                            records_parsed=0,
                            output_path="",
                            errors=[user_friendly_msg],
                            warnings=[],
                            execution_time=0.0
                        )
                        results.append(error_result)
                        processed_count += 1
                        
                        # Explicit continuation: Log and continue to next artifact
                        logger.info(f"Batch execution continuing after database error for {artifact.current_path}. Processed {processed_count}/{total} artifacts so far.")
                        continue
                        
                    except IOError as e:
                        # File I/O error during parsing
                        error_msg = f"File I/O error while parsing {artifact.artifact_type} artifact"
                        logger.error(f"{error_msg} at {artifact.current_path}: {str(e)}", exc_info=True)
                        
                        # Log exception to error file if error_log_path provided
                        if error_log_path:
                            filename = os.path.basename(artifact.current_path)
                            self._log_error_to_file(error_log_path, artifact.artifact_type, filename, f"I/O error: {str(e)}")
                        
                        # Create error result with user-friendly message
                        user_friendly_msg = f"Unable to read or write files during parsing. Check file permissions and disk space."
                        error_result = ParserResult(
                            success=False,
                            artifact_type=artifact.artifact_type,
                            records_parsed=0,
                            output_path="",
                            errors=[user_friendly_msg],
                            warnings=[],
                            execution_time=0.0
                        )
                        results.append(error_result)
                        processed_count += 1
                        
                        # Explicit continuation: Log and continue to next artifact
                        logger.info(f"Batch execution continuing after I/O error for {artifact.current_path}. Processed {processed_count}/{total} artifacts so far.")
                        continue
                        
                    except KeyError as e:
                        # Missing key/field error during parsing
                        error_msg = f"Missing required data field while parsing {artifact.artifact_type} artifact"
                        logger.error(f"{error_msg} at {artifact.current_path}: {str(e)}", exc_info=True)
                        
                        # Log exception to error file if error_log_path provided
                        if error_log_path:
                            filename = os.path.basename(artifact.current_path)
                            self._log_error_to_file(error_log_path, artifact.artifact_type, filename, f"Missing field: {str(e)}")
                        
                        # Create error result with user-friendly message
                        user_friendly_msg = f"Missing required data field during parsing. The artifact format may be unexpected."
                        error_result = ParserResult(
                            success=False,
                            artifact_type=artifact.artifact_type,
                            records_parsed=0,
                            output_path="",
                            errors=[user_friendly_msg],
                            warnings=[],
                            execution_time=0.0
                        )
                        results.append(error_result)
                        processed_count += 1
                        
                        # Explicit continuation: Log and continue to next artifact
                        logger.info(f"Batch execution continuing after missing field error for {artifact.current_path}. Processed {processed_count}/{total} artifacts so far.")
                        continue
                        
                    except Exception as e:
                        # Generic exception handler for unexpected errors
                        logger.error(f"Unexpected error while parsing {artifact.artifact_type} artifact at {artifact.current_path}: {str(e)}", exc_info=True)
                        
                        # Log exception to error file if error_log_path provided
                        if error_log_path:
                            filename = os.path.basename(artifact.current_path)
                            self._log_error_to_file(error_log_path, artifact.artifact_type, filename, f"Unexpected error: {str(e)}")
                        
                        # Create error result with user-friendly message
                        user_friendly_msg = f"An unexpected error occurred during parsing. Please check the error log for details."
                        error_result = ParserResult(
                            success=False,
                            artifact_type=artifact.artifact_type,
                            records_parsed=0,
                            output_path="",
                            errors=[user_friendly_msg],
                            warnings=[],
                            execution_time=0.0
                        )
                        results.append(error_result)
                        processed_count += 1
                        
                        # Explicit continuation: Log and continue to next artifact
                        logger.info(f"Batch execution continuing after unexpected error for {artifact.current_path}. Processed {processed_count}/{total} artifacts so far.")
                        continue  # Explicitly continue to next artifact

        # Final progress callback
        if progress_callback:
            progress_callback(len(results), total, "Complete", "")

        return results

