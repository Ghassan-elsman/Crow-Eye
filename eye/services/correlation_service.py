"""
CorrelationService - Read-only access to Crow-eye correlation analysis results.

This service provides access to correlation data from the Crow-eye correlation engine,
enabling EYE to query time-based and identity-based correlations conversationally.

The correlation database is located in the case directory and contains:
- Time-based correlations: Events within temporal proximity
- Identity-based correlations: Events linked by user, process, or file
- Pipeline execution metadata and results

"""

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class CorrelationService:
    """
    Provides read-only access to correlation analysis results.
    
    This service connects to the correlation database in the case directory
    and provides methods to query time-based and identity-based correlations.
    
    The correlation database is created by Crow-eye's correlation engine and
    contains results from correlation pipeline executions.
    
    Attributes:
        case_directory: Path to the case directory
        correlation_db_path: Path to the correlation_results.db file
        logger: Logger instance for audit trail
    """
    
    def __init__(self, case_directory: Union[str, Path]):
        """
        Initialize the CorrelationService.
        
        Args:
            case_directory: Path to the case directory containing correlation database
        """
        self.case_directory = Path(case_directory)
        self.correlation_db_path = self.case_directory / "correlation_results.db"
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Validate correlation database exists
        if not self.correlation_db_path.exists():
            self.logger.warning(
                f"Correlation database does not exist: {self.correlation_db_path}"
            )
    
    def _get_connection(self) -> Optional[sqlite3.Connection]:
        """
        Get a read-only connection to the correlation database.
        
        Returns:
            Read-only SQLite connection, or None if connection fails
        """
        if not self.correlation_db_path.exists():
            self.logger.error(
                f"Correlation database not found: {self.correlation_db_path}"
            )
            return None
        
        try:

            db_uri = self.correlation_db_path.absolute().as_uri() + "?mode=ro"
            
            # Open in read-only mode using URI
            conn = sqlite3.connect(
                db_uri,
                uri=True,
                timeout=30.0
            )
            # Enable row factory for dict-like access
            conn.row_factory = sqlite3.Row
            return conn
            
        except sqlite3.Error as e:
            self.logger.error(
                f"Failed to connect to correlation database: {e}"
            )
            return None
    
    def query_time_correlations(
        self,
        start_time: str,
        end_time: str,
        time_window_seconds: int = 60
    ) -> Dict[str, Any]:
        """
        Query time-based correlations within a time range.
        
        Returns correlation matches that occurred within temporal proximity,
        where events are grouped based on their timestamps and a time window.
        
        Args:
            start_time: Start timestamp (ISO 8601 format: YYYY-MM-DD HH:MM:SS)
            end_time: End timestamp (ISO 8601 format: YYYY-MM-DD HH:MM:SS)
            time_window_seconds: Maximum time spread for correlations (default 60)
            
        Returns:
            Dictionary containing:
                - success: bool indicating if query succeeded
                - matches: List of correlation matches within the time range
                - match_count: Number of matches found
                - time_range: Dict with start_time and end_time
                - time_window: Time window used for filtering
                - error: Error message if query failed
                
        """
        try:
            conn = self._get_connection()
            if conn is None:
                return {
                    "success": False,
                    "matches": [],
                    "match_count": 0,
                    "time_range": {"start": start_time, "end": end_time},
                    "time_window": time_window_seconds,
                    "error": "Failed to connect to correlation database"
                }
            
            # Query matches within time range and time window
            query = """
                SELECT 
                    m.match_id,
                    m.timestamp,
                    m.match_score,
                    m.confidence_score,
                    m.confidence_category,
                    m.feather_count,
                    m.time_spread_seconds,
                    m.anchor_feather_id,
                    m.anchor_artifact_type,
                    m.matched_application,
                    m.matched_file_path,
                    m.matched_event_id,
                    m.weighted_score_value,
                    m.weighted_score_interpretation,
                    m.feather_records,
                    m.score_breakdown,
                    m.semantic_data,
                    r.wing_id,
                    r.wing_name,
                    e.execution_id,
                    e.pipeline_name,
                    e.execution_time
                FROM matches m
                JOIN results r ON m.result_id = r.result_id
                JOIN executions e ON r.execution_id = e.execution_id
                WHERE m.timestamp BETWEEN ? AND ?
                AND m.time_spread_seconds <= ?
                ORDER BY m.timestamp ASC, m.match_score DESC
                LIMIT ?
            """
            
            cursor = conn.execute(
                query,
                (start_time, end_time, time_window_seconds, 500)
            )
            
            # Convert rows to dictionaries
            matches = []
            for row in cursor.fetchall():
                match_dict = dict(row)
                matches.append(match_dict)
            
            self.logger.info(
                f"Time correlation query: {len(matches)} matches found "
                f"between {start_time} and {end_time} "
                f"(time_window={time_window_seconds}s)"
            )
            
            return {
                "success": True,
                "matches": matches,
                "match_count": len(matches),
                "time_range": {"start": start_time, "end": end_time},
                "time_window": time_window_seconds,
                "error": None
            }
            
        except Exception as e:
            error_msg = f"Time correlation query failed: {str(e)}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "matches": [],
                "match_count": 0,
                "time_range": {"start": start_time, "end": end_time},
                "time_window": time_window_seconds,
                "error": error_msg
            }
        finally:
            if 'conn' in locals() and conn:
                conn.close()
    
    def query_identity_correlations(
        self,
        identity_type: str,
        identity_value: str
    ) -> Dict[str, Any]:
        """
        Query identity-based correlations.
        
        Returns correlation matches linked by specific identities such as
        usernames, process names, file paths, or other identifying attributes.
        
        Args:
            identity_type: Type of identity to search for:
                - 'application': Application/process name
                - 'file': File path
                - 'event': Event ID
                - 'user': Username (from semantic data)
                - 'process': Process name (from semantic data)
            identity_value: Specific identity value to search for
            
        Returns:
            Dictionary containing:
                - success: bool indicating if query succeeded
                - matches: List of correlation matches with the identity
                - match_count: Number of matches found
                - identity: Dict with type and value
                - error: Error message if query failed
                
        """
        try:
            conn = self._get_connection()
            if conn is None:
                return {
                    "success": False,
                    "matches": [],
                    "match_count": 0,
                    "identity": {"type": identity_type, "value": identity_value},
                    "error": "Failed to connect to correlation database"
                }
            
            # Build query based on identity type
            if identity_type == "application":
                where_clause = "m.matched_application = ?"
                query_value = identity_value
            elif identity_type == "file":
                where_clause = "m.matched_file_path = ?"
                query_value = identity_value
            elif identity_type == "event":
                where_clause = "m.matched_event_id = ?"
                query_value = identity_value
            elif identity_type in ("user", "process"):
                # Search in semantic_data JSON field using json_extract for robustness
                where_clause = f"json_extract(m.semantic_data, '$.{identity_type}') = ?"
                query_value = identity_value
            else:
                conn.close()
                return {
                    "success": False,
                    "matches": [],
                    "match_count": 0,
                    "identity": {"type": identity_type, "value": identity_value},
                    "error": f"Unsupported identity type: {identity_type}"
                }
            
            query = f"""
                SELECT 
                    m.match_id,
                    m.timestamp,
                    m.match_score,
                    m.confidence_score,
                    m.confidence_category,
                    m.feather_count,
                    m.time_spread_seconds,
                    m.anchor_feather_id,
                    m.anchor_artifact_type,
                    m.matched_application,
                    m.matched_file_path,
                    m.matched_event_id,
                    m.weighted_score_value,
                    m.weighted_score_interpretation,
                    m.feather_records,
                    m.score_breakdown,
                    m.semantic_data,
                    r.wing_id,
                    r.wing_name,
                    e.execution_id,
                    e.pipeline_name,
                    e.execution_time
                FROM matches m
                JOIN results r ON m.result_id = r.result_id
                JOIN executions e ON r.execution_id = e.execution_id
                WHERE {where_clause}
                ORDER BY m.timestamp ASC, m.match_score DESC
                LIMIT ?
            """
            
            cursor = conn.execute(query, (query_value, 500))
            
            # Convert rows to dictionaries
            matches = []
            for row in cursor.fetchall():
                match_dict = dict(row)
                matches.append(match_dict)
            
            self.logger.info(
                f"Identity correlation query: {len(matches)} matches found "
                f"for {identity_type}={identity_value}"
            )
            
            return {
                "success": True,
                "matches": matches,
                "match_count": len(matches),
                "identity": {"type": identity_type, "value": identity_value},
                "error": None
            }
            
        except Exception as e:
            error_msg = f"Identity correlation query failed: {str(e)}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "matches": [],
                "match_count": 0,
                "identity": {"type": identity_type, "value": identity_value},
                "error": error_msg
            }
        finally:
            if 'conn' in locals() and conn:
                conn.close()
    
    def get_recent_executions(
        self,
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        Get recent correlation pipeline executions.
        
        Returns metadata about recent correlation analysis runs, useful for
        understanding what correlation data is available.
        
        Args:
            limit: Maximum number of executions to return (default 10)
            
        Returns:
            Dictionary containing:
                - success: bool indicating if query succeeded
                - executions: List of execution metadata
                - execution_count: Number of executions found
                - error: Error message if query failed
        """
        try:
            conn = self._get_connection()
            if conn is None:
                return {
                    "success": False,
                    "executions": [],
                    "execution_count": 0,
                    "error": "Failed to connect to correlation database"
                }
            
            query = """
                SELECT 
                    execution_id,
                    run_name,
                    pipeline_name,
                    execution_time,
                    execution_duration_seconds,
                    total_wings,
                    total_matches,
                    total_records_scanned,
                    engine_type,
                    time_period_start,
                    time_period_end
                FROM executions
                ORDER BY execution_time DESC
                LIMIT ?
            """
            
            cursor = conn.execute(query, (limit,))
            
            # Convert rows to dictionaries
            executions = []
            for row in cursor.fetchall():
                exec_dict = dict(row)
                executions.append(exec_dict)
            
            self.logger.info(
                f"Retrieved {len(executions)} recent correlation executions"
            )
            
            return {
                "success": True,
                "executions": executions,
                "execution_count": len(executions),
                "error": None
            }
            
        except Exception as e:
            error_msg = f"Failed to retrieve recent executions: {str(e)}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "executions": [],
                "execution_count": 0,
                "error": error_msg
            }
        finally:
            if 'conn' in locals() and conn:
                conn.close()
    
    def get_correlation_statistics(self) -> Dict[str, Any]:
        """
        Get overall statistics about correlation data.
        
        Returns summary statistics about the correlation database, useful for
        providing context to the LLM about available correlation data.
        
        Returns:
            Dictionary containing:
                - success: bool indicating if query succeeded
                - statistics: Dict with various statistics
                - error: Error message if query failed
        """
        try:
            conn = self._get_connection()
            if conn is None:
                return {
                    "success": False,
                    "statistics": {},
                    "error": "Failed to connect to correlation database"
                }
            
            # Get various statistics
            stats = {}
            
            # Total executions
            cursor = conn.execute("SELECT COUNT(*) FROM executions")
            stats["total_executions"] = cursor.fetchone()[0]
            
            # Total matches
            cursor = conn.execute("SELECT COUNT(*) FROM matches")
            stats["total_matches"] = cursor.fetchone()[0]
            
            # Total results (wings)
            cursor = conn.execute("SELECT COUNT(*) FROM results")
            stats["total_results"] = cursor.fetchone()[0]
            
            # Latest execution
            cursor = conn.execute(
                "SELECT execution_time FROM executions "
                "ORDER BY execution_time DESC LIMIT 1"
            )
            row = cursor.fetchone()
            stats["latest_execution_time"] = row[0] if row else None
            
            # Time range of matches
            cursor = conn.execute(
                "SELECT MIN(timestamp), MAX(timestamp) FROM matches"
            )
            row = cursor.fetchone()
            stats["match_time_range"] = {
                "earliest": row[0] if row else None,
                "latest": row[1] if row else None
            }
            
            # Top applications
            cursor = conn.execute("""
                SELECT matched_application, COUNT(*) as count
                FROM matches
                WHERE matched_application IS NOT NULL
                GROUP BY matched_application
                ORDER BY count DESC
                LIMIT 5
            """)
            stats["top_applications"] = [
                {"application": row[0], "count": row[1]}
                for row in cursor.fetchall()
            ]
            
            self.logger.info("Retrieved correlation statistics")
            
            return {
                "success": True,
                "statistics": stats,
                "error": None
            }
            
        except Exception as e:
            error_msg = f"Failed to retrieve correlation statistics: {str(e)}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "statistics": {},
                "error": error_msg
            }
        finally:
            if 'conn' in locals() and conn:
                conn.close()
    
    def database_exists(self) -> bool:
        """
        Check if the correlation database exists.
        
        Returns:
            True if correlation database exists, False otherwise
        """
        return self.correlation_db_path.exists()
