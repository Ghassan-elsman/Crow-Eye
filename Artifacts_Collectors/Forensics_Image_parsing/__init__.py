"""
Forensic Image Parsing Module

This module extends the Crow-Claw artifact acquisition engine to support
forensic image formats (E01, VHDX, VMDK, ISO, Raw/DD).

Components:
- Image_Access_Strategy classes: Extend FileAccessStrategy for each image format
- ImageParser: Format detection and strategy selection
- ImageParsingDialog: Three-panel GUI for image processing
- Integration with existing CollectionCoordinator and ArtifactCollector
"""

__version__ = "1.0.0"
__author__ = "Crow-Eye Forensics"

# Imports will be added as modules are implemented
# from .image_parser import ImageParser
# from .image_parsing_dialog import ImageParsingDialog

__all__ = []
