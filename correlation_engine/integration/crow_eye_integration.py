"""
Crow Eye Integration

Integration layer between Crow Eye case management system and the correlation engine.
Handles case directory structure initialization and pipeline configuration management.
"""

from pathlib import Path
from typing import Optional

from ..config.pipeline_config_manager import PipelineConfigurationManager


class CrowEyeIntegration:
    """
    Integration with Crow Eye case management system.
    Provides utilities for case directory management and initialization.
    """
    
    @staticmethod
    def get_case_correlation_directory(case_path: Path) -> Path:
        """
        Get correlation directory for a case.
        
        Args:
            case_path: Path to the case directory
        
        Returns:
            Path to the Correlation subdirectory
        """
        return case_path / "Correlation"
    
    @staticmethod
    def initialize_case_correlation(case_path: Path):
        """
        Initialize correlation directory structure for a case.
        Creates standard subdirectories if they don't exist.
        
        Args:
            case_path: Path to the case directory
        """
        corr_dir = CrowEyeIntegration.get_case_correlation_directory(case_path)
        
        # Create standard directory structure
        (corr_dir / "pipelines").mkdir(parents=True, exist_ok=True)
        (corr_dir / "feathers").mkdir(parents=True, exist_ok=True)
        (corr_dir / "wings").mkdir(parents=True, exist_ok=True)
        (corr_dir / "databases").mkdir(parents=True, exist_ok=True)
        (corr_dir / "results").mkdir(parents=True, exist_ok=True)
    
    @staticmethod
    def on_case_opened(case_path: Path) -> PipelineConfigurationManager:
        """
        Handle case opened event.
        Initializes correlation directory and returns configuration manager.
        
        Args:
            case_path: Path to the opened case
        
        Returns:
            PipelineConfigurationManager for the case
        """
        # Initialize directory structure
        CrowEyeIntegration.initialize_case_correlation(case_path)
        
        # Get correlation directory
        corr_dir = CrowEyeIntegration.get_case_correlation_directory(case_path)
        
        # Create and return configuration manager
        return PipelineConfigurationManager(corr_dir)
    
    @staticmethod
    def validate_case_structure(case_path: Path) -> tuple[bool, Optional[str]]:
        """
        Validate that a case has proper correlation directory structure.
        
        Args:
            case_path: Path to the case directory
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not case_path.exists():
            return False, f"Case directory does not exist: {case_path}"
        
        if not case_path.is_dir():
            return False, f"Case path is not a directory: {case_path}"
        
        corr_dir = CrowEyeIntegration.get_case_correlation_directory(case_path)
        
        # Check if correlation directory exists
        if not corr_dir.exists():
            return False, "Correlation directory not initialized"
        
        # Check for required subdirectories
        required_dirs = ["pipelines", "feathers", "wings", "databases", "results"]
        missing_dirs = []
        
        for dir_name in required_dirs:
            if not (corr_dir / dir_name).exists():
                missing_dirs.append(dir_name)
        
        if missing_dirs:
            return False, f"Missing subdirectories: {', '.join(missing_dirs)}"
        
        return True, None
    
    @staticmethod
    def get_case_name(case_path: Path) -> str:
        """
        Get case name from case path.
        
        Args:
            case_path: Path to the case directory
        
        Returns:
            Case name (directory name)
        """
        return case_path.name
