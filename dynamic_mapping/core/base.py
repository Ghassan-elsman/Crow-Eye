"""
Base classes for core components of the Dynamic Linking Intelligence Engine.
"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseComponent(ABC):
    """
    Base class for all core components of the intelligence engine.
    
    Provides common functionality and interface for all components.
    """
    
    def __init__(self, name: str):
        """
        Initialize a base component.
        
        Args:
            name: Component identifier
        """
        self.name = name
    
    @abstractmethod
    def validate(self) -> bool:
        """
        Validate component configuration.
        
        Returns:
            True if valid, False otherwise
        """
        pass
    
    @abstractmethod
    def initialize(self) -> bool:
        """
        Initialize component for use.
        
        Returns:
            True if initialization successful, False otherwise
        """
        pass
    
    @abstractmethod
    def cleanup(self) -> None:
        """
        Clean up component resources.
        """
        pass