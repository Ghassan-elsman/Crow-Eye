"""
Streaming Manager for Time-Window Scanning Engine

Provides streaming mode functionality for handling large result sets that exceed memory limits.
Instead of storing all matches in memory, matches are written directly to a SQLite database
for later retrieval and analysis.
"""

import sqlite3
import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from dataclasses import dataclass

from .correlation_result import CorrelationMatch


@dataclass
class StreamingConfig:
    """Configuration for streaming mode."""
    database_path: str
    batch_size: int = 1000  # Number of matches to batch before writing
    enable_compression: bool = True  # Compress match data
    auto_vacuum: bool = True  # Enable SQLite auto-vacuum
    memory_limit_mb: int = 500  # Memory limit that triggers streaming mode


class StreamingMatchWriter:
    """
    Writes correlation matches directly to SQLite database for streaming mode.
    
    This allows processing of very large result sets without running out of memory.
    Matches are written in batches for optimal performance.
    """
    
    def __init__(self, config: StreamingConfig):
        """
        Initialize streaming match writer.
        
        Args:
            config: StreamingConfig with database path and settings
        """
        self.config = config
        self.database_path = Path(config.database_path)
        self.conn: Optional[sqlite3.Connection] = None
        self.batch_buffer: List[Tuple[int, CorrelationMatch]] = []
        self.total_matches_written = 0
        self.current_result_id = 0
        
        # Ensure database directory exists
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._initialize_database()
    
    def _initialize_database(self):
        """Initialize SQLite database with streaming tables."""
        self.conn = sqlite3.connect(str(self.database_path))
        
        # Enable WAL mode for better concurrent access
        self.conn.execute("PRAGMA journal_mode=WAL")
        
        # Enable auto-vacuum if configured
        if self.config.auto_vacuum:
            self.conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        
        # Create tables for streaming results
        self.conn.executescript("""
            -- Results metadata table
            CREATE TABLE IF NOT EXISTS streaming_results (
                result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                wing_id TEXT NOT NULL,
                wing_name TEXT NOT NULL,
                execution_time TEXT NOT NULL,
                execution_duration_seconds REAL DEFAULT 0.0,
                total_matches INTEGER DEFAULT 0,
                feathers_processed INTEGER DEFAULT 0,
                total_records_scanned INTEGER DEFAULT 0,
                duplicates_prevented INTEGER DEFAULT 0,
                anchor_feather_id TEXT DEFAULT '',
                anchor_selection_reason TEXT DEFAULT '',
                filters_applied TEXT DEFAULT '{}',  -- JSON
                feather_metadata TEXT DEFAULT '{}',  -- JSON
                performance_metrics TEXT DEFAULT '{}',  -- JSON
                errors TEXT DEFAULT '[]',  -- JSON array
                warnings TEXT DEFAULT '[]',  -- JSON array
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP NULL,
                status TEXT DEFAULT 'active'  -- active, completed, error
            );
            
            -- Matches table for streaming storage
            CREATE TABLE IF NOT EXISTS streaming_matches (
                match_id TEXT PRIMARY KEY,
                result_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                match_score REAL NOT NULL,
                feather_count INTEGER NOT NULL,
                time_spread_seconds REAL NOT NULL,
                anchor_feather_id TEXT NOT NULL,
                anchor_artifact_type TEXT NOT NULL,
                matched_application TEXT,
                matched_file_path TEXT,
                matched_event_id TEXT,
                confidence_score REAL,
                confidence_category TEXT,
                algorithm_version TEXT DEFAULT '2.0',
                is_duplicate BOOLEAN DEFAULT 0,
                feather_records TEXT NOT NULL,  -- JSON
                score_breakdown TEXT,  -- JSON
                weighted_score TEXT,  -- JSON
                time_deltas TEXT,  -- JSON
                field_similarity_scores TEXT,  -- JSON
                candidate_counts TEXT,  -- JSON
                semantic_data TEXT,  -- JSON
                duplicate_info TEXT,  -- JSON
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (result_id) REFERENCES streaming_results (result_id)
            );
            
            -- Indexes for efficient querying
            CREATE INDEX IF NOT EXISTS idx_streaming_matches_result_id 
                ON streaming_matches (result_id);
            CREATE INDEX IF NOT EXISTS idx_streaming_matches_timestamp 
                ON streaming_matches (timestamp);
            CREATE INDEX IF NOT EXISTS idx_streaming_matches_score 
                ON streaming_matches (match_score DESC);
            CREATE INDEX IF NOT EXISTS idx_streaming_matches_feather_count 
                ON streaming_matches (feather_count DESC);
            CREATE INDEX IF NOT EXISTS idx_streaming_results_wing_id 
                ON streaming_results (wing_id);
            CREATE INDEX IF NOT EXISTS idx_streaming_results_created_at 
                ON streaming_results (created_at DESC);
        """)
        
        self.conn.commit()
        # print(f"[StreamingWriter] Initialized database: {self.database_path}")
    
    def create_result_session(self, wing_id: str, wing_name: str, 
                            filters_applied: Dict[str, Any] = None) -> int:
        """
        Create a new result session for streaming matches.
        
        Args:
            wing_id: Wing identifier
            wing_name: Wing name
            filters_applied: Dictionary of applied filters
            
        Returns:
            result_id for this streaming session
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO streaming_results 
            (wing_id, wing_name, execution_time, filters_applied)
            VALUES (?, ?, ?, ?)
        """, (
            wing_id,
            wing_name,
            datetime.now().isoformat(),
            json.dumps(filters_applied or {})
        ))
        
        result_id = cursor.lastrowid
        self.current_result_id = result_id
        self.conn.commit()
        
        # print(f"[StreamingWriter] Created result session {result_id} for wing {wing_id}")
        return result_id
    
    def write_match(self, result_id: int, match: CorrelationMatch):
        """
        Write a correlation match to the streaming database.
        
        Args:
            result_id: Result session ID
            match: CorrelationMatch to write
        """
        # Add to batch buffer
        self.batch_buffer.append((result_id, match))
        
        # Write batch if buffer is full
        if len(self.batch_buffer) >= self.config.batch_size:
            self._flush_batch()
    
    def _flush_batch(self):
        """Flush the current batch of matches to database."""
        if not self.batch_buffer:
            return
        
        # Prepare batch data
        batch_data = []
        for result_id, match in self.batch_buffer:
            batch_data.append((
                match.match_id,
                result_id,
                match.timestamp,
                match.match_score,
                match.feather_count,
                match.time_spread_seconds,
                match.anchor_feather_id,
                match.anchor_artifact_type,
                match.matched_application,
                match.matched_file_path,
                match.matched_event_id,
                match.confidence_score,
                match.confidence_category,
                match.algorithm_version,
                1 if match.is_duplicate else 0,
                json.dumps(match.feather_records) if match.feather_records else '{}',
                json.dumps(match.score_breakdown) if match.score_breakdown else None,
                json.dumps(match.weighted_score) if match.weighted_score else None,
                json.dumps(match.time_deltas) if match.time_deltas else None,
                json.dumps(match.field_similarity_scores) if match.field_similarity_scores else None,
                json.dumps(match.candidate_counts) if match.candidate_counts else None,
                json.dumps(match.semantic_data) if match.semantic_data else None,
                json.dumps(match.duplicate_info.to_dict() if hasattr(match.duplicate_info, 'to_dict') else match.duplicate_info) if match.duplicate_info else None
            ))
        
        # Execute batch insert
        self.conn.executemany("""
            INSERT INTO streaming_matches (
                match_id, result_id, timestamp, match_score, feather_count,
                time_spread_seconds, anchor_feather_id, anchor_artifact_type,
                matched_application, matched_file_path, matched_event_id,
                confidence_score, confidence_category, algorithm_version,
                is_duplicate, feather_records, score_breakdown, weighted_score,
                time_deltas, field_similarity_scores, candidate_counts,
                semantic_data, duplicate_info
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, batch_data)
        
        self.conn.commit()
        
        # Update statistics
        self.total_matches_written += len(self.batch_buffer)
        
        # print(f"[StreamingWriter] Flushed batch of {len(self.batch_buffer)} matches "
        #       f"(total: {self.total_matches_written})")
        
        # Clear buffer
        self.batch_buffer.clear()
    
    def flush(self):
        """Flush any remaining matches in the buffer."""
        if self.batch_buffer:
            self._flush_batch()
    
    def finalize_result_session(self, result_id: int, execution_duration: float,
                              total_matches: int, feathers_processed: int,
                              total_records_scanned: int, duplicates_prevented: int = 0,
                              anchor_feather_id: str = "", anchor_selection_reason: str = "",
                              feather_metadata: Dict[str, Any] = None,
                              performance_metrics: Dict[str, Any] = None,
                              errors: List[str] = None, warnings: List[str] = None):
        """
        Finalize a result session with final statistics.
        """
        # Flush any remaining matches
        self.flush()
        
        # Update result session
        self.conn.execute("""
            UPDATE streaming_results SET
                execution_duration_seconds = ?,
                total_matches = ?,
                feathers_processed = ?,
                total_records_scanned = ?,
                duplicates_prevented = ?,
                anchor_feather_id = ?,
                anchor_selection_reason = ?,
                feather_metadata = ?,
                performance_metrics = ?,
                errors = ?,
                warnings = ?,
                completed_at = CURRENT_TIMESTAMP,
                status = 'completed'
            WHERE result_id = ?
        """, (
            execution_duration,
            total_matches,
            feathers_processed,
            total_records_scanned,
            duplicates_prevented,
            anchor_feather_id,
            anchor_selection_reason,
            json.dumps(feather_metadata or {}),
            json.dumps(performance_metrics or {}),
            json.dumps(errors or []),
            json.dumps(warnings or []),
            result_id
        ))
        
        self.conn.commit()
        
        # print(f"[StreamingWriter] Finalized result session {result_id}: "
        #       f"{total_matches} matches, {execution_duration:.2f}s")
    
    def close(self):
        """Close the database connection."""
        if self.conn:
            self.flush()  # Ensure all data is written
            self.conn.close()
            self.conn = None
            # print(f"[StreamingWriter] Closed database connection")


def create_streaming_manager(database_path: str, memory_limit_mb: int = 500) -> StreamingMatchWriter:
    """
    Create a streaming manager for large result sets.
    
    Args:
        database_path: Path where streaming database should be created
        memory_limit_mb: Memory limit that triggers streaming mode
        
    Returns:
        StreamingMatchWriter instance
    """
    config = StreamingConfig(
        database_path=database_path,
        memory_limit_mb=memory_limit_mb,
        batch_size=1000,
        enable_compression=True,
        auto_vacuum=True
    )
    
    return StreamingMatchWriter(config)