""
Data access layer for the Crow Eye application.
Provides classes for loading and processing various types of forensic data.
"""

from .base_loader import BaseDataLoader
from .registry_loader import RegistryDataLoader

__all__ = ['BaseDataLoader', 'RegistryDataLoader']
