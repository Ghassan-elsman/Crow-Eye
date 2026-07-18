"""
Cross-Wing Identity Run Reconciler
==================================

Wings execute one after another — in a live GUI run each wing even gets its
own execution row in ``correlation_results.db``. This module gives the
Identity engine run-level memory: as each wing finishes, its identities are
merged into a persistent per-run registry so that

* an identity a later wing finds that ALREADY EXISTS (discovered by an
  earlier wing of the same run) is merged into the existing main identity —
  never duplicated — and the new wing is attributed alongside the earlier
  one(s);
* a later wing that finds only a VARIANT of an existing main identity gets a
  new sub-identity created under that existing main identity;
* a wing that did not find an identity contributes no attribution for it;
* identities and sub-identities discovered by multiple wings carry ALL of
  their discovering wings.

Registry tables (created by ``ResultsDatabase._create_schema`` and
defensively here): ``run_identities`` (one row per main identity per
run group), ``run_sub_identities`` (variants), ``identity_wing_links``
(which wing found which identity/sub, with match counts).

Grouping uses the SAME canonical functions as the results GUI
(``identity_grouping.display_grouping_key`` / ``extract_original_name`` /
``sub_identity_key``), so the persisted registry and the unified results
view agree by construction.

``reconcile_wing`` is idempotent: re-running it for the same execution
overwrites that execution's own wing-link counts and never double-counts —
safe for resumed or repeated runs.
"""

from __future__ import annotations

import gzip
import json
import logging
import sqlite3
from typing import Any, Dict, Optional, Tuple

from .identity_grouping import (
    display_grouping_key,
    extract_original_name,
    sub_identity_key,
)

logger = logging.getLogger(__name__)


_REGISTRY_DDL = [
    """
    CREATE TABLE IF NOT EXISTS run_identities (
        identity_pk INTEGER PRIMARY KEY AUTOINCREMENT,
        run_group_id TEXT NOT NULL,
        identity_key TEXT NOT NULL,
        display_name TEXT,
        identity_type TEXT DEFAULT 'name',
        first_wing_name TEXT,
        first_execution_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(run_group_id, identity_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS run_sub_identities (
        sub_pk INTEGER PRIMARY KEY AUTOINCREMENT,
        identity_pk INTEGER NOT NULL,
        sub_key TEXT NOT NULL,
        display_name TEXT,
        first_wing_name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(identity_pk, sub_key),
        FOREIGN KEY (identity_pk) REFERENCES run_identities(identity_pk)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS identity_wing_links (
        link_id INTEGER PRIMARY KEY AUTOINCREMENT,
        identity_pk INTEGER NOT NULL,
        sub_pk INTEGER,
        wing_id TEXT,
        wing_name TEXT NOT NULL,
        execution_id INTEGER,
        match_count INTEGER DEFAULT 0,
        FOREIGN KEY (identity_pk) REFERENCES run_identities(identity_pk),
        FOREIGN KEY (sub_pk) REFERENCES run_sub_identities(sub_pk)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_run_identities_group ON run_identities(run_group_id)",
    "CREATE INDEX IF NOT EXISTS idx_iwl_identity ON identity_wing_links(identity_pk)",
]


def _decode_feather_records(raw: Any, compressed: Any) -> Dict[str, Any]:
    """Decode a matches.feather_records value, handling gzip compression.

    Rows > 1MB are stored gzip'd with compressed=1 (as str via latin1 or as
    bytes). Any failure returns {} — reconciliation must never abort on a
    single unreadable row.
    """
    if not raw:
        return {}
    try:
        if compressed:
            data = raw
            if isinstance(data, str):
                data = data.encode('latin1')
            decoded = json.loads(gzip.decompress(data).decode('utf-8'))
        else:
            decoded = json.loads(raw)
        return decoded if isinstance(decoded, dict) else {}
    except Exception as e:
        logger.warning(f"[Reconciler] Could not decode feather_records: {e}")
        return {}


def _upsert_link(cursor: sqlite3.Cursor, identity_pk: int, sub_pk: Optional[int],
                 wing_id: Optional[str], wing_name: str, execution_id: int,
                 match_count: int) -> bool:
    """Insert or update one wing-attribution link.

    Python-side dedupe (``sub_pk IS ?``) because SQLite UNIQUE constraints
    treat NULLs as distinct. Overwrites match_count so re-reconciling the
    same execution is idempotent. Returns True when a new link was inserted.
    """
    cursor.execute(
        """
        SELECT link_id FROM identity_wing_links
        WHERE identity_pk = ? AND sub_pk IS ? AND wing_name = ? AND execution_id = ?
        """,
        (identity_pk, sub_pk, wing_name, execution_id)
    )
    row = cursor.fetchone()
    if row:
        cursor.execute(
            "UPDATE identity_wing_links SET match_count = ?, wing_id = ? WHERE link_id = ?",
            (match_count, wing_id, row[0])
        )
        return False
    cursor.execute(
        """
        INSERT INTO identity_wing_links
            (identity_pk, sub_pk, wing_id, wing_name, execution_id, match_count)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (identity_pk, sub_pk, wing_id, wing_name, execution_id, match_count)
    )
    return True


