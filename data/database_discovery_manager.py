"""
Enhanced Database Discovery Manager for Crow Eye.

Provides comprehensive database discovery with timestamp column detection,
GUI tab name mapping, and metadata caching for the unified search system.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Set, Union
from dataclasses import dataclass, field

from data.timestamp_detector import TimestampDetector
from data.database_manager import DatabaseManager, DatabaseInfo


@dataclass
class TimestampColumnInfo:
    """
    Information about a timestamp column in a database table.
    
    Attributes:
        name: Column name
        format: Detected timestamp format ('iso8601', 'unix', 'filetime', 'datetime', 'mixed')
        sample_values: Sample of original values from the column
        parse_success_rate: Percentage of successfully parsed timestamp values
    """
    name: str
    format: str
    sample_values: List[str] = field(default_factory=list)
    parse_success_rate: float = 0.0


@dataclass
class TableInfo:
    """
    Information about a database table.
    
    Attributes:
        name: Table name
        columns: List of all column names
        timestamp_columns: List of detected timestamp columns with metadata
        row_count: Number of rows in the table (None if not counted)
        supports_time_filtering: Whether this table has valid timestamp columns
    """
    name: str
    columns: List[str] = field(default_factory=list)
    timestamp_columns: List[TimestampColumnInfo] = field(default_factory=list)
    row_count: Optional[int] = None
    supports_time_filtering: bool = False
    
    def __post_init__(self):
        """Update supports_time_filtering based on timestamp_columns."""
        self.supports_time_filtering = len(self.timestamp_columns) > 0


@dataclass
class EnhancedDatabaseInfo:
    """
    Extended database information with timestamp metadata and GUI mapping.
    
    Attributes:
        name: Database filename (e.g., 'registry_data.db')
        path: Full path to the database file
        category: Forensic category (e.g., 'Registry Evidence')
        gui_tab_name: Normalized name matching GUI tabs (e.g., 'Prefetch')
        tables: Dictionary mapping table names to TableInfo objects
        accessible: Whether the database can be opened
        exists: Whether the database file exists
        error: Error message if database is not accessible
    """
    name: str
    path: Path
    category: str
    gui_tab_name: str
    tables: Dict[str, TableInfo] = field(default_factory=dict)
    accessible: bool = True
    exists: bool = True
    error: Optional[str] = None
    
    def supports_time_filtering(self) -> bool:
        """Check if any table in this database supports time filtering."""
        return any(table.supports_time_filtering for table in self.tables.values())


class DatabaseDiscoveryManager:
    """
    Manages database discovery with enhanced metadata including
    timestamp columns and GUI tab mappings.
    
    This manager extends the basic DatabaseManager functionality with:
    - Automatic timestamp column detection per table
    - GUI tab name mapping for seamless navigation
    - Database grouping by GUI tab
    - Metadata caching for performance
    """
    
    # GUI tab name mappings
    # Maps database file names and display names to their corresponding GUI tab names
    GUI_TAB_MAPPINGS = {
        # Execution Evidence
        'prefetch_data.db': 'Prefetch',
        'Prefetch Files': 'Prefetch',
        'amcache_data.db': 'Amcache',
        'amcache.db': 'Amcache',
        'AmCache': 'Amcache',
        'shimcache_data.db': 'ShimCache',
        'shimcache.db': 'ShimCache',
        'ShimCache': 'ShimCache',
        'lnk_data.db': 'LNK/JL',
        'LnkDB.db': 'LNK/JL',
        'LNK Files': 'LNK/JL',
        'jumplist_data.db': 'LNK/JL',
        'Jump Lists': 'LNK/JL',
        'userassist_data.db': 'UserAssist',
        'UserAssist': 'UserAssist',
        'bam_dam_data.db': 'BAM/DAM',
        'BAM/DAM': 'BAM/DAM',
        
        # Registry Evidence
        'registry_data.db': 'Registry',
        'Registry Data': 'Registry',
        'muicache_data.db': 'MUICache',
        'MUICache': 'MUICache',
        'shellbags_data.db': 'ShellBags',
        'ShellBags': 'ShellBags',
        
        # File System Evidence
        'mft_data.db': 'MFT',
        'mft_claw_analysis.db': 'MFT',
        'MFT Records': 'MFT',
        'usn_data.db': 'USN Journal',
        'USN_journal.db': 'USN Journal',
        'USN Journal': 'USN Journal',
        'recyclebin_data.db': 'Recycle Bin',
        'recyclebin_analysis.db': 'Recycle Bin',
        'Recycle Bin': 'Recycle Bin',
        
        # System Information
        'eventlog_data.db': 'Event Logs',
        'Event Logs': 'Event Logs',
        
        # SRUM (System Resource Usage Monitor)
        'srum_data.db': 'SRUM',
        'srum_dump.db': 'SRUM',
        'SRUM': 'SRUM',
    }
    
    def __init__(self, case_directory: Union[str, Path]):
        """
        Initialize the database discovery manager.
        
        Args:
            case_directory: Path to the case directory containing artifact databases
        """
        self.case_directory = Path(case_directory)
        self.db_manager = DatabaseManager(case_directory)
        self.timestamp_detector = TimestampDetector()
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Cache for enhanced database information
        self.cache: Dict[str, EnhancedDatabaseInfo] = {}
        
        self.logger.info(f"Initialized database discovery manager for: {self.case_directory}")
    
    def discover_databases_with_metadata(
        self,
        force_refresh: bool = False,
        verify_timestamps: bool = True,
        sample_size: int = 100
    ) -> List[EnhancedDatabaseInfo]:
        """
        Discover databases with full metadata including timestamp columns.
        
        Uses caching to avoid repeated schema analysis. Set force_refresh=True
        to bypass cache and re-analyze all databases.
        
        Args:
            force_refresh: Force re-discovery and bypass cache
            verify_timestamps: Whether to verify timestamp columns by sampling data
            sample_size: Number of rows to sample for timestamp verification
            
        Returns:
            List of EnhancedDatabaseInfo objects with complete metadata
        """
        if not force_refresh and self.cache:
            self.logger.debug("Returning cached database metadata")
            return list(self.cache.values())
        
        self.logger.info("Discovering databases with metadata...")
        
        # Use DatabaseManager to discover basic database information
        basic_databases = self.db_manager.discover_databases()
        
        enhanced_databases = []
        
        for db_info in basic_databases:
            try:
                enhanced_db = self._enhance_database_info(
                    db_info,
                    verify_timestamps=verify_timestamps,
                    sample_size=sample_size
                )
                enhanced_databases.append(enhanced_db)
                
                # Cache the enhanced info
                self.cache[db_info.name] = enhanced_db
                
            except Exception as e:
                self.logger.error(
                    f"Error enhancing database info for {db_info.name}: {e}",
                    exc_info=True
                )
                # Create minimal enhanced info on error
                enhanced_db = EnhancedDatabaseInfo(
                    name=db_info.name,
                    path=db_info.path,
                    category=db_info.category,
                    gui_tab_name=self.get_gui_tab_name(db_info.name, db_info.display_name),
                    tables={},
                    accessible=False,
                    exists=db_info.exists,
                    error=str(e)
                )
                enhanced_databases.append(enhanced_db)
                self.cache[db_info.name] = enhanced_db
        
        # Log summary
        accessible_count = len([db for db in enhanced_databases if db.accessible])
        time_filter_count = len([db for db in enhanced_databases if db.supports_time_filtering()])
        
        self.logger.info(
            f"Discovered {len(enhanced_databases)} databases: "
            f"{accessible_count} accessible, "
            f"{time_filter_count} support time filtering"
        )
        
        return enhanced_databases
    
    def _enhance_database_info(
        self,
        db_info: DatabaseInfo,
        verify_timestamps: bool = True,
        sample_size: int = 100
    ) -> EnhancedDatabaseInfo:
        """
        Enhance basic database info with timestamp metadata.
        
        Args:
            db_info: Basic database information from DatabaseManager
            verify_timestamps: Whether to verify timestamp columns by sampling data
            sample_size: Number of rows to sample for verification
            
        Returns:
            EnhancedDatabaseInfo with complete metadata
        """
        # Get GUI tab name
        gui_tab_name = self.get_gui_tab_name(db_info.name, db_info.display_name)
        
        # Create enhanced database info
        enhanced_db = EnhancedDatabaseInfo(
            name=db_info.name,
            path=db_info.path,
            category=db_info.category,
            gui_tab_name=gui_tab_name,
            tables={},
            accessible=db_info.accessible,
            exists=db_info.exists,
            error=db_info.error
        )
        
        # If database is not accessible, return early
        if not db_info.accessible or not db_info.exists:
            return enhanced_db
        
        # Analyze each table for timestamp columns
        for table_name in db_info.tables:
            try:
                table_info = self._analyze_table(
                    db_info.path,
                    table_name,
                    verify_timestamps=verify_timestamps,
                    sample_size=sample_size
                )
                enhanced_db.tables[table_name] = table_info
                
            except Exception as e:
                self.logger.warning(
                    f"Error analyzing table {table_name} in {db_info.name}: {e}"
                )
                # Create minimal table info on error
                table_info = TableInfo(
                    name=table_name,
                    columns=[],
                    timestamp_columns=[],
                    row_count=None,
                    supports_time_filtering=False
                )
                enhanced_db.tables[table_name] = table_info
        
        return enhanced_db
    
    def _analyze_table(
        self,
        db_path: Path,
        table_name: str,
        verify_timestamps: bool = True,
        sample_size: int = 100
    ) -> TableInfo:
        """
        Analyze a table for columns and timestamp information.
        
        Args:
            db_path: Path to the database file
            table_name: Name of the table to analyze
            verify_timestamps: Whether to verify timestamp columns by sampling data
            sample_size: Number of rows to sample for verification
            
        Returns:
            TableInfo with column and timestamp metadata
        """
        # Get all columns
        columns = self.timestamp_detector.get_table_columns(str(db_path), table_name)
        
        # Detect timestamp columns
        timestamp_columns = []
        
        if verify_timestamps:
            # Use full detection with data verification
            timestamp_data = self.timestamp_detector.detect_all_timestamp_columns(
                str(db_path),
                table_name,
                verify_data=True,
                sample_size=sample_size
            )
            
            for ts_col in timestamp_data:
                timestamp_columns.append(
                    TimestampColumnInfo(
                        name=ts_col['column_name'],
                        format=ts_col['format'],
                        sample_values=ts_col.get('sample_values', []),
                        parse_success_rate=ts_col.get('parse_success_rate', 0.0)
                    )
                )
        else:
            # Quick detection by name only
            candidate_columns = self.timestamp_detector.detect_timestamp_columns(
                table_name,
                columns
            )
            
            for col_name in candidate_columns:
                timestamp_columns.append(
                    TimestampColumnInfo(
                        name=col_name,
                        format='unknown',
                        sample_values=[],
                        parse_success_rate=0.0
                    )
                )
        
        # Get row count (optional, can be slow for large tables)
        row_count = None
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
            row_count = cursor.fetchone()[0]
            conn.close()
        except Exception:
            pass
        
        return TableInfo(
            name=table_name,
            columns=columns,
            timestamp_columns=timestamp_columns,
            row_count=row_count,
            supports_time_filtering=len(timestamp_columns) > 0
        )
    
    def get_gui_tab_name(
        self,
        database_name: str,
        display_name: Optional[str] = None
    ) -> str:
        """
        Map database name to GUI tab name.
        
        Uses the GUI_TAB_MAPPINGS dictionary to normalize database names
        to their corresponding GUI tab names. Falls back to display name
        or database name if no mapping is found.
        
        Args:
            database_name: Database filename (e.g., 'prefetch_data.db')
            display_name: Optional display name from DatabaseInfo
            
        Returns:
            GUI tab name (e.g., 'Prefetch')
        """
        # Try direct mapping with database name
        if database_name in self.GUI_TAB_MAPPINGS:
            return self.GUI_TAB_MAPPINGS[database_name]
        
        # Try mapping with display name
        if display_name and display_name in self.GUI_TAB_MAPPINGS:
            return self.GUI_TAB_MAPPINGS[display_name]
        
        # Try case-insensitive matching
        db_name_lower = database_name.lower()
        for key, value in self.GUI_TAB_MAPPINGS.items():
            if key.lower() == db_name_lower:
                return value
        
        # Fall back to display name or database name without extension
        if display_name:
            return display_name
        
        # Remove .db extension and return
        return database_name.replace('.db', '').replace('_', ' ').title()
    
    def get_databases_by_gui_tab(
        self,
        force_refresh: bool = False
    ) -> Dict[str, List[EnhancedDatabaseInfo]]:
        """
        Group databases by their GUI tab names.
        
        This is useful for consolidating multiple database files that map
        to the same GUI tab (e.g., 'prefetch_data.db' and 'Prefetch Files'
        both map to 'Prefetch').
        
        Args:
            force_refresh: Force re-discovery and bypass cache
            
        Returns:
            Dictionary mapping GUI tab names to lists of EnhancedDatabaseInfo
        """
        databases = self.discover_databases_with_metadata(force_refresh=force_refresh)
        
        grouped: Dict[str, List[EnhancedDatabaseInfo]] = {}
        
        for db in databases:
            tab_name = db.gui_tab_name
            if tab_name not in grouped:
                grouped[tab_name] = []
            grouped[tab_name].append(db)
        
        return grouped
    
    def get_database_by_name(
        self,
        database_name: str,
        force_refresh: bool = False
    ) -> Optional[EnhancedDatabaseInfo]:
        """
        Get enhanced information for a specific database.
        
        Args:
            database_name: Name of the database
            force_refresh: Force re-discovery and bypass cache
            
        Returns:
            EnhancedDatabaseInfo or None if not found
        """
        if not force_refresh and database_name in self.cache:
            return self.cache[database_name]
        
        databases = self.discover_databases_with_metadata(force_refresh=force_refresh)
        
        for db in databases:
            if db.name == database_name:
                return db
        
        return None
    
    def clear_cache(self):
        """Clear the metadata cache."""
        self.cache.clear()
        self.logger.debug("Cleared database metadata cache")
    
    def get_all_timestamp_columns(
        self,
        force_refresh: bool = False
    ) -> Dict[str, Dict[str, List[TimestampColumnInfo]]]:
        """
        Get all timestamp columns across all databases.
        
        Returns a nested dictionary structure:
        {
            'database_name': {
                'table_name': [TimestampColumnInfo, ...]
            }
        }
        
        Args:
            force_refresh: Force re-discovery and bypass cache
            
        Returns:
            Nested dictionary of timestamp columns
        """
        databases = self.discover_databases_with_metadata(force_refresh=force_refresh)
        
        result = {}
        
        for db in databases:
            if not db.accessible:
                continue
            
            db_timestamps = {}
            for table_name, table_info in db.tables.items():
                if table_info.timestamp_columns:
                    db_timestamps[table_name] = table_info.timestamp_columns
            
            if db_timestamps:
                result[db.name] = db_timestamps
        
        return result
    
    def supports_time_filtering(
        self,
        database_name: str,
        table_name: Optional[str] = None
    ) -> bool:
        """
        Check if a database or specific table supports time filtering.
        
        Args:
            database_name: Name of the database
            table_name: Optional table name to check specifically
            
        Returns:
            True if time filtering is supported, False otherwise
        """
        db_info = self.get_database_by_name(database_name)
        
        if not db_info or not db_info.accessible:
            return False
        
        if table_name:
            # Check specific table
            table_info = db_info.tables.get(table_name)
            return table_info.supports_time_filtering if table_info else False
        else:
            # Check if any table supports time filtering
            return db_info.supports_time_filtering()

    def close(self):
        """
        Close all open resources.
        """
        if hasattr(self, 'db_manager'):
            self.db_manager.close_all()
        self.clear_cache()
        self.logger.debug("Closed DatabaseDiscoveryManager resources")


# Example usage
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python database_discovery_manager.py <case_directory>")
        sys.exit(1)
    
    case_dir = sys.argv[1]
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    manager = DatabaseDiscoveryManager(case_dir)
    
    print(f"Discovering databases in: {case_dir}\n")
    
    databases = manager.discover_databases_with_metadata(verify_timestamps=True)
    
    print(f"Found {len(databases)} databases:\n")
    
    for db in databases:
        status = "✓" if db.accessible else "✗"
        time_filter = "🕐" if db.supports_time_filtering() else "○"
        
        print(f"{status} {time_filter} {db.gui_tab_name} ({db.name})")
        print(f"   Category: {db.category}")
        print(f"   Tables: {len(db.tables)}")
        
        if db.accessible and db.tables:
            for table_name, table_info in db.tables.items():
                if table_info.timestamp_columns:
                    print(f"     - {table_name}: {len(table_info.timestamp_columns)} timestamp columns")
                    for ts_col in table_info.timestamp_columns:
                        print(f"       • {ts_col.name} ({ts_col.format}, {ts_col.parse_success_rate:.0f}% success)")
        
        if db.error:
            print(f"   Error: {db.error}")
        
        print()
    
    # Show grouping by GUI tab
    print("\nDatabases grouped by GUI tab:")
    print("-" * 60)
    
    grouped = manager.get_databases_by_gui_tab()
    
    for tab_name, dbs in sorted(grouped.items()):
        accessible_dbs = [db for db in dbs if db.accessible]
        if accessible_dbs:
            print(f"\n{tab_name}:")
            for db in accessible_dbs:
                time_filter = "🕐" if db.supports_time_filtering() else "○"
                print(f"  {time_filter} {db.name}")
