#!/usr/bin/env python3
"""
MFT_USN_Correlator.py - Comprehensive correlation script for MFT and USN journal data

This script:
1. Runs both MFT_Claw and USN_Claw parsers
2. Creates a comprehensive correlated table with all data
3. Reconstructs complete file paths
4. Provides forensic analysis capabilities
"""

import os
import sys
import sqlite3
import subprocess
import logging
import time
import importlib.util
from pathlib import Path
from datetime import datetime, timezone

# Add utils directory to path for time_utils import
utils_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'utils')
if utils_dir not in sys.path:
    sys.path.insert(0, utils_dir)

from time_utils import get_current_forensic_timestamp

# Import the main functions from MFT_Claw and USN_Claw for direct function calls
# Add the current directory to sys.path to allow importing the scripts
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from MFT_Claw import main as mft_claw_main
    from USN_Claw import main as usn_claw_main
    HAS_DIRECT_IMPORTS = True
except ImportError as e:
    print(f"Warning: Could not import MFT/USN scripts directly: {e}")
    print("Falling back to subprocess execution")
    HAS_DIRECT_IMPORTS = False

# Colorama for colored terminal output
try:
    import colorama
    from colorama import Fore, Back, Style
    colorama.init()
    
    # Color definitions for consistent output
    COLOR_SUCCESS = Fore.GREEN
    COLOR_WARNING = Fore.YELLOW
    COLOR_ERROR = Fore.RED
    COLOR_INFO = Fore.CYAN
    COLOR_HEADER = Fore.MAGENTA + Style.BRIGHT
    COLOR_PROGRESS = Fore.BLUE
    COLOR_RESET = Style.RESET_ALL
    
except ImportError:
    # Fallback if colorama is not available
    COLOR_SUCCESS = COLOR_WARNING = COLOR_ERROR = COLOR_INFO = COLOR_HEADER = COLOR_PROGRESS = COLOR_RESET = ""

# File attribute constants
FILE_ATTRIBUTE_MAP = {
    0x00000001: "READONLY",
    0x00000002: "HIDDEN",
    0x00000004: "SYSTEM",
    0x00000010: "DIRECTORY",
    0x00000020: "ARCHIVE",
    0x00000040: "DEVICE",
    0x00000080: "NORMAL",
    0x00000100: "TEMPORARY",
    0x00000200: "SPARSE_FILE",
    0x00000400: "REPARSE_POINT",
    0x00000800: "COMPRESSED",
    0x00001000: "OFFLINE",
    0x00002000: "NOT_CONTENT_INDEXED",
    0x00004000: "ENCRYPTED",
    0x00008000: "INTEGRITY_STREAM",
    0x00010000: "VIRTUAL",
    0x00020000: "NO_SCRUB_DATA",
    0x00040000: "RECALL_ON_OPEN",
    0x00080000: "RECALL_ON_DATA_ACCESS",
}

def file_attributes_to_text(file_attributes):
    """Convert numeric file attributes to human-readable text representation"""
    try:
        file_attributes = int(file_attributes)
        if file_attributes == 0:
            return "NORMAL"
        
        attributes = []
        for attr_value, attr_name in FILE_ATTRIBUTE_MAP.items():
            if file_attributes & attr_value:
                attributes.append(attr_name)
        
        return "|".join(attributes) if attributes else "NORMAL"
    except (ValueError, TypeError):
        # If already a string or invalid, return as is
        return str(file_attributes)

def usn_reason_to_text(reason_code):
    """Convert numeric USN reason code to human-readable text"""
    try:
        reason_code = int(reason_code)
    except (ValueError, TypeError):
        return str(reason_code)  # Return as is if not a valid integer

    reasons = {
        0x00000001: "DATA_OVERWRITE",
        0x00000002: "DATA_EXTEND",
        0x00000004: "DATA_TRUNCATION",
        0x00000010: "NAMED_DATA_OVERWRITE",
        0x00000020: "NAMED_DATA_EXTEND",
        0x00000040: "NAMED_DATA_TRUNCATION",
        0x00000100: "FILE_CREATE",
        0x00000200: "FILE_DELETE",
        0x00000400: "EA_CHANGE",
        0x00000800: "SECURITY_CHANGE",
        0x00001000: "RENAME_OLD_NAME",
        0x00002000: "RENAME_NEW_NAME",
        0x00004000: "INDEXABLE_CHANGE",
        0x00008000: "BASIC_INFO_CHANGE",
        0x00010000: "HARD_LINK_CHANGE",
        0x00020000: "COMPRESSION_CHANGE",
        0x00040000: "ENCRYPTION_CHANGE",
        0x00080000: "OBJECT_ID_CHANGE",
        0x00100000: "REPARSE_POINT_CHANGE",
        0x00200000: "STREAM_CHANGE",
        0x80000000: "CLOSE"
    }
    if reason_code == 0:
        return "NONE"
    reason_texts = [name for code, name in reasons.items() if reason_code & code]
    return "|".join(reason_texts) if reason_texts else f"UNKNOWN_REASON_{reason_code:08X}"


# Check for required dependencies
# Longest a parser run in its own interpreter may take (MFT of a large volume).
PARSER_SUBPROCESS_TIMEOUT = 6 * 3600


def check_dependencies():
    missing_deps = []
    for module in ["psutil"]:
        if importlib.util.find_spec(module) is None:
            missing_deps.append(module)
    
    if missing_deps:
        print(f"{COLOR_WARNING}Missing dependencies: {', '.join(missing_deps)}{COLOR_RESET}")
        print(f"{COLOR_INFO}Installing missing dependencies...{COLOR_RESET}")
        for module in missing_deps:
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", module], timeout=600)
                print(f"{COLOR_SUCCESS}Successfully installed {module}{COLOR_RESET}")
            except Exception as e:
                print(f"{COLOR_ERROR}Failed to install {module}: {e}{COLOR_RESET}")
                return False
    return True

# Deliberately no logging.basicConfig() and no directory creation at import time.
#
# This module used to build "./Target_Artifacts" and open a log inside it the
# moment it was imported - relative to the CURRENT WORKING DIRECTORY, which is
# not the case folder, so the log landed wherever the app happened to be
# launched from. Worse, basicConfig at import seeds the root logger before any
# case exists and then does nothing at all once a case has added its handlers,
# so the file it believed it was writing often did not exist either way.
#
# The root configuration belongs to utils.logging_setup, which points at
# <case>/logs. This module asks for a logger and lets its records propagate
# there like every other component.
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column positions in the MFT row assembled by _get_mft_data_with_paths.
#
# That row is a bare tuple read by index in two places forty lines apart. The
# first twenty-one positions were already load-bearing and are left alone; the
# ones added for volume, extension, size and ADS are named, because appending
# to a tuple that is unpacked positionally elsewhere is exactly how an off-by-
# one gets into a forensic tool without anything failing.
# ---------------------------------------------------------------------------
VOL        = 21   # mr.volume_letter
# Which of a record's names is kept: Win32 & DOS, Win32, POSIX, then the 8.3
# DOS name (2) or anything else only when there is no other.
_NAMESPACE_RANK = {3: 0, 1: 1, 0: 2}
EXT        = 22   # mr.extension
FILE_SIZE  = 23   # mr.file_size
HAS_ADS    = 24   # mr.has_ads
ADS_COUNT  = 25   # mr.ads_count


# ---------------------------------------------------------------------------
# The correlated row, in one place.
#
# This column list was written out twice - once for the batched insert and once
# for the final flush - and adding a column meant remembering both. Declaring it
# once and generating the statement means the two cannot disagree, and the
# placeholder count cannot drift from the column count.
# ---------------------------------------------------------------------------
CORRELATED_COLUMNS = [
    'volume_letter',
    'mft_record_number', 'fn_filename', 'reconstructed_path',
    'mft_sequence_number', 'mft_flags', 'is_directory', 'is_deleted',
    'file_extension', 'file_size', 'in_use', 'has_ads', 'ads_count',
    'si_creation_time', 'si_modification_time', 'si_mft_entry_change_time',
    'si_access_time', 'si_file_attributes',
    'fn_parent_record_number', 'fn_parent_sequence_number',
    'fn_creation_time', 'fn_modification_time', 'fn_mft_entry_change_time',
    'fn_access_time', 'fn_allocated_size', 'fn_real_size', 'fn_file_attributes',
    'fn_namespace',
    'usn_event_id', 'usn_timestamp', 'usn_reason', 'usn_source_info',
    'usn_file_attributes', 'usn_filename', 'usn_frn', 'usn_parent_frn',
    'usn_security_id',
    'has_mft_record', 'has_usn_event', 'correlation_confidence',
    'filename_change_timeline', 'namespace_evolution',
]

CORRELATED_INSERT = "INSERT OR IGNORE INTO mft_usn_correlated (%s) VALUES (%s)" % (
    ', '.join(CORRELATED_COLUMNS), ', '.join(['?'] * len(CORRELATED_COLUMNS)))


