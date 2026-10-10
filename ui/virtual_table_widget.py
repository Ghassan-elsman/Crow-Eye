"""
Virtual Table Widget for Crow Eye
Provides a truly virtualized table (QTableView + lazy QAbstractTableModel) that
loads rows on demand. Qt only requests data() for visible cells, so there is no
per-row item allocation — this scales smoothly to multi-million-row MFT/USN/SRUM
tables where the old QTableWidget + setRowCount(total) approach lagged badly.

Row data is fetched a small page at a time and addressed by rowid (seek by
rowid, not LIMIT/OFFSET). Which rowids a page holds is found by walking the
table's own order from the nearest known page edge (keyset paging), so opening
a 12M-row table reads one page, not every rowid. Only a sort with no index
behind it still builds the full ordered rowid list - on a worker thread when
the table is large.
"""

from PyQt5.QtWidgets import QTableView, QHeaderView, QAbstractItemView
from PyQt5.QtCore import (pyqtSignal, pyqtSlot, Qt, QAbstractTableModel, QModelIndex,
                          QObject, QThread, QCoreApplication)
from typing import Optional, List, Dict, Any
import logging
import os
from array import array
from collections import OrderedDict
import re
import sqlite3

from dynamic_mapping.enrichment.enrichment_mixin import EnrichmentMixin


# ---------------------------------------------------------------- ordering
# A page is found by walking the table in its display order from a known
# position (keyset paging), not by materialising every rowid first. Building
# that list was the whole cost of opening the MFT tab: SELECT rowid ... ORDER BY
# over 6.6M-12.4M rows per table, 9-70 s each, on the GUI thread.
#
# The order is decided by SQLite itself: EXPLAIN QUERY PLAN for the view's
# ORDER BY tells which b-tree it walks. A plain table scan is rowid order; an
# index scan is that index's order, i.e. its key columns and then rowid. That
# is exactly the order the old rowid list had, so pages are identical. A plan
# that needs a temporary b-tree (a column with no index behind it) still gets a
# full rowid list - built on a worker thread when the table is large.

_IDENT = r'(?:"(?:[^"]|"")+"|\[[^\]]+\]|`[^`]+`|[A-Za-z_][A-Za-z0-9_$]*)'
_ORDER_TERM = re.compile(r'^\s*(' + _IDENT + r')\s*(?:\s(ASC|DESC))?\s*$', re.I)
_ROWID_NAMES = {'rowid', '_rowid_', 'oid'}


def _unquote(ident: str) -> str:
    if len(ident) >= 2 and ident[0] == '"' and ident[-1] == '"':
        return ident[1:-1].replace('""', '"')
    if len(ident) >= 2 and ((ident[0] == '[' and ident[-1] == ']')
                            or (ident[0] == '`' and ident[-1] == '`')):
        return ident[1:-1]
    return ident


def _q(col: str) -> str:
    """SQL for a key column: rowid stays bare, everything else is quoted."""
    if col == 'rowid':
        return 'rowid'
    return '"' + col.replace('"', '""') + '"'


def _parse_order(order_by: str):
    """'a DESC, "b" ASC' -> [('a', True), ('b', False)], or None if not plain columns."""
    terms = []
    for part in str(order_by).split(','):
        m = _ORDER_TERM.match(part)
        if not m:
            return None
        terms.append((_unquote(m.group(1)), (m.group(2) or 'ASC').upper() == 'DESC'))
    return terms or None


def _is_rowid_alias(conn, table: str, col: str) -> bool:
    try:
        info = conn.execute('PRAGMA table_info(%s)' % _q(table)).fetchall()
    except sqlite3.Error:
        return False
    pks = [r for r in info if r[5]]
    return (len(pks) == 1 and str(pks[0][1]).lower() == col.lower()
            and str(pks[0][2] or '').upper() == 'INTEGER')


def order_key_for(conn, table: str, order_by: str):
    """The total order SQLite uses for ``SELECT rowid FROM table ORDER BY order_by``.

    Returns (key_columns, descending) where key_columns ends with 'rowid', or
    None when that order needs a sort (no index behind it) or is not a list of
    plain columns.
    """
    terms = _parse_order(order_by)
    if not terms:
        return None
    desc = terms[0][1]
    if any(d != desc for _c, d in terms):
        return None
    plan = conn.execute('EXPLAIN QUERY PLAN SELECT rowid FROM %s ORDER BY %s'
                        % (table, order_by)).fetchall()
    details = [str(r[-1]) for r in plan]
    if any('TEMP B-TREE' in d.upper() for d in details):
        return None
    scans = [d for d in details if d.upper().startswith(('SCAN', 'SEARCH'))]
    if len(scans) != 1:
        return None
    m = re.search(r'USING (?:COVERING )?INDEX (\S+)', scans[0])
    if m is None:
        if 'USING' in scans[0].upper():
            return None
        first = terms[0][0]
        if first.lower() in _ROWID_NAMES or _is_rowid_alias(conn, table, first):
            return ['rowid'], desc
        return None
    idx = m.group(1)
    cols = []
    for _seq, cid, name, idesc, coll, is_key in conn.execute(
            'PRAGMA index_xinfo(%s)' % _q(idx)).fetchall():
        if not is_key:
            continue
        if cid is None or cid < 0 or idesc or str(coll or 'BINARY').upper() != 'BINARY':
            return None
        cols.append(name)
    key = cols + ['rowid']
    for i, (name, _d) in enumerate(terms):
        want = 'rowid' if (name.lower() in _ROWID_NAMES
                           or _is_rowid_alias(conn, table, name)) else name
        if i >= len(key) or key[i].lower() != want.lower():
            return None
    return key, desc


def _segments(key, anchor, asc):
    """WHERE terms for the rows after ``anchor`` in one direction, as disjoint
    index ranges in walk order (equality prefix + a range on the next column).
    NULLs sort first ascending and last descending, as in an index."""
    if anchor is None:
        return [([], [])]
    segs = []
    for i in range(len(key) - 1, -1, -1):
        terms, params = [], []
        for j in range(i):
            if anchor[j] is None:
                terms.append('%s IS NULL' % _q(key[j]))
            else:
                terms.append('%s = ?' % _q(key[j]))
                params.append(anchor[j])
        col, v = _q(key[i]), anchor[i]
        if asc:
            if v is None:
                segs.append((terms + ['%s IS NOT NULL' % col], params))
            else:
                segs.append((terms + ['%s > ?' % col], params + [v]))
        elif v is not None:
            segs.append((terms + ['%s < ?' % col], params + [v]))
            if key[i] != 'rowid':
                segs.append((terms + ['%s IS NULL' % col], params))
    return segs


def keyset_walk(conn, table, key, desc, where, params, anchor, backward, skip, limit):
    """Key tuples of up to ``limit`` rows after ``anchor`` (None = an end of the
    table), skipping ``skip`` rows first, walking forward or backward through
    the order (key, desc). Rows come back in walk order."""
    asc = (not desc) != bool(backward)
    direction = 'ASC' if asc else 'DESC'
    order_sql = ', '.join('%s %s' % (_q(k), direction) for k in key)
    sel = ', '.join(_q(k) for k in key)
    base_terms = ['(%s)' % where] if where else []
    base_params = list(params or ())
    out = []
    for terms, sp in _segments(key, anchor, asc):
        need = limit - len(out)
        if need <= 0:
            break
        wsql = ' AND '.join(base_terms + terms) or '1'
        allp = base_params + list(sp)
        rows = conn.execute('SELECT %s FROM %s WHERE %s ORDER BY %s LIMIT ? OFFSET ?'
                            % (sel, table, wsql, order_sql), allp + [need, skip]).fetchall()
        if rows or not skip:
            skip = 0
        else:
            # The skip runs past this range: count it (no ORDER BY needed).
            n = conn.execute('SELECT count(*) FROM (SELECT 1 FROM %s WHERE %s LIMIT ?)'
                             % (table, wsql), allp + [skip]).fetchone()[0]
            skip -= n
        out.extend(tuple(r) for r in rows)
    return out


