"""Enhanced data processing utilities with streaming support for large datasets."""

import asyncio
import sqlite3
import json
import csv
from typing import AsyncGenerator, Dict, List, Any, Optional, Callable, Union
from pathlib import Path
import logging
from concurrent.futures import ThreadPoolExecutor
import threading
from queue import Queue, Empty
from dataclasses import dataclass
import time


@dataclass
class ProcessingResult:
    """Result of a data processing operation."""
    success: bool
    records_processed: int
    errors: List[str]
    duration_seconds: float
    metadata: Dict[str, Any]


class StreamingDataProcessor:
    """Process large datasets in streaming fashion to manage memory usage."""
    
    def __init__(self, chunk_size: int = 1000, max_workers: int = 4):
        """Initialize the streaming data processor.
        
        Args:
            chunk_size: Number of records to process in each chunk
            max_workers: Maximum number of worker threads
        """
        self.chunk_size = chunk_size
        self.max_workers = max_workers
        self.logger = logging.getLogger(__name__)
        
    async def process_large_file(
        self,
        file_path: Union[str, Path],
        processor_func: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]],
        output_db: str,
        table_name: str,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> ProcessingResult:
        """Process a large file in chunks to manage memory usage.
        
        Args:
            file_path: Path to the file to process
            processor_func: Function to process each chunk of data
            output_db: Path to output SQLite database
            table_name: Name of the table to store results
            progress_callback: Callback for progress updates (current, total)
            
        Returns:
            ProcessingResult with operation details
        """
        start_time = time.time()
        file_path = Path(file_path)
        total_records = 0
        errors = []
        
        try:
            # Estimate total records for progress tracking
            total_size = file_path.stat().st_size
            estimated_records = max(1, total_size // 100)  # Rough estimate
            
            # Initialize database
            await self._init_database(output_db, table_name)
            
            # Process file in chunks
            records_processed = 0
            async for chunk in self._read_file_chunks(file_path):
                try:
                    # Process chunk
                    processed_chunk = await asyncio.get_event_loop().run_in_executor(
                        None, processor_func, chunk
                    )
                    
                    # Store results
                    await self._store_chunk(output_db, table_name, processed_chunk)
                    
                    records_processed += len(processed_chunk)
                    
                    # Update progress
                    if progress_callback:
                        progress_callback(records_processed, estimated_records)
                        
                except Exception as e:
                    error_msg = f"Error processing chunk: {e}"
                    errors.append(error_msg)
                    self.logger.error(error_msg)
            
            duration = time.time() - start_time
            
            return ProcessingResult(
                success=len(errors) == 0,
                records_processed=records_processed,
                errors=errors,
                duration_seconds=duration,
                metadata={
                    "file_size_bytes": total_size,
                    "chunk_size": self.chunk_size,
                    "throughput_records_per_second": records_processed / duration if duration > 0 else 0
                }
            )
            
        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"Fatal error processing file: {e}"
            errors.append(error_msg)
            self.logger.error(error_msg)
            
            return ProcessingResult(
                success=False,
                records_processed=0,
                errors=errors,
                duration_seconds=duration,
                metadata={}
            )
    
    async def _read_file_chunks(self, file_path: Path) -> AsyncGenerator[List[Dict[str, Any]], None]:
        """Read file in chunks based on file type.
        
        Args:
            file_path: Path to the file to read
            
        Yields:
            Chunks of data as lists of dictionaries
        """
        file_extension = file_path.suffix.lower()
        
        if file_extension == '.json':
            async for chunk in self._read_json_chunks(file_path):
                yield chunk
        elif file_extension == '.csv':
            async for chunk in self._read_csv_chunks(file_path):
                yield chunk
        else:
            # For binary files or unknown formats, read in binary chunks
            async for chunk in self._read_binary_chunks(file_path):
                yield chunk
    
    async def _read_json_chunks(self, file_path: Path) -> AsyncGenerator[List[Dict[str, Any]], None]:
        """Read JSON file in chunks."""
        def read_json():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    else:
                        return [data]
            except Exception as e:
                self.logger.error(f"Error reading JSON file: {e}")
                return []
        
        data = await asyncio.get_event_loop().run_in_executor(None, read_json)
        
        # Yield data in chunks
        for i in range(0, len(data), self.chunk_size):
            yield data[i:i + self.chunk_size]
    
    async def _read_csv_chunks(self, file_path: Path) -> AsyncGenerator[List[Dict[str, Any]], None]:
        """Read CSV file in chunks."""
        def read_csv_chunk():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    chunk = []
                    for row in reader:
                        chunk.append(row)
                        if len(chunk) >= self.chunk_size:
                            yield chunk
                            chunk = []
                    if chunk:  # Yield remaining records
                        yield chunk
            except Exception as e:
                self.logger.error(f"Error reading CSV file: {e}")
                yield []
        
        for chunk in await asyncio.get_event_loop().run_in_executor(None, read_csv_chunk):
            yield chunk
    
    async def _read_binary_chunks(self, file_path: Path) -> AsyncGenerator[List[Dict[str, Any]], None]:
        """Read binary file in chunks (placeholder for custom binary parsers)."""
        # This is a placeholder - specific binary format parsers should be implemented
        # based on the artifact type (prefetch, registry, etc.)
        def read_binary():
            try:
                with open(file_path, 'rb') as f:
                    chunk_size_bytes = 64 * 1024  # 64KB chunks
                    chunk_data = f.read(chunk_size_bytes)
                    if chunk_data:
                        return [{"binary_data": chunk_data.hex(), "offset": 0, "size": len(chunk_data)}]
                return []
            except Exception as e:
                self.logger.error(f"Error reading binary file: {e}")
                return []
        
        data = await asyncio.get_event_loop().run_in_executor(None, read_binary)
        if data:
            yield data
    
    async def _init_database(self, db_path: str, table_name: str):
        """Initialize the database and table if they don't exist."""
        def init_db():
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # Create a flexible table schema that can accommodate various data types
                cursor.execute(f'''
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        data TEXT,
                        metadata TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                conn.commit()
                conn.close()
            except Exception as e:
                self.logger.error(f"Error initializing database: {e}")
                raise
        
        await asyncio.get_event_loop().run_in_executor(None, init_db)
    
    async def _store_chunk(self, db_path: str, table_name: str, data: List[Dict[str, Any]]):
        """Store a chunk of processed data in the database."""
        def store_data():
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                for record in data:
                    # Store the main data as JSON
                    data_json = json.dumps(record.get('data', record))
                    metadata_json = json.dumps(record.get('metadata', {}))
                    
                    cursor.execute(f'''
                        INSERT INTO {table_name} (data, metadata)
                        VALUES (?, ?)
                    ''', (data_json, metadata_json))
                
                conn.commit()
                conn.close()
            except Exception as e:
                self.logger.error(f"Error storing data chunk: {e}")
                raise
        
        await asyncio.get_event_loop().run_in_executor(None, store_data)


class BatchProcessor:
    """Process multiple operations in parallel with controlled concurrency."""
    
    def __init__(self, max_concurrent: int = 4):
        """Initialize the batch processor.
        
        Args:
            max_concurrent: Maximum number of concurrent operations
        """
        self.max_concurrent = max_concurrent
        self.logger = logging.getLogger(__name__)
        
    async def process_batch(
        self,
        operations: List[Callable],
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[Any]:
        """Process a batch of operations with controlled concurrency.
        
        Args:
            operations: List of callable operations to execute
            progress_callback: Callback for progress updates
            
        Returns:
            List of results from each operation
        """
        semaphore = asyncio.Semaphore(self.max_concurrent)
        results = []
        completed = 0
        
        async def execute_operation(operation):
            nonlocal completed
            async with semaphore:
                try:
                    result = await asyncio.get_event_loop().run_in_executor(None, operation)
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, len(operations))
                    return result
                except Exception as e:
                    self.logger.error(f"Error in batch operation: {e}")
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, len(operations))
                    return {"error": str(e)}
        
        # Execute all operations concurrently
        tasks = [execute_operation(op) for op in operations]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        return results


class DataCorrelator:
    """Correlate data across multiple artifact types for enhanced analysis."""
    
    def __init__(self, database_paths: Dict[str, str]):
        """Initialize the data correlator.
        
        Args:
            database_paths: Dictionary mapping artifact types to database paths
        """
        self.database_paths = database_paths
        self.logger = logging.getLogger(__name__)
        
    async def correlate_by_timestamp(
        self,
        time_window_minutes: int = 5,
        artifact_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Correlate artifacts based on timestamps within a time window.
        
        Args:
            time_window_minutes: Time window for correlation in minutes
            artifact_types: Specific artifact types to correlate (optional)
            
        Returns:
            List of correlated artifact groups
        """
        if artifact_types is None:
            artifact_types = list(self.database_paths.keys())
        
        # Collect all timestamped artifacts
        all_artifacts = []
        
        for artifact_type in artifact_types:
            if artifact_type in self.database_paths:
                artifacts = await self._get_timestamped_artifacts(artifact_type)
                all_artifacts.extend(artifacts)
        
        # Sort by timestamp
        all_artifacts.sort(key=lambda x: x.get('timestamp', ''))
        
        # Group artifacts within time windows
        correlations = []
        current_group = []
        current_time = None
        
        for artifact in all_artifacts:
            artifact_time = artifact.get('timestamp')
            if not artifact_time:
                continue
                
            if current_time is None:
                current_time = artifact_time
                current_group = [artifact]
            else:
                # Check if within time window
                time_diff = self._calculate_time_difference(current_time, artifact_time)
                if time_diff <= time_window_minutes:
                    current_group.append(artifact)
                else:
                    # Start new group
                    if len(current_group) > 1:  # Only keep groups with multiple artifacts
                        correlations.append({
                            "correlation_id": len(correlations) + 1,
                            "time_window_start": current_time,
                            "time_window_end": current_group[-1].get('timestamp'),
                            "artifacts": current_group,
                            "artifact_count": len(current_group),
                            "artifact_types": list(set(a.get('type') for a in current_group))
                        })
                    current_group = [artifact]
                    current_time = artifact_time
        
        # Don't forget the last group
        if len(current_group) > 1:
            correlations.append({
                "correlation_id": len(correlations) + 1,
                "time_window_start": current_time,
                "time_window_end": current_group[-1].get('timestamp'),
                "artifacts": current_group,
                "artifact_count": len(current_group),
                "artifact_types": list(set(a.get('type') for a in current_group))
            })
        
        return correlations
    
    async def _get_timestamped_artifacts(self, artifact_type: str) -> List[Dict[str, Any]]:
        """Get artifacts with timestamps from a specific database."""
        def query_artifacts():
            artifacts = []
            try:
                db_path = self.database_paths[artifact_type]
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # Get table names
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor.fetchall()
                
                for table_name in tables:
                    table_name = table_name[0]
                    
                    # Get column names
                    cursor.execute(f"PRAGMA table_info({table_name})")
                    columns = [col[1] for col in cursor.fetchall()]
                    
                    # Look for timestamp columns
                    timestamp_columns = [col for col in columns if any(
                        keyword in col.lower() for keyword in 
                        ['time', 'date', 'timestamp', 'created', 'modified', 'accessed']
                    )]
                    
                    if timestamp_columns:
                        # Query with timestamp
                        timestamp_col = timestamp_columns[0]  # Use first timestamp column
                        cursor.execute(f"SELECT * FROM {table_name} WHERE {timestamp_col} IS NOT NULL")
                        rows = cursor.fetchall()
                        
                        for row in rows:
                            artifact = {
                                "type": artifact_type,
                                "table": table_name,
                                "timestamp": row[columns.index(timestamp_col)],
                                "data": dict(zip(columns, row))
                            }
                            artifacts.append(artifact)
                
                conn.close()
            except Exception as e:
                self.logger.error(f"Error querying artifacts from {artifact_type}: {e}")
            
            return artifacts
        
        return await asyncio.get_event_loop().run_in_executor(None, query_artifacts)
    
    def _calculate_time_difference(self, time1: str, time2: str) -> float:
        """Calculate time difference in minutes between two timestamp strings."""
        # This is a simplified implementation - you might need more robust parsing
        # depending on the timestamp formats used in your artifacts
        try:
            from datetime import datetime
            
            # Try common timestamp formats
            formats = [
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S.%f"
            ]
            
            dt1 = dt2 = None
            for fmt in formats:
                try:
                    dt1 = datetime.strptime(time1, fmt)
                    dt2 = datetime.strptime(time2, fmt)
                    break
                except ValueError:
                    continue
            
            if dt1 and dt2:
                diff = abs((dt2 - dt1).total_seconds()) / 60  # Convert to minutes
                return diff
            
        except Exception as e:
            self.logger.error(f"Error calculating time difference: {e}")
        
        return float('inf')  # Return infinity if can't parse times


# Utility functions for common data processing tasks

async def optimize_database(db_path: str) -> ProcessingResult:
    """Optimize database by adding indexes and running VACUUM."""
    start_time = time.time()
    errors = []
    
    def optimize():
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get all tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            
            for table_name in tables:
                table_name = table_name[0]
                
                # Get column info
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = cursor.fetchall()
                
                # Create indexes on timestamp and common search columns
                for col_info in columns:
                    col_name = col_info[1]
                    if any(keyword in col_name.lower() for keyword in 
                          ['time', 'date', 'path', 'name', 'hash']):
                        try:
                            index_name = f"idx_{table_name}_{col_name}"
                            cursor.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name}({col_name})")
                        except Exception as e:
                            errors.append(f"Error creating index on {table_name}.{col_name}: {e}")
            
            # Vacuum database to optimize storage
            cursor.execute("VACUUM")
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            errors.append(f"Error optimizing database: {e}")
    
    await asyncio.get_event_loop().run_in_executor(None, optimize)
    
    duration = time.time() - start_time
    
    return ProcessingResult(
        success=len(errors) == 0,
        records_processed=0,
        errors=errors,
        duration_seconds=duration,
        metadata={"database_path": db_path}
    )


async def export_correlations_to_timeline(
    correlations: List[Dict[str, Any]],
    output_file: str
) -> ProcessingResult:
    """Export correlation data to a timeline format (JSON)."""
    start_time = time.time()
    
    try:
        # Create timeline format
        timeline_data = {
            "title": "Crow Eye Artifact Timeline",
            "events": []
        }
        
        for correlation in correlations:
            event = {
                "start_date": {
                    "year": int(correlation["time_window_start"][:4]),
                    "month": int(correlation["time_window_start"][5:7]),
                    "day": int(correlation["time_window_start"][8:10])
                },
                "text": {
                    "headline": f"Correlation Event {correlation['correlation_id']}",
                    "text": f"Found {correlation['artifact_count']} related artifacts: " +
                           ", ".join(correlation['artifact_types'])
                },
                "group": "correlations"
            }
            timeline_data["events"].append(event)
        
        # Save to file
        with open(output_file, 'w') as f:
            json.dump(timeline_data, f, indent=2)
        
        duration = time.time() - start_time
        
        return ProcessingResult(
            success=True,
            records_processed=len(correlations),
            errors=[],
            duration_seconds=duration,
            metadata={"output_file": output_file}
        )
        
    except Exception as e:
        duration = time.time() - start_time
        return ProcessingResult(
            success=False,
            records_processed=0,
            errors=[str(e)],
            duration_seconds=duration,
            metadata={}
        )