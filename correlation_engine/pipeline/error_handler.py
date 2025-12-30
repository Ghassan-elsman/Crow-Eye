"""
Error Handler

Centralized error handling for the Pipeline Configuration Manager.
Provides user-friendly error messages and recovery actions.
"""

from typing import Optional
from ..config.session_state import ErrorResponse, LoadStatus


class ErrorHandler:
    """
    Centralized error handling for configuration manager.
    Provides standardized error responses with recovery actions.
    """
    
    @staticmethod
    def handle_missing_config(config_path: str, config_type: str) -> ErrorResponse:
        """
        Handle missing configuration file.
        
        Args:
            config_path: Path to missing configuration
            config_type: Type of configuration ("pipeline", "feather", "wing")
        
        Returns:
            ErrorResponse with recovery action
        """
        return ErrorResponse(
            severity="error",
            message=f"{config_type.capitalize()} configuration not found: {config_path}",
            recovery_action="prompt_user_to_select_alternative",
            user_message=f"The {config_type} configuration could not be found. Would you like to select a different one?",
            technical_details=f"File not found: {config_path}"
        )
    
    @staticmethod
    def handle_partial_load(load_status: LoadStatus) -> ErrorResponse:
        """
        Handle partial pipeline load.
        
        Args:
            load_status: LoadStatus with partial load information
        
        Returns:
            ErrorResponse with recovery action
        """
        failed_components = []
        
        if load_status.feathers_loaded < load_status.feathers_total:
            failed_count = load_status.feathers_total - load_status.feathers_loaded
            failed_components.append(f"{failed_count} feather(s)")
        
        if load_status.wings_loaded < load_status.wings_total:
            failed_count = load_status.wings_total - load_status.wings_loaded
            failed_components.append(f"{failed_count} wing(s)")
        
        failed_str = " and ".join(failed_components)
        
        return ErrorResponse(
            severity="warning",
            message=f"Pipeline partially loaded: {failed_str} failed to load",
            recovery_action="continue_with_partial",
            user_message=f"Some components could not be loaded ({failed_str}). Continue with available components?",
            technical_details="; ".join(load_status.errors)
        )
    
    @staticmethod
    def handle_connection_failure(feather_name: str, error: Exception) -> ErrorResponse:
        """
        Handle database connection failure.
        
        Args:
            feather_name: Name of the feather
            error: Exception that occurred
        
        Returns:
            ErrorResponse with recovery action
        """
        return ErrorResponse(
            severity="error",
            message=f"Failed to connect to {feather_name}: {str(error)}",
            recovery_action="skip_feather",
            user_message=f"Could not connect to {feather_name} database. Skip this feather and continue?",
            technical_details=f"{type(error).__name__}: {str(error)}"
        )
    
    @staticmethod
    def handle_session_error(error: Exception) -> ErrorResponse:
        """
        Handle session state error.
        
        Args:
            error: Exception that occurred
        
        Returns:
            ErrorResponse with recovery action
        """
        return ErrorResponse(
            severity="warning",
            message=f"Session state error: {str(error)}",
            recovery_action="clear_session",
            user_message="The session state file is corrupted. Clear session and start fresh?",
            technical_details=f"{type(error).__name__}: {str(error)}"
        )
    
    @staticmethod
    def handle_validation_error(config_type: str, errors: list[str]) -> ErrorResponse:
        """
        Handle configuration validation error.
        
        Args:
            config_type: Type of configuration
            errors: List of validation errors
        
        Returns:
            ErrorResponse with recovery action
        """
        error_list = "\n".join(f"- {err}" for err in errors)
        
        return ErrorResponse(
            severity="error",
            message=f"{config_type.capitalize()} validation failed",
            recovery_action="show_errors",
            user_message=f"The {config_type} configuration has validation errors:\n{error_list}",
            technical_details="; ".join(errors)
        )
    
    @staticmethod
    def handle_database_not_found(database_path: str, feather_name: str) -> ErrorResponse:
        """
        Handle database file not found.
        
        Args:
            database_path: Path to missing database
            feather_name: Name of the feather
        
        Returns:
            ErrorResponse with recovery action
        """
        return ErrorResponse(
            severity="error",
            message=f"Database not found for {feather_name}",
            recovery_action="skip_feather",
            user_message=f"The database file for {feather_name} could not be found at:\n{database_path}\n\nSkip this feather?",
            technical_details=f"File not found: {database_path}"
        )
    
    @staticmethod
    def handle_auto_load_failure(pipeline_path: str, error: Exception) -> ErrorResponse:
        """
        Handle auto-load failure.
        
        Args:
            pipeline_path: Path to pipeline that failed to load
            error: Exception that occurred
        
        Returns:
            ErrorResponse with recovery action
        """
        return ErrorResponse(
            severity="warning",
            message=f"Failed to auto-load pipeline: {str(error)}",
            recovery_action="prompt_manual_selection",
            user_message=f"Could not automatically load the last pipeline. Would you like to select a pipeline manually?",
            technical_details=f"Pipeline: {pipeline_path}\n{type(error).__name__}: {str(error)}"
        )
    
    @staticmethod
    def handle_pipeline_creation_error(error: Exception) -> ErrorResponse:
        """
        Handle pipeline creation error.
        
        Args:
            error: Exception that occurred
        
        Returns:
            ErrorResponse with recovery action
        """
        return ErrorResponse(
            severity="error",
            message=f"Failed to create pipeline: {str(error)}",
            recovery_action="show_error",
            user_message=f"Could not create the pipeline:\n{str(error)}",
            technical_details=f"{type(error).__name__}: {str(error)}"
        )
    
    @staticmethod
    def handle_discovery_error(error: Exception) -> ErrorResponse:
        """
        Handle configuration discovery error.
        
        Args:
            error: Exception that occurred
        
        Returns:
            ErrorResponse with recovery action
        """
        return ErrorResponse(
            severity="warning",
            message=f"Configuration discovery failed: {str(error)}",
            recovery_action="retry",
            user_message=f"Could not scan for configurations. Retry?",
            technical_details=f"{type(error).__name__}: {str(error)}"
        )
    
    @staticmethod
    def format_user_message(error_response: ErrorResponse) -> str:
        """
        Format error response for user display.
        
        Args:
            error_response: ErrorResponse to format
        
        Returns:
            Formatted message string
        """
        severity_icon = {
            "error": "✗",
            "warning": "⚠",
            "info": "ℹ"
        }.get(error_response.severity, "•")
        
        return f"{severity_icon} {error_response.user_message}"
