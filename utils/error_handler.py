import logging
import sys
import traceback
from typing import Optional, Type, Dict, Any, Callable, TypeVar, Tuple
from functools import wraps

T = TypeVar('T')  # Generic type variable for return types

class ErrorHandler:
    """
    Centralized error handling and logging utility.
    Provides decorators and context managers for consistent error handling.
    """
    
    def __init__(self, logger_name: str = 'CrowEye'):
        """
        Initialize the error handler with a logger.
        
        Args:
            logger_name: Name to use for the logger
        """
        self.logger = logging.getLogger(logger_name)
        self.setup_logging()
    
    def setup_logging(self, log_level: int = logging.INFO, log_file: Optional[str] = None):
        """
        Configure logging settings.
        
        Args:
            log_level: Logging level (e.g., logging.INFO, logging.DEBUG)
            log_file: Optional file to write logs to
        """
        # Clear any existing handlers
        self.logger.handlers = []
        
        # Set log level
        self.logger.setLevel(log_level)
        
        # Create console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        
        # Add console handler to logger
        self.logger.addHandler(console_handler)
        
        # Add file handler if log file is specified
        if log_file:
            try:
                file_handler = logging.FileHandler(log_file)
                file_handler.setLevel(log_level)
                file_handler.setFormatter(formatter)
                self.logger.addHandler(file_handler)
            except Exception as e:
                self.logger.error(f"Failed to set up file logging: {str(e)}")
    
    def handle_error(self, 
                    exception: Optional[Type[Exception]] = None, 
                    message: str = "An error occurred",
                    log_level: int = logging.ERROR,
                    raise_exception: bool = True) -> bool:
        """
        Handle an error with consistent logging and optional re-raising.
        
        Args:
            exception: The exception that was caught (if any)
            message: Custom error message
            log_level: Logging level for the error
            raise_exception: Whether to re-raise the exception
            
        Returns:
            bool: Always returns False to allow for early returns
        """
        exc_info = sys.exc_info()
        full_message = message
        
        if exception is not None:
            full_message = f"{message}: {str(exception)}"
        
        # Log the error
        self.logger.log(log_level, full_message, exc_info=exc_info[0] is not None)
        
        # Re-raise the exception if requested
        if raise_exception and exception is not None:
            raise exception
            
        return False
    
    def error_decorator(self, 
                       exception: Type[Exception] = Exception,
                       message: str = "An error occurred in function {function_name}",
                       log_level: int = logging.ERROR,
                       return_value: Any = None):
        """
        Decorator for handling exceptions in functions.
        
        Args:
            exception: Exception type to catch
            message: Error message template (can use {function_name} placeholder)
            log_level: Logging level
            return_value: Value to return when an exception is caught
            
        Returns:
            Decorator function
        """
        def decorator(func: Callable[..., T]) -> Callable[..., T]:
            @wraps(func)
            def wrapper(*args, **kwargs) -> T:
                try:
                    return func(*args, **kwargs)
                except exception as e:
                    formatted_message = message.format(
                        function_name=func.__name__,
                        exception=str(e)
                    )
                    self.handle_error(e, formatted_message, log_level, False)
                    return return_value
            return wrapper
        return decorator
    
    def error_context(self, 
                     exception: Type[Exception] = Exception,
                     message: str = "An error occurred in context",
                     log_level: int = logging.ERROR,
                     reraise: bool = True):
        """
        Context manager for handling exceptions in a with block.
        
        Args:
            exception: Exception type to catch
            message: Error message
            log_level: Logging level
            reraise: Whether to re-raise the exception
            
        Returns:
            Context manager
        """
        class ErrorContext:
            def __init__(self, handler, exception, message, log_level, reraise):
                self.handler = handler
                self.exception = exception
                self.message = message
                self.log_level = log_level
                self.reraise = reraise
                
            def __enter__(self):
                return self
                
            def __exit__(self, exc_type, exc_val, exc_tb):
                if exc_type is not None and issubclass(exc_type, self.exception):
                    self.handler.handle_error(
                        exc_val,
                        self.message,
                        self.log_level,
                        self.reraise
                    )
                    return not self.reraise  # Only suppress if we're not re-raising
                return False
                
        return ErrorContext(self, exception, message, log_level, reraise)
    
    def log_execution(self, level: int = logging.DEBUG):
        """
        Decorator to log function entry and exit.
        
        Args:
            level: Logging level for the entry/exit messages
            
        Returns:
            Decorator function
        """
        def decorator(func: Callable[..., T]) -> Callable[..., T]:
            @wraps(func)
            def wrapper(*args, **kwargs) -> T:
                self.logger.log(level, f"Entering {func.__name__}")
                try:
                    result = func(*args, **kwargs)
                    self.logger.log(level, f"Exiting {func.__name__} (success)")
                    return result
                except Exception as e:
                    self.logger.log(level, f"Exiting {func.__name__} (error: {str(e)})", exc_info=True)
                    raise
            return wrapper
        return decorator

# Create a default instance for easy importing
default_handler = ErrorHandler()
handle_error = default_handler.handle_error
error_decorator = default_handler.error_decorator
error_context = default_handler.error_context
log_execution = default_handler.log_execution
