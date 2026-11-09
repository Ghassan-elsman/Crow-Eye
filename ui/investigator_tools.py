"""What every artifact table in the main window offers the investigator.

Crow-Eye has over a hundred and forty tables across nested tabs, built two
ways: QTableWidget tabs (setup_standard_table) and paged VirtualTableWidget
tabs. Each had what its own code gave it, so most had no way to copy rows,
filter, see a long value whole, or say how many rows were on screen, and
113 registry sub-tabs could only be reached by scrolling a tab bar.

InvestigatorTools adds, for every table, without touching how each is
built:

- a status bar: where you are ("Registry > RecentDocs"), the rows, the rows
  selected, and the table's filter;
- a filter box in that status bar (Ctrl+F) for the table on screen: a SQL
  filter on a paged table (every row, not only the loaded page), hidden rows
  on the others;
- a right-click menu: copy the cell, copy the selected rows with their
  headers, the row's details, search the value across the case (Database
  Search), filter the table by it, and choose columns;
- Ctrl+C copies the selected rows with headers (Qt copied nothing);
- the whole text of a cut-off cell as its tooltip, and a header's tooltip
  saying what kind of column it is ("a time, in UTC");
- Go to tab (Ctrl+K): type part of a tab's name, Enter opens it.

All of it lives in one application event filter and two shortcuts, so a
table created later (a re-parse swaps QTableWidgets for paged tables) is
covered without being registered.
"""

import logging

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import QEvent, Qt

logger = logging.getLogger(__name__)

# Cells longer than this are cut in the tooltip too (a Prefetch file list
# can be tens of kilobytes).
TOOLTIP_CHARS = 3000
# A paged table this large is filtered on Enter only, never as you type:
# its filter is a LIKE over every column of every row, counted before the
# first page shows (3.9 M correlated rows take tens of seconds).
LIVE_FILTER_MAX_ROWS = 300_000


def _tab_path(widget):
    """'Registry > RecentDocs': the tab texts from the top down to `widget`."""
    parts = []
    w = widget
    while w is not None:
        parent = w.parentWidget()
        tabs = parent.parentWidget() if parent is not None else None
        if isinstance(tabs, QtWidgets.QTabWidget):
            idx = tabs.indexOf(w)
            if idx >= 0:
                parts.insert(0, tabs.tabText(idx).replace("&", "").strip())
            w = tabs
        else:
            w = parent
    return " > ".join(p for p in parts if p)


def _themed(dialog):
    """The site look (ui/app_theme.py) every Crow-Eye dialog wears."""
    try:
        from ui.app_theme import apply_theme
        apply_theme(dialog)
    except Exception as e:
        logger.debug("theme not applied: %s", e)


def _status_qss():
    try:
        from ui import app_theme as t
        return (
            "QStatusBar#investigatorStatusBar { background: %(CARD)s; color: %(MUTED)s;"
            " border-top: 1px solid %(LINE)s; min-height: 30px; }"
            "QStatusBar#investigatorStatusBar::item { border: none; }"
            "QLabel#statusWhere { color: %(BODY)s; padding: 0 10px; font-size: 12px; }"
            "QLabel#statusHint { color: %(MUTED)s; padding: 0 10px; font-size: 11px; }"
            "QLineEdit#tableFilterBox { background: %(BG)s; color: %(TEXT)s;"
            " border: 1px solid %(LINE_2)s; border-radius: 6px; padding: 3px 8px;"
            " margin: 3px 4px; selection-background-color: %(INDIGO)s; }"
            "QLineEdit#tableFilterBox:focus { border: 1px solid %(INDIGO)s; }"
        ) % {"CARD": t.CARD, "MUTED": t.MUTED, "LINE": t.LINE, "LINE_2": t.LINE_2,
             "BODY": t.BODY, "BG": t.BG, "TEXT": t.TEXT, "INDIGO": t.INDIGO}
    except Exception:
        return ""


def _headers(view):
    model = view.model()
    if model is None:
        return []
    return [str(model.headerData(c, Qt.Horizontal, Qt.DisplayRole) or "")
            for c in range(model.columnCount())]


