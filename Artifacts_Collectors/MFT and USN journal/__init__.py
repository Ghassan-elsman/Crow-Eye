"""
MFT and USN Journal Parsers Package

This package contains parsers for NTFS Master File Table (MFT) and 
Update Sequence Number (USN) Journal forensic artifacts.

Modules:
- MFT_Claw: NTFS MFT parser
- USN_Claw: USN Journal parser  
- mft_usn_correlator: Correlates MFT and USN data
"""

__all__ = ['MFT_Claw', 'USN_Claw', 'mft_usn_correlator']
