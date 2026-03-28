"""
Offline USN Journal Parser Wrapper for Crow-eye
===============================================

This module provides a dedicated offline wrapper for the USN Journal parser,
allowing for the analysis of collected $UsnJrnl files from a case directory.
"""

import os
import sys
import logging
import struct
import datetime
import sqlite3

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Add USN parser directory to path
usn_dir = os.path.join(parent_dir, 'MFT and USN journal')
if usn_dir not in sys.path:
    sys.path.insert(0, usn_dir)

# Import reusable functions and structures from live parser
try:
    from USN_Claw import (
        # Core parsing
        parse_record,
        
        # Conversion utilities
        filetime_to_datetime,
        file_id_128_to_str,
        reason_to_text,
        sourceinfo_to_text,
        file_attributes_to_text,
        
        # Forensic filtering
        should_exclude_from_analysis,
        
        # Database
        init_db,
        DatabaseTransaction,
        
        # Memory management
        get_memory_usage,
        check_memory_usage,
        cleanup_memory,
        
        # Constants
        BUFFER_SIZE,
        BATCH_SIZE,
        
        # Structures
        USN_RECORD_V2,
        USN_RECORD_V3,
        FILE_ID_128,
    )
    _HAS_USN_CLAW = True
except ImportError as e:
    print(f"Warning: Could not import from USN_Claw: {e}")
    _HAS_USN_CLAW = False
    BUFFER_SIZE = 65536
    BATCH_SIZE = 500

# Try to import tqdm for progress bar
try:
    from tqdm import tqdm
    _HAS_TQDM = True
except ImportError:
    _HAS_TQDM = False
    print("Warning: tqdm not available - progress bar disabled")


