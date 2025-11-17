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
from datetime import datetime

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
                subprocess.check_call([sys.executable, "-m", "pip", "install", module])
                print(f"{COLOR_SUCCESS}Successfully installed {module}{COLOR_RESET}")
            except Exception as e:
                print(f"{COLOR_ERROR}Failed to install {module}: {e}{COLOR_RESET}")
                return False
    return True

# Configure logging
# Create Target_Artifacts directory for logs
target_artifacts_dir = os.path.join(".", "Target_Artifacts")
os.makedirs(target_artifacts_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(target_artifacts_dir, "mft_usn_correlation.log"), mode='w'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class MFTUSNCorrelator:
    def __init__(self, case_directory=None):
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
        
    def run_parsers(self):
        """Always run both MFT and USN parsers and show their progress in terminal"""
        logger.info("Running MFT and USN parsers...")
        
        # Ensure dependencies are installed
        check_dependencies()
        
        # Run MFT parser with live terminal output
        logger.info("Running MFT parser...")
        try:
            if HAS_DIRECT_IMPORTS:
                # Save current directory and change to case directory for direct function call
                original_cwd = os.getcwd()
                try:
                    os.chdir(self.case_directory)
                    # Run MFT parser directly as a function
                    result = mft_claw_main()
                    if result == 0:
                        logger.info("MFT parser completed successfully")
                    else:
                        logger.warning("MFT parser may have had display issues but database might be created")
                finally:
                    os.chdir(original_cwd)
            else:
                # Fallback to subprocess execution
                env = os.environ.copy()
                env['PYTHONIOENCODING'] = 'utf-8'
                env["PYTHONUNBUFFERED"] = "1"  # Ensure output is not buffered
                
                mft_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MFT_Claw.py")
                result = subprocess.run([sys.executable, mft_script], 
                                      cwd=self.case_directory, env=env)
                
                if result.returncode == 0:
                    logger.info("MFT parser completed successfully")
                else:
                    logger.warning("MFT parser may have had display issues but database might be created")
            
            # Check if database was created despite any errors
            if not os.path.exists(self.mft_db):
                logger.error("MFT database was not created")
                return False
                
        except Exception as e:
            logger.error(f"Error running MFT parser: {e}")
            return False
        
        # Run USN parser with live terminal output
        logger.info("Running USN parser...")
        
        try:
            if HAS_DIRECT_IMPORTS:
                # Save current directory and change to case directory for direct function call
                original_cwd = os.getcwd()
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
            else:
                # Fallback to subprocess execution
                env = os.environ.copy()
                env['PYTHONIOENCODING'] = 'utf-8'
                env["PYTHONUNBUFFERED"] = "1"  # Ensure output is not buffered
                
                usn_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "USN_Claw.py")
                result = subprocess.run([sys.executable, usn_script], 
                                      cwd=self.case_directory, env=env)
                
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
        bar = '█' * filled_length + '░' * (bar_length - filled_length)
        
        # Format the progress display - simple version without ETA
        progress_text = f"\r{prefix}[{bar}] {int(percent*100):3d}% | {current}/{total} {suffix}"
        
        # Use print with flush=True for better display
        print(f"{COLOR_PROGRESS}{progress_text}{COLOR_RESET}", end='', flush=True)
        
        if current >= total:
            # Show completion message
            print(f"\r{COLOR_SUCCESS}{prefix}[{'█' * bar_length}] 100% | {total}/{total} | Correlation complete!{' '*30}{COLOR_RESET}")
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
    
    def create_correlated_database(self):
        """Create or update database with comprehensive correlated data"""
        logger.info("Processing correlated database...")

        # Check if correlated database already exists
        database_exists = os.path.exists(self.correlated_db)
        
        if database_exists:
            logger.info(f"Existing correlated database found: {self.correlated_db}")
            logger.info("Preserving existing forensic data - appending new correlation results")
            
            # Check if database is accessible for appending data
            try:
                test_conn = sqlite3.connect(self.correlated_db)
                test_conn.close()
                logger.info("Database is accessible for appending data")
                # Continue with existing database - we'll append data
            except sqlite3.Error as e:
                # Database is locked/in use by another process
                logger.warning(f"Correlated database is locked/in use: {e}")
                logger.warning("Cannot access database for appending. Using existing data.")
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
            -- MFT Core Information
            mft_record_number INTEGER,
            fn_filename TEXT,
            mft_sequence_number INTEGER,
            mft_flags TEXT,
            is_directory INTEGER,
            is_deleted INTEGER,

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

            -- Correlation & Analysis Fields
            has_mft_record INTEGER,
            has_usn_event INTEGER,
            correlation_confidence TEXT,
            
            -- Forensic Analysis Fields
            filename_change_timeline TEXT,
            namespace_evolution TEXT,
            
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            
            -- Unique constraint to prevent duplicate entries
            UNIQUE(mft_record_number, fn_filename, usn_event_id, usn_timestamp)
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
        usn_cursor = usn_conn.cursor()
        usn_data, usn_select_columns = self._get_usn_data(usn_cursor)
        print(f"{COLOR_INFO}Retrieved {len(usn_data)} USN journal events{COLOR_RESET}")
        
        # Correlate and insert data with column information
        self._correlate_and_insert(mft_data, usn_data, usn_select_columns, corr_cursor)
    
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
        
        # First, get the count to show progress
        cursor.execute("SELECT COUNT(DISTINCT mr.record_number) FROM mft_records mr JOIN mft_file_names mfn ON mr.record_number = mfn.record_number WHERE mfn.file_name IS NOT NULL")
        total_records = cursor.fetchone()[0]
        print(f"{COLOR_INFO}Found {total_records:,} MFT records to process{COLOR_RESET}")
        
        # Optimize the query - remove subqueries and use simpler joins for better performance
        print(f"{COLOR_INFO}Fetching MFT data...{COLOR_RESET}")
        
        # Start time for progress tracking
        start_time = time.time()
        
        # Fetch all necessary data in a single, optimized query
        print(f"{COLOR_INFO}Fetching and processing MFT data...{COLOR_RESET}")
        
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
            mfn.namespace
        FROM mft_records mr
        LEFT JOIN mft_file_names mfn ON mr.record_number = mfn.record_number
        LEFT JOIN mft_standard_info si ON mr.record_number = si.record_number
        WHERE mfn.file_name IS NOT NULL 
        AND mfn.file_name NOT LIKE ':$DATA' 
        AND mfn.file_name NOT LIKE ':%'
        ORDER BY mr.record_number, mfn.namespace DESC
        """
        
        cursor.execute(query)
        all_rows = cursor.fetchall()
        
        # Process records, selecting the best file name for each record number
        result = []
        processed_records = set()
        
        # Fetch data attributes counts and file names counts separately for efficiency
        data_attributes_counts = self._get_counts(cursor, "mft_data_attributes", "record_number")
        file_names_counts = self._get_counts(cursor, "mft_file_names", "record_number")

        for row in all_rows:
            record_number = row[0]
            if record_number not in processed_records:
                # Manually construct the row with the counts
                standard_info_present = 1 if row[7] is not None else 0 # si_created timestamp
                
                data_attributes_count = data_attributes_counts.get(record_number, 0)
                file_names_count = file_names_counts.get(record_number, 0)

                # Assemble the final row, including the namespace (last element)
                final_row = row + (data_attributes_count, standard_info_present, file_names_count)
                result.append(final_row)
                processed_records.add(record_number)

        print(f"{COLOR_SUCCESS}\nSuccessfully processed {len(result):,} MFT records in {time.time() - start_time:.2f} seconds{COLOR_RESET}")
        return result
    
    def _get_counts(self, cursor, table_name, column_name):
        """
        Get counts of a given column from a table and return as a dictionary.
        """
        query = f"SELECT {column_name}, COUNT(*) FROM {table_name} GROUP BY {column_name}"
        cursor.execute(query)
        return dict(cursor.fetchall())

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
            "record_length"  # Record length (can be used as file_size proxy)
        ]
        
        query = f"SELECT {', '.join(select_columns)} FROM journal_events ORDER BY usn"
        
        cursor.execute(query)
        usn_data = cursor.fetchall()
        
        # Show progress
        total_usn = len(usn_data)
        bar_length = 30
        bar = '█' * bar_length
        print(f"\r[{bar}] {100:6.1f}% | {total_usn:,}/{total_usn:,} USN records", flush=True)
        
        print(f"\nSuccessfully fetched {len(usn_data):,} USN journal records")
        return usn_data, select_columns
    
    def _extract_mft_record_from_frn(self, frn_string):
        """
        Extract MFT record number from USN file reference number string.
        
        Windows file reference number format:
        - 64-bit value where lower 48 bits contain MFT record number
        - frn_string is the string representation of this 64-bit value
        
        Args:
            frn_string (str): String representation of file reference number
            
        Returns:
            int or None: MFT record number if extraction successful, None otherwise
        """
        try:
            # Convert string to integer
            frn_int = int(frn_string)
            # Extract lower 48 bits (MFT record number)
            mft_record = frn_int & 0xFFFFFFFFFFFF  # 48-bit mask (0xFFFFFFFFFFFF = 281474976710655)
            return mft_record
        except (ValueError, TypeError):
            # If conversion fails (invalid format or None), return None
            return None

    def flags_to_text(self, flags_val):
        """Convert MFT flags to a human-readable string."""
        if flags_val is None:
            return ""
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
        
        # Create mapping for quick lookup - optimize with dictionaries
        mft_by_record = {}
        for row in mft_data:
            record_num = row[0]
            if record_num not in mft_by_record:
                mft_by_record[record_num] = []
            mft_by_record[record_num].append(row)
        
        # Create USN lookup by MFT record number for faster correlation
        usn_by_mft_record = {}
        if usn_data:  # Only process if we have USN data
            # Find the correct index for file reference number in the select_columns
            ref_num_index = None
            for i, col_name in enumerate(usn_select_columns):
                # Look for frn (File Reference Number) or file_reference variations
                if col_name.lower() in ['frn', 'file_reference_number', 'file_reference']:
                    ref_num_index = i
                    break
            
            if ref_num_index is None:
                print(f"{COLOR_WARNING}WARNING: No file_reference column found in USN data - correlation may fail{COLOR_RESET}")
            else:
                for usn_row in usn_data:
                    try:
                        ref_num = usn_row[ref_num_index]  # file_reference field
                        if ref_num:
                            # Extract MFT record number from file reference
                            mft_record = self._extract_mft_record_from_frn(ref_num)
                            if mft_record and mft_record not in usn_by_mft_record:
                                usn_by_mft_record[mft_record] = []
                            if mft_record:
                                usn_by_mft_record[mft_record].append(usn_row)
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
        path_cache = {}
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
            data_attributes_count = mft_record_data[21]
            standard_info_present = mft_record_data[22]
            file_names_count = mft_record_data[23]

            # Reconstruct path using parent-child relationships
            reconstructed_path = self._reconstruct_path(record_num, mft_by_record, path_cache)
            
            # Convert file attributes to text for better readability
            flags_text = self.flags_to_text(flags)
            si_file_attributes_text = file_attributes_to_text(si_file_attributes)
            fn_file_flags_text = file_attributes_to_text(fn_file_flags)
            
            # Check if this record has matching USN entries
            usn_event_id = None
            usn_value = None
            usn_reason = None
            usn_timestamp = None
            usn_volume_letter = None
            usn_file_attributes_val = None
            usn_file_attributes_text = None
            has_usn_event = 0
            
            # Check if this MFT record has any corresponding USN events
            if record_num in usn_by_mft_record and usn_by_mft_record[record_num]:
                # Use the most recent USN event for this file (last in list)
                usn_event = usn_by_mft_record[record_num][-1]
                usn_event_id = usn_event[usn_select_columns.index('usn')]
                usn_value = usn_event[usn_select_columns.index('usn')]
                usn_reason = usn_reason_to_text(usn_event[usn_select_columns.index('reason')])
                usn_timestamp = usn_event[usn_select_columns.index('timestamp')]
                usn_volume_letter = usn_event[usn_select_columns.index('source_info')]
                
                # Extract USN file attributes if available
                try:
                    usn_file_attributes_val = usn_event[usn_select_columns.index('file_attributes')]
                    if usn_file_attributes_val is not None:
                        usn_file_attributes_text = file_attributes_to_text(usn_file_attributes_val)
                except (IndexError, ValueError):
                    # File attributes column might not exist or be invalid
                    usn_file_attributes_text = None
                
                has_usn_event = 1
                matched_with_usn += 1
            
            # Add to batch with all the glorious data
            insert_batch.append((
                record_num,
                fn_filename,
                reconstructed_path,
                sequence_number,
                flags_text,
                is_directory,
                is_deleted,
                si_created,
                si_modified,
                si_mft_modified,
                si_accessed,
                si_file_attributes_text,
                parent_record,
                parent_sequence,  # fn_parent_sequence_number - now available from MFT data
                fn_created,
                fn_modified,
                fn_mft_modified,
                fn_accessed,
                fn_allocated_size,
                fn_real_size,
                fn_file_flags_text,
                namespace,  # fn_namespace - now available from MFT data
                usn_event_id,
                usn_timestamp,
                usn_reason,
                usn_volume_letter,
                usn_file_attributes_text,  # usn_file_attributes - now extracted from USN data
                1,  # has_mft_record
                has_usn_event,
                'HIGH' if has_usn_event else 'MEDIUM',
                
                # Forensic Analysis Fields - will be populated after correlation
                None,  # filename_change_timeline (placeholder)
                None  # namespace_evolution (placeholder)
            ))

            # Execute batch insert when batch is full
            if len(insert_batch) >= batch_size:
                corr_cursor.executemany("""
                INSERT OR IGNORE INTO mft_usn_correlated (
                    mft_record_number, fn_filename, reconstructed_path,
                    mft_sequence_number, mft_flags, is_directory, is_deleted,
                    si_creation_time, si_modification_time, si_mft_entry_change_time, si_access_time, si_file_attributes,
                    fn_parent_record_number, fn_parent_sequence_number,
                    fn_creation_time, fn_modification_time, fn_mft_entry_change_time, fn_access_time,
                    fn_allocated_size, fn_real_size, fn_file_attributes, fn_namespace,
                    usn_event_id, usn_timestamp, usn_reason, usn_source_info, usn_file_attributes,
                    has_mft_record, has_usn_event, correlation_confidence,
                    filename_change_timeline, namespace_evolution
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, insert_batch)
                inserted_count += len(insert_batch)
                insert_batch = []

                # Show progress with detailed statistics - use time-based updates to prevent freezing
                current_time = time.time()
                if current_time - last_update_time >= 1.0 or inserted_count == total_records:  # Update less frequently (1.0s)
                    elapsed = current_time - start_time
                    percent = min(float(inserted_count) / total_records, 1.0) * 100
                    records_per_sec = inserted_count / elapsed if elapsed > 0 else 0
                    
                    # Create a more visible progress bar
                    bar_length = 40
                    filled_length = int(bar_length * inserted_count // total_records)
                    bar = '█' * filled_length + '▒' * (bar_length - filled_length)
                    
                    # Format the progress information with processing speed
                    stats = f"{percent:6.1f}% | {inserted_count:,}/{total_records:,} records | {records_per_sec:.1f} rec/s"
                    
                    # Clear the line and show progress bar only once (not on every line)
                    if inserted_count == batch_size:  # First update
                        print(f"\n{COLOR_PROGRESS}Correlation Progress:{COLOR_RESET}")
                        print(f"{COLOR_PROGRESS}[{bar}] {stats}{COLOR_RESET}", end="", flush=True)
                    else:
                        print(f"\r{COLOR_PROGRESS}[{bar}] {stats}{COLOR_RESET}", end="", flush=True)
                    
                    last_update_time = current_time
        
        # Insert any remaining records
        if insert_batch:
            corr_cursor.executemany("""
            INSERT OR IGNORE INTO mft_usn_correlated (
                mft_record_number, fn_filename, reconstructed_path,
                mft_sequence_number, mft_flags, is_directory, is_deleted,
                si_creation_time, si_modification_time, si_mft_entry_change_time, si_access_time, si_file_attributes,
                fn_parent_record_number, fn_parent_sequence_number,
                fn_creation_time, fn_modification_time, fn_mft_entry_change_time, fn_access_time,
                fn_allocated_size, fn_real_size, fn_file_attributes, fn_namespace,
                usn_event_id, usn_timestamp, usn_reason, usn_source_info, usn_file_attributes,
                has_mft_record, has_usn_event, correlation_confidence,
                filename_change_timeline, namespace_evolution
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, insert_batch)
            inserted_count += len(insert_batch)
        
        # Final statistics
        elapsed = time.time() - start_time
        records_per_sec = inserted_count / elapsed if elapsed > 0 else 0
        usn_match_percent = (matched_with_usn / inserted_count * 100) if inserted_count > 0 else 0
        
        # Print a new line to ensure the progress bar is complete
        print("\n")
        print(f"{COLOR_HEADER}{'=' * 60}{COLOR_RESET}")
        print(f"{COLOR_SUCCESS}✓ Correlation complete in {elapsed:.2f} seconds!{COLOR_RESET}")
        print(f"{COLOR_SUCCESS}✓ Total records processed: {inserted_count:,} ({records_per_sec:.1f} records/second){COLOR_RESET}")
        print(f"{COLOR_SUCCESS}✓ Records with USN matches: {matched_with_usn:,} ({usn_match_percent:.1f}%){COLOR_RESET}")
        print(f"{COLOR_HEADER}{'=' * 60}{COLOR_RESET}")
        
        logger.info(f"Total {inserted_count} correlated records inserted in {elapsed:.2f} seconds")

    def _update_forensic_analysis_fields(self, cursor):
        """
        Update forensic analysis fields in the correlated database.
        This populates the filename change tracking and multiple filename analysis columns
        using data from the MFT database's filename_changes table.
        """
        logger.info("Updating forensic analysis fields for filename change tracking...")
        
        # Connect to MFT database to get filename change data
        try:
            # Attach MFT database to the current connection for cross-database queries
            cursor.execute(f"ATTACH DATABASE '{self.mft_db}' AS mft_db")
            
            # Check if filename_changes table exists in MFT database
            cursor.execute("""
            SELECT name FROM mft_db.sqlite_master 
            WHERE type='table' AND name='filename_changes'
            """)
            
            if not cursor.fetchone():
                logger.warning("filename_changes table not found in MFT database - skipping forensic analysis updates")
                cursor.execute("DETACH DATABASE mft_db")
                return
            

            
            logger.info("Processing 135,000+ filename changes - using batched approach for performance...")
            
            # Get distinct record numbers with filename changes in batches
            batch_size = 1000
            offset = 0
            total_updated = 0
            
            while True:
                # Get batch of record numbers with filename changes
                cursor.execute(f"""
                SELECT DISTINCT record_number 
                FROM mft_db.filename_changes 
                ORDER BY record_number 
                LIMIT {batch_size} OFFSET {offset}
                """)
                
                record_batch = [row[0] for row in cursor.fetchall()]
                if not record_batch:
                    break
                
                # Create placeholders for IN clause
                placeholders = ','.join('?' for _ in record_batch)
                
                # Update filename_change_timeline for this batch
                cursor.execute(f"""
                WITH change_timeline AS (
                    SELECT 
                        record_number,
                        GROUP_CONCAT(
                            old_filename || ' -> ' || new_filename || ' (' || change_timestamp || ')',
                            ' | '
                        ) as timeline
                    FROM mft_db.filename_changes
                    WHERE record_number IN ({placeholders})
                    GROUP BY record_number
                )
                UPDATE mft_usn_correlated
                SET filename_change_timeline = (
                    SELECT timeline
                    FROM change_timeline ct
                    WHERE ct.record_number = mft_usn_correlated.mft_record_number
                )
                WHERE mft_record_number IN ({placeholders})
                """, record_batch + record_batch)
                
                # Update namespace_evolution for this batch
                cursor.execute(f"""
                WITH namespace_evolution AS (
                    SELECT 
                        record_number,
                        GROUP_CONCAT(
                            CASE 
                                WHEN namespace = 0 THEN 'POSIX'
                                WHEN namespace = 1 THEN 'Win32'
                                WHEN namespace = 2 THEN 'DOS'
                                WHEN namespace = 3 THEN 'Win32 & DOS'
                                ELSE 'Unknown'
                            END,
                            ' -> '
                        ) as evolution
                    FROM mft_db.filename_changes
                    WHERE record_number IN ({placeholders})
                    GROUP BY record_number
                )
                UPDATE mft_usn_correlated
                SET namespace_evolution = (
                    SELECT evolution
                    FROM namespace_evolution ne
                    WHERE ne.record_number = mft_usn_correlated.mft_record_number
                )
                WHERE mft_record_number IN ({placeholders})
                """, record_batch + record_batch)
                
                total_updated += len(record_batch)
                offset += batch_size
                

            
            logger.info(f"Completed forensic analysis updates for {total_updated:,} records")
            
            # Detach the MFT database
            cursor.execute("DETACH DATABASE mft_db")
            logger.info("Forensic analysis fields updated successfully using MFT filename changes data")
            
        except Exception as e:
            logger.error(f"Error updating forensic analysis fields: {e}")
            try:
                cursor.execute("DETACH DATABASE mft_db")
            except:
                pass

    def _reconstruct_path(self, record_num, mft_by_record, path_cache):
        """
        Iteratively reconstruct file path using a cache to avoid re-computation.
        """
        if record_num in path_cache:
            return path_cache[record_num]

        path_parts = []
        current_record = record_num
        visited = set()

        while current_record is not None and current_record != 0 and current_record not in visited:
            visited.add(current_record)
            if current_record in mft_by_record:
                record_data = mft_by_record[current_record][0]
                filename = record_data[5]
                parent_record = record_data[6]

                if filename:
                    path_parts.append(filename)
                
                if parent_record == current_record or parent_record is None or parent_record == 0:
                    break

                current_record = parent_record
            else:
                # Try to find the parent record in the MFT data to provide more context
                parent_info = ""
                if parent_record in mft_by_record:
                    parent_data = mft_by_record[parent_record][0]
                    parent_filename = parent_data[5]
                    parent_info = f" (Filename: {parent_filename})"
                
                path_parts.append(f"[Unknown Parent: {current_record}{parent_info}]")
                break
        
        # Handle root directory case
        if not path_parts:
            if record_num == 5:  # MFT record 5 is usually the root directory
                reconstructed_path = "./"
            else:
                reconstructed_path = "[Unknown]"
        else:
            reconstructed_path = "/".join(reversed(path_parts))

        path_cache[record_num] = reconstructed_path
        return reconstructed_path
    
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
            "CREATE INDEX IF NOT EXISTS idx_corr_timestamps ON mft_usn_correlated(si_creation_time, si_modification_time, usn_timestamp)"
        ]
        
        for index_sql in indexes:
            cursor.execute(index_sql)
    
    def track_filename_changes(self, mft_conn):
        """
        Track file name changes by analyzing the mft_file_names table.
        
        This method identifies records with multiple file names and creates
        a timeline of name changes for forensic analysis.
        
        Args:
            mft_conn: SQLite connection to the MFT database
            
        Returns:
            int: Number of filename changes tracked
        """
        cursor = mft_conn.cursor()
        
        # Create filename_changes table if it doesn't exist
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS filename_changes (
            record_number INTEGER,
            old_filename TEXT,
            volume_letter TEXT,
            new_filename TEXT,
            change_timestamp TEXT,
            namespace TEXT,
            UNIQUE(record_number, volume_letter, old_filename, new_filename)
        )
        """)
        
        # Use a more efficient SQL approach to find filename changes
        # This avoids the N+1 query problem by processing all changes in a single query
        logger.info("Tracking file name changes using optimized SQL approach...")
        
        # First, get a count of records with multiple names for logging
        cursor.execute("""
        SELECT COUNT(*) 
        FROM (
            SELECT record_number, volume_letter
            FROM mft_file_names 
            GROUP BY record_number, volume_letter 
            HAVING COUNT(*) > 1
        )
        """)
        
        multi_name_count = cursor.fetchone()[0]
        logger.info(f"Found {multi_name_count} records with multiple file names")
        
        # Use window functions to efficiently find consecutive filename changes
        # First count the changes to get an accurate count
        cursor.execute("""
        WITH OrderedFileNames AS (
            SELECT 
                record_number,
                volume_letter,
                file_name,
                namespace,
                modified,
                LAG(file_name) OVER (PARTITION BY record_number, volume_letter ORDER BY modified) as prev_file_name
            FROM mft_file_names
        )
        SELECT COUNT(*)
        FROM OrderedFileNames
        WHERE prev_file_name IS NOT NULL 
          AND prev_file_name != file_name
        """)
        
        changes_count = cursor.fetchone()[0]
        
        # Now perform the actual insertion
        if changes_count > 0:
            cursor.execute("""
            WITH OrderedFileNames AS (
                SELECT 
                    record_number,
                    volume_letter,
                    file_name,
                    namespace,
                    modified,
                    LAG(file_name) OVER (PARTITION BY record_number, volume_letter ORDER BY modified) as prev_file_name,
                    LAG(namespace) OVER (PARTITION BY record_number, volume_letter ORDER BY modified) as prev_namespace
                FROM mft_file_names
            )
            INSERT OR IGNORE INTO filename_changes 
            (record_number, old_filename, volume_letter, new_filename, change_timestamp, namespace)
            SELECT 
                record_number,
                prev_file_name,
                volume_letter,
                file_name,
                modified,  -- Use current file's timestamp as change time
                namespace
            FROM OrderedFileNames
            WHERE prev_file_name IS NOT NULL 
              AND prev_file_name != file_name
            """)
        
        mft_conn.commit()
        
        logger.info(f"Tracked {changes_count} file name changes using optimized query")
        
        return changes_count
    
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
        
        # Check if databases exist
        mft_exists = os.path.exists(self.mft_db)
        usn_exists = os.path.exists(self.usn_db)
        
        logger.info(f"MFT database exists: {mft_exists}")
        logger.info(f"USN database exists: {usn_exists}")
        
        # Step 1: Run parsers if databases don't exist
        if not mft_exists or not usn_exists:
            logger.info("Source databases not found, running parsers...")
            if not self.run_parsers():
                logger.error("Failed to run parsers")
                
                # Check if databases were created despite errors
                mft_exists_now = os.path.exists(self.mft_db)
                usn_exists_now = os.path.exists(self.usn_db)
                
                if mft_exists_now and usn_exists_now:
                    logger.info("Databases were created successfully, continuing with correlation")
                else:
                    logger.error("Cannot proceed without both databases")
                    return False
        
        # Step 2: Create correlated database
        correlation_success = self.create_correlated_database()
        if not correlation_success:
            # Only warn if the database wasn't created and we're not just using an existing one
            if not os.path.exists(self.correlated_db):
                logger.warning("Correlated database creation failed. Using existing database if available.")
            else:
                logger.info("Using existing correlated database")
            
        # Step 3: Track filename changes from MFT database
        try:
            mft_conn = sqlite3.connect(self.mft_db)
            filename_changes_count = self.track_filename_changes(mft_conn)
            logger.info(f"Tracked {filename_changes_count} file name changes")
            
            # Step 3.5: Update forensic analysis fields now that filename_changes table exists
            corr_conn = sqlite3.connect(self.correlated_db)
            corr_cursor = corr_conn.cursor()
            self._update_forensic_analysis_fields(corr_cursor)
            corr_conn.close()
            
            mft_conn.close()
        except Exception as e:
            logger.error(f"Error tracking filename changes: {e}")
        
        # Step 4: Generate forensic report
        self.generate_forensic_report()
        
        logger.info("Correlation analysis completed successfully")
        return True
    
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
            report_lines.append(f"Generated: {datetime.now().isoformat()}")
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
            
            cursor.execute("SELECT COUNT(DISTINCT mft_record_number) FROM mft_usn_correlated")
            unique_files = cursor.fetchone()[0]
            report_lines.append(f"Unique Files: {unique_files:,}")
            
            cursor.execute("SELECT COUNT(*) FROM mft_usn_correlated WHERE is_deleted = 1")
            deleted_files = cursor.fetchone()[0]
            report_lines.append(f"Deleted Files: {deleted_files:,}")
            
            cursor.execute("""
            SELECT COUNT(*) FROM mft_usn_correlated 
            WHERE reconstructed_path LIKE '%[Unknown Parent%'
            """)
            unknown_parents = cursor.fetchone()[0]
            report_lines.append(f"Files with Unknown Parents: {unknown_parents:,}")
            
            report_lines.append("")
            report_lines.append("Top 10 Most Modified Files:")
            cursor.execute("""
            SELECT fn_filename, reconstructed_path, COUNT(*) as modification_count
            FROM mft_usn_correlated 
            WHERE fn_filename IS NOT NULL 
            GROUP BY fn_filename, reconstructed_path 
            ORDER BY modification_count DESC 
            LIMIT 10
            """)
            
            for row in cursor.fetchall():
                report_lines.append(f"  {row[0]} ({row[1]}): {row[2]} modifications")
            
            # Add filename change statistics if available
            try:
                mft_conn = sqlite3.connect(self.mft_db)
                mft_cursor = mft_conn.cursor()
                
                # Check if filename_changes table exists
                mft_cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='filename_changes'
                """)
                
                if mft_cursor.fetchone():
                    mft_cursor.execute("SELECT COUNT(*) FROM filename_changes")
                    filename_changes_count = mft_cursor.fetchone()[0]
                    report_lines.append("")
                    report_lines.append(f"File Name Changes Tracked: {filename_changes_count:,}")
                    
                    # Show top 5 most renamed files
                    mft_cursor.execute("""
                    SELECT record_number, COUNT(*) as rename_count
                    FROM filename_changes 
                    GROUP BY record_number 
                    ORDER BY rename_count DESC 
                    LIMIT 5
                    """)
                    
                    top_renamed = mft_cursor.fetchall()
                    if top_renamed:
                        report_lines.append("")
                        report_lines.append("Top 5 Most Renamed Files:")
                        for record_num, rename_count in top_renamed:
                            report_lines.append(f"  MFT Record {record_num}: {rename_count} name changes")
                    
                    # Add detailed multiple filenames analysis
                    report_lines.append("")
                    report_lines.append("=== MULTIPLE FILENAMES ANALYSIS ===")
                    
                    # Count records with multiple filenames
                    mft_cursor.execute("""
                    SELECT COUNT(*) 
                    FROM (
                        SELECT record_number, COUNT(DISTINCT file_name) as name_count
                        FROM mft_file_names 
                        WHERE file_name IS NOT NULL AND file_name != ''
                        GROUP BY record_number
                        HAVING COUNT(DISTINCT file_name) > 1
                    )
                    """)
                    multi_name_records = mft_cursor.fetchone()[0]
                    report_lines.append(f"Records with Multiple Filenames: {multi_name_records:,}")
                    
                    # Show files with most name variations
                    mft_cursor.execute("""
                    SELECT record_number, COUNT(DISTINCT file_name) as name_count
                    FROM mft_file_names 
                    WHERE file_name IS NOT NULL AND file_name != ''
                    GROUP BY record_number
                    HAVING COUNT(DISTINCT file_name) > 1
                    ORDER BY name_count DESC
                    LIMIT 10
                    """)
                    top_multi_name = mft_cursor.fetchall()
                    if top_multi_name:
                        report_lines.append("")
                        report_lines.append("Files with Most Name Variations:")
                        for record_num, name_count in top_multi_name:
                            report_lines.append(f"  MFT Record {record_num}: {name_count} different names")
                    
                    # Add namespace distribution analysis
                    report_lines.append("")
                    report_lines.append("Namespace Distribution in Multiple Filenames:")
                    mft_cursor.execute("""
                    SELECT namespace, COUNT(*) as count
                    FROM mft_file_names 
                    WHERE record_number IN (
                        SELECT record_number
                        FROM mft_file_names 
                        WHERE file_name IS NOT NULL AND file_name != ''
                        GROUP BY record_number
                        HAVING COUNT(DISTINCT file_name) > 1
                    )
                    GROUP BY namespace
                    ORDER BY count DESC
                    """)
                    namespace_dist = mft_cursor.fetchall()
                    for namespace_val, count in namespace_dist:
                        namespace_name = self._get_namespace_name(namespace_val)
                        report_lines.append(f"  {namespace_name}: {count:,} entries")
                    
                    # Add timeline analysis of name changes
                    report_lines.append("")
                    report_lines.append("=== TIMELINE ANALYSIS ===")
                    
                    # Get earliest and latest name change timestamps
                    mft_cursor.execute("""
                    SELECT 
                        MIN(change_timestamp) as earliest_change,
                        MAX(change_timestamp) as latest_change,
                        COUNT(*) as total_changes
                    FROM filename_changes
                    WHERE change_timestamp IS NOT NULL 
                    AND change_timestamp != ''
                    """)
                    timeline_stats = mft_cursor.fetchone()
                    if timeline_stats and timeline_stats[0]:
                        earliest, latest, total = timeline_stats
                        report_lines.append(f"Earliest Name Change: {earliest}")
                        report_lines.append(f"Latest Name Change: {latest}")
                        report_lines.append(f"Total Name Changes in Timeline: {total:,}")
                        
                        # Analyze name changes by time period
                        mft_cursor.execute("""
                        SELECT 
                            strftime('%Y-%m', change_timestamp) as month,
                            COUNT(*) as change_count
                        FROM filename_changes
                        WHERE change_timestamp IS NOT NULL 
                        AND change_timestamp != ''
                        GROUP BY strftime('%Y-%m', change_timestamp)
                        ORDER BY month DESC
                        LIMIT 12
                        """)
                        monthly_changes = mft_cursor.fetchall()
                        if monthly_changes:
                            report_lines.append("")
                            report_lines.append("Name Changes by Month (Last 12 months):")
                            for month, count in monthly_changes:
                                report_lines.append(f"  {month}: {count:,} changes")
                
                mft_conn.close()
            except Exception as e:
                logger.warning(f"Could not include filename change statistics: {e}")
            
            # Write report to file
            report_filename = "mft_usn_forensic_report.txt"
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
    print(f"{COLOR_HEADER}Starting MFT-USN correlation script at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{COLOR_RESET}")
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
        print(f"{COLOR_SUCCESS}✓ Total script execution time: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}.{milliseconds:03d}{COLOR_RESET}")
        print(f"{COLOR_SUCCESS}✓ Completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{COLOR_RESET}")
        print(f"{COLOR_HEADER}{'=' * 60}{COLOR_RESET}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
