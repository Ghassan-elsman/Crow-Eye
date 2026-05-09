"""
IOC Parser module for the Dynamic Linking Intelligence Engine.

This module provides parsing functionality for IOC (Indicators of Compromise) files
in CSV and JSON formats, supporting configurable field mapping and various formats.
"""

import csv
import json
import os
from typing import List, Tuple, Optional


class IOCParsing:
    """
    Parser for IOC files containing value-key mapping pairs.
    
    Supports CSV and JSON formats with configurable field mapping.
    Handles various delimiters for CSV and different JSON structures.
    """
    
    def __init__(self):
        """Initialize the IOC parser."""
        pass
    
    def parse_csv(self, file_path: str, value_col: str = 'value', key_col: str = 'key') -> List[Tuple[str, str]]:
        """
        Parse CSV file and extract value-key mapping pairs.
        
        Args:
            file_path: Path to CSV file
            value_col: Name of column containing values (default: 'value')
            key_col: Name of column containing keys (default: 'key')
        
        Returns:
            List of tuples (value, key) extracted from the CSV file
        
        Raises:
            FileNotFoundError: If the file does not exist
            ValueError: If the file is empty, has no data rows, or cannot be parsed
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Check if file is empty
        if os.path.getsize(file_path) == 0:
            raise ValueError(f"CSV file is empty: {file_path}")
        
        mappings = []
        
        # Try different encodings
        encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', newline='', encoding=encoding) as f:
                    # Try to detect delimiter
                    sample = f.read(4096)
                    f.seek(0)
                    
                    # Detect delimiter
                    try:
                        dialect = csv.Sniffer().sniff(sample, delimiters=',;:\t|')
                    except csv.Error:
                        # Use default comma delimiter
                        dialect = csv.excel
                    
                    reader = csv.DictReader(f, dialect=dialect)
                    
                    for row in reader:
                        value = row.get(value_col, '').strip() if row.get(value_col) else ''
                        key = row.get(key_col, '').strip() if row.get(key_col) else ''
                        
                        # Skip rows with missing values or keys
                        if value and key:
                            mappings.append((value, key))
                    
                    # Check if we got any data
                    if not mappings:
                        raise ValueError(f"CSV file has no valid data rows: {file_path}")
                    
                    return mappings
                    
            except ValueError:
                # Re-raise ValueError (empty file or no data)
                raise
            except UnicodeDecodeError:
                continue
            except Exception as e:
                # Try fallback with default delimiter
                try:
                    with open(file_path, 'r', newline='', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        
                        for row in reader:
                            value = row.get(value_col, '').strip() if row.get(value_col) else ''
                            key = row.get(key_col, '').strip() if row.get(key_col) else ''
                            
                            if value and key:
                                mappings.append((value, key))
                        
                        if not mappings:
                            raise ValueError(f"CSV file has no valid data rows: {file_path}")
                        
                        return mappings
                except ValueError:
                    raise
                except Exception:
                    continue
        
        raise ValueError(f"Could not parse CSV file: {file_path}")
    
    def parse_json(self, file_path: str, value_key: str = 'value', key_key: str = 'key') -> List[Tuple[str, str]]:
        """
        Parse JSON file and extract value-key mapping pairs.
        
        Supports two formats:
        1. Array of objects: [{"value": "v1", "key": "k1"}, ...]
        2. Key-value object: {"v1": "k1", "v2": "k2", ...}
        
        Args:
            file_path: Path to JSON file
            value_key: Key name for values in object format (default: 'value')
            key_key: Key name for keys in object format (default: 'key')
        
        Returns:
            List of tuples (value, key) extracted from the JSON file
        
        Raises:
            FileNotFoundError: If the file does not exist
            json.JSONDecodeError: If the file cannot be parsed as JSON
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        mappings = []
        last_error = None
        
        # Try different encodings
        encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    data = json.load(f)
                    
                    if isinstance(data, list):
                        # Array of objects format
                        for item in data:
                            if isinstance(item, dict):
                                value = item.get(value_key, '')
                                key = item.get(key_key, '')
                                
                                # Handle non-string values
                                if isinstance(value, (dict, list)):
                                    continue  # Skip nested objects
                                if isinstance(key, (dict, list)):
                                    continue  # Skip nested objects
                                
                                value = str(value).strip() if value else ''
                                key = str(key).strip() if key else ''
                                
                                if value and key:
                                    mappings.append((value, key))
                    
                    elif isinstance(data, dict):
                        # Key-value object format
                        for value, key in data.items():
                            # Skip if key or value is a nested object
                            if isinstance(value, (dict, list)) or isinstance(key, (dict, list)):
                                continue
                            
                            value = str(value).strip() if value else ''
                            key = str(key).strip() if key else ''
                            
                            if value and key:
                                mappings.append((value, key))
                    
                    # Return empty list for empty arrays/objects (valid JSON)
                    return mappings
                    
            except UnicodeDecodeError:
                continue
            except json.JSONDecodeError as e:
                last_error = e
                continue
        
        # If we got here, all encodings failed
        if last_error:
            raise last_error
        raise json.JSONDecodeError(f"Could not parse JSON file: {file_path}", "", 0)
    
    def validate_csv_format(self, file_path: str) -> Tuple[bool, str]:
        """
        Validate that a file is a valid CSV with expected structure.
        
        Args:
            file_path: Path to file to validate
        
        Returns:
            Tuple of (is_valid, error_message)
            - is_valid: True if file is valid CSV, False otherwise
            - error_message: Empty string if valid, error description otherwise
        """
        if not os.path.exists(file_path):
            return False, f"File not found: {file_path}"
        
        try:
            # Check file is not empty
            if os.path.getsize(file_path) == 0:
                return False, "File is empty"
            
            # Try to read and parse as CSV
            with open(file_path, 'r', encoding='utf-8') as f:
                # Read first line to check for headers
                first_line = f.readline().strip()
                
                if not first_line:
                    return False, "File has no content"
                
                # Try to detect delimiter
                try:
                    dialect = csv.Sniffer().sniff(first_line, delimiters=',;:\t|')
                except csv.Error:
                    # Use default comma delimiter
                    dialect = csv.excel
                
                # Check if we can create a DictReader
                f.seek(0)
                try:
                    reader = csv.DictReader(f, dialect=dialect)
                    # Check if we have fieldnames (headers)
                    if not reader.fieldnames:
                        return False, "File has no headers"
                    
                    # Try to read at least one row
                    first_row = next(reader, None)
                    
                    # Headers-only is still valid CSV format
                    return True, ""
                    
                except Exception as e:
                    return False, f"Invalid CSV format: {str(e)}"
                    
        except Exception as e:
            return False, f"Error reading file: {str(e)}"
    
    def validate_json_format(self, file_path: str) -> Tuple[bool, str]:
        """
        Validate that a file is a valid JSON with expected structure.
        
        Args:
            file_path: Path to file to validate
        
        Returns:
            Tuple of (is_valid, error_message)
            - is_valid: True if file is valid JSON, False otherwise
            - error_message: Empty string if valid, error description otherwise
        """
        if not os.path.exists(file_path):
            return False, f"File not found: {file_path}"
        
        try:
            # Check file is not empty
            if os.path.getsize(file_path) == 0:
                return False, "File is empty"
            
            # Try to parse as JSON
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                
                if not content:
                    return False, "File is empty"
                
                try:
                    data = json.loads(content)
                except json.JSONDecodeError as e:
                    return False, f"Invalid JSON format: {str(e)}"
                
                # Validate structure
                if isinstance(data, list):
                    # Array of objects - check first item if exists
                    if len(data) > 0 and isinstance(data[0], dict):
                        return True, ""
                    elif len(data) == 0:
                        return True, ""  # Empty array is valid
                    else:
                        return False, "Array must contain objects/dictionaries"
                
                elif isinstance(data, dict):
                    # Key-value object is valid
                    return True, ""
                
                else:
                    return False, "JSON must be an array of objects or a key-value object"
                    
        except Exception as e:
            return False, f"Error reading file: {str(e)}"
    
    def parse_file(self, file_path: str, file_type: str = 'auto',
                   value_col: str = 'value', key_col: str = 'key',
                   value_key: str = 'value', key_key: str = 'key') -> List[Tuple[str, str]]:
        """
        Parse IOC file automatically detecting format or using specified format.
        
        Args:
            file_path: Path to file to parse
            file_type: 'auto' to detect, 'csv' or 'json' to specify
            value_col: Column name for values in CSV (default: 'value')
            key_col: Column name for keys in CSV (default: 'key')
            value_key: Key name for values in JSON (default: 'value')
            key_key: Key name for keys in JSON (default: 'key')
        
        Returns:
            List of tuples (value, key) extracted from the file
        
        Raises:
            ValueError: If file type cannot be determined or file is invalid
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Determine file type
        if file_type == 'auto':
            file_ext = os.path.splitext(file_path)[1].lower()
            
            if file_ext == '.csv':
                file_type = 'csv'
            elif file_ext == '.json':
                file_type = 'json'
            else:
                # Try to detect from content
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        first_char = f.read(1)
                        if first_char == '[' or first_char == '{':
                            file_type = 'json'
                        else:
                            file_type = 'csv'
                except:
                    file_type = 'csv'
        
        # Parse based on type
        if file_type == 'csv':
            return self.parse_csv(file_path, value_col, key_col)
        elif file_type == 'json':
            return self.parse_json(file_path, value_key, key_key)
        else:
            raise ValueError(f"Unsupported file type: {file_type}. Use 'auto', 'csv', or 'json'.")
    
    def validate_file(self, file_path: str, file_type: str = 'auto') -> Tuple[bool, str]:
        """
        Validate IOC file format.
        
        Args:
            file_path: Path to file to validate
            file_type: 'auto' to detect, 'csv' or 'json' to specify
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not os.path.exists(file_path):
            return False, f"File not found: {file_path}"
        
        # Determine file type
        if file_type == 'auto':
            file_ext = os.path.splitext(file_path)[1].lower()
            
            if file_ext == '.csv':
                file_type = 'csv'
            elif file_ext == '.json':
                file_type = 'json'
            else:
                # Try to detect from content
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        first_char = f.read(1)
                        if first_char == '[' or first_char == '{':
                            file_type = 'json'
                        else:
                            file_type = 'csv'
                except:
                    file_type = 'csv'
        
        # Validate based on type
        if file_type == 'csv':
            return self.validate_csv_format(file_path)
        elif file_type == 'json':
            return self.validate_json_format(file_path)
        else:
            return False, f"Unsupported file type: {file_type}"
