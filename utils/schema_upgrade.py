"""Bring an existing case database's tables up to the columns a parser now writes.

A parser creates its tables with ``CREATE TABLE IF NOT EXISTS``. On a case parsed
by an older Crow-Eye that statement does nothing, the table keeps its old columns,
and every insert that names a newer one (``parsed_at``, ``user_name``,
``row_data``) fails - a re-parse of a case from before 2026-07-31 logged about
2,700 registry errors and stored none of those rows.

``UpgradingCursor`` wraps a sqlite3 cursor. Each ``CREATE TABLE IF NOT EXISTS``
it runs is also run against an in-memory database to learn the columns the
parser declares today, and any the existing table lacks are added with
``ALTER TABLE ... ADD COLUMN``. Nothing is rebuilt or dropped: a case that has
been parsed is evidence, and its rows and old columns stay exactly as they were.
"""
import logging
import re
import sqlite3

logger = logging.getLogger(__name__)

_CREATE_IF_NOT_EXISTS = re.compile(
    r'^\s*create\s+table\s+if\s+not\s+exists\s+["\[`]?([A-Za-z_][A-Za-z0-9_]*)["\]`]?\s*\(',
    re.IGNORECASE)


def declared_columns(create_sql):
    """{column: declared type} for a CREATE TABLE statement, or {} if it cannot be read."""
    match = _CREATE_IF_NOT_EXISTS.match(create_sql or "")
    if not match:
        return {}
    mem = sqlite3.connect(":memory:")
    try:
        mem.execute(create_sql)
        return {row[1]: (row[2] or "TEXT")
                for row in mem.execute('PRAGMA table_info("%s")' % match.group(1))}
    except sqlite3.Error:
        return {}
    finally:
        mem.close()


def add_missing_columns(cursor, table, columns):
    """ALTER TABLE ADD COLUMN for each column the existing table lacks. Returns the names added."""
    try:
        have = {row[1].lower() for row in cursor.execute('PRAGMA table_info("%s")' % table)}
    except sqlite3.Error:
        return []
    if not have:
        return []
    added = []
    for name, sql_type in columns.items():
        if name.lower() in have:
            continue
        try:
            cursor.execute('ALTER TABLE "%s" ADD COLUMN "%s" %s' % (table, name, sql_type))
            added.append(name)
        except sqlite3.Error as exc:
            logger.debug("could not add %s.%s: %s", table, name, exc)
    if added:
        logger.info("Brought %s up to date for this case: added %s", table, ", ".join(added))
    return added


class UpgradingCursor:
    """A sqlite3 cursor whose CREATE TABLE IF NOT EXISTS also adds missing columns."""

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql, *args):
        result = self._cursor.execute(sql, *args)
        if isinstance(sql, str) and _CREATE_IF_NOT_EXISTS.match(sql):
            columns = declared_columns(sql)
            if columns:
                table = _CREATE_IF_NOT_EXISTS.match(sql).group(1)
                add_missing_columns(self._cursor, table, columns)
        return result

    def __iter__(self):
        return iter(self._cursor)

    def __getattr__(self, name):
        return getattr(self._cursor, name)
