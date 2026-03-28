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


def run_offline_correlation(case_path):
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
    
    # Check if correlated database already exists
    if os.path.exists(correlated_db_path):
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
        
        # Run correlation (skip parser execution since databases already exist)
        print(f"[Offline Correlator] Creating correlated database...")
        correlator.create_correlated_database()
        
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
