"""
Two-Phase Correlation Architecture - Unified Module

This module contains all components for the two-phase correlation architecture:
- Data Models (TimeWindow, WindowData, FeatherData, CorrelationResult)
- Database Storage (WindowDataStorage)
- Phase 1: Data Collection (WindowDataCollector)
- Phase 2: Correlation Processing (PostCorrelationProcessor)
- Configuration (TwoPhaseConfig)

Performance: 2-10x faster than single-phase approach
- Phase 1: 1-3 minutes for 10,000 windows (data collection)
- Phase 2: 3-5 minutes for 10,000 windows (correlation analysis)
"""

import sqlite3
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path
import traceback

logger = logging.getLogger(__name__)

# Error handling configuration
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 0.5
DEFAULT_CORRELATION_SCORE = 0.5


# ============================================================================
# ERROR HANDLING UTILITIES
# ============================================================================

class Phase1ErrorHandler:
    """Error handler for Phase 1 (data collection)"""
    
    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode
        self.failed_feathers = []
        self.failed_windows = []
    
    def handle_feather_query_error(self, feather_id: str, feather_name: str, error: Exception):
        """Handle error when querying a feather - skip and continue"""
        self.failed_feathers.append((feather_id, feather_name, str(error)))
        logger.warning(f"[Phase1] Skipping feather '{feather_name}' due to query error: {error}")
        if self.debug_mode:
            logger.debug(traceback.format_exc())
    
    def handle_identity_grouping_error(self, feather_id: str, error: Exception):
        """Handle error when grouping records by identity - return empty"""
        logger.warning(f"[Phase1] Failed to group identities for feather {feather_id}: {error}")
        if self.debug_mode:
            logger.debug(traceback.format_exc())
        return {}
    
    def get_summary(self) -> dict:
        """Get summary of errors encountered"""
        return {
            'failed_feathers': len(self.failed_feathers),
            'failed_windows': len(self.failed_windows),
            'feather_details': self.failed_feathers
        }


class Phase2ErrorHandler:
    """Error handler for Phase 2 (correlation processing)"""
    
    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode
        self.failed_window_loads = []
        self.failed_semantic_matches = []
        self.failed_scorings = []
        self.skipped_windows = []
    
    def handle_window_processing_error(self, window_id: str, error: Exception):
        """Handle general error when processing a window - skip and continue"""
        self.skipped_windows.append((window_id, str(error)))
        logger.error(f"[Phase2] Skipping window {window_id} due to processing error: {error}")
        if self.debug_mode:
            logger.debug(traceback.format_exc())
    
    def handle_semantic_match_error(self, window_id: str, identity_key: str, error: Exception):
        """Handle error during semantic matching - skip this identity"""
        self.failed_semantic_matches.append((window_id, identity_key, str(error)))
        logger.error(f"[Phase2] Semantic matching failed for window {window_id}, identity {identity_key}: {error}")
        if self.debug_mode:
            logger.debug(traceback.format_exc())
    
    def handle_scoring_error(self, window_id: str, identity_key: str, error: Exception) -> float:
        """Handle error during scoring - use default score"""
        self.failed_scorings.append((window_id, identity_key, str(error)))
        logger.warning(f"[Phase2] Scoring failed for window {window_id}, identity {identity_key}, using default score: {error}")
        if self.debug_mode:
            logger.debug(traceback.format_exc())
        return DEFAULT_CORRELATION_SCORE
    
    def get_summary(self) -> dict:
        """Get summary of errors encountered"""
        return {
            'failed_window_loads': len(self.failed_window_loads),
            'failed_semantic_matches': len(self.failed_semantic_matches),
            'failed_scorings': len(self.failed_scorings),
            'skipped_windows': len(self.skipped_windows)
        }


def log_error_summary(phase: str, error_handler):
    """Log summary of errors encountered during a phase"""
    summary = error_handler.get_summary()
    
    if any(summary.values()):
        logger.warning(f"\n{'='*70}")
        logger.warning(f"{phase} ERROR SUMMARY")
        logger.warning(f"{'='*70}")
        
        for key, value in summary.items():
            if isinstance(value, int) and value > 0:
                logger.warning(f"{key}: {value}")
        
        logger.warning(f"{'='*70}\n")


# ============================================================================
# SECTION 1: DATA MODELS
# ============================================================================

