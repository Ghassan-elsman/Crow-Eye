"""
Lazy evidence resolution: turns the EvidenceRefs stored on a BehaviorEvent
back into the actual source rows (read-only), paged so a 5000-row burst
never travels over the bridge at once.
"""

import logging
from typing import List, Optional

from uba.utils.db_access import table_columns, table_exists

logger = logging.getLogger(__name__)

PAGE_SIZE = 50


class EvidenceFetcher:
    def __init__(self, db_pool):
        self.db_pool = db_pool

    def fetch(self, evidence_refs: List[dict], offset: int = 0,
              page_size: int = PAGE_SIZE) -> dict:
        """Resolve stored refs into rows.

        Returns {"groups": [{db, table, role, rows: [{__rowid__, ...cols}],
        total, has_more}], "offset": ..., "page_size": ...}. The offset/page
        applies within each rowid_range group (rowid-keyed paging).
        """
        groups = []
        for ref in evidence_refs or []:
            db_name, table = ref.get("db"), ref.get("table")
            conn = self.db_pool.get(db_name)
            group = {"db": db_name, "table": table,
                     "role": ref.get("role", "primary"),
                     "rows": [], "total": ref.get("count", 0), "has_more": False}
            if conn is None or not table_exists(conn, table):
                group["error"] = "source database is not available"
                groups.append(group)
                continue
            try:
                rows = self._rows_for_ref(conn, table, ref, offset, page_size)
                group["rows"] = rows
                fetched_so_far = offset + len(rows)
                group["has_more"] = fetched_so_far < (group["total"] or 0)
            except Exception as e:
                logger.warning("UBA: evidence fetch failed %s/%s: %s",
                               db_name, table, e)
                group["error"] = str(e)
            groups.append(group)
        return {"groups": groups, "offset": offset, "page_size": page_size}

    def _rows_for_ref(self, conn, table, ref, offset, page_size) -> List[dict]:
        cols = table_columns(conn, table)
        col_sql = ", ".join('"{}"'.format(c) for c in cols)
        rowid_range = ref.get("rowid_range")
        rowids = ref.get("rowids") or []

        if rowid_range and len(rowid_range) == 2:
            sql = ('SELECT rowid, {} FROM "{}" WHERE rowid BETWEEN ? AND ? '
                   "ORDER BY rowid LIMIT ? OFFSET ?").format(col_sql, table)
            cursor = conn.execute(sql, [rowid_range[0], rowid_range[1],
                                        page_size, offset])
        elif rowids:
            page = rowids[offset:offset + page_size]
            if not page:
                return []
            marks = ",".join("?" for _ in page)
            sql = ('SELECT rowid, {} FROM "{}" WHERE rowid IN ({}) '
                   "ORDER BY rowid").format(col_sql, table, marks)
            cursor = conn.execute(sql, page)
        else:
            # corroborating state reference without specific rows (e.g. the
            # SystemServices table as a whole): show a small sample
            sql = 'SELECT rowid, {} FROM "{}" ORDER BY rowid LIMIT ? OFFSET ?'.format(
                col_sql, table)
            cursor = conn.execute(sql, [page_size, offset])

        out = []
        for row in cursor.fetchall():
            item = {"__rowid__": row[0]}
            for idx, col in enumerate(cols, start=1):
                value = row[idx]
                if isinstance(value, bytes):
                    value = "0x" + value.hex()[:120]
                item[col] = value
            out.append(item)
        return out