class MFTUSNCorrelator:
    def __init__(self, case_directory=None, status_callback=None):
        """
        Args:
            case_directory: the case folder; databases live in its
                Target_Artifacts subdirectory.
            status_callback: optional, called as
                ``status_callback(status=..., log=...)`` when something happens
                that a person should be told about - currently only the rebuild
                of a correlated table that predates the correlation fix.

                This exists so the GUI can put that on the loading screen. The
                correlator itself must stay free of any GUI: it runs headless,
                inside spawned subprocesses via standalone_parsers, and from
                the offline wrapper, and an accidental PyQt import here would
                fail in a worker process where the traceback goes nowhere
                useful. A callback keeps that boundary intact - the same shape
                as progress_callback in the other parsers.
        """
        self.status_callback = status_callback

        # Database file paths - using Target_Artifacts subdirectory for consistency
        if case_directory:
            # Create Target_Artifacts subdirectory in case directory
            target_artifacts_dir = os.path.join(case_directory, "Target_Artifacts")
            os.makedirs(target_artifacts_dir, exist_ok=True)
            
            # Use Target_Artifacts subdirectory for database paths
            self.mft_db = os.path.join(target_artifacts_dir, "mft_claw_analysis.db")
            self.usn_db = os.path.join(target_artifacts_dir, "USN_journal.db")
            self.correlated_db = os.path.join(target_artifacts_dir, "mft_usn_correlated_analysis.db")
            self.case_directory = case_directory
        else:
            # Default to current directory with Target_Artifacts subdirectory
            target_artifacts_dir = os.path.join(".", "Target_Artifacts")
            os.makedirs(target_artifacts_dir, exist_ok=True)
            
            self.mft_db = os.path.join(target_artifacts_dir, "mft_claw_analysis.db")
            self.usn_db = os.path.join(target_artifacts_dir, "USN_journal.db")
            self.correlated_db = os.path.join(target_artifacts_dir, "mft_usn_correlated_analysis.db")
            self.case_directory = os.getcwd()
        
    def run_parsers(self, run_mft=True, run_usn=True):
        """Run MFT and/or USN parsers based on parameters
        
        Args:
            run_mft: Whether to run MFT parser (default: True)
            run_usn: Whether to run USN parser (default: True)
        
        Returns:
            bool: True if all requested parsers completed successfully
        """
        logger.info(f"Running parsers (MFT: {run_mft}, USN: {run_usn})...")
        
        # Ensure dependencies are installed
        check_dependencies()
        
        # Run MFT parser if requested
        if run_mft:
            logger.info("Running MFT parser...")
            try:
                if HAS_DIRECT_IMPORTS:
                    # Save current directory and change to case directory for direct function call
                    original_cwd = os.getcwd()
                    
                    # Temporarily restore original stdout/stderr to avoid log capture overhead
                    # This prevents massive slowdown from capturing thousands of progress bar updates
                    original_stdout = sys.stdout
                    original_stderr = sys.stderr
                    
                    # Check if stdout/stderr have been redirected (have original_stdout_ref attribute)
                    if hasattr(sys.stdout, 'original_stdout_ref'):
                        sys.stdout = sys.stdout.original_stdout_ref
                    if hasattr(sys.stderr, 'original_stderr_ref'):
                        sys.stderr = sys.stderr.original_stderr_ref
                    
                    try:
                        os.chdir(self.case_directory)
                        # Run MFT parser directly as a function
                        result = mft_claw_main()
                        if result == 0:
                            logger.info("MFT parser completed successfully")
                        else:
                            logger.error("MFT parser failed")
                            return False
                    finally:
                        os.chdir(original_cwd)
                        # Restore the redirected stdout/stderr
                        sys.stdout = original_stdout
                        sys.stderr = original_stderr
                else:
                    # Fallback to subprocess execution
                    env = os.environ.copy()
                    env['PYTHONIOENCODING'] = 'utf-8'
                    env["PYTHONUNBUFFERED"] = "1"  # Ensure output is not buffered
                    
                    mft_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MFT_Claw.py")
                    result = self._run_parser_subprocess(mft_script, "MFT")
                    
                    if result.returncode == 0:
                        logger.info("MFT parser completed successfully")
                    else:
                        logger.error("MFT parser failed")
                        return False
                
                # Check if database was created despite any errors
                if not os.path.exists(self.mft_db):
                    logger.error("MFT database was not created")
                    return False
                    
            except Exception as e:
                logger.error(f"Error running MFT parser: {e}")
                return False
        
        # Run USN parser if requested
        if run_usn:
            logger.info("Running USN parser...")
            
            try:
                if HAS_DIRECT_IMPORTS:
                    # Save current directory and change to case directory for direct function call
                    original_cwd = os.getcwd()
                    
                    # Temporarily restore original stdout/stderr to avoid log capture overhead
                    original_stdout = sys.stdout
                    original_stderr = sys.stderr
                    
                    # Check if stdout/stderr have been redirected (have original_stdout_ref attribute)
                    if hasattr(sys.stdout, 'original_stdout_ref'):
                        sys.stdout = sys.stdout.original_stdout_ref
                    if hasattr(sys.stderr, 'original_stderr_ref'):
                        sys.stderr = sys.stderr.original_stderr_ref
                    
                    try:
                        os.chdir(self.case_directory)
                        # Run USN parser directly as a function
                        result = usn_claw_main()
                        if result == 0:
                            logger.info("USN parser completed successfully")
                        else:
                            logger.warning("USN parser may have failed due to privilege requirements or missing dependencies")
                    finally:
                        os.chdir(original_cwd)
                        # Restore the redirected stdout/stderr
                        sys.stdout = original_stdout
                        sys.stderr = original_stderr
                else:
                    # Fallback to subprocess execution
                    env = os.environ.copy()
                    env['PYTHONIOENCODING'] = 'utf-8'
                    env["PYTHONUNBUFFERED"] = "1"  # Ensure output is not buffered
                    
                    usn_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "USN_Claw.py")
                    result = self._run_parser_subprocess(usn_script, "USN")
                    
                    if result.returncode == 0:
                        logger.info("USN parser completed successfully")
                    else:
                        # Only warn if the database wasn't created
                        if not os.path.exists(self.usn_db):
                            logger.warning("USN parser may have failed due to privilege requirements or missing dependencies")
                
                # Check if database was created despite any errors
                if not os.path.exists(self.usn_db):
                    logger.warning("USN database was not created - may need admin privileges")
                    logger.warning("Please run USN_Claw.py manually as administrator")
                    # USN database is optional for correlation, so don't return False here
                    
            except Exception as e:
                logger.error(f"Error running USN parser: {e}")
                logger.error("This may be due to privilege requirements for USN journal access or missing dependencies")
                # USN database is optional for correlation, so don't return False here
        
        return True
    
    def _show_progress(self, current, total, prefix="", suffix="", bar_length=50):
        """Display a simple progress bar without ETA"""
        if total == 0:
            return
            
        # Calculate percentage
        percent = min(float(current) / total, 1.0)
        filled_length = int(round(bar_length * percent))
        
        # Create the bar with clear characters for better visibility
        bar = '#' * filled_length + '-' * (bar_length - filled_length)
        
        # Format the progress display - simple version without ETA
        progress_text = f"\r{prefix}[{bar}] {int(percent*100):3d}% | {current}/{total} {suffix}"
        
        # Use print with flush=True for better display
        print(f"{COLOR_PROGRESS}{progress_text}{COLOR_RESET}", end='', flush=True)
        
        if current >= total:
            # Show completion message
            print(f"\r{COLOR_SUCCESS}{prefix}[{'#' * bar_length}] 100% | {total}/{total} | Correlation complete!{' '*30}{COLOR_RESET}")
            print()
    
    def _get_namespace_name(self, namespace_value):
        """
        Convert namespace numeric value to human-readable name.
        
        Args:
            namespace_value (int): The namespace value from MFT
            
        Returns:
            str: Human-readable namespace name
        """
        namespace_map = {
            0: "POSIX",      # Case-sensitive, all Unicode characters allowed
            1: "Win32",      # Case-insensitive, most Unicode characters allowed
            2: "DOS",        # 8.3 format, case-insensitive, limited character set
            3: "Win32 & DOS" # Both Win32 and DOS namespaces present
        }
        
        return namespace_map.get(namespace_value, f"Unknown ({namespace_value})")
    
    # -----------------------------------------------------------------------
    # A correlated database produced BEFORE the correlation was corrected.
    #
    # This one appends to an existing database rather than replacing it, and
    # creates its table with CREATE TABLE IF NOT EXISTS - so a case correlated
    # by the earlier version keeps its narrower table and the insert fails on
    # the columns that were added.
    #
    # Those rows are not merely differently shaped, they are wrong: they were
    # produced by the version that keyed on the MFT record number without the
    # sequence number, so a deleted file's journal events were attributed to
    # whichever file inherited its record.
    #
    # So the table is REBUILT, not migrated. Nothing is lost by that - the
    # correlated database is derived entirely from mft_claw_analysis.db and
    # USN_journal.db, and both are still in the case folder. Adding the columns
    # and keeping the old rows would leave known-wrong correlations sitting in
    # one table beside correct ones with nothing to tell them apart, which is
    # the worse outcome for evidence.
    # -----------------------------------------------------------------------
    STALE_MARKER_COLUMN = 'volume_letter'

    def _notify(self, status=None, log=None):
        """Report something a person should see, wherever they are watching.

        `status` is a short line for a progress display; `log` is the sentence
        that has to still make sense after the run has finished.

        The console output is unconditional so the headless, subprocess and
        offline paths behave exactly as they always did. Plain text only -
        this is read by a GUI that renders it as HTML, and terminal colour
        codes would arrive as escape sequences in the middle of it.
        """
        if log:
            logger.warning(log)
            print(log)
        if status:
            logger.info(status)

        if self.status_callback:
            try:
                self.status_callback(status=status, log=log)
            except Exception as e:
                # A display that cannot draw must never stop a correlation.
                logger.warning(f"Status callback failed, continuing: {e}")

    def _is_stale_schema(self, conn):
        """True if the correlated table predates the correlation fix."""
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='mft_usn_correlated'")
            if not cur.fetchone():
                return False                      # nothing there yet - not stale, just absent
            cur.execute("PRAGMA table_info(mft_usn_correlated)")
            columns = [row[1] for row in cur.fetchall()]
            return self.STALE_MARKER_COLUMN not in columns
        except sqlite3.Error as e:
            logger.warning(f"Could not read the correlated table's schema: {e}")
            return False

    def _rebuild_stale_tables(self):
        """Drop a pre-fix correlated table so it is rebuilt from the raw data."""
        # Said plainly, wherever the person is looking. A tool that silently
        # discards and regenerates a table in a case folder is worse than one
        # that says what it did and why - and "why" has to outlast the run,
        # which is why it goes to the log and not only to a status line.
        self._notify(
            status="REBUILDING CORRELATED TABLE",
            log=("[MFT-USN] This case was correlated before the MFT/USN correlation fix, "
                 "so its correlated rows are not reliable - journal events could be "
                 "attributed to the wrong file. Rebuilding from mft_claw_analysis.db and "
                 "USN_journal.db, which are unchanged, so nothing is lost."))
        try:
            conn = sqlite3.connect(self.correlated_db)
            cur = conn.cursor()
            # filename_changes is built from the same inputs - leaving it stale
            # beside a rebuilt table would have the two disagreeing.
            for table in ('mft_usn_correlated', 'filename_changes'):
                cur.execute(f"DROP TABLE IF EXISTS {table}")
            conn.commit()
            conn.close()
            logger.info("Stale correlated tables dropped; they will be rebuilt below.")
            return True
        except sqlite3.Error as e:
            logger.error(f"Could not rebuild the stale correlated database: {e}")
            print(f"{COLOR_ERROR}Could not rebuild the stale correlated database: {e}{COLOR_RESET}")
            return False

    def create_correlated_database(self):
        """Create or update database with comprehensive correlated data"""
        logger.info("Processing correlated database...")

        # Check if correlated database already exists
        database_exists = os.path.exists(self.correlated_db)
        
        if database_exists:
            logger.info(f"Existing correlated database found: {self.correlated_db}")

            # Check if database is accessible for appending data
            try:
                test_conn = sqlite3.connect(self.correlated_db)
                stale = self._is_stale_schema(test_conn)
                test_conn.close()
                logger.info("Database is accessible for appending data")
            except sqlite3.Error as e:
                # Database is locked/in use by another process
                logger.warning(f"Correlated database is locked/in use: {e}")
                logger.warning("Cannot access database for appending. Using existing data.")
                return False

            if stale:
                self._rebuild_stale_tables()
            else:
                # Rebuilt, never appended to. Both tables are derived entirely
                # from mft_claw_analysis.db and USN_journal.db, which are left
                # as they are. Appending duplicated every MFT-only row on each
                # re-correlation: the UNIQUE key includes the USN columns, and
                # NULLs never collide in SQLite, so INSERT OR IGNORE let them in.
                try:
                    conn = sqlite3.connect(self.correlated_db)
                    for table in ('mft_usn_correlated', 'filename_changes'):
                        conn.execute(f"DROP TABLE IF EXISTS {table}")
                    conn.commit()
                    conn.close()
                    logger.info("Existing correlated tables cleared; rebuilding them from the "
                                "MFT and USN databases")
                except sqlite3.Error as e:
                    logger.warning(f"Could not clear the correlated tables: {e}")
                    return False
        else:
            logger.info("Creating new correlated database")
        
        mft_conn = None
        usn_conn = None
        corr_conn = None
        
        try:
            # Connect to source databases
            mft_conn = sqlite3.connect(self.mft_db)
            
            # Handle USN database - may not exist or be empty
            if os.path.exists(self.usn_db) and os.path.getsize(self.usn_db) > 0:
                usn_conn = sqlite3.connect(self.usn_db)
            else:
                logger.warning("USN database is empty or does not exist. Continuing with MFT data only.")
                print(f"{COLOR_WARNING}USN database is empty or does not exist. Continuing with MFT data only.{COLOR_RESET}")
                usn_conn = None
            
            # Create new correlated database
            corr_conn = sqlite3.connect(self.correlated_db)
            corr_cursor = corr_conn.cursor()
            
            # Create comprehensive correlated table
            self._create_correlated_table(corr_cursor)
            
            # Populate with correlated data
            self._populate_correlated_data(mft_conn, usn_conn, corr_cursor)
            
            # Create indexes for performance
            self._create_indexes(corr_cursor)

            # The rename log (old name -> new name, from the journal) and the
            # per-file rename summary on the correlated rows.
            self._write_rename_log(corr_cursor)

            corr_conn.commit()
            logger.info(f"Correlated database created: {self.correlated_db}")
            
        except Exception as e:
            logger.error(f"Error creating correlated database: {e}")
            raise
        finally:
            if mft_conn:
                try:
                    mft_conn.close()
                except:
                    pass
            if usn_conn:
                try:
                    usn_conn.close()
                except:
                    pass
            if corr_conn:
                try:
                    corr_conn.close()
                except:
                    pass
    
    def _create_correlated_table(self, cursor):
        """Create the comprehensive correlated table"""
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS mft_usn_correlated (
            -- Identity. volume_letter is part of it: an MFT record number is
            -- unique per volume, not per machine, so record 5000 on C: and on
            -- D: are different files.
            volume_letter TEXT,

            -- MFT Core Information
            mft_record_number INTEGER,
            fn_filename TEXT,
            mft_sequence_number INTEGER,
            mft_flags TEXT,
            is_directory INTEGER,
            is_deleted INTEGER,
            file_extension TEXT,
            file_size INTEGER,
            in_use INTEGER,
            has_ads INTEGER,
            ads_count INTEGER,

            -- MFT Standard Information
            si_creation_time TEXT,
            si_modification_time TEXT,
            si_access_time TEXT,
            si_mft_entry_change_time TEXT,
            si_file_attributes TEXT,

            -- MFT File Name Information
            fn_parent_record_number INTEGER,
            fn_parent_sequence_number INTEGER,
            fn_namespace TEXT,
            fn_creation_time TEXT,
            fn_modification_time TEXT,
            fn_access_time TEXT,
            fn_mft_entry_change_time TEXT,
            fn_allocated_size INTEGER,
            fn_real_size INTEGER,
            fn_file_attributes TEXT,

            -- Derived File Information
            reconstructed_path TEXT,

            -- USN Journal Information
            usn_event_id INTEGER,
            usn_timestamp TEXT,
            usn_reason TEXT,
            usn_source_info TEXT,
            usn_file_attributes TEXT,
            -- The name the journal recorded AT THE TIME of the event, which is
            -- not necessarily the name the MFT holds now. That difference is
            -- the rename evidence.
            usn_filename TEXT,
            usn_frn TEXT,
            usn_parent_frn TEXT,
            usn_security_id INTEGER,

            -- Correlation & Analysis Fields
            has_mft_record INTEGER,
            has_usn_event INTEGER,
            correlation_confidence TEXT,

            -- Forensic Analysis Fields
            filename_change_timeline TEXT,
            namespace_evolution TEXT,

            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            -- Identity is volume + record + sequence + the event. Without the
            -- volume and the sequence this collapsed rows from different files
            -- onto each other.
            UNIQUE(volume_letter, mft_record_number, mft_sequence_number, usn_event_id, usn_timestamp, usn_reason)
        )
        """)
    
    def _populate_correlated_data(self, mft_conn, usn_conn, corr_cursor):
        """Populate the correlated table with joined data"""
        logger.info("Populating correlated data...")
        
        print(f"\n{COLOR_INFO}Retrieving MFT data...{COLOR_RESET}")
        # Get MFT data with reconstructed paths
        mft_cursor = mft_conn.cursor()
        mft_data = self._get_mft_data_with_paths(mft_cursor)
        print(f"{COLOR_INFO}Retrieved {len(mft_data)} MFT records{COLOR_RESET}")
        
        print(f"\n{COLOR_INFO}Retrieving USN data...{COLOR_RESET}")
        # Get USN journal data
        if usn_conn is not None:
            usn_data, usn_select_columns = self._get_usn_data(usn_conn.cursor())
        else:
            usn_data, usn_select_columns = [], []
        print(f"{COLOR_INFO}Retrieved {len(usn_data)} USN journal events{COLOR_RESET}")
        
        # Correlate and insert data with column information
        self._correlate_and_insert(mft_data, usn_data, usn_select_columns, corr_cursor)
    
    def _run_parser_subprocess(self, script, label):
        """Run a parser in its own interpreter and route its output to the log.

        Without stdout/stderr pipes the child inherits the OS handles, so its
        output goes past the parent's console tee entirely - and in the frozen
        windowless build, where there is no console at all, it goes nowhere.
        Two whole parsers ran that way. Captured here and replayed through the
        logger, so it lands in the case log like every other component's.
        """
        import subprocess as _sp
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        # Bounded: a parser that hangs (a locked volume, a stuck driver) used
        # to hold the correlation - and the live Parse All - for ever. On
        # timeout the parser's whole process tree is ended.
        try:
            from utils.concurrency.process_tree import run_with_timeout
            result = run_with_timeout([sys.executable, script], PARSER_SUBPROCESS_TIMEOUT,
                                      cwd=self.case_directory, env=env,
                                      stdout=_sp.PIPE, stderr=_sp.STDOUT)
        except _sp.TimeoutExpired:
            logger.error("[%s] did not finish within %d s and was ended", label,
                         PARSER_SUBPROCESS_TIMEOUT)
            return _sp.CompletedProcess([sys.executable, script], 124, b"", b"")
        except ImportError:
            result = _sp.run([sys.executable, script], cwd=self.case_directory, env=env,
                             stdout=_sp.PIPE, stderr=_sp.STDOUT,
                             timeout=PARSER_SUBPROCESS_TIMEOUT)
        text = (result.stdout or b"").decode("utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip():
                logger.info("[%s] %s", label, line.rstrip())
        return result

    def _get_mft_data_with_paths(self, cursor):
        """
        Get MFT data with reconstructed paths using optimized approach.
        
        This method avoids complex SQL subqueries by fetching data in two phases:
        1. Fetch all file names from mft_file_names table
        2. Fetch basic MFT record information from mft_records table
        3. Combine and process data in Python for better performance
        
        Returns:
            list: List of tuples containing MFT data with placeholders for missing columns
        """
        print(f"{COLOR_INFO}Executing MFT query... (this may take a few moments){COLOR_RESET}")
        
        # (A COUNT(DISTINCT) join here only printed a number before the real
        # query read the same rows again; the count is reported after it.)
        
        # Optimize the query - remove subqueries and use simpler joins for better performance
        print(f"{COLOR_INFO}Fetching MFT data...{COLOR_RESET}")
        
        # Start time for progress tracking
        start_time = time.time()
        
        # Fetch all necessary data in a single, optimized query
        print(f"{COLOR_INFO}Fetching and processing MFT data...{COLOR_RESET}")
        
        # Every join carries volume_letter. Without it, record 5000 on C: joins
        # to record 5000 on D: - two unrelated files merged into one row, and
        # each one's timestamps attributed to the other.
        query = """
        SELECT
            mr.record_number,
            mr.mft_sequence_number,
            mr.flags,
            mr.is_directory,
            mr.in_use,
            mfn.file_name,
            mfn.parent_record,
            mfn.parent_sequence,
            si.created AS si_created,
            si.modified AS si_modified,
            si.accessed AS si_accessed,
            si.mft_modified AS si_mft_modified,
            mr.file_attributes AS si_file_attributes,
            mfn.created AS fn_created,
            mfn.modified AS fn_modified,
            mfn.accessed AS fn_accessed,
            mfn.mft_modified AS fn_mft_modified,
            mfn.allocated_size,
            mfn.real_size,
            mfn.flags,
            mfn.namespace,
            mr.volume_letter,
            mr.extension,
            mr.file_size,
            mr.has_ads,
            mr.ads_count
        FROM mft_records mr
        LEFT JOIN mft_file_names mfn
               ON mr.record_number = mfn.record_number
              AND mr.volume_letter = mfn.volume_letter
        LEFT JOIN mft_standard_info si
               ON mr.record_number = si.record_number
              AND mr.volume_letter = si.volume_letter
        WHERE (mfn.file_name IS NOT NULL OR si.created IS NOT NULL)
        AND COALESCE(mfn.file_name, '') NOT LIKE ':%'
        ORDER BY mr.record_number, mr.volume_letter
        """
        # The ORDER BY is the primary key's own order, so SQLite reads it from
        # the index with no sort. It was (volume, record, namespace rank): a
        # temporary B-tree of every joined row (5.5 M, 26 columns) built before
        # the first row came back - 30 s of a 70 s fetch. A record's rows are
        # consecutive either way; the namespace rank is applied per record in
        # Python below (a handful of rows each).
        #
        # The first row per record is the name kept, and every path is built
        # from those names. Win32 & DOS (3), then Win32 (1), then POSIX (0);
        # the 8.3 DOS name (2) only when there is no other. It was
        # `namespace DESC`, which put DOS (2) ahead of Win32 (1): a file with a
        # long name and a separate short one was stored as MIGRAT~1.DAT, and
        # 181,609 paths of one case carried an 8.3 component.
        
        # Process records, selecting the best file name for each record number
        result = []
        processed_records = set()
        
        # Fetch data attributes counts and file names counts separately for efficiency
        # (before the main query: the main query is streamed on this cursor)
        data_attributes_counts = self._get_counts(cursor, "mft_data_attributes")
        file_names_counts = self._get_counts(cursor, "mft_file_names")

        # Extension records carry attributes of another (base) record; MFT_Claw
        # merges what they hold into the base. They are not files themselves.
        extension_records = set()
        try:
            cursor.execute("SELECT volume_letter, record_number FROM mft_data_attributes "
                           "WHERE data_type = 'ExtensionOf'")
            extension_records = set(cursor.fetchall())
        except sqlite3.Error:
            pass

        # A record's OTHER names - hard links, and the POSIX name beside a
        # Win32 one - for the namespace_evolution column. The 8.3 DOS alias is
        # left out: it is not another name anyone gave the file.
        self._other_names = {}
        self._first_name = {}

        # Streamed: fetchall() held every joined row (6.5 million on one case,
        # several hundred bytes each) at once, beside the result being built.
        cursor.execute(query)

        def _streamed(cur, size=20000):
            while True:
                rows = cur.fetchmany(size)
                if not rows:
                    return
                yield from rows

        def _rank(row):
            try:
                ns = int(row[20])
            except (TypeError, ValueError):
                return 3
            return _NAMESPACE_RANK.get(ns, 3)

        def _by_record(rows):
            """Each record's rows, best name first (stable: ties keep the
            order they were read in, as the SQL sort kept them)."""
            group, gkey = [], None
            for row in rows:
                key = (row[VOL], row[0])
                if key != gkey and group:
                    if len(group) > 1:
                        group.sort(key=_rank)
                    yield from group
                    group = []
                gkey = key
                group.append(row)
            if group:
                if len(group) > 1:
                    group.sort(key=_rank)
                yield from group

        for row in _by_record(_streamed(cursor)):
            # Keyed by volume AND record: the same record number on two volumes
            # is two files, and de-duplicating on the number alone silently
            # discarded whichever one the ORDER BY happened to put second.
            key = (row[VOL], row[0])
            if key in extension_records:
                continue
            if key in processed_records:
                name, ns = row[5], row[20]
                try:
                    ns = int(ns)
                except (TypeError, ValueError):
                    ns = None
                if name and ns != 2:
                    names = self._other_names.setdefault(key, [])
                    label = {0: 'POSIX', 1: 'Win32', 3: 'Win32 & DOS'}.get(ns, 'other')
                    entry = f"{label}: {name}"
                    if entry not in names and name != self._first_name.get(key):
                        names.append(entry)
                continue
            if key not in processed_records:
                self._first_name[key] = row[5]
                # index 8 is si.created - index 7 is mfn.parent_sequence, which
                # is present for every row and made this constantly 1
                standard_info_present = 1 if row[8] is not None else 0

                data_attributes_count = data_attributes_counts.get(key, 0)
                file_names_count = file_names_counts.get(key, 0)

                # Assemble the final row, including the namespace (last element)
                final_row = row + (data_attributes_count, standard_info_present, file_names_count)
                result.append(final_row)
                processed_records.add(key)

        print(f"{COLOR_SUCCESS}\nSuccessfully processed {len(result):,} MFT records in {time.time() - start_time:.2f} seconds{COLOR_RESET}")
        return result
    
    def _get_counts(self, cursor, table_name):
        """{(volume, record): row count} for one MFT table - per volume, since
        record 5000 on C: is not record 5000 on D:."""
        cursor.execute(f"SELECT volume_letter, record_number, COUNT(*) FROM {table_name} "
                       f"GROUP BY volume_letter, record_number")
        return {(v, r): n for v, r, n in cursor.fetchall()}

    def _get_usn_data(self, cursor):
        """
        Get USN journal data from journal_events table.
        
        This method retrieves data from the actual USN journal table structure
        created by USN_Claw parser.
        
        Returns:
            tuple: (usn_data, select_columns) where:
                - usn_data: List of USN journal records
                - select_columns: List of column names used in the query
        """
        print(f"{COLOR_INFO}Fetching USN journal data...{COLOR_RESET}")
        
        # Use the actual column names from journal_events table
        select_columns = [
            "frn",           # File Reference Number (equivalent to file_reference_number)
            "parent_frn",    # Parent File Reference Number
            "usn",           # USN value
            "timestamp",     # Event timestamp
            "reason",        # USN reason flags
            "source_info",   # Source information
            "security_id",   # Security ID
            "file_attributes", # File attributes
            "filename",      # Filename
            "record_length", # Record length (can be used as file_size proxy)
            "volume_letter"  # An MFT record number is unique per volume only
        ]
        
        query = f"SELECT {', '.join(select_columns)} FROM journal_events ORDER BY usn"
        
        cursor.execute(query)
        usn_data = cursor.fetchall()
        
        # Show progress
        total_usn = len(usn_data)
        bar_length = 30
        bar = '#' * bar_length
        print(f"\r[{bar}] {100:6.1f}% | {total_usn:,}/{total_usn:,} USN records", flush=True)
        
        print(f"\nSuccessfully fetched {len(usn_data):,} USN journal records")
        return usn_data, select_columns
    
    def _extract_mft_reference_from_frn(self, frn_string):
        """
        Extract the MFT record number AND sequence number from a USN file
        reference number.

        Windows file reference number format:
        - lower 48 bits  MFT record number
        - upper 16 bits  sequence number

        THE SEQUENCE NUMBER IS NOT OPTIONAL. NTFS reuses an MFT record when the
        file occupying it is deleted, incrementing the sequence number to mark
        that the record now means something else. Keying correlation on the
        record number alone attaches the deleted file's journal events to
        whichever file inherited its record - producing a confident timeline
        for the wrong file, with no error to indicate it.

        Args:
            frn_string (str): String representation of file reference number

        Returns:
            tuple or None: (record_number, sequence_number), or None if the
            reference cannot be read.
        """
        frn_int = self._frn_to_int(frn_string)
        if frn_int is None:
            return None
        record = frn_int & 0xFFFFFFFFFFFF        # low 48 bits
        sequence = (frn_int >> 48) & 0xFFFF      # high 16 bits
        return (record, sequence)

    @staticmethod
    def _frn_to_int(frn):
        """A USN file reference as an integer.

        Version 2 records store it as a decimal string. Version 3 records
        store a 128-bit FILE_ID_128 as 32 hex digits, high half first; on NTFS
        the 64-bit file reference is the low half. Read as decimal, a v3 id
        made only of digits decoded to a wrong file and any other was skipped.
        """
        if frn is None:
            return None
        if isinstance(frn, int):
            return frn
        s = str(frn).strip()
        if not s:
            return None
        if s.isdigit() and len(s) != 32:
            return int(s)
        h = s[2:] if s.lower().startswith('0x') else s
        try:
            value = int(h, 16)
        except ValueError:
            return None
        return value & 0xFFFFFFFFFFFFFFFF

    @staticmethod
    def _usn_field(usn_row, select_columns, name):
        """One USN column by name, or None if this build did not select it."""
        try:
            return usn_row[select_columns.index(name)]
        except (ValueError, IndexError, TypeError):
            return None

    def flags_to_text(self, flags_val):
        """Convert MFT flags to a human-readable string."""
        if flags_val is None:
            return ""
        # Coerce like file_attributes_to_text does. A value that arrives as a
        # string - from an older database, or a column whose declared affinity
        # converted it - otherwise raises deep inside the correlation loop.
        try:
            flags_val = int(flags_val)
        except (ValueError, TypeError):
            return str(flags_val)
        flags = []
        if flags_val & 0x1: flags.append("IN_USE")
        if flags_val & 0x2: flags.append("IS_DIRECTORY")
        return ", ".join(flags) if flags else str(flags_val)

    def _correlate_and_insert(self, mft_data, usn_data, usn_select_columns, corr_cursor):
        """
        Correlate MFT and USN data and insert into correlated table.
        
        This method performs the core correlation logic:
        1. Builds lookup tables for MFT and USN data for fast access
        2. Processes each MFT record to find matching USN events
        3. Reconstructs file paths using parent-child relationships
        4. Performs batch inserts for optimal performance
        5. Tracks correlation statistics and progress
        
        Args:
            mft_data (list): List of MFT records to correlate
            usn_data (list): List of USN journal events to correlate
            corr_cursor: SQLite cursor for the correlated database
        """
        logger.info("Correlating MFT and USN data...")
        start_time = time.time()
        last_update_time = time.time()  # For progress bar updates
        
        # Create mapping for quick lookup - optimize with dictionaries.
        # Keyed by (volume, record) - see the note on VOL above.
        mft_by_record = {}
        for row in mft_data:
            key = (row[VOL], row[0])
            if key not in mft_by_record:
                mft_by_record[key] = []
            mft_by_record[key].append(row)

        # USN lookup keyed by (volume, record, sequence). All three matter:
        # the record number alone is ambiguous across volumes, and without the
        # sequence number a deleted file's events attach to whatever now
        # occupies its record.
        usn_by_mft_record = {}
        matched_usn_keys = set()
        # What the journal last called each (volume, record, sequence), and its
        # parent - how a folder deleted before the MFT was read still gets a
        # name in the paths below it.
        self._journal_names = {}
        self._mft_by_record = mft_by_record
        self._path_cache = {}
        self._dir_memo = {}
        self._usn_rows, self._usn_cols = usn_data, usn_select_columns
        if usn_data:  # Only process if we have USN data
            # Find the correct index for file reference number in the select_columns
            ref_num_index = None
            for i, col_name in enumerate(usn_select_columns):
                # Look for frn (File Reference Number) or file_reference variations
                if col_name.lower() in ['frn', 'file_reference_number', 'file_reference']:
                    ref_num_index = i
                    break

            vol_index = (usn_select_columns.index('volume_letter')
                         if 'volume_letter' in usn_select_columns else None)

            if ref_num_index is None:
                print(f"{COLOR_WARNING}WARNING: No file_reference column found in USN data - correlation may fail{COLOR_RESET}")
            else:
                for usn_row in usn_data:
                    try:
                        ref_num = usn_row[ref_num_index]  # file_reference field
                        if not ref_num:
                            continue
                        reference = self._extract_mft_reference_from_frn(ref_num)
                        if not reference:
                            continue
                        record, sequence = reference
                        volume = usn_row[vol_index] if vol_index is not None else None
                        key = (volume, record, sequence)
                        if key not in usn_by_mft_record:
                            usn_by_mft_record[key] = []
                        usn_by_mft_record[key].append(usn_row)
                        name = self._usn_field(usn_row, usn_select_columns, 'filename')
                        if name:
                            parent = self._extract_mft_reference_from_frn(
                                self._usn_field(usn_row, usn_select_columns, 'parent_frn'))
                            self._journal_names[key] = (
                                name, (volume,) + parent if parent else None)
                    except (IndexError, TypeError):
                        # Skip rows with missing or invalid file_reference
                        continue

        # Insert correlated data
        inserted_count = 0
        total_records = len(mft_data)
        matched_with_usn = 0
        
        # Use batch inserts for better performance
        batch_size = 5000  # Increased batch size for better performance
        insert_batch = []
        
        print(f"Starting correlation of {total_records:,} MFT records with {len(usn_data):,} USN events...")
        
        # Process MFT data first
        path_cache = self._path_cache
        for i, mft_record_data in enumerate(mft_data):
            # mft_record_data is a tuple. Destructure for readability.
            # Tuple structure: (record_number, sequence_number, flags, is_directory, is_deleted, fn_filename, 
            # parent_record, parent_sequence, si_created, si_modified, si_accessed, si_mft_modified, si_file_attributes,
            # fn_created, fn_modified, fn_accessed, fn_mft_modified, fn_allocated_size, fn_real_size, fn_file_flags, namespace,
            # data_attributes_count, standard_info_present, file_names_count)
            record_num = mft_record_data[0]
            sequence_number = mft_record_data[1]
            flags = mft_record_data[2]
            is_directory = mft_record_data[3]
            is_deleted = not mft_record_data[4]
            fn_filename = mft_record_data[5]
            parent_record = mft_record_data[6]
            parent_sequence = mft_record_data[7]
            si_created = mft_record_data[8]
            si_modified = mft_record_data[9]
            si_accessed = mft_record_data[10]
            si_mft_modified = mft_record_data[11]
            si_file_attributes = mft_record_data[12]
            fn_created = mft_record_data[13]
            fn_modified = mft_record_data[14]
            fn_accessed = mft_record_data[15]
            fn_mft_modified = mft_record_data[16]
            fn_allocated_size = mft_record_data[17]
            fn_real_size = mft_record_data[18]
            fn_file_flags = mft_record_data[19]
            namespace = mft_record_data[20]  # New: namespace field
            # The three counts are appended after the 26 query columns; 21-23
            # are volume, extension and size.
            data_attributes_count = mft_record_data[26]
            standard_info_present = mft_record_data[27]
            file_names_count = mft_record_data[28]

            in_use_val = mft_record_data[4]
            volume_letter = mft_record_data[VOL]
            file_extension = mft_record_data[EXT]
            file_size = mft_record_data[FILE_SIZE]
            has_ads = mft_record_data[HAS_ADS]
            ads_count = mft_record_data[ADS_COUNT]

            # Reconstruct path using parent-child relationships
            reconstructed_path = self._reconstruct_path(
                (volume_letter, record_num), mft_by_record, path_cache)
            other_names = ' | '.join(self._other_names.get((volume_letter, record_num), [])) or None

            # Convert file attributes to text for better readability
            flags_text = self.flags_to_text(flags)
            si_file_attributes_text = file_attributes_to_text(si_file_attributes)
            fn_file_flags_text = file_attributes_to_text(fn_file_flags)

            # Check if this record has matching USN entries
            usn_events_to_process = []

            # Volume, record AND sequence - a record that has been reused must
            # not collect the events of the file that used to occupy it.
            usn_key = (volume_letter, record_num, sequence_number)
            if usn_by_mft_record.get(usn_key):
                usn_events_to_process = usn_by_mft_record[usn_key]
                matched_usn_keys.add(usn_key)
                matched_with_usn += 1
            else:
                # If no USN events, still process once for MFT record
                usn_events_to_process = [None]
            
            # Process each USN event (or once if no events)
            for usn_event in usn_events_to_process:
                usn_event_id = None
                usn_value = None
                usn_reason = None
                usn_timestamp = None
                usn_volume_letter = None
                usn_file_attributes_val = None
                usn_file_attributes_text = None
                has_usn_event = 0
                
                usn_filename = None
                usn_frn = None
                usn_parent_frn = None
                usn_security_id = None

                if usn_event:
                    usn_event_id = usn_event[usn_select_columns.index('usn')]
                    usn_value = usn_event[usn_select_columns.index('usn')]
                    usn_reason = usn_reason_to_text(usn_event[usn_select_columns.index('reason')])
                    usn_timestamp = usn_event[usn_select_columns.index('timestamp')]
                    # NOT a volume letter - source_info is the USN source flags.
                    # The name is kept for the column it feeds, usn_source_info.
                    usn_volume_letter = usn_event[usn_select_columns.index('source_info')]

                    # Fetched by the query all along and then discarded. The
                    # filename is the name the journal recorded AT the event,
                    # which is what makes a rename visible.
                    usn_filename = self._usn_field(usn_event, usn_select_columns, 'filename')
                    usn_frn = self._usn_field(usn_event, usn_select_columns, 'frn')
                    usn_parent_frn = self._usn_field(usn_event, usn_select_columns, 'parent_frn')
                    usn_security_id = self._usn_field(usn_event, usn_select_columns, 'security_id')

                    # Extract USN file attributes if available
                    try:
                        usn_file_attributes_val = usn_event[usn_select_columns.index('file_attributes')]
                        if usn_file_attributes_val is not None:
                            usn_file_attributes_text = file_attributes_to_text(usn_file_attributes_val)
                    except (IndexError, ValueError):
                        usn_file_attributes_text = None
                    
                    has_usn_event = 1
                
                # Add to batch with all the glorious data
                insert_batch.append((
                    volume_letter,
                    record_num,
                    fn_filename,
                    reconstructed_path,
                    sequence_number,
                    flags_text,
                    is_directory,
                    is_deleted,
                    file_extension,
                    file_size,
                    in_use_val,
                    has_ads,
                    ads_count,
                    si_created,
                    si_modified,
                    si_mft_modified,
                    si_accessed,
                    si_file_attributes_text,
                    parent_record,
                    parent_sequence,
                    fn_created,
                    fn_modified,
                    fn_mft_modified,
                    fn_accessed,
                    fn_allocated_size,
                    fn_real_size,
                    fn_file_flags_text,
                    namespace,
                    usn_event_id,
                    usn_timestamp,
                    usn_reason,
                    usn_volume_letter,
                    usn_file_attributes_text,
                    usn_filename,
                    usn_frn,
                    usn_parent_frn,
                    usn_security_id,
                    1,  # has_mft_record
                    has_usn_event,
                    'HIGH' if has_usn_event else 'MEDIUM',
                    None,  # filename_change_timeline - the renames, filled below
                    other_names  # namespace_evolution - the record's other names
                ))

                # Execute batch insert when batch is full
                if len(insert_batch) >= batch_size:
                    corr_cursor.executemany(CORRELATED_INSERT, insert_batch)
                    inserted_count += len(insert_batch)
                    insert_batch = []

                # Show progress with detailed statistics - use time-based updates to prevent freezing
                current_time = time.time()
                # Progress in MFT records done (i + 1), not rows written: a
                # file with journal events writes one row per event, so rows
                # over records read "3,345,000/3,272,581".
                done = i + 1
                if current_time - last_update_time >= 1.0 or done == total_records:  # Update less frequently (1.0s)
                    elapsed = current_time - start_time
                    percent = min(float(done) / total_records, 1.0) * 100
                    records_per_sec = done / elapsed if elapsed > 0 else 0

                    # Create a more visible progress bar
                    bar_length = 40
                    filled_length = int(bar_length * done // total_records)
                    bar = '#' * filled_length + '-' * (bar_length - filled_length)

                    # Format the progress information with processing speed
                    stats = f"{percent:6.1f}% | {done:,}/{total_records:,} MFT records | {records_per_sec:.1f} rec/s"
                    
                    # Clear the line and show progress bar only once (not on every line)
                    if inserted_count == batch_size:  # First update
                        print(f"\n{COLOR_PROGRESS}Correlation Progress:{COLOR_RESET}")
                        print(f"{COLOR_PROGRESS}[{bar}] {stats}{COLOR_RESET}", end="", flush=True)
                    else:
                        print(f"\r{COLOR_PROGRESS}[{bar}] {stats}{COLOR_RESET}", end="", flush=True)
                    
                    last_update_time = current_time
        
        # Insert any remaining records
        if insert_batch:
            corr_cursor.executemany(CORRELATED_INSERT, insert_batch)
            inserted_count += len(insert_batch)
            insert_batch = []

        # -------------------------------------------------------------------
        # ORPHAN JOURNAL EVENTS
        #
        # Everything above walks MFT records, so a journal event whose file has
        # no MFT record was silently dropped - and `has_mft_record` was written
        # as a literal 1, so the column could never say otherwise.
        #
        # Those are the events worth having. A file created and deleted between
        # two collections leaves no MFT record at all; the journal is the only
        # place it ever existed. Discarding them means the correlated database
        # can only ever show files that survived to be collected.
        # -------------------------------------------------------------------
        orphan_count = 0
        for usn_key, events in usn_by_mft_record.items():
            if usn_key in matched_usn_keys:
                continue
            volume, record, sequence = usn_key
            for usn_event in events:
                usn_attrs = self._usn_field(usn_event, usn_select_columns, 'file_attributes')
                insert_batch.append((
                    volume,
                    record, None,                # no MFT record, so no File-Name
                    # ...but a path: the journal's name under its parent folder,
                    # which is in the MFT or named by the journal itself. Left
                    # empty, 87% of one case's events had no folder, and a
                    # search by folder could not find them.
                    self._journal_event_path(volume, usn_event, usn_select_columns),
                    sequence, None, None, None,
                    None, None, None, None, None,
                    None, None, None, None, None,
                    None, None,
                    None, None, None, None, None, None, None, None,
                    self._usn_field(usn_event, usn_select_columns, 'usn'),
                    self._usn_field(usn_event, usn_select_columns, 'timestamp'),
                    usn_reason_to_text(self._usn_field(usn_event, usn_select_columns, 'reason')),
                    self._usn_field(usn_event, usn_select_columns, 'source_info'),
                    file_attributes_to_text(usn_attrs) if usn_attrs is not None else None,
                    self._usn_field(usn_event, usn_select_columns, 'filename'),
                    self._usn_field(usn_event, usn_select_columns, 'frn'),
                    self._usn_field(usn_event, usn_select_columns, 'parent_frn'),
                    self._usn_field(usn_event, usn_select_columns, 'security_id'),
                    0,   # has_mft_record - the point of this pass
                    1,   # has_usn_event
                    'JOURNAL_ONLY',
                    None, None
                ))
                orphan_count += 1
                if len(insert_batch) >= batch_size:
                    corr_cursor.executemany(CORRELATED_INSERT, insert_batch)
                    inserted_count += len(insert_batch)
                    insert_batch = []

        if insert_batch:
            corr_cursor.executemany(CORRELATED_INSERT, insert_batch)
            inserted_count += len(insert_batch)
            insert_batch = []

        if orphan_count:
            print(f"{COLOR_INFO}{orphan_count:,} journal event(s) had no MFT record - "
                  f"kept as JOURNAL_ONLY{COLOR_RESET}")

        # Final statistics
        elapsed = time.time() - start_time
        records_per_sec = inserted_count / elapsed if elapsed > 0 else 0
        usn_match_percent = (matched_with_usn / inserted_count * 100) if inserted_count > 0 else 0
        
        # Print a new line to ensure the progress bar is complete
        print("\n")
        print(f"{COLOR_HEADER}{'=' * 60}{COLOR_RESET}")
        print(f"{COLOR_SUCCESS}[OK] Correlation complete in {elapsed:.2f} seconds!{COLOR_RESET}")
        print(f"{COLOR_SUCCESS}[OK] Total records processed: {inserted_count:,} ({records_per_sec:.1f} records/second){COLOR_RESET}")
        print(f"{COLOR_SUCCESS}[OK] Records with USN matches: {matched_with_usn:,} ({usn_match_percent:.1f}%){COLOR_RESET}")
        print(f"{COLOR_HEADER}{'=' * 60}{COLOR_RESET}")
        
        logger.info(f"Total {inserted_count} correlated records inserted in {elapsed:.2f} seconds")

    def _reconstruct_path(self, key, mft_by_record, path_cache):
        """
        Iteratively reconstruct file path using a cache to avoid re-computation.

        `key` is (volume_letter, record_number). A path is walked by following
        parent record numbers, and those are only meaningful within one volume -
        walking across volumes would splice one disk's directory tree into
        another's.

        Each step checks the parent's SEQUENCE number too: a $FILE_NAME points
        at "record 4711, sequence 3", and if record 4711 now holds sequence 9
        the folder it named was deleted and the entry reused - following it
        would print a plausible path through a folder the file was never in.
        Such a parent, and one that is not in the MFT at all, is looked up in
        the journal, which often still names it.
        """
        if key in path_cache:
            return path_cache[key]

        volume, record_num = key
        path_parts = []
        current_record = record_num
        visited = set()
        prefix = None

        while current_record is not None and current_record != 0 and current_record not in visited:
            visited.add(current_record)
            record_data = mft_by_record[(volume, current_record)][0]
            filename = record_data[5]
            parent_record = record_data[6]
            parent_seq = record_data[7]

            if filename:
                path_parts.append(filename)

            if parent_record == current_record or parent_record is None or parent_record == 0:
                break

            parent_rows = mft_by_record.get((volume, parent_record))
            if parent_rows and not self._seq_mismatch(parent_seq, parent_rows[0][1]):
                current_record = parent_record
                continue

            # Not in the MFT, or the entry was reused: ask the journal.
            jpath = self._journal_dir_path((volume, parent_record, parent_seq))
            if jpath is not None:
                prefix = jpath
            elif parent_rows:
                path_parts.append(f"[Reused Parent: {parent_record}]")
            else:
                path_parts.append(f"[Unknown Parent: {parent_record}]")
            break

        # Handle root directory case
        if not path_parts and prefix is None:
            if record_num == 5:  # MFT record 5 is usually the root directory
                reconstructed_path = "./"
            else:
                reconstructed_path = "[Unknown]"
        else:
            parts = list(reversed(path_parts))
            if prefix is not None:
                parts.insert(0, prefix.rstrip("/"))
            reconstructed_path = "/".join(p for p in parts if p != "")

        path_cache[key] = reconstructed_path
        return reconstructed_path

    @staticmethod
    def _seq_mismatch(wanted, actual):
        """True when a reference's sequence names an earlier occupant. MFT_Claw
        stores a parent sequence of 0 as 1, so 1 is not evidence either way."""
        try:
            wanted, actual = int(wanted), int(actual)
        except (TypeError, ValueError):
            return False
        return wanted > 1 and actual > 0 and wanted != actual

    def _journal_dir_path(self, key, depth=0):
        """Path of a directory (volume, record, sequence) that the MFT cannot
        give: its last journal name under its own parent, recursively, until a
        folder the MFT does have (or the root). None if the chain breaks."""
        memo = getattr(self, '_dir_memo', None)
        if memo is None:
            return None
        if key in memo:
            return memo[key]
        memo[key] = None                     # cycle guard
        volume, record, seq = key
        out = None
        if record == 5:
            out = "."
        else:
            rows = self._mft_by_record.get((volume, record))
            if rows and not self._seq_mismatch(seq, rows[0][1]):
                p = self._reconstruct_path((volume, record), self._mft_by_record, self._path_cache)
                if (p and not p.startswith("[") and "[Unknown Parent" not in p
                        and "[Reused Parent" not in p):
                    out = p.rstrip("/") if p != "./" else "."
            if out is None and depth < 64:
                hit = self._journal_names.get(key)
                if hit:
                    name, parent = hit
                    pp = self._journal_dir_path(parent, depth + 1) if parent else None
                    if pp is not None:
                        out = f"{pp.rstrip('/')}/{name}"
        memo[key] = out
        return out

    def _journal_event_path(self, volume, usn_event, cols):
        """Full path for a journal-only event: its folder (MFT or journal) and
        the name the journal recorded."""
        name = self._usn_field(usn_event, cols, 'filename') or ""
        parent = self._extract_mft_reference_from_frn(self._usn_field(usn_event, cols, 'parent_frn'))
        if not parent:
            return None
        folder = self._journal_dir_path((volume,) + parent)
        if folder is None:
            return f"[Unknown Parent: {parent[0]}]/{name}" if name else None
        return f"{folder.rstrip('/')}/{name}" if name else folder

    def _create_indexes(self, cursor):
        """
        Create database indexes for query performance optimization.
        
        Indexes significantly improve query performance for common forensic
        analysis patterns like searching by filename, path, or timestamps.
        
        Args:
            cursor: SQLite cursor for executing index creation statements
        """
        logger.info("Creating indexes for performance optimization...")
        
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_corr_mft_record ON mft_usn_correlated(mft_record_number)",
            "CREATE INDEX IF NOT EXISTS idx_corr_filename ON mft_usn_correlated(fn_filename)",
            "CREATE INDEX IF NOT EXISTS idx_corr_path ON mft_usn_correlated(reconstructed_path)",
            "CREATE INDEX IF NOT EXISTS idx_corr_timestamps ON mft_usn_correlated(si_creation_time, si_modification_time, usn_timestamp)",
            # The MFT/USN dashboard: a day's events, and one file by volume +
            # record + sequence (a day's drill-down 0.15 s -> 0.04 s on 482k rows).
            "CREATE INDEX IF NOT EXISTS idx_corr_usn_event ON mft_usn_correlated(has_usn_event, usn_timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_corr_vol_rec ON mft_usn_correlated(volume_letter, mft_record_number, mft_sequence_number)",
            # The dashboard's MFT strip counts files per day by $SI created /
            # modified. Covering and partial (MFT rows only): on a 3.5-million-row
            # live case each count went from a ~6 s table scan to ~3 s.
            "CREATE INDEX IF NOT EXISTS idx_corr_si_created ON mft_usn_correlated"
            "(si_creation_time, volume_letter, mft_record_number) WHERE has_mft_record = 1",
            "CREATE INDEX IF NOT EXISTS idx_corr_si_modified ON mft_usn_correlated"
            "(si_modification_time, volume_letter, mft_record_number) WHERE has_mft_record = 1",
            # ...and its overview's file counts (files, folders, deleted, ADS):
            # one pass in record order instead of four temporary B-trees.
            "CREATE INDEX IF NOT EXISTS idx_corr_mft_files ON mft_usn_correlated"
            "(mft_record_number, volume_letter, is_directory, is_deleted, has_ads) WHERE has_mft_record = 1",
            # Timestomp candidates ($SI created later than $FN created): a
            # partial index holding only those rows, so the overview's insight
            # reads a few thousand entries instead of scanning millions.
            "CREATE INDEX IF NOT EXISTS idx_corr_timestomp ON mft_usn_correlated"
            "(volume_letter, mft_record_number, si_creation_time, fn_creation_time) "
            "WHERE has_mft_record = 1 AND si_creation_time > fn_creation_time",
            # The USN strip and the overview group events by day and reason:
            # covering, so the reason is read from the index, not 3.8 M rows
            # (2.6 s -> 0.5 s on case 7.10.2026).
            "CREATE INDEX IF NOT EXISTS idx_corr_usn_reason ON mft_usn_correlated"
            "(has_usn_event, usn_timestamp, usn_reason)",
            # Files with alternate data streams: a few thousand rows, which the
            # overview found by scanning the table (5.2 s -> 0.02 s).
            "CREATE INDEX IF NOT EXISTS idx_corr_ads ON mft_usn_correlated"
            "(volume_letter, mft_record_number) WHERE has_ads = 1",
        ]
        
        for index_sql in indexes:
            cursor.execute(index_sql)
    
    # ------------------------------------------------------------------
    # The rename log
    # ------------------------------------------------------------------
    RENAME_COLUMNS = (
        "volume_letter", "mft_record_number", "mft_sequence_number", "rename_time",
        "old_name", "new_name", "old_parent_path", "new_parent_path", "is_move",
        "usn_old", "usn_new", "parsed_at",
    )

    def pair_renames(self, usn_rows, cols):
        """Pair each RENAME_OLD_NAME journal record with the RENAME_NEW_NAME that
        follows it for the same file (volume + file reference), in USN order.

        NTFS writes a rename as an OLD record carrying the old name and parent,
        then a NEW record carrying the new ones (usually twice: once more with
        CLOSE). On one case, 4,107 of 4,107 OLD records had their NEW as the
        file's very next record. The MFT cannot hold this - it keeps a file's
        current names only - so this is the only place a name history exists.

        Returns (renames, unpaired_old, unpaired_new); a rename is a dict.
        """
        pending = {}          # (vol, frn) -> the OLD row
        last_new = {}         # (vol, frn) -> name of the last paired NEW
        out, unpaired_old, unpaired_new = [], 0, 0
        for row in usn_rows:
            reason = str(self._usn_field(row, cols, 'reason') or "")
            flags = {f.strip() for f in reason.split("|")}
            is_old, is_new = "RENAME_OLD_NAME" in flags, "RENAME_NEW_NAME" in flags
            if not (is_old or is_new):
                continue
            frn = self._frn_to_int(self._usn_field(row, cols, 'frn'))
            if frn is None:
                continue
            vol = self._usn_field(row, cols, 'volume_letter')
            key = (vol, frn)
            name = self._usn_field(row, cols, 'filename')
            if is_old:
                if key in pending:
                    unpaired_old += 1
                pending[key] = row
                continue
            old = pending.pop(key, None)
            if old is None:
                # The NEW record repeated with CLOSE is the same rename again.
                if last_new.get(key) != name:
                    unpaired_new += 1
                continue
            last_new[key] = name
            out.append({
                "volume": vol, "frn": frn,
                "time": self._usn_field(row, cols, 'timestamp'),
                "old_name": self._usn_field(old, cols, 'filename'),
                "new_name": name,
                "old_parent": self._extract_mft_reference_from_frn(
                    self._usn_field(old, cols, 'parent_frn')),
                "new_parent": self._extract_mft_reference_from_frn(
                    self._usn_field(row, cols, 'parent_frn')),
                "usn_old": self._usn_field(old, cols, 'usn'),
                "usn_new": self._usn_field(row, cols, 'usn'),
            })
        unpaired_old += len(pending)
        return out, unpaired_old, unpaired_new

    def _write_rename_log(self, cursor):
        """Write `filename_changes` (one row per rename: old name -> new name,
        old folder -> new folder) and summarise each file's renames on its
        correlated rows (`filename_change_timeline`)."""
        cursor.execute("DROP TABLE IF EXISTS filename_changes")
        cursor.execute("""
        CREATE TABLE filename_changes (
            volume_letter TEXT,
            mft_record_number INTEGER,
            mft_sequence_number INTEGER,
            rename_time TEXT,
            old_name TEXT,
            new_name TEXT,
            old_parent_path TEXT,
            new_parent_path TEXT,
            is_move INTEGER,
            usn_old INTEGER,
            usn_new INTEGER,
            parsed_at TEXT,
            -- One rename is one RENAME_OLD_NAME record of one volume.
            UNIQUE(volume_letter, usn_old)
        )
        """)
        rows = getattr(self, '_usn_rows', None) or []
        cols = getattr(self, '_usn_cols', None) or []
        if not rows or 'reason' not in cols:
            logger.info("No journal records to pair renames from")
            return 0
        renames, unpaired_old, unpaired_new = self.pair_renames(rows, cols)
        parsed_at = get_current_forensic_timestamp()

        def folder(vol, parent):
            if not parent:
                return None
            path = self._journal_dir_path((vol,) + parent)
            return path if path is not None else f"[Unknown Parent: {parent[0]}]"

        out = []
        per_file = {}
        for r in renames:
            rec, seq = r["frn"] & 0xFFFFFFFFFFFF, (r["frn"] >> 48) & 0xFFFF
            old_dir, new_dir = folder(r["volume"], r["old_parent"]), folder(r["volume"], r["new_parent"])
            is_move = 1 if (r["old_parent"] and r["new_parent"]
                            and r["old_parent"] != r["new_parent"]) else 0
            out.append((r["volume"], rec, seq, r["time"], r["old_name"], r["new_name"],
                        old_dir, new_dir, is_move, r["usn_old"], r["usn_new"], parsed_at))
            text = f"{r['time']} {r['old_name']} -> {r['new_name']}"
            if is_move:
                text += f" (moved to {new_dir})"
            per_file.setdefault((r["volume"], rec, seq), []).append(text)
        cursor.executemany(
            "INSERT OR IGNORE INTO filename_changes (%s) VALUES (%s)"
            % (", ".join(self.RENAME_COLUMNS), ", ".join("?" * len(self.RENAME_COLUMNS))), out)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fnc_file ON filename_changes"
                       "(volume_letter, mft_record_number, mft_sequence_number)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fnc_time ON filename_changes(rename_time)")
        # Matched on volume, record AND sequence: a rename belongs to the file
        # that held the record then, not to whichever holds it now.
        cursor.executemany(
            "UPDATE mft_usn_correlated SET filename_change_timeline = ? "
            "WHERE volume_letter = ? AND mft_record_number = ? AND mft_sequence_number = ?",
            [(" | ".join(v[-20:]), k[0], k[1], k[2]) for k, v in per_file.items()])
        logger.info(f"Recorded {len(out):,} renames (old name -> new name) from the journal; "
                    f"{sum(x[8] for x in out):,} of them moved the file to another folder")
        if unpaired_old or unpaired_new:
            logger.info(f"{unpaired_old:,} RENAME_OLD_NAME and {unpaired_new:,} RENAME_NEW_NAME "
                        f"record(s) had no partner in the journal (the other half fell outside "
                        f"its window) - not recorded as renames")
        return len(out)

    def run_complete_analysis(self):
        """
        Run the complete MFT-USN correlation pipeline.
        
        This method orchestrates the entire correlation process:
        1. Checks if source databases exist
        2. Runs parsers if databases are missing
        3. Creates the correlated database
        4. Generates a comprehensive forensic report
        
        Returns:
            bool: True if analysis completed successfully, False otherwise
        """
        logger.info("Starting MFT-USN correlation analysis")
        
        # Check if databases exist AND have data
        mft_exists = os.path.exists(self.mft_db)
        usn_exists = os.path.exists(self.usn_db)
        
        mft_has_data = False
        usn_has_data = False
        
        # Check if MFT database has data
        if mft_exists:
            try:
                conn = sqlite3.connect(self.mft_db)
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM mft_records")
                mft_count = cursor.fetchone()[0]
                conn.close()
                mft_has_data = (mft_count > 0)
                logger.info(f"MFT database exists with {mft_count:,} records")
            except Exception as e:
                logger.warning(f"MFT database exists but couldn't check record count: {e}")
                mft_has_data = False
        else:
            logger.info("MFT database does not exist")
        
        # Check if USN database has data
        if usn_exists:
            try:
                conn = sqlite3.connect(self.usn_db)
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM journal_events")
                usn_count = cursor.fetchone()[0]
                conn.close()
                usn_has_data = (usn_count > 0)
                logger.info(f"USN database exists with {usn_count:,} records")
            except Exception as e:
                logger.warning(f"USN database exists but couldn't check record count: {e}")
                usn_has_data = False
        else:
            logger.info("USN database does not exist")
        
        # Step 1: Always run parsers to get fresh data (will append to existing database)
        # This ensures we capture new activity since last analysis
        logger.info("Running parsers to collect current data (will append to existing data)...")
        
        if not self.run_parsers(run_mft=True, run_usn=True):
            logger.error("Failed to run parsers")
            
            # Check if databases exist despite parser errors
            mft_exists_now = os.path.exists(self.mft_db)
            usn_exists_now = os.path.exists(self.usn_db)
            
            if mft_exists_now and usn_exists_now:
                logger.info("Databases exist, continuing with correlation")
            else:
                logger.error("Cannot proceed without both databases")
                return False
        
        # Steps 2-3: the join, the record names, the name columns.
        self.correlate_existing()
        
        # Step 4: Generate forensic report
        self.generate_forensic_report()
        
        logger.info("Correlation analysis completed successfully")
        return True
    
    def databases_have_data(self):
        """(MFT has records, USN has events) - without touching either parser."""
        def _rows(path, table):
            if not os.path.exists(path):
                return False
            try:
                conn = sqlite3.connect(path)
                try:
                    return conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None
                finally:
                    conn.close()
            except sqlite3.Error:
                return False
        return _rows(self.mft_db, "mft_records"), _rows(self.usn_db, "journal_events")

    def correlate_existing(self):
        """Correlate the MFT and USN databases ALREADY parsed - never a parser.

        run_complete_analysis() first re-parses the live MFT and USN of the
        machine it runs on, which is right for the live "correlate" action
        and wrong for every other caller: the live Parse All has just parsed
        them, and an offline or image case must never take in the examiner's
        own disk. Live Parse All called create_correlated_database() alone,
        so neither it nor the offline wrapper filled the name columns.

        Returns create_correlated_database()'s result (False when the
        correlated database is locked).
        """
        result = self.create_correlated_database()
        if result is False and not os.path.exists(self.correlated_db):
            logger.warning("Correlated database creation failed.")
        # filename_changes used to live in mft_claw_analysis.db and hold a
        # record's other $FILE_NAME names; it is the rename log now, in the
        # correlated database. A stale copy left in the MFT database would
        # keep feeding the old meaning to anything that reads it.
        try:
            mft_conn = sqlite3.connect(self.mft_db)
            try:
                mft_conn.execute("DROP TABLE IF EXISTS filename_changes")
                mft_conn.commit()
            finally:
                mft_conn.close()
        except sqlite3.Error as e:
            logger.warning(f"Could not remove the old filename_changes table: {e}")
        return result

    def run_correlation_for_case(self):
        """
        Run complete correlation for a specific case directory.
        This is the main entry point for Crow Eye integration.
        
        Returns:
            bool: True if correlation completed successfully, False otherwise
        """
        logger.info(f"Running MFT-USN correlation for case directory: {self.case_directory}")
        
        try:
            # Run the complete analysis pipeline
            success = self.run_complete_analysis()
            
            if success:
                logger.info(f"MFT-USN correlation completed successfully for case: {self.case_directory}")
                logger.info(f"Databases created in: {self.case_directory}")
                return True
            else:
                logger.error(f"MFT-USN correlation failed for case: {self.case_directory}")
                return False
                
        except Exception as e:
            logger.error(f"Unexpected error during correlation for case {self.case_directory}: {e}")
            import traceback
            logger.error(f"Error details: {traceback.format_exc()}")
            return False
    
    def generate_forensic_report(self):
        """Generate a comprehensive forensic report"""
        logger.info("Generating forensic report...")
        
        try:
            conn = sqlite3.connect(self.correlated_db)
            cursor = conn.cursor()
            
            report_lines = []
            report_lines.append("=" * 80)
            report_lines.append("MFT-USN CORRELATION FORENSIC REPORT")
            report_lines.append("=" * 80)
            report_lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M:%S')}")
            report_lines.append("")
            
            # Add explanation for tilde (~) in paths
            report_lines.append("=== IMPORTANT NOTE ABOUT PATHS WITH TILDE (~) ===")
            report_lines.append("Paths containing a tilde character (~) represent Windows 8.3 short filename format.")
            report_lines.append("These are generated by Windows for backward compatibility with older applications.")
            report_lines.append("For example, 'PROGRA~1' is the short name for 'Program Files'.")
            report_lines.append("This is normal Windows behavior and not an indication of malicious activity.")
            report_lines.append("Long filenames with spaces are automatically assigned a short 8.3 name by Windows.")
            report_lines.append("")
            
            # Basic statistics
            cursor.execute("SELECT COUNT(*) FROM mft_usn_correlated")
            total_records = cursor.fetchone()[0]
            report_lines.append(f"Total Correlated Records: {total_records:,}")
            
            # Files, not rows: the table repeats a file once per journal event,
            # and a file is volume + record + sequence.
            # DISTINCT over the columns themselves (idx_corr_vol_rec covers
            # them), not over a string built per row: the concatenations cost
            # most of these counts.
            cursor.execute("SELECT COUNT(*) FROM (SELECT DISTINCT volume_letter, mft_record_number, "
                           "mft_sequence_number FROM mft_usn_correlated WHERE has_mft_record = 1)")
            unique_files = cursor.fetchone()[0]
            report_lines.append(f"Unique Files (in the MFT): {unique_files:,}")

            cursor.execute("SELECT COUNT(*) FROM (SELECT DISTINCT volume_letter, mft_record_number "
                           "FROM mft_usn_correlated WHERE has_mft_record = 1 AND is_deleted = 1)")
            deleted_files = cursor.fetchone()[0]
            report_lines.append(f"Deleted Files (entry not in use): {deleted_files:,}")

            cursor.execute("SELECT COUNT(*) FROM mft_usn_correlated WHERE has_mft_record = 0")
            j_events = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM (SELECT DISTINCT volume_letter, mft_record_number, "
                           "mft_sequence_number FROM mft_usn_correlated WHERE has_mft_record = 0)")
            j_files = cursor.fetchone()[0]
            report_lines.append(f"Journal-only Events (file not in the MFT read): {j_events:,} "
                                f"across {j_files:,} files")
            
            cursor.execute("""
            SELECT COUNT(*) FROM mft_usn_correlated 
            WHERE reconstructed_path LIKE '%[Unknown Parent%'
            """)
            unknown_parents = cursor.fetchone()[0]
            report_lines.append(f"Files with Unknown Parents: {unknown_parents:,}")
            
            report_lines.append("")
            # Journal events per file. It grouped every row by name + path, so
            # a file with no event counted as one "modification", two files
            # sharing a name and path were added together, and the grouping of
            # 3.5 M rows was a fifth of the whole report.
            report_lines.append("Top 10 Files by Journal Events:")
            cursor.execute("""
            SELECT MAX(fn_filename), MAX(reconstructed_path), COUNT(*) AS n
            FROM mft_usn_correlated
            WHERE has_usn_event = 1
            GROUP BY volume_letter, mft_record_number, mft_sequence_number
            ORDER BY n DESC
            LIMIT 10
            """)

            for row in cursor.fetchall():
                report_lines.append(f"  {row[0]} ({row[1]}): {row[2]:,} journal events")
            
            # Renames, from the journal (old name -> new name).
            try:
                cursor.execute("SELECT COUNT(*), SUM(is_move), MIN(rename_time), MAX(rename_time) "
                               "FROM filename_changes")
                n, moves, first, last = cursor.fetchone()
                report_lines.append("")
                report_lines.append(f"Renames Recorded in the Journal: {n or 0:,} "
                                    f"({moves or 0:,} moved to another folder)")
                if n:
                    report_lines.append(f"  First: {first}   Last: {last}")
                    report_lines.append("")
                    report_lines.append("Most Renamed Files:")
                    cursor.execute("""
                    SELECT volume_letter, mft_record_number, COUNT(*) AS n,
                           MAX(new_name) AS latest
                    FROM filename_changes
                    GROUP BY volume_letter, mft_record_number, mft_sequence_number
                    ORDER BY n DESC LIMIT 5
                    """)
                    for vol, rec, cnt, latest in cursor.fetchall():
                        report_lines.append(f"  {vol}: record {rec} ({latest}): {cnt} renames")
                    report_lines.append("")
                    report_lines.append("Renames by Month:")
                    cursor.execute("""
                    SELECT strftime('%Y-%m', rename_time) AS month, COUNT(*)
                    FROM filename_changes WHERE rename_time IS NOT NULL
                    GROUP BY month ORDER BY month DESC LIMIT 12
                    """)
                    for month, cnt in cursor.fetchall():
                        report_lines.append(f"  {month}: {cnt:,}")
            except sqlite3.Error as e:
                logger.warning(f"Could not include rename statistics: {e}")

            # A record with more than one name: hard links, or a POSIX name
            # beside a Win32 one. Not renames - the MFT keeps current names only.
            try:
                mft_conn = sqlite3.connect(self.mft_db)
                mft_cursor = mft_conn.cursor()
                mft_cursor.execute("""
                SELECT COUNT(*) FROM (
                    SELECT 1 FROM mft_file_names
                    WHERE file_name IS NOT NULL AND file_name != ''
                      AND CAST(namespace AS INTEGER) != 2
                    GROUP BY volume_letter, record_number
                    HAVING COUNT(DISTINCT file_name) > 1
                )
                """)
                report_lines.append("")
                report_lines.append(f"Records with More Than One Name (hard links): "
                                    f"{mft_cursor.fetchone()[0]:,}")
                mft_conn.close()
            except Exception as e:
                logger.warning(f"Could not include multiple-name statistics: {e}")
            
            # Write report to file
            # Beside the correlated database, in the case. A bare file name put
            # it in the working folder - beside Crow Eye.py, or on the examined
            # machine wherever Crow-Eye was started.
            report_filename = os.path.join(
                os.path.dirname(os.path.abspath(self.correlated_db)),
                "mft_usn_forensic_report.txt")
            with open(report_filename, 'w', encoding='utf-8') as f:
                f.write('\n'.join(report_lines))
            
            logger.info(f"Forensic report saved: {report_filename}")
            
        except Exception as e:
            logger.error(f"Error generating forensic report: {e}")
        finally:
            conn.close()

def main():
    """Main function"""
    # Start total script timer
    total_start_time = time.time()
    print(f"{COLOR_HEADER}Starting MFT-USN correlation script at {get_current_forensic_timestamp()}{COLOR_RESET}")
    print(f"{COLOR_HEADER}{'=' * 60}{COLOR_RESET}")
    
    # Check dependencies before starting
    if not check_dependencies():
        logger.error("Failed to install required dependencies. Please install them manually.")
        logger.error("Required: psutil")
        return 1
        
    correlator = MFTUSNCorrelator()
    
    try:
        success = correlator.run_complete_analysis()
        if success:
            logger.info("MFT-USN correlation completed successfully!")
            logger.info(f"Correlated database: {correlator.correlated_db}")
            logger.info("Check the forensic report for analysis results.")
        else:
            logger.error("MFT-USN correlation failed")
            return 1
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Unexpected error during correlation: {e}")
        logger.error(f"Error details: {error_details}")
        print(f"{COLOR_ERROR}Error: {e}{COLOR_RESET}")
        print(f"{COLOR_ERROR}Error details: {error_details}{COLOR_RESET}")
        return 1
    finally:
        # Calculate and display total script time
        total_elapsed = time.time() - total_start_time
        minutes, seconds = divmod(total_elapsed, 60)
        hours, minutes = divmod(minutes, 60)
        milliseconds = int((seconds - int(seconds)) * 1000)
        
        print(f"\n{COLOR_HEADER}{'=' * 60}{COLOR_RESET}")
        print(f"{COLOR_SUCCESS}[OK] Total script execution time: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}.{milliseconds:03d}{COLOR_RESET}")
        print(f"{COLOR_SUCCESS}[OK] Completed at {get_current_forensic_timestamp()}{COLOR_RESET}")
        print(f"{COLOR_HEADER}{'=' * 60}{COLOR_RESET}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
