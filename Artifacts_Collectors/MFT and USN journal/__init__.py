"""
MFT and USN Journal Analysis Package

This package contains tools for parsing and correlating NTFS Master File Table (MFT)
and Update Sequence Number (USN) Journal data for forensic analysis.

Modules:
    - MFT_Claw: NTFS MFT parser
    - USN_Claw: USN Journal parser
    - mft_usn_correlator: Correlation engine for MFT and USN data
"""

__version__ = "2.0.0"
__author__ = "Ghassan Elsman (Crow Eye Development)"

# Import main classes for easier access
try:
    from .mft_usn_correlator import MFTUSNCorrelator
    __all__ = ['MFTUSNCorrelator']
except ImportError:
    # If imports fail, just make the package importable
    __all__ = []
