"""
Offline AmCache Parser Wrapper for Crow-eye
===========================================

This module provides a dedicated offline wrapper for the AmCache parser,
allowing for the analysis of collected Amcache.hve hives from a case directory.
"""

import os
import sys
import logging

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from amcacheparser import amcache_parser
except ImportError:
    try:
        from Artifacts_Collectors.amcacheparser import amcache_parser
    except ImportError:
        grandparent_dir = os.path.dirname(parent_dir)
        if grandparent_dir not in sys.path:
            sys.path.insert(0, grandparent_dir)
        from Artifacts_Collectors.amcacheparser import amcache_parser

def run_offline_amcache(case_path, windows_partition="C:"):
    """
    Run AmCache analysis in offline mode.
    
    Args:
        case_path (str): Path to the case directory
        windows_partition (str): Original windows partition (default: C:)
        
    Returns:
        dict: Parser results including record counts and status
    """
    print(f"[Offline AmCache] Starting analysis for case: {case_path}")
    
    try:
        # The amcache_parser function now returns a dict with correct format
        result = amcache_parser(
            case_path=case_path,
            offline_mode=True,
            windows_partition=windows_partition
        )
        # Result is already in correct format: {'success': bool, 'records': int, 'output_path': str}
        return result
    except Exception as e:
        print(f"[Offline AmCache Error] {str(e)}")
        # Construct expected output path even on error (flat structure)
        output_path = os.path.join(case_path, "Target_Artifacts", "amcache.db")
        return {"success": False, "error": str(e), "records": 0, "output_path": output_path}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python offline_AmCacheClaw.py <case_path> [windows_partition]")
        sys.exit(1)
    
    path = sys.argv[1]
    partition = sys.argv[2] if len(sys.argv) > 2 else "C:"
    run_offline_amcache(path, partition)
