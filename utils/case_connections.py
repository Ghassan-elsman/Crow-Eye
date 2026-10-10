"""Close the SQLite connections that belong to the case being left.

Opening or creating a case used to close EVERY ``sqlite3.Connection`` in the
process (a ``gc.get_objects()`` sweep). That included the Correlation Engine's
own: the semantic-mapping index is an in-memory connection opened with
``check_same_thread=False``, so it could be closed from the GUI thread, and
every correlation run after a case open logged "[FTS5] Error during field
matching: Cannot operate on a closed database" for each field it tried to map.

Only a connection whose main database file lives inside the old case's
``Target_Artifacts`` is closed now. In-memory and path-less connections, and
anything else, are left alone. A connection made in another thread cannot be
closed from this one at all (sqlite3 raises ProgrammingError), so those were
never closed by the sweep either; they are skipped the same way.
"""

import gc
import os
import sqlite3


def _main_file(conn):
    """The main database file of ``conn``, '' for an in-memory one, or None
    when it cannot be asked (closed, or owned by another thread)."""
    try:
        rows = conn.execute("PRAGMA database_list").fetchall()
    except Exception:
        return None
    for row in rows:
        if len(row) >= 3 and row[1] == "main":
            return row[2] or ""
    return ""


def _inside(path, folder):
    try:
        path = os.path.normcase(os.path.abspath(path))
        folder = os.path.normcase(os.path.abspath(folder)).rstrip("\\/")
    except Exception:
        return False
    return path.startswith(folder + os.sep)


def close_case_connections(artifacts_dir, objects=None):
    """Close the connections on database files under ``artifacts_dir``.

    Returns how many were closed. ``objects`` replaces the gc sweep (tests)."""
    if not artifacts_dir:
        return 0
    closed = 0
    for obj in (objects if objects is not None else gc.get_objects()):
        if not isinstance(obj, sqlite3.Connection):
            continue
        main = _main_file(obj)
        if not main or not _inside(main, artifacts_dir):
            continue
        try:
            obj.close()
            closed += 1
        except Exception:
            pass
    return closed