def count_before(conn, table, key, desc, where, params, anchor):
    """How many rows of the view come before the row whose key is ``anchor``."""
    asc = desc  # walking backward from the anchor
    base_terms = ['(%s)' % where] if where else []
    total = 0
    for terms, sp in _segments(key, anchor, asc):
        wsql = ' AND '.join(base_terms + terms) or '1'
        total += conn.execute('SELECT count(*) FROM %s WHERE %s' % (table, wsql),
                              list(params or ()) + list(sp)).fetchone()[0]
    return total


def _ro_connect(db_path):
    conn = sqlite3.connect('file:%s?mode=ro' % str(db_path).replace('\\', '/'),
                           uri=True, timeout=30)
    try:
        conn.execute('PRAGMA cache_size = -65536')
    except sqlite3.Error:
        pass
    return conn


class _InterruptibleWorker(QThread):
    """A worker with its own read-only connection that can be stopped mid-query.

    ``_live_conn`` is kept only so cancel() can call interrupt() on it from the
    GUI thread - the one sqlite3 call made to be used across threads. Nothing
    else touches it outside run(), and run() closes it on its own thread.
    """

    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path
        self._cancel = False
        self._live_conn = None

    def cancel(self):
        self._cancel = True
        conn = self._live_conn
        if conn is not None:
            try:
                conn.interrupt()
            except Exception:
                pass

    def _open(self):
        self._live_conn = _ro_connect(self.db_path)
        return self._live_conn

    def _close(self):
        conn, self._live_conn = self._live_conn, None
        if conn is not None:
            conn.close()


class _RowidListWorker(_InterruptibleWorker):
    """Builds the ordered rowid list for a sort that has no index behind it."""

    built = pyqtSignal(int, object, str)  # generation, array('q') or None, error

    def __init__(self, gen, db_path, sql, params):
        super().__init__(db_path)
        self.gen, self.sql, self.params = gen, sql, list(params or ())

    def run(self):
        try:
            conn = self._open()
            cur = conn.execute(self.sql, self.params)
            ids = array('q')
            while not self._cancel:
                chunk = cur.fetchmany(100000)
                if not chunk:
                    break
                ids.extend(r[0] for r in chunk)
            self.built.emit(self.gen, None if self._cancel else ids,
                            'cancelled' if self._cancel else '')
        except Exception as e:
            self.built.emit(self.gen, None, 'cancelled' if self._cancel else str(e))
        finally:
            self._close()


class _CountWorker(_InterruptibleWorker):
    """COUNT(*) of each table, once, in order, on its own connection."""

    counted = pyqtSignal(str, object)  # table, row count (None if it failed)

    def __init__(self, db_path, tables):
        super().__init__(db_path)
        self.tables = list(tables)

    def run(self):
        try:
            conn = self._open()
            for t in self.tables:
                if self._cancel:
                    break
                try:
                    n = conn.execute('SELECT COUNT(*) FROM %s' % _q(t)).fetchone()[0]
                except sqlite3.Error:
                    n = None
                if not self._cancel:
                    self.counted.emit(t, n)
        except Exception:
            pass
        finally:
            self._close()


class _MarksWorker(_InterruptibleWorker):
    """Every PAGE-th key of a keyset view, so a jump anywhere is one page read.

    SQLite numbers the rows itself (row_number() over the index order, no sort)
    and hands back one row in PAGE - ~26k small tuples for 6.6M rows - so the
    walk runs inside SQLite with the GIL released.
    """

    built = pyqtSignal(int, object)  # generation, list of key tuples (None if stopped)

    def __init__(self, gen, db_path, sql, params):
        super().__init__(db_path)
        self.gen, self.sql, self.params = gen, sql, list(params or ())

    def run(self):
        marks = None
        try:
            conn = self._open()
            marks = [tuple(r) for r in conn.execute(self.sql, self.params).fetchall()]
        except Exception:
            marks = None
        finally:
            self._close()
        self.built.emit(self.gen, None if self._cancel else marks)


# Running workers stay referenced here until they finish: a QThread that is
# garbage-collected while running takes the process down with it. They are
# stopped (interrupt) and waited for when the application quits.
_LIVE_WORKERS = set()
_QUIT_HOOKED = []


def _keep_alive_until_done(worker):
    _LIVE_WORKERS.add(worker)
    if not _QUIT_HOOKED:
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(_stop_all_workers)
            _QUIT_HOOKED.append(True)


def _stop_all_workers():
    for wk in list(_LIVE_WORKERS):
        if isinstance(wk, QThread):
            try:
                wk.cancel()
                wk.wait(5000)
            except Exception:
                pass


class _CountRouter(QObject):
    """Lives on the GUI thread; hands each count to its table, if still there."""

    def __init__(self, worker, widgets):
        super().__init__()
        self.worker, self.widgets = worker, dict(widgets)

    @pyqtSlot(str, object)
    def on_counted(self, table, n):
        w = self.widgets.get(table)
        try:
            from PyQt5 import sip
            alive = w is not None and not sip.isdeleted(w)
        except Exception:
            alive = w is not None
        if alive:
            w._on_background_count(n)

    @pyqtSlot()
    def on_finished(self):
        self.worker.wait()
        for w in self.widgets.values():
            try:
                w._count_worker = None
            except Exception:
                pass
        _LIVE_WORKERS.discard(self.worker)
        _LIVE_WORKERS.discard(self)


def count_rows_in_background(db_path, widgets_by_table) -> QThread:
    """Count each table ONCE, off the GUI thread, and hand each count to its
    VirtualTableWidget as it arrives (``{table_name: widget}``, counted in that
    order). Until then a table shows an estimate from its rowid range - exact
    for these insert-only tables, and corrected (the view re-plans) if not.
    """
    worker = _CountWorker(db_path, list(widgets_by_table))
    router = _CountRouter(worker, widgets_by_table)
    worker.counted.connect(router.on_counted, Qt.QueuedConnection)
    worker.finished.connect(router.on_finished, Qt.QueuedConnection)
    for w in widgets_by_table.values():
        w._count_worker = worker
    _keep_alive_until_done(worker)
    _LIVE_WORKERS.add(router)
    worker.start()
    return worker


