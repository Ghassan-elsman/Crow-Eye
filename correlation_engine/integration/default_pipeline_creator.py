"""
Default Pipeline Creator

Creates a default pipeline configuration with Default Wings and their feathers.
This enables users to immediately run correlation analysis without manual setup.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ..config import PipelineConfig, WingConfig, FeatherConfig

logger = logging.getLogger(__name__)


class DefaultPipelineCreator:
    """
    Creates default pipeline configurations for cases.
    
    Loads Default Wings from the case directory, collects all feather references,
    and creates a complete pipeline ready for execution.
    """
    
    @staticmethod
    def create_default_pipeline(
        case_directory: Path,
        case_name: str
    ) -> Optional[PipelineConfig]:
        """
        Create a default pipeline for the case.
        
        Args:
            case_directory: Path to the case directory
            case_name: Name of the case
            
        Returns:
            PipelineConfig object or None if creation fails
        """
        logger.info(f"Creating default pipeline for case: {case_name}")
        
        correlation_dir = case_directory / "Correlation"
        
        if not correlation_dir.exists():
            logger.error(f"Correlation directory does not exist: {correlation_dir}")
            return None
        
        # Load Default Wings from case directory
        wings = DefaultPipelineCreator.load_default_wings_for_case(correlation_dir)
        
        if not wings:
            logger.warning("No Default Wings found in case directory")
            return None
        
        logger.info(f"Loaded {len(wings)} Default Wings")
        
        # Collect feathers from wings
        feathers_dir = correlation_dir / "feathers"
        feathers = DefaultPipelineCreator.collect_feathers_from_wings(wings, feathers_dir)
        
        logger.info(f"Collected {len(feathers)} feathers from wings")
        
        # Generate pipeline name
        pipeline_name = f"{case_name}_Default_Pipeline"
        config_name = pipeline_name.lower().replace(' ', '_')
        
        # Create pipeline config
        pipeline = PipelineConfig(
            config_name=config_name,
            pipeline_name=pipeline_name,
            description=f"Default pipeline for {case_name} with execution and user activity correlation",
            case_name=case_name,
            case_id="",
            investigator="",
            output_directory=str(correlation_dir / "output"),
            created_date=datetime.now().isoformat(),
            last_modified=datetime.now().isoformat()
        )
        
        # Add wings to pipeline
        for wing in wings:
            pipeline.add_wing_config(wing)
        
        # Add feathers to pipeline
        for feather in feathers:
            pipeline.add_feather_config(feather)
        
        # Save pipeline to pipelines directory
        pipelines_dir = correlation_dir / "pipelines"
        pipelines_dir.mkdir(parents=True, exist_ok=True)
        
        pipeline_path = pipelines_dir / f"{config_name}.json"
        
        try:
            pipeline.save_to_file(str(pipeline_path))
            logger.info(f"✓ Saved default pipeline to: {pipeline_path}")
            return pipeline
        except Exception as e:
            logger.error(f"Failed to save pipeline: {e}")
            return None
    
    @staticmethod
    def load_default_wings_for_case(correlation_directory: Path) -> List[WingConfig]:
        """
        Load Default Wings from case wings directory.
        
        Args:
            correlation_directory: Path to the Correlation directory
            
        Returns:
            List of WingConfig objects
        """
        wings_dir = correlation_directory / "wings"
        
        if not wings_dir.exists():
            logger.warning(f"Wings directory does not exist: {wings_dir}")
            return []
        
        wings = []
        
        # Look for Default Wing files
        default_wing_names = [
            "Execution_Proof_Correlation.json",
            "User_Activity_Correlation.json"
        ]
        
        for wing_filename in default_wing_names:
            wing_path = wings_dir / wing_filename
            
            if wing_path.exists():
                try:
                    wing_config = WingConfig.load_from_file(str(wing_path))
                    wings.append(wing_config)
                    logger.info(f"✓ Loaded Default Wing: {wing_config.wing_name}")
                except Exception as e:
                    logger.error(f"Failed to load wing {wing_filename}: {e}")
            else:
                logger.warning(f"Default Wing not found: {wing_filename}")
        
        return wings
    
    @staticmethod
    def collect_feathers_from_wings(
        wings: List[WingConfig],
        feathers_directory: Path
    ) -> List[FeatherConfig]:
        """
        Collect and load all feathers referenced by wings.
        
        Args:
            wings: List of WingConfig objects
            feathers_directory: Directory containing feather files
            
        Returns:
            List of FeatherConfig objects
        """
        feathers = []
        feather_names_seen = set()
        
        for wing in wings:
            logger.info(f"Collecting feathers from wing: {wing.wing_name}")
            
            for feather_ref in wing.feathers:
                feather_name = feather_ref.feather_config_name
                
                # Skip if already processed
                if feather_name in feather_names_seen:
                    continue
                
                feather_names_seen.add(feather_name)
                
                # Try to load feather config
                feather_config = DefaultPipelineCreator._load_feather_config(
                    feather_name,
                    feather_ref.feather_database_path,
                    feathers_directory
                )
                
                if feather_config:
                    feathers.append(feather_config)
                    logger.info(f"  ✓ Loaded feather: {feather_name}")
                else:
                    # Create placeholder if feather doesn't exist
                    logger.warning(f"  ⚠ Feather not found, creating placeholder: {feather_name}")
                    placeholder = DefaultPipelineCreator._create_placeholder_feather(
                        feather_name,
                        feather_ref.feather_database_path,
                        feather_ref.artifact_type,
                        feathers_directory
                    )
                    if placeholder:
                        feathers.append(placeholder)
        
        return feathers
    
    @staticmethod
    def _load_feather_config(
        feather_name: str,
        relative_db_path: str,
        feathers_directory: Path
    ) -> Optional[FeatherConfig]:
        """
        Load a feather config from JSON file.
        
        Args:
            feather_name: Name of the feather
            relative_db_path: Relative path to database (e.g., "feathers/Prefetch_CrowEyeFeather.db")
            feathers_directory: Directory containing feather files
            
        Returns:
            FeatherConfig object or None
        """
        # Try to find JSON config file
        json_path = feathers_directory / f"{feather_name}.json"
        
        if json_path.exists():
            try:
                return FeatherConfig.load_from_file(str(json_path))
            except Exception as e:
                logger.error(f"Failed to load feather config {json_path.name}: {e}")
        
        # Try to find by database filename
        db_filename = Path(relative_db_path).name
        json_by_db = feathers_directory / f"{Path(db_filename).stem}.json"
        
        if json_by_db.exists():
            try:
                return FeatherConfig.load_from_file(str(json_by_db))
            except Exception as e:
                logger.error(f"Failed to load feather config {json_by_db.name}: {e}")
        
        return None
    
    @staticmethod
    def _create_placeholder_feather(
        feather_name: str,
        relative_db_path: str,
        artifact_type: str,
        feathers_directory: Path
    ) -> Optional[FeatherConfig]:
        """
        Create a placeholder feather config for missing feathers.
        
        Args:
            feather_name: Name of the feather
            relative_db_path: Relative path to database
            artifact_type: Type of artifact
            feathers_directory: Directory containing feather files
            
        Returns:
            FeatherConfig object or None
        """
        try:
            # Resolve database path
            db_filename = Path(relative_db_path).name
            db_path = feathers_directory / db_filename
            
            # Check if database file exists
            if not db_path.exists():
                logger.warning(f"Database file does not exist: {db_path}")
                # Still create placeholder with expected path
                db_path_str = str(db_path)
            else:
                db_path_str = str(db_path)
            
            config_name = feather_name.lower().replace(' ', '_')
            
            # Create minimal placeholder config
            placeholder = FeatherConfig(
                config_name=config_name,
                feather_name=feather_name,
                artifact_type=artifact_type,
                source_database=db_path_str,
                source_table="unknown",
                selected_columns=["*"],
                column_mapping={"*": "*"},
                timestamp_column="timestamp",
                timestamp_format="%Y-%m-%d %H:%M:%S",
                output_database=db_path_str,
                description=f"Placeholder config for {feather_name} (auto-generated)"
            )
            
            return placeholder
            
        except Exception as e:
            logger.error(f"Failed to create placeholder for {feather_name}: {e}")
            return None
    
    @staticmethod
    def pipeline_exists(case_directory: Path, pipeline_name: str) -> bool:
        """
        Check if a pipeline already exists.
        
        Args:
            case_directory: Path to the case directory
            pipeline_name: Name of the pipeline
            
        Returns:
            True if pipeline exists, False otherwise
        """
        pipelines_dir = case_directory / "Correlation" / "pipelines"
        
        if not pipelines_dir.exists():
            return False
        
        config_name = pipeline_name.lower().replace(' ', '_')
        pipeline_path = pipelines_dir / f"{config_name}.json"
        
        return pipeline_path.exists()
