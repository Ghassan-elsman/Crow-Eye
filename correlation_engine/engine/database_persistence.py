"""
Database Persistence for Correlation Results
Saves correlation results to SQLite database for efficient querying and viewing.

This module provides SQLite-based persistence for correlation results, replacing
JSON file output with a structured database that supports:
- Efficient querying and filtering
- Historical execution tracking
- Match-level detail storage
- Easy integration with GUI viewers

Author: Crow-Eye Team
"""

import sqlite3
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from .correlation_result import CorrelationResult, CorrelationMatch


class StreamingMatchWriter:
    """
    Efficient streaming writer for correlation matches.
    
    Batches match inserts for better performance and lower memory usage.
    Matches are written directly to the database without holding them in memory.
    
    Usage:
        >>> writer = StreamingMatchWriter(db_path, batch_size=1000)
        >>> result_id = writer.create_result(execution_id, wing_id, wing_name)
        >>> for match in matches:
        ...     writer.write_match(result_id, match)
        >>> writer.flush()  # Write any remaining matches
        >>> writer.close()
    """
    
    def __init__(self, db_path: str, batch_size: int = 1000):
        """
        Initialize streaming writer.
        
        Args:
            db_path: Path to SQLite database
            batch_size: Number of matches to batch before writing
        """
        self.db_path = db_path
        self.batch_size = batch_size
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent access
        self.conn.execute("PRAGMA synchronous=NORMAL")  # Faster writes
        self._batch = []
        self._total_written = 0
        
        # Ensure schema exists
        self._ensure_schema()
    
    def _ensure_schema(self):
        """Ensure required tables exist for streaming writes"""
        cursor = self.conn.cursor()
        
        # Create results table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS results (
                result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                execution_id INTEGER,
                wing_id TEXT NOT NULL,
                wing_name TEXT NOT NULL,
                total_matches INTEGER,
                feathers_processed INTEGER,
                total_records_scanned INTEGER,
                duplicates_prevented INTEGER,
                matches_failed_validation INTEGER,
                execution_duration_seconds REAL,
                anchor_feather_id TEXT,
                anchor_selection_reason TEXT,
                filters_applied TEXT,
                feather_metadata TEXT
            )
        """)
        
        # Migration: Add feather_metadata column if it doesn't exist (for existing databases)
        try:
            cursor.execute("SELECT feather_metadata FROM results LIMIT 1")
        except:
            try:
                cursor.execute("ALTER TABLE results ADD COLUMN feather_metadata TEXT")
                print("[Database] Migration: Added feather_metadata column to results table")
            except:
                pass  # Column might already exist or table doesn't exist yet
        
        # Create matches table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                match_id TEXT PRIMARY KEY,
                result_id INTEGER,
                timestamp TEXT,
                match_score REAL,
                confidence_score REAL,
                confidence_category TEXT,
                feather_count INTEGER,
                time_spread_seconds REAL,
                anchor_feather_id TEXT,
                anchor_artifact_type TEXT,
                matched_application TEXT,
                matched_file_path TEXT,
                matched_event_id TEXT,
                is_duplicate BOOLEAN,
                weighted_score_value REAL,
                weighted_score_interpretation TEXT,
                feather_records TEXT,
                score_breakdown TEXT,
                anchor_start_time TEXT,
                anchor_end_time TEXT,
                anchor_record_count INTEGER,
                semantic_data TEXT
            )
        """)
        
        # Create feather_metadata table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feather_metadata (
                metadata_id INTEGER PRIMARY KEY AUTOINCREMENT,
                result_id INTEGER,
                feather_id TEXT,
                artifact_type TEXT,
                database_path TEXT,
                total_records INTEGER,
                FOREIGN KEY (result_id) REFERENCES results(result_id)
            )
        """)
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_execution ON results(execution_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_matches_result ON matches(result_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_feather_metadata_result ON feather_metadata(result_id)")
        
        self.conn.commit()
    
    def create_result(self, execution_id: int, wing_id: str, wing_name: str,
                     feathers_processed: int = 0, total_records_scanned: int = 0) -> int:
        """
        Create a result record and return its ID.
        
        Args:
            execution_id: Parent execution ID
            wing_id: Wing identifier
            wing_name: Wing name
            feathers_processed: Number of feathers processed
            total_records_scanned: Total records scanned
        
        Returns:
            result_id: Database ID for this result
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO results (
                execution_id, wing_id, wing_name, total_matches,
                feathers_processed, total_records_scanned, duplicates_prevented,
                matches_failed_validation, execution_duration_seconds,
                anchor_feather_id, anchor_selection_reason, filters_applied
            ) VALUES (?, ?, ?, 0, ?, ?, 0, 0, 0, '', '', '{}')
        """, (execution_id, wing_id, wing_name, feathers_processed, total_records_scanned))
        self.conn.commit()
        return cursor.lastrowid
    
    def write_match(self, result_id: int, match: CorrelationMatch):
        """
        Write a match to the batch buffer.
        
        Args:
            result_id: Parent result ID
            match: CorrelationMatch to write
        """
        # Extract weighted score information
        weighted_score_value = None
        weighted_score_interpretation = None
        if match.weighted_score and isinstance(match.weighted_score, dict):
            weighted_score_value = match.weighted_score.get('score')
            weighted_score_interpretation = match.weighted_score.get('interpretation')
        
        # Extract anchor metadata (added by identity engine)
        anchor_start_time = getattr(match, 'anchor_start_time', None)
        anchor_end_time = getattr(match, 'anchor_end_time', None)
        anchor_record_count = getattr(match, 'anchor_record_count', None)
        
        # Extract semantic data
        semantic_data = getattr(match, 'semantic_data', None)
        
        # Add to batch
        self._batch.append((
            match.match_id,
            result_id,
            match.timestamp,
            match.match_score,
            match.confidence_score,
            match.confidence_category,
            match.feather_count,
            match.time_spread_seconds,
            match.anchor_feather_id,
            match.anchor_artifact_type,
            match.matched_application,
            match.matched_file_path,
            match.matched_event_id,
            match.is_duplicate,
            weighted_score_value,
            weighted_score_interpretation,
            json.dumps(match.feather_records),
            json.dumps(match.score_breakdown) if match.score_breakdown else None,
            anchor_start_time,
            anchor_end_time,
            anchor_record_count,
            json.dumps(semantic_data) if semantic_data else None
        ))
        
        # Flush if batch is full
        if len(self._batch) >= self.batch_size:
            self._flush_batch()
    
    def _flush_batch(self):
        """Write batch to database"""
        if not self._batch:
            return
        
        cursor = self.conn.cursor()
        cursor.executemany("""
            INSERT INTO matches (
                match_id, result_id, timestamp, match_score, confidence_score,
                confidence_category, feather_count, time_spread_seconds,
                anchor_feather_id, anchor_artifact_type, matched_application,
                matched_file_path, matched_event_id, is_duplicate,
                weighted_score_value, weighted_score_interpretation,
                feather_records, score_breakdown,
                anchor_start_time, anchor_end_time, anchor_record_count,
                semantic_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, self._batch)
        self.conn.commit()
        
        self._total_written += len(self._batch)
        self._batch = []
    
    def flush(self):
        """Flush any remaining matches in the batch"""
        self._flush_batch()
    
    def update_result_count(self, result_id: int, total_matches: int, 
                           execution_duration: float = 0.0,
                           duplicates_prevented: int = 0,
                           feather_metadata: dict = None):
        """
        Update result record with final counts.
        
        Args:
            result_id: Result ID to update
            total_matches: Final match count
            execution_duration: Execution duration in seconds
            duplicates_prevented: Number of duplicates prevented
            feather_metadata: Feather metadata dictionary
        """
        cursor = self.conn.cursor()
        
        # Serialize feather_metadata to JSON if provided
        feather_metadata_json = None
        if feather_metadata:
            import json
            feather_metadata_json = json.dumps(feather_metadata)
        
        cursor.execute("""
            UPDATE results SET 
                total_matches = ?,
                execution_duration_seconds = ?,
                duplicates_prevented = ?,
                feather_metadata = ?
            WHERE result_id = ?
        """, (total_matches, execution_duration, duplicates_prevented, feather_metadata_json, result_id))
        
        # Also save to feather_metadata table for backwards compatibility
        if feather_metadata:
            for feather_id, metadata in feather_metadata.items():
                cursor.execute("""
                    INSERT OR REPLACE INTO feather_metadata (
                        result_id, feather_id, artifact_type, database_path, total_records
                    ) VALUES (?, ?, ?, ?, ?)
                """, (
                    result_id,
                    feather_id,
                    metadata.get('artifact_type', ''),
                    metadata.get('database_path', ''),
                    metadata.get('records_processed', metadata.get('total_records', 0))
                ))
        
        self.conn.commit()
    
    def update_result_counts(self, result_id: int, total_matches: int,
                            feathers_processed: int = 0,
                            total_records_scanned: int = 0):
        """
        Update result record with final counts (simplified version for streaming).
        
        Args:
            result_id: Result ID to update
            total_matches: Final match count
            feathers_processed: Number of feathers processed
            total_records_scanned: Total records scanned
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE results SET 
                total_matches = ?,
                feathers_processed = ?,
                total_records_scanned = ?
            WHERE result_id = ?
        """, (total_matches, feathers_processed, total_records_scanned, result_id))
        self.conn.commit()
    
    def get_total_written(self) -> int:
        """Get total number of matches written"""
        return self._total_written
    
    def close(self):
        """Close database connection"""
        self.flush()
        if self.conn:
            self.conn.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class ResultsDatabase:
    """
    SQLite database for storing correlation results.
    
    This class manages a SQLite database that stores correlation execution results
    in a structured format, enabling efficient querying and viewing of results.
    
    Database Schema:
        executions: Pipeline execution metadata
        results: Wing-level correlation results
        matches: Individual correlation matches
    
    Usage:
        >>> db = ResultsDatabase("correlation_results.db")
        >>> execution_id = db.save_execution(pipeline_name, execution_time, results, output_dir)
        >>> recent = db.get_recent_executions(limit=10)
        >>> db.close()
    """
    
    def __init__(self, db_path: str):
        """
        Initialize database connection and create schema.
        
        Args:
            db_path: Path to SQLite database file (will be created if doesn't exist)
        """
        self.db_path = Path(db_path)
        self.conn = None
        self._create_schema()
    
    def _create_schema(self):
        """Create database schema if it doesn't exist"""
        self.conn = sqlite3.connect(str(self.db_path))
        cursor = self.conn.cursor()
        
        # Executions table - stores pipeline execution metadata
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS executions (
                execution_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_name TEXT NOT NULL,
                pipeline_name TEXT NOT NULL,
                execution_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                execution_duration_seconds REAL,
                total_wings INTEGER,
                total_matches INTEGER,
                total_records_scanned INTEGER,
                output_directory TEXT,
                case_name TEXT,
                investigator TEXT,
                errors TEXT,
                warnings TEXT,
                engine_type TEXT DEFAULT 'time_based',
                wing_config_json TEXT,
                pipeline_config_json TEXT,
                time_period_start TEXT,
                time_period_end TEXT,
                identity_filters_json TEXT,
                run_number INTEGER DEFAULT 1
            )
        """)
        
        # Results table - stores wing-level results
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS results (
                result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                execution_id INTEGER,
                wing_id TEXT NOT NULL,
                wing_name TEXT NOT NULL,
                total_matches INTEGER,
                feathers_processed INTEGER,
                total_records_scanned INTEGER,
                duplicates_prevented INTEGER,
                matches_failed_validation INTEGER,
                execution_duration_seconds REAL,
                anchor_feather_id TEXT,
                anchor_selection_reason TEXT,
                filters_applied TEXT,
                feather_metadata TEXT,
                FOREIGN KEY (execution_id) REFERENCES executions(execution_id)
            )
        """)
        
        # Matches table - stores individual correlation matches
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                match_id TEXT PRIMARY KEY,
                result_id INTEGER,
                timestamp TEXT,
                match_score REAL,
                confidence_score REAL,
                confidence_category TEXT,
                feather_count INTEGER,
                time_spread_seconds REAL,
                anchor_feather_id TEXT,
                anchor_artifact_type TEXT,
                matched_application TEXT,
                matched_file_path TEXT,
                matched_event_id TEXT,
                is_duplicate BOOLEAN,
                weighted_score_value REAL,
                weighted_score_interpretation TEXT,
                feather_records TEXT,
                score_breakdown TEXT,
                anchor_start_time TEXT,
                anchor_end_time TEXT,
                anchor_record_count INTEGER,
                semantic_data TEXT,
                compressed BOOLEAN DEFAULT 0,
                FOREIGN KEY (result_id) REFERENCES results(result_id)
            )
        """)
        
        # Feather metadata table - stores feather information per result
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feather_metadata (
                metadata_id INTEGER PRIMARY KEY AUTOINCREMENT,
                result_id INTEGER,
                feather_id TEXT,
                artifact_type TEXT,
                database_path TEXT,
                total_records INTEGER,
                FOREIGN KEY (result_id) REFERENCES results(result_id)
            )
        """)
        
        # Create indexes for faster queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_execution ON results(execution_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_wing ON results(wing_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_matches_result ON matches(result_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_matches_timestamp ON matches(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_matches_score ON matches(match_score)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_matches_application ON matches(matched_application)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_feather_metadata_result ON feather_metadata(result_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_executions_engine ON executions(engine_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_executions_time ON executions(execution_time)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_executions_pipeline ON executions(pipeline_name)")
        
        self.conn.commit()
        
        # Migration: Add new columns to existing databases
        self._migrate_schema(cursor)
        
        print(f"[Database] Schema created/verified: {self.db_path}")
    
    def _migrate_schema(self, cursor):
        """
        Add new columns to existing tables if they don't exist.
        This handles upgrading existing databases to the new schema.
        """
        # Check if anchor metadata columns exist in matches table
        cursor.execute("PRAGMA table_info(matches)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        
        # Add anchor_start_time if missing
        if 'anchor_start_time' not in existing_columns:
            try:
                cursor.execute("ALTER TABLE matches ADD COLUMN anchor_start_time TEXT")
                print("[Database] Migration: Added anchor_start_time column")
            except Exception as e:
                pass  # Column might already exist
        
        # Add anchor_end_time if missing
        if 'anchor_end_time' not in existing_columns:
            try:
                cursor.execute("ALTER TABLE matches ADD COLUMN anchor_end_time TEXT")
                print("[Database] Migration: Added anchor_end_time column")
            except Exception as e:
                pass
        
        # Add anchor_record_count if missing
        if 'anchor_record_count' not in existing_columns:
            try:
                cursor.execute("ALTER TABLE matches ADD COLUMN anchor_record_count INTEGER")
                print("[Database] Migration: Added anchor_record_count column")
            except Exception as e:
                pass
        
        # Add semantic_data if missing
        if 'semantic_data' not in existing_columns:
            try:
                cursor.execute("ALTER TABLE matches ADD COLUMN semantic_data TEXT")
                print("[Database] Migration: Added semantic_data column")
            except Exception as e:
                pass
        
        # Check if feather_metadata column exists in results table
        cursor.execute("PRAGMA table_info(results)")
        results_columns = {row[1] for row in cursor.fetchall()}
        
        # Add feather_metadata if missing
        if 'feather_metadata' not in results_columns:
            try:
                cursor.execute("ALTER TABLE results ADD COLUMN feather_metadata TEXT")
                print("[Database] Migration: Added feather_metadata column to results table")
            except Exception as e:
                pass  # Column might already exist
        
        # Add compressed flag if missing (for feather_records compression)
        if 'compressed' not in existing_columns:
            try:
                cursor.execute("ALTER TABLE matches ADD COLUMN compressed BOOLEAN DEFAULT 0")
                print("[Database] Migration: Added compressed column for feather_records compression")
            except Exception as e:
                pass
        
        # Check if run_name and run_number columns exist in executions table
        cursor.execute("PRAGMA table_info(executions)")
        exec_columns = {row[1] for row in cursor.fetchall()}
        
        # Add run_name if missing
        if 'run_name' not in exec_columns:
            try:
                cursor.execute("ALTER TABLE executions ADD COLUMN run_name TEXT")
                print("[Database] Migration: Added run_name column")
                # Update existing records with generated run names
                cursor.execute("""
                    UPDATE executions 
                    SET run_name = engine_type || '_Run_' || execution_id || '_' || 
                                   strftime('%Y%m%d_%H%M%S', execution_time)
                    WHERE run_name IS NULL
                """)
            except Exception as e:
                pass
        
        # Add run_number if missing
        if 'run_number' not in exec_columns:
            try:
                cursor.execute("ALTER TABLE executions ADD COLUMN run_number INTEGER DEFAULT 1")
                print("[Database] Migration: Added run_number column")
            except Exception as e:
                pass
        
        self.conn.commit()
    
    def _generate_run_name(self, engine_type: str, pipeline_name: str = None) -> tuple:
        """
        Generate a unique run name with timestamp and run number.
        
        Args:
            engine_type: Engine type ("time_based" or "identity_based")
            pipeline_name: Optional pipeline name
            
        Returns:
            Tuple of (run_name, run_number)
        """
        cursor = self.conn.cursor()
        
        # Get the next run number for this engine type
        cursor.execute("""
            SELECT COALESCE(MAX(run_number), 0) + 1 
            FROM executions 
            WHERE engine_type = ?
        """, (engine_type,))
        run_number = cursor.fetchone()[0]
        
        # Generate timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Create run name
        engine_prefix = "TimeWindow" if engine_type == "time_based" else "Identity"
        if pipeline_name:
            run_name = f"{engine_prefix}_{pipeline_name}_Run{run_number:03d}_{timestamp}"
        else:
            run_name = f"{engine_prefix}_Run{run_number:03d}_{timestamp}"
        
        return run_name, run_number
    
    def create_execution_placeholder(self, pipeline_name: str, output_dir: str,
                                    case_name: str = "", investigator: str = "",
                                    engine_type: str = "identity_based",
                                    wing_config: Dict[str, Any] = None,
                                    pipeline_config: Dict[str, Any] = None,
                                    time_period_start: str = None,
                                    time_period_end: str = None,
                                    identity_filters: List[str] = None) -> int:
        """
        Create execution record placeholder before wing execution for streaming support.
        
        Returns:
            execution_id: Database ID for this execution
        """
        cursor = self.conn.cursor()
        
        # Generate unique run name
        run_name, run_number = self._generate_run_name(engine_type, pipeline_name)
        
        # Insert execution record with placeholder values
        cursor.execute("""
            INSERT INTO executions (
                run_name, run_number, pipeline_name, execution_duration_seconds, total_wings,
                total_matches, total_records_scanned, output_directory,
                case_name, investigator, errors, warnings,
                engine_type, wing_config_json, pipeline_config_json,
                time_period_start, time_period_end, identity_filters_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_name,
            run_number,
            pipeline_name,
            0.0,  # Placeholder - will be updated
            0,    # Placeholder - will be updated
            0,    # Placeholder - will be updated
            0,    # Placeholder - will be updated
            output_dir,
            case_name,
            investigator,
            json.dumps([]),  # Empty errors initially
            json.dumps([]),  # Empty warnings initially
            engine_type,
            json.dumps(wing_config) if wing_config else None,
            json.dumps(pipeline_config) if pipeline_config else None,
            time_period_start,
            time_period_end,
            json.dumps(identity_filters) if identity_filters else None
        ))
        
        execution_id = cursor.lastrowid
        self.conn.commit()
        
        print(f"[Database] Created execution '{run_name}' (ID: {execution_id}) for streaming")
        return execution_id
    
    def update_execution_stats(self, execution_id: int, execution_duration: float = 0.0,
                               total_matches: int = 0, total_records_scanned: int = 0,
                               errors: List[str] = None, warnings: List[str] = None):
        """
        Update execution record with final statistics after streaming completes.
        
        Args:
            execution_id: Execution ID to update
            execution_duration: Total execution duration in seconds
            total_matches: Total number of matches
            total_records_scanned: Total records scanned
            errors: List of error messages
            warnings: List of warning messages
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE executions SET
                execution_duration_seconds = ?,
                total_matches = ?,
                total_records_scanned = ?,
                errors = ?,
                warnings = ?
            WHERE execution_id = ?
        """, (
            execution_duration,
            total_matches,
            total_records_scanned,
            json.dumps(errors) if errors else None,
            json.dumps(warnings) if warnings else None,
            execution_id
        ))
        self.conn.commit()
        print(f"[Database] Updated execution {execution_id} stats: {total_matches:,} matches")
    
    def save_execution(self, pipeline_name: str, execution_time: float, 
                      results: List[CorrelationResult], output_dir: str,
                      case_name: str = "", investigator: str = "",
                      errors: List[str] = None, warnings: List[str] = None,
                      engine_type: str = "time_based",
                      wing_config: Dict[str, Any] = None,
                      pipeline_config: Dict[str, Any] = None,
                      time_period_start: str = None,
                      time_period_end: str = None,
                      identity_filters: List[str] = None) -> int:
        """
        Save pipeline execution and all results to database.
        
        Args:
            pipeline_name: Name of the pipeline that was executed
            execution_time: Total execution time in seconds
            results: List of CorrelationResult objects
            output_dir: Output directory path
            case_name: Case name (optional)
            investigator: Investigator name (optional)
            errors: List of error messages (optional)
            warnings: List of warning messages (optional)
            engine_type: Engine type used ("time_based" or "identity_based")
            wing_config: Wing configuration dictionary (optional)
            pipeline_config: Pipeline configuration dictionary (optional)
            time_period_start: Time period filter start (ISO format, optional)
            time_period_end: Time period filter end (ISO format, optional)
            identity_filters: List of identity filter patterns (optional)
        
        Returns:
            execution_id: Database ID for this execution
        """
        cursor = self.conn.cursor()
        
        total_matches = sum(r.total_matches for r in results)
        total_records = sum(r.total_records_scanned for r in results)
        
        # Check if we already have an execution_id from streaming (stored in results)
        existing_execution_id = None
        if results and hasattr(results[0], '_result_id'):
            # Query to find execution_id from result_id
            cursor.execute("SELECT execution_id FROM results WHERE result_id = ?", (results[0]._result_id,))
            row = cursor.fetchone()
            if row and row[0] > 0:
                existing_execution_id = row[0]
        
        if existing_execution_id:
            # Update existing execution record
            cursor.execute("""
                UPDATE executions SET
                    execution_duration_seconds = ?,
                    total_wings = ?,
                    total_matches = ?,
                    total_records_scanned = ?,
                    errors = ?,
                    warnings = ?
                WHERE execution_id = ?
            """, (
                execution_time,
                len(results),
                total_matches,
                total_records,
                json.dumps(errors or []),
                json.dumps(warnings or []),
                existing_execution_id
            ))
            execution_id = existing_execution_id
            
            # Get run name for logging
            cursor.execute("SELECT run_name FROM executions WHERE execution_id = ?", (execution_id,))
            row = cursor.fetchone()
            run_name = row[0] if row else f"execution_{execution_id}"
            print(f"[Database] Updated execution '{run_name}' (ID: {execution_id}) with final results")
        else:
            # Generate unique run name
            run_name, run_number = self._generate_run_name(engine_type, pipeline_name)
            
            # Insert new execution record
            cursor.execute("""
                INSERT INTO executions (
                    run_name, run_number, pipeline_name, execution_duration_seconds, total_wings,
                    total_matches, total_records_scanned, output_directory,
                    case_name, investigator, errors, warnings,
                    engine_type, wing_config_json, pipeline_config_json,
                    time_period_start, time_period_end, identity_filters_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_name,
                run_number,
                pipeline_name,
                execution_time,
                len(results),
                total_matches,
                total_records,
                output_dir,
                case_name,
                investigator,
                json.dumps(errors or []),
                json.dumps(warnings or []),
                engine_type,
                json.dumps(wing_config) if wing_config else None,
                json.dumps(pipeline_config) if pipeline_config else None,
                time_period_start,
                time_period_end,
                json.dumps(identity_filters) if identity_filters else None
            ))
            
            execution_id = cursor.lastrowid
            print(f"[Database] Saved execution '{run_name}' (ID: {execution_id})")
        
        print(f"[Database]   - Engine: {engine_type}")
        if time_period_start or time_period_end:
            print(f"[Database]   - Time Filter: {time_period_start} to {time_period_end}")
        if identity_filters:
            print(f"[Database]   - Identity Filters: {', '.join(identity_filters)}")
        print(f"[Database]   - {len(results)} wings, {total_matches:,} total matches")
        
        # Save each result
        for i, result in enumerate(results, 1):
            print(f"[Database]   - Saving wing {i}/{len(results)}: {result.wing_name} ({result.total_matches:,} matches)")
            self.save_result(execution_id, result)
        
        self.conn.commit()
        return execution_id
    
    def save_result(self, execution_id: int, result: CorrelationResult):
        """
        Save a single wing result and all its matches.
        
        If the result was already streamed to the database (has _result_id set),
        this will update the existing result record and link it to the new execution,
        rather than creating a duplicate.
        
        Args:
            execution_id: Parent execution ID
            result: CorrelationResult object to save
        """
        cursor = self.conn.cursor()
        
        # Check if this result was already streamed to the database
        # In streaming mode, matches are written directly with a result_id
        streamed_result_id = getattr(result, '_result_id', 0)
        
        if streamed_result_id > 0:
            # Result was streamed - update the existing result record to link to this execution
            print(f"[Database] Result was streamed (result_id={streamed_result_id}) - updating execution link")
            
            # Serialize feather_metadata to JSON
            feather_metadata_json = None
            if result.feather_metadata:
                feather_metadata_json = json.dumps(result.feather_metadata)
            
            # Update the existing result record to point to the new execution
            cursor.execute("""
                UPDATE results SET 
                    execution_id = ?,
                    total_matches = ?,
                    feathers_processed = ?,
                    total_records_scanned = ?,
                    duplicates_prevented = ?,
                    matches_failed_validation = ?,
                    execution_duration_seconds = ?,
                    anchor_feather_id = ?,
                    anchor_selection_reason = ?,
                    filters_applied = ?,
                    feather_metadata = ?
                WHERE result_id = ?
            """, (
                execution_id,
                result.total_matches,
                result.feathers_processed,
                result.total_records_scanned,
                result.duplicates_prevented,
                result.matches_failed_validation,
                result.execution_duration_seconds,
                result.anchor_feather_id,
                result.anchor_selection_reason,
                json.dumps(result.filters_applied),
                feather_metadata_json,
                streamed_result_id
            ))
            
            result_id = streamed_result_id
            
            # Update feather metadata (delete old and insert new)
            cursor.execute("DELETE FROM feather_metadata WHERE result_id = ?", (result_id,))
        else:
            # Normal case - insert new result record
            # Serialize feather_metadata to JSON
            feather_metadata_json = None
            if result.feather_metadata:
                feather_metadata_json = json.dumps(result.feather_metadata)
            
            cursor.execute("""
                INSERT INTO results (
                    execution_id, wing_id, wing_name, total_matches,
                    feathers_processed, total_records_scanned, duplicates_prevented,
                    matches_failed_validation, execution_duration_seconds,
                    anchor_feather_id, anchor_selection_reason, filters_applied,
                    feather_metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                execution_id,
                result.wing_id,
                result.wing_name,
                result.total_matches,
                result.feathers_processed,
                result.total_records_scanned,
                result.duplicates_prevented,
                result.matches_failed_validation,
                result.execution_duration_seconds,
                result.anchor_feather_id,
                result.anchor_selection_reason,
                json.dumps(result.filters_applied),
                feather_metadata_json
            ))
            
            result_id = cursor.lastrowid
        
        # Save feather metadata
        for feather_id, metadata in result.feather_metadata.items():
            # Handle case where metadata might be a boolean or non-dict value
            if isinstance(metadata, dict):
                artifact_type = metadata.get('artifact_type', '')
                database_path = metadata.get('database_path', '')
                total_records = metadata.get('total_records', 0)
            else:
                # Skip non-dict metadata entries (e.g., boolean values)
                print(f"[Database] Warning: Skipping non-dict metadata for feather {feather_id}: {type(metadata)}")
                continue
            
            cursor.execute("""
                INSERT INTO feather_metadata (
                    result_id, feather_id, artifact_type, database_path, total_records
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                result_id,
                feather_id,
                artifact_type,
                database_path,
                total_records
            ))
        
        # Save all matches (only if not already streamed)
        if streamed_result_id == 0:
            total_matches = len(result.matches)
            
            # DEBUG: Verify matches before saving
            print(f"[Database] 🔍 DEBUG: Saving {total_matches} matches for result_id {result_id}")
            
            batch_size = 1000  # Commit every 1000 matches for better performance
            
            for i, match in enumerate(result.matches):
                self.save_match(result_id, match)
                
                # Progress update every 1000 matches or at specific percentages
                if (i + 1) % batch_size == 0:
                    # Commit batch for better performance
                    self.conn.commit()
                    progress_pct = ((i + 1) / total_matches) * 100
                    print(f"[Database] Saving progress: {progress_pct:.1f}% ({i + 1:,}/{total_matches:,} matches)")
            
            # Final progress message
            print(f"[Database] Saving progress: 100% ({total_matches:,}/{total_matches:,} matches)")
        else:
            print(f"[Database] Skipping match save - {result.total_matches:,} matches already in database")
        
        self.conn.commit()
    
    def save_match(self, result_id: int, match: CorrelationMatch):
        """
        Save a single correlation match with compression for large feather_records.
        
        Args:
            result_id: Parent result ID
            match: CorrelationMatch object to save
        """
        import gzip
        
        cursor = self.conn.cursor()
        
        # Extract weighted score information
        weighted_score_value = None
        weighted_score_interpretation = None
        if match.weighted_score and isinstance(match.weighted_score, dict):
            weighted_score_value = match.weighted_score.get('score')
            weighted_score_interpretation = match.weighted_score.get('interpretation')
        
        # Serialize feather_records
        feather_records_json = json.dumps(match.feather_records)
        feather_records_size = len(feather_records_json.encode('utf-8'))
        
        # Compress if larger than 1MB
        compressed = False
        if feather_records_size > 1024 * 1024:  # 1MB threshold
            feather_records_data = gzip.compress(feather_records_json.encode('utf-8'))
            compressed = True
            if self.debug_mode:
                print(f"[Database] Compressed feather_records: {feather_records_size:,} bytes -> {len(feather_records_data):,} bytes")
        else:
            feather_records_data = feather_records_json
        
        cursor.execute("""
            INSERT INTO matches (
                match_id, result_id, timestamp, match_score, confidence_score,
                confidence_category, feather_count, time_spread_seconds,
                anchor_feather_id, anchor_artifact_type, matched_application,
                matched_file_path, matched_event_id, is_duplicate,
                weighted_score_value, weighted_score_interpretation,
                feather_records, score_breakdown, compressed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            match.match_id,
            result_id,
            match.timestamp,
            match.match_score,
            match.confidence_score,
            match.confidence_category,
            match.feather_count,
            match.time_spread_seconds,
            match.anchor_feather_id,
            match.anchor_artifact_type,
            match.matched_application,
            match.matched_file_path,
            match.matched_event_id,
            match.is_duplicate,
            weighted_score_value,
            weighted_score_interpretation,
            feather_records_data,
            json.dumps(match.score_breakdown) if match.score_breakdown else None,
            compressed
        ))
    
    def get_recent_executions(self, limit: int = 10, engine_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get recent pipeline executions.
        
        Args:
            limit: Maximum number of executions to return
            engine_type: Optional filter by engine type ("time_based" or "identity_based")
        
        Returns:
            List of execution dictionaries with run_name
        """
        cursor = self.conn.cursor()
        
        query = """
            SELECT execution_id, run_name, run_number, pipeline_name, execution_time,
                   execution_duration_seconds, total_wings, total_matches,
                   case_name, investigator, engine_type,
                   time_period_start, time_period_end
            FROM executions
        """
        
        params = []
        if engine_type:
            query += " WHERE engine_type = ?"
            params.append(engine_type)
        
        query += " ORDER BY execution_time DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    def query_executions(self, 
                        start_date: Optional[str] = None,
                        end_date: Optional[str] = None,
                        engine_type: Optional[str] = None,
                        pipeline_name: Optional[str] = None,
                        limit: int = 100) -> List[Dict[str, Any]]:
        """
        Query executions with filters.
        
        Args:
            start_date: Filter by execution time >= this date (ISO format)
            end_date: Filter by execution time <= this date (ISO format)
            engine_type: Filter by engine type ("time_based" or "identity_based")
            pipeline_name: Filter by pipeline name (partial match)
            limit: Maximum number of results
        
        Returns:
            List of execution dictionaries with run_name
        """
        cursor = self.conn.cursor()
        
        query = """
            SELECT execution_id, run_name, run_number, pipeline_name, execution_time,
                   execution_duration_seconds, total_wings, total_matches,
                   total_records_scanned, case_name, investigator,
                   engine_type, time_period_start, time_period_end
            FROM executions
            WHERE 1=1
        """
        params = []
        
        if start_date:
            query += " AND execution_time >= ?"
            params.append(start_date)
        
        if end_date:
            query += " AND execution_time <= ?"
            params.append(end_date)
        
        if engine_type:
            query += " AND engine_type = ?"
            params.append(engine_type)
        
        if pipeline_name:
            query += " AND pipeline_name LIKE ?"
            params.append(f"%{pipeline_name}%")
        
        query += " ORDER BY execution_time DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    def get_execution_metadata(self, execution_id: int) -> Optional[Dict[str, Any]]:
        """
        Get complete metadata for a specific execution.
        
        Args:
            execution_id: Execution ID to query
        
        Returns:
            Dictionary with complete execution metadata or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM executions WHERE execution_id = ?
        """, (execution_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        columns = [desc[0] for desc in cursor.description]
        metadata = dict(zip(columns, row))
        
        # Parse JSON fields
        if metadata.get('errors'):
            metadata['errors'] = json.loads(metadata['errors'])
        if metadata.get('warnings'):
            metadata['warnings'] = json.loads(metadata['warnings'])
        if metadata.get('wing_config_json'):
            metadata['wing_config'] = json.loads(metadata['wing_config_json'])
        if metadata.get('pipeline_config_json'):
            metadata['pipeline_config'] = json.loads(metadata['pipeline_config_json'])
        if metadata.get('identity_filters_json'):
            metadata['identity_filters'] = json.loads(metadata['identity_filters_json'])
        
        return metadata
    
    def get_execution_results(self, execution_id: int) -> List[Dict[str, Any]]:
        """
        Get all results for a specific execution.
        
        Args:
            execution_id: Execution ID to query
        
        Returns:
            List of result dictionaries
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT result_id, wing_id, wing_name, total_matches,
                   feathers_processed, total_records_scanned,
                   duplicates_prevented, execution_duration_seconds
            FROM results
            WHERE execution_id = ?
        """, (execution_id,))
        
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    def get_matches(self, result_id: int, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get matches for a specific result.
        
        Args:
            result_id: Result ID to query
            limit: Optional limit on number of matches
        
        Returns:
            List of match dictionaries
        """
        cursor = self.conn.cursor()
        
        query = """
            SELECT match_id, timestamp, match_score, confidence_score,
                   confidence_category, feather_count, time_spread_seconds,
                   anchor_feather_id, anchor_artifact_type,
                   matched_application, matched_file_path,
                   weighted_score_value, weighted_score_interpretation
            FROM matches
            WHERE result_id = ?
            ORDER BY timestamp
        """
        
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query, (result_id,))
        
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    def get_match_details(self, match_id: str) -> Optional[Dict[str, Any]]:
        """
        Get full details for a specific match including feather records.
        
        Args:
            match_id: Match ID to query
        
        Returns:
            Match dictionary with full details or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM matches WHERE match_id = ?
        """, (match_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        columns = [desc[0] for desc in cursor.description]
        match_dict = dict(zip(columns, row))
        
        # Parse JSON fields
        if match_dict.get('feather_records'):
            match_dict['feather_records'] = json.loads(match_dict['feather_records'])
        if match_dict.get('score_breakdown'):
            match_dict['score_breakdown'] = json.loads(match_dict['score_breakdown'])
        
        return match_dict
    
    def load_correlation_result(self, result_id: int) -> Optional[CorrelationResult]:
        """
        Load a complete CorrelationResult object from the database.
        
        Args:
            result_id: Result ID to load
        
        Returns:
            CorrelationResult object or None if not found
        """
        cursor = self.conn.cursor()
        
        # Get result metadata - only select columns that exist
        cursor.execute("""
            SELECT r.*, e.pipeline_name, e.case_name, e.investigator, e.engine_type
            FROM results r
            JOIN executions e ON r.execution_id = e.execution_id
            WHERE r.result_id = ?
        """, (result_id,))
        
        result_row = cursor.fetchone()
        if not result_row:
            return None
        
        result_columns = [desc[0] for desc in cursor.description]
        result_data = dict(zip(result_columns, result_row))
        
        # Get all matches for this result
        matches = []
        cursor.execute("""
            SELECT * FROM matches WHERE result_id = ? ORDER BY timestamp
        """, (result_id,))
        
        match_columns = [desc[0] for desc in cursor.description]
        for match_row in cursor.fetchall():
            match_data = dict(zip(match_columns, match_row))
            
            # Parse JSON fields with decompression support
            feather_records = {}
            if match_data.get('feather_records'):
                import gzip
                
                # Check if data is compressed
                is_compressed = match_data.get('compressed', False)
                feather_records_data = match_data['feather_records']
                
                if is_compressed:
                    # Decompress the data
                    try:
                        if isinstance(feather_records_data, bytes):
                            decompressed = gzip.decompress(feather_records_data)
                        else:
                            # Handle case where it's stored as string
                            decompressed = gzip.decompress(feather_records_data.encode('latin1'))
                        feather_records = json.loads(decompressed.decode('utf-8'))
                        if self.debug_mode:
                            print(f"[Database] Decompressed feather_records for match {match_data['match_id']}")
                    except Exception as e:
                        print(f"[Database] Error decompressing feather_records: {e}")
                        # Try to parse as regular JSON as fallback
                        try:
                            feather_records = json.loads(feather_records_data)
                        except:
                            feather_records = {}
                else:
                    # Regular JSON parsing
                    feather_records = json.loads(feather_records_data)
            
            score_breakdown = {}
            if match_data.get('score_breakdown'):
                score_breakdown = json.loads(match_data['score_breakdown'])
            
            # Create weighted score dict
            weighted_score = None
            if match_data.get('weighted_score_value') is not None:
                weighted_score = {
                    'score': match_data['weighted_score_value'],
                    'interpretation': match_data.get('weighted_score_interpretation', '')
                }
            
            # Create CorrelationMatch object
            match = CorrelationMatch(
                match_id=match_data['match_id'],
                timestamp=match_data['timestamp'],
                match_score=match_data.get('match_score', 0.0),
                confidence_score=match_data.get('confidence_score', 0.0),
                confidence_category=match_data.get('confidence_category', 'unknown'),
                feather_count=match_data.get('feather_count', 0),
                time_spread_seconds=match_data.get('time_spread_seconds', 0),
                anchor_feather_id=match_data.get('anchor_feather_id', ''),
                anchor_artifact_type=match_data.get('anchor_artifact_type', ''),
                matched_application=match_data.get('matched_application', ''),
                matched_file_path=match_data.get('matched_file_path', ''),
                feather_records=feather_records,
                score_breakdown=score_breakdown,
                weighted_score=weighted_score
            )
            
            # Add anchor metadata if available
            if match_data.get('anchor_start_time'):
                match.anchor_start_time = match_data['anchor_start_time']
            if match_data.get('anchor_end_time'):
                match.anchor_end_time = match_data['anchor_end_time']
            if match_data.get('anchor_record_count'):
                match.anchor_record_count = match_data['anchor_record_count']
            
            # Add semantic data if available
            if match_data.get('semantic_data'):
                match.semantic_data = json.loads(match_data['semantic_data'])
            
            matches.append(match)
        
        # Parse feather metadata
        feather_metadata = {}
        if result_data.get('feather_metadata'):
            feather_metadata = json.loads(result_data['feather_metadata'])
        
        # Create CorrelationResult object
        correlation_result = CorrelationResult(
            wing_id=result_data['wing_id'],
            wing_name=result_data['wing_name'],
            matches=matches,
            total_matches=result_data.get('total_matches', len(matches)),
            feathers_processed=result_data.get('feathers_processed', 0),
            total_records_scanned=result_data.get('total_records_scanned', 0),
            duplicates_prevented=result_data.get('duplicates_prevented', 0),
            matches_failed_validation=result_data.get('matches_failed_validation', 0),
            execution_duration_seconds=result_data.get('execution_duration_seconds', 0.0),
            anchor_feather_id=result_data.get('anchor_feather_id', ''),
            anchor_selection_reason=result_data.get('anchor_selection_reason', ''),
            filters_applied=json.loads(result_data.get('filters_applied', '{}')),
            feather_metadata=feather_metadata
        )
        
        return correlation_result
    
    def load_execution_results(self, execution_id: int) -> List[CorrelationResult]:
        """
        Load all CorrelationResult objects for a specific execution.
        
        Args:
            execution_id: Execution ID to load results for
        
        Returns:
            List of CorrelationResult objects
        """
        # Get all result IDs for this execution
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT result_id FROM results WHERE execution_id = ?
        """, (execution_id,))
        
        results = []
        for (result_id,) in cursor.fetchall():
            result = self.load_correlation_result(result_id)
            if result:
                results.append(result)
        
        return results
    
    def get_latest_execution_id(self) -> Optional[int]:
        """
        Get the ID of the most recent execution.
        
        Returns:
            Latest execution ID or None if no executions exist
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT execution_id FROM executions 
            ORDER BY execution_time DESC 
            LIMIT 1
        """)
        
        row = cursor.fetchone()
        return row[0] if row else None

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            print(f"[Database] Connection closed")
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()
