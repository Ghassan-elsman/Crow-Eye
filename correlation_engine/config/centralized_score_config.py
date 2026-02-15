"""
Centralized Score Configuration System

This module provides a single source of truth for all score configurations
used throughout the correlation system. It ensures consistency across wings,
engines, and GUI components.

Requirements validated: 7.1, 7.2, 7.4, 8.1, 9.1, 9.2
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class CentralizedScoreConfig:
    """
    Single source of truth for all score configurations.
    
    This configuration is loaded once and referenced by all components
    to ensure consistency across the entire system.
    
    Attributes:
        thresholds: Score interpretation thresholds (low, medium, high, critical)
        tier_weights: Weights for evidence tiers (tier1-tier4)
        penalties: Scoring penalties for various conditions
        bonuses: Scoring bonuses for various conditions
        version: Configuration version string
        last_updated: ISO format timestamp of last update
    """
    
    # Score thresholds for interpretation
    thresholds: Dict[str, float] = field(default_factory=lambda: {
        'low': 0.3,
        'medium': 0.5,
        'high': 0.7,
        'critical': 0.9
    })
    
    # Tier weights for evidence levels
    tier_weights: Dict[str, float] = field(default_factory=lambda: {
        'tier1': 1.0,   # Primary evidence
        'tier2': 0.8,   # Secondary evidence
        'tier3': 0.6,   # Supporting evidence
        'tier4': 0.4    # Contextual evidence
    })
    
    # Scoring penalties
    penalties: Dict[str, float] = field(default_factory=lambda: {
        'missing_primary': 0.2,
        'missing_secondary': 0.1,
        'time_gap_penalty': 0.05
    })
    
    # Scoring bonuses
    bonuses: Dict[str, float] = field(default_factory=lambda: {
        'exact_time_match': 0.1,
        'multiple_sources': 0.15,
        'high_confidence': 0.2
    })
    
    # Configuration metadata
    version: str = "1.0"
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict:
        """
        Convert configuration to dictionary for serialization.
        
        Returns:
            Dictionary representation of the configuration
        """
        return asdict(self)
    
    def to_json(self, indent: int = 2) -> str:
        """
        Convert configuration to JSON string.
        
        Args:
            indent: Number of spaces for JSON indentation (default: 2)
        
        Returns:
            JSON string representation of the configuration
        """
        return json.dumps(self.to_dict(), indent=indent)
    
    def save_to_file(self, file_path: str):
        """
        Save configuration to JSON file.
        
        Args:
            file_path: Path to save the configuration file
        
        Raises:
            IOError: If file cannot be written
        """
        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(file_path, 'w') as f:
                f.write(self.to_json())
            
            logger.info(f"Score configuration saved to {file_path}")
        except Exception as e:
            logger.error(f"Failed to save score configuration to {file_path}: {e}")
            raise
    
    @classmethod
    def load_from_file(cls, file_path: str) -> 'CentralizedScoreConfig':
        """
        Load configuration from JSON file.
        
        Args:
            file_path: Path to the configuration file
        
        Returns:
            CentralizedScoreConfig instance loaded from file
        
        Raises:
            FileNotFoundError: If file does not exist
            json.JSONDecodeError: If file contains invalid JSON
        """
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            logger.info(f"Score configuration loaded from {file_path}")
            return cls(**data)
        except FileNotFoundError:
            logger.error(f"Score configuration file not found: {file_path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in score configuration file {file_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to load score configuration from {file_path}: {e}")
            raise
    
    @classmethod
    def get_default(cls) -> 'CentralizedScoreConfig':
        """
        Get default configuration with standard values.
        
        Returns:
            CentralizedScoreConfig instance with default values
        """
        logger.info("Using default score configuration")
        return cls()
    
    def interpret_score(self, score: float) -> str:
        """
        Interpret a score value using configured thresholds.
        
        Args:
            score: Score value to interpret (0.0 to 1.0)
        
        Returns:
            String interpretation ('Critical', 'High', 'Medium', 'Low', or 'Minimal')
        """
        if score >= self.thresholds['critical']:
            return 'Critical'
        elif score >= self.thresholds['high']:
            return 'High'
        elif score >= self.thresholds['medium']:
            return 'Medium'
        elif score >= self.thresholds['low']:
            return 'Low'
        else:
            return 'Minimal'
    
    def get_tier_weight(self, tier: int) -> float:
        """
        Get weight for a specific tier number.
        
        Args:
            tier: Tier number (1-4)
        
        Returns:
            Weight value for the tier (0.0 if tier not found)
        """
        tier_key = f'tier{tier}'
        return self.tier_weights.get(tier_key, 0.0)
    
    def validate(self) -> bool:
        """
        Validate configuration values are within acceptable ranges.
        
        Returns:
            True if configuration is valid, False otherwise
        """
        try:
            # Validate thresholds are in range 0.0-1.0
            for key, value in self.thresholds.items():
                if not (0.0 <= value <= 1.0):
                    logger.error(f"Threshold '{key}' value {value} is out of range [0.0, 1.0]")
                    return False
            
            # Validate tier weights are positive
            for key, value in self.tier_weights.items():
                if value < 0.0:
                    logger.error(f"Tier weight '{key}' value {value} is negative")
                    return False
            
            # Validate penalties are non-negative
            for key, value in self.penalties.items():
                if value < 0.0:
                    logger.error(f"Penalty '{key}' value {value} is negative")
                    return False
            
            # Validate bonuses are non-negative
            for key, value in self.bonuses.items():
                if value < 0.0:
                    logger.error(f"Bonus '{key}' value {value} is negative")
                    return False
            
            logger.info("Score configuration validation passed")
            return True
        except Exception as e:
            logger.error(f"Score configuration validation failed: {e}")
            return False
