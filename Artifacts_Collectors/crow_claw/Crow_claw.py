"""
Crow-Claw Main Entry Point
===========================

Launch the Crow-Claw artifact acquisition tool with optional integrated mode support.

Usage:
    Standalone mode:
        python Crow_claw.py

    Integrated mode (via Crow-Eye):
        python Crow_claw.py --case-directory "C:/Path/To/Case"
"""

import sys
import os
import argparse

# Add parent directories to path for proper imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)

# Add both the crow_claw directory and Artifacts_Collectors directory to path
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from PyQt5.QtWidgets import QApplication

# Import using absolute path from crow_claw package
from crow_claw.gui.main_window import CrowClawMainWindow


def parse_arguments():
    """Parse command-line arguments for Crow-Claw.

    Returns:
        argparse.Namespace: Parsed arguments including:
            - case_directory: Path to case directory (optional, for integrated mode)
            - integrated_mode: Boolean indicating if running in integrated mode
    """
    parser = argparse.ArgumentParser(
        description="Crow-Claw - Windows Forensic Artifact Acquisition Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Standalone mode:
    python Crow_claw.py

  Integrated mode (via Crow-Eye):
    python Crow_claw.py --case-directory "C:/Path/To/Case"
        """
    )

    parser.add_argument(
        '--case-directory',
        '-c',
        type=str,
        default=None,
        help='Case directory path (enables integrated mode with Crow-Eye)'
    )

    return parser.parse_args()


def main():
    """Main entry point for Crow-Claw.

    Supports two modes:
    1. Standalone: User selects output directory
    2. Integrated: Receives case directory from Crow-Eye via --case-directory argument
    """
    # Parse command-line arguments
    args = parse_arguments()

    # Create Qt application
    app = QApplication(sys.argv)

    # Set application properties
    app.setApplicationName("Crow-Claw")
    app.setApplicationVersion("1.0.0")

    # Create and show main window with optional case directory (integrated mode)
    window = CrowClawMainWindow(case_directory=args.case_directory)
    window.show()

    # Run application
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
