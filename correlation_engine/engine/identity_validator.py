"""
Identity Validator Module

This module provides validation for identity values extracted from forensic artifacts.
It filters out invalid data such as boolean strings, numeric values, empty strings,
and other non-meaningful identities.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8
"""

from typing import Tuple, Optional, Dict


class IdentityValidator:
    """
    Validates identity values to filter out invalid data.
    
    Filters:
    - Boolean strings (true, false, True, False, TRUE, FALSE, 1, 0)
    - Pure numeric values (1.0, 2, 123, 0.5)
    - Empty or whitespace-only strings
    - Values shorter than 2 characters (except drive letters)
    - Values without alphanumeric characters
    """
    
    # Boolean string variations
    BOOLEAN_STRINGS = {
        'true', 'false', 'True', 'False', 'TRUE', 'FALSE',
        '1', '0', 'yes', 'no', 'Yes', 'No', 'YES', 'NO'
    }
    
    def __init__(self):
        """Initialize validator with statistics tracking."""
        self.filtered_count = 0
        self.filtered_reasons = {}  # reason -> count
        
        # Fields that should NOT be validated (known to contain IDs, GUIDs, etc.)
        self.skip_validation_fields = {
            'app_id', 'appid', 'application_id', 'applicationid',
            'user_id', 'userid', 'process_id', 'processid',
            'guid', 'uuid', 'identifier', 'id',
            'entry_id', 'entryid', 'record_id', 'recordid',
            'row_id', 'rowid', 'index', 'sequence',
            'count', 'counter', 'number', 'num'
        }
    
    def should_validate_field(self, field_name: str) -> bool:
        """
        Determine if a field should be validated based on its name.
        
        Fields that are known to contain IDs, GUIDs, or numeric identifiers
        should not be validated as they are legitimately numeric.
        
        Args:
            field_name: Name of the field being extracted
            
        Returns:
            True if field should be validated, False to skip validation
        """
        if not field_name:
            return True
        
        field_lower = field_name.lower()
        
        # Check if field name contains any skip patterns
        for skip_pattern in self.skip_validation_fields:
            if skip_pattern in field_lower:
                return False
        
        return True
    
    def is_valid_identity(self, value: str, field_name: str = None) -> Tuple[bool, str]:
        """
        Check if value is a valid identity.
        
        ENHANCED: Now accepts optional field_name to apply field-aware validation.
        Fields known to contain IDs/GUIDs are not validated for numeric/boolean values.
        
        Args:
            value: Identity value to validate
            field_name: Optional field name for context-aware validation
            
        Returns:
            Tuple of (is_valid, reason)
            - is_valid: True if valid, False if should be filtered
            - reason: Reason for filtering (empty string if valid)
        """
        if not value:
            return False, "empty_value"
        
        # Convert to string and strip whitespace
        value_str = str(value).strip()
        
        if not value_str:
            return False, "whitespace_only"
        
        # ENHANCEMENT: Skip strict validation for known ID/GUID fields
        # These fields legitimately contain numeric or boolean-like values
        if field_name and not self.should_validate_field(field_name):
            # For ID fields, only check for empty/whitespace
            # Allow numeric, boolean, and short values
            return True, ""
        
        # Apply strict validation for identity fields (app_name, executable_name, etc.)
        
        # Check for boolean strings
        if value_str in self.BOOLEAN_STRINGS:
            return False, "boolean_string"
        
        # Check for pure numeric values
        if self._is_numeric(value_str):
            return False, "numeric_value"
        
        # Check minimum length (except drive letters like "C:")
        if len(value_str) < 2 and not self._is_drive_letter(value_str):
            return False, "too_short"
        
        # Check for at least one alphanumeric character
        if not any(c.isalnum() for c in value_str):
            return False, "no_alphanumeric"
        
        # Valid identity
        return True, ""
    
    def _is_numeric(self, value: str) -> bool:
        """
        Check if value is a pure number.
        
        Args:
            value: String value to check
            
        Returns:
            True if value is numeric, False otherwise
        """
        try:
            float(value)
            return True
        except ValueError:
            return False
    
    def _is_drive_letter(self, value: str) -> bool:
        """
        Check if value is a Windows drive letter (e.g., 'C:').
        
        Args:
            value: String value to check
            
        Returns:
            True if value is a drive letter, False otherwise
        """
        return len(value) == 2 and value[0].isalpha() and value[1] == ':'
    
    def validate_and_filter(self, value: str, log_filtered: bool = False, field_name: str = None) -> Optional[str]:
        """
        Validate identity value and return it if valid, None if filtered.
        
        ENHANCED: Now accepts optional field_name for context-aware validation.
        
        Args:
            value: Identity value to validate
            log_filtered: If True, log filtered values to console
            field_name: Optional field name for context-aware validation
            
        Returns:
            Original value if valid, None if filtered
        """
        is_valid, reason = self.is_valid_identity(value, field_name=field_name)
        
        if not is_valid:
            self.filtered_count += 1
            self.filtered_reasons[reason] = self.filtered_reasons.get(reason, 0) + 1
            
            if log_filtered:
                field_info = f" from field '{field_name}'" if field_name else ""
                print(f"[Identity Engine] Filtered invalid identity{field_info}: '{value}' (reason: {reason})")
            
            return None
        
        return value
    
    def get_statistics(self) -> Dict[str, any]:
        """
        Get filtering statistics.
        
        Returns:
            Dictionary containing:
            - total_filtered: Total number of filtered identities
            - reasons: Dictionary of reason -> count
        """
        return {
            'total_filtered': self.filtered_count,
            'reasons': dict(self.filtered_reasons)
        }
    
    def reset_statistics(self):
        """Reset filtering statistics to zero."""
        self.filtered_count = 0
        self.filtered_reasons.clear()
