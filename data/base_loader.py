import sqlite3
import logging
from typing import Any, Dict, List, Optional, Tuple, Union, Iterator
from pathlib import Path
import json

class BaseDataLoader:
    """
    Base class for data loading operations with common database functionality.
    Handles database connections, query execution, and error handling.
    """
    
    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        """
        Initialize the data loader with an optional database path.
        
        Args:
            db_path: Path to the SQLite database file. If None, must be set later.
        """
        self.db_path = Path(db_path) if db_path else None
        self.connection = None
        self.logger = logging.getLogger(self.__class__.__name__)
        
    def connect(self, db_path: Optional[Union[str, Path]] = None, *, read_only: bool = True, timeout: float = 30.0, pragmas: Optional[Dict[str, Union[str, int]]] = None) -> bool:
        """
        Establish a connection to the database with optional optimizations.

        Args:
            db_path: Optional path to override the instance db_path.
            read_only: Open the database in read-only mode to avoid write locks.
            timeout: Connection timeout in seconds.
            pragmas: Optional PRAGMA settings to apply after connecting.

        Returns:
            bool: True if connection was successful, False otherwise.
        """
        if db_path:
            self.db_path = Path(db_path)

        if not self.db_path or not self.db_path.exists():
            self.logger.error(f"Database file not found: {self.db_path}")
            return False

        try:
            # Use read-only URI to prevent accidental locks when just reading
            if read_only:
                uri = f"file:{self.db_path}?mode=ro"
                self.connection = sqlite3.connect(uri, uri=True, timeout=timeout)
            else:
                self.connection = sqlite3.connect(str(self.db_path), timeout=timeout)

            # Return rows as dictionaries
            self.connection.row_factory = sqlite3.Row

            # Apply PRAGMAs for performance with large datasets
            self.apply_pragmas(pragmas)

            self.logger.debug(f"Connected to database: {self.db_path} (read_only={read_only})")
            return True
        except sqlite3.Error as e:
            self.logger.error(f"Error connecting to database {self.db_path}: {str(e)}")
            return False
            
    def disconnect(self):
        """Close the database connection if it's open."""
        if self.connection:
            self.connection.close()
            self.connection = None
            self.logger.debug("Database connection closed")
            
    def apply_pragmas(self, pragmas: Optional[Dict[str, Union[str, int]]] = None) -> None:
        """
        Apply PRAGMA settings to optimize SQLite for large read workloads.

        Args:
            pragmas: Optional dictionary of PRAGMA settings to apply.
        """
        if not self.connection:
            return

        # Default PRAGMAs tuned for fast, read-heavy operations
        default_pragmas: Dict[str, Union[str, int]] = {
            "journal_mode": "WAL",
            "synchronous": "NORMAL",
            "cache_size": 10000,  # Cache pages (negative values mean KB)
            "temp_store": "MEMORY",
            "busy_timeout": 30000,  # milliseconds
        }
        settings = {**default_pragmas, **(pragmas or {})}

        cursor = self.connection.cursor()
        try:
            # Apply each PRAGMA safely
            for key, value in settings.items():
                if key == "busy_timeout":
                    cursor.execute("PRAGMA busy_timeout = ?", (int(value),))
                else:
                    cursor.execute(f"PRAGMA {key} = {value}")
        except sqlite3.Error as e:
            self.logger.warning(f"Failed to apply PRAGMA settings: {e}")
            
    def get_row_count(self, table_name: str) -> int:
        """Return total row count for a table, or 0 on error."""
        if not self.connection:
            self.logger.error("No database connection. Call connect() first.")
            return 0
        try:
            cursor = self.connection.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            result = cursor.fetchone()
            return int(result[0]) if result else 0
        except sqlite3.Error as e:
            self.logger.error(f"Error counting rows in table '{table_name}': {e}")
            return 0
            
    def execute_query(self, query: str, params: Tuple = (), fetch: bool = True) -> List[Dict[str, Any]]:
        """
        Execute a SQL query and return the results.
        
        Args:
            query: SQL query to execute
            params: Parameters for the query
            fetch: Whether to fetch results (True for SELECT, False for INSERT/UPDATE)
            
        Returns:
            List of dictionaries representing the query results
        """
        if not self.connection:
            self.logger.error("No database connection. Call connect() first.")
            return []
            
        try:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            
            if fetch:
                columns = [column[0] for column in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
            else:
                self.connection.commit()
                return []
                
        except sqlite3.Error as e:
            self.logger.error(f"Error executing query: {str(e)}\nQuery: {query}")
            return []
            
    def get_table_names(self) -> List[str]:
        """Get a list of all tables in the database."""
        if not self.connection:
            return []
            
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as e:
            self.logger.error(f"Error getting table names: {str(e)}")
            return []
            
    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database."""
        if not self.connection:
            return False
            
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            return cursor.fetchone() is not None
        except sqlite3.Error as e:
            self.logger.error(f"Error checking if table exists: {str(e)}")
            return False

    def iterate_query(self, query: str, params: Tuple = (), page_size: int = 5000) -> Iterator[Dict[str, Any]]:
        """
        Stream results from a SELECT query in pages to minimize memory usage.

        Args:
            query: SQL SELECT query to execute.
            params: Parameters for the query.
            page_size: Number of rows to fetch per page.

        Yields:
            Dict rows representing each record.
        """
        if not self.connection:
            self.logger.error("No database connection. Call connect() first.")
            return iter(())
        try:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            columns = [column[0] for column in cursor.description]

            while True:
                rows = cursor.fetchmany(page_size)
                if not rows:
                    break
                for row in rows:
                    yield {col: row[idx] for idx, col in enumerate(columns)}
        except sqlite3.Error as e:
            self.logger.error(f"Error streaming query: {str(e)}\nQuery: {query}")
            return iter(())
            
    def export_query_to_json(self, output_path: Union[str, Path], query: str, params: Tuple = (), page_size: int = 5000) -> bool:
        """
        Export a SELECT query to a JSON file using streaming to avoid high memory usage.

        Args:
            output_path: Destination JSON path.
            query: SQL SELECT query to execute.
            params: Parameters for the query.
            page_size: Number of rows to fetch per page.

        Returns:
            True on success, False otherwise.
        """
        if not self.connection:
            self.logger.error("No database connection. Call connect() first.")
            return False
        output_path = Path(output_path)
        try:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            columns = [column[0] for column in cursor.description]

            with output_path.open("w", encoding="utf-8") as f:
                f.write("[")
                first = True
                while True:
                    rows = cursor.fetchmany(page_size)
                    if not rows:
                        break
                    for row in rows:
                        obj = {col: row[idx] for idx, col in enumerate(columns)}
                        if not first:
                            f.write(",")
                        f.write(json.dumps(obj, ensure_ascii=False))
                        first = False
                f.write("]")
            return True
        except sqlite3.Error as e:
            self.logger.error(f"Error exporting query to JSON: {str(e)}\nQuery: {query}")
            return False
        except OSError as e:
            self.logger.error(f"Filesystem error writing JSON: {e}")
            return False
            
    def verify_tables(self, required_tables: List[str]) -> Dict[str, bool]:
        """
        Verify presence of required tables in the database.

        Args:
            required_tables: List of table names to verify.

        Returns:
            Dict mapping table name to existence boolean.
        """
        presence: Dict[str, bool] = {}
        for t in required_tables:
            presence[t] = self.table_exists(t)
            if not presence[t]:
                self.logger.warning(f"Required table missing: {t}")
        return presence

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure connection is closed."""
        self.disconnect()

    def get_columns(self, table_name: str) -> List[str]:
        """
        Return column names for a given table using PRAGMA table_info.
        """
        if not self.connection:
            self.logger.error("No database connection. Call connect() first.")
            return []
        try:
            cursor = self.connection.cursor()
            cursor.execute(f"PRAGMA table_info({table_name})")
            return [row[1] for row in cursor.fetchall()]  # name is at index 1
        except sqlite3.Error as e:
            self.logger.error(f"Error getting columns for table '{table_name}': {e}")
            return []

    def index_exists(self, index_name: str) -> bool:
        """
        Check if an index exists in the database.
        """
        if not self.connection:
            return False
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (index_name,)
            )
            return cursor.fetchone() is not None
        except sqlite3.Error as e:
            self.logger.error(f"Error checking if index exists: {e}")
            return False

    def create_index_if_missing(self, table_name: str, columns: List[str], index_name: Optional[str] = None, unique: bool = False) -> bool:
        """
        Create an index on table(columns) if it doesn't already exist.

        Args:
            table_name: Name of the table.
            columns: List of column names to include in the index.
            index_name: Optional explicit index name. If None, generate one.
            unique: Whether to create a UNIQUE index.

        Returns:
            True if index exists or was created successfully, False otherwise.
        """
        if not self.connection:
            self.logger.error("No database connection. Call connect() first.")
            return False
        cols_key = "_".join(columns)
        index_name = index_name or f"idx_{table_name}_{cols_key}"
        try:
            if self.index_exists(index_name):
                return True
            cursor = self.connection.cursor()
            unique_sql = "UNIQUE " if unique else ""
            cursor.execute(f"CREATE {unique_sql}INDEX IF NOT EXISTS {index_name} ON {table_name} ({', '.join(columns)})")
            self.connection.commit()
            self.logger.debug(f"Ensured index {index_name} on {table_name}({cols_key})")
            return True
        except sqlite3.Error as e:
            self.logger.error(f"Error creating index {index_name} on {table_name}: {e}")
            return False

    def ensure_default_indexes(self) -> List[str]:
        """
        Ensure recommended indexes exist for MFT/USN/correlated datasets.
        This does not modify data; it only creates non-unique indexes to speed lookups.

        Returns:
            List of index names that were ensured (exist or created).
        """
        ensured: List[str] = []
        # Recommended indexes based on common query patterns
        index_specs = [
            # MFT databases
            {"table": "mft_records", "columns": ["record_number"], "name": "idx_mft_records_record_number"},
            {"table": "mft_standard_info", "columns": ["record_number"], "name": "idx_mft_si_record_number"},
            {"table": "mft_file_names", "columns": ["record_number"], "name": "idx_mft_fn_record_number"},
            {"table": "mft_file_names", "columns": ["parent_record_number"], "name": "idx_mft_fn_parent_record_number"},
            {"table": "mft_data_attributes", "columns": ["record_number"], "name": "idx_mft_da_record_number"},
            # USN journal
            {"table": "journal_events", "columns": ["usn"], "name": "idx_usn_usn"},
            {"table": "journal_events", "columns": ["frn"], "name": "idx_usn_frn"},
            {"table": "journal_events", "columns": ["parent_frn"], "name": "idx_usn_parent_frn"},
            {"table": "journal_events", "columns": ["timestamp"], "name": "idx_usn_timestamp"},
            # Correlated database
            {"table": "mft_usn_correlated", "columns": ["mft_record_number"], "name": "idx_corr_mft_record_number"},
            {"table": "mft_usn_correlated", "columns": ["usn_event_id"], "name": "idx_corr_usn_event_id"},
            {"table": "mft_usn_correlated", "columns": ["reconstructed_path"], "name": "idx_corr_reconstructed_path"},
        ]
        if not self.connection:
            self.logger.error("No database connection. Call connect() first.")
            return ensured
        available_tables = set(self.get_table_names())
        for spec in index_specs:
            table = spec["table"]
            if table in available_tables:
                name = spec["name"]
                cols = spec["columns"]
                if self.create_index_if_missing(table, cols, index_name=name):
                    ensured.append(name)
        return ensured

    def recommend_sizes(self, total_rows: int) -> Tuple[int, int]:
        """
        Recommend (page_size, batch_size) heuristics based on dataset size.
        """
        if total_rows >= 500_000:
            return (10000, 500)
        if total_rows >= 200_000:
            return (5000, 500)
        if total_rows >= 50_000:
            return (3000, 300)
        return (1000, 200)

    def stream_table(self, table_name: str, columns: Optional[List[str]] = None, where: Optional[str] = None, params: Tuple = (), order_by: Optional[str] = None, page_size: int = 5000) -> Iterator[Dict[str, Any]]:
        """
        Stream a table with optional WHERE and ORDER BY clauses.
        """
        select_cols = ", ".join(columns) if columns else "*"
        query = f"SELECT {select_cols} FROM {table_name}"
        if where:
            query += f" WHERE {where}"
        if order_by:
            query += f" ORDER BY {order_by}"
        return self.iterate_query(query, params, page_size=page_size)

    def stream_query_with_progress(self, query: str, params: Tuple = (), total_rows: Optional[int] = None, page_size: int = 5000, progress_callback: Optional[Any] = None, progress_label: str = "") -> Iterator[Dict[str, Any]]:
        """
        Stream a query and periodically invoke a progress callback.

        Args:
            query: SQL SELECT query.
            params: Parameters.
            total_rows: If known, used for percentage calculation.
            page_size: Rows per fetch.
            progress_callback: Callable(text_message) to report progress.
            progress_label: Optional label included in progress messages.
        """
        processed = 0
        for row in self.iterate_query(query, params, page_size):
            processed += 1
            if progress_callback and processed % (page_size) == 0:
                if total_rows:
                    pct = (processed / total_rows) * 100
                    progress_callback(f"{progress_label} {processed:,}/{total_rows:,} ({pct:0.1f}%)")
                else:
                    progress_callback(f"{progress_label} {processed:,} rows processed")
            yield row
        if progress_callback:
            if total_rows:
                progress_callback(f"{progress_label} Completed {processed:,}/{total_rows:,} (100.0%)")
            else:
                progress_callback(f"{progress_label} Completed {processed:,} rows")

    def count_query(self, query: str, params: Tuple = ()) -> int:
        """
        Execute a COUNT(*) style query and return integer count.
        """
        if not self.connection:
            self.logger.error("No database connection. Call connect() first.")
            return 0
        try:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
        except sqlite3.Error as e:
            self.logger.error(f"Error executing count query: {e}\nQuery: {query}")
            return 0

    def attach_database(self, alias: str, db_path: Union[str, Path]) -> bool:
        """
        ATTACH an external database to the current connection with an alias.
        """
        if not self.connection:
            self.logger.error("No database connection. Call connect() first.")
            return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("ATTACH DATABASE ? AS "+alias, (str(db_path),))
            self.logger.debug(f"Attached database '{db_path}' AS {alias}")
            return True
        except sqlite3.Error as e:
            self.logger.error(f"Error attaching database {db_path} as {alias}: {e}")
            return False

    def detach_database(self, alias: str) -> bool:
        """
        DETACH a previously attached database.
        """
        if not self.connection:
            self.logger.error("No database connection. Call connect() first.")
            return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("DETACH DATABASE "+alias)
            self.logger.debug(f"Detached database alias {alias}")
            return True
        except sqlite3.Error as e:
            self.logger.error(f"Error detaching database alias {alias}: {e}")
            return False

    def execute_many_in_batches(self, sql: str, rows: List[Tuple], batch_size: int = 1000) -> int:
        """
        Execute executemany in batches to avoid large transaction overhead.

        Returns:
            Total number of rows inserted/updated (best-effort).
        """
        if not self.connection:
            self.logger.error("No database connection. Call connect() first.")
            return 0
        total = 0
        try:
            cursor = self.connection.cursor()
            for i in range(0, len(rows), batch_size):
                chunk = rows[i:i+batch_size]
                cursor.executemany(sql, chunk)
                total += len(chunk)
            self.connection.commit()
            return total
        except sqlite3.Error as e:
            self.logger.error(f"Error executing batched operation: {e}")
            return total
