"""
Case Initializer

Orchestrates the initialization of a case with Default Wings, feather configs, and default pipeline.
This ensures users can immediately run correlation analysis without manual setup.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .default_wings_loader import DefaultWingsLoader
from .feather_config_generator import FeatherConfigGenerator
from .default_pipeline_creator import DefaultPipelineCreator

logger = logging.getLogger(__name__)


@dataclass
class InitializationResult:
    """Result of case initialization"""
    success: bool
    case_directory: Path
    wings_copied: List[Path] = field(default_factory=list)
    feather_configs_generated: List[Path] = field(default_factory=list)
    pipeline_created: Optional[Path] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def has_errors(self) -> bool:
        """Check if initialization had errors"""
        return len(self.errors) > 0
    
    def has_warnings(self) -> bool:
        """Check if initialization had warnings"""
        return len(self.warnings) > 0
    
    def summary(self) -> str:
        """Get human-readable summary"""
        lines = []
        lines.append("=" * 60)
        lines.append("CASE INITIALIZATION SUMMARY")
        lines.append("=" * 60)
        lines.append(f"Case: {self.case_directory.name}")
        lines.append(f"Status: {'✓ SUCCESS' if self.success else '❌ FAILED'}")
        lines.append("")
        lines.append(f"Wings Copied: {len(self.wings_copied)}")
        for wing_path in self.wings_copied:
            lines.append(f"  ✓ {wing_path.name}")
        lines.append("")
        lines.append(f"Feather Configs Generated: {len(self.feather_configs_generated)}")
        for config_path in self.feather_configs_generated:
            lines.append(f"  ✓ {config_path.name}")
        lines.append("")
        if self.pipeline_created:
            lines.append(f"Pipeline Created: ✓ {self.pipeline_created.name}")
        else:
            lines.append("Pipeline Created: ❌ None")
        
        if self.warnings:
            lines.append("")
            lines.append(f"Warnings ({len(self.warnings)}):")
            for warning in self.warnings:
                lines.append(f"  ⚠ {warning}")
        
        if self.errors:
            lines.append("")
            lines.append(f"Errors ({len(self.errors)}):")
            for error in self.errors:
                lines.append(f"  ❌ {error}")
        
        lines.append("=" * 60)
        return "\n".join(lines)


class CaseInitializer:
    """
    Orchestrates case initialization process.
    
    Handles copying Default Wings, generating feather configs,
    and creating default pipeline for a case.
    """
    
    @staticmethod
    def initialize_case(case_directory: Path) -> InitializationResult:
        """
        Initialize a case with Default Wings and configurations.
        
        Args:
            case_directory: Path to the case directory
            
        Returns:
            InitializationResult with status and details
        """
        logger.info(f"Initializing case: {case_directory}")
        
        result = InitializationResult(
            success=False,
            case_directory=case_directory
        )
        
        # Validate case directory
        if not case_directory.exists():
            error_msg = f"Case directory does not exist: {case_directory}"
            logger.error(error_msg)
            result.errors.append(error_msg)
            return result
        
        # Create Correlation directory structure if needed
        correlation_dir = case_directory / "Correlation"
        
        try:
            correlation_dir.mkdir(parents=True, exist_ok=True)
            (correlation_dir / "feathers").mkdir(exist_ok=True)
            (correlation_dir / "wings").mkdir(exist_ok=True)
            (correlation_dir / "pipelines").mkdir(exist_ok=True)
            (correlation_dir / "output").mkdir(exist_ok=True)
            logger.info("✓ Correlation directory structure created")
        except Exception as e:
            error_msg = f"Failed to create Correlation directory structure: {e}"
            logger.error(error_msg)
            result.errors.append(error_msg)
            return result
        
        # Step 1: Copy Default Wings
        logger.info("Step 1: Copying Default Wings...")
        try:
            wings_copied = DefaultWingsLoader.initialize_case_wings_directory(correlation_dir)
            result.wings_copied = wings_copied
            
            if wings_copied:
                logger.info(f"✓ Copied {len(wings_copied)} Default Wings")
            else:
                info_msg = "No Default Wings were copied (already exist)"
                logger.info(info_msg)
                # Don't add to warnings - this is normal for existing cases
        except Exception as e:
            error_msg = f"Failed to copy Default Wings: {e}"
            logger.error(error_msg)
            result.errors.append(error_msg)
            # Continue with other steps
        
        # Step 2: Generate missing feather configs
        logger.info("Step 2: Generating missing feather configs...")
        try:
            feathers_dir = correlation_dir / "feathers"
            configs_generated = FeatherConfigGenerator.generate_missing_configs(feathers_dir)
            result.feather_configs_generated = configs_generated
            
            if configs_generated:
                logger.info(f"✓ Generated {len(configs_generated)} feather configs")
            else:
                logger.info("No feather configs needed to be generated")
        except Exception as e:
            error_msg = f"Failed to generate feather configs: {e}"
            logger.error(error_msg)
            result.errors.append(error_msg)
            # Continue with other steps
        
        # Step 3: Create default pipeline
        logger.info("Step 3: Creating default pipeline...")
        try:
            # Extract case name from directory
            case_name = CaseInitializer._extract_case_name(case_directory)
            
            # Check if default pipeline already exists
            pipeline_name = f"{case_name}_Default_Pipeline"
            
            if DefaultPipelineCreator.pipeline_exists(case_directory, pipeline_name):
                info_msg = f"Default pipeline already exists: {pipeline_name}"
                logger.info(info_msg)
                # Don't add to warnings - this is normal for existing cases
            else:
                pipeline = DefaultPipelineCreator.create_default_pipeline(
                    case_directory,
                    case_name
                )
                
                if pipeline:
                    config_name = pipeline_name.lower().replace(' ', '_')
                    result.pipeline_created = correlation_dir / "pipelines" / f"{config_name}.json"
                    logger.info(f"✓ Created default pipeline: {pipeline_name}")
                else:
                    warning_msg = "Failed to create default pipeline"
                    logger.warning(warning_msg)
                    result.warnings.append(warning_msg)
        except Exception as e:
            error_msg = f"Failed to create default pipeline: {e}"
            logger.error(error_msg)
            result.errors.append(error_msg)
        
        # Determine overall success
        result.success = not result.has_errors()
        
        # Log summary
        logger.info("\n" + result.summary())
        
        return result
    
    @staticmethod
    def is_case_initialized(case_directory: Path) -> bool:
        """
        Check if case has been initialized.
        
        Args:
            case_directory: Path to the case directory
            
        Returns:
            True if case is initialized, False otherwise
        """
        correlation_dir = case_directory / "Correlation"
        
        if not correlation_dir.exists():
            return False
        
        # Check for key indicators of initialization
        wings_dir = correlation_dir / "wings"
        pipelines_dir = correlation_dir / "pipelines"
        
        # Check if Default Wings exist
        default_wings_exist = False
        if wings_dir.exists():
            default_wing_files = [
                "Execution_Proof_Correlation.json",
                "User_Activity_Correlation.json"
            ]
            for wing_file in default_wing_files:
                if (wings_dir / wing_file).exists():
                    default_wings_exist = True
                    break
        
        # Check if any pipeline exists
        pipelines_exist = False
        if pipelines_dir.exists():
            pipeline_files = list(pipelines_dir.glob("*.json"))
            pipelines_exist = len(pipeline_files) > 0
        
        # Case is considered initialized if it has Default Wings or pipelines
        return default_wings_exist or pipelines_exist
    
    @staticmethod
    def get_initialization_status(case_directory: Path) -> dict:
        """
        Get detailed initialization status.
        
        Args:
            case_directory: Path to the case directory
            
        Returns:
            Dictionary with initialization status details
        """
        status = {
            'initialized': False,
            'correlation_dir_exists': False,
            'default_wings_exist': False,
            'default_wings_count': 0,
            'feather_configs_exist': False,
            'feather_configs_count': 0,
            'pipelines_exist': False,
            'pipelines_count': 0,
            'default_pipeline_exists': False
        }
        
        correlation_dir = case_directory / "Correlation"
        
        if not correlation_dir.exists():
            return status
        
        status['correlation_dir_exists'] = True
        
        # Check Default Wings
        wings_dir = correlation_dir / "wings"
        if wings_dir.exists():
            default_wing_files = [
                "Execution_Proof_Correlation.json",
                "User_Activity_Correlation.json"
            ]
            wings_found = 0
            for wing_file in default_wing_files:
                if (wings_dir / wing_file).exists():
                    wings_found += 1
            
            status['default_wings_exist'] = wings_found > 0
            status['default_wings_count'] = wings_found
        
        # Check feather configs
        feathers_dir = correlation_dir / "feathers"
        if feathers_dir.exists():
            config_files = list(feathers_dir.glob("*.json"))
            status['feather_configs_exist'] = len(config_files) > 0
            status['feather_configs_count'] = len(config_files)
        
        # Check pipelines
        pipelines_dir = correlation_dir / "pipelines"
        if pipelines_dir.exists():
            pipeline_files = list(pipelines_dir.glob("*.json"))
            status['pipelines_exist'] = len(pipeline_files) > 0
            status['pipelines_count'] = len(pipeline_files)
            
            # Check for default pipeline
            case_name = CaseInitializer._extract_case_name(case_directory)
            default_pipeline_name = f"{case_name}_Default_Pipeline"
            config_name = default_pipeline_name.lower().replace(' ', '_')
            default_pipeline_path = pipelines_dir / f"{config_name}.json"
            status['default_pipeline_exists'] = default_pipeline_path.exists()
        
        # Overall initialization status
        status['initialized'] = (
            status['default_wings_exist'] or 
            status['pipelines_exist']
        )
        
        return status
    
    @staticmethod
    def _extract_case_name(case_directory: Path) -> str:
        """
        Extract case name from case directory path.
        
        Args:
            case_directory: Path to the case directory
            
        Returns:
            Extracted case name
        """
        import re
        
        # Get the directory name (last component of path)
        case_name = case_directory.name
        
        # Clean up the case name (remove special characters, keep alphanumeric and spaces)
        case_name = re.sub(r'[^\w\s-]', '', case_name)
        case_name = case_name.strip()
        
        # If empty after cleaning, use a default
        if not case_name:
            case_name = "UnknownCase"
        
        return case_name