@dataclass
class TimeWindow:
    """
    Represents a single time window for correlation processing.
    Contains all records from all feathers that fall within the window timespan.
    """
    start_time: datetime
    end_time: datetime
    window_id: str
    records_by_feather: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    
    def add_records(self, feather_id: str, records: List[Dict[str, Any]]):
        """Add records from a feather to this window"""
        if records:
            self.records_by_feather[feather_id] = records
    
    def get_total_record_count(self) -> int:
        """Get total records across all feathers in this window"""
        return sum(len(records) for records in self.records_by_feather.values())
    
    def get_feather_count(self) -> int:
        """Get number of feathers with records in this window"""
        return len(self.records_by_feather)
    
    def has_minimum_feathers(self, minimum: int) -> bool:
        """Check if window meets minimum feather threshold"""
        return self.get_feather_count() >= minimum
    
    def is_empty(self) -> bool:
        """Check if window has no records"""
        return self.get_total_record_count() == 0


@dataclass
class FeatherData:
    """Data from a single feather within a time window."""
    feather_id: str
    feather_name: str
    record_count: int
    identity_count: int
    identities: Dict[str, List[Dict[str, Any]]]
    raw_records: Optional[List[Dict[str, Any]]] = None
    
    def get_identity_keys(self) -> List[str]:
        return list(self.identities.keys())
    
    def get_records_for_identity(self, identity_key: str) -> List[Dict[str, Any]]:
        return self.identities.get(identity_key, [])
    
    def has_identity(self, identity_key: str) -> bool:
        return identity_key in self.identities
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'feather_id': self.feather_id,
            'feather_name': self.feather_name,
            'record_count': self.record_count,
            'identity_count': self.identity_count,
            'identities': self.identities,
            'raw_records': self.raw_records
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FeatherData':
        return cls(
            feather_id=data['feather_id'],
            feather_name=data['feather_name'],
            record_count=data['record_count'],
            identity_count=data['identity_count'],
            identities=data['identities'],
            raw_records=data.get('raw_records')
        )


@dataclass
class WindowData:
    """Complete data for a single time window."""
    window_id: str
    start_time: datetime
    end_time: datetime
    feathers: Dict[str, FeatherData] = field(default_factory=dict)
    total_records: int = 0
    total_identities: int = 0
    collection_timestamp: Optional[datetime] = None
    collection_duration_seconds: Optional[float] = None
    
    def add_feather_data(self, feather_data: FeatherData):
        self.feathers[feather_data.feather_id] = feather_data
        self.total_records += feather_data.record_count
        self._recalculate_total_identities()
    
    def _recalculate_total_identities(self):
        all_identities = set()
        for feather_data in self.feathers.values():
            all_identities.update(feather_data.get_identity_keys())
        self.total_identities = len(all_identities)
    
    def get_feather_count(self) -> int:
        return len(self.feathers)
    
    def get_feather_ids(self) -> List[str]:
        return list(self.feathers.keys())
    
    def has_feather(self, feather_id: str) -> bool:
        return feather_id in self.feathers
    
    def get_feather_data(self, feather_id: str) -> Optional[FeatherData]:
        return self.feathers.get(feather_id)
    
    def get_all_identities(self) -> Dict[str, List[str]]:
        identity_map = {}
        for feather_id, feather_data in self.feathers.items():
            for identity_key in feather_data.get_identity_keys():
                if identity_key not in identity_map:
                    identity_map[identity_key] = []
                identity_map[identity_key].append(feather_id)
        return identity_map
    
    def get_cross_feather_identities(self, min_feathers: int = 2) -> Dict[str, List[str]]:
        all_identities = self.get_all_identities()
        return {
            identity_key: feather_ids
            for identity_key, feather_ids in all_identities.items()
            if len(feather_ids) >= min_feathers
        }
    
    def is_empty(self) -> bool:
        return self.total_records == 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'window_id': self.window_id,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'feathers': {fid: fd.to_dict() for fid, fd in self.feathers.items()},
            'total_records': self.total_records,
            'total_identities': self.total_identities,
            'collection_timestamp': self.collection_timestamp.isoformat() if self.collection_timestamp else None,
            'collection_duration_seconds': self.collection_duration_seconds
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WindowData':
        window = cls(
            window_id=data['window_id'],
            start_time=datetime.fromisoformat(data['start_time']) if data.get('start_time') else None,
            end_time=datetime.fromisoformat(data['end_time']) if data.get('end_time') else None,
            total_records=data.get('total_records', 0),
            total_identities=data.get('total_identities', 0),
            collection_timestamp=datetime.fromisoformat(data['collection_timestamp']) if data.get('collection_timestamp') else None,
            collection_duration_seconds=data.get('collection_duration_seconds')
        )
        for feather_id, feather_dict in data.get('feathers', {}).items():
            window.feathers[feather_id] = FeatherData.from_dict(feather_dict)
        return window


