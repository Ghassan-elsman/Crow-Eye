"""
Offline Windows Event Log Parser (offline_WinLog_Claw.py)

This module parses Windows Event Log (.evtx) files offline without requiring
Windows API access. It creates a Log_Claw.db database with identical schema
to the live WinLog-Claw parser for compatibility with forensic timeline tools.

Requirements: 1.1, 2.1, 2.2, 8.1
"""

import sqlite3
import logging
import os
from datetime import datetime
from typing import Optional, Tuple, Iterator, Dict, Any

try:
    import Evtx.Evtx as evtx
    import Evtx.Views as e_views
    from Evtx.Evtx import ParseException, InvalidRecordException
except ImportError:
    print("ERROR: python-evtx library not found. Install with: pip install python-evtx")
    raise

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('offline_winlog_claw.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Database schema constants matching live WinLog-Claw
# These schemas must match exactly for compatibility with forensic timeline tools

SYSTEM_LOGS_SCHEMA = """CREATE TABLE IF NOT EXISTS SystemLogs (
    EventID INTEGER,
    Source TEXT,
    EventType TEXT,
    Category TEXT,
    EventTimestampUTC TEXT,
    ComputerName TEXT,
    User TEXT,
    Keywords TEXT,
    EventDescription TEXT
)"""

APPLICATION_LOGS_SCHEMA = """CREATE TABLE IF NOT EXISTS ApplicationLogs (
    EventID INTEGER,
    Source TEXT,
    EventType TEXT,
    Category TEXT,
    EventTimestampUTC TEXT,
    ComputerName TEXT,
    User TEXT,
    Keywords TEXT,
    EventDescription TEXT
)"""

SECURITY_LOGS_SCHEMA = """CREATE TABLE IF NOT EXISTS SecurityLogs (
    EventID INTEGER,
    Source TEXT,
    EventType TEXT,
    Category TEXT,
    EventTimestampUTC TEXT,
    ComputerName TEXT,
    User TEXT,
    Keywords TEXT,
    TaskCategory TEXT,
    EventDescription TEXT
)"""

# Table name mapping for different log types
LOG_TYPE_TABLE_MAP = {
    'system': 'SystemLogs',
    'application': 'ApplicationLogs',
    'security': 'SecurityLogs'
}


class EVTXParser:
    """
    Parser for Windows Event Log (.evtx) files using python-evtx library.
    
    This class extracts event data from EVTX files without requiring Windows API access.
    Requirements: 1.1, 1.5
    """
    
    def __init__(self, evtx_path: str):
        """
        Initialize parser with path to .evtx file.
        
        Args:
            evtx_path: Path to the .evtx file to parse
        """
        self.evtx_path = evtx_path
        self.log_type = self._determine_log_type()
        logger.debug(f"Initialized EVTXParser for {evtx_path} (type: {self.log_type})")
    
    def _determine_log_type(self) -> str:
        """
        Determine log type (System, Application, Security) from filename.
        
        Returns:
            Log type as lowercase string ('system', 'application', 'security')
        """
        filename = os.path.basename(self.evtx_path).lower()
        
        if 'system' in filename:
            return 'system'
        elif 'application' in filename:
            return 'application'
        elif 'security' in filename:
            return 'security'
        else:
            # Default to system if type cannot be determined
            logger.warning(f"Could not determine log type from filename: {filename}, defaulting to 'system'")
            return 'system'
    
    def parse_events(self) -> Iterator[Dict[str, Any]]:
        """
        Parse all events from the EVTX file.
        
        Yields:
            Dictionary containing event data with all required fields:
            - EventID
            - Source
            - EventType
            - Category
            - EventTimestampUTC
            - ComputerName
            - User
            - Keywords
            - EventDescription
        
        Requirements: 1.1, 1.5, 1.6, 7.1
        """
        try:
            with evtx.Evtx(self.evtx_path) as log:
                for record in log.records():
                    try:
                        event_data = self._extract_event_data(record)
                        if event_data:
                            yield event_data
                    except Exception as e:
                        logger.warning(f"Failed to parse event record: {e}")
                        continue
        except (ParseException, InvalidRecordException) as e:
            # Handle python-evtx specific parsing exceptions (Requirement 1.6, 7.1)
            logger.error(f"EVTX parsing exception for {self.evtx_path}: {type(e).__name__} - {str(e)}")
            raise
        except Exception as e:
            # Handle other exceptions (file not found, permission errors, etc.)
            logger.error(f"Failed to open EVTX file {self.evtx_path}: {type(e).__name__} - {str(e)}")
            raise
    
    def _extract_event_data(self, record) -> Optional[Dict[str, Any]]:
        """
        Extract required fields from event record with validation.
        
        Args:
            record: Event record from python-evtx library
        
        Returns:
            Dictionary with extracted event data, or None if extraction fails
        
        Requirements: 1.5, 9.1, 9.3
        """
        try:
            # Get XML representation of the event
            xml_string = record.xml()
            
            # Parse XML to extract fields
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml_string)
            
            # Define XML namespace
            ns = {'evt': 'http://schemas.microsoft.com/win/2004/08/events/event'}
            
            # Extract System section fields
            system = root.find('evt:System', ns)
            if system is None:
                logger.warning("Event record missing System section")
                return None
            
            # Extract EventID
            event_id_elem = system.find('evt:EventID', ns)
            event_id = event_id_elem.text if event_id_elem is not None else None
            
            # Extract Provider (Source)
            provider_elem = system.find('evt:Provider', ns)
            source = provider_elem.get('Name') if provider_elem is not None else None
            
            # Extract Level (EventType)
            level_elem = system.find('evt:Level', ns)
            level = level_elem.text if level_elem is not None else None
            event_type = self._map_level_to_event_type(level)
            
            # Extract Task (Category)
            task_elem = system.find('evt:Task', ns)
            category = task_elem.text if task_elem is not None else None
            
            # Extract TimeCreated (EventTimestampUTC)
            time_elem = system.find('evt:TimeCreated', ns)
            timestamp_utc = None
            if time_elem is not None:
                system_time = time_elem.get('SystemTime')
                if system_time:
                    timestamp_utc = self._convert_timestamp_to_utc(system_time)
            
            # Extract Computer (ComputerName)
            computer_elem = system.find('evt:Computer', ns)
            computer_name = computer_elem.text if computer_elem is not None else None
            
            # Extract Security UserID (User)
            security_elem = system.find('evt:Security', ns)
            user = None
            if security_elem is not None:
                user = security_elem.get('UserID')
            
            # Extract Keywords
            keywords_elem = system.find('evt:Keywords', ns)
            keywords = keywords_elem.text if keywords_elem is not None else None
            
            # Extract EventData for description
            event_description = self._extract_event_description(root, ns)
            
            # Build event data dictionary
            event_data = {
                'EventID': event_id,
                'Source': source,
                'EventType': event_type,
                'Category': category,
                'EventTimestampUTC': timestamp_utc,
                'ComputerName': computer_name,
                'User': user,
                'Keywords': keywords,
                'EventDescription': event_description
            }
            
            # Validate the extracted data (Requirements 9.1, 9.3)
            if not self._validate_event_data(event_data):
                return None
            
            return event_data
            
        except Exception as e:
            logger.warning(f"Failed to extract event data: {e}")
            return None
    
    def _validate_event_data(self, event_data: Dict[str, Any]) -> bool:
        """
        Validate extracted event data.

        Validates:
        - Timestamp format (Requirement 9.1)
        - Required fields are non-null (Requirement 9.3)

        Args:
            event_data: Dictionary with extracted event data

        Returns:
            True if validation passes, False otherwise

        Requirements: 9.1, 9.3
        """
        # Define required fields that must be non-null
        required_fields = ['EventID', 'EventTimestampUTC']

        # Check required fields are non-null (Requirement 9.3)
        for field in required_fields:
            if event_data.get(field) is None:
                logger.warning(f"Validation failed: Required field '{field}' is null")
                return False

        # Validate timestamp format (Requirement 9.1)
        timestamp = event_data.get('EventTimestampUTC')
        if timestamp and not self._validate_timestamp_format(timestamp):
            logger.warning(f"Validation failed: Invalid timestamp format '{timestamp}'")
            return False

        return True

    def _validate_timestamp_format(self, timestamp_str: str) -> bool:
        """
        Validate timestamp format.

        Accepts formats:
        - YYYY-MM-DD HH:MM:SS.mmm (standard format)
        - ISO 8601 formats (fallback from conversion failures)

        Args:
            timestamp_str: Timestamp string to validate

        Returns:
            True if format is valid, False otherwise

        Requirements: 9.1
        """
        if not timestamp_str or not isinstance(timestamp_str, str):
            return False

        # Try standard format: YYYY-MM-DD HH:MM:SS.mmm
        try:
            datetime.strptime(timestamp_str[:23], '%Y-%m-%d %H:%M:%S.%f')
            return True
        except ValueError:
            pass

        # Try ISO 8601 format (fallback from conversion failures)
        try:
            # Handle various ISO 8601 formats
            if 'T' in timestamp_str:
                # Remove timezone info for parsing
                ts = timestamp_str.replace('Z', '+00:00')
                datetime.fromisoformat(ts)
                return True
        except (ValueError, AttributeError):
            pass

        return False
    
    def _map_level_to_event_type(self, level: Optional[str]) -> Optional[str]:
        """
        Map Windows event level to event type string.
        
        Args:
            level: Event level as string (0-5)
        
        Returns:
            Event type string (Information, Warning, Error, etc.)
        """
        if level is None:
            return None
        
        level_map = {
            '0': 'Information',
            '1': 'Critical',
            '2': 'Error',
            '3': 'Warning',
            '4': 'Information',
            '5': 'Verbose'
        }
        
        return level_map.get(level, 'Information')
    
    def _convert_timestamp_to_utc(self, timestamp_str: str) -> str:
        """
        Convert timestamp to UTC format.
        
        Args:
            timestamp_str: Timestamp string from event record
        
        Returns:
            Formatted UTC timestamp string
        
        Requirements: 1.5
        """
        try:
            # Parse ISO 8601 format timestamp
            # Example: 2024-01-15T10:30:45.123456Z
            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            
            # Format as string for database storage
            return dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]  # Trim to milliseconds
            
        except Exception as e:
            logger.warning(f"Failed to parse timestamp '{timestamp_str}': {e}")
            # Return original string if parsing fails
            return timestamp_str
    
    def _extract_event_description(self, root: Any, ns: Dict[str, str]) -> Optional[str]:
        """
        Extract event description from EventData section.
        
        Args:
            root: XML root element
            ns: XML namespace dictionary
        
        Returns:
            Event description string, or None if not available
        """
        import xml.etree.ElementTree as ET
        
        try:
            # Try to extract EventData
            event_data = root.find('evt:EventData', ns)
            if event_data is not None:
                # Collect all Data elements
                data_items = []
                for data_elem in event_data.findall('evt:Data', ns):
                    name = data_elem.get('Name', '')
                    value = data_elem.text or ''
                    if name:
                        data_items.append(f"{name}: {value}")
                    else:
                        data_items.append(value)
                
                if data_items:
                    return '; '.join(data_items)
            
            # Try UserData as fallback
            user_data = root.find('evt:UserData', ns)
            if user_data is not None:
                # Convert UserData to string representation
                return ET.tostring(user_data, encoding='unicode', method='text').strip()
            
            return None
            
        except Exception as e:
            logger.warning(f"Failed to extract event description: {e}")
            return None


