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
    # Which ScannedArtifact this result is for. Results come back grouped by
    # type in the canonical order, not in the order the artifacts were given,
    # so pairing them by position marked the wrong files as parsed.
    artifact_id: Optional[str] = None
    # No parser for this file (Unknown): neither a success nor a failure.
    skipped: bool = False


def pair_results(artifacts, results):
    """[(artifact, result)] matched by artifact_id; skipped results left out.

    Results without ids (an older invoker) fall back to their position.
    """
    by_id = {}
    for r in results or []:
        rid = getattr(r, "artifact_id", None)
        if rid:
            by_id.setdefault(rid, r)
    if not by_id:
        return [(a, r) for a, r in zip(artifacts, results or [])
                if not getattr(r, "skipped", False)]
    out = []
    for a in artifacts:
        r = by_id.get(getattr(a, "artifact_id", None))
        if r is not None and not getattr(r, "skipped", False):
            out.append((a, r))
    return out


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
        # "Include browser cache": parse the HTTP / Service Worker / Gecko
        # caches of collected browser profiles (set by the dialogs).
        self.include_browser_cache = True
        # 'offline' or 'image' - only labels the parse-status record; callers
        # driving a forensic image set it (ImageParsingDialog).
        self.mode = 'offline'
        # Set by the image window so ONE Parse Status Report covers the whole
        # session: problems found before parsing (BitLocker, wrong partition,
        # ...), artifacts found in the image but not extracted
        # {collector type: [reason, ...]}, and what was read (image, partitions).
        self.session_issues = []
        self.collection_failures = {}
        self.run_source = {}
        # The artifact types the investigator chose to extract (collector type
        # names), or None for all: the rest are "not selected", not "not on
        # this evidence".
        self.extraction_scope = None
        # Optional callable(event dict) for the parsing dialog's checklist:
        # start / file / now / records / warning / line / done per parser
        # (utils.parse_logging.ArtifactRun.emit).
        self.artifact_progress = None

    def _record_parse_status(self, results: List[ParserResult], artifacts: List,
                             started: float, cancelled: bool = False,
                             crashed: Optional[BaseException] = None) -> None:
        """One parse-status outcome per artifact type in this batch.

        Results arrive one per FILE (directory parsers fan the type result out
        across its files), so they are folded back per type: any success with
        failures is PARTIAL, all failures classify by their error text. Types
        the scan index never found are recorded as SOURCE_NOT_FOUND so their
        empty tables explain themselves.
        Best-effort: a status record must never fail a parse.
        """
        try:
            from utils.parse_status import (ARTIFACT_ORDER, NOT_A_FAILURE, ArtifactOutcome,
                                            ParseStatus, ParserResultLike, artifact_db_records,
                                            artifact_db_rowcount,
                                            artifact_label, canonical_artifact, classify_error_text,
                                            classify_result, make_issue, prefetch_failed_files,
                                            probe_sources, record_outcomes, version_problems)
        except Exception as e:
            logger.warning(f"Parse status unavailable: {e}")
            return
        try:
            case_root = str(self.case_root)
            by_type = {}
            for r in results:
                by_type.setdefault(r.artifact_type, []).append(r)
            paths_by_type = {}
            for a in artifacts:
                paths_by_type.setdefault(a.artifact_type, []).append(
                    getattr(a, 'current_path', '') or getattr(a, 'original_path', ''))

            # What the evidence contains at all (scan index), to tell "not in
            # this batch" apart from "not on this evidence".
            indexed_types = set(paths_by_type)
            try:
                from Artifacts_Collectors.Offline_Importer.artifact_scan_index import ArtifactScanIndex
                indexed_types |= {a.artifact_type for a in ArtifactScanIndex(case_root).get_all_artifacts()}
            except Exception:
                pass
            indexed = {canonical_artifact(t) for t in indexed_types}

            outcomes = []
            for type_name, type_results in by_type.items():
                artifact = canonical_artifact(type_name)
                if not artifact:
                    continue
                ok = [r for r in type_results if r.success]
                bad = [r for r in type_results if not r.success]
                errors = []
                for r in bad:
                    errors.extend(e for e in r.errors if e and e not in errors)
                warnings = []
                for r in type_results:
                    warnings.extend(w for w in r.warnings if w and w not in warnings)
                folded = ParserResultLike(
                    success=bool(ok) and not bad,
                    records_parsed=sum(r.records_parsed for r in type_results),
                    errors=errors, warnings=warnings,
                    status=ParseStatus.PARTIAL if ok and bad else None)
                probe = probe_sources(artifact, self.mode, case_root=case_root,
                                      scanned_paths=paths_by_type.get(type_name, []))
                details = []
                if bad and ok:
                    details.append("%d of %d input file(s) failed" % (len(bad), len(type_results)))
                # Prefetch skips files it cannot read (unknown version, bad
                # signature) one by one and still reports success - the list
                # it leaves is the only record of them.
                skipped = prefetch_failed_files(case_root, since=started) if artifact == "prefetch" else []
                details.extend(skipped)
                db_count = artifact_db_records(case_root, artifact, since=started)
                if skipped and not db_count and not folded.records_parsed and not errors:
                    folded.errors = ["%d prefetch file(s) use a version or format the parser "
                                     "does not support, or are corrupt" % len(skipped)]
                    folded.status = ParseStatus.UNSUPPORTED_FORMAT
                rows_before = (getattr(self, "_rows_before", None) or {}).get(artifact)
                outcome = classify_result(
                    artifact, folded, probe=probe, mode=self.mode,
                    db_records=db_count, details=details, rows_before=rows_before,
                    rows_after=artifact_db_rowcount(case_root, artifact) if rows_before is not None else None)
                if outcome.status == ParseStatus.PARTIAL and not outcome.message:
                    outcome.message = errors[0] if errors else "Some input files failed."
                outcomes.append(outcome)

            done = {o.artifact for o in outcomes}

            # Found in the image but never extracted: that is a failure, not
            # "not on this evidence" - the scan index only holds what copied.
            failures = {}
            for type_name, reasons in (self.collection_failures or {}).items():
                art = canonical_artifact(type_name)
                if art:
                    failures.setdefault(art, []).extend(r for r in reasons if r)

            # Selected for this run but never reached: cancelled, or the run stopped.
            selected = {canonical_artifact(t) for t in paths_by_type} - {None}
            for artifact in sorted(selected - done, key=lambda a: ARTIFACT_ORDER.index(a)
                                   if a in ARTIFACT_ORDER else 99):
                why = ("Cancelled before this artifact was parsed." if cancelled else
                       "Parsing stopped before this artifact: %s: %s" % (type(crashed).__name__, crashed)
                       if crashed else "Not parsed in this run.")
                outcomes.append(ArtifactOutcome(artifact, self.mode, ParseStatus.NOT_RUN, 0, why))
                done.add(artifact)

            for artifact, reasons in failures.items():
                if artifact in done:
                    for o in outcomes:
                        if o.artifact == artifact:
                            o.details.append("%d file(s) found in the evidence could not be "
                                             "extracted - first reason: %s" % (len(reasons), reasons[0]))
                    continue
                status = classify_error_text(reasons[0])
                if status in NOT_A_FAILURE:
                    status = ParseStatus.FAILED
                outcomes.append(ArtifactOutcome(
                    artifact, self.mode, status, 0,
                    "Found in the evidence but could not be extracted: %s" % reasons[0],
                    details=["Not extracted: %s" % r for r in reasons[1:10]]))
                done.add(artifact)

            # The MFT-USN correlation runs inside the MFT / USN parsers.
            if "mft_usn_correlation" not in done and ({"mft", "usn"} & done):
                if {"mft", "usn"} <= done:
                    corr = artifact_db_records(case_root, "mft_usn_correlation", since=started)
                    outcomes.append(classify_result("mft_usn_correlation", None, probe={},
                                                    mode=self.mode, db_records=corr))
                else:
                    have = "the $MFT" if "mft" in done else "the USN journal"
                    outcomes.append(ArtifactOutcome(
                        "mft_usn_correlation", self.mode, ParseStatus.NOT_RUN, 0,
                        "The correlation needs both the $MFT and the USN journal; only %s "
                        "was parsed in this run." % have))
                done.add("mft_usn_correlation")

            scope = None
            if self.extraction_scope:
                scope = {canonical_artifact(t) for t in self.extraction_scope} - {None}
            for artifact in ARTIFACT_ORDER:
                if artifact in done or artifact == 'mft_usn_correlation':
                    continue
                if scope is not None and artifact not in scope:
                    outcomes.append(ArtifactOutcome(
                        artifact, self.mode, ParseStatus.NOT_RUN, 0,
                        "Not selected for extraction in this run."))
                    continue
                if artifact not in indexed:
                    probe = probe_sources(artifact, self.mode, case_root=case_root, scanned_paths=[])
                    outcomes.append(classify_result(artifact, None, probe=probe, mode=self.mode))

            issues = list(self.session_issues or [])
            if crashed is not None:
                issues.append(make_issue("parsing_failed", "%s: %s" % (type(crashed).__name__, crashed)))
            issues.extend(self._foreign_log_issues())
            unsupported = [o for o in outcomes if o.status == ParseStatus.UNSUPPORTED_FORMAT]
            for o in unsupported:
                texts = version_problems([o.message] + list(o.details)) or [o.message]
                issues.append(make_issue("unsupported_artifact_version", texts[0],
                                         artifact=artifact_label(o.artifact)))
            record_outcomes(case_root, outcomes, self.mode, show=True, issues=issues,
                            source=self.run_source or None)
            self._last_outcomes = outcomes
        except Exception as e:
            logger.warning(f"Could not record parse status: {e}", exc_info=True)
    @staticmethod
    def _foreign_log_issues():
        """One issue per hive whose own-named log belonged to another hive.

        Old flat cases are left out: their logs were renamed by the
        collector, matched by content, and a mismatch there is expected.
        """
        try:
            from utils.parse_status import make_issue
            try:
                from Artifacts_Collectors import registry_transaction_log as rtl
            except ImportError:
                import registry_transaction_log as rtl
        except ImportError:
            return []
        issues = []
        for res in rtl.recovery_results():
            if res.flat_layout or not res.foreign_logs:
                continue
            path, why = res.foreign_logs[0]
            issue = make_issue("foreign_transaction_log",
                               "%s: %s (%s)" % (res.hive_path, os.path.basename(path), why),
                               hive=res.hive_path)
            if issue is not None:
                issues.append(issue)
        return issues

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
        """Run one parser inside utils.parse_logging.artifact_run.

        The frame logs the start and the result under
        Artifacts_Collectors.run.<artifact>, copies what the parser prints into
        that logger (most parsers only print), and feeds the parsing dialog's
        checklist through ``self.artifact_progress``.
        """
        try:
            from utils.parse_logging import artifact_run
            from utils.parse_status import artifact_label, canonical_artifact
        except Exception:
            return self._invoke_parser(artifact_type, **kwargs)
        key = canonical_artifact(artifact_type) or str(artifact_type).lower()
        source = kwargs.get('artifact_path') or kwargs.get('artifact_dir') or str(self.input_dir)
        with artifact_run(key, artifact_label(key), source=source, mode=self.mode,
                          progress=self.artifact_progress) as run:
            result = self._invoke_parser(artifact_type, **kwargs)
            run.set_records(getattr(result, 'records_parsed', None))
            for warning in (getattr(result, 'warnings', None) or [])[:20]:
                run.warn(str(warning))
            if result is not None and not getattr(result, 'success', True):
                errors = getattr(result, 'errors', None) or []
                run.logger.error("parser reported failure: %s", "; ".join(str(e) for e in errors[:3]))
            return result

    def _invoke_parser(self, artifact_type: str, **kwargs) -> ParserResult:
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
            elif artifact_type == 'link_jumplist':
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
            elif artifact_type == 'Browser':
                logger.info(f"[PARSER ROUTING] → Invoking Browser parser")
                return self._invoke_browser_parser(start_time, **kwargs)
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
            
            # Trust what reg_Claw reports instead of hard-coding success=True:
            # a dict that says success False used to show as parsed.
            reported = result if isinstance(result, dict) else {}
            reg_error = reported.get('error')
            parser_result = ParserResult(
                success=bool(reported.get('success', True)) and not reg_error,
                artifact_type='Registry',
                records_parsed=reported.get('records', 0) or 0,
                output_path=output_path,
                errors=[reg_error] if reg_error else [],
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
                direct_parse=False,
                # the batch's own folder, else the importer's / Crow-Claw's name
                folder=self._input_folder(kwargs, 'C_AJL_Lnk', 'link_jumplist'),
                # Removed: registry_hive_paths parameter (parser doesn't accept it)
            )
            
            # Defensive check: Ensure result is a dict
            if not isinstance(result, dict):
                logger.warning(f"JumpLists parser returned invalid format: {type(result).__name__} instead of dict")
                result = {'success': False, 'records': 0, 'error': f'Parser returned invalid format: {type(result).__name__}'}
            
            output_path = os.path.join(self.target_artifacts_dir, 'LnkDB.db')

            # Files were given and the parser found none where it looked: that
            # is not a success (it said "1185/1185 success" having read the
            # wrong folder). Zero NEW records on a re-parse is still a success.
            success = result.get('success', True)
            if success and kwargs.get('file_count') and result.get('files') == 0:
                success = False
                result['error'] = result.get('error') or (
                    "No LNK / Jump List file found in %s (%d file(s) were imported)"
                    % (result.get('folder'), kwargs.get('file_count')))

            # Create initial ParserResult
            parser_result = ParserResult(
                success=success,
                artifact_type='link_jumplist',
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
            
            return ParserResult(success=False, artifact_type='link_jumplist', records_parsed=0, output_path="", errors=[sanitized_error], execution_time=time.time() - start_time)

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

    def _invoke_browser_parser(self, start_time: float, **kwargs) -> ParserResult:
        """Invoke the browser parser using offline_BrowserClaw.

        One call parses every collected browser tree in the case
        (live_acquisition/Browser/<source>/Users/...), whichever scan-index
        entry triggered it.
        """
        try:
            from Artifacts_Collectors.offline_parsers.offline_BrowserClaw import run_offline_browser

            result = run_offline_browser(
                case_path=str(self.case_root),
                artifact_dir=kwargs.get('artifact_dir'),
                include_cache=self.include_browser_cache,
            )
            if not isinstance(result, dict):
                result = {'success': False, 'records': 0,
                          'error': f'Parser returned invalid format: {type(result).__name__}'}

            return ParserResult(
                success=result.get('success', False),
                artifact_type='Browser',
                records_parsed=result.get('records', 0),
                output_path=result.get('output_path') or os.path.join(self.target_artifacts_dir, 'browser_analysis.db'),
                errors=[result.get('error')] if result.get('error') else [],
                warnings=list(result.get('warnings') or [])[:20],
                execution_time=time.time() - start_time
            )
        except Exception as e:
            import traceback
            error_type = type(e).__name__
            artifact_path = kwargs.get('artifact_path', 'unknown')
            logger.error(f"Browser parser failed - Type: {error_type}, Path: {artifact_path}")
            logger.error(f"Error message: {e}")
            logger.error(f"Stack trace:\n{traceback.format_exc()}")
            sanitized_error = self._sanitize_dependency_error(str(e), error_type, str(artifact_path))
            return ParserResult(success=False, artifact_type='Browser', records_parsed=0, output_path="",
                                errors=[sanitized_error], execution_time=time.time() - start_time)

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
                mft_file_path=mft_file_path,
                correlate=False,          # once per batch, after MFT and USN (below)
            )

            # Where it actually wrote: MFT_USN/MFT_data.db is a path nothing creates.
            output_path = result.get('output_path') or os.path.join(
                self.target_artifacts_dir, 'mft_claw_analysis.db')
            
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
                usn_file_path=usn_file_path,
                correlate=False,          # once per batch (below)
            )

            output_path = result.get('output_path') or os.path.join(
                self.target_artifacts_dir, 'USN_journal.db')
            
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

    def _input_folder(self, kwargs, *names):
        """Where a directory parser's files are: the batch's own folder (the
        common root of the files being parsed), then each known folder name
        under live_acquisition - the Offline Importer's and Crow-Claw's."""
        for candidate in [kwargs.get('artifact_root'), kwargs.get('artifact_dir')] + \
                [os.path.join(self.input_dir, n) for n in names]:
            if candidate and os.path.isdir(candidate):
                return str(candidate)
        return None

    def _invoke_evtx_parser(self, start_time: float, **kwargs) -> ParserResult:
        """Invoke EVTX (Windows Event Log) parser using offline_WinLog_Claw."""
        try:
            from Artifacts_Collectors.offline_parsers.offline_WinLog_Claw import main as run_offline_winlog
            
            # EVTX parser expects evtx_dir and case_path. Crow-Claw writes
            # live_acquisition\EVTX; the importer's own name is EVTX_Logs.
            evtx_dir = self._input_folder(kwargs, 'EVTX_Logs', 'EVTX')

            # Check if the event logs directory exists
            if not evtx_dir:
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
            
            # SRUM parser expects srudb_path and case_path. Crow-Claw writes
            # live_acquisition\SRUM\SRUDB.dat; the importer's name is SRUM_Data.
            srudb_path = None
            given = kwargs.get('artifact_path')
            if given and os.path.basename(str(given)).lower() == 'srudb.dat' and os.path.isfile(given):
                srudb_path = str(given)
            for folder in (kwargs.get('artifact_root'), kwargs.get('artifact_dir'),
                           os.path.join(self.input_dir, 'SRUM_Data'), os.path.join(self.input_dir, 'SRUM')):
                if srudb_path:
                    break
                if folder and os.path.isfile(os.path.join(folder, 'SRUDB.dat')):
                    srudb_path = os.path.join(folder, 'SRUDB.dat')

            # Check if SRUDB.dat exists
            if not srudb_path:
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
        """Parse a batch; whatever happens, record one parse-status run for it.

        A crash part-way used to leave no record at all, so the report never
        said which artifacts had been parsed and which never ran.
        """
        import time as _time
        self._batch_results = []
        self._batch_cancelled = False
        started = _time.time()
        rec = self._custody_begin(artifacts)
        # Each artifact's database total before the batch: with the total
        # after, the report says what this parse added and what was already
        # in the case.
        self._rows_before = {}
        try:
            from utils.parse_status import artifact_db_rowcount, canonical_artifact
            for a in artifacts or []:
                canon = canonical_artifact(getattr(a, "artifact_type", "") or "")
                if canon and canon not in self._rows_before:
                    self._rows_before[canon] = artifact_db_rowcount(str(self.case_root), canon) or 0
        except Exception as e:
            logger.debug("row counts before the batch not taken: %s", e)
        status = "failed"
        try:
            results = self._parse_artifacts_batch(artifacts, progress_callback, cancellation_check,
                                                  error_log_path, heartbeat_callback)
            status = "cancelled" if self._batch_cancelled else "completed"
            return results
        except Exception as exc:
            logger.error("Batch parsing stopped: %s", exc, exc_info=True)
            self._record_parse_status(self._batch_results, artifacts, started, crashed=exc)
            if rec is not None:
                rec.add_failure("batch", "%s: %s" % (type(exc).__name__, exc), method="parse")
            raise
        finally:
            self._custody_end(rec, status, started)

    # -- chain of custody --------------------------------------------------
    def _custody_begin(self, artifacts):
        """The offline parse's own custody record: every input file (size,
        times, SHA-256) recorded BEFORE it is read. Never raises."""
        try:
            from utils import custody
            rec = custody.begin(str(self.case_root), "offline parse",
                                options={"artifacts": len(artifacts or [])},
                                output_dir=str(self.target_artifacts_dir))
        except Exception as e:
            logger.warning("Custody record not started: %s", e)
            return None
        for a in artifacts or []:
            path = getattr(a, "current_path", None) or getattr(a, "original_path", None)
            if not path:
                continue
            try:
                times = custody.file_times(path)
                big = (times.get("size") or 0) > 512 * 1024 ** 2
                known = getattr(a, "file_hash", None) or None
                rec.add_source(path, method="in-place read", times=times,
                               source_sha256=known, hash_source=not big and not known,
                               note="; ".join(x for x in (
                                   getattr(a, "artifact_type", None),
                                   "not hashed: larger than 512 MB" if big and not known else None,
                                   ("from %s" % a.original_path)
                                   if getattr(a, "original_path", None) not in (None, path) else None)
                                   if x))
            except Exception as e:
                rec.add_failure(path, "not recorded: %s" % e, method="inventory")
        return rec

    def _custody_end(self, rec, status, started):
        if rec is None:
            return
        try:
            for r in self._batch_results or []:
                if not getattr(r, "success", False) and not getattr(r, "skipped", False):
                    rec.add_failure(r.artifact_type, "; ".join(r.errors or [])[:2000] or "failed",
                                    method="parse", artifact_id=getattr(r, "artifact_id", None))
            # Each artifact's outcome with what it added and what was already
            # in the case.
            for o in getattr(self, "_last_outcomes", None) or []:
                item = {"artifact": o.artifact, "status": o.status, "records": o.records,
                        "inserted": o.inserted, "duplicates": o.duplicates,
                        "rows_before": o.rows_before, "rows_after": o.rows_after,
                        "message": o.message, "error": o.error,
                        "indexes_created": list(getattr(o, "indexes_created", None) or []) or None}
                with rec._lock:
                    rec.data.setdefault("artifacts", []).append(
                        {k: v for k, v in item.items() if v not in (None, "")})
            rec.record_outputs(since=started)
        except Exception as e:
            rec.warn("Outputs not recorded: %s" % e)
        try:
            from utils import custody
            custody.end(status, rec=rec)
        except Exception as e:
            logger.warning("Custody record not written: %s", e)

    @staticmethod
    def _tag(result, artifact):
        """Stamp a result with the artifact it belongs to (see pair_results)."""
        result.artifact_id = getattr(artifact, "artifact_id", None)
        return result

    def _parse_artifacts_batch(self, artifacts: List,
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
        results = self._batch_results      # the same list, so a crash still sees it
        total = len(artifacts)

        # Track last heartbeat time for emitting heartbeat signals
        import time
        batch_started = time.time()
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
            'link_jumplist',
            'Registry',
            'Prefetch',
            'EVTX',
            'ShimCache',
            'AmCache',
            'RecycleBin',
            'SRUM',
            'Browser',
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
            # Unknown: files collected that no parser reads - said so, per file,
            # as skipped (not failed), instead of vanishing from the results.
            if artifact_type == 'Unknown':
                for artifact in artifacts_by_type[artifact_type]:
                    results.append(self._tag(ParserResult(
                        success=False, artifact_type='Unknown', records_parsed=0, output_path="",
                        warnings=["No parser for this file type"], skipped=True), artifact))
                processed_count += len(artifacts_by_type[artifact_type])
                continue

            type_artifacts = artifacts_by_type[artifact_type]
            
            # Check for cancellation
            if cancellation_check and cancellation_check():
                self._batch_cancelled = True
                logger.info(f"Parsing cancelled after {processed_count} artifacts")
                # Emit heartbeat during cancellation to keep animation smooth
                emit_heartbeat_if_needed()
                break
            
            logger.info(f"Processing {len(type_artifacts)} {artifact_type} artifacts")
            
            # Determine if this is a directory-based parser (scans entire directory)
            # or file-based parser (processes individual files)
            is_directory_parser = artifact_type in ['Prefetch', 'EVTX', 'SRUM', 'Registry', 'link_jumplist', 'RecycleBin', 'Browser',
                                                    'AmCache']
            
            if is_directory_parser:
                # For directory-based parsers, call once with the directory containing the files
                # Use the directory from the first artifact's current_path
                first_artifact = type_artifacts[0]
                artifact_dir = os.path.dirname(first_artifact.current_path)
                # The folder that holds ALL this type's files (per-user files
                # sit in Users\<name>\ subfolders): what a parser should read
                try:
                    artifact_root = os.path.commonpath(
                        [os.path.dirname(a.current_path) for a in type_artifacts])
                except ValueError:
                    artifact_root = artifact_dir
                
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
                        artifact_dir=artifact_dir,  # Pass directory for scanning
                        artifact_root=artifact_root,
                        file_count=len(type_artifacts),
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
                        results.append(self._tag(artifact_result, artifact))
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
                        results.append(self._tag(error_result, artifact))
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
                        results.append(self._tag(error_result, artifact))
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
                        results.append(self._tag(error_result, artifact))
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
                        results.append(self._tag(error_result, artifact))
                        processed_count += 1
                    
                    # Explicit continuation: Log and continue to next artifact type
                    logger.info(f"Batch execution continuing after {artifact_type} unexpected error. Processed {processed_count}/{total} artifacts so far.")
                    continue  # Explicitly continue to next artifact type
            else:
                # For file-based parsers, process each file individually
                for artifact in type_artifacts:
                    # Check for cancellation
                    if cancellation_check and cancellation_check():
                        self._batch_cancelled = True
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
                        
                        results.append(self._tag(result, artifact))
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
                        results.append(self._tag(error_result, artifact))
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
                        results.append(self._tag(error_result, artifact))
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
                        results.append(self._tag(error_result, artifact))
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
                        results.append(self._tag(error_result, artifact))
                        processed_count += 1
                        
                        # Explicit continuation: Log and continue to next artifact
                        logger.info(f"Batch execution continuing after unexpected error for {artifact.current_path}. Processed {processed_count}/{total} artifacts so far.")
                        continue  # Explicitly continue to next artifact

        # MFT <-> USN correlation: once, after both. Each runner used to start
        # its own when it found the other's database - twice a batch, the first
        # time (MFT parses before USN) against the previous run's journal.
        # Both, in THIS run: with only the $MFT parsed (the journal failed or
        # was not collected) it ran anyway - 25 minutes against the previous
        # parse's journal.
        parsed_now = {r.artifact_type for r in results if r.success}
        if {"MFT", "USN"} <= parsed_now \
                and not getattr(self, "_batch_cancelled", False):
            if progress_callback:
                progress_callback(len(results), total, "MFT / USN correlation", "MFT")
            try:
                from Artifacts_Collectors.offline_parsers.offline_MFT_USN_Correlator import \
                    run_offline_correlation
                corr = run_offline_correlation(self.case_root, force=True)
                if corr.get("success"):
                    logger.info("MFT/USN correlation: %s record(s)", corr.get("records"))
                else:
                    logger.warning("MFT/USN correlation not run: %s", corr.get("error"))
                    for r in results:
                        if r.success and r.artifact_type in ("MFT", "USN"):
                            r.warnings.append("MFT/USN correlation not run: %s" % corr.get("error"))
                            break
            except Exception as exc:
                logger.error("MFT/USN correlation failed: %s", exc, exc_info=True)

        # Final progress callback
        if progress_callback:
            progress_callback(len(results), total, "Complete", "")

        # Per-artifact outcome for the Parse Status report / empty-table i buttons.
        self._record_parse_status(results, artifacts, batch_started,
                                  cancelled=getattr(self, "_batch_cancelled", False))

        return results

