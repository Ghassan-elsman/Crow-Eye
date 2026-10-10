"""
Launch script for the Offline Artifact Importer GUI.

This script launches the GUI with all advanced features enabled.
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from Offline_Importer.offline_importer_gui import launch_gui


def main():
    """Launch the Offline Artifact Importer GUI."""
    print("=" * 60)
    print("Launching Offline Artifact Importer GUI")
    print("=" * 60)
    print("\nAdvanced Features Enabled:")
    print("  [OK] Batch Collection from Multiple Directories")
    print("  [OK] Artifact Deduplication Based on Hash")
    print("  [OK] Incremental Collection")
    print("  [OK] Collection Report Generation (HTML/PDF)")
    print("  [OK] Artifact Validation")
    print("\n" + "=" * 60)
    print("\nStarting GUI...")
    
    try:
        # Launch the GUI using the built-in function
        launch_gui()
        
    except Exception as e:
        print(f"\nError launching GUI: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    main()
