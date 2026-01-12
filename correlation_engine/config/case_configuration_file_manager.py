"""
Case Configuration File Manager

Provides file-level operations for case-specific configurations.
Handles file I/O, validation, migration, and maintenance operations
for case configuration files.

Features:
- Configuration file validation and repair
- File format migration and versioning
- Configuration file compression and archiving
- Automatic cleanup and maintenance
- File integrity checking
- Configuration file templates
"""

import json
import logging
import gzip
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import hashlib
import tempfile

logger = logging.getLogger(__name__)


@dataclass
class ConfigurationFileInfo:
    """Information about a configuration file"""
    file_path: Path
    file_type: str  # 'semantic_mappings', 'scoring_weights', 'metadata'
    case_id: str
    file_size: int
    last_modified: datetime
    checksum: str
    version: str
    is_valid: bool
    validation_errors: List[str]


@dataclass
class ConfigurationTemplate:
    """Template for creating new configuration files"""
    template_name: str
    template_type: str  # 'semantic_mappings', 'scoring_weights'
    description: str
    template_data: Dict[str, Any]
    created_date: str
    version: str


class CaseConfigurationFileManager:
    """
    Manager for case configuration file operations.
    
    Provides low-level file operations, validation, and maintenance
    for case-specific configuration files.
    """
    
    def __init__(self, cases_directory: str = "cases"):
        """
        Initialize case configuration file manager.
        
        Args:
            cases_directory: Root directory for case configurations
        """
        self.cases_dir = Path(cases_directory)
        self.templates_dir = self.cases_dir / "templates"
        self.archive_dir = self.cases_dir / "archive"
        
        # Create directories
        self.cases_dir.mkdir(parents=True, exist_ok=True)
        self.templates_dir.mkdir(exist_ok=True)
        self.archive_dir.mkdir(exist_ok=True)
        
        # File patterns
        self.config_files = {
            'semantic_mappings': 'semantic_mappings.json',
            'scoring_weights': 'scoring_weights.json',
            'metadata': 'case_metadata.json'
        }
        
        # Load templates
        self.templates: Dict[str, ConfigurationTemplate] = {}
        self._load_templates()
        
        logger.info(f"Initialized case configuration file manager with directory: {self.cases_dir}")
    
    def _load_templates(self):
        """Load configuration templates from templates directory"""
        try:
            templates_file = self.templates_dir / "templates.json"
            if templates_file.exists():
                with open(templates_file, 'r') as f:
                    templates_data = json.load(f)
                
                for template_data in templates_data.get('templates', []):
                    template = ConfigurationTemplate(**template_data)
                    self.templates[template.template_name] = template
                
                logger.info(f"Loaded {len(self.templates)} configuration templates")
            else:
                # Create default templates
                self._create_default_templates()
                
        except Exception as e:
            logger.error(f"Failed to load configuration templates: {e}")
            self._create_default_templates()
    
    def _create_default_templates(self):
        """Create default configuration templates"""
        try:
            # Default semantic mappings template
            semantic_template = ConfigurationTemplate(
                template_name="default_semantic_mappings",
                template_type="semantic_mappings",
                description="Default semantic mappings template with common forensic artifacts",
                template_data={
                    "case_id": "{case_id}",
                    "enabled": True,
                    "mappings": [
                        {
                            "source": "SecurityLogs",
                            "field": "EventID",
                            "technical_value": "4624",
                            "semantic_value": "User Login",
                            "description": "Successful user logon",
                            "artifact_type": "Logs",
                            "category": "authentication",
                            "severity": "info"
                        },
                        {
                            "source": "SecurityLogs",
                            "field": "EventID",
                            "technical_value": "4688",
                            "semantic_value": "Process Creation",
                            "description": "A new process was created",
                            "artifact_type": "Logs",
                            "category": "process_execution",
                            "severity": "info"
                        }
                    ],
                    "inherit_global": True,
                    "override_global": False,
                    "description": "Default semantic mappings for case: {case_name}",
                    "version": "1.0"
                },
                created_date=datetime.now().isoformat(),
                version="1.0"
            )
            
            # Default scoring weights template
            scoring_template = ConfigurationTemplate(
                template_name="default_scoring_weights",
                template_type="scoring_weights",
                description="Default scoring weights template with balanced artifact weights",
                template_data={
                    "case_id": "{case_id}",
                    "enabled": True,
                    "default_weights": {
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
                    "score_interpretation": {
                        "confirmed": {"min": 0.8, "label": "Confirmed Execution"},
                        "probable": {"min": 0.5, "label": "Probable Match"},
                        "weak": {"min": 0.2, "label": "Weak Evidence"},
                        "minimal": {"min": 0.0, "label": "Minimal Evidence"}
                    },
                    "tier_definitions": {
                        "1": "Primary Evidence",
                        "2": "Supporting Evidence",
                        "3": "Contextual Evidence",
                        "4": "Background Evidence"
                    },
                    "validation_rules": {
                        "max_weight": 1.0,
                        "min_weight": 0.0,
                        "max_tier": 4,
                        "min_tier": 1,
                        "require_positive_weights": True,
                        "allow_zero_weights": True
                    },
                    "inherit_global": True,
                    "override_global": False,
                    "description": "Default scoring weights for case: {case_name}",
                    "version": "1.0"
                },
                created_date=datetime.now().isoformat(),
                version="1.0"
            )
            
            self.templates["default_semantic_mappings"] = semantic_template
            self.templates["default_scoring_weights"] = scoring_template
            
            # Save templates
            self._save_templates()
            
            logger.info("Created default configuration templates")
            
        except Exception as e:
            logger.error(f"Failed to create default templates: {e}")
    
    def _save_templates(self):
        """Save templates to file"""
        try:
            templates_data = {
                'templates': [asdict(template) for template in self.templates.values()],
                'last_updated': datetime.now().isoformat(),
                'version': '1.0'
            }
            
            templates_file = self.templates_dir / "templates.json"
            with open(templates_file, 'w') as f:
                json.dump(templates_data, f, indent=2)
            
            logger.info(f"Saved {len(self.templates)} configuration templates")
            
        except Exception as e:
            logger.error(f"Failed to save templates: {e}")
    
    def get_file_info(self, file_path: Path, case_id: str, file_type: str) -> ConfigurationFileInfo:
        """
        Get information about a configuration file.
        
        Args:
            file_path: Path to configuration file
            case_id: Case identifier
            file_type: Type of configuration file
            
        Returns:
            ConfigurationFileInfo object
        """
        try:
            if not file_path.exists():
                return ConfigurationFileInfo(
                    file_path=file_path,
                    file_type=file_type,
                    case_id=case_id,
                    file_size=0,
                    last_modified=datetime.now(),
                    checksum="",
                    version="",
                    is_valid=False,
                    validation_errors=["File does not exist"]
                )
            
            # Get file stats
            stat = file_path.stat()
            file_size = stat.st_size
            last_modified = datetime.fromtimestamp(stat.st_mtime)
            
            # Calculate checksum
            checksum = self._calculate_file_checksum(file_path)
            
            # Validate file
            validation_result = self.validate_configuration_file(file_path, file_type)
            
            # Get version from file content
            version = "1.0"  # Default
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    version = data.get('version', '1.0')
            except:
                pass
            
            return ConfigurationFileInfo(
                file_path=file_path,
                file_type=file_type,
                case_id=case_id,
                file_size=file_size,
                last_modified=last_modified,
                checksum=checksum,
                version=version,
                is_valid=validation_result['valid'],
                validation_errors=validation_result['errors']
            )
            
        except Exception as e:
            logger.error(f"Failed to get file info for {file_path}: {e}")
            return ConfigurationFileInfo(
                file_path=file_path,
                file_type=file_type,
                case_id=case_id,
                file_size=0,
                last_modified=datetime.now(),
                checksum="",
                version="",
                is_valid=False,
                validation_errors=[f"Error getting file info: {e}"]
            )
    
    def _calculate_file_checksum(self, file_path: Path) -> str:
        """Calculate SHA-256 checksum of file"""
        try:
            hash_sha256 = hashlib.sha256()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
            return hash_sha256.hexdigest()
        except Exception as e:
            logger.error(f"Failed to calculate checksum for {file_path}: {e}")
            return ""
    
    def validate_configuration_file(self, file_path: Path, file_type: str) -> Dict[str, Any]:
        """
        Validate configuration file structure and content.
        
        Args:
            file_path: Path to configuration file
            file_type: Type of configuration file
            
        Returns:
            Dictionary with validation results
        """
        validation_result = {
            'valid': True,
            'errors': [],
            'warnings': []
        }
        
        try:
            if not file_path.exists():
                validation_result['valid'] = False
                validation_result['errors'].append("File does not exist")
                return validation_result
            
            # Load and parse JSON
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            # Validate based on file type
            if file_type == 'semantic_mappings':
                validation_result = self._validate_semantic_mappings_file(data)
            elif file_type == 'scoring_weights':
                validation_result = self._validate_scoring_weights_file(data)
            elif file_type == 'metadata':
                validation_result = self._validate_metadata_file(data)
            else:
                validation_result['warnings'].append(f"Unknown file type: {file_type}")
            
        except json.JSONDecodeError as e:
            validation_result['valid'] = False
            validation_result['errors'].append(f"Invalid JSON format: {e}")
        except Exception as e:
            validation_result['valid'] = False
            validation_result['errors'].append(f"Validation error: {e}")
        
        return validation_result
    
    def _validate_semantic_mappings_file(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate semantic mappings file structure"""
        result = {'valid': True, 'errors': [], 'warnings': []}
        
        # Required fields
        required_fields = ['case_id', 'enabled', 'mappings']
        for field in required_fields:
            if field not in data:
                result['valid'] = False
                result['errors'].append(f"Missing required field: {field}")
        
        # Validate mappings structure
        if 'mappings' in data:
            if not isinstance(data['mappings'], list):
                result['valid'] = False
                result['errors'].append("Mappings must be a list")
            else:
                for i, mapping in enumerate(data['mappings']):
                    if not isinstance(mapping, dict):
                        result['errors'].append(f"Mapping {i} must be a dictionary")
                        result['valid'] = False
                        continue
                    
                    # Check required mapping fields
                    mapping_required = ['source', 'field', 'technical_value', 'semantic_value']
                    for field in mapping_required:
                        if field not in mapping:
                            result['warnings'].append(f"Mapping {i} missing field: {field}")
        
        return result
    
    def _validate_scoring_weights_file(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate scoring weights file structure"""
        result = {'valid': True, 'errors': [], 'warnings': []}
        
        # Required fields
        required_fields = ['case_id', 'enabled', 'default_weights']
        for field in required_fields:
            if field not in data:
                result['valid'] = False
                result['errors'].append(f"Missing required field: {field}")
        
        # Validate weights
        if 'default_weights' in data:
            if not isinstance(data['default_weights'], dict):
                result['valid'] = False
                result['errors'].append("Default weights must be a dictionary")
            else:
                for artifact_type, weight in data['default_weights'].items():
                    if not isinstance(weight, (int, float)):
                        result['errors'].append(f"Weight for {artifact_type} must be numeric")
                        result['valid'] = False
                    elif weight < 0 or weight > 1:
                        result['warnings'].append(f"Weight for {artifact_type} outside normal range [0,1]: {weight}")
        
        # Validate score interpretation
        if 'score_interpretation' in data:
            if not isinstance(data['score_interpretation'], dict):
                result['warnings'].append("Score interpretation should be a dictionary")
            else:
                for level, config in data['score_interpretation'].items():
                    if not isinstance(config, dict) or 'min' not in config:
                        result['warnings'].append(f"Invalid score interpretation for level: {level}")
        
        return result
    
    def _validate_metadata_file(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate metadata file structure"""
        result = {'valid': True, 'errors': [], 'warnings': []}
        
        # Required fields
        required_fields = ['case_id']
        for field in required_fields:
            if field not in data:
                result['valid'] = False
                result['errors'].append(f"Missing required field: {field}")
        
        # Validate timestamps
        timestamp_fields = ['created_date', 'last_modified', 'last_used']
        for field in timestamp_fields:
            if field in data:
                try:
                    datetime.fromisoformat(data[field].replace('Z', '+00:00'))
                except ValueError:
                    result['warnings'].append(f"Invalid timestamp format for {field}")
        
        return result
    
    def repair_configuration_file(self, file_path: Path, file_type: str) -> bool:
        """
        Attempt to repair a corrupted configuration file.
        
        Args:
            file_path: Path to configuration file
            file_type: Type of configuration file
            
        Returns:
            True if repaired successfully, False otherwise
        """
        try:
            # Create backup first
            backup_path = file_path.with_suffix('.backup')
            shutil.copy2(file_path, backup_path)
            
            # Load file content
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Try to fix common JSON issues
            fixed_content = self._fix_json_content(content)
            
            # Validate fixed content
            try:
                data = json.loads(fixed_content)
            except json.JSONDecodeError:
                logger.error(f"Could not repair JSON in {file_path}")
                return False
            
            # Apply file-type specific repairs
            if file_type == 'semantic_mappings':
                data = self._repair_semantic_mappings_data(data)
            elif file_type == 'scoring_weights':
                data = self._repair_scoring_weights_data(data)
            elif file_type == 'metadata':
                data = self._repair_metadata_data(data)
            
            # Write repaired file
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.info(f"Repaired configuration file: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to repair configuration file {file_path}: {e}")
            return False
    
    def _fix_json_content(self, content: str) -> str:
        """Fix common JSON formatting issues"""
        # Remove trailing commas
        import re
        content = re.sub(r',(\s*[}\]])', r'\1', content)
        
        # Fix unquoted keys (basic attempt)
        content = re.sub(r'(\w+):', r'"\1":', content)
        
        return content
    
    def _repair_semantic_mappings_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Repair semantic mappings data structure"""
        # Ensure required fields exist
        if 'case_id' not in data:
            data['case_id'] = 'unknown'
        if 'enabled' not in data:
            data['enabled'] = True
        if 'mappings' not in data:
            data['mappings'] = []
        if 'version' not in data:
            data['version'] = '1.0'
        if 'last_modified' not in data:
            data['last_modified'] = datetime.now().isoformat()
        
        # Repair mappings
        if isinstance(data['mappings'], list):
            repaired_mappings = []
            for mapping in data['mappings']:
                if isinstance(mapping, dict):
                    # Ensure required fields
                    required_fields = {
                        'source': 'Unknown',
                        'field': 'Unknown',
                        'technical_value': '',
                        'semantic_value': '',
                        'artifact_type': '',
                        'category': '',
                        'severity': 'info'
                    }
                    
                    for field, default_value in required_fields.items():
                        if field not in mapping:
                            mapping[field] = default_value
                    
                    repaired_mappings.append(mapping)
            
            data['mappings'] = repaired_mappings
        
        return data
    
    def _repair_scoring_weights_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Repair scoring weights data structure"""
        # Ensure required fields exist
        if 'case_id' not in data:
            data['case_id'] = 'unknown'
        if 'enabled' not in data:
            data['enabled'] = True
        if 'default_weights' not in data:
            data['default_weights'] = {}
        if 'version' not in data:
            data['version'] = '1.0'
        if 'last_modified' not in data:
            data['last_modified'] = datetime.now().isoformat()
        
        # Repair weights - clamp to valid range
        if isinstance(data['default_weights'], dict):
            for artifact_type, weight in data['default_weights'].items():
                if not isinstance(weight, (int, float)):
                    data['default_weights'][artifact_type] = 0.1  # Default weight
                else:
                    # Clamp to valid range
                    data['default_weights'][artifact_type] = max(0.0, min(1.0, weight))
        
        # Ensure score interpretation exists
        if 'score_interpretation' not in data:
            data['score_interpretation'] = {
                "confirmed": {"min": 0.8, "label": "Confirmed Execution"},
                "probable": {"min": 0.5, "label": "Probable Match"},
                "weak": {"min": 0.2, "label": "Weak Evidence"},
                "minimal": {"min": 0.0, "label": "Minimal Evidence"}
            }
        
        return data
    
    def _repair_metadata_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Repair metadata data structure"""
        # Ensure required fields exist
        if 'case_id' not in data:
            data['case_id'] = 'unknown'
        if 'case_name' not in data:
            data['case_name'] = data['case_id']
        if 'created_date' not in data:
            data['created_date'] = datetime.now().isoformat()
        if 'last_modified' not in data:
            data['last_modified'] = datetime.now().isoformat()
        if 'version' not in data:
            data['version'] = '1.0'
        
        return data
    
    def create_from_template(self, template_name: str, case_id: str, case_name: str = "") -> Dict[str, Any]:
        """
        Create configuration data from template.
        
        Args:
            template_name: Name of template to use
            case_id: Case identifier
            case_name: Optional case name
            
        Returns:
            Configuration data dictionary
        """
        if template_name not in self.templates:
            raise ValueError(f"Template not found: {template_name}")
        
        template = self.templates[template_name]
        
        # Deep copy template data
        import copy
        config_data = copy.deepcopy(template.template_data)
        
        # Replace placeholders
        config_str = json.dumps(config_data)
        config_str = config_str.replace('{case_id}', case_id)
        config_str = config_str.replace('{case_name}', case_name or case_id)
        config_data = json.loads(config_str)
        
        # Update timestamps
        now = datetime.now().isoformat()
        config_data['created_date'] = now
        config_data['last_modified'] = now
        
        return config_data
    
    def compress_configuration_file(self, file_path: Path) -> bool:
        """
        Compress configuration file using gzip.
        
        Args:
            file_path: Path to configuration file
            
        Returns:
            True if compressed successfully, False otherwise
        """
        try:
            compressed_path = file_path.with_suffix(file_path.suffix + '.gz')
            
            with open(file_path, 'rb') as f_in:
                with gzip.open(compressed_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            logger.info(f"Compressed configuration file: {file_path} -> {compressed_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to compress configuration file {file_path}: {e}")
            return False
    
    def decompress_configuration_file(self, compressed_path: Path) -> bool:
        """
        Decompress configuration file.
        
        Args:
            compressed_path: Path to compressed configuration file
            
        Returns:
            True if decompressed successfully, False otherwise
        """
        try:
            if not compressed_path.name.endswith('.gz'):
                logger.error(f"File is not compressed: {compressed_path}")
                return False
            
            output_path = compressed_path.with_suffix('')
            
            with gzip.open(compressed_path, 'rb') as f_in:
                with open(output_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            logger.info(f"Decompressed configuration file: {compressed_path} -> {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to decompress configuration file {compressed_path}: {e}")
            return False
    
    def archive_old_configurations(self, days_old: int = 30) -> int:
        """
        Archive old configuration files.
        
        Args:
            days_old: Archive files older than this many days
            
        Returns:
            Number of files archived
        """
        archived_count = 0
        cutoff_date = datetime.now() - timedelta(days=days_old)
        
        try:
            for case_dir in self.cases_dir.iterdir():
                if not case_dir.is_dir() or case_dir.name in ['templates', 'archive']:
                    continue
                
                for config_type, filename in self.config_files.items():
                    config_file = case_dir / filename
                    
                    if config_file.exists():
                        file_time = datetime.fromtimestamp(config_file.stat().st_mtime)
                        
                        if file_time < cutoff_date:
                            # Archive the file
                            archive_case_dir = self.archive_dir / case_dir.name
                            archive_case_dir.mkdir(exist_ok=True)
                            
                            archive_file = archive_case_dir / filename
                            shutil.move(str(config_file), str(archive_file))
                            
                            # Compress archived file
                            self.compress_configuration_file(archive_file)
                            archive_file.unlink()  # Remove uncompressed version
                            
                            archived_count += 1
                            logger.info(f"Archived old configuration: {config_file}")
            
            logger.info(f"Archived {archived_count} old configuration files")
            return archived_count
            
        except Exception as e:
            logger.error(f"Failed to archive old configurations: {e}")
            return archived_count
    
    def cleanup_empty_case_directories(self) -> int:
        """
        Remove empty case directories.
        
        Returns:
            Number of directories removed
        """
        removed_count = 0
        
        try:
            for case_dir in self.cases_dir.iterdir():
                if not case_dir.is_dir() or case_dir.name in ['templates', 'archive']:
                    continue
                
                # Check if directory is empty or contains only empty subdirectories
                if self._is_directory_empty(case_dir):
                    shutil.rmtree(case_dir)
                    removed_count += 1
                    logger.info(f"Removed empty case directory: {case_dir}")
            
            logger.info(f"Removed {removed_count} empty case directories")
            return removed_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup empty directories: {e}")
            return removed_count
    
    def _is_directory_empty(self, directory: Path) -> bool:
        """Check if directory is empty or contains only empty subdirectories"""
        try:
            for item in directory.iterdir():
                if item.is_file():
                    return False
                elif item.is_dir() and not self._is_directory_empty(item):
                    return False
            return True
        except:
            return False
    
    def get_configuration_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about configuration files.
        
        Returns:
            Dictionary with configuration file statistics
        """
        stats = {
            'total_cases': 0,
            'total_files': 0,
            'total_size_bytes': 0,
            'files_by_type': {},
            'invalid_files': 0,
            'compressed_files': 0,
            'archived_files': 0,
            'oldest_file': None,
            'newest_file': None
        }
        
        try:
            oldest_time = None
            newest_time = None
            
            # Initialize file type counters
            for config_type in self.config_files.keys():
                stats['files_by_type'][config_type] = 0
            
            # Scan case directories
            for case_dir in self.cases_dir.iterdir():
                if not case_dir.is_dir() or case_dir.name in ['templates', 'archive']:
                    continue
                
                stats['total_cases'] += 1
                
                for config_type, filename in self.config_files.items():
                    config_file = case_dir / filename
                    
                    if config_file.exists():
                        stats['total_files'] += 1
                        stats['files_by_type'][config_type] += 1
                        stats['total_size_bytes'] += config_file.stat().st_size
                        
                        file_time = datetime.fromtimestamp(config_file.stat().st_mtime)
                        
                        if oldest_time is None or file_time < oldest_time:
                            oldest_time = file_time
                            stats['oldest_file'] = str(config_file)
                        
                        if newest_time is None or file_time > newest_time:
                            newest_time = file_time
                            stats['newest_file'] = str(config_file)
                        
                        # Check if file is valid
                        validation = self.validate_configuration_file(config_file, config_type)
                        if not validation['valid']:
                            stats['invalid_files'] += 1
                    
                    # Check for compressed version
                    compressed_file = case_dir / (filename + '.gz')
                    if compressed_file.exists():
                        stats['compressed_files'] += 1
            
            # Count archived files
            if self.archive_dir.exists():
                for item in self.archive_dir.rglob('*.gz'):
                    stats['archived_files'] += 1
            
            # Convert timestamps to ISO format
            if oldest_time:
                stats['oldest_file_date'] = oldest_time.isoformat()
            if newest_time:
                stats['newest_file_date'] = newest_time.isoformat()
            
        except Exception as e:
            logger.error(f"Failed to get configuration statistics: {e}")
        
        return stats