def _cell_text(index):
    value = index.data(Qt.DisplayRole) if index.isValid() else None
    return "" if value is None else str(value)


def selected_rows_tsv(view, with_headers=True):
    """The selected rows (or the current cell's row) as tab-separated text,
    visible columns only, in view order."""
    model = view.model()
    if model is None:
        return ""
    sel = view.selectionModel()
    rows = sorted({i.row() for i in sel.selectedIndexes()}) if sel is not None else []
    if not rows and view.currentIndex().isValid():
        rows = [view.currentIndex().row()]
    cols = [c for c in range(model.columnCount()) if not view.isColumnHidden(c)]
    clean = lambda s: str(s).replace("\t", " ").replace("\r", " ").replace("\n", " ")
    lines = []
    if with_headers:
        heads = _headers(view)
        lines.append("\t".join(clean(heads[c]) for c in cols))
    for r in rows:
        lines.append("\t".join(clean(_cell_text(model.index(r, c))) for c in cols))
    return "\n".join(lines)


class ColumnsDialog(QtWidgets.QDialog):
    """Show or hide a table's columns; works for any table view."""

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Columns")
        self.setMinimumWidth(360)
        layout = QtWidgets.QVBoxLayout(self)
        self.list = QtWidgets.QListWidget()
        for c, name in enumerate(_headers(view)):
            item = QtWidgets.QListWidgetItem(name or "(column %d)" % (c + 1))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked if view.isColumnHidden(c) else Qt.Checked)
            item.setData(Qt.UserRole, c)
            self.list.addItem(item)
        self.list.itemChanged.connect(
            lambda it: view.setColumnHidden(it.data(Qt.UserRole), it.checkState() != Qt.Checked))
        layout.addWidget(self.list)
        row = QtWidgets.QHBoxLayout()
        for label, state in (("Show all", Qt.Checked), ("Hide all", Qt.Unchecked)):
            b = QtWidgets.QPushButton(label)
            b.clicked.connect(lambda _c=False, s=state: [
                self.list.item(i).setCheckState(s) for i in range(self.list.count())])
            row.addWidget(b)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)
        _themed(self)


class GoToTabDialog(QtWidgets.QDialog):
    """Ctrl+K: every tab by its path, filtered as you type, Enter opens it."""

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Go to tab")
        self.setMinimumSize(520, 420)
        self.entries = entries
        self.chosen = None
        layout = QtWidgets.QVBoxLayout(self)
        self.box = QtWidgets.QLineEdit()
        self.box.setPlaceholderText("Type part of a tab's name: recentdocs, srum net, usn...")
        self.box.setClearButtonEnabled(True)
        layout.addWidget(self.box)
        self.list = QtWidgets.QListWidget()
        layout.addWidget(self.list)
        self.note = QtWidgets.QLabel("")
        self.note.setObjectName("goToTabNote")
        layout.addWidget(self.note)
        self.box.textChanged.connect(self._refill)
        self.box.returnPressed.connect(self._accept_current)
        self.list.itemActivated.connect(lambda _i: self._accept_current())
        self.box.installEventFilter(self)
        self._refill("")
        _themed(self)

    def eventFilter(self, obj, event):
        # Up and Down move through the list while typing.
        if obj is self.box and event.type() == QEvent.KeyPress and \
                event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown):
            QtWidgets.QApplication.sendEvent(self.list, event)
            return True
        return super().eventFilter(obj, event)

    @staticmethod
    def rank(path, terms):
        """None when a term is missing; else lower is better: a match at the
        start of the last part first, then shorter paths."""
        low = path.lower()
        if not all(t in low for t in terms):
            return None
        last = low.rsplit(" > ", 1)[-1]
        return (0 if terms and last.startswith(terms[0]) else 1, len(path))

    def _refill(self, text):
        terms = [t for t in text.lower().split() if t]
        # Keyed on rank and path only: two tabs can share a path, and the
        # tab widgets themselves cannot be compared.
        ranked = sorted(((r, path, target) for r, path, target in (
            (self.rank(p, terms), p, t) for p, t in self.entries) if r is not None),
            key=lambda e: (e[0], e[1].lower()))
        self.list.clear()
        for _r, path, target in ranked[:300]:
            item = QtWidgets.QListWidgetItem(path)
            item.setData(Qt.UserRole, target)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.note.setText("%d of %d tabs" % (len(ranked), len(self.entries)))

    def _accept_current(self):
        item = self.list.currentItem()
        if item is not None:
            self.chosen = item.data(Qt.UserRole)
            self.accept()


