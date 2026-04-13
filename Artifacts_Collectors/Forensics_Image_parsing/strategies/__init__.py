"""
Image Access Strategy Classes

This module contains FileAccessStrategy implementations for forensic image formats.

Available strategies:
- E01AccessStrategy: E01/Ex01 images using libewf
- VHDXAccessStrategy: VHDX/VHD images using pyvhdi
- VMDKAccessStrategy: VMDK images using pyvmdk
- ISOAccessStrategy: ISO images using pytsk3
- RawAccessStrategy: Raw/DD images using pytsk3
"""

# Only import implemented strategies
__all__ = []

try:
    from .e01_access_strategy import E01AccessStrategy
    __all__.append('E01AccessStrategy')
except ImportError as e:
    # If dependencies are missing, provide a helpful error message
    print(f"Warning: Could not import E01AccessStrategy: {e}")

try:
    from .vhdx_access_strategy import VHDXAccessStrategy
    __all__.append('VHDXAccessStrategy')
except ImportError as e:
    # If dependencies are missing, provide a helpful error message
    print(f"Warning: Could not import VHDXAccessStrategy: {e}")

try:
    from .vmdk_access_strategy import VMDKAccessStrategy
    __all__.append('VMDKAccessStrategy')
except ImportError as e:
    # If dependencies are missing, provide a helpful error message
    print(f"Warning: Could not import VMDKAccessStrategy: {e}")

try:
    from .iso_access_strategy import ISOAccessStrategy
    __all__.append('ISOAccessStrategy')
except ImportError as e:
    # If dependencies are missing, provide a helpful error message
    print(f"Warning: Could not import ISOAccessStrategy: {e}")

try:
    from .raw_access_strategy import RawAccessStrategy
    __all__.append('RawAccessStrategy')
except ImportError as e:
    # If dependencies are missing, provide a helpful error message
    print(f"Warning: Could not import RawAccessStrategy: {e}")
