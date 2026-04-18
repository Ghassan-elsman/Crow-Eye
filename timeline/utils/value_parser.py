"""
Value Parser Utility for Timeline Feature
=========================================

This module provides dynamic "de-formatting" of beautified forensic strings.
It can detect and convert strings like "1.50 MB" or "5m 20s" back into 
raw numeric values (bytes, seconds, milliseconds) for use in calculations.

It supports "Dual-Mode" detection:
1. Raw Pass-through: If value is already a number, it returns it as-is.
2. Dynamic Parse: If value is a string, it detects units and converts them.
"""

import re
import logging

logger = logging.getLogger(__name__)

class ValueParser:
    """
    Robust utility to parse formatted forensic metrics into numbers.
    """
    
    # Regex patterns for various units
    # Handle Bytes: B, KB, MB, GB, TB
    BYTES_PATTERN = re.compile(r"(\d+\.?\d*)\s*(B|KB|MB|GB|TB)", re.IGNORECASE)
    
    # Handle Durations: 5h 20m 30s or 5.2 ms
    # ms must come before m to avoid partial matches
    DURATION_COMPONENTS = re.compile(r"(\d+\.?\d*)\s*(ms|h|m|s|hrs|min|sec)", re.IGNORECASE)

    @staticmethod
    def parse_to_num(value):
        """
        Main entry point for dynamic parsing.
        Detects type and format, then returns a float.
        Returns 0.0 if parsing fails.
        """
        if value is None:
            return 0.0
            
        # Case 1: Already a number (Integer or Float)
        if isinstance(value, (int, float)):
            return float(value)
            
        # Case 2: String - needs parsing
        if isinstance(value, str):
            clean_s = value.strip()
            if not clean_s or clean_s.lower() == "unknown":
                return 0.0
                
            # Try plain number conversion first (handles "1,234")
            try:
                return float(clean_s.replace(",", ""))
            except ValueError:
                pass
                
            # Try Byte parsing
            byte_val = ValueParser._parse_bytes(clean_s)
            if byte_val is not None:
                return byte_val
                
            # Try Duration parsing
            dur_val = ValueParser._parse_duration(clean_s)
            if dur_val is not None:
                return dur_val
                
        # Fallback
        return 0.0

    @staticmethod
    def _parse_bytes(s):
        """Converts '1.50 MB' to raw bytes (float)."""
        match = ValueParser.BYTES_PATTERN.search(s)
        if not match:
            return None
            
        num = float(match.group(1))
        unit = match.group(2).upper()
        
        multipliers = {
            'B': 1,
            'KB': 1024,
            'MB': 1024**2,
            'GB': 1024**3,
            'TB': 1024**4
        }
        
        return num * multipliers.get(unit, 1)

    @staticmethod
    def _parse_duration(s):
        """Converts dur strings to seconds (float). Handles 'ms', 's', 'm', 'h'."""
        matches = ValueParser.DURATION_COMPONENTS.findall(s)
        if not matches:
            return None
            
        total_seconds = 0.0
        found = False
        
        multipliers = {
            'h': 3600, 'hrs': 3600,
            'm': 60, 'min': 60,
            's': 1, 'sec': 1,
            'ms': 0.001
        }
        
        for num_str, unit in matches:
            unit_lower = unit.lower()
            total_seconds += float(num_str) * multipliers.get(unit_lower, 0)
            found = True
            
        return total_seconds if found else None

# SQLite adapter function
def parsable_num_adapter(value):
    """Bridge function for SQLite connections."""
    return ValueParser.parse_to_num(value)
