"""
Auto Feather Generator

Automatically generates Feathers from Crow-Eye parser output databases.
Converts parsed forensic artifacts into standardized Feather format for correlation analysis.
"""

import sqlite3
import threading
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any

# Import from Crow-Eye root config directory
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
# config.configuration_manager is a Qt QObject; it is imported where it is
# used (AutoFeatherGenerator.__init__), not here. Importing it at module level
# pulled PyQt5.QtCore into every `import correlation_engine.integration` - and
# so into the headless Behavioural engine, which the Sentinel server imports
# with no Qt at all (tests/test_behavioural_engine_is_headless.py).
from correlation_engine.config.feather_config import FeatherConfig

from .feather_mappings import get_feather_mappings


def source_fingerprint(path) -> str:
    """Size and modification time of a source database and its WAL file: what
    changes when a parser writes to it. Recorded in feather_metadata so a
    feather built from an older parse is known to be stale."""
    parts = []
    for p in (Path(path), Path(str(path) + '-wal')):
        try:
            st = p.stat()
            parts.append('%d:%d' % (st.st_size, st.st_mtime_ns))
        except OSError:
            parts.append('-')
    return '/'.join(parts)


def stale_feathers(feathers_dir) -> List[str]:
    """Names of the feathers in `feathers_dir` whose source changed since they
    were built, or that were built before the fingerprint was recorded. The
    feather is opened read-only and immutable, so the check writes nothing
    (not even a -shm file) beside it."""
    out = []
    for db in sorted(Path(feathers_dir).glob('*_CrowEyeFeather.db')):
        try:
            conn = sqlite3.connect(_sqlite_uri(db, 'ro') + '&immutable=1', uri=True)
            try:
                meta = dict(conn.execute(
                    "SELECT key, value FROM feather_metadata "
                    "WHERE key IN ('source_database', 'source_fingerprint')").fetchall())
            finally:
                conn.close()
        except sqlite3.Error:
            out.append(db.stem)
            continue
        recorded = meta.get('source_fingerprint')
        source = meta.get('source_database')
        if source and Path(source).parent.name == 'UBA':
            evidence = Path(source).parent.parent / 'Target_Artifacts'
            try:
                built = db.stat().st_mtime
                if any(p.stat().st_mtime > built for p in evidence.glob('*.db')):
                    out.append(db.stem)
                    continue
            except OSError:
                pass
        if not recorded or not source:
            out.append(db.stem)
        elif recorded == 'missing':
            # Built empty because the source was absent: stale only once a
            # parse has produced it (never rebuilt on every load).
            if Path(source).exists():
                out.append(db.stem)
        elif Path(source).exists() and source_fingerprint(source) != recorded:
            # A source that is gone leaves the feather as built: rebuilding it
            # would throw its rows away.
            out.append(db.stem)
    return out


def feathers_to_build(feathers_dir) -> List[str]:
    """The feathers an automatic build needs: those missing (no .db or no .json) and those
    stale. Any one of them used to rebuild all 42, the UBA analysis and the 280 MB MFT
    feather included, every time the Correlation Engine opened."""
    from .feather_mappings import get_feather_mappings
    d = Path(feathers_dir)
    names = [m['name'] for m in get_feather_mappings()]
    missing = [n for n in names if not (d / (n + '.db')).exists() or not (d / (n + '.json')).exists()]
    stale = stale_feathers(d) if d.exists() else []
    return [n for n in names if n in set(missing) | set(stale)]


def _sqlite_uri(path, mode=None) -> str:
    """A SQLite URI for `path`, percent-encoded (case folders hold spaces, and
    a '#' or '?' in a folder name would end the path), optionally read-only."""
    from urllib.parse import quote
    uri = 'file:' + quote(Path(path).resolve().as_posix(), safe='/:')
    return uri + ('?mode=%s' % mode if mode else '')


