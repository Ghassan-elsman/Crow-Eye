"""
Case-Specific Configuration Manager

Manages case-specific configurations for semantic mappings and weighted scoring.
Provides storage, loading, validation, and management of case-specific settings
that override global configurations.

Features:
- Case-specific semantic mapping storage and loading
- Case-specific scoring weight storage and loading
- Configuration file management and validation
- Automatic case configuration discovery
- Configuration inheritance and merging
- Configuration export/import capabilities
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict, field
from datetime import datetime
import shutil

from .semantic_mapping import SemanticMapping, SemanticMappingManager
from .integrated_configuration_manager import CaseSpecificConfig, SemanticMappingConfig, WeightedScoringConfig

logger = logging.getLogger(__name__)


@dataclass
class CaseSemanticMappingConfig:
    """Case-specific semantic mapping configuration"""
    case_id: str
    enabled: bool = True
    mappings: List[Dict[str, Any]] = field(default_factory=list)
    inherit_global: bool = True
    override_global: bool = False
    created_date: str = field(default_factory=lambda: datetime.now().isoformat())
    last_modified: str = field(default_factory=lambda: datetime.now().isoformat())
    description: str = ""
    version: str = "1.0"


@dataclass
class CaseScoringWeightsConfig:
    """Case-specific scoring weights configuration"""
    case_id: str
    enabled: bool = True
    default_weights: Dict[str, float] = field(default_factory=dict)
    score_interpretation: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    tier_definitions: Dict[int, str] = field(default_factory=dict)
    validation_rules: Dict[str, Any] = field(default_factory=dict)
    inherit_global: bool = True
    override_global: bool = False
    created_date: str = field(default_factory=lambda: datetime.now().isoformat())
    last_modified: str = field(default_factory=lambda: datetime.now().isoformat())
    description: str = ""
    version: str = "1.0"


@dataclass
class CaseConfigurationMetadata:
    """Metadata for case configuration"""
    case_id: str
    case_name: str = ""
    description: str = ""
    created_date: str = field(default_factory=lambda: datetime.now().isoformat())
    last_modified: str = field(default_factory=lambda: datetime.now().isoformat())
    created_by: str = ""
    tags: List[str] = field(default_factory=list)
    version: str = "1.0"
    has_semantic_mappings: bool = False
    has_scoring_weights: bool = False
    configuration_size: int = 0
    last_used: str = ""


class CaseSpecificConfigurationManager:
    """
    Manager for case-specific configurations.
    
    Handles storage, loading, and management of case-specific semantic mappings
    and scoring weights that override global configurations.
    """
    
    def __init__(self, cases_directory: str = "cases"):
        """
        Initialize case-specific configuration manager.
        
        Args:
            cases_directory: Root directory for storing case configurations
        """
        self.cases_dir = Path(cases_directory)
        self.cases_dir.mkdir(parents=True, exist_ok=True)
        
        # Configuration file names
        self.semantic_mappings_filename = "semantic_mappings.json"
        self.scoring_weights_filename = "scoring_weights.json"
        self.metadata_filename = "case_metadata.json"
        
        # Cache for loaded configurations
        self._semantic_mappings_cache: Dict[str, CaseSemanticMappingConfig] = {}
        self._scoring_weights_cache: Dict[str, CaseScoringWeightsConfig] = {}
        self._metadata_cache: Dict[str, CaseConfigurationMetadata] = {}
        
        logger.info(f"Initialized case-specific configuration manager with directory: {self.cases_dir}")
    
    def create_case_directory(self, case_id: str) -> Path:
        """
        Create directory structure for a case.
        
        Args:
            case_id: Case identifier
            
        Returns:
            Path to case directory
        """
        case_dir = self.cases_dir / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectories for organization
        (case_dir / "configs").mkdir(exist_ok=True)
        (case_dir / "exports").mkdir(exist_ok=True)
        (case_dir / "backups").mkdir(exist_ok=True)
        
        logger.info(f"Created case directory structure for case: {case_id}")
        return case_dir
    
    def get_case_directory(self, case_id: str) -> Path:
        """
        Get path to case directory.
        
        Args:
            case_id: Case identifier
            
        Returns:
            Path to case directory
        """
        return self.cases_dir / case_id
    
    def case_exists(self, case_id: str) -> bool:
        """
        Check if case configuration exists.
        
        Args:
            case_id: Case identifier
            
        Returns:
            True if case exists, False otherwise
        """
        case_dir = self.get_case_directory(case_id)
        return case_dir.exists()
    
    def list_cases(self) -> List[str]:
        """
        List all available cases.
        
        Returns:
            List of case IDs
        """
        if not self.cases_dir.exists():
            return []
        
        cases = []
        for item in self.cases_dir.iterdir():
            if item.is_dir():
                cases.append(item.name)
        
        return sorted(cases)
    
    def get_case_metadata(self, case_id: str) -> Optional[CaseConfigurationMetadata]:
        """
        Get metadata for a case.
        
        Args:
            case_id: Case identifier
            
        Returns:
            CaseConfigurationMetadata if found, None otherwise
        """
        # Check cache first
        if case_id in self._metadata_cache:
            return self._metadata_cache[case_id]
        
        case_dir = self.get_case_directory(case_id)
        metadata_path = case_dir / self.metadata_filename
        
        if not metadata_path.exists():
            # Create default metadata
            metadata = CaseConfigurationMetadata(
                case_id=case_id,
                case_name=case_id,
                has_semantic_mappings=self.has_semantic_mappings(case_id),
                has_scoring_weights=self.has_scoring_weights(case_id)
            )
            self.save_case_metadata(metadata)
            return metadata
        
        try:
            with open(metadata_path, 'r') as f:
                metadata_data = json.load(f)
            
            metadata = CaseConfigurationMetadata(**metadata_data)
            
            # Update dynamic fields
            metadata.has_semantic_mappings = self.has_semantic_mappings(case_id)
            metadata.has_scoring_weights = self.has_scoring_weights(case_id)
            
            # Cache the metadata
            self._metadata_cache[case_id] = metadata
            
            return metadata
            
        except Exception as e:
            logger.error(f"Failed to load case metadata for {case_id}: {e}")
            return None
    
    def save_case_metadata(self, metadata: CaseConfigurationMetadata) -> bool:
        """
        Save case metadata.
        
        Args:
            metadata: Metadata to save
            
        Returns:
            True if saved successfully, False otherwise
        """
        try:
            case_dir = self.create_case_directory(metadata.case_id)
            metadata_path = case_dir / self.metadata_filename
            
            # Update last modified
            metadata.last_modified = datetime.now().isoformat()
            
            # Update dynamic fields
            metadata.has_semantic_mappings = self.has_semantic_mappings(metadata.case_id)
            metadata.has_scoring_weights = self.has_scoring_weights(metadata.case_id)
            
            with open(metadata_path, 'w') as f:
                json.dump(asdict(metadata), f, indent=2)
            
            # Update cache
            self._metadata_cache[metadata.case_id] = metadata
            
            logger.info(f"Saved case metadata for case: {metadata.case_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save case metadata for {metadata.case_id}: {e}")
            return False
    
    # Semantic Mappings Management
    
    def has_semantic_mappings(self, case_id: str) -> bool:
        """
        Check if case has semantic mappings configuration.
        
        Args:
            case_id: Case identifier
            
        Returns:
            True if case has semantic mappings, False otherwise
        """
        case_dir = self.get_case_directory(case_id)
        semantic_path = case_dir / self.semantic_mappings_filename
        return semantic_path.exists()
    
    def load_case_semantic_mappings(self, case_id: str) -> Optional[CaseSemanticMappingConfig]:
        """
        Load case-specific semantic mappings.
        
        Args:
            case_id: Case identifier
            
        Returns:
            CaseSemanticMappingConfig if found, None otherwise
        """
        # Check cache first
        if case_id in self._semantic_mappings_cache:
            return self._semantic_mappings_cache[case_id]
        
        case_dir = self.get_case_directory(case_id)
        semantic_path = case_dir / self.semantic_mappings_filename
        
        if not semantic_path.exists():
            logger.info(f"No semantic mappings found for case: {case_id}")
            return None
        
        try:
            with open(semantic_path, 'r') as f:
                semantic_data = json.load(f)
            
            config = CaseSemanticMappingConfig(**semantic_data)
            
            # Cache the configuration
            self._semantic_mappings_cache[case_id] = config
            
            logger.info(f"Loaded case-specific semantic mappings for case: {case_id}")
            return config
            
        except Exception as e:
            logger.error(f"Failed to load case semantic mappings for {case_id}: {e}")
            return None
    
    def save_case_semantic_mappings(self, config: CaseSemanticMappingConfig) -> bool:
        """
        Save case-specific semantic mappings.
        
        Args:
            config: Semantic mappings configuration to save
            
        Returns:
            True if saved successfully, False otherwise
        """
        try:
            case_dir = self.create_case_directory(config.case_id)
            semantic_path = case_dir / self.semantic_mappings_filename
            
            # Update last modified
            config.last_modified = datetime.now().isoformat()
            
            with open(semantic_path, 'w') as f:
                json.dump(asdict(config), f, indent=2)
            
            # Update cache
            self._semantic_mappings_cache[config.case_id] = config
            
            # Update metadata
            metadata = self.get_case_metadata(config.case_id)
            if metadata:
                metadata.has_semantic_mappings = True
                metadata.last_modified = config.last_modified
                self.save_case_metadata(metadata)
            
            logger.info(f"Saved case-specific semantic mappings for case: {config.case_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save case semantic mappings for {config.case_id}: {e}")
            return False
    
    def create_default_semantic_mappings(self, case_id: str, case_name: str = "") -> CaseSemanticMappingConfig:
        """
        Create default semantic mappings configuration for a case.
        
        Args:
            case_id: Case identifier
            case_name: Optional case name
            
        Returns:
            Default CaseSemanticMappingConfig
        """
        config = CaseSemanticMappingConfig(
            case_id=case_id,
            enabled=True,
            mappings=[],
            inherit_global=True,
            override_global=False,
            description=f"Semantic mappings for case: {case_name or case_id}"
        )
        
        return config
    
    # Scoring Weights Management
    
    def has_scoring_weights(self, case_id: str) -> bool:
        """
        Check if case has scoring weights configuration.
        
        Args:
            case_id: Case identifier
            
        Returns:
            True if case has scoring weights, False otherwise
        """
        case_dir = self.get_case_directory(case_id)
        scoring_path = case_dir / self.scoring_weights_filename
        return scoring_path.exists()
    
    def load_case_scoring_weights(self, case_id: str) -> Optional[CaseScoringWeightsConfig]:
        """
        Load case-specific scoring weights.
        
        Args:
            case_id: Case identifier
            
        Returns:
            CaseScoringWeightsConfig if found, None otherwise
        """
        # Check cache first
        if case_id in self._scoring_weights_cache:
            return self._scoring_weights_cache[case_id]
        
        case_dir = self.get_case_directory(case_id)
        scoring_path = case_dir / self.scoring_weights_filename
        
        if not scoring_path.exists():
            logger.info(f"No scoring weights found for case: {case_id}")
            return None
        
        try:
            with open(scoring_path, 'r') as f:
                scoring_data = json.load(f)
            
            config = CaseScoringWeightsConfig(**scoring_data)
            
            # Cache the configuration
            self._scoring_weights_cache[case_id] = config
            
            logger.info(f"Loaded case-specific scoring weights for case: {case_id}")
            return config
            
        except Exception as e:
            logger.error(f"Failed to load case scoring weights for {case_id}: {e}")
            return None
    
    def save_case_scoring_weights(self, config: CaseScoringWeightsConfig) -> bool:
        """
        Save case-specific scoring weights.
        
        Args:
            config: Scoring weights configuration to save
            
        Returns:
            True if saved successfully, False otherwise
        """
        try:
            case_dir = self.create_case_directory(config.case_id)
            scoring_path = case_dir / self.scoring_weights_filename
            
            # Update last modified
            config.last_modified = datetime.now().isoformat()
            
            with open(scoring_path, 'w') as f:
                json.dump(asdict(config), f, indent=2)
            
            # Update cache
            self._scoring_weights_cache[config.case_id] = config
            
            # Update metadata
            metadata = self.get_case_metadata(config.case_id)
            if metadata:
                metadata.has_scoring_weights = True
                metadata.last_modified = config.last_modified
                self.save_case_metadata(metadata)
            
            logger.info(f"Saved case-specific scoring weights for case: {config.case_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save case scoring weights for {config.case_id}: {e}")
            return False
    
    def create_default_scoring_weights(self, case_id: str, case_name: str = "") -> CaseScoringWeightsConfig:
        """
        Create default scoring weights configuration for a case.
        
        Args:
            case_id: Case identifier
            case_name: Optional case name
            
        Returns:
            Default CaseScoringWeightsConfig
        """
        config = CaseScoringWeightsConfig(
            case_id=case_id,
            enabled=True,
            default_weights={
                "Logs": 0.4,
                "Prefetch": 0.3,
                "SRUM": 0.2,
                "AmCache": 0.15,
                "ShimCache": 0.15,
                "Jumplists": 0.1,
                "LNK": 0.1,
                "MFT": 0.05,
                "USN": 0.05
            },
            score_interpretation={
                "confirmed": {"min": 0.8, "label": "Confirmed Execution"},
                "probable": {"min": 0.5, "label": "Probable Match"},
                "weak": {"min": 0.2, "label": "Weak Evidence"},
                "minimal": {"min": 0.0, "label": "Minimal Evidence"}
            },
            tier_definitions={
                1: "Primary Evidence",
                2: "Supporting Evidence", 
                3: "Contextual Evidence",
                4: "Background Evidence"
            },
            validation_rules={
                "max_weight": 1.0,
                "min_weight": 0.0,
                "max_tier": 4,
                "min_tier": 1,
                "require_positive_weights": True,
                "allow_zero_weights": True
            },
            inherit_global=True,
            override_global=False,
            description=f"Scoring weights for case: {case_name or case_id}"
        )
        
        return config
    
    # Configuration Management Operations
    
    def delete_case_configuration(self, case_id: str, backup: bool = True) -> bool:
        """
        Delete case configuration.
        
        Args:
            case_id: Case identifier
            backup: Whether to create backup before deletion
            
        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            case_dir = self.get_case_directory(case_id)
            
            if not case_dir.exists():
                logger.warning(f"Case configuration does not exist: {case_id}")
                return True
            
            if backup:
                backup_success = self.backup_case_configuration(case_id)
                if not backup_success:
                    logger.warning(f"Failed to create backup for case {case_id}, proceeding with deletion")
            
            # Remove from caches
            self._semantic_mappings_cache.pop(case_id, None)
            self._scoring_weights_cache.pop(case_id, None)
            self._metadata_cache.pop(case_id, None)
            
            # Delete directory
            shutil.rmtree(case_dir)
            
            logger.info(f"Deleted case configuration for case: {case_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete case configuration for {case_id}: {e}")
            return False
    
    def copy_case_configuration(self, source_case_id: str, target_case_id: str, 
                              copy_semantic_mappings: bool = True,
                              copy_scoring_weights: bool = True) -> bool:
        """
        Copy configuration from one case to another.
        
        Args:
            source_case_id: Source case identifier
            target_case_id: Target case identifier
            copy_semantic_mappings: Whether to copy semantic mappings
            copy_scoring_weights: Whether to copy scoring weights
            
        Returns:
            True if copied successfully, False otherwise
        """
        try:
            if not self.case_exists(source_case_id):
                logger.error(f"Source case does not exist: {source_case_id}")
                return False
            
            # Copy semantic mappings
            if copy_semantic_mappings and self.has_semantic_mappings(source_case_id):
                source_semantic = self.load_case_semantic_mappings(source_case_id)
                if source_semantic:
                    target_semantic = CaseSemanticMappingConfig(
                        case_id=target_case_id,
                        enabled=source_semantic.enabled,
                        mappings=source_semantic.mappings.copy(),
                        inherit_global=source_semantic.inherit_global,
                        override_global=source_semantic.override_global,
                        description=f"Copied from case: {source_case_id}"
                    )
                    self.save_case_semantic_mappings(target_semantic)
            
            # Copy scoring weights
            if copy_scoring_weights and self.has_scoring_weights(source_case_id):
                source_scoring = self.load_case_scoring_weights(source_case_id)
                if source_scoring:
                    target_scoring = CaseScoringWeightsConfig(
                        case_id=target_case_id,
                        enabled=source_scoring.enabled,
                        default_weights=source_scoring.default_weights.copy(),
                        score_interpretation=source_scoring.score_interpretation.copy(),
                        tier_definitions=source_scoring.tier_definitions.copy(),
                        validation_rules=source_scoring.validation_rules.copy(),
                        inherit_global=source_scoring.inherit_global,
                        override_global=source_scoring.override_global,
                        description=f"Copied from case: {source_case_id}"
                    )
                    self.save_case_scoring_weights(target_scoring)
            
            # Copy metadata
            source_metadata = self.get_case_metadata(source_case_id)
            if source_metadata:
                target_metadata = CaseConfigurationMetadata(
                    case_id=target_case_id,
                    case_name=f"{source_metadata.case_name} (Copy)",
                    description=f"Copied from case: {source_case_id}",
                    tags=source_metadata.tags.copy()
                )
                self.save_case_metadata(target_metadata)
            
            logger.info(f"Copied case configuration from {source_case_id} to {target_case_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to copy case configuration from {source_case_id} to {target_case_id}: {e}")
            return False
    
    def backup_case_configuration(self, case_id: str) -> bool:
        """
        Create backup of case configuration.
        
        Args:
            case_id: Case identifier
            
        Returns:
            True if backup created successfully, False otherwise
        """
        try:
            case_dir = self.get_case_directory(case_id)
            
            if not case_dir.exists():
                logger.warning(f"Case configuration does not exist: {case_id}")
                return False
            
            # Create backup directory
            backup_dir = case_dir / "backups"
            backup_dir.mkdir(exist_ok=True)
            
            # Create timestamped backup
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"backup_{timestamp}"
            backup_path = backup_dir / backup_name
            backup_path.mkdir(exist_ok=True)
            
            # Copy configuration files
            for filename in [self.semantic_mappings_filename, self.scoring_weights_filename, self.metadata_filename]:
                source_file = case_dir / filename
                if source_file.exists():
                    target_file = backup_path / filename
                    shutil.copy2(source_file, target_file)
            
            logger.info(f"Created backup for case {case_id}: {backup_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create backup for case {case_id}: {e}")
            return False
    
    def export_case_configuration(self, case_id: str, export_path: str) -> bool:
        """
        Export case configuration to file.
        
        Args:
            case_id: Case identifier
            export_path: Path to export file
            
        Returns:
            True if exported successfully, False otherwise
        """
        try:
            export_data = {
                'case_id': case_id,
                'export_timestamp': datetime.now().isoformat(),
                'version': '1.0'
            }
            
            # Add metadata
            metadata = self.get_case_metadata(case_id)
            if metadata:
                export_data['metadata'] = asdict(metadata)
            
            # Add semantic mappings
            semantic_config = self.load_case_semantic_mappings(case_id)
            if semantic_config:
                export_data['semantic_mappings'] = asdict(semantic_config)
            
            # Add scoring weights
            scoring_config = self.load_case_scoring_weights(case_id)
            if scoring_config:
                export_data['scoring_weights'] = asdict(scoring_config)
            
            # Write export file
            with open(export_path, 'w') as f:
                json.dump(export_data, f, indent=2)
            
            logger.info(f"Exported case configuration for {case_id} to {export_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to export case configuration for {case_id}: {e}")
            return False
    
    def import_case_configuration(self, import_path: str, target_case_id: Optional[str] = None) -> bool:
        """
        Import case configuration from file.
        
        Args:
            import_path: Path to import file
            target_case_id: Optional target case ID (uses original if not specified)
            
        Returns:
            True if imported successfully, False otherwise
        """
        try:
            with open(import_path, 'r') as f:
                import_data = json.load(f)
            
            case_id = target_case_id or import_data.get('case_id')
            if not case_id:
                logger.error("No case ID specified for import")
                return False
            
            # Import metadata
            if 'metadata' in import_data:
                metadata_data = import_data['metadata']
                metadata_data['case_id'] = case_id  # Update case ID
                metadata = CaseConfigurationMetadata(**metadata_data)
                self.save_case_metadata(metadata)
            
            # Import semantic mappings
            if 'semantic_mappings' in import_data:
                semantic_data = import_data['semantic_mappings']
                semantic_data['case_id'] = case_id  # Update case ID
                semantic_config = CaseSemanticMappingConfig(**semantic_data)
                self.save_case_semantic_mappings(semantic_config)
            
            # Import scoring weights
            if 'scoring_weights' in import_data:
                scoring_data = import_data['scoring_weights']
                scoring_data['case_id'] = case_id  # Update case ID
                scoring_config = CaseScoringWeightsConfig(**scoring_data)
                self.save_case_scoring_weights(scoring_config)
            
            logger.info(f"Imported case configuration for {case_id} from {import_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to import case configuration from {import_path}: {e}")
            return False
    
    def validate_case_configuration(self, case_id: str) -> Dict[str, Any]:
        """
        Validate case configuration for correctness.
        
        Args:
            case_id: Case identifier
            
        Returns:
            Dictionary with validation results
        """
        validation_result = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'case_id': case_id,
            'has_semantic_mappings': False,
            'has_scoring_weights': False,
            'metadata_valid': False
        }
        
        try:
            # Validate metadata
            metadata = self.get_case_metadata(case_id)
            if metadata:
                validation_result['metadata_valid'] = True
            else:
                validation_result['warnings'].append("No metadata found for case")
            
            # Validate semantic mappings
            if self.has_semantic_mappings(case_id):
                validation_result['has_semantic_mappings'] = True
                semantic_config = self.load_case_semantic_mappings(case_id)
                if not semantic_config:
                    validation_result['errors'].append("Failed to load semantic mappings")
                    validation_result['valid'] = False
                else:
                    # Validate semantic mappings structure
                    if not isinstance(semantic_config.mappings, list):
                        validation_result['errors'].append("Semantic mappings must be a list")
                        validation_result['valid'] = False
            
            # Validate scoring weights
            if self.has_scoring_weights(case_id):
                validation_result['has_scoring_weights'] = True
                scoring_config = self.load_case_scoring_weights(case_id)
                if not scoring_config:
                    validation_result['errors'].append("Failed to load scoring weights")
                    validation_result['valid'] = False
                else:
                    # Validate scoring weights structure
                    if not isinstance(scoring_config.default_weights, dict):
                        validation_result['errors'].append("Default weights must be a dictionary")
                        validation_result['valid'] = False
                    
                    # Validate weight values
                    for artifact_type, weight in scoring_config.default_weights.items():
                        if not isinstance(weight, (int, float)) or weight < 0 or weight > 1:
                            validation_result['errors'].append(f"Invalid weight for {artifact_type}: {weight}")
                            validation_result['valid'] = False
            
            if not validation_result['has_semantic_mappings'] and not validation_result['has_scoring_weights']:
                validation_result['warnings'].append("Case has no custom configurations")
            
        except Exception as e:
            validation_result['valid'] = False
            validation_result['errors'].append(f"Validation failed: {e}")
        
        return validation_result
    
    def clear_cache(self, case_id: Optional[str] = None):
        """
        Clear configuration cache.
        
        Args:
            case_id: Optional case ID to clear specific cache, clears all if None
        """
        if case_id:
            self._semantic_mappings_cache.pop(case_id, None)
            self._scoring_weights_cache.pop(case_id, None)
            self._metadata_cache.pop(case_id, None)
            logger.info(f"Cleared cache for case: {case_id}")
        else:
            self._semantic_mappings_cache.clear()
            self._scoring_weights_cache.clear()
            self._metadata_cache.clear()
            logger.info("Cleared all configuration caches")
    
    def get_configuration_summary(self) -> Dict[str, Any]:
        """
        Get summary of all case configurations.
        
        Returns:
            Dictionary with configuration summary
        """
        cases = self.list_cases()
        summary = {
            'total_cases': len(cases),
            'cases_with_semantic_mappings': 0,
            'cases_with_scoring_weights': 0,
            'cases_with_both': 0,
            'cases': []
        }
        
        for case_id in cases:
            has_semantic = self.has_semantic_mappings(case_id)
            has_scoring = self.has_scoring_weights(case_id)
            
            if has_semantic:
                summary['cases_with_semantic_mappings'] += 1
            if has_scoring:
                summary['cases_with_scoring_weights'] += 1
            if has_semantic and has_scoring:
                summary['cases_with_both'] += 1
            
            metadata = self.get_case_metadata(case_id)
            case_info = {
                'case_id': case_id,
                'has_semantic_mappings': has_semantic,
                'has_scoring_weights': has_scoring,
                'last_modified': metadata.last_modified if metadata else None,
                'description': metadata.description if metadata else ""
            }
            summary['cases'].append(case_info)
        
        return summary