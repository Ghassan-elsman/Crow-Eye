"""
Score Configuration Migration Tool

This module provides tools to migrate existing score configurations to the
centralized score configuration system. It scans the codebase for old score
definitions, extracts values, creates a centralized configuration file, and
updates references.

Requirements validated: 17.1, 17.2, 17.3, 17.5
"""

import ast
import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

from .centralized_score_config import CentralizedScoreConfig
from .score_configuration_manager import ScoreConfigurationManager

logger = logging.getLogger(__name__)


@dataclass
class ScoreDefinitionLocation:
    """
    Represents a location where a score definition was found.
    
    Attributes:
        file_path: Path to the file containing the definition
        line_number: Line number where definition was found
        definition_type: Type of definition (threshold, tier_weight, penalty, bonus)
        key: Configuration key (e.g., 'low', 'tier1')
        value: Score value
        context: Surrounding code context
    """
    file_path: str
    line_number: int
    definition_type: str
    key: str
    value: float
    context: str = ""


@dataclass
class MigrationReport:
    """
    Report of migration operations performed.
    
    Attributes:
        timestamp: When migration was performed
        old_definitions_found: List of old score definitions found
        centralized_config_created: Whether centralized config was created
        centralized_config_path: Path to centralized config file
        references_updated: Number of references updated
        duplicates_removed: Number of duplicate definitions removed
        validation_passed: Whether validation passed
        errors: List of errors encountered
        warnings: List of warnings generated
        backup_path: Path to backup of original files
    """
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    old_definitions_found: List[ScoreDefinitionLocation] = field(default_factory=list)
    centralized_config_created: bool = False
    centralized_config_path: Optional[str] = None
    references_updated: int = 0
    duplicates_removed: int = 0
    validation_passed: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    backup_path: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert report to dictionary."""
        return {
            'timestamp': self.timestamp,
            'old_definitions_found': [
                {
                    'file_path': loc.file_path,
                    'line_number': loc.line_number,
                    'definition_type': loc.definition_type,
                    'key': loc.key,
                    'value': loc.value,
                    'context': loc.context
                }
                for loc in self.old_definitions_found
            ],
            'centralized_config_created': self.centralized_config_created,
            'centralized_config_path': self.centralized_config_path,
            'references_updated': self.references_updated,
            'duplicates_removed': self.duplicates_removed,
            'validation_passed': self.validation_passed,
            'errors': self.errors,
            'warnings': self.warnings,
            'backup_path': self.backup_path
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert report to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
    
    def save_to_file(self, file_path: str):
        """Save report to JSON file."""
        with open(file_path, 'w') as f:
            f.write(self.to_json())
        logger.info(f"Migration report saved to {file_path}")


class ScoreConfigMigrationTool:
    """
    Tool for migrating score configurations to centralized system.
    
    This tool scans the codebase for old score definitions, extracts values,
    creates a centralized configuration file, and provides validation and
    rollback capabilities.
    """
    
    def __init__(self, root_path: str = "Crow-Eye"):
        """
        Initialize migration tool.
        
        Args:
            root_path: Root path to scan for score definitions
        """
        self.root_path = Path(root_path)
        self.report = MigrationReport()
        self.backup_dir: Optional[Path] = None
        
        # Patterns to search for score definitions
        self.threshold_patterns = [
            r"threshold[s]?\s*[=:]\s*\{[^}]*'low'\s*:\s*(0\.\d+)",
            r"threshold[s]?\s*[=:]\s*\{[^}]*'medium'\s*:\s*(0\.\d+)",
            r"threshold[s]?\s*[=:]\s*\{[^}]*'high'\s*:\s*(0\.\d+)",
            r"threshold[s]?\s*[=:]\s*\{[^}]*'critical'\s*:\s*(0\.\d+)",
            r"'low'\s*:\s*(0\.\d+)",
            r"'medium'\s*:\s*(0\.\d+)",
            r"'high'\s*:\s*(0\.\d+)",
            r"'critical'\s*:\s*(0\.\d+)",
        ]
        
        self.tier_weight_patterns = [
            r"tier_weight[s]?\s*[=:]\s*\{[^}]*'tier1'\s*:\s*(\d+\.?\d*)",
            r"tier_weight[s]?\s*[=:]\s*\{[^}]*'tier2'\s*:\s*(\d+\.?\d*)",
            r"tier_weight[s]?\s*[=:]\s*\{[^}]*'tier3'\s*:\s*(\d+\.?\d*)",
            r"tier_weight[s]?\s*[=:]\s*\{[^}]*'tier4'\s*:\s*(\d+\.?\d*)",
            r"'tier1'\s*:\s*(\d+\.?\d*)",
            r"'tier2'\s*:\s*(\d+\.?\d*)",
            r"'tier3'\s*:\s*(\d+\.?\d*)",
            r"'tier4'\s*:\s*(\d+\.?\d*)",
        ]
        
        # Files to exclude from scanning
        self.exclude_patterns = [
            '**/test_*.py',
            '**/*_test.py',
            '**/tests/**',
            '**/crow_eye_venv/**',
            '**/venv/**',
            '**/__pycache__/**',
            '**/centralized_score_config.py',
            '**/score_configuration_manager.py',
            '**/score_config_migration_tool.py',
        ]
    
    def scan_for_old_definitions(self) -> List[ScoreDefinitionLocation]:
        """
        Scan codebase for old score definitions.
        
        Returns:
            List of score definition locations found
        """
        logger.info(f"Scanning {self.root_path} for old score definitions...")
        definitions = []
        
        # Find all Python files
        python_files = []
        for pattern in ['**/*.py', '**/*.json']:
            for file_path in self.root_path.rglob(pattern.split('/')[-1]):
                # Check if file should be excluded
                should_exclude = False
                for exclude_pattern in self.exclude_patterns:
                    if file_path.match(exclude_pattern):
                        should_exclude = True
                        break
                
                if not should_exclude:
                    python_files.append(file_path)
        
        logger.info(f"Found {len(python_files)} files to scan")
        
        # Scan each file
        for file_path in python_files:
            try:
                definitions.extend(self._scan_file(file_path))
            except Exception as e:
                error_msg = f"Error scanning {file_path}: {e}"
                logger.error(error_msg)
                self.report.errors.append(error_msg)
        
        logger.info(f"Found {len(definitions)} old score definitions")
        self.report.old_definitions_found = definitions
        return definitions
    
    def _scan_file(self, file_path: Path) -> List[ScoreDefinitionLocation]:
        """
        Scan a single file for score definitions.
        
        Args:
            file_path: Path to file to scan
        
        Returns:
            List of score definitions found in file
        """
        definitions = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
            
            # Search for threshold patterns
            for line_num, line in enumerate(lines, 1):
                # Skip comments
                if line.strip().startswith('#'):
                    continue
                
                # Check threshold patterns
                for pattern in self.threshold_patterns:
                    matches = re.finditer(pattern, line, re.IGNORECASE)
                    for match in matches:
                        # Extract key from pattern
                        key = self._extract_key_from_pattern(pattern, line)
                        if key:
                            value = float(match.group(1))
                            definitions.append(ScoreDefinitionLocation(
                                file_path=str(file_path),
                                line_number=line_num,
                                definition_type='threshold',
                                key=key,
                                value=value,
                                context=line.strip()
                            ))
                
                # Check tier weight patterns
                for pattern in self.tier_weight_patterns:
                    matches = re.finditer(pattern, line, re.IGNORECASE)
                    for match in matches:
                        key = self._extract_key_from_pattern(pattern, line)
                        if key:
                            value = float(match.group(1))
                            definitions.append(ScoreDefinitionLocation(
                                file_path=str(file_path),
                                line_number=line_num,
                                definition_type='tier_weight',
                                key=key,
                                value=value,
                                context=line.strip()
                            ))
        
        except Exception as e:
            logger.debug(f"Could not scan {file_path}: {e}")
        
        return definitions
    
    def _extract_key_from_pattern(self, pattern: str, line: str) -> Optional[str]:
        """
        Extract configuration key from pattern match.
        
        Args:
            pattern: Regex pattern used
            line: Line that matched
        
        Returns:
            Configuration key (e.g., 'low', 'tier1') or None
        """
        # Extract key from pattern
        for key in ['low', 'medium', 'high', 'critical', 'tier1', 'tier2', 'tier3', 'tier4']:
            if key in pattern.lower() or key in line.lower():
                return key
        return None
    
    def extract_score_values(self, definitions: List[ScoreDefinitionLocation]) -> CentralizedScoreConfig:
        """
        Extract score values from definitions and create centralized config.
        
        Uses the most common values found, or defaults if no consensus.
        
        Args:
            definitions: List of score definitions found
        
        Returns:
            CentralizedScoreConfig with extracted values
        """
        logger.info("Extracting score values from definitions...")
        
        # Group definitions by type and key
        thresholds_by_key: Dict[str, List[float]] = {}
        tier_weights_by_key: Dict[str, List[float]] = {}
        
        for definition in definitions:
            if definition.definition_type == 'threshold':
                if definition.key not in thresholds_by_key:
                    thresholds_by_key[definition.key] = []
                thresholds_by_key[definition.key].append(definition.value)
            elif definition.definition_type == 'tier_weight':
                if definition.key not in tier_weights_by_key:
                    tier_weights_by_key[definition.key] = []
                tier_weights_by_key[definition.key].append(definition.value)
        
        # Create config with most common values
        config = CentralizedScoreConfig.get_default()
        
        # Update thresholds with most common values
        for key, values in thresholds_by_key.items():
            if values:
                # Use most common value
                most_common = max(set(values), key=values.count)
                config.thresholds[key] = most_common
                
                # Warn if multiple different values found
                unique_values = set(values)
                if len(unique_values) > 1:
                    warning = f"Multiple values found for threshold '{key}': {unique_values}. Using {most_common}"
                    logger.warning(warning)
                    self.report.warnings.append(warning)
        
        # Update tier weights with most common values
        for key, values in tier_weights_by_key.items():
            if values:
                most_common = max(set(values), key=values.count)
                config.tier_weights[key] = most_common
                
                unique_values = set(values)
                if len(unique_values) > 1:
                    warning = f"Multiple values found for tier_weight '{key}': {unique_values}. Using {most_common}"
                    logger.warning(warning)
                    self.report.warnings.append(warning)
        
        logger.info("Score values extracted successfully")
        return config
    
    def create_centralized_config_file(self, config: CentralizedScoreConfig, 
                                      output_path: str = "Crow-Eye/correlation_engine/config/score_config.json") -> str:
        """
        Create centralized configuration file.
        
        Args:
            config: Configuration to save
            output_path: Path where config file should be created
        
        Returns:
            Path to created configuration file
        """
        logger.info(f"Creating centralized configuration file at {output_path}...")
        
        try:
            config.save_to_file(output_path)
            self.report.centralized_config_created = True
            self.report.centralized_config_path = output_path
            logger.info(f"Centralized configuration file created: {output_path}")
            return output_path
        except Exception as e:
            error_msg = f"Failed to create centralized config file: {e}"
            logger.error(error_msg)
            self.report.errors.append(error_msg)
            raise
    
    def create_backup(self) -> str:
        """
        Create backup of files before migration.
        
        Returns:
            Path to backup directory
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path(f"migration_backup_{timestamp}")
        backup_dir.mkdir(exist_ok=True)
        
        logger.info(f"Creating backup in {backup_dir}...")
        
        # Backup files with score definitions
        for definition in self.report.old_definitions_found:
            source_file = Path(definition.file_path)
            if source_file.exists():
                # Create relative path in backup
                rel_path = source_file.relative_to(self.root_path.parent)
                backup_file = backup_dir / rel_path
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                
                # Copy file
                shutil.copy2(source_file, backup_file)
        
        self.backup_dir = backup_dir
        self.report.backup_path = str(backup_dir)
        logger.info(f"Backup created: {backup_dir}")
        return str(backup_dir)
    
    def validate_migration(self) -> Tuple[bool, List[str]]:
        """
        Validate migration results.
        
        Checks:
        - All score references updated correctly
        - No duplicate definitions remain
        - Centralized config is valid
        
        Returns:
            Tuple of (validation_passed, list_of_issues)
        """
        logger.info("Validating migration...")
        issues = []
        
        # Check centralized config exists and is valid
        if not self.report.centralized_config_path:
            issues.append("Centralized configuration file was not created")
        else:
            try:
                config = CentralizedScoreConfig.load_from_file(self.report.centralized_config_path)
                if not config.validate():
                    issues.append("Centralized configuration failed validation")
            except Exception as e:
                issues.append(f"Failed to load centralized configuration: {e}")
        
        # Check for remaining duplicate definitions
        remaining_definitions = self.scan_for_old_definitions()
        
        # Filter out definitions in centralized config files (expected)
        remaining_definitions = [
            d for d in remaining_definitions
            if 'centralized_score_config.py' not in d.file_path
            and 'score_configuration_manager.py' not in d.file_path
            and 'score_config_migration_tool.py' not in d.file_path
            and 'score_config.json' not in d.file_path
        ]
        
        if remaining_definitions:
            issues.append(f"Found {len(remaining_definitions)} remaining score definitions that should be migrated")
            for definition in remaining_definitions[:5]:  # Show first 5
                issues.append(f"  - {definition.file_path}:{definition.line_number} ({definition.definition_type}.{definition.key})")
        
        # Check ScoreConfigurationManager is being used
        manager_usage_count = self._count_manager_usage()
        if manager_usage_count == 0:
            issues.append("ScoreConfigurationManager is not being used in any files")
        else:
            logger.info(f"Found {manager_usage_count} files using ScoreConfigurationManager")
        
        validation_passed = len(issues) == 0
        self.report.validation_passed = validation_passed
        
        if validation_passed:
            logger.info("Migration validation passed")
        else:
            logger.error(f"Migration validation failed with {len(issues)} issues")
            for issue in issues:
                logger.error(f"  - {issue}")
        
        return validation_passed, issues
    
    def _count_manager_usage(self) -> int:
        """
        Count files using ScoreConfigurationManager.
        
        Returns:
            Number of files using the manager
        """
        count = 0
        pattern = r"ScoreConfigurationManager"
        
        for file_path in self.root_path.rglob('*.py'):
            # Skip excluded files
            should_exclude = False
            for exclude_pattern in self.exclude_patterns:
                if file_path.match(exclude_pattern):
                    should_exclude = True
                    break
            
            if should_exclude:
                continue
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if re.search(pattern, content):
                        count += 1
            except Exception:
                pass
        
        return count
    
    def rollback_migration(self) -> bool:
        """
        Rollback migration using backup.
        
        Returns:
            True if rollback successful, False otherwise
        """
        if not self.backup_dir or not self.backup_dir.exists():
            logger.error("No backup directory found, cannot rollback")
            return False
        
        logger.info(f"Rolling back migration from {self.backup_dir}...")
        
        try:
            # Restore files from backup
            for backup_file in self.backup_dir.rglob('*'):
                if backup_file.is_file():
                    # Calculate original path
                    rel_path = backup_file.relative_to(self.backup_dir)
                    original_file = self.root_path.parent / rel_path
                    
                    # Restore file
                    original_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup_file, original_file)
            
            # Remove centralized config file if it was created
            if self.report.centralized_config_path:
                config_path = Path(self.report.centralized_config_path)
                if config_path.exists():
                    config_path.unlink()
                    logger.info(f"Removed centralized config file: {config_path}")
            
            logger.info("Migration rollback completed successfully")
            return True
        
        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            return False
    
    def run_migration(self, output_config_path: str = "Crow-Eye/correlation_engine/config/score_config.json",
                     create_backup: bool = True, validate: bool = True) -> MigrationReport:
        """
        Run complete migration process.
        
        Steps:
        1. Scan for old score definitions
        2. Extract score values
        3. Create backup (if requested)
        4. Create centralized configuration file
        5. Validate migration (if requested)
        
        Args:
            output_config_path: Path for centralized config file
            create_backup: Whether to create backup before migration
            validate: Whether to validate migration results
        
        Returns:
            MigrationReport with results
        """
        logger.info("Starting score configuration migration...")
        
        try:
            # Step 1: Scan for old definitions
            definitions = self.scan_for_old_definitions()
            logger.info(f"Found {len(definitions)} old score definitions")
            
            # Step 2: Extract score values
            config = self.extract_score_values(definitions)
            logger.info("Extracted score values from definitions")
            
            # Step 3: Create backup
            if create_backup:
                backup_path = self.create_backup()
                logger.info(f"Created backup at {backup_path}")
            
            # Step 4: Create centralized configuration file
            config_path = self.create_centralized_config_file(config, output_config_path)
            logger.info(f"Created centralized configuration at {config_path}")
            
            # Step 5: Validate migration
            if validate:
                validation_passed, issues = self.validate_migration()
                if not validation_passed:
                    logger.warning(f"Migration validation found {len(issues)} issues")
                    self.report.warnings.extend(issues)
                else:
                    logger.info("Migration validation passed")
            
            logger.info("Score configuration migration completed")
            
        except Exception as e:
            error_msg = f"Migration failed: {e}"
            logger.error(error_msg)
            self.report.errors.append(error_msg)
            raise
        
        return self.report
    
    def generate_migration_summary(self) -> str:
        """
        Generate human-readable migration summary.
        
        Returns:
            Formatted summary string
        """
        summary = []
        summary.append("=" * 80)
        summary.append("SCORE CONFIGURATION MIGRATION SUMMARY")
        summary.append("=" * 80)
        summary.append(f"Timestamp: {self.report.timestamp}")
        summary.append("")
        
        summary.append(f"Old Definitions Found: {len(self.report.old_definitions_found)}")
        if self.report.old_definitions_found:
            # Group by type
            by_type = {}
            for definition in self.report.old_definitions_found:
                key = f"{definition.definition_type}.{definition.key}"
                if key not in by_type:
                    by_type[key] = []
                by_type[key].append(definition)
            
            for key, defs in sorted(by_type.items()):
                summary.append(f"  - {key}: {len(defs)} occurrences")
        summary.append("")
        
        summary.append(f"Centralized Config Created: {self.report.centralized_config_created}")
        if self.report.centralized_config_path:
            summary.append(f"  Path: {self.report.centralized_config_path}")
        summary.append("")
        
        summary.append(f"Validation Passed: {self.report.validation_passed}")
        summary.append("")
        
        if self.report.warnings:
            summary.append(f"Warnings ({len(self.report.warnings)}):")
            for warning in self.report.warnings:
                summary.append(f"  - {warning}")
            summary.append("")
        
        if self.report.errors:
            summary.append(f"Errors ({len(self.report.errors)}):")
            for error in self.report.errors:
                summary.append(f"  - {error}")
            summary.append("")
        
        if self.report.backup_path:
            summary.append(f"Backup Location: {self.report.backup_path}")
            summary.append("")
        
        summary.append("=" * 80)
        
        return "\n".join(summary)
