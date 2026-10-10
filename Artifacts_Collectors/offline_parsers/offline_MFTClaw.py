"""
Offline MFT Parser Wrapper for Crow-eye
========================================

This module provides a dedicated offline wrapper for the MFT (Master File Table) parser,
allowing for the analysis of collected $MFT files from a case directory.
"""

import os
import sys
import logging

# Named, so its records reach parsers.log: the root logger's do not.
logger = logging.getLogger(__name__)

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Add MFT parser directory to path
mft_dir = os.path.join(parent_dir, 'MFT and USN journal')
if mft_dir not in sys.path:
    sys.path.insert(0, mft_dir)

# ...and this folder, for offline_MFT_USN_Correlator (the volume label and the
# correlation both live there).
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

def run_offline_mft(case_path, mft_file_path=None, registry_hive_paths=None, correlate=True):
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
        from MFT_Claw import (MFTClawConfig, MFTParser, OutputFormat, LogLevel, DatabaseManager,
                              merge_extension_records)
        
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
        
        # The disk's own volume, not one made from the file name: Crow-Claw's
        # copy of C:'s $MFT is stored as 'C', beside (and deduplicated
        # against) a live parse of C:. It was 'OFFLINE', so the same disk was
        # stored twice, and two disks' $MFT files shared 'OFFLINE'.
        from volume_identity import resolve_volume
        volume_label, how = resolve_volume(mft_file_path, case_path, output_db)
        print(f"[Offline MFT] Volume: {volume_label} (from {how})")

        # No "already parsed -> skip": a volume already in the database goes
        # through the per-volume re-parse guard (utils/dedupe_insert), which
        # adds only what is new and reports the rest as already present. A
        # whole-volume skip hid everything a later capture of the disk added.
        print(f"[Offline MFT] Parsing the MFT file")
        
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
            # 10,000 records per insert + commit (was 1,000): the commit
            # per batch was a tenth of the parse.
            batch_size=10000,
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

        # A load large next to what the tables already hold builds the
        # secondary indexes once at the end instead of row by row.
        db = parser.db_manager
        try:
            existing = db.connection.execute("SELECT MAX(rowid) FROM mft_records").fetchone()[0] or 0
        except Exception:
            existing = 0
        suspended = []
        if estimated_records >= 50000 and estimated_records * 2 >= existing:
            suspended = db.suspend_secondary_indexes()

        def _records(handle, chunk_records=4096):
            """1024-byte records, read 4 MB at a time (one read per record before)."""
            while True:
                chunk = handle.read(record_size * chunk_records)
                if not chunk:
                    return
                for i in range(0, len(chunk) - record_size + 1, record_size):
                    yield chunk[i:i + record_size]
                if len(chunk) % record_size:
                    return                     # a short tail: no whole record left

        try:
            with open(mft_file_path, 'rb') as mft_file:
                record_num = 0
                for raw_record in _records(mft_file):
                    try:
                        # Parse the record using parser's internal method
                        mft_record = parser._parse_mft_record(record_num, volume_label, raw_record)
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
                        logger.debug(f"Error parsing record {record_num}: {e}")

                    record_num += 1

            # Process remaining batch
            if batch_records:
                parser._process_record_batch(batch_records)
                parser.db_manager.commit()
        finally:
            # Always - a failed parse too: the indexes dropped for the bulk
            # load were left dropped when the parse raised.
            if suspended:
                print(f"[Offline MFT] Building indexes ({', '.join(suspended)})...")
            try:
                db.connection.rollback()        # nothing half-written holds the lock
                db.restore_secondary_indexes()
            except Exception as e:
                print(f"[Offline MFT] Could not rebuild the indexes: {e}")
        
        print(f"\n[Offline MFT] Successfully parsed {records_parsed:,} MFT records")
        merged = merge_extension_records(parser.db_manager.connection, volume_label,
                                         parser.db_manager.child_start_rowid,
                                         parser.db_manager.tally)
        if merged:
            print(f"[Offline MFT] Merged {merged:,} extension record(s) into their base records")
        # What this run added vs what the database already held (a re-parse of
        # the same $MFT adds nothing).
        # Counted in MFT records (mft_records), not summed over the four
        # tables - "new" was rows, five or six per record, beside a record count.
        counts = parser.db_manager.tally.as_result(primary="mft_records")
        print(f"[Offline MFT] MFT records: {counts['records']:,} - new: {counts['inserted']:,}, "
              f"already in the database: {counts['duplicates']:,} "
              f"(rows written across the MFT tables: {counts['rows']:,})")
        
        # Cleanup
        parser.cleanup()
        
        # After successful MFT parsing, check if we should run correlation
        print(f"[Offline MFT] Checking for USN database to run correlation...")
        usn_db_path = os.path.join(output_dir, 'USN_journal.db')
        
        if not correlate:
            print(f"[Offline MFT] Correlation is left to the caller (once per batch)")
        elif os.path.exists(usn_db_path):
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
            "inserted": counts["inserted"],
            "duplicates": counts["duplicates"],
            "tables": counts["tables"],
            "volume": volume_label,
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
