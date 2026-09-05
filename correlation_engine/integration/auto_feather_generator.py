"""
Auto Feather Generator

Automatically generates Feathers from Crow-Eye parser output databases.
Converts parsed forensic artifacts into standardized Feather format for correlation analysis.
"""

import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any

# Import from Crow-Eye root config directory
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config.configuration_manager import ConfigurationManager
from correlation_engine.config.feather_config import FeatherConfig

from .feather_mappings import get_feather_mappings

logger = logging.getLogger(__name__)


# Parser bookkeeping - when the parser wrote the row, never when the thing
# happened. Excluded from every feather by NAME, never by position.
#
# It used to be `exclude_last_column: True`, which dropped whichever column
# happened to be last. That was tuned to a schema that has since moved, and by
# the time anyone looked it was cutting `user_name` off four user-activity
# feathers - Shellbags, MUICache, OpenSaveMRU and LastSaveMRU - the column that
# attributes an artifact to a person. Nothing failed; the feathers were simply
# built without it. Meanwhile three AmCache feathers carried `parsed_at` in as
# though it were evidence, because their flag said False.
#
# `parsed_at` is the canonical name and the ONLY one safe to exclude globally.
#
# The legacy aliases - timestamp, analyzing_date, created_at, parsed_timestamp -
# are NOT safe to exclude by name, and treating them as though they were is a
# mistake worth recording: a first pass at this fix stripped
# `srum_application_usage.timestamp`, which is the SRUM event time and the most
# important column in the table. Measured across the reference cases, the same
# spelling means two different things:
#
#     MUICache.timestamp                 110 rows,    1 distinct -> parse time
#     SystemServices.timestamp           814 rows,    4 distinct -> parse time
#     srum_application_usage.timestamp 30190 rows,  191 distinct -> EVENT time
#     srum_network_data_usage.timestamp 32002 rows, 2026 distinct -> EVENT time
#
# So a legacy alias is bookkeeping only where its mapping says so, and each such
# declaration is checked against that distinct-value evidence by
# test_feathers_keep_their_evidence.
BOOKKEEPING_COLUMNS = frozenset({"parsed_at"})

# Names that are bookkeeping in some tables and evidence in others. Listing one
# of these in a mapping's `bookkeeping_columns` is a per-table claim.
AMBIGUOUS_BOOKKEEPING_NAMES = frozenset({
    "timestamp", "analyzing_date", "created_at", "parsed_timestamp",
})


def is_bookkeeping_column(name, mapping=None) -> bool:
    """True if `name` is bookkeeping - globally, or for this mapping's table.

    `mapping` is optional so callers that only have a column name still get the
    unambiguous `parsed_at` answer, but anything deciding what to put in a
    feather must pass it, or a genuine event time gets thrown away.
    """
    if not name:
        return False
    lowered = str(name).strip().lower()
    if lowered in BOOKKEEPING_COLUMNS:
        return True
    declared = (mapping or {}).get('bookkeeping_columns') or ()
    return lowered in {str(c).strip().lower() for c in declared}