def read_journal_file(file_path, cursor, conn, volume_letter="OFFLINE"):
    """
    Read and parse a USN journal file from disk.
    
    Args:
        file_path (str): Path to the $UsnJrnl file
        cursor: SQLite cursor for database operations
        conn: SQLite connection for commits
        volume_letter (str): Volume identifier for database records (default: "OFFLINE")
    
    Returns:
        int: Number of records successfully parsed
    
    Raises:
        FileNotFoundError: If file_path does not exist
        PermissionError: If file cannot be read
        ValueError: If file is empty or invalid
    """
    if not _HAS_USN_CLAW:
        raise ImportError("USN_Claw functions not available - cannot parse USN journal")
    
    # Validate file exists
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"USN file not found: {file_path}")
    
    # Validate file is not empty
    file_size = os.path.getsize(file_path)
    if file_size == 0:
        raise ValueError(f"USN file is empty (0 bytes): {file_path}")
    
    # Validate file is readable
    try:
        with open(file_path, 'rb') as test_file:
            test_file.read(1)
    except PermissionError:
        raise PermissionError(f"Permission denied reading USN file: {file_path}")
    
    print(f"[Offline USN] Parsing USN journal file: {file_path}")
    print(f"[Offline USN] File size: {file_size:,} bytes ({file_size / (1024*1024):.2f} MB)")
    
    record_count = 0
    excluded_count = 0
    failed_count = 0
    batch_records = []
    leftover_bytes = b""
    
    # Initialize progress bar if available
    if _HAS_TQDM:
        pbar = tqdm(total=file_size, unit='B', unit_scale=True, unit_divisor=1024,
                   desc="Parsing USN", bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{percentage:3.0f}%]")
    else:
        pbar = None
    
    try:
        with open(file_path, 'rb') as usn_file:
            bytes_processed = 0
            
            while True:
                # Read chunk
                chunk = usn_file.read(BUFFER_SIZE)
                if not chunk:
                    break
                
                # Prepend leftover from previous chunk
                data = leftover_bytes + chunk
                bytes_processed += len(chunk)
                
                # Update progress bar
                if pbar:
                    pbar.update(len(chunk))
                
                # Parse records from data
                offset = 0
                while offset + 8 <= len(data):
                    try:
                        # Read record length
                        rec_len = struct.unpack_from("<I", data, offset)[0]
                        
                        # Check if we have complete record
                        if rec_len <= 0 or offset + rec_len > len(data):
                            # Incomplete record - save for next iteration
                            leftover_bytes = data[offset:]
                            break
                        
                        # Parse the record using reusable function
                        rec = parse_record(data, offset)
                        
                        if rec:
                            # Apply forensic filtering
                            if should_exclude_from_analysis(rec["filename"]):
                                excluded_count += 1
                                offset += rec_len
                                continue
                            
                            # Add to batch
                            record_count += 1
                            inserted_at = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
                            
                            batch_records.append((
                                volume_letter,
                                rec["filename"],
                                rec["usn"],
                                rec["major_version"],
                                rec["frn"],
                                rec["parent_frn"],
                                rec["timestamp"],
                                rec["reason"],
                                rec["source_info"],
                                rec["security_id"],
                                rec["file_attributes"],
                                rec["record_length"],
                                inserted_at
                            ))
                            
                            # Batch commit when batch size reached
                            if len(batch_records) >= BATCH_SIZE:
                                try:
                                    with DatabaseTransaction(conn) as transaction:
                                        cursor.executemany(
                                            "INSERT OR IGNORE INTO journal_events "
                                            "(volume_letter, filename, usn, major_version, frn, parent_frn, "
                                            "timestamp, reason, source_info, security_id, file_attributes, "
                                            "record_length, inserted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                            batch_records
                                        )
                                    batch_records.clear()
                                    
                                    # Memory cleanup if needed
                                    if check_memory_usage(1024):
                                        cleanup_memory()
                                        
                                except Exception as e:
                                    print(f"[Offline USN] Database write error: {e}")
                                    batch_records.clear()
                        else:
                            # Parse failed
                            failed_count += 1
                        
                        offset += rec_len
                        
                    except Exception as e:
                        # Log error and try to continue
                        print(f"[Offline USN] Parse error at offset {offset}: {e}")
                        failed_count += 1
                        offset += 8  # Skip ahead and try next potential record
                        if offset >= len(data):
                            break
                else:
                    # Processed all complete records in this chunk
                    leftover_bytes = b""
        
        # Final batch commit
        if batch_records:
            try:
                with DatabaseTransaction(conn) as transaction:
                    cursor.executemany(
                        "INSERT OR IGNORE INTO journal_events "
                        "(volume_letter, filename, usn, major_version, frn, parent_frn, "
                        "timestamp, reason, source_info, security_id, file_attributes, "
                        "record_length, inserted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        batch_records
                    )
                print(f"[Offline USN] Final batch: {len(batch_records)} records committed")
            except Exception as e:
                print(f"[Offline USN] Final batch write error: {e}")
        
        if pbar:
            pbar.close()
        
        print(f"[Offline USN] Parsing complete:")
        print(f"[Offline USN]   Records parsed: {record_count:,}")
        if excluded_count > 0:
            print(f"[Offline USN]   Records excluded: {excluded_count:,}")
        if failed_count > 0:
            print(f"[Offline USN]   Parse failures: {failed_count:,}")
        
        return record_count
        
    except Exception as e:
        if pbar:
            pbar.close()
        raise


