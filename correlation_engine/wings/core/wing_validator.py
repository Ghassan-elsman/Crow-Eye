"""
Wing Validator
Validates wing configurations before saving or execution.
"""

from typing import List, Tuple
from .wing_model import Wing


class WingValidator:
    """Validates wing configurations"""
    
    @staticmethod
    def validate_wing(wing: Wing) -> Tuple[bool, List[str]]:
        """
        Validate complete wing configuration.
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        # Validate basic fields
        errors.extend(WingValidator._validate_basic_fields(wing))
        
        # Validate feathers
        errors.extend(WingValidator._validate_feathers(wing))
        
        # Validate correlation rules
        errors.extend(WingValidator._validate_correlation_rules(wing))
        
        return (len(errors) == 0, errors)
    
    @staticmethod
    def _validate_basic_fields(wing: Wing) -> List[str]:
        """Validate basic wing fields"""
        errors = []
        
        if not wing.wing_name or wing.wing_name.strip() == "":
            errors.append("Wing name is required")
        
        if not wing.wing_id:
            errors.append("Wing ID is required")
        
        if not wing.proves or wing.proves.strip() == "":
            errors.append("'Proves' field is required - what does this wing prove?")
        
        return errors
    
    @staticmethod
    def _validate_feathers(wing: Wing) -> List[str]:
        """Validate feather specifications"""
        errors = []
        
        # Check minimum feathers
        if len(wing.feathers) < 2:
            errors.append("Wing must have at least 2 feathers for correlation")
        
        # Validate each feather
        for i, feather in enumerate(wing.feathers, 1):
            # Check artifact type
            if feather.artifact_type == 'Unknown':
                errors.append(f"Feather {i}: Artifact type must be selected (cannot be 'Unknown')")
            
            # Check database filename
            if not feather.database_filename:
                errors.append(f"Feather {i}: Database filename is required")
            
            # Check feather ID
            if not feather.feather_id:
                errors.append(f"Feather {i}: Feather ID is required")
            
            # Check for duplicate feather IDs
            duplicate_ids = [f for f in wing.feathers if f.feather_id == feather.feather_id]
            if len(duplicate_ids) > 1:
                errors.append(f"Feather {i}: Duplicate feather ID '{feather.feather_id}'")
        
        return errors
    
    @staticmethod
    def _validate_correlation_rules(wing: Wing) -> List[str]:
        """Validate correlation rules"""
        errors = []
        
        rules = wing.correlation_rules
        
        # Validate time window
        if rules.time_window_minutes <= 0:
            errors.append("Time window must be greater than 0 minutes")
        
        if rules.time_window_minutes > 1440:  # 24 hours
            errors.append("Time window cannot exceed 1440 minutes (24 hours)")
        
        # Validate minimum matches
        if rules.minimum_matches < 2:
            errors.append("Minimum matches must be at least 2")
        
        if rules.minimum_matches > len(wing.feathers):
            errors.append(f"Minimum matches ({rules.minimum_matches}) cannot exceed number of feathers ({len(wing.feathers)})")
        
        # Validate anchor priority
        if not rules.anchor_priority or len(rules.anchor_priority) == 0:
            errors.append("Anchor priority list cannot be empty")
        
        return errors
    
    @staticmethod
    def validate_before_save(wing: Wing) -> Tuple[bool, List[str]]:
        """
        Validate wing before saving to file.
        Includes all standard validations plus save-specific checks.
        """
        is_valid, errors = WingValidator.validate_wing(wing)
        
        # Additional save-specific validations
        if not wing.author or wing.author.strip() == "":
            errors.append("Author name is required before saving")
        
        if not wing.description or wing.description.strip() == "":
            errors.append("Description is required before saving")
        
        return (len(errors) == 0, errors)
    
    @staticmethod
    def validate_before_execution(wing: Wing) -> Tuple[bool, List[str]]:
        """
        Validate wing before execution in correlation engine.
        Includes all standard validations plus execution-specific checks.
        """
        is_valid, errors = WingValidator.validate_wing(wing)
        
        # Additional execution-specific validations
        # Check wing-level filters
        if wing.correlation_rules.apply_to == 'specific':
            if not wing.correlation_rules.target_application or wing.correlation_rules.target_application.strip() == '':
                errors.append("Target application name is required when 'Apply to' is set to 'Specific Application'")
        
        return (len(errors) == 0, errors)

    @staticmethod
    def get_validation_summary(errors: List[str]) -> str:
        """
        Get a human-readable summary of validation results.
        
        Args:
            errors: List of validation error messages
            
        Returns:
            Summary string
        """
        if not errors:
            return "✓ Wing validation passed - No issues found"
        
        error_count = len(errors)
        if error_count == 1:
            return f"✗ 1 validation error"
        else:
            return f"✗ {error_count} validation errors"
