"""
Offline MFT-USN Correlator Wrapper for Crow-eye
================================================

This module provides an offline wrapper for the MFT-USN correlator,
automatically running correlation when both MFT and USN databases exist.
"""

import os
import sys
import logging

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Add MFT and USN journal directory to path
mft_usn_dir = os.path.join(parent_dir, 'MFT and USN journal')
if mft_usn_dir not in sys.path:
    sys.path.insert(0, mft_usn_dir)


def offline_volume_label(path, case_root=None, db_path=None, journal=False):
    """The volume a collected $MFT (or, with journal=True, $J) is stored under.

    The parsers ask volume_identity directly; this is the same answer for any
    caller still importing it from here. The journal gets the label of its
    $MFT, so the correlator - which joins on volume_letter - pairs the two.
    It used to be made from the file name alone ('OFFLINE', 'OFFLINE_1' for a
    name-conflict copy), so Crow-Claw's copy of C:'s $MFT was stored a second
    time beside the live parse of C:, and two disks' $MFT files shared
    'OFFLINE'. That name-based label is now only the last resort.
    """
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    import volume_identity
    if journal:
        return volume_identity.resolve_usn_volume_label(path, case_root, db_path)
    return volume_identity.resolve_volume_label(path, case_root, db_path)


def run_offline_correlation(case_path, force=False):
    """
    Run MFT-USN correlation in offline mode.
    
    This function checks if both MFT and USN databases exist in the case directory,
    and if so, runs the correlator to create the correlated analysis database.
    
    Args:
        case_path (str): Path to the case directory
    
    Returns:
        dict: Correlation results including status and database path
    """
    print(f"[Offline Correlator] Checking for MFT and USN databases in: {case_path}")
    
    # Define expected database paths in Target_Artifacts
    target_artifacts_dir = os.path.join(case_path, 'Target_Artifacts')
    
    # Try both possible MFT database names (different versions use different names)
    mft_db_names = ['mft_claw_analysis.db', 'MFT_data.db']
    mft_db_path = None
    
    for db_name in mft_db_names:
        test_path = os.path.join(target_artifacts_dir, db_name)
        if os.path.exists(test_path):
            mft_db_path = test_path
            break
    
    usn_db_path = os.path.join(target_artifacts_dir, 'USN_journal.db')
    correlated_db_path = os.path.join(target_artifacts_dir, 'mft_usn_correlated_analysis.db')
    
    # An existing correlation is reused only while it is newer than both of
    # its inputs. It was reused whenever it existed, so evidence parsed later
    # (a second import, a re-collected $J) was never correlated.
    inputs = [p for p in (mft_db_path, usn_db_path) if p and os.path.exists(p)]
    stale = bool(inputs) and os.path.exists(correlated_db_path) and \
        os.path.getmtime(correlated_db_path) < max(os.path.getmtime(p) for p in inputs)
    if os.path.exists(correlated_db_path) and (force or stale):
        try:
            os.remove(correlated_db_path)        # derived: rebuilt below
            print(f"[Offline Correlator] Rebuilding the correlation (inputs are newer)")
        except OSError as e:
            # Open in the GUI: the correlator appends (rows are unique).
            print(f"[Offline Correlator] Could not remove the old correlation ({e}); updating it in place")
    if os.path.exists(correlated_db_path) and not (force or stale):
        print(f"[Offline Correlator] Correlated database already exists: {correlated_db_path}")
        try:
            import sqlite3
            conn = sqlite3.connect(correlated_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM mft_usn_correlated")
            count = cursor.fetchone()[0]
            conn.close()
            
            print(f"[Offline Correlator] Using existing correlated database with {count:,} records")
            return {
                "success": True,
                "records": count,
                "output_path": correlated_db_path,
                "message": "Using existing correlated database"
            }
        except Exception as e:
            print(f"[Offline Correlator] Error reading existing database: {e}")
    
    # Check if both MFT and USN databases exist
    mft_exists = mft_db_path is not None
    usn_exists = os.path.exists(usn_db_path)
    
    if not mft_exists and not usn_exists:
        print(f"[Offline Correlator] Neither MFT nor USN database found")
        return {
            "success": False,
            "error": "Neither MFT nor USN database found. Run MFT and USN parsers first.",
            "records": 0
        }
    
    if not mft_exists:
        print(f"[Offline Correlator] MFT database not found: {mft_db_path}")
        return {
            "success": False,
            "error": "MFT database not found. Run MFT parser first.",
            "records": 0
        }
    
    if not usn_exists:
        print(f"[Offline Correlator] USN database not found: {usn_db_path}")
        print(f"[Offline Correlator] Correlation requires both MFT and USN databases")
        return {
            "success": False,
            "error": "USN database not found. Run USN parser first.",
            "records": 0
        }
    
    print(f"[Offline Correlator] Found MFT database: {mft_db_path}")
    print(f"[Offline Correlator] Found USN database: {usn_db_path}")
    print(f"[Offline Correlator] Starting correlation...")
    
    try:
        # Import the correlator
        from mft_usn_correlator import MFTUSNCorrelator
        
        # Create correlator instance with case directory
        correlator = MFTUSNCorrelator(case_directory=case_path)
        
        # Override the database paths to use the actual found databases
        correlator.mft_db = mft_db_path
        correlator.usn_db = usn_db_path
        correlator.correlated_db = correlated_db_path
        
        # The join, the record names and the name columns - and never a
        # parser: run_complete_analysis() would first parse THIS machine's
        # MFT and USN into the evidence case.
        print(f"[Offline Correlator] Creating correlated database...")
        correlator.correlate_existing()
        correlator.generate_forensic_report()
        
        # Verify the correlated database was created
        if os.path.exists(correlated_db_path):
            import sqlite3
            conn = sqlite3.connect(correlated_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM mft_usn_correlated")
            count = cursor.fetchone()[0]
            conn.close()
            
            print(f"[Offline Correlator] Correlation complete!")
            print(f"[Offline Correlator] Correlated records: {count:,}")
            print(f"[Offline Correlator] Database: {correlated_db_path}")
            
            return {
                "success": True,
                "records": count,
                "output_path": correlated_db_path,
                "message": "Correlation completed successfully"
            }
        else:
            return {
                "success": False,
                "error": "Correlated database was not created",
                "records": 0
            }
            
    except ImportError as e:
        error_msg = f"Failed to import MFT-USN correlator: {str(e)}"
        print(f"[Offline Correlator Error] {error_msg}")
        return {"success": False, "error": error_msg, "records": 0}
    except Exception as e:
        error_msg = f"Correlation failed: {str(e)}"
        print(f"[Offline Correlator Error] {error_msg}")
        return {"success": False, "error": error_msg, "records": 0}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python offline_MFT_USN_Correlator.py <case_path>")
        sys.exit(1)
    
    case_path = sys.argv[1]
    result = run_offline_correlation(case_path)
    
    if result["success"]:
        print(f"\nSuccess! Correlated {result['records']:,} records")
        sys.exit(0)
    else:
        print(f"\nFailed: {result.get('error', 'Unknown error')}")
        sys.exit(1)
