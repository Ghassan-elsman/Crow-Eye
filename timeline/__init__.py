"""
Forensic Timeline Visualization Module

This module provides interactive timeline visualization for forensic artifacts
collected by Crow Eye. It displays artifacts chronologically with filtering,
correlation, and detailed event information.
"""

__version__ = "1.0.0"
__author__ = "Crow Eye Development Team"

# Import components as they are implemented
from .timeline_dialog import TimelineDialog

__all__ = ['TimelineDialog']
