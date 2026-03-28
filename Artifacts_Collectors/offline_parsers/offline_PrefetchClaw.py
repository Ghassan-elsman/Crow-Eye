"""
Offline Prefetch Parser Wrapper for Crow-eye
============================================

This module provides a dedicated offline wrapper for the Prefetch parser,
allowing for the analysis of collected .pf files from a case directory.
"""

import os
import sys
import logging

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from Prefetch_claw import prefetch_claw
except ImportError:
    try:
        from Artifacts_Collectors.Prefetch_claw import prefetch_claw
    except ImportError:
        grandparent_dir = os.path.dirname(parent_dir)
        if grandparent_dir not in sys.path:
            sys.path.insert(0, grandparent_dir)
        from Artifacts_Collectors.Prefetch_claw import prefetch_claw

def run_offline_prefetch(case_path, windows_partition="C:", prefetch_dir=None, registry_hive_paths=None):
    """
    Run prefetch analysis in offline mode.
    
    Args:
        case_path (str): Path to the case directory
        windows_partition (str): Original windows partition (default: C:)
        prefetch_dir (str, optional): Explicit prefetch directory to parse. If not provided,
                                      uses case_path/live_acquisition/Prefetch
        registry_hive_paths (dict, optional): DEPRECATED - Not used by this parser.
                                              Kept for backward compatibility only.
    
    Note:
        Prefetch parser operates on .pf file artifacts and does not require
        registry context. The registry_hive_paths parameter is ignored.
        
    Returns:
        dict: Parser results including record counts and status
    """
    print(f"[Offline Prefetch] Starting analysis for case: {case_path}")
    if prefetch_dir:
        print(f"[Offline Prefetch] Using explicit prefetch directory: {prefetch_dir}")
    
    try:
        # Don't pass registry_hive_paths - prefetch_claw doesn't accept it
        # The prefetch_claw function already supports offline_mode
        result = prefetch_claw(
            case_path=case_path,
            offline_mode=True,
            windows_partition=windows_partition,
            prefetch_dir=prefetch_dir  # Pass explicit directory
            # Removed: registry_hive_paths parameter (underlying function doesn't accept it)
        )
        return result
    except Exception as e:
        print(f"[Offline Prefetch Error] {str(e)}")
        return {"success": False, "error": str(e), "records": 0}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python offline_PrefetchClaw.py <case_path> [windows_partition]")
        sys.exit(1)
    
    path = sys.argv[1]
    partition = sys.argv[2] if len(sys.argv) > 2 else "C:"
    run_offline_prefetch(path, partition)