class AutoFeatherGenerator:
    """
    Generates Feathers automatically from Crow-Eye parser output.
    
    This class handles the automatic conversion of Crow-Eye parsed databases
    into standardized Feather format, including:
    - Reading source database schemas
    - Excluding parsing timestamp columns
    - Creating Feather databases with metadata
    - Registering Feathers with Configuration Manager
    """
    
    def __init__(self, case_directory: str):
        """
        Initialize AutoFeatherGenerator.
        
        Args:
            case_directory: Path to the case directory
        """
        self.case_directory = Path(case_directory)
        # Support both Target_Artifacts (live parsers) and live_acquisition (offline parsers)
        self.target_artifacts_dir = self.case_directory / "Target_Artifacts"
        self.live_acquisition_dir = self.case_directory / "live_acquisition"
        self.feather_output_dir = self.case_directory / "Correlation" / "feathers"
        self.config_manager = ConfigurationManager.get_instance()
        
        # Ensure output directory exists
        self.feather_output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_all_feathers(self, progress_callback=None) -> Dict[str, Any]:
        """
        Generate all Feathers from parser output with progress tracking and error handling.
        
        Args:
            progress_callback: Optional callback function(current, total, feather_name, status)
                             to report progress
        
        Returns:
            Dictionary with generation results:
            {
                'successful': [list of generated feather paths],
                'failed': [list of (feather_name, error_message) tuples],
                'total': total number of mappings,
                'success_count': number of successful generations,
                'failure_count': number of failed generations
            }
        """
        generated_feathers = []
        failed_feathers = []
        
        # Get feather generation mappings
        mappings = self._get_feather_mappings()
        total_mappings = len(mappings)
        
        logger.info(f"Starting Feather generation for {total_mappings} mappings")
        
        for idx, mapping in enumerate(mappings, 1):
            feather_name = mapping['name']
            
            # Report progress
            if progress_callback:
                progress_callback(idx, total_mappings, feather_name, 'processing')
            
            try:
                # Generate feather
                feather_path = self._generate_feather(mapping)
                generated_feathers.append(feather_path)
                
                logger.info(f"[OK] [{idx}/{total_mappings}] Generated: {feather_name}")
                
                # Report success
                if progress_callback:
                    progress_callback(idx, total_mappings, feather_name, 'success')
                    
            except FileNotFoundError as e:
                error_msg = f"Source database not found: {e}"
                failed_feathers.append((feather_name, error_msg))
                logger.warning(f"[FAIL] [{idx}/{total_mappings}] Skipped {feather_name}: {error_msg}")
                
                # Report failure
                if progress_callback:
                    progress_callback(idx, total_mappings, feather_name, 'skipped')
                    
            except Exception as e:
                error_msg = str(e)
                failed_feathers.append((feather_name, error_msg))
                logger.error(f"[FAIL] [{idx}/{total_mappings}] Failed to generate {feather_name}: {error_msg}")
                
                # Report failure
                if progress_callback:
                    progress_callback(idx, total_mappings, feather_name, 'failed')
        
        # Generate summary
        success_count = len(generated_feathers)
        failure_count = len(failed_feathers)
        
        logger.info(f"Feather generation complete: {success_count}/{total_mappings} successful, "
                   f"{failure_count} failed/skipped")
        
        # Log detailed failure information
        if failed_feathers:
            logger.info("Failed/Skipped Feathers:")
            for name, error in failed_feathers:
                logger.info(f" - {name}: {error}")
        
        return {
            'successful': generated_feathers,
            'failed': failed_feathers,
            'total': total_mappings,
            'success_count': success_count,
            'failure_count': failure_count
        }
    
    def _get_feather_mappings(self) -> List[Dict]:
        """
        Get all feather generation mappings.
        
        Returns:
            List of mapping dictionaries
        """
        return get_feather_mappings()
    
    def _generate_feather(self, mapping: Dict) -> str:
        """
        Generate a single Feather from mapping configuration.
        
        Searches for source database in both Target_Artifacts (live parsers)
        and live_acquisition (offline parsers) directories.
        
        Args:
            mapping: Feather generation mapping
            
        Returns:
            Path to generated Feather
            
        Raises:
            FileNotFoundError: If source database not found in either location
            Exception: If Feather generation fails
        """
        # Try both Target_Artifacts (live parsers) and live_acquisition (offline parsers)
        source_db_path = None
        source_location = None
        
        # Check Target_Artifacts first (live parsers)
        target_artifacts_path = self.target_artifacts_dir / mapping['source_db']
        if target_artifacts_path.exists():
            source_db_path = target_artifacts_path
            source_location = "Target_Artifacts (live parser)"
            logger.debug(f"Found source database in Target_Artifacts: {source_db_path}")
        
        # Check live_acquisition (offline parsers)
        if not source_db_path:
            live_acquisition_path = self.live_acquisition_dir / mapping['source_db']
            if live_acquisition_path.exists():
                source_db_path = live_acquisition_path
                source_location = "live_acquisition (offline parser)"
                logger.debug(f"Found source database in live_acquisition: {source_db_path}")
        
        # If the database is not in either location, the parser that writes it
        # was never run for this case. That is ordinary - an analyst may parse
        # the registry and nothing else - and it must not take down every wing
        # that references the feather. Same reasoning as the absent-table case
        # below, one level up.
        db_missing = source_db_path is None
        if db_missing:
            if not mapping.get('fallback_columns'):
                raise FileNotFoundError(
                    f"Source database '{mapping['source_db']}' not found in either:\n"
                    f" - {self.target_artifacts_dir}\n"
                    f" - {self.live_acquisition_dir}\n"
                    f"and the mapping declares no fallback_columns"
                )
            source_db_path = target_artifacts_path  # for the metadata only
            source_location = "absent (empty feather)"
            logger.info(
                "Source database %s not present in this case - generating an "
                "empty %s so wings still resolve",
                mapping['source_db'], mapping['name'])

        logger.debug(f"Generating {mapping['name']} from {source_location}: {source_db_path}")

        source_conn = None
        try:
            # Connect to source database. An absent database becomes an empty
            # one, so the table-missing branch below builds the feather from the
            # mapping's declared columns - one path for both kinds of absence
            # rather than a second copy of the builder.
            source_conn = sqlite3.connect(
                ":memory:" if db_missing else str(source_db_path))
            source_cursor = source_conn.cursor()
            
            # Get table schema
            source_cursor.execute(f"PRAGMA table_info({mapping['source_table']})")
            columns = source_cursor.fetchall()
            
            table_missing = not columns
            if table_missing:
                # A table this build of the parsers does not write - most often
                # a case parsed before it existed.
                #
                # This used to raise, which failed the mapping, which failed
                # dependency validation, which killed EVERY wing referencing the
                # feather - not just that one reference. So adding a mapping for
                # a new table would silently disable whole wings on every older
                # case in the analyst's folder.
                #
                # Build the feather empty instead, from the columns the mapping
                # declares. The wing resolves, contributes no matches, and says
                # so. `fallback_columns` is checked against the parser's real
                # CREATE TABLE by a test, because a declared shape that drifts
                # from the schema is worse than none.
                fallback = mapping.get('fallback_columns') or []
                if not fallback:
                    raise Exception(
                        f"Table {mapping['source_table']} not found in "
                        f"{source_db_path.name} and the mapping declares no "
                        f"fallback_columns - cannot build an empty feather")
                # Shaped like PRAGMA table_info rows: (cid, name, type, ...)
                columns = [(i, name, col_type, 0, None, 0)
                           for i, (name, col_type) in enumerate(fallback)]
                logger.info(
                    "Table %s absent from %s - generating an empty feather from "
                    "the %d declared column(s) so wings still resolve",
                    mapping['source_table'], source_db_path.name, len(fallback))

            # Drop parser bookkeeping columns by name, whatever position they
            # sit in. See BOOKKEEPING_COLUMNS for why this is not positional.
            dropped = [c[1] for c in columns if is_bookkeeping_column(c[1], mapping)]
            if dropped:
                columns = [c for c in columns
                           if not is_bookkeeping_column(c[1], mapping)]
                logger.debug(
                    f"Excluded bookkeeping column(s) from "
                    f"{mapping['source_table']}: {', '.join(dropped)}")
            if not columns:
                raise Exception(
                    f"Table {mapping['source_table']} has nothing but bookkeeping "
                    f"columns ({', '.join(dropped)}) - refusing to build an "
                    f"evidence-free feather")

            # Sanitize column names and filter out None/empty (Fixes "no such column: None")
            valid_columns = []
            for col in columns:
                name = col[1]
                if name and isinstance(name, str):
                    valid_columns.append(col)
                else:
                    logger.warning(f"Skipped invalid column definition in {mapping['source_table']}: {col}")
            
            columns = valid_columns
            column_names = [col[1] for col in columns]
            
            # Support column mapping for standardization
            column_mapping = mapping.get('column_mapping', {})
            
            # Build SELECT query with aliasing if mapping exists
            select_cols_list = []
            for col_name in column_names:
                if col_name in column_mapping:
                    alias = column_mapping[col_name]
                    select_cols_list.append(f'"{col_name}" AS "{alias}"')
                else:
                    select_cols_list.append(f'"{col_name}"')
            
            select_cols = ', '.join(select_cols_list)
            query = f"SELECT {select_cols} FROM {mapping['source_table']}"
            
            # Add filter if specified
            if mapping.get('filter'):
                query += f" WHERE {mapping['filter']}"
                logger.debug(f"Applied filter: {mapping['filter']}")
            
            # Execute query to get data. There is nothing to select when the
            # table is absent - the columns above came from the mapping, not
            # from the database.
            if table_missing:
                rows = []
            else:
                source_cursor.execute(query)
                rows = source_cursor.fetchall()

            logger.debug(f"Retrieved {len(rows)} rows from {mapping['source_table']}")
            
            # Create output Feather database
            feather_path = self.feather_output_dir / f"{mapping['name']}.db"
            
            # Remove existing feather if it exists
            if feather_path.exists():
                feather_path.unlink()
                logger.debug(f"Removed existing feather: {feather_path}")
            
            feather_conn = sqlite3.connect(str(feather_path))
            try:
                feather_cursor = feather_conn.cursor()
                
                # Create feather_metadata table with key-value structure (matching FeatherBuilder schema)
                feather_cursor.execute('''
                    CREATE TABLE IF NOT EXISTS feather_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                ''')
                
                # Insert metadata as key-value pairs
                feather_id = mapping['name'].replace('_CrowEyeFeather', '').lower()
                timestamp = datetime.now().isoformat()
                
                metadata_entries = [
                    ('feather_id', feather_id),
                    ('feather_name', mapping['name']),
                    ('artifact_type', mapping['artifact_type']),
                    ('created_date', timestamp),
                    ('last_modified', timestamp),
                    ('version', '1.0'),
                    ('source_database', str(source_db_path)),
                    ('source_table', mapping['source_table']),
                    ('auto_generated', 'true'),
                    ('filter', mapping.get('filter', '')),
                    ('row_count', str(len(rows))),
                    # What was actually dropped, by name. The old key recorded
                    # a boolean flag that said nothing about which column went,
                    # which is why four feathers could lose `user_name` without
                    # leaving a trace anywhere. Kept under the same key so
                    # anything reading existing feather metadata still finds it.
                    ('exclude_last_column', ', '.join(dropped) if dropped else 'none'),
                    ('source_table_present', 'false' if table_missing else 'true')
                ]
                
                for key, value in metadata_entries:
                    feather_cursor.execute('''
                        INSERT OR REPLACE INTO feather_metadata (key, value)
                        VALUES (?, ?)
                    ''', (key, value))
                
                # Create data table with mapped column names
                mapped_columns = []
                for col in columns:
                    name = col[1]
                    col_type = col[2]
                    # Use alias if mapped
                    if name in column_mapping:
                        mapped_columns.append(f'"{column_mapping[name]}" {col_type}')
                    else:
                        mapped_columns.append(f'"{name}" {col_type}')
                
                col_defs = ', '.join(mapped_columns)
                feather_cursor.execute(f'''
                    CREATE TABLE IF NOT EXISTS {mapping['source_table']} (
                        {col_defs}
                    )
                ''')
                
                # Update column names for insertion (use aliases if mapped)
                target_column_names = []
                for name in column_names:
                    if name in column_mapping:
                        target_column_names.append(column_mapping[name])
                    else:
                        target_column_names.append(name)
                
                # Insert data
                if rows:
                    placeholders = ', '.join(['?' for _ in target_column_names])
                    feather_cursor.executemany(
                        f'INSERT INTO {mapping["source_table"]} VALUES ({placeholders})',
                        rows
                    )
                
                # Create indexes for common columns (use target names)
                self._create_indexes(feather_cursor, mapping['source_table'], target_column_names)
                
                # Commit and close feather database
                feather_conn.commit()
                
                logger.debug(f"Created feather database: {feather_path}")
                
            finally:
                feather_conn.close()
            
            # Create FeatherConfig and save as JSON
            feather_config = self._create_feather_config(
                mapping=mapping,
                feather_path=feather_path,
                column_names=target_column_names,
                row_count=len(rows),
                source_db_path=source_db_path
            )
            
            # Save FeatherConfig as JSON file
            config_json_path = self.feather_output_dir / f"{mapping['name']}.json"
            feather_config.save_to_file(str(config_json_path))
            logger.debug(f"Saved FeatherConfig JSON: {config_json_path}")
            
            # Create metadata dict for Configuration Manager
            config_metadata = {
                'source_database': str(source_db_path),
                'source_table': mapping['source_table'],
                'auto_generated': True,
                'filter': mapping.get('filter', None),
                'row_count': len(rows)
            }
            
            # Register with Configuration Manager
            self.config_manager.add_feather(
                feather_id=feather_id,
                db_path=str(feather_path),
                artifact_type=mapping['artifact_type'],
                metadata=config_metadata
            )
            
            logger.debug(f"Registered feather with Configuration Manager: {feather_id}")
            
            return str(feather_path)
            
        finally:
            if source_conn:
                source_conn.close()
    
    def _create_feather_config(self, mapping: Dict, feather_path: Path,
                              column_names: List[str], row_count: int,
                              source_db_path: Path) -> FeatherConfig:
        """
        Create a FeatherConfig object with all required fields.
        
        Args:
            mapping: Feather generation mapping
            feather_path: Path to generated feather database
            column_names: List of column names in the feather
            row_count: Number of rows in the feather
            source_db_path: Path to source database
            
        Returns:
            FeatherConfig object
        """
        feather_id = mapping['name'].replace('_CrowEyeFeather', '').lower()
        
        # Detect timestamp column (first column with time/date in name)
        timestamp_col = next(
            (col for col in column_names 
             if any(keyword in col.lower() for keyword in ['time', 'date', 'timestamp'])),
            column_names[0] if column_names else 'timestamp'
        )
        
        # Detect application/program column
        app_col = next(
            (col for col in column_names 
             if any(keyword in col.lower() for keyword in ['app', 'program', 'executable', 'name'])),
            None
        )
        
        # Detect path column
        path_col = next(
            (col for col in column_names 
             if any(keyword in col.lower() for keyword in ['path', 'file', 'location'])),
            None
        )
        
        # Create column mapping (identity mapping since we're not renaming columns)
        column_mapping = {col: col for col in column_names}
        
        return FeatherConfig(
            config_name=feather_id,
            feather_name=mapping['name'],
            artifact_type=mapping['artifact_type'],
            source_database=str(source_db_path),
            source_table=mapping['source_table'],
            selected_columns=column_names,
            column_mapping=column_mapping,
            timestamp_column=timestamp_col,
            timestamp_format='ISO8601', # Crow-Eye uses ISO format
            output_database=str(feather_path),
            # Crow-Eye's source DB stores all timestamps in UTC. Override per
            # feather if a downstream tool ingests local-time exports.
            source_timezone='UTC',
            application_column=app_col,
            path_column=path_col,
            created_date=datetime.now().isoformat(),
            created_by='Auto-Generated',
            description=f'Auto-generated feather from {mapping["source_db"]} - {mapping["source_table"]}',
            notes=f'Filter: {mapping.get("filter", "None")}',
            total_records=row_count
        )
    
    def _create_indexes(self, cursor: sqlite3.Cursor, table_name: str, 
                       column_names: List[str]) -> None:
        """
        Create indexes on common columns for performance.
        
        Args:
            cursor: Database cursor
            table_name: Name of the table
            column_names: List of column names
        """
        try:
            # Index on timestamp columns
            timestamp_cols = [col for col in column_names 
                            if 'timestamp' in col.lower() or 'time' in col.lower() 
                            or 'date' in col.lower()]
            
            for col in timestamp_cols:
                try:
                    cursor.execute(f'''
                        CREATE INDEX IF NOT EXISTS idx_{col.replace(" ", "_")} 
                        ON {table_name}("{col}")
                    ''')
                except Exception as e:
                    logger.debug(f"Could not create index on {col}: {e}")
            
            # Index on application/program columns
            app_cols = [col for col in column_names 
                       if 'application' in col.lower() or 'app' in col.lower() 
                       or 'program' in col.lower() or 'executable' in col.lower()]
            
            for col in app_cols:
                try:
                    cursor.execute(f'''
                        CREATE INDEX IF NOT EXISTS idx_{col.replace(" ", "_")} 
                        ON {table_name}("{col}")
                    ''')
                except Exception as e:
                    logger.debug(f"Could not create index on {col}: {e}")
            
            # Index on path columns
            path_cols = [col for col in column_names 
                        if 'path' in col.lower() or 'file' in col.lower()]
            
            for col in path_cols:
                try:
                    cursor.execute(f'''
                        CREATE INDEX IF NOT EXISTS idx_{col.replace(" ", "_")} 
                        ON {table_name}("{col}")
                    ''')
                except Exception as e:
                    logger.debug(f"Could not create index on {col}: {e}")
                    
        except Exception as e:
            logger.warning(f"Error creating indexes: {e}")