def _utc_now_text() -> str:
    """Now, in UTC, the way every Crow-Eye timestamp is written (utils/time_utils)."""
    try:
        from utils.time_utils import format_forensic_timestamp, get_current_utc
        return format_forensic_timestamp(get_current_utc())
    except Exception:                                    # pragma: no cover
        from datetime import timezone
        return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

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
        self._uba_lock = threading.Lock()
        self._uba_checked = False
        self.live_acquisition_dir = self.case_directory / "live_acquisition"
        self.feather_output_dir = self.case_directory / "Correlation" / "feathers"
        from config.configuration_manager import ConfigurationManager
        self.config_manager = ConfigurationManager.get_instance()
        
        # Ensure output directory exists
        self.feather_output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_all_feathers(self, progress_callback=None, should_cancel=None,
                              idle_callback=None, max_workers=None, started_callback=None,
                              only=None, register=True, uba_progress=None) -> Dict[str, Any]:
        """
        Generate all Feathers from parser output, several at once.

        Each feather is its own SQLite file built inside SQLite (ATTACH +
        INSERT ... SELECT), which releases the GIL, so a thread pool builds
        them in parallel. Everything that touches the caller's world runs on
        the calling thread: `progress_callback(current, total, name, status)`
        after each feather, `idle_callback()` every 100 ms while waiting (the
        GUI passes QApplication.processEvents, so the window stays live while
        the 280 MB MFT feather builds), and the registry is written once at
        the end. `should_cancel()` returning True stops every feather not yet
        started; one already building finishes, so no file is left half-made.

        `started_callback(name)` is called from the pool thread when a feather really starts
        (progress_callback alone named the last one to FINISH, so a fast SRUM feather stayed
        on screen while the MFT feather or the UBA analysis ran). `only` limits the build to
        those feather names. `register=False` leaves the registry to the caller - a worker
        thread hands 'registrations' back to the GUI thread, since ConfigurationManager is a
        QObject. `uba_progress(percent, label)` reports the user behaviour analysis that the
        Behaviour feather runs first.

        Returns:
            {'successful', 'failed', 'total', 'success_count', 'failure_count', 'cancelled',
             'registrations', 'seconds'}
        """
        import os
        from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

        mappings = self._get_feather_mappings()
        if only is not None:
            wanted = set(only)
            mappings = [m for m in mappings if m['name'] in wanted]
        self._uba_progress = uba_progress
        total_mappings = len(mappings)
        import time as _time
        seconds: Dict[str, float] = {}

        def build(mapping):
            t0 = _time.monotonic()
            if started_callback is not None:
                try:
                    started_callback(mapping['name'])
                except Exception:
                    pass
            try:
                return self._generate_feather(mapping)
            finally:
                seconds[mapping['name']] = _time.monotonic() - t0
        workers = max_workers or max(1, min(4, (os.cpu_count() or 2) - 1))
        logger.info(f"Starting Feather generation for {total_mappings} mappings, {workers} at a time")

        done_by_index: Dict[int, Any] = {}
        registrations = []
        cancelled = False
        finished = 0
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="feather") as pool:
            futures = {pool.submit(build, m): (i, m) for i, m in enumerate(mappings)}
            pending = set(futures)
            while pending:
                done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in done:
                    i, mapping = futures[future]
                    name = mapping['name']
                    finished += 1
                    if future.cancelled():
                        done_by_index[i] = ('cancelled', name, 'cancelled')
                        continue
                    try:
                        path, registration = future.result()
                        done_by_index[i] = ('ok', name, path)
                        registrations.append(registration)
                        status = 'success'
                    except FileNotFoundError as e:
                        done_by_index[i] = ('failed', name, f"Source database not found: {e}")
                        status = 'skipped'
                    except Exception as e:
                        done_by_index[i] = ('failed', name, str(e))
                        status = 'failed'
                    if progress_callback:
                        progress_callback(finished, total_mappings, name, status)
                if not cancelled and should_cancel is not None and should_cancel():
                    cancelled = True
                    for future in pending:
                        future.cancel()
                    logger.info("Feather generation cancelled: the feathers not started are left as they were")
                if idle_callback is not None:
                    idle_callback()

        # The registry once, from this thread (ConfigurationManager is a
        # QObject; it rewrote its JSON file once per feather).
        if registrations and register:
            self.config_manager.add_feathers(registrations)

        generated_feathers = [v[2] for k, v in sorted(done_by_index.items()) if v[0] == 'ok']
        failed_feathers = [(v[1], v[2]) for k, v in sorted(done_by_index.items()) if v[0] == 'failed']
        success_count = len(generated_feathers)
        failure_count = len(failed_feathers)
        logger.info(f"Feather generation complete: {success_count}/{total_mappings} successful, "
                    f"{failure_count} failed/skipped" + (", cancelled" if cancelled else ""))
        for name, error in failed_feathers:
            logger.info(f" - {name}: {error}")
        self._record_custody(generated_feathers, failed_feathers, cancelled)
        return {
            'successful': generated_feathers,
            'failed': failed_feathers,
            'total': total_mappings,
            'success_count': success_count,
            'failure_count': failure_count,
            'cancelled': cancelled,
            'registrations': registrations,
            'seconds': seconds,
        }

    def _get_feather_mappings(self) -> List[Dict]:
        """
        Get all feather generation mappings.

        Returns:
            List of mapping dictionaries
        """
        return get_feather_mappings()

    # Build settings for a feather's own connection: nothing else reads the
    # file until it is renamed into place, so no journal and no syncs; the
    # finished file is left in the ordinary DELETE journal mode.
    _BUILD_PRAGMAS = ("PRAGMA journal_mode=OFF", "PRAGMA synchronous=OFF",
                      "PRAGMA temp_store=MEMORY", "PRAGMA cache_size=-32768")

    def _record_custody(self, generated, failed, cancelled):
        """The feathers built into the case, in its custody ledger: each one's
        rows, SHA-256 and the fingerprint of the source it was copied from. A
        correlation result is only as provable as the feathers it read."""
        try:
            from utils import custody
            built = []
            for path in generated or []:
                entry = {"feather": Path(path).name}
                try:
                    entry["sha256"] = custody.sha256_file(str(path))[0]
                    conn = sqlite3.connect(_sqlite_uri(path, 'ro') + '&immutable=1', uri=True)
                    try:
                        meta = dict(conn.execute(
                            "SELECT key, value FROM feather_metadata WHERE key IN "
                            "('source_database', 'source_fingerprint', 'row_count')").fetchall())
                    finally:
                        conn.close()
                    entry.update(meta)
                except Exception:
                    pass
                built.append(entry)
            custody.ledger(str(self.case_directory), "feathers built",
                           built=built, failed=[{"feather": n, "error": str(e)[:300]} for n, e in failed or []],
                           cancelled=bool(cancelled), output=str(self.feather_output_dir))
        except Exception as e:
            logger.debug("[Feather] custody entry not written: %s", e)

    def _ensure_uba_store(self):
        """Build or refresh the case's stored UBA analysis (reused while fresh).
        Once per generator: the pool may reach here from one thread only, but
        the lock keeps a second caller from building it twice. A failure is
        logged and leaves the behaviour feather empty, never the run failed."""
        with self._uba_lock:
            if self._uba_checked:
                return
            self._uba_checked = True
            if not self.target_artifacts_dir.exists():
                return
            try:
                from uba.engine.behavior_engine import BehaviorEngine
                BehaviorEngine(str(self.target_artifacts_dir)).run_or_load(
                    progress_cb=getattr(self, "_uba_progress", None))
            except Exception as e:
                logger.warning("[Feather] User behaviour analysis not built - the "
                               "Behaviour feather will be empty: %s", e)

    def _generate_feather(self, mapping: Dict):
        """
        Generate a single Feather from mapping configuration. Runs on a pool
        thread: it touches only its own two SQLite files and returns
        (feather path, registry entry) for the caller to register.

        The rows are copied inside SQLite (ATTACH + INSERT ... SELECT), not
        read into Python and written back, and the feather is built as
        <name>.db.tmp and renamed over the old one only when complete: the old
        build deleted the feather first, so a failed or locked build lost it.

        Raises:
            FileNotFoundError: If source database not found in either location
            Exception: If Feather generation fails
        """
        import os
        source_db_path = None
        source_location = None

        target_artifacts_path = self.target_artifacts_dir / mapping['source_db']
        if mapping.get('source_dir'):
            # A source outside Target_Artifacts - UBA's stored analysis. It is
            # built or refreshed first, as the Behaviour engine and the User
            # Behavior window do (reused while fresh).
            if mapping['source_dir'] == 'UBA':
                self._ensure_uba_store()
            target_artifacts_path = self.case_directory / mapping['source_dir'] / mapping['source_db']
        if target_artifacts_path.exists():
            source_db_path = target_artifacts_path
            source_location = ("%s (stored analysis)" % mapping['source_dir']
                               if mapping.get('source_dir') else "Target_Artifacts (live parser)")
        if not source_db_path and not mapping.get('source_dir'):
            live_acquisition_path = self.live_acquisition_dir / mapping['source_db']
            if live_acquisition_path.exists():
                source_db_path = live_acquisition_path
                source_location = "live_acquisition (offline parser)"

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
        table = mapping['source_table']

        # The source's columns, read-only (an absent database reads as empty).
        if db_missing:
            columns = []
        else:
            source_conn = sqlite3.connect(_sqlite_uri(source_db_path, 'ro'), uri=True)
            try:
                columns = source_conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            finally:
                source_conn.close()

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
                    f"Table {table} not found in "
                    f"{Path(source_db_path).name} and the mapping declares no "
                    f"fallback_columns - cannot build an empty feather")
            # Shaped like PRAGMA table_info rows: (cid, name, type, ...)
            columns = [(i, name, col_type, 0, None, 0)
                       for i, (name, col_type) in enumerate(fallback)]
            logger.info(
                "Table %s absent from %s - generating an empty feather from "
                "the %d declared column(s) so wings still resolve",
                table, Path(source_db_path).name, len(fallback))

        # Drop parser bookkeeping columns by name, whatever position they
        # sit in. See BOOKKEEPING_COLUMNS for why this is not positional.
        dropped = [c[1] for c in columns if is_bookkeeping_column(c[1], mapping)]
        if dropped:
            columns = [c for c in columns if not is_bookkeeping_column(c[1], mapping)]
        if not columns:
            raise Exception(
                f"Table {table} has nothing but bookkeeping "
                f"columns ({', '.join(dropped)}) - refusing to build an "
                f"evidence-free feather")

        # Sanitize column names and filter out None/empty (Fixes "no such column: None")
        columns = [c for c in columns if c[1] and isinstance(c[1], str)]
        # Columns computed from the source row (the behaviour feather's
        # executable_name / file_path, read out of details_json). A fallback
        # shape already lists them.
        derived = [d for d in (mapping.get('derived_columns') or [])
                   if d[0] not in {c[1] for c in columns}]
        columns = columns + [(len(columns) + i, name, col_type, 0, None, 0)
                             for i, (name, col_type, _expr) in enumerate(derived)]
        derived_sql = {name: expr for name, _t, expr in (mapping.get('derived_columns') or [])}
        column_names = [col[1] for col in columns]
        column_mapping = mapping.get('column_mapping', {})
        target_column_names = [column_mapping.get(n, n) for n in column_names]

        feather_path = self.feather_output_dir / f"{mapping['name']}.db"
        tmp_path = self.feather_output_dir / f"{mapping['name']}.db.tmp"
        for leftover in (tmp_path, Path(str(tmp_path) + '-journal')):
            if leftover.exists():
                leftover.unlink()

        # URIs on, so the source can be attached read-only below.
        feather_conn = sqlite3.connect(_sqlite_uri(tmp_path), uri=True)
        try:
            for pragma in self._BUILD_PRAGMAS:
                feather_conn.execute(pragma)
            col_defs = ', '.join(f'"{column_mapping.get(c[1], c[1])}" {c[2]}' for c in columns)
            feather_conn.execute(f'CREATE TABLE "{table}" ({col_defs})')

            row_count = 0
            if not table_missing:
                # The copy happens in SQLite: the source is attached read-only
                # and its rows never become Python objects.
                feather_conn.execute("ATTACH DATABASE ? AS src",
                                     (_sqlite_uri(source_db_path, 'ro'),))
                try:
                    select_cols = ', '.join(derived_sql[n] if n in derived_sql else f'"{n}"'
                                            for n in column_names)
                    insert_cols = ', '.join(f'"{n}"' for n in target_column_names)
                    query = f'INSERT INTO main."{table}" ({insert_cols}) SELECT {select_cols} FROM src."{table}"'
                    if mapping.get('filter'):
                        query += f" WHERE {mapping['filter']}"
                    feather_conn.execute(query)
                    feather_conn.commit()
                finally:
                    feather_conn.execute("DETACH DATABASE src")
                row_count = feather_conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

            feather_id = mapping['name'].replace('_CrowEyeFeather', '').lower()
            timestamp = _utc_now_text()
            # Key/value metadata, matching the FeatherBuilder schema.
            feather_conn.execute('CREATE TABLE feather_metadata (key TEXT PRIMARY KEY, value TEXT)')
            feather_conn.executemany('INSERT OR REPLACE INTO feather_metadata (key, value) VALUES (?, ?)', [
                ('feather_id', feather_id),
                ('feather_name', mapping['name']),
                ('artifact_type', mapping['artifact_type']),
                ('created_date', timestamp),
                ('last_modified', timestamp),
                ('version', '1.0'),
                ('source_database', str(source_db_path)),
                ('source_table', table),
                ('auto_generated', 'true'),
                ('filter', mapping.get('filter', '')),
                ('row_count', str(row_count)),
                # What was actually dropped, by name. The old key recorded
                # a boolean flag that said nothing about which column went,
                # which is why four feathers could lose `user_name` without
                # leaving a trace anywhere. Kept under the same key so
                # anything reading existing feather metadata still finds it.
                ('exclude_last_column', ', '.join(dropped) if dropped else 'none'),
                ('source_table_present', 'false' if table_missing else 'true'),
                # What the source looked like when this feather was built
                # (stale_feathers compares it at the next case load).
                ('source_fingerprint', source_fingerprint(source_db_path)
                 if not db_missing else 'missing'),
            ])

            self._create_indexes(feather_conn.cursor(), table, target_column_names,
                                 column_mapping)
            feather_conn.commit()
            feather_conn.execute("PRAGMA journal_mode=DELETE")
        except Exception:
            feather_conn.close()
            if tmp_path.exists():
                tmp_path.unlink()
            raise
        feather_conn.close()

        try:
            os.replace(tmp_path, feather_path)
        except PermissionError:
            if tmp_path.exists():
                tmp_path.unlink()
            raise Exception(
                f"{feather_path.name} is open in another program (a correlation run, "
                f"or a viewer): the old feather is kept; close it and generate again")

        feather_config = self._create_feather_config(
            mapping=mapping,
            feather_path=feather_path,
            column_names=target_column_names,
            row_count=row_count,
            source_db_path=source_db_path
        )
        config_json_path = self.feather_output_dir / f"{mapping['name']}.json"
        feather_config.save_to_file(str(config_json_path))

        registration = {
            'feather_id': feather_id,
            'db_path': str(feather_path),
            'artifact_type': mapping['artifact_type'],
            'metadata': {
                'source_database': str(source_db_path),
                'source_table': table,
                'auto_generated': True,
                'filter': mapping.get('filter', None),
                'row_count': row_count,
            },
        }
        return str(feather_path), registration

    @staticmethod
    def _declared_columns(source_table: str, column_names: List[str],
                          renamed: Optional[Dict[str, str]] = None):
        """(timestamp, application, path) columns for a feather: the registry's
        declared ones that exist in the built table, else a guess by name for
        a table the registry does not declare. A timeless table has no
        timestamp column (""). The registry names source columns; `renamed`
        is the mapping's column_mapping (LNK's Local_Path is built as
        target_path), so a declared column is looked up under its new name."""
        from correlation_engine.config import feather_schemas
        present = set(column_names)
        renamed = renamed or {}
        schema = feather_schemas.get_schema(source_table)
        if schema is not None:
            source_names = {k for k, v in renamed.items() if v in present} | present
            primary = feather_schemas.primary_timestamp_column(source_table, source_names)
            ts = renamed.get(primary, primary) if primary else ''
            ts = ts if ts in present else ''
            ids = [renamed.get(c, c) for c in (schema.get('identity_columns_preferred') or [])]
            ids = [c for c in ids if c in present]
            app = next((c for c in ids if 'path' not in c.lower()), ids[0] if ids else None)
            path = next((c for c in ids if 'path' in c.lower()), None)
            return ts, app, path
        logger.warning("[Feather] %s is not declared in config/feather_schemas.json: "
                       "its columns are guessed by name", source_table)
        ts = next((c for c in column_names
                   if any(k in c.lower() for k in ('timestamp', 'time', 'date'))), '')
        app = next((c for c in column_names
                    if any(k in c.lower() for k in ('app', 'program', 'executable', 'name'))), None)
        path = next((c for c in column_names if 'path' in c.lower()), None)
        return ts, app, path

    @staticmethod
    def _sample_timestamp_format(feather_path: Path, table: str, column: str) -> str:
        """The stored format of `column`, read from a non-empty sample
        (engine/timestamp_format_codec), or "" when it has none."""
        if not column:
            return ''
        try:
            from correlation_engine.engine.timestamp_format_codec import detect_column_format
            conn = sqlite3.connect(str(feather_path))
            try:
                rows = conn.execute(
                    "SELECT \"%s\" FROM \"%s\" WHERE \"%s\" IS NOT NULL AND \"%s\" != '' LIMIT 200"
                    % (column, table, column, column)).fetchall()
            finally:
                conn.close()
            # The most common format of up to 200 values: one stray value
            # (InventoryApplicationFile.link_date holds a "0.5") must not
            # decide the column's format.
            from collections import Counter
            seen = Counter(detect_column_format(r[0]) for r in rows)
            seen.pop(None, None)
            return seen.most_common(1)[0][0] if seen else ''
        except Exception:
            return ''

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

        # The columns come from config/feather_schemas.json, the registry the
        # Time engine already reads, and only a table it does not declare
        # falls back to guessing by name. Guessing chose the first column
        # whose name held "time"/"app"/"path": BAM's timestamp was `subkey`,
        # ShimCache's `id`, Prefetch's the JSON `run_times`, every Event Log's
        # application `ComputerName` (so every event shared the host name as
        # its identity), and timeless tables got a text column as their time.
        timestamp_col, app_col, path_col = self._declared_columns(
            mapping['source_table'], column_names, mapping.get('column_mapping'))
        timestamp_format = self._sample_timestamp_format(
            feather_path, mapping['source_table'], timestamp_col)

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
            timestamp_format=timestamp_format,
            output_database=str(feather_path),
            # Crow-Eye's source DB stores all timestamps in UTC. Override per
            # feather if a downstream tool ingests local-time exports.
            source_timezone='UTC',
            application_column=app_col,
            path_column=path_col,
            created_date=_utc_now_text(),
            created_by='Auto-Generated',
            description=f'Auto-generated feather from {mapping["source_db"]} - {mapping["source_table"]}',
            notes=f'Filter: {mapping.get("filter", "None")}',
            total_records=row_count
        )
    
    def _create_indexes(self, cursor: sqlite3.Cursor, table_name: str,
                        column_names: List[str], renamed: Optional[Dict[str, str]] = None) -> None:
        """One index per column the engines search by, and no others.

        Timestamp columns get the `idx_timewindow_<col>` names the Time engine
        looks for (OptimizedFeatherQuery.has_timestamp_index): the generator
        used to name them `idx_<col>` and the engine then built its own copy of
        each, so MFT_USN carried 24 indexes, 9 of them duplicates, rebuilt on
        every regenerate. The declared application and path columns get one
        each. Columns that only looked searchable by name (run_times JSON,
        FileSize, focus_time, File_Permission) are no longer indexed.
        """
        from correlation_engine.config import feather_schemas
        renamed = renamed or {}
        present = set(column_names)
        declared = feather_schemas.get_schema(table_name) is not None
        if declared:
            source_names = {k for k, v in renamed.items() if v in present} | present
            stamps = [renamed.get(c, c) for c in
                      feather_schemas.all_timestamp_columns(table_name, source_names)]
        else:
            stamps = [c for c in column_names
                      if any(k in c.lower() for k in ('timestamp', 'time', 'date'))]
        _ts, app, path = self._declared_columns(table_name, column_names, renamed)
        wanted = [('idx_timewindow_', c) for c in stamps if c in present]
        wanted += [('idx_identity_', c) for c in (app, path) if c and c in present and c not in stamps]
        seen = set()
        for prefix, col in wanted:
            if col in seen:
                continue
            seen.add(col)
            try:
                cursor.execute('CREATE INDEX IF NOT EXISTS "%s%s" ON "%s"("%s")'
                               % (prefix, col.replace(' ', '_'), table_name, col))
            except Exception as e:
                logger.debug(f"Could not create index on {col}: {e}")