def reconcile_wing(db_path: str, run_group_id: Optional[str],
                   execution_id: int) -> Dict[str, int]:
    """Merge one finished wing's identities into the per-run registry.

    Args:
        db_path: Path to correlation_results.db
        run_group_id: Groups the per-wing executions of one run. Falls back
            to ``exec:<execution_id>`` when None (legacy/standalone), so the
            execution still gets a self-contained registry.
        execution_id: The execution whose matches to reconcile. In live runs
            this holds exactly one wing; in non-streaming CLI runs it can
            hold several results rows — the results JOIN handles both.

    Returns:
        Stats dict: identities_new, identities_merged, subs_new,
        links_written, matches_processed.
    """
    stats = {
        'identities_new': 0,
        'identities_merged': 0,
        'subs_new': 0,
        'links_written': 0,
        'matches_processed': 0,
    }

    if not run_group_id:
        run_group_id = f"exec:{execution_id}"

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        cursor = conn.cursor()

        # Defensive: direct connections to legacy DBs may predate the tables
        for ddl in _REGISTRY_DDL:
            cursor.execute(ddl)

        # Legacy matches tables may lack the compressed column
        cursor.execute("PRAGMA table_info(matches)")
        match_columns = {row[1] for row in cursor.fetchall()}
        compressed_col = "m.compressed" if 'compressed' in match_columns else "0 AS compressed"

        cursor.execute(f"""
            SELECT m.matched_application, m.matched_file_path, m.feather_records,
                   {compressed_col}, r.wing_id, r.wing_name, r.total_matches
            FROM matches m
            JOIN results r ON m.result_id = r.result_id
            WHERE r.execution_id = ?
        """, (execution_id,))
        rows = cursor.fetchall()

        # Aggregate per wing → main identity → sub identity.
        # main_agg[(wing_id, wing_name)][main_key] =
        #   {'display': str, 'count': int,
        #    'subs': {sub_key: {'display': str, 'count': int}}}
        main_agg: Dict[Tuple[Optional[str], str], Dict[str, Dict[str, Any]]] = {}
        expected_counts: Dict[Tuple[Optional[str], str], int] = {}

        for (matched_application, matched_file_path, feather_records_raw,
             compressed, wing_id, wing_name, wing_total_matches) in rows:
            stats['matches_processed'] += 1
            wing_key = (wing_id, wing_name or "Unknown Wing")
            expected_counts[wing_key] = wing_total_matches or 0

            raw_app = matched_application or matched_file_path or "Unknown"
            main_key = display_grouping_key(raw_app)

            feather_records = _decode_feather_records(feather_records_raw, compressed)
            original_name = extract_original_name(raw_app, feather_records)
            sub_key = sub_identity_key(original_name) or original_name.strip().lower()

            wing_bucket = main_agg.setdefault(wing_key, {})
            identity = wing_bucket.setdefault(main_key, {
                'display': raw_app,
                'count': 0,
                'subs': {}
            })
            identity['count'] += 1
            sub = identity['subs'].setdefault(sub_key, {
                'display': original_name,
                'count': 0
            })
            sub['count'] += 1

        # Streaming-timing sanity check: matches should be fully committed
        # by the time the pipeline calls us
        for (wing_id, wing_name), expected in expected_counts.items():
            actual = sum(i['count'] for i in main_agg.get((wing_id, wing_name), {}).values())
            if expected and actual < expected:
                logger.warning(
                    f"[Reconciler] Wing '{wing_name}' (execution {execution_id}): "
                    f"reconciled {actual} matches but results row expects {expected} — "
                    f"matches may not be fully flushed yet"
                )

        # Upserts in one transaction
        for (wing_id, wing_name), identities in main_agg.items():
            for main_key, identity in identities.items():
                # Main identity: merge into the run's existing row if an
                # earlier wing already discovered it, else create it
                cursor.execute(
                    """
                    INSERT INTO run_identities
                        (run_group_id, identity_key, display_name, identity_type,
                         first_wing_name, first_execution_id)
                    VALUES (?, ?, ?, 'name', ?, ?)
                    ON CONFLICT(run_group_id, identity_key) DO NOTHING
                    """,
                    (run_group_id, main_key, identity['display'], wing_name, execution_id)
                )
                inserted_main = cursor.rowcount > 0
                cursor.execute(
                    "SELECT identity_pk FROM run_identities WHERE run_group_id = ? AND identity_key = ?",
                    (run_group_id, main_key)
                )
                identity_pk = cursor.fetchone()[0]
                if inserted_main:
                    stats['identities_new'] += 1
                else:
                    stats['identities_merged'] += 1

                # Main-level wing attribution
                if _upsert_link(cursor, identity_pk, None, wing_id, wing_name,
                                execution_id, identity['count']):
                    stats['links_written'] += 1

                # Sub-identities: a variant found by a later wing becomes a
                # new sub under the EXISTING main identity
                for sub_key, sub in identity['subs'].items():
                    cursor.execute(
                        """
                        INSERT INTO run_sub_identities
                            (identity_pk, sub_key, display_name, first_wing_name)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(identity_pk, sub_key) DO NOTHING
                        """,
                        (identity_pk, sub_key, sub['display'], wing_name)
                    )
                    if cursor.rowcount > 0:
                        stats['subs_new'] += 1
                    cursor.execute(
                        "SELECT sub_pk FROM run_sub_identities WHERE identity_pk = ? AND sub_key = ?",
                        (identity_pk, sub_key)
                    )
                    sub_pk = cursor.fetchone()[0]

                    if _upsert_link(cursor, identity_pk, sub_pk, wing_id, wing_name,
                                    execution_id, sub['count']):
                        stats['links_written'] += 1

        conn.commit()
        logger.info(
            f"[Reconciler] Execution {execution_id} (run group {run_group_id}): "
            f"{stats['identities_new']} new / {stats['identities_merged']} merged identities, "
            f"{stats['subs_new']} new sub-identities, {stats['links_written']} new wing links"
        )
        return stats
    finally:
        conn.close()


