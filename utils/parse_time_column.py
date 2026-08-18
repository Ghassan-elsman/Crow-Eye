"""
Parse-time column registry — single source of truth for the parser-bookkeeping
timestamp column.

Crow-Eye parsers record *when the parser ran* alongside each artifact row. That
column historically shipped under four different names:

    timestamp           registry tables (Regclaw / offline_RegClaw)
    parse_timestamp     SRUM parsing metadata
    parsed_timestamp    ShimCache entries
    inserted_at         USN journal tables

``timestamp`` in particular is actively misleading in a forensics tool: an
analyst reading ``UserAssist.timestamp`` reasonably takes it for activity time
when it is ingest time. Worse, ``config/standard_fields/timestamps.json`` ranks
``timestamp`` as a *real-activity* synonym, so the correlation engine and
Timeline could anchor on parser bookkeeping.

The canonical name is now ``parsed_at`` — already classified as ``bookkeeping``
in the standard-fields registry and therefore sorted to the back by
``utils.standard_fields.StandardFields.all_timestamp_fields``.

Back-compat contract
--------------------
Case databases written by older Crow-Eye versions still carry the legacy names.
They must stay **viewable and byte-identical** — nothing here writes to a
database. Read paths call :func:`resolve_parse_time_column` to discover whichever
name a given database actually uses, and :func:`parse_time_label` to render it as
"Parsed At" regardless.

Usage
-----
::

    from utils.parse_time_column import (
        PARSE_TIME_COLUMN, resolve_parse_time_column, parse_time_label,
    )

    col = resolve_parse_time_column(conn, "SystemServices")   # 'parsed_at' or 'timestamp'
    header = parse_time_label(col, "SystemServices")          # 'Parsed At'
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

#: The canonical parser-bookkeeping column name written by every parser.
PARSE_TIME_COLUMN = "parsed_at"

#: How the column is rendered in every GUI table header.
PARSE_TIME_LABEL = "Parsed At"

#: Legacy names that *always* mean parse time, in any table. Unambiguous —
#: no artifact stores real activity time under any of these.
LEGACY_PARSE_TIME_COLUMNS = (
    "parsed_timestamp",
    "parse_timestamp",
    "inserted_at",
)

#: ``timestamp`` is ambiguous. In SRUM application-usage / network tables and in
#: the USN journal it is a REAL event time and must never be relabelled. It only
#: means parse time in these legacy registry tables, which is why resolution is
#: table-scoped rather than a blanket name match.
LEGACY_TIMESTAMP_TABLES = frozenset({
    "ComputerNameInfo",
    "TimeZoneInfo",
    "NetworkInterfacesInfo",
    "Auto",
    "WindowsUpdateInfo",
    "ShutdownInfo",
    "USBStorageDevices",
    "USBStorageVolumes",
    "BrowserHistory",
    "InstalledSoftware",
    "SystemServices",
    "AutoStartPrograms",
    "WordWheelQuery",
    "UserAssist",
    "RunMRU",
    "UserProfiles",
    # offline_RegClaw-only tables
    "SuspiciousIndicators",
    "AutoStartSuspicious",
})

#: Lowercase lookup for the table allow-list (SQLite table names are
#: case-insensitive, and the registry tables are inconsistently cased).
_LEGACY_TIMESTAMP_TABLES_LOWER = frozenset(t.lower() for t in LEGACY_TIMESTAMP_TABLES)

# Resolution order: canonical first, then the unambiguous legacy names. The
# table-scoped "timestamp" fallback is appended by the resolver when applicable.
_CANDIDATES = (PARSE_TIME_COLUMN,) + LEGACY_PARSE_TIME_COLUMNS


def _legacy_timestamp_applies(table: Optional[str]) -> bool:
    """True when a bare ``timestamp`` column in *table* means parse time."""
    if not table:
        return False
    return table.strip().strip('"').strip("[]").lower() in _LEGACY_TIMESTAMP_TABLES_LOWER


def candidate_columns(table: Optional[str] = None) -> tuple:
    """Parse-time column names to look for, most-canonical first.

    ``timestamp`` is only included when *table* is one of the legacy registry
    tables in :data:`LEGACY_TIMESTAMP_TABLES`.
    """
    if _legacy_timestamp_applies(table):
        return _CANDIDATES + ("timestamp",)
    return _CANDIDATES


def is_parse_time_column(column: Optional[str], table: Optional[str] = None) -> bool:
    """True when *column* holds parser bookkeeping rather than artifact activity.

    Pass *table* so the ambiguous ``timestamp`` name is only treated as parse
    time for the legacy registry tables.
    """
    if not column:
        return False
    return column.strip().lower() in {c.lower() for c in candidate_columns(table)}


# Words that must not be title-cased into "Id", "Sid", "Dll". Plain .title()
# is right for almost every column name a parser writes; these are the ones it
# gets wrong, and they are common enough in registry schemas to be worth a set.
HEADER_ACRONYMS = frozenset({
    "id", "sid", "dll", "guid", "uuid", "url", "uri", "pid", "mru", "usb",
    "utc", "clsid", "ip", "mac", "os", "wmi", "dns", "uac", "exe", "lnk",
    "ntfs", "cpu", "api", "sql", "http", "https", "rdp", "smb", "vpn",
})


def parse_time_label(column: str, table: Optional[str] = None) -> str:
    """Render *column* as a GUI header label.

    Parse-time columns collapse to :data:`PARSE_TIME_LABEL` whatever they are
    stored as, so an old case database displays "Parsed At" without being
    modified. Everything else falls back to a title-cased form, with known
    acronyms kept upper case - "Device ID", not "Device Id".
    """
    if is_parse_time_column(column, table):
        return PARSE_TIME_LABEL
    words = str(column).replace("_", " ").split()
    return " ".join(w.upper() if w.lower() in HEADER_ACRONYMS else w.title()
                    for w in words)


def resolve_parse_time_column(
    conn: sqlite3.Connection,
    table: str,
    columns: Optional[Sequence[str]] = None,
) -> Optional[str]:
    """Return the parse-time column *table* actually uses, or ``None``.

    Prefers ``parsed_at``, then the unambiguous legacy names, then a bare
    ``timestamp`` for legacy registry tables only. Read-only: never alters the
    database.

    Pass *columns* when the caller already has the column list (e.g. from a
    prior ``PRAGMA table_info``) to skip the extra query.
    """
    if columns is None:
        columns = get_table_columns(conn, table)
    if not columns:
        return None

    existing = {str(c).lower(): str(c) for c in columns}
    for candidate in candidate_columns(table):
        actual = existing.get(candidate.lower())
        if actual:
            return actual
    return None


def get_table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    """Column names for *table*, or ``[]`` if it does not exist.

    Mirrors ``data.base_loader.BaseDataLoader.get_columns`` so both read paths
    use the same PRAGMA idiom.
    """
    try:
        cursor = conn.cursor()
        cursor.execute(f'PRAGMA table_info("{table}")')
        return [row[1] for row in cursor.fetchall()]  # name is at index 1
    except sqlite3.Error as e:
        logger.debug("PRAGMA table_info failed for '%s': %s", table, e)
        return []


def nice_headers(columns: Iterable[str], table: Optional[str] = None) -> List[str]:
    """Title-case a column list for display, collapsing parse-time names.

    Same contract as ``get_nice_srum_headers`` in the GUI, but driven by this
    module so registry tabs rendered straight from ``PRAGMA table_info`` show
    "Parsed At" for both the new and the legacy column name.
    """
    return [parse_time_label(col, table) for col in columns]


__all__ = [
    "PARSE_TIME_COLUMN",
    "PARSE_TIME_LABEL",
    "LEGACY_PARSE_TIME_COLUMNS",
    "LEGACY_TIMESTAMP_TABLES",
    "candidate_columns",
    "is_parse_time_column",
    "parse_time_label",
    "resolve_parse_time_column",
    "get_table_columns",
    "nice_headers",
]