class _LazyArtifactModel(QAbstractTableModel):
    """
    Lazy table model backing VirtualTableWidget.

    rowCount() reports the full total, but rows are only fetched (a page at a
    time) when Qt asks data() for them — i.e. only for visible cells. Pages are
    cached with simple LRU eviction so memory stays bounded while scrolling.
    All data-source state (table, columns, filter, order, enrichment) is read
    from the owning widget so there is a single source of truth.

    How a page's rowids are found (``_mode``):
      'dense'  - rowid order, no filter, rowids without gaps: row i is rowid
                 lo+i. Nothing is read to place a row.
      'keyset' - rowid or index order: walk from the nearest known page edge
                 (or either end of the table) - see keyset_walk().
      'list'   - the order needs a sort: an ordered rowid list, as before.
      'offset' - fallback when none of the above could be set up.
    """

    PAGE = 256            # rows per fetched chunk (keeps rowid IN-lists small)
    MAX_CACHED_PAGES = 16  # ~4k rows kept resident
    MAX_BOUNDS = 4096      # page edges remembered for keyset jumps (tiny tuples)
    # Above this many rows a full rowid list (an unindexed sort) is built on a
    # worker thread with the loading bar; below it, inline - it takes < 0.1 s.
    SYNC_LIST_MAX_ROWS = 200000
    # A keyset view this big gets page marks (_MarksWorker) in the background,
    # so a jump deep into it reads one page instead of walking the index there.
    MARKS_MIN_ROWS = 100000

    def __init__(self, widget):
        super().__init__(widget)
        self.w = widget
        self._rowids = None        # array('q') of ordered rowids ('list' mode)
        self._total = 0
        self._cache: Dict[int, Any] = {}   # row_index -> record dict (or None)
        self._page_order: List[int] = []   # loaded page-start indices (LRU)
        self._mode = 'empty'
        self._key = None           # keyset: key columns, ending with 'rowid'
        self._desc = False
        self._lo = self._hi = 0    # dense: rowid range
        self._bounds = OrderedDict()  # page start -> (first key, last key, end)
        self._gen = 0              # bumps on every reset; stale async results are dropped
        self.unfiltered_total = None
        self._marks = None         # keyset: key of the last row of every page
        self._marks_page = 0
        self._marks_worker = None

    # ------------------------------------------------------------------ Qt API
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self._total

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.w.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.UserRole and orientation == Qt.Horizontal:
            # The database column behind the header, whatever its label says
            # (ui/column_colors.py colours a column by this name).
            if 0 <= section < len(self.w.columns):
                return self.w.columns[section]
            return None
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            labels = getattr(self.w, '_header_labels', None)
            if labels and 0 <= section < len(labels):
                return labels[section]
            if 0 <= section < len(self.w.columns):
                return self.w.columns[section]
            return None
        return str(section + 1)

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        row = index.row()
        rec = self._cache.get(row)
        if rec is None:
            self._ensure_row(row)
            rec = self._cache.get(row)
            if rec is None:
                return None
        col_name = self.w.columns[index.column()]
        value = rec.get(col_name)
        text = self.w.format_for_display(col_name, value)
        # Inline enrichment on the chosen column only.
        if col_name == self.w.enrichment_column:
            dyn = rec.get('Dynamic_Key')
            if dyn:
                try:
                    return self.w.format_enriched_value(text, dyn)
                except Exception:
                    return text
        return text

    # ---------------------------------------------------------------- loading
    def _clear_state(self):
        self._cache.clear()
        self._page_order.clear()
        self._bounds.clear()
        self._rowids = None
        self._key = None
        self._mode = 'empty'
        self._total = 0
        self._gen += 1
        self.__dict__.pop('_rid_index', None)
        self._marks = None
        if self._marks_worker is not None:
            self._marks_worker.cancel()   # its result is dropped by the generation check
            self._marks_worker = None

    def reload(self, total_hint=None):
        """Set the model up for the widget's current table/filter/order.

        Returns 'pending' when an unindexed sort of a large table is being
        built on a worker (the view keeps what it shows until it is ready),
        otherwise True.
        """
        w = self.w
        if getattr(self, '_list_worker', None) is not None:
            self.cancel_pending()
            w._on_sort_finished(None, 'superseded')
        try:
            plan = self._plan(total_hint)
        except Exception as e:
            w.logger.warning(f"paging setup failed for '{w.table_name}'; "
                             f"using OFFSET fallback: {e}")
            plan = {'mode': 'offset'}

        if plan['mode'] == 'list' and plan.get('async'):
            if self._start_list_worker(plan):
                return 'pending'
            plan['async'] = False

        self.beginResetModel()
        self._clear_state()
        try:
            if plan['mode'] == 'list':
                self._build_rowids()
                self._total = len(self._rowids)
                self._mode = 'list'
            elif plan['mode'] == 'offset':
                self._mode = 'offset'
                self._total = self._count_rows()
            else:
                self._mode = plan['mode']
                self._total = plan['total']
                self._key, self._desc = plan.get('key'), plan.get('desc', False)
                self._lo, self._hi = plan.get('lo', 0), plan.get('hi', 0)
        except Exception as e:
            w.logger.warning(f"rowid index build failed for '{w.table_name}'; "
                             f"using OFFSET fallback: {e}")
            self._rowids = None
            self._mode = 'offset'
            self._total = self._count_rows()
        self.endResetModel()
        if self._mode == 'keyset' and self._total >= self.MARKS_MIN_ROWS:
            self._start_marks_worker()
        return True

    def _start_marks_worker(self):
        w = self.w
        if not self._can_async():
            return
        try:
            direction = 'DESC' if self._desc else 'ASC'
            inner = ', '.join('rowid AS _vtw_rid' if k == 'rowid' else _q(k) for k in self._key)
            outer = ', '.join('_vtw_rid' if k == 'rowid' else _q(k) for k in self._key)
            order_sql = ', '.join('%s %s' % (_q(k), direction) for k in self._key)
            sql = ('SELECT %s FROM (SELECT %s, row_number() OVER (ORDER BY %s) AS _vtw_rn '
                   'FROM %s%s) WHERE _vtw_rn %% %d = 0' % (
                       outer, inner, order_sql, w.table_name,
                       (' WHERE %s' % w.where_clause) if w.where_clause else '', self.PAGE))
            worker = _MarksWorker(self._gen, w.data_loader.db_path, sql, w.where_params)
        except Exception as e:
            w.logger.debug("page marks not started for '%s': %s", w.table_name, e)
            return
        self._marks_page = self.PAGE
        worker.built.connect(self._on_marks_built, Qt.QueuedConnection)
        _keep_alive_until_done(worker)
        self._marks_worker = worker
        worker.start()

    @pyqtSlot(int, object)
    def _on_marks_built(self, gen, marks):
        worker = self.sender()
        if worker is not None:
            worker.wait()
            _LIVE_WORKERS.discard(worker)
            if worker is self._marks_worker:
                self._marks_worker = None
        if gen == self._gen and marks:
            self._marks = marks

    def _plan(self, total_hint):
        """Decide the paging mode. Reads only the plan, the count (unless it is
        already known) and, for rowid order, the two ends of the rowid range."""
        w = self.w
        conn = w.data_loader.connection
        table = w.table_name
        order = w.order_by or 'rowid'
        where = w.where_clause
        key = order_key_for(conn, table, order)

        if where:
            total = self._count_rows()
        elif total_hint is not None:
            total = int(total_hint)
        else:
            total = int(w.data_loader.get_row_count(table))
        if not where:
            self.unfiltered_total = total

        if key is None:
            return {'mode': 'list', 'total': total,
                    'async': total > self.SYNC_LIST_MAX_ROWS and self._can_async()}
        cols, desc = key
        if cols == ['rowid'] and not where:
            if total == 0:
                return {'mode': 'dense', 'total': 0, 'lo': 0, 'hi': -1, 'desc': desc}
            lo = conn.execute('SELECT rowid FROM %s ORDER BY rowid ASC LIMIT 1' % table).fetchone()
            hi = conn.execute('SELECT rowid FROM %s ORDER BY rowid DESC LIMIT 1' % table).fetchone()
            if lo and hi and hi[0] - lo[0] + 1 == total:
                return {'mode': 'dense', 'total': total, 'lo': lo[0], 'hi': hi[0], 'desc': desc}
        return {'mode': 'keyset', 'total': total, 'key': cols, 'desc': desc}

    def estimate_total(self) -> int:
        """Rows by the rowid range: two O(log n) seeks, no scan. Exact when the
        rowids have no gaps (insert-only tables); an upper bound otherwise."""
        return int(self.w.data_loader.estimate_row_count(self.w.table_name))

    def _can_async(self) -> bool:
        app = QCoreApplication.instance()
        db_path = getattr(self.w.data_loader, 'db_path', None)
        return bool(app is not None and QThread.currentThread() is app.thread()
                    and db_path and os.path.exists(str(db_path)))

    def _list_sql(self):
        w = self.w
        sql = f"SELECT rowid FROM {w.table_name}"
        if w.where_clause:
            sql += f" WHERE {w.where_clause}"
        sql += f" ORDER BY {w.order_by or 'rowid'}"
        return sql

    def _start_list_worker(self, plan) -> bool:
        w = self.w
        try:
            self._gen += 1
            worker = _RowidListWorker(self._gen, w.data_loader.db_path, self._list_sql(),
                                      w.where_params)
        except Exception as e:
            w.logger.warning("sort worker not started: %s", e)
            return False
        worker.built.connect(self._on_list_built, Qt.QueuedConnection)
        _keep_alive_until_done(worker)
        self._list_worker = worker
        w._on_sort_started(plan.get('total', 0), worker)
        worker.start()
        return True

    @pyqtSlot(int, object, str)
    def _on_list_built(self, gen, ids, error):
        worker = self.sender()
        if worker is not None:
            # 'built' is the worker's last act: let it end, then let it go
            # (on this thread - never drop a running QThread's last reference).
            worker.wait()
            _LIVE_WORKERS.discard(worker)
        if gen != self._gen:
            return  # superseded by a newer reload / clear
        self._list_worker = None
        if ids is None:
            self.w._on_sort_finished(False, error)
            return
        self.beginResetModel()
        self._clear_state()
        self._rowids = ids
        self._total = len(ids)
        self._mode = 'list'
        self.endResetModel()
        self.w._on_sort_finished(True, '')

    def cancel_pending(self):
        worker = getattr(self, '_list_worker', None)
        if worker is not None:
            worker.cancel()
        self._list_worker = None
        self._gen += 1

    def _count_rows(self) -> int:
        w = self.w
        try:
            if w.where_clause:
                q = f"SELECT COUNT(*) AS c FROM {w.table_name} WHERE {w.where_clause}"
                return int(w.data_loader.count_query(q, w.where_params))
            return int(w.data_loader.get_row_count(w.table_name))
        except Exception:
            return 0

    def _build_rowids(self):
        """Fetch an ordered list of rowids once (integers only, compact).

        Only for an order with no index behind it (see order_key_for); a large
        table gets this on a worker (_RowidListWorker) instead.
        """
        w = self.w
        conn = w.data_loader.connection
        cur = conn.cursor()
        import time as _time
        t0 = _time.perf_counter()
        cur.execute(self._list_sql(), tuple(w.where_params) if w.where_params else [])
        self._rowids = array('q', (r[0] for r in cur))
        took = _time.perf_counter() - t0
        if took > 0.5:
            w.logger.warning("rowid index for '%s' (ORDER BY %s) took %.2f s for %d rows - "
                             "an index on that order would help", w.table_name,
                             w.order_by or 'rowid', took, len(self._rowids))

    def _ensure_row(self, row: int):
        if row < 0 or row >= self._total:
            return
        start = (row // self.PAGE) * self.PAGE
        if start in self._page_order:
            return
        self._load_page(start)

    # ------------------------------------------------------------ page rowids
    def _page_rowids(self, start: int, end: int):
        """The rowids shown on rows [start, end), in view order."""
        if self._mode == 'list':
            return list(self._rowids[start:end])
        if self._mode == 'dense':
            if self._desc:
                return list(range(self._hi - start, self._hi - end, -1))
            return list(range(self._lo + start, self._lo + end))
        return self._keyset_page(start, end)

    def _keyset_page(self, start: int, end: int):
        w = self.w
        n = end - start
        # The cheapest starting point: either end of the table, or the edge of
        # a page already seen (scrolling on from it costs nothing to skip).
        best = (start, False, None)                   # (skip, backward, anchor)
        p = start // self.PAGE
        if self._marks and self._marks_page == self.PAGE and start % self.PAGE == 0 \
                and 0 < p <= len(self._marks):
            best = (0, False, self._marks[p - 1])     # the last key of the page before
        if self._total - end < best[0]:
            best = (self._total - end, True, None)
        for s, (first, last, e) in self._bounds.items():
            if e <= start and start - e < best[0]:
                best = (start - e, False, last)
            if s >= end and s - end < best[0]:
                best = (s - end, True, first)
        skip, backward, anchor = best
        rows = keyset_walk(w.data_loader.connection, w.table_name, self._key, self._desc,
                           w.where_clause, w.where_params, anchor, backward, skip, n)
        if backward:
            rows.reverse()
            if len(rows) < n:  # the table shrank under us: keep rows aligned to the end
                rows = [None] * (n - len(rows)) + rows
        got = [r for r in rows if r is not None]
        if got:
            self._bounds[start] = (got[0], got[-1], start + len(rows))
            self._bounds.move_to_end(start)
            while len(self._bounds) > self.MAX_BOUNDS:
                self._bounds.popitem(last=False)
        return [None if r is None else r[-1] for r in rows]

    def _load_page(self, start: int):
        w = self.w
        end = min(start + self.PAGE, self._total)
        if end <= start:
            return
        # Quote identifiers so columns containing spaces / reserved words
        # (e.g. "Process Name") don't produce invalid SQL (which execute_query
        # would swallow, leaving the whole page blank).
        select_cols = ", ".join('"' + c + '"' for c in w.columns)
        enriched = bool(w.get_intelligence_db_path() and w.enrichment_column)
        try:
            if self._mode in ('list', 'dense', 'keyset'):
                # Seek by rowid: order comes from the page's rowids (mapped
                # back via _vtw_rid), so this works for natural, custom-sorted
                # and filtered views alike regardless of SQL row order.
                chunk_ids = self._page_rowids(start, end)
                ids_csv = ",".join(str(int(r)) for r in chunk_ids if r is not None) or "NULL"
                if enriched:
                    base = f"SELECT {select_cols}, rowid AS _vtw_rid FROM {w.table_name}"
                    query = w.get_enrichment_query(base, w.table_name, w.enrichment_column)
                    alias = f'"{w.table_name[:3]}_tbl"'
                    query += f" WHERE {alias}.rowid IN ({ids_csv})"
                else:
                    query = (
                        f"SELECT {select_cols}, rowid AS _vtw_rid "
                        f"FROM {w.table_name} WHERE rowid IN ({ids_csv})"
                    )
                rows = w.data_loader.execute_query(query, [])
                by_rid = {rec.get('_vtw_rid'): rec for rec in rows}
                for i in range(end - start):
                    rid = chunk_ids[i] if i < len(chunk_ids) else None
                    rec = by_rid.get(rid) if rid is not None else None
                    if rec is not None:
                        rec.pop('_vtw_rid', None)  # drop the rowid helper column
                    self._cache[start + i] = rec
            else:
                # Fallback: no paging could be set up (rare — e.g. a view, which
                # has no rowid). Page by OFFSET with the real filter + order.
                # Enrichment is sacrificed here so the filtered/ordered rows stay
                # correct; correctness of which rows appear beats enrichment.
                query = f"SELECT {select_cols} FROM {w.table_name}"
                if w.where_clause:
                    query += f" WHERE {w.where_clause}"
                if w.order_by:
                    query += f" ORDER BY {w.order_by}"
                query += f" LIMIT {end - start} OFFSET {start}"
                rows = w.data_loader.execute_query(query, w.where_params)
                for i, rec in enumerate(rows):
                    self._cache[start + i] = rec
        except Exception as e:
            w.logger.error(f"page load failed (start={start}) for '{w.table_name}': {e}")
            for i in range(start, end):
                self._cache.setdefault(i, None)

        # Register the page and evict the oldest to keep memory bounded.
        self._page_order.append(start)
        while len(self._page_order) > self.MAX_CACHED_PAGES:
            old = self._page_order.pop(0)
            for i in range(old, min(old + self.PAGE, self._total)):
                self._cache.pop(i, None)

    def record_at(self, row: int):
        rec = self._cache.get(row)
        if rec is None:
            self._ensure_row(row)
            rec = self._cache.get(row)
        return rec

    # ------------------------------------------------------ rowid -> view row
    def position_of(self, rowid) -> Optional[int]:
        """The view row holding database rowid ``rowid`` (None if not in view).

        Safe on any thread for 'dense'/'keyset': it reads through its own
        read-only connection, never the GUI thread's.
        """
        try:
            rowid = int(rowid)
        except (TypeError, ValueError):
            return None
        if self._mode == 'dense':
            pos = (self._hi - rowid) if self._desc else (rowid - self._lo)
            return pos if 0 <= pos < self._total else None
        if self._mode != 'keyset':
            return None
        w = self.w
        db_path = getattr(w.data_loader, 'db_path', None) if w.data_loader else None
        if not db_path:
            return None
        key, desc, where, params = self._key, self._desc, w.where_clause, w.where_params
        conn = _ro_connect(db_path)
        try:
            sql = 'SELECT %s FROM %s WHERE rowid = ?' % (', '.join(_q(k) for k in key),
                                                         w.table_name)
            p = [rowid]
            if where:
                sql += ' AND (%s)' % where
                p += list(params or ())
            row = conn.execute(sql, p).fetchone()
            if row is None:
                return None
            return count_before(conn, w.table_name, key, desc, where, params, tuple(row))
        finally:
            conn.close()


class VirtualTableWidget(QTableView, EnrichmentMixin):
    """
    A QTableView-backed lazily-loaded table. Drop-in replacement for the former
    QTableWidget implementation: same constructor, signals, public methods and
    externally-read attributes, but truly virtualized for large datasets.
    """

    # Signals
    data_requested = pyqtSignal(int, int)  # offset, limit (kept for API compat)
    loading_started = pyqtSignal()
    loading_finished = pyqtSignal()
    data_loaded = pyqtSignal()  # Emitted when data is loaded and ready for styling
    sort_finished = pyqtSignal(bool)  # an unindexed sort built on a worker is ready (or not)

    # Enrichment Target Columns: Set of column names that should be enriched
    # If empty, the heuristic in _initialize_intelligence will try to pick the best ones.
    ENRICHMENT_TARGET_COLUMNS = {
        # --- File & Path Identifiers ---
        'target_path', 'Local_Path', 'Source_Name', 'Source_Path', 'executable_path',
        'key_path', 'program_path', 'app_path', 'file_path', 'folder_path', 'root_dir_path',
        'lower_case_long_path', 'process_path', 'image_path', 'ShortcutPath',
        'ShortcutTargetPath', 'mare_path', 'install_location', 'original_path',
        'recycle_bin_path', 'r_file_path', 'reconstructed_path', 'registry_path',
        'parent_path', 'Relative_Path', 'Working_Directory', 'Icon_Location',
        'Common_Path', 'manifest_path', 'package_full_name', 'bundle_manifest_path',
        'srudb_path', 'uninstall_string', 'path', 'folder_path', 'icon', 'ShortcutAumid',

        # --- User & System Identifiers ---
        'SID', 'user_sid', 'sid', 'User', 'username', 'user_name', 'Owner_UID',
        'registered_owner', 'ComputerName', 'computer_name', 'ComputerNameInfo',
        'Tracker_NetBIOS', 'ComputerName', 'registered_organization', 'product_id',
        'Owner_GID', 'owner_id', 'security_id', 'profile_image_path',

        # --- Network Identifiers ---
        'MAC_Address', 'gateway_mac', 'mac_address', 'dhcp_server', 'dns_servers',
        'network_name', 'server_name', 'share_name', 'interface_id', 'Tracker_MAC',
        'ip_address', 'network_share', 'interface_luid', 'l2_profile_id',
        'Birth_Object_ID_MAC', 'dhcp_server',

        # --- Hardware & Device Identifiers ---
        'device_id', 'instance_id', 'parent_id', 'serial_number', 'vendor_id',
        'product_id', 'volume_guid', 'model_id', 'class_guid', 'Device_ID',
        'Volume_Serial', 'Volume_Label', 'volume_name', 'Known_Folder_GUID',
        'Birth_Volume_ID', 'Birth_Object_ID', 'DestList_New_Volume_ID',
        'DestList_New_Object_ID', 'LNK_Class_ID', 'class_id', 'interface_luid',

        # --- Forensic & Process Identifiers ---
        'Value', 'Name', 'Filename', 'file_name', 'executable_name', 'fn_filename',
        'original_file_name', 'file_id', 'program_id', 'program_instance_id',
        'Process Name', 'app_name', 'program_name', 'service_name', 'display_name',
        'friendly_name', 'model_name', 'mare_name', 'search_term', 'command',
        'EventID', 'Source', 'TaskCategory', 'AppID',
        'entry_hash', 'original_filename',
        'random_i_filename', 'random_r_filename', 'ShortcutAumid', 'ShortcutProgramId',
        'driver_name', 'driver_id', 'mare_id', 'uup_id', 'uup_name', 'subkey_name',
        'folder_name', 'short_name',

        # --- Generic but Pattern-Heavy Columns ---
        'row_data', 'subkey', 'data', 'version', 'bin_file_version',
        'bin_product_version', 'display_version', 'driver_version', 'product_version'
    }

    # Identity / sequence columns that must NEVER be used as an enrichment target.
    # These hold incrementing integers (primary keys, MFT/USN record numbers) that
    # spuriously collide with numeric-valued mappings (e.g. Event-ID lookups),
    # producing meaningless "[Description not available]" enrichments.
    ENRICHMENT_EXCLUDED_COLUMNS = {
        'id', 'ID', 'rowid', 'ROWID', 'record_number', 'mft_record_number',
        'frn', 'parent_frn', 'parent_record', 'usn_event_id', 'offset',
    }

    def __init__(
        self,
        data_loader,
        table_name: str,
        columns: List[str],
        page_size: int = 1000,
        buffer_size: int = 2000,
        parent=None
    ):
        """
        Initialize virtual table widget.

        Args:
            data_loader: BaseDataLoader instance for database access
            table_name: Name of the database table
            columns: List of column names to display
            page_size: (retained for API compatibility; the lazy model uses its
                own small internal page size)
            buffer_size: (retained for API compatibility)
            parent: Parent widget
        """
        QTableView.__init__(self, parent)
        EnrichmentMixin.__init__(self)

        self.logger = logging.getLogger(__name__)

        # Data source configuration
        self.data_loader = data_loader
        self.table_name = table_name
        self.columns = columns
        self.page_size = page_size
        self.buffer_size = buffer_size

        # Enrichment configuration
        self.enrichment_column = None
        self._intelligence_initialized = False

        # Filter / sort state
        self.where_clause = None
        self.where_params = ()
        self.order_by = None

        # Data state
        self.total_rows = 0
        self.is_loading = False

        # Opt-in behaviour (event logs set these; MFT/USN/SRUM leave them off)
        self.searchable = False                 # include in the toolbar search
        self.time_column = None                 # column the search's time filter uses
        self.preferred_enrichment_column = None  # beats the heuristic when present
        self._sort_column = None
        self._sort_desc = False
        self._default_order = None

        # Optional display labels for the horizontal header (set via
        # setHorizontalHeaderLabels). The model still uses `columns` for SQL.
        self._header_labels = None

        # A row count the caller already has (set_known_row_count) is used by
        # the next load instead of counting again; a deferred table loads the
        # first time it is shown (defer_initial_load).
        self._known_row_count = None
        self._load_pending = False
        self._count_worker = None      # count_rows_in_background() is counting this table
        self._estimated_total = False  # the model's total is the rowid-range estimate
        self._sort_overlay = None
        self._sort_prev = None

        # Backing model
        self._model = _LazyArtifactModel(self)
        self.setModel(self._model)

        self._init_view()

    def _init_view(self):
        """Configure the view for fast, virtualized display."""
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(True)
        self.setSortingEnabled(False)  # ordering is server-side via set_order_by
        self.setWordWrap(False)
        self.setAttribute(Qt.WA_StyledBackground, True)

        # Smooth per-pixel scrolling to match the other artifact tables.
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

        # Fixed-height rows => cheap geometry for huge row counts.
        vh = self.verticalHeader()
        vh.setSectionResizeMode(QHeaderView.Fixed)
        vh.setDefaultSectionSize(30)
        vh.setMinimumSectionSize(24)

        # Auto-fit columns to content (matches the other tables), but cap how
        # many rows ResizeToContents samples so it stays cheap on the lazy model.
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setStretchLastSection(True)
        hh.setMinimumSectionSize(80)
        hh.setSectionsClickable(True)
        hh.setHighlightSections(True)
        hh.setResizeContentsPrecision(50)

        self.doubleClicked.connect(self._on_double_clicked)

        # Standard columns in their own colours (ui/column_colors.py).
        try:
            from ui.column_colors import install as _install_column_colors
            _install_column_colors(self)
        except Exception as e:
            self.logger.debug("column colours not installed: %s", e)

    def setHorizontalHeaderLabels(self, labels):
        """QTableWidget-compatible: set the display labels shown in the header.

        The model keeps using the real `columns` for SQL; only the visible
        header text changes. SRUM tabs call this to show friendly names.
        """
        self._header_labels = list(labels) if labels else None
        try:
            self._model.headerDataChanged.emit(Qt.Horizontal, 0, max(0, len(self.columns) - 1))
        except Exception:
            pass

    # ----------------------------------------------------------- data loading
    def set_known_row_count(self, row_count) -> None:
        """Hand over a row count the caller has already taken (statistics).

        The next load uses it instead of running COUNT(*) again - the MFT tab
        counted every table twice, ~25 s each time on 37M rows. It is used once
        and only for the unfiltered view; a later refresh counts afresh.
        """
        self._known_row_count = None if row_count is None else int(row_count)
        if self._known_row_count is not None:
            self.total_rows = self._known_row_count

    def defer_initial_load(self, row_count=None) -> None:
        """Load when this table is first shown, not now.

        get_total_rows() already answers with ``row_count`` so the empty-table
        indicators are right before the tab is ever opened.
        """
        if row_count is not None:
            self.set_known_row_count(row_count)
        self._load_pending = True

    def estimate_row_count(self) -> int:
        """Rows by the rowid range (no COUNT); see _LazyArtifactModel.estimate_total."""
        try:
            return self._model.estimate_total()
        except Exception:
            return 0

    def _on_background_count(self, n) -> None:
        """The exact count from count_rows_in_background() arrived."""
        self._count_worker = None
        if n is None or self.data_loader is None:
            return
        n = int(n)
        model = self._model
        if self._load_pending or model._mode == 'empty':
            self.set_known_row_count(n)        # not loaded yet: used by the load
            return
        model.unfiltered_total = n
        if not self.where_clause:
            if self._estimated_total and model._mode in ('dense', 'keyset') \
                    and n != model.rowCount():
                # The rowids have gaps: re-plan with the true count.
                model.reload(total_hint=n)
            self.total_rows = model.rowCount() if model._mode != 'empty' else n
        self._estimated_total = False

    def _ensure_loaded(self) -> None:
        if self._load_pending and self.data_loader is not None:
            self._load_pending = False
            self.load_initial_data()

    def showEvent(self, event):
        super().showEvent(event)
        self._ensure_loaded()

    def load_initial_data(self) -> bool:
        """Detect enrichment, (re)build the model and refresh the view."""
        self._load_pending = False
        known = self._known_row_count
        self._known_row_count = None
        self._estimated_total = False
        try:
            self.loading_started.emit()
            self.is_loading = True

            # Existence only: the count comes from the caller's statistics
            # (set_known_row_count) or is taken once by the model.
            if not self.data_loader.table_exists(self.table_name):
                self.logger.error(f"Table '{self.table_name}' does not exist.")
                self._model.reload(total_hint=0)
                self.total_rows = 0
                return False

            # Intelligence Integration
            if not self._intelligence_initialized:
                self._initialize_intelligence()

            # Re-attach intelligence DB so enriched page queries can see Intel.*
            if self.get_intelligence_db_path():
                try:
                    cursor = self.data_loader.connection.cursor()
                    self.attach_intelligence_db(cursor)
                    self.logger.info(f"Attached intelligence brain to {self.table_name} view.")
                except Exception as attach_err:
                    self.logger.error(f"Failed to attach intelligence: {attach_err}")

            if known is None and self._count_worker is not None and not self.where_clause:
                # The exact count is on its way (count_rows_in_background):
                # open on the rowid-range estimate instead of counting here.
                known = self.estimate_row_count()
                self._estimated_total = True
            state = self._model.reload(
                total_hint=None if self.where_clause else known)
            self.total_rows = (self._model.rowCount() if state != 'pending'
                               else self._expected_total())

            self._apply_styles_immediately()
            self.data_loaded.emit()
            return True

        except Exception as e:
            self.logger.error(f"Error loading initial data: {e}")
            return False
        finally:
            self.is_loading = False
            self.loading_finished.emit()

    def refresh_data(self) -> bool:
        """Reload from the database (re-detecting enrichment if reset)."""
        try:
            return self.load_initial_data()
        except Exception as e:
            self.logger.error(f"Error refreshing data: {e}")
            return False

    def apply_filter(self, where_clause: str, where_params: tuple = ()) -> bool:
        """Apply a WHERE filter and reload."""
        try:
            self.where_clause = where_clause
            self.where_params = where_params
            return self.load_initial_data()
        except Exception as e:
            self.logger.error(f"Error applying filter: {e}")
            return False

    def clear_filter(self) -> bool:
        """Clear any applied filter and reload."""
        try:
            self.where_clause = None
            self.where_params = ()
            return self.load_initial_data()
        except Exception as e:
            self.logger.error(f"Error clearing filter: {e}")
            return False

    # Columns whose stored value is a number but whose readable form is a size,
    # a duration or a grouped integer. The database keeps the number so it can
    # be compared and filtered - SQLite sorts every TEXT above every INTEGER, so
    # storing "34.83 KB" made `bytes_sent > 1000000` match every row - and the
    # formatting happens here, where it belongs. Formatters are the ones the
    # SRUM parser already defines; nothing new is introduced.
    DISPLAY_FORMATTERS = {
        'bytes_sent': 'bytes',
        'bytes_received': 'bytes',
        'foreground_bytes_read': 'bytes',
        'foreground_bytes_written': 'bytes',
        'background_bytes_read': 'bytes',
        'background_bytes_written': 'bytes',
        'disk_raw': 'bytes',
        'network_bytes_raw': 'bytes',
        'network_tail_raw': 'bytes',
        'connected_time': 'duration',
        'charge_level': 'charge',
        'foreground_cycle_time': 'cpu',
        'background_cycle_time': 'cpu',
        'face_time': 'cpu',
        'interface_luid': 'number',
        'l2_profile_id': 'number',
        'l2_profile_flags': 'number',
        'foreground_context_switches': 'number',
        'background_context_switches': 'number',
        'foreground_num_read_operations': 'number',
        'foreground_num_write_operations': 'number',
        'foreground_number_of_flushes': 'number',
        'background_num_read_operations': 'number',
        'background_num_write_operations': 'number',
        'background_number_of_flushes': 'number',
        'state_transition': 'number',
        'cycle_count': 'number',
        'duration_ms': 'number',
        'span_ms': 'number',
        'cycles': 'number',
        'cycles_attr': 'number',
        'cycles_wob': 'number',
    }

    # Registry columns that store a raw number and read better rendered.
    # Separate from DISPLAY_FORMATTERS because that map is SRUM-only: a column
    # named bytes_sent means something specific in a SRUM table and nothing in
    # a registry one.
    REGISTRY_FORMATTERS = {
        'focus_time': 'focus_ms',
    }

    def format_for_display(self, col_name, value):
        """Render one cell. Falls back to str() for anything unmapped."""
        if value is None:
            return ""
        if not self._is_srum_table():
            if self.REGISTRY_FORMATTERS.get(col_name) == 'focus_ms':
                # UserAssist stores focus time as milliseconds, so the column
                # sorts and compares as a number. "2.47h" is for reading.
                try:
                    from Artifacts_Collectors.Regclaw import format_focus_time
                    return format_focus_time(int(value))
                except Exception:
                    return str(value)
            return str(value)
        kind = self.DISPLAY_FORMATTERS.get(col_name)
        if kind is None:
            return str(value)
        try:
            from Artifacts_Collectors.SRUM_Claw import (
                format_bytes, format_number, format_cpu_time,
                format_time_duration, format_charge_level,
            )
        except Exception:
            return str(value)
        try:
            return {
                'bytes': format_bytes,
                'number': format_number,
                'cpu': format_cpu_time,
                'duration': format_time_duration,
                'charge': format_charge_level,
            }[kind](value)
        except Exception:
            return str(value)

    def _is_srum_table(self):
        return str(getattr(self, 'table_name', '') or '').startswith('srum_')

    def clear_data(self):
        """Drop every row and let go of the case database.

        A new case used to leave these tables showing the previous one. The
        clear-down walked findChildren(QTableWidget) and this is a QTableView,
        so it was never found - and even when found, setRowCount(0) is not a
        method it has. The model keeps a page cache and a rowid index, and the
        widget keeps the loader, so all three have to be released or the old
        case is still on screen and still open on disk.
        """
        try:
            model = self._model
            model.cancel_pending()
            self._hide_sort_overlay()
            model.beginResetModel()
            model._clear_state()
            model.unfiltered_total = None
            model.endResetModel()
        except Exception as e:
            self.logger.warning(f"clear_data: model reset failed: {e}")
        self._load_pending = False
        self._known_row_count = None
        self._estimated_total = False
        self._count_worker = None

        self.data_loader = None
        self.total_rows = 0
        self.where_clause = None
        self.where_params = ()
        self._header_labels = None

    def set_order_by(self, order_by: Optional[str]):
        """Set the ORDER BY clause (applied on the next load)."""
        self.order_by = order_by

    def get_total_rows(self) -> int:
        return self.total_rows

    # ------------------------------------------------- navigation and search
    def select_row(self, row: int) -> bool:
        """Scroll ``row`` (a view row index) to the centre and select it."""
        self._ensure_loaded()
        if row is None or row < 0 or row >= self._model.rowCount():
            return False
        index = self._model.index(row, 0)
        self.scrollTo(index, QAbstractItemView.PositionAtCenter)
        self.selectRow(row)
        return True

    def row_for_rowid(self, rowid) -> Optional[int]:
        """The view row showing database rowid ``rowid`` (None if filtered out).

        Paged views (no rowid list) work it out from the order: arithmetic for
        plain rowid order, an index-range count otherwise - through the model's
        own read-only connection, so a search worker thread may call it.
        """
        if self._load_pending and QThread.currentThread() is self.thread():
            self._ensure_loaded()
        rowids = self._model._rowids
        if rowids is None:
            return self._model.position_of(rowid)
        cache = getattr(self._model, "_rid_index", None)
        if cache is None or cache[0] is not rowids:
            cache = (rowids, {int(r): i for i, r in enumerate(rowids)})
            self._model._rid_index = cache
        try:
            return cache[1].get(int(rowid))
        except (TypeError, ValueError):
            return None

    def select_rowid(self, rowid) -> bool:
        """Select the row holding database rowid ``rowid``."""
        return self.select_row(self.row_for_rowid(rowid))

    def search_rowids(self, text: str, limit: int = 10000,
                      start_time=None, end_time=None) -> List[int]:
        """rowids of rows with ``text`` in any column, in the view's order.

        Runs on its OWN read-only connection, so it may be called from a
        worker thread (a sqlite3 connection belongs to the thread that made
        it). Case-insensitive for ASCII, like SQLite's LIKE.
        """
        import sqlite3
        db_path = getattr(self.data_loader, "db_path", None) if self.data_loader else None
        if not db_path or not text or not self.columns:
            return []
        pattern = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        likes = " OR ".join('CAST("%s" AS TEXT) LIKE ? ESCAPE \'\\\'' % c for c in self.columns)
        where = ["(%s)" % likes]
        params = [pattern] * len(self.columns)
        if self.where_clause:
            where.append("(%s)" % self.where_clause)
            params += list(self.where_params or ())
        if self.time_column and (start_time or end_time):
            if start_time:
                where.append('"%s" >= ?' % self.time_column)
                params.append(str(start_time))
            if end_time:
                where.append('"%s" <= ?' % self.time_column)
                params.append(str(end_time))
        sql = "SELECT rowid FROM %s WHERE %s ORDER BY %s LIMIT %d" % (
            self.table_name, " AND ".join(where), self.order_by or "rowid", int(limit))
        conn = sqlite3.connect("file:%s?mode=ro" % str(db_path).replace("\\", "/"), uri=True, timeout=10)
        try:
            return [r[0] for r in conn.execute(sql, params)]
        finally:
            conn.close()

    def iter_records(self, page_size: int = 5000):
        """Every row of the current view (filter + order), as dicts, streamed.

        Its own read-only connection; nothing is held in the model's cache.
        Used by the export, which used to write only what a QTableWidget held.
        """
        import sqlite3
        db_path = getattr(self.data_loader, "db_path", None) if self.data_loader else None
        if not db_path:
            return
        cols = ", ".join('"%s"' % c for c in self.columns)
        sql = "SELECT %s FROM %s" % (cols, self.table_name)
        if self.where_clause:
            sql += " WHERE %s" % self.where_clause
        sql += " ORDER BY %s" % (self.order_by or "rowid")
        conn = sqlite3.connect("file:%s?mode=ro" % str(db_path).replace("\\", "/"), uri=True, timeout=10)
        try:
            cur = conn.execute(sql, tuple(self.where_params or ()))
            while True:
                rows = cur.fetchmany(page_size)
                if not rows:
                    break
                for r in rows:
                    yield dict(zip(self.columns, r))
        finally:
            conn.close()

    def header_labels(self) -> List[str]:
        return list(self._header_labels) if self._header_labels else list(self.columns)

    # ------------------------------------------------------ sorting, sizing
    def enable_header_sort(self, default_order: str = "rowid ASC"):
        """Click a header to sort by that column (in SQL); again to reverse.

        QTableView sorting would sort only what the lazy model has fetched, so
        the order is pushed into the rowid index instead.
        """
        self._default_order = default_order
        if self.order_by is None:
            self.order_by = default_order
        hh = self.horizontalHeader()
        hh.setSortIndicatorShown(True)
        hh.setSectionsClickable(True)
        try:
            hh.sectionClicked.disconnect(self._on_header_sort)
        except TypeError:
            pass
        hh.sectionClicked.connect(self._on_header_sort)

    def _on_header_sort(self, section: int):
        if not (0 <= section < len(self.columns)) or self.data_loader is None:
            return
        col = self.columns[section]
        prev = (self._sort_column, self._sort_desc, self.order_by)
        self._sort_desc = (not self._sort_desc) if col == self._sort_column else False
        self._sort_column = col
        self.order_by = '"%s" %s, rowid' % (col, "DESC" if self._sort_desc else "ASC")
        self.horizontalHeader().setSortIndicator(
            section, Qt.DescendingOrder if self._sort_desc else Qt.AscendingOrder)
        # The rows did not change, only their order: no second COUNT.
        state = self._model.reload(
            total_hint=None if self.where_clause else self._model.unfiltered_total)
        if state == 'pending':
            self._sort_prev = prev
            self.total_rows = self._expected_total()
        else:
            self.total_rows = self._model.rowCount()

    # ------------------------------------------- unindexed sort on a worker
    def _expected_total(self) -> int:
        n = self._model.unfiltered_total
        return int(n) if (n is not None and not self.where_clause) else self._model.rowCount()

    def _on_sort_started(self, total, worker):
        """Called by the model when a big unindexed sort goes to a worker."""
        try:
            from ui.progress_indicator import TableLoadingOverlay
            if self._sort_overlay is None:
                self._sort_overlay = TableLoadingOverlay(self)
                self._sort_overlay.cancelled.connect(self._cancel_sort)
            label = self._header_labels[self.columns.index(self._sort_column)] \
                if (self._header_labels and self._sort_column in self.columns
                    and self.columns.index(self._sort_column) < len(self._header_labels)) \
                else (self._sort_column or self.order_by or "rowid")
            self._sort_overlay.show_loading("Sorting %s rows by %s..." % (
                format(int(total or 0), ","), label))
        except Exception as e:
            self.logger.debug("sort overlay not shown: %s", e)

    def _hide_sort_overlay(self):
        if self._sort_overlay is not None:
            try:
                self._sort_overlay.hide_loading()
            except Exception:
                pass

    def _cancel_sort(self):
        self._model.cancel_pending()
        self._on_sort_finished(False, 'cancelled')

    def _on_sort_finished(self, ok, error):
        """The worker's list is in (ok), failed or was cancelled (restore the
        previous order), or superseded (ok is None: another reload follows)."""
        self._hide_sort_overlay()
        if ok is None:
            return
        if ok:
            self.total_rows = self._model.rowCount()
            self._sort_prev = None
        else:
            if error not in ('cancelled', ''):
                self.logger.warning("sort of '%s' failed: %s", self.table_name, error)
            if self._sort_prev is not None:
                self._sort_column, self._sort_desc, self.order_by = self._sort_prev
                self._sort_prev = None
                try:
                    hh = self.horizontalHeader()
                    if self._sort_column in self.columns:
                        hh.setSortIndicator(self.columns.index(self._sort_column),
                                            Qt.DescendingOrder if self._sort_desc
                                            else Qt.AscendingOrder)
                    else:
                        hh.setSortIndicator(-1, Qt.AscendingOrder)
                except Exception:
                    pass
        self.sort_finished.emit(bool(ok))

    def reset_sort(self):
        self._sort_column, self._sort_desc = None, False
        self.order_by = self._default_order
        try:
            self.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        except Exception:
            pass

    def fit_columns(self, max_col_width: int = 480, min_col_width: int = 60):
        """Fit columns to their content once, clamp them, then let the analyst drag.

        apply_table_styles leaves the header in ResizeToContents, which
        re-measures on every scroll and never lets a divider move; one long
        Event Description then pushed every other column off screen.
        """
        hh = self.horizontalHeader()
        hh.setResizeContentsPrecision(50)
        hh.setSectionResizeMode(QHeaderView.Interactive)
        self.resizeColumnsToContents()
        for i in range(len(self.columns)):
            w = hh.sectionSize(i)
            if w > max_col_width:
                hh.resizeSection(i, max_col_width)
            elif w < min_col_width:
                hh.resizeSection(i, min_col_width)
        hh.setStretchLastSection(True)

    def get_loaded_row_count(self) -> int:
        return len(self._model._cache)

    def get_selected_records(self) -> List[Dict[str, Any]]:
        """Return the full DB records for the selected rows."""
        records: List[Dict[str, Any]] = []
        try:
            rows = sorted({idx.row() for idx in self.selectionModel().selectedRows()})
            for row_index in rows:
                rec = self._model.record_at(row_index)
                if rec is not None:
                    records.append(rec)
            return records
        except Exception as e:
            self.logger.error(f"Error getting selected records: {e}")
            return []

    def _apply_styles_immediately(self):
        """Apply Crow Eye styles, keeping columns Interactive (not ResizeToContents)."""
        try:
            from styles import CrowEyeStyles
            CrowEyeStyles.apply_table_styles(self)
        except Exception as e:
            self.logger.error(f"Error applying styles: {e}")
        # apply_table_styles sets ResizeToContents (matching the other tables);
        # just cap the sampling so auto-fit stays fast on the lazy model.
        try:
            self.horizontalHeader().setResizeContentsPrecision(50)
        except Exception:
            pass

    # ------------------------------------------------------------- row detail
    def _on_double_clicked(self, index: QModelIndex):
        """Open the row-detail dialog for the double-clicked row."""
        try:
            if not index.isValid():
                return
            from ui.row_detail_dialog import RowDetailDialog

            row = index.row()
            row_data = self._model.record_at(row)
            if not row_data:
                self.logger.warning(f"No data found for row {row}")
                return

            # Determine Row Name (heuristic)
            row_name = "Unknown Row"
            name_keys = ["Name", "Filename", "Executable Name", "Process Name", "Service Name", "Device Name", "User", "Key", "app_name", "folder_name"]
            for key in name_keys:
                for data_key in row_data.keys():
                    if data_key.lower() == key.lower() and row_data[data_key]:
                        row_name = str(row_data[data_key])
                        break
                if row_name != "Unknown Row":
                    break

            # Fallback: use the first available value if no priority key found
            if row_name == "Unknown Row" and row_data:
                first_value = next(iter(row_data.values()))
                if first_value:
                    row_name = str(first_value)

            row_number = row + 1
            display_name = self.table_name.replace('_', ' ').title()

            dialog = RowDetailDialog(row_data, display_name, row_name, row_number, self.parent())
            dialog.show()

        except Exception as e:
            self.logger.error(f"Error showing row detail dialog: {e}")
            import traceback
            traceback.print_exc()

    def set_intelligence_db_path(self, case_directory: str):
        """
        Manually set the path to the intelligence database.

        Args:
            case_directory: Root directory of the case
        """
        intel_db = os.path.join(case_directory, "Crow_Intelligence.db")
        if os.path.exists(intel_db):
            super().set_intelligence_db_path(case_directory)
            self._intelligence_initialized = True
            if self.data_loader and self.data_loader.connection:
                try:
                    cursor = self.data_loader.connection.cursor()
                    self.attach_intelligence_db(cursor)
                    self.logger.info(f"Attached intelligence brain from {intel_db}")
                except Exception as e:
                    self.logger.error(f"Failed to attach intelligence: {e}")
        else:
            self.logger.warning(f"Intelligence database not found at {intel_db}")

    def _initialize_intelligence(self):
        """
        Detect Crow_Intelligence.db and set up enrichment targets.

        Searches recursively upwards from the artifact directory to find the case root
        where Crow_Intelligence.db resides.
        """
        try:
            if not (hasattr(self.data_loader, 'db_path') and self.data_loader.db_path):
                self._intelligence_initialized = True
                return

            # --- 1. Recursive Brain Discovery ---
            current_dir = os.path.dirname(str(self.data_loader.db_path))
            intel_db_path = None
            intel_case_root = None

            # Search upwards (max 5 levels for sanity) to find the case root
            for _ in range(5):
                candidate = os.path.join(current_dir, "Crow_Intelligence.db")
                if os.path.exists(candidate):
                    intel_db_path = candidate
                    intel_case_root = current_dir
                    break

                parent = os.path.dirname(current_dir)
                if parent == current_dir:  # Reached drive root
                    break
                current_dir = parent

            if not intel_db_path:
                self.logger.debug("No Crow_Intelligence.db found in recursive upward search.")
                self._intelligence_initialized = True
                return

            self.set_intelligence_db_path(intel_case_root)
            self.logger.info(f"Recursive Discovery: Found intelligence at {intel_db_path}")

            # The table knows better than the heuristic: the event logs'
            # fallback pick was EventID, whose small integers collide with
            # every numeric mapping.
            pref = self.preferred_enrichment_column
            if pref and pref in self.columns and pref not in self.ENRICHMENT_EXCLUDED_COLUMNS:
                self.enrichment_column = pref
                self._intelligence_initialized = True
                return

            # --- 2. Forensic Priority Heuristic ---
            # We prioritize identity-bearing columns because they have the highest
            # intelligence value (e.g. mapping a SID to "Admin" is better than mapping a Filename).
            priority_groups = [
                # Tier 1: Identity (Most Valuable)
                ['user_sid', 'SID', 'sid', 'security_id', 'MAC_Address', 'mac_address', 'gateway_mac', 'ip_address', 'IP_Address'],
                # Tier 2: Device/HW
                ['device_id', 'serial_number', 'volume_serial', 'volume_guid', 'instance_id'],
                # Tier 3: Process/App
                ['app_name', 'service_name', 'executable_name', 'Process Name', 'app_id', 'AppID'],
                # Tier 4: Files/Paths (Least specific, often collisions)
                ['Filename', 'file_name', 'filename', 'target_path', 'path', 'Local_Path', 'key_path']
            ]

            found_target = False
            for group in priority_groups:
                for candidate in group:
                    # Check if this priority candidate is in our table columns
                    if candidate in self.columns and candidate not in self.ENRICHMENT_EXCLUDED_COLUMNS:
                        self.enrichment_column = candidate
                        self.logger.info(f"Heuristic Match: Prioritizing Tier {priority_groups.index(group)+1} column '{candidate}'")
                        found_target = True
                        break
                if found_target:
                    break

            # Final Fallback: Set match
            if not found_target:
                for col in self.columns:
                    if col in self.ENRICHMENT_EXCLUDED_COLUMNS:
                        continue
                    if col in self.ENRICHMENT_TARGET_COLUMNS:
                        self.enrichment_column = col
                        found_target = True
                        break

            self._intelligence_initialized = True

        except Exception as e:
            self.logger.error(f"Failed to initialize intelligence brain: {e}")
            self._intelligence_initialized = True