def get_run_registry(db_path: str, run_group_id: str) -> Dict[str, Any]:
    """Read the reconciled registry for one run group.

    Returns {'identities': [{identity_key, display_name, wings: [...],
    sub_identities: [{sub_key, display_name, wings: [...]}]}]} — handy for
    reports, Eye AI queries, and tests.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT identity_pk, identity_key, display_name, first_wing_name
            FROM run_identities WHERE run_group_id = ?
            ORDER BY identity_key
            """,
            (run_group_id,)
        )
        identities = []
        for identity_pk, identity_key, display_name, first_wing_name in cursor.fetchall():
            cursor.execute(
                """
                SELECT DISTINCT wing_name FROM identity_wing_links
                WHERE identity_pk = ? AND sub_pk IS NULL
                ORDER BY wing_name
                """,
                (identity_pk,)
            )
            wings = [r[0] for r in cursor.fetchall()]

            cursor.execute(
                "SELECT sub_pk, sub_key, display_name FROM run_sub_identities WHERE identity_pk = ? ORDER BY sub_key",
                (identity_pk,)
            )
            subs = []
            for sub_pk, sub_key, sub_display in cursor.fetchall():
                cursor.execute(
                    """
                    SELECT DISTINCT wing_name FROM identity_wing_links
                    WHERE identity_pk = ? AND sub_pk = ?
                    ORDER BY wing_name
                    """,
                    (identity_pk, sub_pk)
                )
                subs.append({
                    'sub_key': sub_key,
                    'display_name': sub_display,
                    'wings': [r[0] for r in cursor.fetchall()],
                })

            identities.append({
                'identity_key': identity_key,
                'display_name': display_name,
                'first_wing_name': first_wing_name,
                'wings': wings,
                'sub_identities': subs,
            })

        return {'run_group_id': run_group_id, 'identities': identities}
    finally:
        conn.close()


__all__ = ["reconcile_wing", "get_run_registry"]
