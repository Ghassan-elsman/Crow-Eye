"""
Offline Recycle Bin Parser Wrapper for Crow-eye
===============================================

This module provides a dedicated offline wrapper for the Recycle Bin parser,
allowing for the analysis of collected $I and $R files from a case directory.
"""

import os
import sys
import logging

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from recyclebin_claw import parse_recycle_bin
except ImportError:
    try:
        from Artifacts_Collectors.recyclebin_claw import parse_recycle_bin
    except ImportError:
        grandparent_dir = os.path.dirname(parent_dir)
        if grandparent_dir not in sys.path:
            sys.path.insert(0, grandparent_dir)
        from Artifacts_Collectors.recyclebin_claw import parse_recycle_bin

def run_offline_recyclebin(case_path, network_paths=None, artifact_dir=None):
    """
    Run Recycle Bin analysis in offline mode.
    
    Args:
        case_path (str): Path to the case directory
        network_paths (list): Optional network paths to include
        artifact_dir (str): Optional directory containing the scanned RecycleBin artifacts
        
    Returns:
        dict: Parser results including record counts and status
    """
    print(f"[Offline Recycle Bin] Starting analysis for case: {case_path}")
    
    try:
        # The parse_recycle_bin function now returns a dict with correct format
        result = parse_recycle_bin(
            case_path=case_path,
            offline_mode=True,
            network_paths=network_paths,
            artifact_dir=artifact_dir
        )
        # Result is already in correct format: {'success': bool, 'records': int, 'output_path': str}
        return result
    except Exception as e:
        print(f"[Offline Recycle Bin Error] {str(e)}")
        return {"success": False, "error": str(e), "records": 0}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python offline_RecycleBinClaw.py <case_path>")
        sys.exit(1)
    
    path = sys.argv[1]
    run_offline_recyclebin(path)
