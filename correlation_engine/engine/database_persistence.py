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
        if match.weighted_score:
            weighted_score_value = match.weighted_score.get('score')
            weighted_score_interpretation = match.weighted_score.get('interpretation')
        
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
            json.dumps(match.score_breakdown) if match.score_breakdown else None
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
                feather_records, score_breakdown
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        cursor.execute("""
            UPDATE results SET 
                total_matches = ?,
                execution_duration_seconds = ?,
                duplicates_prevented = ?
            WHERE result_id = ?
        """, (total_matches, execution_duration, duplicates_prevented, result_id))
        
        # Save feather metadata if provided
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
                    metadata.get('records_loaded', metadata.get('total_records', 0))
                ))
        
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
                identity_filters_json TEXT
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
        print(f"[Database] Schema created/verified: {self.db_path}")
    
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
        
        # Insert execution record
        cursor.execute("""
            INSERT INTO executions (
                pipeline_name, execution_duration_seconds, total_wings,
                total_matches, total_records_scanned, output_directory,
                case_name, investigator, errors, warnings,
                engine_type, wing_config_json, pipeline_config_json,
                time_period_start, time_period_end, identity_filters_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
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
        
        print(f"[Database] Saved execution {execution_id}: {pipeline_name}")
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
                    filters_applied = ?
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
                streamed_result_id
            ))
            
            result_id = streamed_result_id
            
            # Update feather metadata (delete old and insert new)
            cursor.execute("DELETE FROM feather_metadata WHERE result_id = ?", (result_id,))
        else:
            # Normal case - insert new result record
            cursor.execute("""
                INSERT INTO results (
                    execution_id, wing_id, wing_name, total_matches,
                    feathers_processed, total_records_scanned, duplicates_prevented,
                    matches_failed_validation, execution_duration_seconds,
                    anchor_feather_id, anchor_selection_reason, filters_applied
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                json.dumps(result.filters_applied)
            ))
            
            result_id = cursor.lastrowid
        
        # Save feather metadata
        for feather_id, metadata in result.feather_metadata.items():
            cursor.execute("""
                INSERT INTO feather_metadata (
                    result_id, feather_id, artifact_type, database_path, total_records
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                result_id,
                feather_id,
                metadata.get('artifact_type', ''),
                metadata.get('database_path', ''),
                metadata.get('total_records', 0)
            ))
        
        # Save all matches (only if not already streamed)
        if streamed_result_id == 0:
            for match in result.matches:
                self.save_match(result_id, match)
        else:
            print(f"[Database] Skipping match save - {result.total_matches:,} matches already in database")
        
        self.conn.commit()
    
    def save_match(self, result_id: int, match: CorrelationMatch):
        """
        Save a single correlation match.
        
        Args:
            result_id: Parent result ID
            match: CorrelationMatch object to save
        """
        cursor = self.conn.cursor()
        
        # Extract weighted score information
        weighted_score_value = None
        weighted_score_interpretation = None
        if match.weighted_score:
            weighted_score_value = match.weighted_score.get('score')
            weighted_score_interpretation = match.weighted_score.get('interpretation')
        
        cursor.execute("""
            INSERT INTO matches (
                match_id, result_id, timestamp, match_score, confidence_score,
                confidence_category, feather_count, time_spread_seconds,
                anchor_feather_id, anchor_artifact_type, matched_application,
                matched_file_path, matched_event_id, is_duplicate,
                weighted_score_value, weighted_score_interpretation,
                feather_records, score_breakdown
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            json.dumps(match.feather_records),
            json.dumps(match.score_breakdown) if match.score_breakdown else None
        ))
    
    def get_recent_executions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent pipeline executions.
        
        Args:
            limit: Maximum number of executions to return
        
        Returns:
            List of execution dictionaries
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT execution_id, pipeline_name, execution_time,
                   execution_duration_seconds, total_wings, total_matches,
                   case_name, investigator, engine_type,
                   time_period_start, time_period_end
            FROM executions
            ORDER BY execution_time DESC
            LIMIT ?
        """, (limit,))
        
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
            List of execution dictionaries
        """
        cursor = self.conn.cursor()
        
        query = """
            SELECT execution_id, pipeline_name, execution_time,
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
