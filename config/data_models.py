"""Data models for case configuration management."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional


def default_cases_dir() -> str:
    """Where new cases go until the analyst picks somewhere: C:/Cases on
    Windows, ~/Cases elsewhere (there is no C: on Linux)."""
    import os
    if os.name == 'nt':
        return 'C:/Cases'
    return os.path.join(os.path.expanduser('~'), 'Cases')


@dataclass
class CaseMetadata:
    """Metadata for a forensic investigation case."""
    case_id: str
    name: str
    path: str
    description: str
    created_date: datetime
    last_accessed: datetime
    last_opened: datetime
    is_favorite: bool = False
    tags: List[str] = field(default_factory=list)
    status: str = "active"  # active, archived, unavailable
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'case_id': self.case_id,
            'name': self.name,
            'path': self.path,
            'description': self.description,
            'created_date': self.created_date.isoformat() if isinstance(self.created_date, datetime) else self.created_date,
            'last_accessed': self.last_accessed.isoformat() if isinstance(self.last_accessed, datetime) else self.last_accessed,
            'last_opened': self.last_opened.isoformat() if isinstance(self.last_opened, datetime) else self.last_opened,
            'is_favorite': self.is_favorite,
            'tags': self.tags,
            'status': self.status
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CaseMetadata':
        """Create from dictionary loaded from JSON."""
        # Parse datetime strings
        created_date = data.get('created_date')
        if isinstance(created_date, str):
            created_date = datetime.fromisoformat(created_date)
        
        last_accessed = data.get('last_accessed')
        if isinstance(last_accessed, str):
            last_accessed = datetime.fromisoformat(last_accessed)
        
        last_opened = data.get('last_opened', last_accessed)
        if isinstance(last_opened, str):
            last_opened = datetime.fromisoformat(last_opened)
        
        return cls(
            case_id=data.get('case_id', ''),
            name=data.get('name', ''),
            path=data.get('path', ''),
            description=data.get('description', ''),
            created_date=created_date,
            last_accessed=last_accessed,
            last_opened=last_opened,
            is_favorite=data.get('is_favorite', False),
            tags=data.get('tags', []),
            status=data.get('status', 'active')
        )


@dataclass
class GlobalConfig:
    """Global application configuration."""
    version: str
    default_case_directory: str
    recent_cases_display_count: int
    max_history_size: int
    theme: str
    last_updated: datetime
    identity_semantic_phase_enabled: bool = True  # Enable identity-level semantic mapping by default
    wings_semantic_mapping_enabled: bool = True  # Enable semantic mapping for Wings by default
    cascade_tree_expansion_enabled: bool = True  # Enable cascade expansion in tree views by default
    # May a parse CREATE a shadow copy to read a locked hive, or only use
    # ones that already exist? On by default: a hive that cannot be read is
    # evidence lost. Off, the parser still uses existing snapshots and falls
    # back to raw disk and then to an NtSaveKeyEx export.
    parser_allow_snapshot_creation: bool = True
    # Parse automatically once a collection finishes: the Offline Importer's
    # COLLECT, the main window's Parse Offline Artifacts scan, and the default
    # of Image Parsing's "Parse automatically after extraction". Off, every one
    # of them stops at a ready Parse button.
    auto_parse_after_collection: bool = True
    # Settings -> Semantic Mappings -> "Semantic mapping engine": how the
    # semantic phase runs (read by sql_semantic_mapper through
    # read_global_setting). Worker threads for the rules; the share of
    # matches (percent) above which the FTS5 prefilter is skipped because it
    # cannot filter; candidates matched per chunk; and the detailed per-rule
    # debug log in <case>/logs.
    semantic_worker_count: int = 4
    semantic_fts_skip_coverage: int = 50
    semantic_candidate_chunk_size: int = 20000
    semantic_debug_log: bool = False
    # Settings -> Parsing -> "NTFS integrity checks" (read by the MFT parser
    # through read_global_setting; the same keys as Sentinel's policy, and the
    # list in Artifacts_Collectors/MFT and USN journal/ntfs_integrity.py
    # SETTING_DEFAULTS). Everything on except timestamp steganography (D28).
    # A check turned off is written to custody at every parse.
    ntfs_integrity_enabled: bool = True             # the master switch
    # Parse only the MFT records that changed since the last parse of the
    # same volume in the same case. Separate from the master switch: turning
    # the checks off does not change how the MFT is parsed.
    mft_delta_parse: bool = True
    ntfs_integrity_digest_map: bool = True          # D1  changes between parses
    ntfs_integrity_lsn_checks: bool = True          # D2/D3
    ntfs_integrity_usn_continuity: bool = True      # D4
    ntfs_integrity_logfile_continuity: bool = True  # D5
    ntfs_integrity_offline_detect: bool = True      # D6  (Sentinel)
    ntfs_integrity_timestomp: bool = True           # D7/D8/D21/D24/D27
    ntfs_integrity_wipe_detect: bool = True         # D9/D17
    ntfs_integrity_structural: bool = True          # D10/D12/D13/D29
    ntfs_integrity_usn_witness: bool = True         # D11 (later)
    ntfs_integrity_ads_ea_reparse: bool = True      # D14-D16 (later)
    ntfs_integrity_clock: bool = True               # D18 (later)
    ntfs_integrity_vss_inventory: bool = True       # D19 (later)
    ntfs_integrity_security_links: bool = True      # D20 (later)
    ntfs_integrity_i30: bool = True                 # D22 (later)
    ntfs_integrity_logfile_deep: bool = True        # D23 (later)
    ntfs_integrity_txf_efs: bool = True             # D25/D26 (later)
    ntfs_integrity_timestamp_stego: bool = False    # D28 - off by default
    ntfs_integrity_weekly_full_parse: bool = True   # Sentinel only
    # D11: an annotation until it is tuned in the lab, then 'alert'. Reserved.
    ntfs_integrity_usn_witness_mode: str = 'annotation'

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'version': self.version,
            'default_case_directory': self.default_case_directory,
            'recent_cases_display_count': self.recent_cases_display_count,
            'max_history_size': self.max_history_size,
            'theme': self.theme,
            'last_updated': self.last_updated.isoformat() if isinstance(self.last_updated, datetime) else self.last_updated,
            'identity_semantic_phase_enabled': self.identity_semantic_phase_enabled,
            'wings_semantic_mapping_enabled': self.wings_semantic_mapping_enabled,
            'cascade_tree_expansion_enabled': self.cascade_tree_expansion_enabled,
            'parser_allow_snapshot_creation': self.parser_allow_snapshot_creation,
            'auto_parse_after_collection': self.auto_parse_after_collection,
            'semantic_worker_count': self.semantic_worker_count,
            'semantic_fts_skip_coverage': self.semantic_fts_skip_coverage,
            'semantic_candidate_chunk_size': self.semantic_candidate_chunk_size,
            'semantic_debug_log': self.semantic_debug_log,
            'ntfs_integrity_enabled': self.ntfs_integrity_enabled,
            'mft_delta_parse': self.mft_delta_parse,
            'ntfs_integrity_digest_map': self.ntfs_integrity_digest_map,
            'ntfs_integrity_lsn_checks': self.ntfs_integrity_lsn_checks,
            'ntfs_integrity_usn_continuity': self.ntfs_integrity_usn_continuity,
            'ntfs_integrity_logfile_continuity': self.ntfs_integrity_logfile_continuity,
            'ntfs_integrity_offline_detect': self.ntfs_integrity_offline_detect,
            'ntfs_integrity_timestomp': self.ntfs_integrity_timestomp,
            'ntfs_integrity_wipe_detect': self.ntfs_integrity_wipe_detect,
            'ntfs_integrity_structural': self.ntfs_integrity_structural,
            'ntfs_integrity_usn_witness': self.ntfs_integrity_usn_witness,
            'ntfs_integrity_ads_ea_reparse': self.ntfs_integrity_ads_ea_reparse,
            'ntfs_integrity_clock': self.ntfs_integrity_clock,
            'ntfs_integrity_vss_inventory': self.ntfs_integrity_vss_inventory,
            'ntfs_integrity_security_links': self.ntfs_integrity_security_links,
            'ntfs_integrity_i30': self.ntfs_integrity_i30,
            'ntfs_integrity_logfile_deep': self.ntfs_integrity_logfile_deep,
            'ntfs_integrity_txf_efs': self.ntfs_integrity_txf_efs,
            'ntfs_integrity_timestamp_stego': self.ntfs_integrity_timestamp_stego,
            'ntfs_integrity_weekly_full_parse': self.ntfs_integrity_weekly_full_parse,
            'ntfs_integrity_usn_witness_mode': self.ntfs_integrity_usn_witness_mode,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GlobalConfig':
        """Create from dictionary loaded from JSON."""
        last_updated = data.get('last_updated')
        if isinstance(last_updated, str):
            last_updated = datetime.fromisoformat(last_updated)
        
        return cls(
            version=data.get('version', '1.0'),
            default_case_directory=data.get('default_case_directory', default_cases_dir()),
            recent_cases_display_count=data.get('recent_cases_display_count', 10),
            max_history_size=data.get('max_history_size', 200),
            theme=data.get('theme', 'cyberpunk_dark'),
            last_updated=last_updated,
            identity_semantic_phase_enabled=data.get('identity_semantic_phase_enabled', True),
            wings_semantic_mapping_enabled=data.get('wings_semantic_mapping_enabled', True),
            cascade_tree_expansion_enabled=data.get('cascade_tree_expansion_enabled', True),
            parser_allow_snapshot_creation=data.get('parser_allow_snapshot_creation', True),
            auto_parse_after_collection=data.get('auto_parse_after_collection', True),
            semantic_worker_count=data.get('semantic_worker_count', 4),
            semantic_fts_skip_coverage=data.get('semantic_fts_skip_coverage', 50),
            semantic_candidate_chunk_size=data.get('semantic_candidate_chunk_size', 20000),
            semantic_debug_log=data.get('semantic_debug_log', False),
            ntfs_integrity_enabled=data.get('ntfs_integrity_enabled', True),
            mft_delta_parse=data.get('mft_delta_parse', True),
            ntfs_integrity_digest_map=data.get('ntfs_integrity_digest_map', True),
            ntfs_integrity_lsn_checks=data.get('ntfs_integrity_lsn_checks', True),
            ntfs_integrity_usn_continuity=data.get('ntfs_integrity_usn_continuity', True),
            ntfs_integrity_logfile_continuity=data.get('ntfs_integrity_logfile_continuity', True),
            ntfs_integrity_offline_detect=data.get('ntfs_integrity_offline_detect', True),
            ntfs_integrity_timestomp=data.get('ntfs_integrity_timestomp', True),
            ntfs_integrity_wipe_detect=data.get('ntfs_integrity_wipe_detect', True),
            ntfs_integrity_structural=data.get('ntfs_integrity_structural', True),
            ntfs_integrity_usn_witness=data.get('ntfs_integrity_usn_witness', True),
            ntfs_integrity_ads_ea_reparse=data.get('ntfs_integrity_ads_ea_reparse', True),
            ntfs_integrity_clock=data.get('ntfs_integrity_clock', True),
            ntfs_integrity_vss_inventory=data.get('ntfs_integrity_vss_inventory', True),
            ntfs_integrity_security_links=data.get('ntfs_integrity_security_links', True),
            ntfs_integrity_i30=data.get('ntfs_integrity_i30', True),
            ntfs_integrity_logfile_deep=data.get('ntfs_integrity_logfile_deep', True),
            ntfs_integrity_txf_efs=data.get('ntfs_integrity_txf_efs', True),
            ntfs_integrity_timestamp_stego=data.get('ntfs_integrity_timestamp_stego', False),
            ntfs_integrity_weekly_full_parse=data.get('ntfs_integrity_weekly_full_parse', True),
            ntfs_integrity_usn_witness_mode=data.get('ntfs_integrity_usn_witness_mode', 'annotation'),
        )
    
    @classmethod
    def default(cls) -> 'GlobalConfig':
        """Create default global configuration."""
        return cls(
            version='1.0',
            default_case_directory=default_cases_dir(),
            recent_cases_display_count=10,
            max_history_size=200,
            theme='cyberpunk_dark',
            last_updated=datetime.now(),
            identity_semantic_phase_enabled=True,
            wings_semantic_mapping_enabled=True,
            cascade_tree_expansion_enabled=True,
            parser_allow_snapshot_creation=True,
            auto_parse_after_collection=True,
            ntfs_integrity_enabled=True,
            mft_delta_parse=True,
            ntfs_integrity_digest_map=True,
            ntfs_integrity_lsn_checks=True,
            ntfs_integrity_usn_continuity=True,
            ntfs_integrity_logfile_continuity=True,
            ntfs_integrity_offline_detect=True,
            ntfs_integrity_timestomp=True,
            ntfs_integrity_wipe_detect=True,
            ntfs_integrity_structural=True,
            ntfs_integrity_usn_witness=True,
            ntfs_integrity_ads_ea_reparse=True,
            ntfs_integrity_clock=True,
            ntfs_integrity_vss_inventory=True,
            ntfs_integrity_security_links=True,
            ntfs_integrity_i30=True,
            ntfs_integrity_logfile_deep=True,
            ntfs_integrity_txf_efs=True,
            ntfs_integrity_timestamp_stego=False,
            ntfs_integrity_weekly_full_parse=True,
            ntfs_integrity_usn_witness_mode='annotation'
        )


@dataclass
class CaseConfig:
    """Configuration for a specific case."""
    version: str
    case_id: str
    name: str
    description: str
    created_date: datetime
    last_accessed: datetime
    case_paths: Dict[str, Any]
    case_settings: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'version': self.version,
            'case_id': self.case_id,
            'name': self.name,
            'description': self.description,
            'created_date': self.created_date.isoformat() if isinstance(self.created_date, datetime) else self.created_date,
            'last_accessed': self.last_accessed.isoformat() if isinstance(self.last_accessed, datetime) else self.last_accessed,
            'case_paths': self.case_paths,
            'case_settings': self.case_settings
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CaseConfig':
        """Create from dictionary loaded from JSON."""
        created_date = data.get('created_date')
        if isinstance(created_date, str):
            created_date = datetime.fromisoformat(created_date)
        
        last_accessed = data.get('last_accessed')
        if isinstance(last_accessed, str):
            last_accessed = datetime.fromisoformat(last_accessed)
        
        return cls(
            version=data.get('version', '1.0'),
            case_id=data.get('case_id', ''),
            name=data.get('name', ''),
            description=data.get('description', ''),
            created_date=created_date,
            last_accessed=last_accessed,
            case_paths=data.get('case_paths', {}),
            case_settings=data.get('case_settings', {})
        )