class InvestigatorTools(QtCore.QObject):
    """Installed once on the main window (Ui_Crow_Eye.setupUi)."""

    def __init__(self, ui, main_window):
        super().__init__(main_window)
        self.ui = ui
        self.main_window = main_window
        self._filters = {}                 # id(view) -> filter text
        self._last_view = None
        self._case = None                  # case root the tab memory is for
        self._restored = True              # nothing to restore before a case
        self._opened_at = None             # the tab shown when the case opened
        self.settings = QtCore.QSettings("CrowEye", "InvestigatorTools")

    # ------------------------------------------------------------- install
    def install(self):
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self._build_status_bar()
        for keys, slot in (("Ctrl+K", self.go_to_tab), ("Ctrl+F", self.focus_filter),
                           ("Ctrl+T", self.open_timeline), ("Ctrl+/", self.show_shortcuts),
                           ("F1", self.show_shortcuts)):
            sc = QtWidgets.QShortcut(QtGui.QKeySequence(keys), self.main_window)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(slot)
        # Where the investigator is changes on any tab switch, selection or
        # focus; the bar follows once a beat rather than on every event.
        self._tick = QtCore.QTimer(self)
        self._tick.setSingleShot(True)
        self._tick.setInterval(150)
        self._tick.timeout.connect(self.refresh_status)
        if app is not None:
            # A bound slot, not a lambda: Qt drops it with this object, where a
            # lambda went on firing into a deleted timer.
            app.focusChanged.connect(self._focus_changed)
        self._poll = QtCore.QTimer(self)
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self.refresh_status)
        self._poll.start()
        return self

    @QtCore.pyqtSlot("QWidget*", "QWidget*")
    def _focus_changed(self, _old, _new):
        try:
            self._tick.start()
        except RuntimeError:
            pass

    def _build_status_bar(self):
        bar = self.main_window.statusBar() if hasattr(self.main_window, "statusBar") else None
        if bar is None:
            self.status_bar = self.where = self.filter_box = None
            return
        bar.setObjectName("investigatorStatusBar")
        bar.setSizeGripEnabled(False)
        bar.setStyleSheet(_status_qss())
        self.status_bar = bar
        self.where = QtWidgets.QLabel("")
        self.where.setObjectName("statusWhere")
        self.where.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bar.addWidget(self.where, 1)
        self.filter_box = QtWidgets.QLineEdit()
        self.filter_box.setObjectName("tableFilterBox")
        self.filter_box.setPlaceholderText("Filter this table (Ctrl+F)")
        self.filter_box.setClearButtonEnabled(True)
        self.filter_box.setMinimumWidth(260)
        self.filter_box.setToolTip(
            "Shows only the rows of the table on screen that contain this text in any "
            "column. On the large paged tables every row is searched, not only the "
            "rows already loaded. Each table keeps its own filter.")
        bar.addPermanentWidget(self.filter_box)
        hint = QtWidgets.QLabel("Ctrl+K go to tab   ·   F1 shortcuts")
        hint.setObjectName("statusHint")
        bar.addPermanentWidget(hint)
        self._filter_timer = QtCore.QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(350)
        self._filter_timer.timeout.connect(self._apply_filter_now)
        self.filter_box.textEdited.connect(lambda _t: self._filter_timer.start())
        self.filter_box.returnPressed.connect(lambda: self._apply_filter_now(explicit=True))

    # ------------------------------------------------------- the current table
    def _is_ours(self, view):
        try:
            return isinstance(view, QtWidgets.QTableView) and view.window() is self.main_window
        except RuntimeError:
            return False

    def current_view(self):
        """The table the investigator is looking at: the focused one, else the
        largest table shown in the main window."""
        focus = QtWidgets.QApplication.focusWidget()
        w = focus
        while w is not None and not isinstance(w, QtWidgets.QTableView):
            w = w.parentWidget()
        if w is not None and self._is_ours(w) and w.isVisible():
            return w
        best, area = None, 0
        for view in self.main_window.findChildren(QtWidgets.QTableView):
            try:
                if not view.isVisible() or view.window() is not self.main_window:
                    continue
                a = view.width() * view.height()
            except RuntimeError:
                continue
            if a > area:
                best, area = view, a
        return best

    @staticmethod
    def _total(view):
        try:
            if hasattr(view, "get_total_rows"):
                return int(view.get_total_rows() or 0)
            model = view.model()
            if isinstance(view, QtWidgets.QTableWidget):
                return sum(1 for r in range(view.rowCount()) if not view.isRowHidden(r))
            return model.rowCount() if model is not None else 0
        except Exception:
            return 0

    # ------------------------------------------------------- show a row
    def table_view_for(self, table, db_name=None):
        """The main-window table showing database table `table`, or None.

        utils/table_sources first (every GUI table -> its database and table,
        the map "Why empty?" uses), then Database Search's map, then the
        `<table>_table` naming most tabs follow."""
        import os
        attrs = []
        try:
            sources = self.ui._table_sources() if hasattr(self.ui, "_table_sources") else {}
        except Exception:
            sources = {}
        want_db = os.path.basename(str(db_name)).lower() if db_name else None
        for attr, (_art, db, tbl) in sources.items():
            if str(tbl).lower() == str(table).lower() and \
                    (want_db is None or str(db).lower() == want_db):
                attrs.append(attr)
        nav = getattr(self.ui, "db_search_integration", None)
        mapping = getattr(nav, "table_mapping", None) or {}
        entry = mapping.get(str(table).lower())
        attrs += ([entry[1]] if entry and len(entry) > 1 else []) + ["%s_table" % table]
        for attr in attrs:
            view = getattr(self.ui, attr, None)
            try:
                if isinstance(view, QtWidgets.QTableView) and view.window() is self.main_window:
                    return view
            except RuntimeError:
                continue
        return None

    def _record(self, db_name, table, rowid):
        """Every column of one row, read from the case's own database."""
        import os
        import re
        import sqlite3
        paths = getattr(self.ui, "case_paths", None) or {}
        base = paths.get("artifacts_dir") if isinstance(paths, dict) else None
        if not base or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(table)):
            return None
        path = os.path.join(base, os.path.basename(str(db_name)))
        if not os.path.isfile(path):
            return None
        try:
            from urllib.request import pathname2url
            conn = sqlite3.connect("file:%s?mode=ro" % pathname2url(path), uri=True)
            try:
                cur = conn.execute('SELECT * FROM "%s" WHERE rowid = ?' % table, (int(rowid),))
                row = cur.fetchone()
                return dict(zip([d[0] for d in cur.description], row)) if row else None
            finally:
                conn.close()
        except (sqlite3.Error, TypeError, ValueError):
            return None

    @staticmethod
    def _match_row(view, record):
        """The view row showing `record`: the one whose cells hold the most of
        its values (an ordinary table keeps no rowid). Needs two matching
        cells, or one when the record has a single usable value."""
        values = {str(v).strip() for v in (record or {}).values()
                  if v is not None and len(str(v).strip()) >= 3}
        if not values:
            return None
        model = view.model()
        rows, cols = model.rowCount(), model.columnCount()
        best, score = None, 0
        for r in range(rows):
            s = 0
            for c in range(cols):
                d = model.index(r, c).data()
                if d is not None and str(d).strip() in values:
                    s += 1
            if s > score:
                best, score = r, s
        return best if score >= min(2, len(values)) else None

    def show_row(self, db_name, table, rowid):
        """Open the tab holding `table` and select row `rowid` in it.
        Returns (ok, message): the message says why when it could not."""
        view = self.table_view_for(table, db_name)
        if view is None:
            return False, "No tab in the main window shows %s." % table
        self.open_tab((None, view))
        if self._filters.get(id(view)):
            self.filter_view(view, "")       # the row may be the one filtered out
        if hasattr(view, "select_rowid"):
            try:
                if view.select_rowid(int(rowid)):
                    view.setFocus()
                    return True, ""
            except (TypeError, ValueError):
                pass
            return False, ("The row is in the case but not in this table's current "
                           "view; a time filter or search on the table may hide it.")
        if view.model() is None or view.model().rowCount() == 0:
            return False, "The %s tab has no rows loaded yet." % _tab_path(view)
        row = self._match_row(view, self._record(db_name, table, rowid))
        if row is None:
            return False, "The row was not found among the rows loaded in %s." % _tab_path(view)
        if isinstance(view, QtWidgets.QTableWidget) and view.isRowHidden(row):
            view.setRowHidden(row, False)
        view.clearSelection()
        view.selectRow(row)
        view.scrollTo(view.model().index(row, 0), QtWidgets.QAbstractItemView.PositionAtCenter)
        view.setFocus()
        self.refresh_status()
        return True, ""

    # ------------------------------------------------------- last tab per case
    def _case_root(self):
        paths = getattr(self.ui, "case_paths", None)
        return paths.get("case_root") if isinstance(paths, dict) else None

    def _settings_key(self, root):
        import hashlib
        norm = str(root).replace("/", "\\").rstrip("\\").lower()
        return "last_tab/" + hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]

    def current_tab_path(self):
        """The deepest tab shown in the main window: 'Registry > RecentDocs'."""
        best = ""
        for path, (tabs, page) in self.tab_entries():
            try:
                if tabs.currentWidget() is page and page.isVisible() and \
                        len(path) > len(best):
                    best = path
            except RuntimeError:
                continue
        return best

    def _follow_case(self):
        """A new case: restore the tab the investigator last had open in it,
        once the case has loaded, unless they have already moved."""
        root = self._case_root()
        if root == self._case:
            return
        self._case = root
        self._saved_path = None
        self._restored = not root
        if not root:
            return
        self._opened_at = self.current_tab_path()
        try:
            from ui import busy_guard
            busy_guard.when_idle("restore last tab", self.restore_last_tab)
        except Exception:
            QtCore.QTimer.singleShot(0, self.restore_last_tab)

    def forget_case(self):
        """The case is being cleared (open/new case): the next one, even the
        same folder again, restores its last tab once it has loaded."""
        self._case = None
        self._restored = False

    def restore_last_tab(self):
        self._restored = True
        if not self._case:
            return False
        saved = self.settings.value(self._settings_key(self._case), "", type=str)
        if not saved or self.current_tab_path() != self._opened_at:
            return False                  # nothing saved, or they moved already
        for path, target in self.tab_entries():
            if path == saved:
                try:
                    self.open_tab(target)
                    return True
                except RuntimeError:
                    return False
        return False

    def _remember_tab(self):
        if self._case and self._restored:
            path = self.current_tab_path()
            if path and path != getattr(self, "_saved_path", None):
                self._saved_path = path
                self.settings.setValue(self._settings_key(self._case), path)

    # ------------------------------------------------------------ shortcuts
    def open_timeline(self):
        opener = getattr(self.ui, "open_timeline_dialog", None)
        if callable(opener):
            opener()

    SHORTCUTS = (
        ("Ctrl+K", "Go to any tab by name"),
        ("Ctrl+F", "Filter the table on screen"),
        ("Ctrl+C", "Copy the selected rows, with headers"),
        ("Right-click", "Copy, row details, search the case, filter, columns"),
        ("Ctrl+T", "Timeline"),
        ("Ctrl+Shift+F", "Database Search (the whole case)"),
        ("Ctrl+Shift+B", "User Behavior Analytics"),
        ("Ctrl+Shift+E", "Eye"),
        ("Ctrl+,", "Settings"),
        ("Ctrl+L", "Logs"),
        ("F1  or  Ctrl+/", "This list"),
    )

    def show_shortcuts(self):
        dlg = QtWidgets.QDialog(self.main_window)
        dlg.setWindowTitle("Keyboard shortcuts")
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.setContentsMargins(18, 16, 18, 14)
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        for r, (keys, what) in enumerate(self.SHORTCUTS):
            k = QtWidgets.QLabel(keys)
            k.setObjectName("shortcutKeys")
            k.setStyleSheet("font-weight: 600;")
            grid.addWidget(k, r, 0)
            grid.addWidget(QtWidgets.QLabel(what), r, 1)
        lay.addLayout(grid)
        row = QtWidgets.QHBoxLayout()
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(dlg.accept)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        _themed(dlg)
        self._shortcuts_dialog = dlg
        dlg.show()
        return dlg

    def refresh_status(self):
        self._follow_case()
        if self._restored:
            self._remember_tab()
        if self.where is None:
            return
        view = self.current_view()
        if view is not self._last_view:
            self._last_view = view
            if self.filter_box is not None and not self.filter_box.hasFocus():
                self.filter_box.setText(self._filters.get(id(view), "") if view else "")
        if view is None:
            self.where.setText("")
            return
        sel = view.selectionModel()
        selected = len({i.row() for i in sel.selectedIndexes()}) if sel is not None else 0
        total = self._total(view)
        parts = [_tab_path(view) or (view.objectName() or "Table"),
                 "%s row%s" % (format(total, ","), "" if total == 1 else "s")]
        if selected:
            parts.append("%s selected" % format(selected, ","))
        text = self._filters.get(id(view))
        if text:
            parts.append('filtered by "%s"' % text)
        self.where.setText("   ·   ".join(parts))

    # ------------------------------------------------------------ filtering
    def focus_filter(self):
        if self.filter_box is not None:
            self.filter_box.setFocus()
            self.filter_box.selectAll()

    def filter_view(self, view, text, explicit=True):
        """Show only the rows of `view` containing `text` in any column.
        `explicit`: asked for (Enter, the menu), not a pause while typing; a
        large paged table is filtered only then."""
        text = (text or "").strip()
        if view is None:
            return
        if hasattr(view, "apply_filter") and hasattr(view, "columns"):
            big = self._total(view) > LIVE_FILTER_MAX_ROWS or \
                int(getattr(view, "_inv_unfiltered", 0) or 0) > LIVE_FILTER_MAX_ROWS
            if big and not explicit:
                if self.where is not None:
                    self.where.setText("%s   \u00b7   press Enter to filter all %s rows" % (
                        _tab_path(view) or "Table", format(self._total(view), ",")))
                return
            if id(view) not in self._filters:
                view._inv_unfiltered = self._total(view)
            if big:
                QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
                if self.where is not None:
                    self.where.setText("Filtering %s rows..." % format(self._total(view), ","))
                    self.where.repaint()
            # A paged table: the filter is SQL over every row. Its own WHERE
            # (a time window set by another feature) is left alone.
            if getattr(view, "where_clause", None) and id(view) not in self._filters:
                return
            if text:
                cols = list(getattr(view, "columns", []) or [])
                if not cols:
                    return
                like = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                where = " OR ".join('CAST("%s" AS TEXT) LIKE ? ESCAPE \'\\\'' % c.replace('"', '""')
                                    for c in cols)
                try:
                    view.apply_filter("(%s)" % where, tuple([like] * len(cols)))
                finally:
                    if big:
                        QtWidgets.QApplication.restoreOverrideCursor()
                self._filters[id(view)] = text
            else:
                try:
                    if id(view) in self._filters:
                        view.clear_filter()
                finally:
                    if big:
                        QtWidgets.QApplication.restoreOverrideCursor()
                self._filters.pop(id(view), None)
        elif isinstance(view, QtWidgets.QTableWidget):
            needle = text.lower()
            cols = view.columnCount()
            view.setUpdatesEnabled(False)
            try:
                for r in range(view.rowCount()):
                    if not needle:
                        view.setRowHidden(r, False)
                        continue
                    hit = False
                    for c in range(cols):
                        item = view.item(r, c)
                        if item is not None and needle in item.text().lower():
                            hit = True
                            break
                    view.setRowHidden(r, not hit)
            finally:
                view.setUpdatesEnabled(True)
            if text:
                self._filters[id(view)] = text
            else:
                self._filters.pop(id(view), None)
        self.refresh_status()

    def _apply_filter_now(self, explicit=False):
        if self.filter_box is not None:
            self.filter_view(self._last_view or self.current_view(), self.filter_box.text(),
                             explicit=explicit)

    # ------------------------------------------------------------ go to tab
    def tab_entries(self):
        """[(path, (tabwidget, page))] for every tab in the main window."""
        out = []
        for tabs in self.main_window.findChildren(QtWidgets.QTabWidget):
            try:
                if tabs.window() is not self.main_window:
                    continue
                for i in range(tabs.count()):
                    page = tabs.widget(i)
                    path = _tab_path(page)
                    if path:
                        out.append((path, (tabs, page)))
            except RuntimeError:
                continue
        out.sort(key=lambda e: e[0].lower())
        return out

    @staticmethod
    def open_tab(target):
        """Select `page` in its tab widget and every tab widget above it."""
        tabs, page = target
        chain = []
        w = page
        while w is not None:
            parent = w.parentWidget()
            t = parent.parentWidget() if parent is not None else None
            if isinstance(t, QtWidgets.QTabWidget) and t.indexOf(w) >= 0:
                chain.append((t, w))
                w = t
            else:
                w = parent
        for t, p in reversed(chain):
            t.setCurrentWidget(p)

    def go_to_tab(self):
        dlg = GoToTabDialog(self.tab_entries(), self.main_window)
        if dlg.exec_() == QtWidgets.QDialog.Accepted and dlg.chosen is not None:
            try:
                self.open_tab(dlg.chosen)
            except RuntimeError:
                pass
            self.refresh_status()

    # ----------------------------------------------------------- the menu
    def _menu_for(self, view, pos):
        index = view.indexAt(pos)
        value = _cell_text(index)
        menu = QtWidgets.QMenu(view)
        a = menu.addAction("Copy cell")
        a.setEnabled(bool(index.isValid()))
        a.triggered.connect(lambda: QtWidgets.QApplication.clipboard().setText(value))
        menu.addAction("Copy selected rows (with headers)").triggered.connect(
            lambda: QtWidgets.QApplication.clipboard().setText(selected_rows_tsv(view)))
        details = menu.addAction("Row details...")
        details.setEnabled(bool(index.isValid()))
        details.triggered.connect(lambda: self.show_details(view, index))
        menu.addSeparator()
        short = value if len(value) <= 40 else value[:37] + "..."
        search = menu.addAction('Search the case for "%s"' % short if value else "Search the case")
        search.setEnabled(bool(value))
        search.triggered.connect(lambda: self.search_case(value))
        filt = menu.addAction('Filter this table by "%s"' % short if value else "Filter this table")
        filt.setEnabled(bool(value))
        filt.triggered.connect(lambda: self._set_filter(view, value))
        if self._filters.get(id(view)):
            menu.addAction("Clear this table's filter").triggered.connect(
                lambda: self._set_filter(view, ""))
        menu.addSeparator()
        menu.addAction("Columns...").triggered.connect(
            lambda: ColumnsDialog(view, self.main_window).exec_())
        return menu

    def _header_menu(self, view):
        menu = QtWidgets.QMenu(view)
        menu.addAction("Columns...").triggered.connect(
            lambda: ColumnsDialog(view, self.main_window).exec_())
        menu.addAction("Fit columns to their contents").triggered.connect(
            view.resizeColumnsToContents)
        return menu

    def _set_filter(self, view, text):
        self._last_view = view
        if self.filter_box is not None:
            self.filter_box.setText(text)
        self.filter_view(view, text)

    def show_details(self, view, index):
        if not index.isValid():
            return
        try:
            if hasattr(view, "_on_double_clicked"):
                view._on_double_clicked(index)
                return
            if isinstance(view, QtWidgets.QTableWidget):
                item = view.item(index.row(), index.column())
                if item is None:
                    item = QtWidgets.QTableWidgetItem("")
                    view.setItem(index.row(), index.column(), item)
                from ui.row_detail_dialog_handler import handle_table_double_click
                handle_table_double_click(self.main_window, item)
        except Exception as e:
            logger.warning("Row details not shown: %s", e)

    def search_case(self, value):
        """Database Search over the whole case, with the value in its box."""
        try:
            self.ui._show_database_search()
            integ = getattr(self.ui, "db_search_integration", None)
            dlg = getattr(integ, "search_dialog", None)
            box = getattr(dlg, "search_input", None)
            if box is not None:
                box.setText(value)
                box.setFocus()
        except Exception as e:
            logger.warning("Database Search not opened: %s", e)

    # ------------------------------------------------------- event filter
    def eventFilter(self, obj, event):
        try:
            et = event.type()
            if et not in (QEvent.ContextMenu, QEvent.ToolTip, QEvent.KeyPress):
                return False
            parent = obj.parentWidget() if isinstance(obj, QtWidgets.QWidget) else None
            if et == QEvent.KeyPress:
                if isinstance(obj, QtWidgets.QTableView) and self._is_ours(obj) \
                        and event.matches(QtGui.QKeySequence.Copy):
                    QtWidgets.QApplication.clipboard().setText(selected_rows_tsv(obj))
                    return True
                return False
            # A header: its own menu and what kind of column it is.
            if isinstance(obj, QtWidgets.QHeaderView) or isinstance(parent, QtWidgets.QHeaderView):
                header = obj if isinstance(obj, QtWidgets.QHeaderView) else parent
                view = header.parentWidget()
                if not (self._is_ours(view) and header.orientation() == Qt.Horizontal):
                    return False
                if et == QEvent.ContextMenu:
                    self._header_menu(view).exec_(event.globalPos())
                    return True
                return self._header_tooltip(view, header, event)
            # A cell.
            if isinstance(parent, QtWidgets.QTableView) and obj is parent.viewport() \
                    and self._is_ours(parent):
                if et == QEvent.ContextMenu:
                    self._menu_for(parent, event.pos()).exec_(event.globalPos())
                    return True
                return self._cell_tooltip(parent, event)
        except RuntimeError:
            return False
        except Exception as e:  # never let a menu break a table
            logger.debug("investigator tools: %s", e)
        return False

    @staticmethod
    def _cell_tooltip(view, event):
        index = view.indexAt(event.pos())
        if not index.isValid():
            return False
        if index.data(Qt.ToolTipRole):
            return False                       # the table says something itself
        text = _cell_text(index)
        if not text:
            return False
        width = view.columnWidth(index.column()) - 10
        if "\n" not in text and view.fontMetrics().horizontalAdvance(text) <= width:
            return False
        if len(text) > TOOLTIP_CHARS:
            text = text[:TOOLTIP_CHARS] + " ..."
        QtWidgets.QToolTip.showText(event.globalPos(), text, view.viewport())
        return True

    @staticmethod
    def _header_tooltip(view, header, event):
        section = header.logicalIndexAt(event.pos())
        if section < 0:
            return False
        model = view.model()
        label = str(model.headerData(section, Qt.Horizontal, Qt.DisplayRole) or "")
        if model.headerData(section, Qt.Horizontal, Qt.ToolTipRole):
            return False
        kind = None
        try:
            from ui.column_colors import classify_column
            kind = classify_column(label)
            if kind is None and hasattr(view, "columns") and section < len(view.columns):
                kind = classify_column(view.columns[section])
        except Exception:
            kind = None
        words = {
            "time": "A time, in UTC.",
            "parsed": "When Crow-Eye parsed this row (UTC), not when anything happened.",
            "path": "A path.",
        }.get(kind, "")
        tip = label + ("\n" + words if words else "")
        if header.sectionsClickable():
            tip += "\nClick to sort; again to reverse."
        tip += "\nRight-click: choose columns."
        QtWidgets.QToolTip.showText(event.globalPos(), tip, header)
        return True
