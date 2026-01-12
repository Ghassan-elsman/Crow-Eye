"""Case history manager for Crow Eye forensic investigation tool."""

import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from .data_models import CaseMetadata, GlobalConfig, CaseConfig


class CaseHistoryManager:
    """Manages case history and configuration persistence."""
    
    def __init__(self, config_dir: Optional[str] = None):
        """Initialize the case history manager.
        
        Args:
            config_dir: Optional custom configuration directory path.
                       Defaults to %APPDATA%/CrowEye/config/ on Windows.
        """
        if config_dir is None:
            # Use %APPDATA%/CrowEye/config/ on Windows
            appdata = os.getenv('APPDATA')
            if appdata:
                config_dir = os.path.join(appdata, 'CrowEye', 'config')
            else:
                # Fallback to local directory
                config_dir = os.path.join(os.path.dirname(__file__), '..', 'config_data')
        
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self.global_config_path = self.config_dir / 'global_config.json'
        self.case_history_path = self.config_dir / 'case_history.json'
        
        self.global_config: GlobalConfig = self._load_global_config()
        self.case_history: List[CaseMetadata] = []
        self.load_case_history()
    
    def _load_global_config(self) -> GlobalConfig:
        """Load global configuration from file or create default."""
        if self.global_config_path.exists():
            try:
                with open(self.global_config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return GlobalConfig.from_dict(data)
            except (json.JSONDecodeError, IOError) as e:
                print(f"[Config] Error loading global config: {e}")
                print("[Config] Using default configuration")
                return GlobalConfig.default()
        else:
            # Create default configuration
            config = GlobalConfig.default()
            self._save_global_config(config)
            return config
    
    def _save_global_config(self, config: GlobalConfig) -> bool:
        """Save global configuration to file.
        
        Args:
            config: GlobalConfig object to save
            
        Returns:
            True if successful, False otherwise
        """
        try:
            config.last_updated = datetime.now()
            self._atomic_write(self.global_config_path, config.to_dict())
            return True
        except Exception as e:
            print(f"[Config] Error saving global config: {e}")
            return False
    
    def load_case_history(self) -> List[CaseMetadata]:
        """Load case history from persistent storage.
        
        Returns:
            List of CaseMetadata objects
        """
        if not self.case_history_path.exists():
            print("[Config] No case history file found, starting fresh")
            self.case_history = []
            return self.case_history
        
        try:
            with open(self.case_history_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Validate version
            version = data.get('version', '1.0')
            if version != '1.0':
                print(f"[Config] Warning: Case history version {version} may not be compatible")
            
            # Parse cases
            cases_data = data.get('cases', [])
            self.case_history = []
            
            for case_data in cases_data:
                try:
                    case = CaseMetadata.from_dict(case_data)
                    self.case_history.append(case)
                except Exception as e:
                    print(f"[Config] Error parsing case entry: {e}")
                    continue
            
            print(f"[Config] Loaded {len(self.case_history)} cases from history")
            return self.case_history
            
        except json.JSONDecodeError as e:
            print(f"[Config] Error parsing case history JSON: {e}")
            self.case_history = []
            return self.case_history
        except IOError as e:
            print(f"[Config] Error reading case history file: {e}")
            self.case_history = []
            return self.case_history
    
    def save_case_history(self) -> bool:
        """Save case history to persistent storage with atomic write.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Prepare data structure
            data = {
                'version': '1.0',
                'cases': [case.to_dict() for case in self.case_history]
            }
            
            # Atomic write with backup
            self._atomic_write(self.case_history_path, data)
            print(f"[Config] Saved {len(self.case_history)} cases to history")
            return True
            
        except Exception as e:
            print(f"[Config] Error saving case history: {e}")
            return False
    
    def _atomic_write(self, file_path: Path, data: Dict[str, Any]) -> None:
        """Perform atomic write with backup.
        
        Args:
            file_path: Path to the file to write
            data: Dictionary to write as JSON
        """
        # Create backup if file exists
        if file_path.exists():
            backup_path = file_path.with_suffix(file_path.suffix + '.bak')
            shutil.copy2(file_path, backup_path)
        
        # Write to temporary file first
        temp_path = file_path.with_suffix(file_path.suffix + '.tmp')
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # Atomic rename
            temp_path.replace(file_path)
            
        except Exception as e:
            # Clean up temp file on error
            if temp_path.exists():
                temp_path.unlink()
            raise e
    
    def add_case(self, case_info: Dict[str, Any]) -> CaseMetadata:
        """Add a new case to history.
        
        Args:
            case_info: Dictionary containing case information:
                - name: Case name
                - path: Case directory path
                - description: Optional case description
                
        Returns:
            CaseMetadata object for the added case
        """
        # Generate UUID for case
        case_id = str(uuid.uuid4())
        
        # Create timestamps
        now = datetime.now()
        
        # Create case metadata
        case = CaseMetadata(
            case_id=case_id,
            name=case_info.get('name', ''),
            path=case_info.get('path', ''),
            description=case_info.get('description', ''),
            created_date=now,
            last_accessed=now,
            last_opened=now,
            is_favorite=case_info.get('is_favorite', False),
            tags=case_info.get('tags', []),
            status='active'
        )
        
        # Check for duplicate paths
        existing = self.get_case_by_path(case.path)
        if existing:
            print(f"[Config] Case already exists at path: {case.path}")
            # Update existing case instead
            existing.last_accessed = now
            existing.last_opened = now
            existing.name = case.name
            existing.description = case.description
            self.save_case_history()
            return existing
        
        # Add to history
        self.case_history.append(case)
        
        # Enforce max history size
        max_size = self.global_config.max_history_size
        if len(self.case_history) > max_size:
            # Remove oldest non-favorite cases
            self.case_history.sort(key=lambda c: (c.is_favorite, c.last_opened), reverse=True)
            self.case_history = self.case_history[:max_size]
        
        # Save to disk
        self.save_case_history()
        
        print(f"[Config] Added case to history: {case.name}")
        return case
    
    def update_case_access(self, case_path: str) -> bool:
        """Update last accessed timestamp for a case.
        
        Args:
            case_path: Path to the case directory
            
        Returns:
            True if successful, False if case not found
        """
        case = self.get_case_by_path(case_path)
        if case:
            case.last_accessed = datetime.now()
            case.last_opened = datetime.now()
            self.save_case_history()
            print(f"[Config] Updated access time for case: {case.name}")
            return True
        else:
            print(f"[Config] Case not found in history: {case_path}")
            return False
    
    def remove_case(self, case_path: str) -> bool:
        """Remove a case from history (does not delete case files).
        
        Args:
            case_path: Path to the case directory
            
        Returns:
            True if successful, False if case not found
        """
        case = self.get_case_by_path(case_path)
        if case:
            self.case_history.remove(case)
            self.save_case_history()
            print(f"[Config] Removed case from history: {case.name}")
            return True
        else:
            print(f"[Config] Case not found in history: {case_path}")
            return False
    
    def get_recent_cases(self, limit: int = 10) -> List[CaseMetadata]:
        """Get N most recently accessed cases.
        
        Args:
            limit: Maximum number of cases to return
            
        Returns:
            List of CaseMetadata objects sorted by last_opened descending
        """
        # Sort by last_opened descending
        sorted_cases = sorted(self.case_history, key=lambda c: c.last_opened, reverse=True)
        return sorted_cases[:limit]
    
    def get_case_by_path(self, case_path: str) -> Optional[CaseMetadata]:
        """Get case metadata by path.
        
        Args:
            case_path: Path to the case directory
            
        Returns:
            CaseMetadata object or None if not found
        """
        # Normalize paths for comparison
        normalized_path = os.path.normpath(case_path)
        
        for case in self.case_history:
            if os.path.normpath(case.path) == normalized_path:
                return case
        
        return None
    
    def get_case_by_id(self, case_id: str) -> Optional[CaseMetadata]:
        """Get case metadata by ID.
        
        Args:
            case_id: UUID of the case
            
        Returns:
            CaseMetadata object or None if not found
        """
        for case in self.case_history:
            if case.case_id == case_id:
                return case
        return None
    
    def validate_case(self, case_path: str) -> Dict[str, Any]:
        """Validate case directory and required files.
        
        Args:
            case_path: Path to the case directory
            
        Returns:
            Dictionary with validation results:
                - valid: bool
                - errors: List of error messages
                - warnings: List of warning messages
        """
        result = {
            'valid': True,
            'errors': [],
            'warnings': []
        }
        
        # Check if directory exists
        if not os.path.exists(case_path):
            result['valid'] = False
            result['errors'].append(f"Case directory does not exist: {case_path}")
            return result
        
        if not os.path.isdir(case_path):
            result['valid'] = False
            result['errors'].append(f"Path is not a directory: {case_path}")
            return result
        
        # Check for Target_Artifacts directory
        artifacts_dir = os.path.join(case_path, 'Target_Artifacts')
        if not os.path.exists(artifacts_dir):
            result['warnings'].append("Target_Artifacts directory not found")
        
        # Check for expected database files (warnings only)
        expected_dbs = ['registry_data.db', 'mft.db', 'shimcache.db']
        for db_name in expected_dbs:
            db_path = os.path.join(artifacts_dir, db_name)
            if not os.path.exists(db_path):
                result['warnings'].append(f"Database file not found: {db_name}")
        
        return result
    
    def export_case_config(self, case_path: str, export_path: str) -> bool:
        """Export case configuration to a standalone JSON file.
        
        Args:
            case_path: Path to the case directory
            export_path: Path where to save the exported configuration
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Load case config from case directory
            config_path = os.path.join(case_path, 'case_config.json')
            if not os.path.exists(config_path):
                print(f"[Config] Case config not found: {config_path}")
                return False
            
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            # Write to export path
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            
            print(f"[Config] Exported case config to: {export_path}")
            return True
            
        except Exception as e:
            print(f"[Config] Error exporting case config: {e}")
            return False
    
    def import_case_config(self, import_path: str) -> Optional[CaseMetadata]:
        """Import case configuration from a JSON file.
        
        Args:
            import_path: Path to the configuration file to import
            
        Returns:
            CaseMetadata object if successful, None otherwise
        """
        try:
            with open(import_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            # Extract case information
            case_path = config_data.get('case_paths', {}).get('case_root', '')
            if not case_path:
                print("[Config] Invalid case config: missing case_root")
                return None
            
            # Validate case directory
            validation = self.validate_case(case_path)
            if not validation['valid']:
                print(f"[Config] Case validation failed: {validation['errors']}")
                return None
            
            # Add to history
            case_info = {
                'name': config_data.get('name', os.path.basename(case_path)),
                'path': case_path,
                'description': config_data.get('description', '')
            }
            
            case = self.add_case(case_info)
            print(f"[Config] Imported case: {case.name}")
            return case
            
        except Exception as e:
            print(f"[Config] Error importing case config: {e}")
            return None
    
    def update_global_config(self, **kwargs) -> bool:
        """Update global configuration settings.
        
        Args:
            **kwargs: Configuration key-value pairs to update
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Update fields
            for key, value in kwargs.items():
                if hasattr(self.global_config, key):
                    setattr(self.global_config, key, value)
            
            # Save to disk
            return self._save_global_config(self.global_config)
            
        except Exception as e:
            print(f"[Config] Error updating global config: {e}")
            return False
