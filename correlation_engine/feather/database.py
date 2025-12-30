"""
Feather Database Manager
Handles creation and management of feather SQLite databases.
"""

import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Any


class FeatherDatabase:
    """Manages feather database operations."""
    
    def __init__(self, db_path: str, feather_name: str):
        """
        Initialize feather database.
        
        Args:
            db_path: Directory path for database
            feather_name: Name of the feather database
        """
        self.db_path = db_path
        self.feather_name = feather_name
        self.full_path = os.path.join(db_path, f"{feather_name}.db")
        self.connection = None
        self.cursor = None
    
    def connect(self):
        """Connect to the feather database."""
        self.connection = sqlite3.connect(self.full_path)
        self.cursor = self.connection.cursor()
    
    def close(self):
        """Close database connection."""
        if self.connection:
            self.connection.close()
    
    def create_base_schema(self):
        """Create base feather schema with common fields."""
        # Use key-value structure for metadata table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS feather_metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        # Insert metadata using key-value pairs
        timestamp = datetime.now().isoformat()
        metadata_entries = [
            ('feather_name', self.feather_name),
            ('feather_path', self.db_path),
            ('created_timestamp', timestamp),
            ('last_modified', timestamp),
            ('version', '1.0')
        ]
        
        for key, value in metadata_entries:
            self.cursor.execute('''
                INSERT OR REPLACE INTO feather_metadata (key, value)
                VALUES (?, ?)
            ''', (key, value))
        
        # Create import history table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS import_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,
                source_path TEXT NOT NULL,
                import_timestamp TEXT NOT NULL,
                records_imported INTEGER,
                columns_imported INTEGER,
                status TEXT,
                error_message TEXT
            )
        ''')
        
        # Create data lineage table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS data_lineage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feather_record_id INTEGER NOT NULL,
                original_source TEXT NOT NULL,
                source_table TEXT,
                source_row_id INTEGER,
                transformation_applied TEXT,
                import_id INTEGER,
                FOREIGN KEY (import_id) REFERENCES import_history(id)
            )
        ''')
        
        self.connection.commit()
    
    def create_feather_table(self, table_name: str, columns: List[Dict[str, Any]]):
        """
        Create a feather data table with dynamic schema.
        
        Args:
            table_name: Name of the feather table
            columns: List of column definitions
        """
        # Sanitize table name
        table_name = self.sanitize_identifier(table_name)
        
        # Base fields that all feather tables have
        base_fields = [
            "artifact_id INTEGER PRIMARY KEY AUTOINCREMENT",
            "source_tool TEXT",
            "collection_timestamp TEXT",
            "primary_timestamp TEXT",
            "artifact_type TEXT",
            "source_path TEXT"
        ]
        
        # Track used column names to avoid duplicates
        used_names = {'artifact_id', 'source_tool', 'collection_timestamp', 
                      'primary_timestamp', 'artifact_type', 'source_path'}
        
        # Add custom fields from import
        custom_fields = []
        for col in columns:
            if col['original'] == '[ROW_COUNT]':
                continue  # Skip, handled by artifact_id
            
            feather_name = self.sanitize_identifier(col['feather'])
            
            # Avoid duplicate column names
            if feather_name.lower() in used_names:
                counter = 1
                original_name = feather_name
                while f"{feather_name}_{counter}".lower() in used_names:
                    counter += 1
                feather_name = f"{original_name}_{counter}"
            
            used_names.add(feather_name.lower())
            col_type = self.map_data_type(col.get('type', 'TEXT'))
            custom_fields.append(f'"{feather_name}" {col_type}')
        
        all_fields = base_fields + custom_fields
        
        create_sql = f'''
            CREATE TABLE IF NOT EXISTS "{table_name}" (
                {', '.join(all_fields)}
            )
        '''
        
        self.cursor.execute(create_sql)
        
        # Create indexes for common search fields
        self.cursor.execute(f'''
            CREATE INDEX IF NOT EXISTS idx_{table_name}_timestamp 
            ON {table_name}(primary_timestamp)
        ''')
        
        self.cursor.execute(f'''
            CREATE INDEX IF NOT EXISTS idx_{table_name}_source 
            ON {table_name}(source_path)
        ''')
        
        self.connection.commit()
    
    def sanitize_identifier(self, name: str) -> str:
        """
        Sanitize table/column names for SQLite.
        
        Args:
            name: Original identifier name
            
        Returns:
            Sanitized identifier safe for SQLite
        """
        import re
        
        # Remove or replace invalid characters
        name = re.sub(r'[^\w]', '_', name)
        
        # Ensure it doesn't start with a number
        if name and name[0].isdigit():
            name = f'col_{name}'
        
        # Ensure it's not empty
        if not name:
            name = 'column'
        
        # Check against SQLite reserved words
        reserved_words = {
            'abort', 'action', 'add', 'after', 'all', 'alter', 'analyze', 'and', 'as',
            'asc', 'attach', 'autoincrement', 'before', 'begin', 'between', 'by',
            'cascade', 'case', 'cast', 'check', 'collate', 'column', 'commit',
            'conflict', 'constraint', 'create', 'cross', 'current_date', 'current_time',
            'current_timestamp', 'database', 'default', 'deferrable', 'deferred',
            'delete', 'desc', 'detach', 'distinct', 'drop', 'each', 'else', 'end',
            'escape', 'except', 'exclusive', 'exists', 'explain', 'fail', 'for',
            'foreign', 'from', 'full', 'glob', 'group', 'having', 'if', 'ignore',
            'immediate', 'in', 'index', 'indexed', 'initially', 'inner', 'insert',
            'instead', 'intersect', 'into', 'is', 'isnull', 'join', 'key', 'left',
            'like', 'limit', 'match', 'natural', 'no', 'not', 'notnull', 'null',
            'of', 'offset', 'on', 'or', 'order', 'outer', 'plan', 'pragma', 'primary',
            'query', 'raise', 'recursive', 'references', 'regexp', 'reindex', 'release',
            'rename', 'replace', 'restrict', 'right', 'rollback', 'row', 'savepoint',
            'select', 'set', 'table', 'temp', 'temporary', 'then', 'to', 'transaction',
            'trigger', 'union', 'unique', 'update', 'using', 'vacuum', 'values', 'view',
            'virtual', 'when', 'where', 'with', 'without'
        }
        
        if name.lower() in reserved_words:
            name = f'{name}_col'
        
        return name
    
    def map_data_type(self, original_type: str) -> str:
        """Map original data types to SQLite types."""
        type_mapping = {
            'INTEGER': 'INTEGER',
            'INT': 'INTEGER',
            'REAL': 'REAL',
            'FLOAT': 'REAL',
            'DOUBLE': 'REAL',
            'TEXT': 'TEXT',
            'VARCHAR': 'TEXT',
            'CHAR': 'TEXT',
            'BLOB': 'BLOB',
            'DATETIME': 'TEXT',
            'DATE': 'TEXT',
            'TIMESTAMP': 'TEXT'
        }
        
        return type_mapping.get(original_type.upper(), 'TEXT')
    
    def insert_data(self, table_name: str, data: List[Dict[str, Any]], 
                   source_info: Dict[str, Any], columns: List[Dict[str, Any]]):
        """
        Insert data into feather table.
        
        Args:
            table_name: Name of the feather table
            data: List of data records to insert
            source_info: Information about data source
            columns: Column mapping configuration
        """
        # Sanitize table name
        table_name = self.sanitize_identifier(table_name)
        
        # Record import in history
        self.cursor.execute('''
            INSERT INTO import_history 
            (source_type, source_path, import_timestamp, records_imported, columns_imported, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            source_info['source_type'],
            source_info['source_path'],
            datetime.now().isoformat(),
            len(data),
            len(columns),
            'in_progress'
        ))
        
        import_id = self.cursor.lastrowid
        
        try:
            # Prepare column names (excluding generated fields) and sanitize them
            data_columns = [self.sanitize_identifier(col['feather']) for col in columns if col['original'] != '[ROW_COUNT]']
            
            # Add base fields
            all_columns = [
                'source_tool', 'collection_timestamp', 'primary_timestamp',
                'artifact_type', 'source_path'
            ] + data_columns
            
            placeholders = ', '.join(['?' for _ in all_columns])
            columns_str = ', '.join([f'"{col}"' for col in all_columns])
            
            insert_sql = f'''
                INSERT INTO "{table_name}" ({columns_str})
                VALUES ({placeholders})
            '''
            
            # Insert each record
            for row_idx, record in enumerate(data):
                # Base values
                base_values = [
                    source_info.get('source_tool', 'Unknown'),
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                    source_info.get('artifact_type', 'imported'),
                    source_info['source_path']
                ]
                
                # Data values
                data_values = []
                for col in columns:
                    if col['original'] == '[ROW_COUNT]':
                        continue
                    
                    value = record.get(col['original'], '')
                    data_values.append(value)
                
                all_values = base_values + data_values
                
                self.cursor.execute(insert_sql, all_values)
                
                # Record lineage
                feather_record_id = self.cursor.lastrowid
                self.cursor.execute('''
                    INSERT INTO data_lineage 
                    (feather_record_id, original_source, source_row_id, import_id)
                    VALUES (?, ?, ?, ?)
                ''', (
                    feather_record_id,
                    source_info['source_path'],
                    row_idx + 1,
                    import_id
                ))
            
            # Update import status
            self.cursor.execute('''
                UPDATE import_history 
                SET status = 'completed'
                WHERE id = ?
            ''', (import_id,))
            
            self.connection.commit()
            return True, None
            
        except Exception as e:
            # Update import status with error
            self.cursor.execute('''
                UPDATE import_history 
                SET status = 'failed', error_message = ?
                WHERE id = ?
            ''', (str(e), import_id))
            
            self.connection.commit()
            return False, str(e)
    
    def get_table_names(self) -> List[str]:
        """Get all feather table names."""
        self.cursor.execute('''
            SELECT name FROM sqlite_master 
            WHERE type='table' 
            AND name NOT LIKE 'feather_%' 
            AND name NOT LIKE 'import_%'
            AND name NOT LIKE 'data_%'
            AND name NOT LIKE 'sqlite_%'
        ''')
        
        return [row[0] for row in self.cursor.fetchall()]
    
    def get_table_data(self, table_name: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get data from feather table."""
        table_name = self.sanitize_identifier(table_name)
        self.cursor.execute(f'SELECT * FROM "{table_name}" LIMIT {limit}')
        
        columns = [description[0] for description in self.cursor.description]
        rows = self.cursor.fetchall()
        
        return [dict(zip(columns, row)) for row in rows]
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get feather database statistics."""
        stats = {
            'feather_name': self.feather_name,
            'feather_path': self.full_path,
            'tables': [],
            'total_records': 0
        }
        
        tables = self.get_table_names()
        
        for table in tables:
            self.cursor.execute(f'SELECT COUNT(*) FROM {table}')
            count = self.cursor.fetchone()[0]
            
            stats['tables'].append({
                'name': table,
                'record_count': count
            })
            stats['total_records'] += count
        
        return stats
