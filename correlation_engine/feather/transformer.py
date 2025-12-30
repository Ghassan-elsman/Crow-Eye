"""
Data Transformation Module
Handles data type conversion, validation, and transformation.
"""

from datetime import datetime
from typing import Any, List, Dict
import re


class DataTransformer:
    """Handles data transformation and validation."""
    
    @staticmethod
    def detect_data_type(value: Any) -> str:
        """Detect data type of a value."""
        if value is None or value == '':
            return 'TEXT'
        
        # Try integer
        try:
            int(value)
            return 'INTEGER'
        except (ValueError, TypeError):
            pass
        
        # Try float
        try:
            float(value)
            return 'REAL'
        except (ValueError, TypeError):
            pass
        
        # Try datetime
        if DataTransformer.is_timestamp(str(value)):
            return 'DATETIME'
        
        return 'TEXT'
    
    @staticmethod
    def is_timestamp(value: str) -> bool:
        """Check if value is a timestamp."""
        timestamp_patterns = [
            r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
            r'\d{2}/\d{2}/\d{4}',  # MM/DD/YYYY
            r'\d{4}/\d{2}/\d{2}',  # YYYY/MM/DD
            r'\d{2}-\d{2}-\d{4}',  # DD-MM-YYYY
        ]
        
        for pattern in timestamp_patterns:
            if re.match(pattern, str(value)):
                return True
        
        return False
    
    @staticmethod
    def normalize_timestamp(value: Any) -> str:
        """Normalize timestamp to ISO format."""
        if not value:
            return datetime.now().isoformat()
        
        value_str = str(value)
        
        # Try common formats
        formats = [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d',
            '%m/%d/%Y %H:%M:%S',
            '%m/%d/%Y',
            '%d-%m-%Y %H:%M:%S',
            '%d-%m-%Y',
            '%Y/%m/%d %H:%M:%S',
            '%Y/%m/%d',
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(value_str, fmt)
                return dt.isoformat()
            except ValueError:
                continue
        
        # If no format matches, return as is
        return value_str
    
    @staticmethod
    def convert_value(value: Any, target_type: str) -> Any:
        """Convert value to target type."""
        if value is None or value == '':
            return None
        
        try:
            if target_type == 'INTEGER':
                return int(value)
            elif target_type == 'REAL':
                return float(value)
            elif target_type == 'DATETIME':
                return DataTransformer.normalize_timestamp(value)
            else:  # TEXT
                return str(value)
        except (ValueError, TypeError):
            return str(value)  # Fallback to string
    
    @staticmethod
    def validate_data(data: List[Dict[str, Any]], columns: List[Dict[str, Any]]) -> tuple:
        """
        Validate data against column definitions.
        
        Returns:
            (valid_records, invalid_records, errors)
        """
        valid_records = []
        invalid_records = []
        errors = []
        
        for idx, record in enumerate(data):
            is_valid = True
            validated_record = {}
            
            for col in columns:
                if col['original'] == '[ROW_COUNT]':
                    continue
                
                value = record.get(col['original'])
                
                try:
                    # Convert value to appropriate type
                    converted_value = DataTransformer.convert_value(
                        value,
                        col.get('type', 'TEXT')
                    )
                    validated_record[col['original']] = converted_value
                    
                except Exception as e:
                    is_valid = False
                    errors.append({
                        'row': idx + 1,
                        'column': col['original'],
                        'error': str(e),
                        'value': value
                    })
            
            if is_valid:
                valid_records.append(validated_record)
            else:
                invalid_records.append(record)
        
        return valid_records, invalid_records, errors
    
    @staticmethod
    def clean_data(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Clean data by removing null values and trimming strings."""
        cleaned_data = []
        
        for record in data:
            cleaned_record = {}
            for key, value in record.items():
                if isinstance(value, str):
                    cleaned_record[key] = value.strip()
                else:
                    cleaned_record[key] = value
            cleaned_data.append(cleaned_record)
        
        return cleaned_data