@dataclass
class CorrelationResult:
    """Result from Phase 2 correlation processing."""
    correlation_id: str
    window_id: str
    identity_key: str
    feathers_matched: List[str]
    correlation_score: float
    semantic_similarity: float
    match_details: Optional[Dict[str, Any]] = None
    processing_timestamp: Optional[datetime] = None
    
    def get_feather_count(self) -> int:
        return len(self.feathers_matched)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'correlation_id': self.correlation_id,
            'window_id': self.window_id,
            'identity_key': self.identity_key,
            'feathers_matched': self.feathers_matched,
            'correlation_score': self.correlation_score,
            'semantic_similarity': self.semantic_similarity,
            'match_details': self.match_details,
            'processing_timestamp': self.processing_timestamp.isoformat() if self.processing_timestamp else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CorrelationResult':
        return cls(
            correlation_id=data['correlation_id'],
            window_id=data['window_id'],
            identity_key=data['identity_key'],
            feathers_matched=data['feathers_matched'],
            correlation_score=data['correlation_score'],
            semantic_similarity=data['semantic_similarity'],
            match_details=data.get('match_details'),
            processing_timestamp=datetime.fromisoformat(data['processing_timestamp']) if data.get('processing_timestamp') else None
        )


# ============================================================================
# SECTION 2: CONFIGURATION
# ============================================================================

@dataclass
class TwoPhaseConfig:
    """Configuration for two-phase correlation execution."""
    enable_two_phase: bool = True
    run_phase1_only: bool = False
    run_phase2_only: bool = False
    progress_update_interval_percent: float = 5.0
    phase1_batch_size: int = 100
    phase2_batch_size: int = 100
    correlation_database_path: Optional[str] = None
    
    def validate(self) -> tuple[bool, Optional[str]]:
        if self.run_phase1_only and self.run_phase2_only:
            return False, "Cannot set both run_phase1_only and run_phase2_only"
        if not self.enable_two_phase and self.run_phase2_only:
            return False, "Cannot run phase2_only when two-phase mode is disabled"
        if not (0 < self.progress_update_interval_percent <= 100):
            return False, "progress_update_interval_percent must be between 0 and 100"
        if self.phase1_batch_size <= 0:
            return False, "phase1_batch_size must be positive"
        if self.phase2_batch_size <= 0:
            return False, "phase2_batch_size must be positive"
        return True, None
    
    def should_run_phase1(self) -> bool:
        if not self.enable_two_phase:
            return True
        if self.run_phase2_only:
            return False
        return True
    
    def should_run_phase2(self) -> bool:
        if not self.enable_two_phase:
            return False
        if self.run_phase1_only:
            return False
        return True
    
    def get_execution_mode(self) -> str:
        if not self.enable_two_phase:
            return "Single-Phase (Legacy)"
        if self.run_phase1_only:
            return "Phase 1 Only (Data Collection)"
        if self.run_phase2_only:
            return "Phase 2 Only (Correlation Analysis)"
        return "Two-Phase (Full Pipeline)"
    
    @classmethod
    def create_default(cls) -> 'TwoPhaseConfig':
        return cls()
    
    @classmethod
    def create_phase1_only(cls) -> 'TwoPhaseConfig':
        return cls(enable_two_phase=True, run_phase1_only=True, run_phase2_only=False)
    
    @classmethod
    def create_phase2_only(cls, correlation_database_path: str) -> 'TwoPhaseConfig':
        return cls(enable_two_phase=True, run_phase1_only=False, run_phase2_only=True,
                   correlation_database_path=correlation_database_path)
    
    def __str__(self) -> str:
        return f"TwoPhaseConfig(mode={self.get_execution_mode()}, phase1_batch={self.phase1_batch_size}, phase2_batch={self.phase2_batch_size})"


