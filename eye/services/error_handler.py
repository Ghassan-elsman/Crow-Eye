"""
Error Handler for EYE AI Forensic Assistant.

This module provides centralized error handling with logging and user-friendly messaging.
Handles error categories: database errors, LLM backend errors, tool execution errors, 
and file system errors.

"""

import logging
import traceback
from typing import Dict, Any, Optional
from datetime import datetime
import sqlite3
import requests


class ErrorHandler:
    """
    Centralized error handler for EYE system.
    
    Provides:
    - Comprehensive error logging with stack traces
    - User-friendly error messages without internal details
    - Category-specific error handling
    - Troubleshooting guidance
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize ErrorHandler.
        
        Args:
            logger: Optional logger instance. If None, creates default logger.
        """
        self.logger = logger or logging.getLogger(__name__)
    
    def handle_error(
        self, 
        error: Exception, 
        context: Dict[str, Any], 
        user_facing: bool = True
    ) -> Dict[str, Any]:
        """
        Handle error with logging and user message generation.
        
        Args:
            error: The exception that occurred
            context: Context information (operation, parameters, etc.)
            user_facing: Whether to generate user-friendly message
            
        Returns:
            Dict containing:
                - error_type: Category of error
                - user_message: User-friendly error message
                - technical_details: Technical error information
                - troubleshooting: Suggested troubleshooting steps
                - timestamp: When error occurred
        """
        # Log full error with stack trace
        self.logger.error(
            f"Error in {context.get('operation', 'unknown operation')}: {str(error)}",
            exc_info=True,
            extra={"context": context}
        )
        
        # Determine error category
        error_type = self._categorize_error(error, context)
        
        # Generate user-friendly message
        user_message = self._get_user_message(error, context) if user_facing else str(error)
        
        # Get troubleshooting guidance
        troubleshooting = self._get_troubleshooting_steps(error_type, error, context)
        
        return {
            "error_type": error_type,
            "user_message": user_message,
            "technical_details": {
                "exception_type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc()
            },
            "troubleshooting": troubleshooting,
            "timestamp": datetime.now().isoformat(),
            "context": context
        }
    
    def _categorize_error(self, error: Exception, context: Dict[str, Any] = None) -> str:
        """
        Categorize error into one of the main error types.
        
        Args:
            error: The exception to categorize
            context: Context information to help with categorization
            
        Returns:
            Error category string
        """
        context = context or {}
        
        # Database errors
        if isinstance(error, (sqlite3.Error, sqlite3.DatabaseError, sqlite3.OperationalError)):
            return "database_error"
        
        # LLM backend errors
        if isinstance(error, (requests.exceptions.RequestException, 
                             requests.exceptions.ConnectionError,
                             requests.exceptions.Timeout)):
            return "llm_backend_error"
        
        if "openai" in str(type(error)).lower() or "anthropic" in str(type(error)).lower():
            return "llm_backend_error"
        
        # File system errors
        if isinstance(error, (FileNotFoundError, PermissionError, OSError, IOError)):
            return "file_system_error"
        
        # Tool execution errors - check context for tool operations
        operation = context.get("operation", "")
        tool_name = context.get("tool_name", "")
        
        if isinstance(error, (ValueError, KeyError, TypeError)):
            # Check if this is a tool-related operation
            if "tool" in operation.lower() or tool_name or "execute_tool" in operation:
                return "tool_execution_error"
            # Check if error message mentions tools
            if "tool" in str(error).lower():
                return "tool_execution_error"
        
        # Generic errors
        return "general_error"
    
    def _get_user_message(self, error: Exception, context: Dict[str, Any]) -> str:
        """
        Generate user-friendly error message without exposing internal details.
        
        Args:
            error: The exception that occurred
            context: Context information about the operation
            
        Returns:
            User-friendly error message
        """
        error_type = self._categorize_error(error, context)
        operation = context.get("operation", "operation")
        
        # Database errors
        if error_type == "database_error":
            if "locked" in str(error).lower():
                return (
                    "The forensic database is currently locked. "
                    "Please ensure no other processes are accessing the database and try again."
                )
            elif "no such table" in str(error).lower():
                table_name = context.get("table_name", "requested table")
                return (
                    f"The database table '{table_name}' was not found. "
                    "This may indicate the artifact has not been parsed yet."
                )
            elif "no such column" in str(error).lower():
                return (
                    "The requested database column does not exist. "
                    "Please verify the column name or check the database schema."
                )
            elif "read-only" in str(error).lower() or "attempt to write" in str(error).lower():
                return (
                    "Cannot modify the forensic database. "
                    "EYE operates in read-only mode to preserve evidence integrity."
                )
            else:
                return (
                    f"A database error occurred while {operation}. "
                    "Please check the database file and try again."
                )
        
        # LLM backend errors
        elif error_type == "llm_backend_error":
            backend = context.get("backend", "LLM backend")
            
            if isinstance(error, requests.exceptions.ConnectionError):
                return (
                    f"Cannot connect to {backend}. "
                    "Please verify the service is running and network connectivity is available."
                )
            elif isinstance(error, requests.exceptions.Timeout):
                return (
                    f"Request to {backend} timed out. "
                    "The model may be processing a large request or the service may be overloaded."
                )
            elif "api key" in str(error).lower() or "authentication" in str(error).lower():
                return (
                    f"Authentication failed for {backend}. "
                    "Please verify your API key in the configuration settings."
                )
            elif "rate limit" in str(error).lower():
                return (
                    f"Rate limit exceeded for {backend}. "
                    "Please wait a moment before trying again."
                )
            elif "context length" in str(error).lower() or "token" in str(error).lower():
                return (
                    "The request exceeds the model's context window. "
                    "Try reducing the conversation history or query complexity."
                )
            else:
                return (
                    f"Failed to communicate with {backend}. "
                    "Please check the backend configuration and connectivity."
                )
        
        # File system errors
        elif error_type == "file_system_error":
            file_path = context.get("file_path", "file")
            
            if isinstance(error, FileNotFoundError):
                return (
                    f"The file '{file_path}' was not found. "
                    "Please verify the file path and ensure the file exists."
                )
            elif isinstance(error, PermissionError):
                return (
                    f"Permission denied when accessing '{file_path}'. "
                    "Please check file permissions and ensure you have access rights."
                )
            elif "disk full" in str(error).lower() or "no space" in str(error).lower():
                return (
                    "Insufficient disk space to complete the operation. "
                    "Please free up disk space and try again."
                )
            else:
                return (
                    f"A file system error occurred while accessing '{file_path}'. "
                    "Please check file permissions and disk space."
                )
        
        # Tool execution errors
        elif error_type == "tool_execution_error":
            tool_name = context.get("tool_name", "tool")
            
            if isinstance(error, KeyError):
                missing_param = str(error).strip("'\"")
                return (
                    f"Missing required parameter '{missing_param}' for {tool_name}. "
                    "Please provide all required parameters."
                )
            elif isinstance(error, ValueError):
                return (
                    f"Invalid parameter value for {tool_name}. "
                    "Please check the parameter format and try again."
                )
            elif isinstance(error, TypeError):
                return (
                    f"Incorrect parameter type for {tool_name}. "
                    "Please verify the parameter types match the expected format."
                )
            else:
                return (
                    f"Failed to execute {tool_name}. "
                    "Please verify the parameters and try again."
                )
        
        # General errors
        else:
            return (
                f"An unexpected error occurred during {operation}. "
                "Please check the logs for more details or try again."
            )
    
    def _get_troubleshooting_steps(
        self, 
        error_type: str, 
        error: Exception, 
        context: Dict[str, Any]
    ) -> list:
        """
        Generate troubleshooting steps based on error type.
        
        Args:
            error_type: Category of error
            error: The exception that occurred
            context: Context information
            
        Returns:
            List of troubleshooting steps
        """
        # Database errors
        if error_type == "database_error":
            steps = [
                "Verify the database file exists and is not corrupted",
                "Ensure no other processes have the database locked",
                "Check that the database was created by Crow-eye's parsers",
                "Verify you have read permissions for the database file"
            ]
            
            if "locked" in str(error).lower():
                steps.insert(0, "Close any other applications accessing the database")
            
            return steps
        
        # LLM backend errors
        elif error_type == "llm_backend_error":
            backend = context.get("backend", "backend")
            steps = []
            
            if "ollama" in backend.lower():
                steps = [
                    "Verify Ollama is running: ollama list",
                    "Check the model is installed: ollama list",
                    "Ensure the executable path is correct in settings",
                    "Try restarting the Ollama service"
                ]
            elif "lm studio" in backend.lower() or "lm_studio" in backend.lower():
                steps = [
                    "Verify LM Studio is running and the server is started",
                    "Check the API endpoint (default: http://localhost:1234)",
                    "Ensure a model is loaded in LM Studio",
                    "Verify the port is not blocked by firewall"
                ]
            elif "openai" in backend.lower():
                steps = [
                    "Verify your OpenAI API key is valid",
                    "Check your OpenAI account has available credits",
                    "Ensure you have internet connectivity",
                    "Verify the API endpoint is accessible"
                ]
            elif "anthropic" in backend.lower():
                steps = [
                    "Verify your Anthropic API key is valid",
                    "Check your Anthropic account status",
                    "Ensure you have internet connectivity",
                    "Verify the API endpoint is accessible"
                ]
            else:
                steps = [
                    f"Verify {backend} is running and accessible",
                    "Check the configuration settings",
                    "Test connectivity using the configuration wizard",
                    "Review the session logs for detailed error information"
                ]
            
            return steps
        
        # File system errors
        elif error_type == "file_system_error":
            return [
                "Verify the file path is correct",
                "Check file and directory permissions",
                "Ensure sufficient disk space is available",
                "Verify the file is not locked by another process",
                "Check that the parent directory exists"
            ]
        
        # Tool execution errors
        elif error_type == "tool_execution_error":
            return [
                "Verify all required parameters are provided",
                "Check parameter types match expected format",
                "Review the tool documentation for correct usage",
                "Try simplifying the query or parameters",
                "Check the session logs for detailed error information"
            ]
        
        # General errors
        else:
            return [
                "Review the session logs for detailed error information",
                "Try restarting the EYE Assistant",
                "Verify all configuration settings are correct",
                "Check system resources (memory, disk space)",
                "Contact support if the issue persists"
            ]
