"""
Dynamic Linking Intelligence Engine

A forensic intelligence system that enriches data display with human-readable context
by translating raw forensic artifacts (SIDs, MAC addresses, file hashes, GUIDs, etc.)
into human-readable context (usernames, network names, application names) in real-time
during data display.

This engine operates as a non-invasive overlay system that enriches data visualization
without modifying the original parsed forensic databases, ensuring evidence integrity
while dramatically improving investigator efficiency.
"""

__version__ = "0.1.0"
__author__ = "Crow Eye Development Team"

from dynamic_mapping.core.intelligence_engine import IntelligenceEngine
from dynamic_mapping.rules.default_rules import DEFAULT_RULES
from dynamic_mapping.rules.custom_rules import CustomRule, CustomRulesManager

__all__ = [
    "IntelligenceEngine",
    "DEFAULT_RULES",
    "CustomRule",
    "CustomRulesManager",
]