def run_offline_usn(case_path, usn_file_path=None):
    """
    Run USN Journal analysis in offline mode.
    
    Args:
        case_path (str): Path to the case directory
        usn_file_path (str, optional): Explicit path to $UsnJrnl file to parse. If not provided,
                                       searches in case_path/live_acquisition/Target_Artifacts/usn/
    
    Returns:
        dict: Parser results including record counts and status
    """
    print(f"[Offline USN] Starting analysis for case: {case_path}")
    
    # First check if USN database already exists from live collection
    existing_db = os.path.join(case_path, 'Target_Artifacts', 'USN_journal.db')
    if os.path.exists(existing_db):
        print(f"[Offline USN] Found existing USN database: {existing_db}")
        
        # Count records in existing database
        try:
            import sqlite3
            conn = sqlite3.connect(existing_db)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM journal_events")
            count = cursor.fetchone()[0]
            conn.close()
            
            print(f"[Offline USN] Using existing database with {count:,} records")
            return {
                "success": True,
                "records": count,
                "output_path": existing_db
            }
        except Exception as e:
            print(f"[Offline USN] Error reading existing database: {e}")
    
    try:
        # Import USN parser functions (already imported at module level)
        if not _HAS_USN_CLAW:
            return {
                "success": False,
                "error": "USN_Claw functions not available - cannot parse USN journal",
                "records": 0
            }
        
        # Determine USN file path
        if not usn_file_path:
            # Search for $UsnJrnl file in standard locations (input from live_acquisition)
            possible_paths = [
                os.path.join(case_path, 'live_acquisition', 'usn_journal', '$UsnJrnl'),
                os.path.join(case_path, 'live_acquisition', 'MFT_USN', '$UsnJrnl'),
                os.path.join(case_path, 'live_acquisition', 'MFT_USN', '$J'),
                os.path.join(case_path, 'live_acquisition', 'USN_Journal', '$UsnJrnl'),
                os.path.join(case_path, 'live_acquisition', 'USN_Journal', '$J'),
                os.path.join(case_path, 'live_acquisition', '$UsnJrnl'),
                os.path.join(case_path, 'live_acquisition', '$J'),
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    usn_file_path = path
                    print(f"[Offline USN] Found USN file: {usn_file_path}")
                    break
            
            if not usn_file_path:
                print(f"[Offline USN] No $UsnJrnl file found in standard locations")
                return {
                    "success": False,
                    "error": "No $UsnJrnl file found. Expected locations: " + ", ".join(possible_paths),
                    "records": 0
                }
        
        # Verify USN file exists and is not empty
        if not os.path.exists(usn_file_path):
            return {
                "success": False,
                "error": f"USN file not found: {usn_file_path}",
                "records": 0
            }
        
        file_size = os.path.getsize(usn_file_path)
        if file_size == 0:
            print(f"[Offline USN] USN file is empty (0 bytes)")
            return {
                "success": False,
                "error": "USN file is empty (0 bytes). This may be expected for offline collections.",
                "records": 0
            }
        
        print(f"[Offline USN] Using USN file: {usn_file_path}")
        
        # Configure output directory - use Target_Artifacts for parsed databases (flat structure)
        output_dir = os.path.join(case_path, 'Target_Artifacts')
        os.makedirs(output_dir, exist_ok=True)
        
        # Initialize database
        db_path = os.path.join(output_dir, 'USN_journal.db')
        conn, cursor = init_db(db_path)
        
        print(f"[Offline USN] Parsing USN journal...")
        
        # Parse the USN journal file
        try:
            record_count = read_journal_file(usn_file_path, cursor, conn, volume_letter="OFFLINE")
            conn.close()
            
            print(f"[Offline USN] Successfully parsed {record_count:,} records")
            
            # After successful USN parsing, check if we should run correlation
            print(f"[Offline USN] Checking for MFT database to run correlation...")
            
            # Check for both possible MFT database names
            mft_db_names = ['mft_claw_analysis.db', 'MFT_data.db']
            mft_db_path = None
            
            for db_name in mft_db_names:
                test_path = os.path.join(output_dir, db_name)
                if os.path.exists(test_path):
                    mft_db_path = test_path
                    break
            
            if mft_db_path:
                print(f"[Offline USN] MFT database found - running correlation...")
                try:
                    # Import and run the offline correlator
                    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                    from offline_MFT_USN_Correlator import run_offline_correlation
                    
                    correlation_result = run_offline_correlation(case_path)
                    
                    if correlation_result["success"]:
                        print(f"[Offline USN] Correlation complete: {correlation_result['records']:,} correlated records")
                    else:
                        print(f"[Offline USN] Correlation skipped: {correlation_result.get('error', 'Unknown reason')}")
                        
                except Exception as e:
                    print(f"[Offline USN] Correlation failed: {e}")
                    # Don't fail the whole operation if correlation fails
            else:
                print(f"[Offline USN] MFT database not found - skipping correlation")
                print(f"[Offline USN] Run MFT parser first to enable correlation")
            
            return {
                "success": True,
                "records": record_count,
                "output_path": db_path
            }
        except Exception as e:
            conn.close()
            raise
        
    except ImportError as e:
        error_msg = f"Failed to import USN parser: {str(e)}"
        print(f"[Offline USN Error] {error_msg}")
        return {"success": False, "error": error_msg, "records": 0}
    except Exception as e:
        error_msg = f"USN parsing failed: {str(e)}"
        print(f"[Offline USN Error] {error_msg}")
        return {"success": False, "error": error_msg, "records": 0}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python offline_USNClaw.py <case_path> [usn_file_path]")
        sys.exit(1)
    
    path = sys.argv[1]
    usn_file = sys.argv[2] if len(sys.argv) > 2 else None
    run_offline_usn(path, usn_file)
