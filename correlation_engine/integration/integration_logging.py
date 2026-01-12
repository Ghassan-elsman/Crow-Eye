"""
Integration Logging Configuration

Provides comprehensive logging configuration for all integration points
including structured logging, performance logging, and error tracking.
"""

import logging
import logging.handlers
import json
import time
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path
import traceback
from dataclasses import dataclass, field


@dataclass
class LoggingConfig:
    """Configuration for integration logging"""
    log_level: str = "INFO"
    log_format: str = "detailed"  # simple, detailed, json
    enable_file_logging: bool = True
    enable_console_logging: bool = True
    log_directory: str = "logs"
    max_file_size_mb: int = 10
    backup_count: int = 5
    enable_performance_logging: bool = True
    enable_error_tracking: bool = True
    enable_audit_logging: bool = True


class IntegrationLogFormatter(logging.Formatter):
    """Custom formatter for integration logging"""
    
    def __init__(self, format_type: str = "detailed"):
        self.format_type = format_type
        
        if format_type == "json":
            super().__init__()
        elif format_type == "detailed":
            fmt = (
                "%(asctime)s | %(levelname)-8s | %(name)-30s | "
                "%(funcName)-20s:%(lineno)-4d | %(message)s"