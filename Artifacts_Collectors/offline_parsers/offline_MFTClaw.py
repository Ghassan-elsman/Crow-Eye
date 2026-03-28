"""
Offline MFT Parser Wrapper for Crow-eye
========================================

This module provides a dedicated offline wrapper for the MFT (Master File Table) parser,
allowing for the analysis of collected $MFT files from a case directory.
"""

import os
import sys
import logging

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Add MFT parser directory to path
mft_dir = os.path.join(parent_dir, 'MFT and USN journal')
if mft_dir not in sys.path:
    sys.path.insert(0, mft_dir)

def run_offline_mft(case_path, mft_file_path=None, registry_hive_paths=None):
    """
    Run MFT analysis in offline mode.
    
    Args:
        case_path (str): Path to the case directory
        mft_file_path (str, optional): Explicit path to $MFT file to parse. If not provided,
                                       searches in case_path/live_acquisition/Target_Artifacts/mft/
        registry_hive_paths (dict, optional): DEPRECATED - Not used by this parser.
                                              Kept for backward compatibility only.
    
    Note:
        MFT parser operates on $MFT file and does not require registry context.
        The registry_hive_paths parameter is ignored.
        
    Returns:
        dict: Parser results including record counts and status
    """
    print(f"[Offline MFT] Starting analysis for case: {case_path}")
    
    try:
        # Import MFT parser components
        from MFT_Claw import MFTClawConfig, MFTParser, OutputFormat, LogLevel, DatabaseManager
        
        # Determine MFT file path
        if not mft_file_path:
            # Search for $MFT file in standard locations (input from live_acquisition)
            possible_paths = [
                os.path.join(case_path, 'live_acquisition', 'MFT_USN', '$MFT'),
                os.path.join(case_path, 'live_acquisition', 'MFT', '$MFT'),
                os.path.join(case_path, 'live_acquisition', '$MFT'),
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    mft_file_path = path
                    print(f"[Offline MFT] Found MFT file: {mft_file_path}")
                    break
            
            if not mft_file_path:
                print(f"[Offline MFT] No $MFT file found in standard locations")
                return {
                    "success": False,
                    "error": "No $MFT file found. Expected locations: " + ", ".join(possible_paths),
                    "records": 0
                }
        
        # Verify MFT file exists
        if not os.path.exists(mft_file_path):
            return {
                "success": False,
                "error": f"MFT file not found: {mft_file_path}",
                "records": 0
            }
        
        print(f"[Offline MFT] Using MFT file: {mft_file_path}")
        
        # Configure output directory - use Target_Artifacts for parsed databases (flat structure)
        output_dir = os.path.join(case_path, 'Target_Artifacts')
        os.makedirs(output_dir, exist_ok=True)
        output_db = os.path.join(output_dir, 'mft_claw_analysis.db')  # Use standard name for GUI compatibility
        
        # Check if database already exists with data BEFORE creating parser
        # This prevents DatabaseManager from recreating/wiping the database
        if os.path.exists(output_db):
            print(f"[Offline MFT] Found existing database: {output_db}")
            try:
                import sqlite3
                conn = sqlite3.connect(output_db)
                cursor = conn.cursor()
                
                # Check if mft_records table exists
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='mft_records'")
                if cursor.fetchone():
                    cursor.execute("SELECT COUNT(*) FROM mft_records")
                    count = cursor.fetchone()[0]
                    conn.close()
                    
                    if count > 0:
                        print(f"[Offline MFT] Using existing database with {count:,} records (skipping re-parse)")
                        return {
                            "success": True,
                            "records": count,
                            "output_path": output_db
                        }
                else:
                    conn.close()
                    print(f"[Offline MFT] Database exists but mft_records table not found, will recreate")
            except Exception as e:
                print(f"[Offline MFT] Existing database is invalid, will recreate: {e}")
        
        # If we get here, we need to parse the MFT file
        print(f"[Offline MFT] No valid existing database found, will parse MFT file")
        
        # Get file size to estimate record count
        file_size = os.path.getsize(mft_file_path)
        record_size = 1024  # Standard MFT record size
        estimated_records = file_size // record_size
        
        print(f"[Offline MFT] MFT file size: {file_size:,} bytes ({file_size / (1024*1024):.1f} MB)")
        print(f"[Offline MFT] Estimated records: {estimated_records:,}")
        print(f"[Offline MFT] WARNING: This will take several minutes to parse...")
        
        # Configure MFT parser for offline mode
        config = MFTClawConfig(
            output_format=OutputFormat.SQLITE,
            output_directory=output_dir,
            database_name='mft_claw_analysis.db',  # Use standard name for GUI compatibility
            batch_size=1000,
            log_level=LogLevel.INFO,
            log_file=os.path.join(output_dir, 'mft_claw.log'),
            enable_console_logging=True
        )
        
        # Create parser and database manager
        parser = MFTParser(config)
        
        # Read and parse MFT file directly
        print(f"[Offline MFT] Parsing MFT records...")
        records_parsed = 0
        batch_records = []
        
        with open(mft_file_path, 'rb') as mft_file:
            record_num = 0
            while True:
                raw_record = mft_file.read(record_size)
                if len(raw_record) < record_size:
                    break
                
                try:
                    # Parse the record using parser's internal method
                    mft_record = parser._parse_mft_record(record_num, 'OFFLINE', raw_record)
                    if mft_record:
                        batch_records.append(mft_record)
                        records_parsed += 1
                        
                        # Process batch when full
                        if len(batch_records) >= config.batch_size:
                            parser._process_record_batch(batch_records)
                            batch_records.clear()
                            parser.db_manager.commit()
                        
                        # Progress reporting - less frequent for better performance
                        if records_parsed % 10000 == 0:
                            progress = (records_parsed / estimated_records * 100) if estimated_records > 0 else 0
                            print(f"\r[Offline MFT] Parsed {records_parsed:,} / {estimated_records:,} records ({progress:.1f}%)", end='', flush=True)
                
                except Exception as e:
                    logging.debug(f"Error parsing record {record_num}: {e}")
                
                record_num += 1
        
        # Process remaining batch
        if batch_records:
            parser._process_record_batch(batch_records)
            parser.db_manager.commit()
        
        print(f"\n[Offline MFT] Successfully parsed {records_parsed:,} MFT records")
        
        # Cleanup
        parser.cleanup()
        
        # After successful MFT parsing, check if we should run correlation
        print(f"[Offline MFT] Checking for USN database to run correlation...")
        usn_db_path = os.path.join(output_dir, 'USN_journal.db')
        
        if os.path.exists(usn_db_path):
            print(f"[Offline MFT] USN database found - running correlation...")
            try:
                # Import and run the offline correlator
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                from offline_MFT_USN_Correlator import run_offline_correlation
                
                correlation_result = run_offline_correlation(case_path)
                
                if correlation_result["success"]:
                    print(f"[Offline MFT] Correlation complete: {correlation_result['records']:,} correlated records")
                else:
                    print(f"[Offline MFT] Correlation skipped: {correlation_result.get('error', 'Unknown reason')}")
                    
            except Exception as e:
                print(f"[Offline MFT] Correlation failed: {e}")
                # Don't fail the whole operation if correlation fails
        else:
            print(f"[Offline MFT] USN database not found - skipping correlation")
            print(f"[Offline MFT] Run USN parser to enable correlation")
        
        return {
            "success": True,
            "records": records_parsed,
            "output_path": output_db  # Return the actual database path created
        }
        
    except ImportError as e:
        error_msg = f"Failed to import MFT parser: {str(e)}"
        print(f"[Offline MFT Error] {error_msg}")
        return {"success": False, "error": error_msg, "records": 0}
    except Exception as e:
        error_msg = f"MFT parsing failed: {str(e)}"
        print(f"[Offline MFT Error] {error_msg}")
        return {"success": False, "error": error_msg, "records": 0}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python offline_MFTClaw.py <case_path> [mft_file_path]")
        sys.exit(1)
    
    path = sys.argv[1]
    mft_file = sys.argv[2] if len(sys.argv) > 2 else None
    run_offline_mft(path, mft_file)
