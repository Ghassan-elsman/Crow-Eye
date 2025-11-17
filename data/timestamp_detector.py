"""
Timestamp detection module for identifying timestamp columns in database tables.

This module provides the TimestampDetector class for automatically detecting
timestamp columns based on column names and data sampling.
"""

import re
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional
from data.timestamp_parser import TimestampParser


class TimestampDetector:
    """
    Detects and identifies timestamp columns in database tables.
    
    Uses a combination of column name pattern matching and data sampling
    to identify columns that contain timestamp information.
    """
    
    # Common timestamp column name patterns (case-insensitive)
    # More specific patterns to avoid false positives
    TIMESTAMP_PATTERNS = [
        r'^.*timestamp.*$',
        r'^.*_time$',
        r'^.*_date$',
        r'^time_.*$',
        r'^date_.*$',
        r'^.*created.*$',
        r'^.*modified.*$',
        r'^.*accessed.*$',
        r'^.*updated.*$',
        r'^last_.*$',
        r'^first_.*$',
        r'^.*_when$',
        r'^when_.*$',
        r'^.*expire.*$',
        r'^.*birth.*$',
        r'^.*_start$',
        r'^start_.*$',
        r'^.*_end$',
        r'^end_.*$',
        r'^.*write_time.*$',
        r'^.*read_time.*$',
        r'^.*change_time.*$',
    ]
    
    # Patterns to exclude (columns that contain time-related words but aren't timestamps)
    EXCLUDE_PATTERNS = [
        r'.*cycle_time.*',  # CPU cycle time (numeric)
        r'.*execution_time.*',  # Execution duration (numeric)
        r'.*duration.*',  # Duration values (numeric)
        r'.*elapsed.*',  # Elapsed time (numeric)
        r'.*timeout.*',  # Timeout values (numeric)
        r'.*lifetime.*',  # Lifetime values (numeric)
        r'.*uptime.*',  # Uptime values (numeric)
        r'.*bytes.*',  # Byte counts
        r'.*num_.*',  # Numeric counters
        r'.*count.*',  # Counters
        r'.*operations.*',  # Operation counts
    ]
    
    def __init__(self):
        """Initialize the timestamp detector with a parser instance."""
        self.parser = TimestampParser()
        self._compiled_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.TIMESTAMP_PATTERNS
        ]
        self._exclude_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.EXCLUDE_PATTERNS
        ]
    
    def detect_timestamp_columns(
        self,
        table_name: str,
        columns: List[str]
    ) -> List[str]:
        """
        Identify timestamp columns based on name patterns.
        
        Args:
            table_name: Name of the database table
            columns: List of column names in the table
            
        Returns:
            List of column names that likely contain timestamps
        """
        timestamp_columns = []
        
        for column in columns:
            if self._matches_timestamp_pattern(column):
                timestamp_columns.append(column)
        
        return timestamp_columns
    
    def _matches_timestamp_pattern(self, column_name: str) -> bool:
        """
        Check if a column name matches any timestamp pattern.
        
        Args:
            column_name: Name of the column
            
        Returns:
            True if the column name matches a timestamp pattern
        """
        # First check if it matches an exclude pattern
        for pattern in self._exclude_patterns:
            if pattern.match(column_name):
                return False
        
        # Then check if it matches a timestamp pattern
        for pattern in self._compiled_patterns:
            if pattern.match(column_name):
                return True
        return False
    
    def analyze_column_data(
        self,
        db_path: str,
        table_name: str,
        column_name: str,
        sample_size: int = 100
    ) -> Dict[str, Any]:
        """
        Analyze sample data to determine timestamp format and validity.
        
        Samples data from the specified column and attempts to parse it
        to determine if it contains valid timestamp data and what format.
        
        Args:
            db_path: Path to the SQLite database file
            table_name: Name of the table
            column_name: Name of the column to analyze
            sample_size: Number of rows to sample (default: 100)
            
        Returns:
            Dictionary containing:
                - 'is_timestamp': bool (True if column contains valid timestamps)
                - 'format': str (detected format: 'iso8601', 'unix', 'filetime', 'datetime', 'mixed', etc.)
                - 'sample_values': List[str] (sample of original values)
                - 'parse_success_rate': float (percentage of successfully parsed values)
                - 'parsed_samples': List[datetime] (successfully parsed datetime objects)
        """
        result = {
            'is_timestamp': False,
            'format': None,
            'sample_values': [],
            'parse_success_rate': 0.0,
            'parsed_samples': []
        }
        
        try:
            # Connect to database and sample data
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get sample data (skip NULL values)
            query = f"""
                SELECT "{column_name}"
                FROM "{table_name}"
                WHERE "{column_name}" IS NOT NULL
                LIMIT {sample_size}
            """
            
            cursor.execute(query)
            rows = cursor.fetchall()
            conn.close()
            
            if not rows:
                return result
            
            # Extract values
            sample_values = [row[0] for row in rows if row[0] is not None]
            result['sample_values'] = [str(v)[:100] for v in sample_values[:10]]  # Store first 10 for reference
            
            if not sample_values:
                return result
            
            # Try parsing each value
            parsed_count = 0
            parsed_samples = []
            format_counts = {}
            
            # Additional validation: check if values look like reasonable timestamps
            min_reasonable_year = 1990
            max_reasonable_year = 2100
            
            for value in sample_values:
                parsed = self.parser.parse_timestamp(value)
                if parsed:
                    # Validate that the parsed timestamp is reasonable
                    if min_reasonable_year <= parsed.year <= max_reasonable_year:
                        parsed_count += 1
                        parsed_samples.append(parsed)
                        
                        # Track format distribution
                        fmt = self.parser.detect_format(value)
                        if fmt:
                            format_counts[fmt] = format_counts.get(fmt, 0) + 1
            
            # Calculate success rate
            total_samples = len(sample_values)
            success_rate = (parsed_count / total_samples) * 100 if total_samples > 0 else 0.0
            
            result['parse_success_rate'] = success_rate
            result['parsed_samples'] = parsed_samples[:10]  # Store first 10 parsed samples
            
            # Determine if this is a timestamp column (>= 80% success rate)
            if success_rate >= 80.0:
                result['is_timestamp'] = True
                
                # Determine primary format
                if format_counts:
                    primary_format = max(format_counts, key=format_counts.get)
                    
                    # Check if mixed formats
                    if len(format_counts) > 1:
                        # If multiple formats but one is dominant (>80%), use that
                        dominant_count = format_counts[primary_format]
                        if (dominant_count / parsed_count) >= 0.8:
                            result['format'] = primary_format
                        else:
                            result['format'] = 'mixed'
                    else:
                        result['format'] = primary_format
        
        except sqlite3.Error as e:
            # Database error - log but don't fail
            result['error'] = str(e)
        except Exception as e:
            # Other errors
            result['error'] = str(e)
        
        return result
    
    def detect_all_timestamp_columns(
        self,
        db_path: str,
        table_name: str,
        verify_data: bool = True,
        sample_size: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Detect all timestamp columns in a table with optional data verification.
        
        Args:
            db_path: Path to the SQLite database file
            table_name: Name of the table
            verify_data: Whether to verify by sampling data (default: True)
            sample_size: Number of rows to sample for verification
            
        Returns:
            List of dictionaries containing timestamp column information:
                - 'column_name': str
                - 'is_timestamp': bool
                - 'format': str
                - 'parse_success_rate': float
                - 'sample_values': List[str]
        """
        timestamp_columns = []
        
        try:
            # Connect to database and get column names
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get table schema
            cursor.execute(f'PRAGMA table_info("{table_name}")')
            columns_info = cursor.fetchall()
            conn.close()
            
            if not columns_info:
                return timestamp_columns
            
            # Extract column names
            column_names = [col[1] for col in columns_info]
            
            # Detect timestamp columns by name
            candidate_columns = self.detect_timestamp_columns(table_name, column_names)
            
            # Verify with data sampling if requested
            if verify_data and candidate_columns:
                for column_name in candidate_columns:
                    analysis = self.analyze_column_data(
                        db_path,
                        table_name,
                        column_name,
                        sample_size
                    )
                    
                    if analysis['is_timestamp']:
                        timestamp_columns.append({
                            'column_name': column_name,
                            'is_timestamp': True,
                            'format': analysis['format'],
                            'parse_success_rate': analysis['parse_success_rate'],
                            'sample_values': analysis['sample_values']
                        })
            else:
                # Just return candidates without verification
                for column_name in candidate_columns:
                    timestamp_columns.append({
                        'column_name': column_name,
                        'is_timestamp': True,  # Assumed based on name
                        'format': 'unknown',
                        'parse_success_rate': None,
                        'sample_values': []
                    })
        
        except sqlite3.Error as e:
            # Database error - return empty list
            pass
        except Exception as e:
            # Other errors - return empty list
            pass
        
        return timestamp_columns
    
    def get_table_columns(self, db_path: str, table_name: str) -> List[str]:
        """
        Get all column names for a table.
        
        Args:
            db_path: Path to the SQLite database file
            table_name: Name of the table
            
        Returns:
            List of column names
        """
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(f'PRAGMA table_info("{table_name}")')
            columns_info = cursor.fetchall()
            conn.close()
            
            return [col[1] for col in columns_info]
        except Exception:
            return []
    
    def get_all_tables(self, db_path: str) -> List[str]:
        """
        Get all table names in a database.
        
        Args:
            db_path: Path to the SQLite database file
            
        Returns:
            List of table names
        """
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()
            
            return tables
        except Exception:
            return []
    
    def analyze_database(
        self,
        db_path: str,
        verify_data: bool = True,
        sample_size: int = 100
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Analyze all tables in a database for timestamp columns.
        
        Args:
            db_path: Path to the SQLite database file
            verify_data: Whether to verify by sampling data
            sample_size: Number of rows to sample for verification
            
        Returns:
            Dictionary mapping table names to lists of timestamp column info
        """
        result = {}
        
        tables = self.get_all_tables(db_path)
        
        for table_name in tables:
            timestamp_columns = self.detect_all_timestamp_columns(
                db_path,
                table_name,
                verify_data,
                sample_size
            )
            
            if timestamp_columns:
                result[table_name] = timestamp_columns
        
        return result


# Example usage
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python timestamp_detector.py <database_path>")
        sys.exit(1)
    
    db_path = sys.argv[1]
    
    detector = TimestampDetector()
    
    print(f"Analyzing database: {db_path}\n")
    
    results = detector.analyze_database(db_path, verify_data=True, sample_size=50)
    
    if not results:
        print("No timestamp columns detected.")
    else:
        for table_name, columns in results.items():
            print(f"\nTable: {table_name}")
            print("-" * 60)
            
            for col_info in columns:
                print(f"  Column: {col_info['column_name']}")
                print(f"    Format: {col_info['format']}")
                print(f"    Success Rate: {col_info['parse_success_rate']:.1f}%")
                
                if col_info['sample_values']:
                    print(f"    Sample: {col_info['sample_values'][0]}")
                print()