def create_database(case_path: Optional[str] = None) -> Tuple[sqlite3.Connection, sqlite3.Cursor, str]:
    """
    Create Log_Claw.db database with schema matching live WinLog-Claw parser.
    
    Args:
        case_path: Optional path to case directory. If provided, database will be
                  created in case_path/live_acquisition/Log_Claw.db
    
    Returns:
        Tuple of (connection, cursor, db_path)
    
    Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 7.5
    """
    db_path = 'Log_Claw.db'
    
    if case_path:
        artifacts_dir = os.path.join(case_path, 'Target_Artifacts')
        if os.path.exists(artifacts_dir):
            db_path = os.path.join(artifacts_dir, 'Log_Claw.db')
        else:
            logger.warning(f"Target_Artifacts directory not found in {case_path}, using current directory")
    
    logger.info(f"Creating database at: {db_path}")
    
    conn = None
    cursor = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Drop existing tables to ensure clean state
        cursor.execute('DROP TABLE IF EXISTS SystemLogs')
        cursor.execute('DROP TABLE IF EXISTS ApplicationLogs')
        cursor.execute('DROP TABLE IF EXISTS SecurityLogs')
        
        # Create tables with exact schema from live parser
        cursor.execute(SYSTEM_LOGS_SCHEMA)
        cursor.execute(APPLICATION_LOGS_SCHEMA)
        cursor.execute(SECURITY_LOGS_SCHEMA)
        
        conn.commit()
        logger.info("Database schema created successfully")
        
        return conn, cursor, db_path
        
    except sqlite3.Error as e:
        # Log detailed database error information (Requirement 7.5)
        logger.error(f"Database creation failed: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.error(f"Database path: {db_path}")
        
        # Close connection if it was opened
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        
        # Clean up partial database file on failure (Requirement 7.5)
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
                logger.info(f"Cleaned up partial database file: {db_path}")
            except OSError as cleanup_error:
                logger.warning(f"Failed to clean up partial database file: {cleanup_error}")
        
        raise
    except Exception as e:
        # Handle non-SQLite exceptions (e.g., permission errors, disk full)
        logger.error(f"Unexpected error during database creation: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.error(f"Database path: {db_path}")
        
        # Close connection if it was opened
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        
        # Clean up partial database file on failure (Requirement 7.5)
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
                logger.info(f"Cleaned up partial database file: {db_path}")
            except OSError as cleanup_error:
                logger.warning(f"Failed to clean up partial database file: {cleanup_error}")
        
        raise


def process_evtx_files(evtx_dir: str, conn: sqlite3.Connection, cursor: sqlite3.Cursor) -> Dict[str, int]:
    """
    Process all .evtx files in the specified directory with progress reporting.
    
    Args:
        evtx_dir: Directory containing .evtx files to parse
        conn: Database connection
        cursor: Database cursor
    
    Returns:
        Dictionary with processing statistics:
        - total_files: Total number of .evtx files found
        - successful: Number of successfully processed files
        - failed: Number of files that failed to process
        - total_events: Total number of events parsed
        - processing_time: Total processing time in seconds
    
    Requirements: 1.7, 6.1, 6.3, 6.4, 6.5, 7.2, 7.3
    """
    start_time = datetime.now()
    
    stats = {
        'total_files': 0,
        'successful': 0,
        'failed': 0,
        'total_events': 0,
        'processing_time': 0.0
    }
    
    # Find all .evtx files in the directory
    evtx_files = []
    if os.path.isdir(evtx_dir):
        for filename in os.listdir(evtx_dir):
            if filename.lower().endswith('.evtx'):
                evtx_files.append(os.path.join(evtx_dir, filename))
    else:
        logger.error(f"Directory not found: {evtx_dir}")
        return stats
    
    stats['total_files'] = len(evtx_files)
    logger.info(f"Found {stats['total_files']} .evtx files to process")
    
    # Process each file sequentially with progress reporting
    for index, evtx_file in enumerate(evtx_files, start=1):
        try:
            # Print current file being processed (Requirement 6.3)
            filename = os.path.basename(evtx_file)
            logger.info(f"Processing file {index}/{stats['total_files']}: {filename}")
            
            # Print completion percentage (Requirement 6.3)
            completion_pct = (index - 1) / stats['total_files'] * 100
            print(f"Progress: {completion_pct:.1f}% complete ({index-1}/{stats['total_files']} files processed)")
            
            # Check file existence before parsing (Requirement 7.4)
            if not os.path.exists(evtx_file):
                stats['failed'] += 1
                logger.error(f"File not found: {evtx_file}")
                logger.error(f"The file '{filename}' does not exist or is inaccessible")
                continue
            
            # Check if file is accessible (readable)
            if not os.path.isfile(evtx_file):
                stats['failed'] += 1
                logger.error(f"Not a valid file: {evtx_file}")
                logger.error(f"The path '{filename}' exists but is not a regular file")
                continue
            
            # Create parser for this file
            parser = EVTXParser(evtx_file)
            
            # Determine target table based on log type
            table_name = LOG_TYPE_TABLE_MAP.get(parser.log_type, 'SystemLogs')
            
            # Parse events and insert into database
            event_count = 0
            for event_data in parser.parse_events():
                try:
                    # Insert event into appropriate table
                    insert_event(cursor, table_name, event_data)
                    event_count += 1
                except sqlite3.Error as e:
                    # Handle database errors during insertion (Requirement 7.5)
                    logger.warning(f"Database error inserting event: {type(e).__name__} - {str(e)}")
                    continue
                except Exception as e:
                    logger.warning(f"Failed to insert event: {e}")
                    continue
            
            # Commit after each file
            try:
                conn.commit()
            except sqlite3.Error as e:
                # Handle database commit errors (Requirement 7.5)
                logger.error(f"Database commit error for {filename}: {type(e).__name__} - {str(e)}")
                stats['failed'] += 1
                continue
            
            stats['successful'] += 1
            stats['total_events'] += event_count
            logger.info(f"Successfully processed {filename}: {event_count} events")
            
        except (ParseException, InvalidRecordException) as e:
            # Handle python-evtx parsing exceptions specifically (Requirement 1.6, 7.1)
            stats['failed'] += 1
            filename = os.path.basename(evtx_file)
            logger.error(f"EVTX parsing error in {filename}: {type(e).__name__} - {str(e)}")
            logger.error(f"File path: {evtx_file}")
            # Continue processing remaining files (Requirement 6.5, 7.4)
            continue
        except Exception as e:
            # Continue processing on other errors (Requirement 6.5)
            stats['failed'] += 1
            filename = os.path.basename(evtx_file)
            logger.error(f"Failed to process {filename}: {type(e).__name__} - {str(e)}")
            logger.error(f"File path: {evtx_file}")
            continue
    
    # Calculate processing time
    end_time = datetime.now()
    stats['processing_time'] = (end_time - start_time).total_seconds()
    
    # Print final completion percentage
    print(f"Progress: 100.0% complete ({stats['total_files']}/{stats['total_files']} files processed)")
    
    return stats


def insert_event(cursor: sqlite3.Cursor, table_name: str, event_data: Dict[str, Any]):
    """
    Insert a single event record into the specified table with error handling.
    
    Args:
        cursor: Database cursor
        table_name: Name of the table (SystemLogs, ApplicationLogs, or SecurityLogs)
        event_data: Dictionary containing event data
    
    Raises:
        sqlite3.Error: If database insertion fails
    
    Requirements: 1.2, 1.3, 1.4, 1.5, 7.5
    """
    try:
        # Handle SecurityLogs table which has TaskCategory instead of Category
        if table_name == 'SecurityLogs':
            sql = """INSERT INTO SecurityLogs 
                     (EventID, Source, EventType, Category, EventTimestampUTC, 
                      ComputerName, User, Keywords, TaskCategory, EventDescription)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
            
            cursor.execute(sql, (
                event_data.get('EventID'),
                event_data.get('Source'),
                event_data.get('EventType'),
                event_data.get('Category'),
                event_data.get('EventTimestampUTC'),
                event_data.get('ComputerName'),
                event_data.get('User'),
                event_data.get('Keywords'),
                event_data.get('Category'),  # TaskCategory uses same value as Category
                event_data.get('EventDescription')
            ))
        else:
            sql = f"""INSERT INTO {table_name} 
                      (EventID, Source, EventType, Category, EventTimestampUTC, 
                       ComputerName, User, Keywords, EventDescription)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""
            
            cursor.execute(sql, (
                event_data.get('EventID'),
                event_data.get('Source'),
                event_data.get('EventType'),
                event_data.get('Category'),
                event_data.get('EventTimestampUTC'),
                event_data.get('ComputerName'),
                event_data.get('User'),
                event_data.get('Keywords'),
                event_data.get('EventDescription')
            ))
    except sqlite3.Error as e:
        # Log detailed database error information (Requirement 7.5)
        logger.error(f"Database insertion error: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.error(f"Table: {table_name}")
        logger.error(f"Event ID: {event_data.get('EventID')}")
        logger.error(f"Timestamp: {event_data.get('EventTimestampUTC')}")
        raise


def main(evtx_dir: Optional[str] = None, case_path: Optional[str] = None):
    """
    Main entry point for offline event log parsing.
    
    Args:
        evtx_dir: Directory containing .evtx files to parse
        case_path: Path where output database should be created
                  If None, creates Log_Claw.db in current directory
    
    Returns:
        Dictionary with parsing results:
        - success: True if parsing succeeded, False otherwise
        - records: Number of events parsed
        - output_path: Path to output database
        - error: Error message if success=False (optional)
    
    Requirements: 8.3, 8.6, 8.7, 1.2, 2.2
    """
    logger.info("Starting offline Windows Event Log parsing")
    logger.info(f"EVTX directory: {evtx_dir}")
    logger.info(f"Case path: {case_path}")
    
    # Initialize counter for total events parsed
    total_events = 0
    
    # Wrap main parsing logic in try-except to return error dict on failure
    try:
        # Create database
        try:
            conn, cursor, db_path = create_database(case_path)
        except Exception as e:
            logger.error(f"Failed to create database: {e}")
            return {'success': False, 'records': 0, 'error': f"Database creation failed: {str(e)}"}
        
        # Process EVTX files if directory provided
        if evtx_dir:
            # Check if directory exists (early exit path)
            if not os.path.exists(evtx_dir):
                conn.close()
                return {'success': False, 'records': 0, 'error': f"EVTX directory not found: {evtx_dir}"}
            
            if not os.path.isdir(evtx_dir):
                conn.close()
                return {'success': False, 'records': 0, 'error': f"EVTX path is not a directory: {evtx_dir}"}
            
            stats = process_evtx_files(evtx_dir, conn, cursor)
            
            # Increment counter with total events from all EVTX files
            total_events = stats['total_events']
            
            # Generate summary report with statistics (Requirements 6.4, 7.2, 7.3)
            logger.info("=" * 60)
            logger.info("PROCESSING SUMMARY REPORT")
            logger.info("=" * 60)
            logger.info(f"  Total files found:       {stats['total_files']}")
            logger.info(f"  Successfully processed:  {stats['successful']}")
            logger.info(f"  Failed:                  {stats['failed']}")
            logger.info(f"  Total events parsed:     {stats['total_events']}")
            logger.info(f"  Processing time:         {stats['processing_time']:.2f} seconds")
            logger.info("=" * 60)
        else:
            logger.warning("No EVTX directory provided, database created but no files processed")
        
        # Commit and close database connection (Requirement 8.3)
        try:
            conn.commit()
            logger.info("Database committed successfully")
        except sqlite3.Error as e:
            logger.error(f"Failed to commit database: {e}")
            return {'success': False, 'records': 0, 'error': f"Database commit failed: {str(e)}"}
        finally:
            conn.close()
            logger.info("Database connection closed")
        
        # Print completion message with database path (Requirements 8.6, 8.7)
        print(f"\nEvent log parsing completed successfully!")
        print(f"Database created at: {db_path}")
        logger.info(f"Event log parsing completed. Database created at: {db_path}")
        
        # Return success dict with total events and database path
        return {'success': True, 'records': total_events, 'output_path': db_path}
        
    except Exception as e:
        # Catch all exceptions and return error dict
        logger.error(f"Unexpected error during EVTX parsing: {type(e).__name__} - {str(e)}")
        return {'success': False, 'records': 0, 'error': f"EVTX parsing failed: {str(e)}"}


if __name__ == "__main__":
    # Example usage
    main()
