"""
EYE (Enhanced Yield Engine) - AI-Powered Forensic Investigation Assistant

EYE bridges natural language interaction with Crow-eye's SQLite forensic databases,
enabling investigators to query databases conversationally, create semantic rules,
and receive forensic guidance while maintaining strict security controls.
"""

__version__ = "0.1.0"
__author__ = "Crow-eye Forensics"

# Package initialization
from pathlib import Path

# Define package directories
PACKAGE_ROOT = Path(__file__).parent
SERVICES_DIR = PACKAGE_ROOT / "services"
UI_DIR = PACKAGE_ROOT / "ui"
BRIDGE_DIR = PACKAGE_ROOT / "bridge"
MODELS_DIR = PACKAGE_ROOT / "models"
TESTS_DIR = PACKAGE_ROOT / "tests"

__all__ = [
    "__version__",
    "__author__",
    "PACKAGE_ROOT",
    "SERVICES_DIR",
    "UI_DIR",
    "BRIDGE_DIR",
    "MODELS_DIR",
    "TESTS_DIR",
]
