"""
Correlation Engine - Forensic Analysis System
Main package for the correlation engine system.
"""

__version__ = "0.1.0"
__author__ = "Crow-Eye Forensics"

# Import optimization module
try:
    from . import optimization
except ImportError:
    # Optimization module is optional
    optimization = None