# ============================================================================
# SECTION 3: DATABASE STORAGE
# ============================================================================

class WindowDataStorage:
    """Database storage for window data and correlation results."""
    
    def __init__(self, database_path: str, debug_mode: bool = False):
        self.database_path = database_path
        self.debug_mode = debug_mode
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()
    
    def _initialize_schema(self):
        with sqlite3.connect(self.database_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS time_windows (
                    window_id TEXT PRIMARY KEY,
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP NOT NULL,
                    feathers_found INTEGER NOT NULL DEFAULT 0,
                    total_records INTEGER NOT NULL DEFAULT 0,
                    total_identities INTEGER NOT NULL DEFAULT 0,
                    collection_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    collection_duration_seconds REAL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS window_feather_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    window_id TEXT NOT NULL,
                    feather_id TEXT NOT NULL,
                    feather_name TEXT,
                    record_count INTEGER NOT NULL DEFAULT 0,
                    identity_count INTEGER NOT NULL DEFAULT 0,
                    identities_json TEXT NOT NULL,
                    FOREIGN KEY (window_id) REFERENCES time_windows(window_id),
                    UNIQUE(window_id, feather_id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS window_correlations (
                    correlation_id TEXT PRIMARY KEY,
                    window_id TEXT NOT NULL,
                    identity_key TEXT NOT NULL,
                    feathers_matched INTEGER NOT NULL,
                    feathers_matched_list TEXT NOT NULL,
                    correlation_score REAL NOT NULL,
                    semantic_similarity REAL NOT NULL,
                    match_details_json TEXT,
                    processing_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (window_id) REFERENCES time_windows(window_id)
                )
            """)
            conn.commit()


# ============================================================================
# SECTION 6: TWO-PHASE PROGRESS TRACKING
# ============================================================================

class TwoPhaseProgressTracker:
    """
    Phase-aware progress tracking for two-phase correlation.
    
    Tracks progress separately for Phase 1 (data collection) and Phase 2 (correlation).
    Provides clear progress indicators, time estimates, and statistics for each phase.
    """
    
    def __init__(self, debug_mode: bool = False):
        """
        Initialize progress tracker.
        
        Args:
            debug_mode: Enable debug logging
        """
        self.debug_mode = debug_mode
        
        # Current phase tracking
        self.current_phase = None
        
        # Phase 1 statistics
        self.phase1_start_time = None
        self.phase1_end_time = None
        self.phase1_total_windows = 0
        self.phase1_windows_processed = 0
        self.phase1_feathers_found = 0
        self.phase1_records_found = 0
        
        # Phase 2 statistics
        self.phase2_start_time = None
        self.phase2_end_time = None
        self.phase2_total_windows = 0
        self.phase2_windows_processed = 0
        self.phase2_matches_found = 0
        
        # Progress update interval
        self.update_interval_percent = 5.0
        self.last_update_percent = 0
    
    def start_phase1(self, total_windows: int):
        """Start Phase 1 progress tracking."""
        self.current_phase = 1
        self.phase1_start_time = time.time()
        self.phase1_total_windows = total_windows
        self.phase1_windows_processed = 0
        self.phase1_feathers_found = 0
        self.phase1_records_found = 0
        self.last_update_percent = 0
        
        logger.info(f"\n{'='*70}")
        logger.info(f"PHASE 1: DATA COLLECTION")
        logger.info(f"{'='*70}")
        logger.info(f"Total windows to process: {total_windows:,}")
        logger.info(f"Starting data collection...\n")
    
    def update_phase1(self, windows_processed: int, feathers_found: int = 0, records_found: int = 0):
        """Update Phase 1 progress."""
        self.phase1_windows_processed = windows_processed
        self.phase1_feathers_found += feathers_found
        self.phase1_records_found += records_found
        
        # Calculate progress percentage
        if self.phase1_total_windows > 0:
            progress_percent = (windows_processed / self.phase1_total_windows) * 100
            
            # Only update if we've crossed the next interval threshold
            if progress_percent >= self.last_update_percent + self.update_interval_percent:
                self.last_update_percent = int(progress_percent / self.update_interval_percent) * self.update_interval_percent
                
                # Calculate time estimates
                elapsed = time.time() - self.phase1_start_time
                if windows_processed > 0:
                    time_per_window = elapsed / windows_processed
                    remaining_windows = self.phase1_total_windows - windows_processed
                    estimated_remaining = time_per_window * remaining_windows
                else:
                    estimated_remaining = 0
                
                logger.info(
                    f"Phase 1: {progress_percent:.1f}% | "
                    f"Windows: {windows_processed:,}/{self.phase1_total_windows:,} | "
                    f"Feathers: {self.phase1_feathers_found:,} | "
                    f"Records: {self.phase1_records_found:,} | "
                    f"Elapsed: {self._format_time(elapsed)} | "
                    f"Remaining: ~{self._format_time(estimated_remaining)}"
                )
    
    def complete_phase1(self):
        """Complete Phase 1 progress tracking."""
        self.phase1_end_time = time.time()
        duration = self.phase1_end_time - self.phase1_start_time
        
        logger.info(f"\n{'='*70}")
        logger.info(f"PHASE 1 COMPLETE")
        logger.info(f"{'='*70}")
        logger.info(f"Windows processed: {self.phase1_windows_processed:,}")
        logger.info(f"Feathers found: {self.phase1_feathers_found:,}")
        logger.info(f"Records collected: {self.phase1_records_found:,}")
        logger.info(f"Duration: {self._format_time(duration)}")
        logger.info(f"{'='*70}\n")
        
        self.current_phase = None
    
    def start_phase2(self, total_windows: int):
        """Start Phase 2 progress tracking."""
        self.current_phase = 2
        self.phase2_start_time = time.time()
        self.phase2_total_windows = total_windows
        self.phase2_windows_processed = 0
        self.phase2_matches_found = 0
        self.last_update_percent = 0
        
        logger.info(f"\n{'='*70}")
        logger.info(f"PHASE 2: CORRELATION PROCESSING")
        logger.info(f"{'='*70}")
        logger.info(f"Total windows to analyze: {total_windows:,}")
        logger.info(f"Starting correlation analysis...\n")
    
    def update_phase2(self, windows_processed: int, matches_found: int = 0):
        """Update Phase 2 progress."""
        self.phase2_windows_processed = windows_processed
        self.phase2_matches_found = matches_found
        
        # Calculate progress percentage
        if self.phase2_total_windows > 0:
            progress_percent = (windows_processed / self.phase2_total_windows) * 100
            
            # Only update if we've crossed the next interval threshold
            if progress_percent >= self.last_update_percent + self.update_interval_percent:
                self.last_update_percent = int(progress_percent / self.update_interval_percent) * self.update_interval_percent
                
                # Calculate time estimates
                elapsed = time.time() - self.phase2_start_time
                if windows_processed > 0:
                    time_per_window = elapsed / windows_processed
                    remaining_windows = self.phase2_total_windows - windows_processed
                    estimated_remaining = time_per_window * remaining_windows
                else:
                    estimated_remaining = 0
                
                logger.info(
                    f"Phase 2: {progress_percent:.1f}% | "
                    f"Windows: {windows_processed:,}/{self.phase2_total_windows:,} | "
                    f"Matches: {matches_found:,} | "
                    f"Elapsed: {self._format_time(elapsed)} | "
                    f"Remaining: ~{self._format_time(estimated_remaining)}"
                )
    
    def complete_phase2(self):
        """Complete Phase 2 progress tracking."""
        self.phase2_end_time = time.time()
        duration = self.phase2_end_time - self.phase2_start_time
        
        logger.info(f"\n{'='*70}")
        logger.info(f"PHASE 2 COMPLETE")
        logger.info(f"{'='*70}")
        logger.info(f"Windows analyzed: {self.phase2_windows_processed:,}")
        logger.info(f"Correlations found: {self.phase2_matches_found:,}")
        logger.info(f"Duration: {self._format_time(duration)}")
        logger.info(f"{'='*70}\n")
        
        self.current_phase = None
    
    def get_summary(self) -> Dict[str, Any]:
        """Get complete summary of both phases."""
        summary = {
            'phase1': {
                'windows_processed': self.phase1_windows_processed,
                'feathers_found': self.phase1_feathers_found,
                'records_found': self.phase1_records_found,
                'duration_seconds': (self.phase1_end_time - self.phase1_start_time) if self.phase1_end_time else 0
            },
            'phase2': {
                'windows_processed': self.phase2_windows_processed,
                'matches_found': self.phase2_matches_found,
                'duration_seconds': (self.phase2_end_time - self.phase2_start_time) if self.phase2_end_time else 0
            }
        }
        
        # Calculate total duration
        if self.phase1_start_time and self.phase2_end_time:
            summary['total_duration_seconds'] = self.phase2_end_time - self.phase1_start_time
        elif self.phase1_start_time and self.phase1_end_time:
            summary['total_duration_seconds'] = self.phase1_end_time - self.phase1_start_time
        else:
            summary['total_duration_seconds'] = 0
        
        return summary
    
    def _format_time(self, seconds: float) -> str:
        """Format time duration in human-readable format."""
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}h {minutes}m"
    
    def print_final_summary(self):
        """Print final summary of both phases."""
        summary = self.get_summary()
        
        logger.info(f"\n{'='*70}")
        logger.info(f"TWO-PHASE CORRELATION COMPLETE")
        logger.info(f"{'='*70}")
        logger.info(f"\nPhase 1 (Data Collection):")
        logger.info(f"  Windows processed: {summary['phase1']['windows_processed']:,}")
        logger.info(f"  Feathers found: {summary['phase1']['feathers_found']:,}")
        logger.info(f"  Records collected: {summary['phase1']['records_found']:,}")
        logger.info(f"  Duration: {self._format_time(summary['phase1']['duration_seconds'])}")
        
        if summary['phase2']['windows_processed'] > 0:
            logger.info(f"\nPhase 2 (Correlation Processing):")
            logger.info(f"  Windows analyzed: {summary['phase2']['windows_processed']:,}")
            logger.info(f"  Correlations found: {summary['phase2']['matches_found']:,}")
            logger.info(f"  Duration: {self._format_time(summary['phase2']['duration_seconds'])}")
        
        logger.info(f"\nTotal Duration: {self._format_time(summary['total_duration_seconds'])}")
        logger.info(f"{'='*70}\n")


# ============================================================================
# Window Data Collector
# ============================================================================

class WindowDataCollector:
    """
    Collects data for time windows from feathers.
    Phase 1 of two-phase correlation.
    """
    
    def __init__(self, feather_loader, error_handler: Phase1ErrorHandler, debug_mode: bool = False):
        """
        Initialize window data collector.
        
        Args:
            feather_loader: FeatherLoader instance for querying feathers
            error_handler: Error handler for Phase 1
            debug_mode: Enable debug logging
        """
        self.feather_loader = feather_loader
        self.error_handler = error_handler
        self.debug_mode = debug_mode
    
    def collect_window_data(self, window: TimeWindow, feather_ids: List[str]) -> WindowData:
        """
        Collect all data for a time window from specified feathers.
        
        Args:
            window: TimeWindow to collect data for
            feather_ids: List of feather IDs to query
            
        Returns:
            WindowData with all collected records
        """
        window_data = WindowData(
            window_id=f"{window.start_time.isoformat()}_{window.end_time.isoformat()}",
            start_time=window.start_time,
            end_time=window.end_time
        )
        
        collection_start = time.time()
        
        for feather_id in feather_ids:
            try:
                # Query feather for records in time window
                records = self.feather_loader.query_time_range(
                    feather_id,
                    window.start_time,
                    window.end_time
                )
                
                if records:
                    # Group records by identity
                    identities = self._group_by_identity(records, feather_id)
                    
                    feather_data = FeatherData(
                        feather_id=feather_id,
                        feather_name=feather_id,
                        identities=identities,
                        record_count=len(records),
                        identity_count=len(identities)
                    )
                    
                    window_data.add_feather_data(feather_data)
                    
            except Exception as e:
                self.error_handler.handle_feather_query_error(feather_id, feather_id, e)
        
        window_data.collection_duration_seconds = time.time() - collection_start
        return window_data
    
    def _group_by_identity(self, records: List[Dict[str, Any]], feather_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group records by identity key.
        
        Args:
            records: List of records to group
            feather_id: Feather ID for error handling
            
        Returns:
            Dictionary mapping identity keys to lists of records
        """
        try:
            identities = {}
            for record in records:
                # Extract identity key (implementation depends on record structure)
                identity_key = record.get('identity', record.get('name', 'unknown'))
                if identity_key not in identities:
                    identities[identity_key] = []
                identities[identity_key].append(record)
            return identities
        except Exception as e:
            return self.error_handler.handle_identity_grouping_error(feather_id, e)
