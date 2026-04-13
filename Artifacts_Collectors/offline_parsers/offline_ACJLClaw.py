"""
Offline Jump Lists & LNK Parser Wrapper for Crow-eye
====================================================

This module provides a dedicated offline wrapper for the Jump Lists and LNK parser,
allowing for the analysis of collected .lnk and -ms files from a case directory.
"""

import os
import sys
import logging

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from A_CJL_LNK_Claw import A_CJL_LNK_Claw
except ImportError:
    try:
        from Artifacts_Collectors.A_CJL_LNK_Claw import A_CJL_LNK_Claw
    except ImportError:
        grandparent_dir = os.path.dirname(parent_dir)
        if grandparent_dir not in sys.path:
            sys.path.insert(0, grandparent_dir)
        from Artifacts_Collectors.A_CJL_LNK_Claw import A_CJL_LNK_Claw

def run_offline_acjl(case_path, registry_hive_paths=None, direct_parse=False):
    """
    Run Jump Lists and LNK analysis in offline mode.
    
    Args:
        case_path (str): Path to the case directory
        registry_hive_paths (dict, optional): DEPRECATED - Not used by this parser.
                                              Kept for backward compatibility only.
        direct_parse (bool, optional): Whether to parse artifacts directly.
    
    Note:
        JumpLists/LNK parser operates on file artifacts (.lnk, .automaticDestinations-ms)
        and does not require registry context. The registry_hive_paths parameter is ignored.
        
    Returns:
        dict: Parser results including record counts and status
    """
    print(f"[Offline ACJL] Starting analysis for case: {case_path}")
    
    try:
        # Don't pass registry_hive_paths - A_CJL_LNK_Claw doesn't accept it
        # The A_CJL_LNK_Claw function handles offline collection structure
        result = A_CJL_LNK_Claw(
            case_path=case_path,
            offline_mode=True,
            direct_parse=direct_parse
            # Removed: registry_hive_paths parameter (underlying function doesn't accept it)
        )
        return result
    except Exception as e:
        print(f"[Offline ACJL Error] {str(e)}")
        return {"success": False, "error": str(e), "records": 0}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python offline_ACJLClaw.py <case_path>")
        sys.exit(1)
    
    path = sys.argv[1]
    run_offline_acjl(path)
