"""
Data access layer for the Crow Eye application.
Provides classes for loading and processing various types of forensic data.
"""

from .base_loader import BaseDataLoader
from .registry_loader import RegistryDataLoader
from .mft_loader import MFTDataLoader
from .usn_loader import USNDataLoader
from .correlated_loader import CorrelatedDataLoader
from .index_manager import IndexManager
from .search_engine import (
    DatabaseSearchEngine,
    SearchConfig,
    SearchResult as LegacySearchResult,
    SearchResults,
    SearchCache
)
from .database_manager import (
    DatabaseManager,
    SearchResult,
    DatabaseInfo
)
from .unified_search_engine import (
    UnifiedDatabaseSearchEngine,
    SearchParameters
)

__all__ = [
    'BaseDataLoader',
    'RegistryDataLoader',
    'MFTDataLoader',
    'USNDataLoader',
    'CorrelatedDataLoader',
    'IndexManager',
    'DatabaseSearchEngine',
    'SearchConfig',
    'LegacySearchResult',
    'SearchResults',
    'SearchCache',
    'DatabaseManager',
    'SearchResult',
    'DatabaseInfo',
    'UnifiedDatabaseSearchEngine',
    'SearchParameters'
]
