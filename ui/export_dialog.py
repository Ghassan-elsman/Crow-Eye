"""Export: which tables, in which format, to which folder.

The side menu's Export used to ask only for a folder and then write every table twice, JSON and
CSV, from a hard-coded list of 43 tables that had stopped growing with the tabs (no MFT/USN, SRUM,
Browser, Recycle Bin or the newer Registry tables). This dialog asks first:

  * the format: CSV, JSON, both, or an HTML report (one page per table and an index);
  * the tables: every table under the main tabs, found by walking them, grouped by tab, with its
    row count; tables with rows are ticked, empty ones are listed greyed;
  * the folder.

Paged tables (VirtualTableWidget) hold only the rows on screen, so they are streamed from their
database, every row in the view's order. Folder names and the summary use UTC (utils/time_utils).

The writing runs on a worker thread (2026-11-01: it ran on the GUI thread behind a plain progress
dialog, kept alive by processEvents). Each table is frozen on the GUI thread first - a
QTableWidget's rows copied out, a paged table's database and query - so the worker never reads a
Qt object. ExportWindow shows Crow-Eye's loading screen while it writes and turns into the result
card (open the report or the folder) when it is done; Crow-Eye stays usable throughout.
"""
import csv
import html
import json
import os
import re

from PyQt5 import QtCore, QtWidgets

try:
    from ui import app_theme as _theme
except Exception:                                         # pragma: no cover
    _theme = None
from ui.loading_panel import LoadingPanel, STEP_PREFIX

FORMATS = (("csv", "CSV", "One .csv per table: opens in Excel and Timeline Explorer."),
           ("json", "JSON", "One .json per table: an array of rows keyed by column."),
           ("both", "CSV and JSON", "Both, in CSV\\ and JSON\\ folders."),
           ("html", "HTML report", "One page per table and an index, readable in any browser."))


# ------------------------------------------------------------------ discovery
def _tab_chain(widget, stop):
    """The tab labels from `stop` (the main tab widget) down to `widget`."""
    chain = []
    w = widget
    while w is not None and w is not stop:
        parent = w.parentWidget()
        if isinstance(parent, QtWidgets.QStackedWidget) and isinstance(parent.parentWidget(), QtWidgets.QTabWidget):
            tabs = parent.parentWidget()
            i = tabs.indexOf(w)
            if i >= 0:
                chain.append(tabs.tabText(i).replace("&", "").strip())
            if tabs is stop:
                break
        w = parent
    return list(reversed(chain))


def _is_virtual(widget):
    return hasattr(widget, "iter_records") and hasattr(widget, "get_total_rows")


def row_count(widget):
    try:
        return widget.get_total_rows() if _is_virtual(widget) else widget.rowCount()
    except Exception:
        return 0


def discover_tables(main_tab, ui=None):
    """[(group, name, widget)] for every table under the main tabs, in tab order.

    A table the GUI replaced (MFT/USN swap their QTableWidget for a paged table and
    deleteLater the old one, which lingers until the event loop runs) is skipped: its
    ui attribute now names the replacement."""
    found, seen_names = [], set()
    for i in range(main_tab.count()):
        page = main_tab.widget(i)
        if page is None:
            continue
        group = main_tab.tabText(i).replace("&", "").strip()
        widgets = page.findChildren(QtWidgets.QTableWidget) + [
            v for v in page.findChildren(QtWidgets.QTableView) if _is_virtual(v)]
        for w in widgets:
            name_attr = w.objectName()
            if ui is not None and name_attr and getattr(ui, name_attr, w) is not w:
                continue
            chain = _tab_chain(w, main_tab)[1:] or [group]
            name = " - ".join(chain)
            # Two tabs can share a label (Registry has two "USB Devices"): the
            # table's own name tells them apart.
            own = re.sub(r"_table$", "", name_attr or "")
            if name in seen_names and own and "%s (%s)" % (name, own) not in seen_names:
                name = "%s (%s)" % (name, own)
            if name in seen_names:
                n = 2
                while "%s (%d)" % (name, n) in seen_names:
                    n += 1
                name = "%s (%d)" % (name, n)
            seen_names.add(name)
            found.append((group, name, w))
    return found


# ------------------------------------------------------------------ rows
def table_rows(widget):
    """(labels, row iterator) for a QTableWidget or a paged VirtualTableWidget (GUI thread)."""
    src = freeze(widget)
    return src["labels"], source_rows(src)


def freeze(widget):
    """What the export worker needs from a table, taken on the GUI thread.

    A QTableWidget's cells are Qt objects that only the GUI thread may read, so its rows are
    copied out here. A paged table (VirtualTableWidget) gives its database, query and order,
    and the worker reads them with its own connection - every row, not the page on screen."""
    if _is_virtual(widget):
        loader = getattr(widget, "data_loader", None)
        db_path = getattr(loader, "db_path", None) if loader else None
        columns = list(widget.columns)
        sql = None
        if db_path:
            sql = "SELECT %s FROM %s" % (", ".join('"%s"' % c for c in columns), widget.table_name)
            if widget.where_clause:
                sql += " WHERE %s" % widget.where_clause
            sql += " ORDER BY %s" % (widget.order_by or "rowid")
        return {"labels": widget.header_labels(), "db": str(db_path) if db_path else None, "sql": sql,
                "params": tuple(widget.where_params or ()), "total": row_count(widget)}
    labels = []
    for c in range(widget.columnCount()):
        item = widget.horizontalHeaderItem(c)
        labels.append(item.text() if item is not None else "Column %d" % (c + 1))
    rows = []
    cols = widget.columnCount()
    for r in range(widget.rowCount()):
        out = []
        for c in range(cols):
            item = widget.item(r, c)
            out.append(item.text() if item is not None else "")
        rows.append(out)
    return {"labels": labels, "rows": rows, "total": len(rows)}


def source_rows(src):
    """The rows of a frozen source; safe on any thread."""
    if "rows" in src:
        for row in src["rows"]:
            yield row
        return
    if not src.get("sql"):
        return
    import sqlite3
    conn = sqlite3.connect("file:%s?mode=ro" % src["db"].replace("\\", "/"), uri=True, timeout=10)
    try:
        cur = conn.execute(src["sql"], src.get("params") or ())
        while True:
            chunk = cur.fetchmany(5000)
            if not chunk:
                break
            for r in chunk:
                yield ["" if v is None else v for v in r]
    finally:
        conn.close()


def safe_name(name):
    return re.sub(r'[<>:"/\\|?*\s]+', "_", name).strip("_.") or "table"


class Stopped(Exception):
    """The investigator pressed Stop; the table being written is left incomplete and listed so."""


# The report's look: crow-eye.com's palette (dark ground, cyan and indigo accents), one header
# card per page, sticky column headings, zebra rows.
HTML_HEAD = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>%(title)s</title><style>
:root{--bg:#0B1220;--card:#111A2C;--line:#24324A;--text:#E2E8F0;--muted:#94A3B8;--cyan:#22D3EE;--indigo:#818CF8;--ok:#4ADE80;--warn:#FBBF24}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--text);font:13px/1.5 "Segoe UI",system-ui,sans-serif;margin:0;padding:24px}
a{color:var(--cyan);text-decoration:none} a:hover{text-decoration:underline}
.head{background:linear-gradient(135deg,#111A2C,#0F1730);border:1px solid var(--line);border-top:3px solid var(--cyan);
      border-radius:12px;padding:18px 22px;margin:0 0 18px}
.brand{color:var(--cyan);font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;margin:0 0 4px}
h1{font-size:22px;margin:0 0 8px;color:#F8FAFC}
.facts{display:flex;flex-wrap:wrap;gap:8px 22px;color:var(--muted);margin:0}
.facts b{color:var(--text);font-weight:600}
.back{display:inline-block;margin:0 0 10px}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%%}
th{position:sticky;top:0;background:var(--card);color:var(--muted);text-align:left;font-weight:600;
   padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:6px 10px;border-bottom:1px solid #182235;vertical-align:top;word-break:break-word}
tr:nth-child(even) td{background:#0E1626} tr:hover td{background:#13203A}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.failed{color:var(--warn)}
.foot{color:var(--muted);font-size:12px;margin:16px 0 0}
</style></head><body>"""


def _head_card(title, facts):
    return ('<div class="head"><p class="brand">Crow-Eye Forensics Engine</p><h1>%s</h1><p class="facts">%s</p></div>'
            % (html.escape(title), "".join("<span>%s <b>%s</b></span>" % (html.escape(k), html.escape(str(v)))
                                           for k, v in facts)))


def write_table(src, base_path, fmt, on_rows=None, cancelled=None):
    """Write one frozen table; returns (files written, rows). Raises Stopped on Stop."""
    labels, rows = src["labels"], source_rows(src)
    files, n = 0, 0
    csv_f = json_f = html_f = None
    try:
        if fmt in ("csv", "both"):
            csv_f = open(base_path["csv"], "w", encoding="utf-8-sig", newline="")
            cw = csv.writer(csv_f)
            cw.writerow(labels)
        if fmt in ("json", "both"):
            json_f = open(base_path["json"], "w", encoding="utf-8")
            json_f.write("[\n")
        if fmt == "html":
            html_f = open(base_path["html"], "w", encoding="utf-8")
            html_f.write(HTML_HEAD % {"title": html.escape(base_path["title"])})
            html_f.write('<a class="back" href="index.html">&larr; All tables</a>')
            html_f.write(_head_card(base_path["title"], base_path.get("facts") or []))
            html_f.write('<div class="wrap"><table><thead><tr>%s</tr></thead><tbody>\n'
                         % "".join("<th>%s</th>" % html.escape(str(l)) for l in labels))
        for row in rows:
            if csv_f:
                cw.writerow(row)
            if json_f:
                json_f.write(("" if n == 0 else ",\n")
                             + json.dumps(dict(zip(labels, row)), ensure_ascii=False, default=str))
            if html_f:
                html_f.write("<tr>%s</tr>\n" % "".join("<td>%s</td>" % html.escape(str(v)) for v in row))
            n += 1
            if n % 2000 == 0:
                if cancelled is not None and cancelled():
                    raise Stopped("stopped after %d rows" % n)
                if on_rows is not None:
                    on_rows(n)
        if json_f:
            json_f.write("\n]\n")
        if html_f:
            html_f.write("</tbody></table></div><p class=\"foot\">%s rows</p></body></html>\n" % "{:,}".format(n))
        files = sum(1 for f in (csv_f, json_f, html_f) if f)
    finally:
        for f in (csv_f, json_f, html_f):
            if f:
                f.close()
    return files, n


# ------------------------------------------------------------------ dialog
class ExportDialog(QtWidgets.QDialog):
    def __init__(self, tables, parent=None, start_dir=""):
        super().__init__(parent)
        self.setWindowTitle("Export tables")
        self.setMinimumSize(640, 600)
        if _theme is not None:
            _theme.begin_theme(self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        title = QtWidgets.QLabel("Export tables")
        intro = QtWidgets.QLabel("Choose the format, the tables and the folder. Every row of a "
                                 "table is written, not only the rows on screen.")
        intro.setWordWrap(True)
        if _theme is not None:
            _theme.set_role(title, "title")
            _theme.set_role(intro, "muted")
        layout.addWidget(title)
        layout.addWidget(intro)

        fmt_box = QtWidgets.QGroupBox("Format")
        fmt_layout = QtWidgets.QGridLayout(fmt_box)
        fmt_layout.setHorizontalSpacing(18)
        self._formats = QtWidgets.QButtonGroup(self)
        for i, (key, label, help_text) in enumerate(FORMATS):
            radio = QtWidgets.QRadioButton(label)
            radio.setToolTip(help_text)
            radio.setProperty("fmt", key)
            radio.setChecked(i == 0)
            self._formats.addButton(radio)
            fmt_layout.addWidget(radio, i // 2, i % 2)
        self.fmt_help = QtWidgets.QLabel(FORMATS[0][2])
        self.fmt_help.setWordWrap(True)
        if _theme is not None:
            _theme.set_role(self.fmt_help, "muted")
        fmt_layout.addWidget(self.fmt_help, 2, 0, 1, 2)
        self._formats.buttonToggled.connect(
            lambda b, on: on and self.fmt_help.setText(dict((k, h) for k, _l, h in FORMATS)[b.property("fmt")]))
        layout.addWidget(fmt_box)

        tables_box = QtWidgets.QGroupBox("Tables")
        tables_layout = QtWidgets.QVBoxLayout(tables_box)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Table", "Rows"])
        self.tree.setRootIsDecorated(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        groups = {}
        for group, name, widget in tables:
            parent_item = groups.get(group)
            if parent_item is None:
                # A heading, not a choice: Qt draws an auto-tristate parent's box only
                # once a child has changed, so some groups had one and some did not.
                parent_item = QtWidgets.QTreeWidgetItem(self.tree, [group, ""])
                parent_item.setFlags(QtCore.Qt.ItemIsEnabled)
                groups[group] = parent_item
            rows = row_count(widget)
            item = QtWidgets.QTreeWidgetItem(parent_item, [name, "{:,}".format(rows)])
            item.setData(0, QtCore.Qt.UserRole, (name, widget))
            item.setTextAlignment(1, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            if rows:
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(0, QtCore.Qt.Checked)
            else:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEnabled)
                item.setToolTip(0, "Empty: nothing to export")
                item.setData(0, QtCore.Qt.UserRole + 1, "empty")
        for parent_item in groups.values():
            if not any(parent_item.child(i).flags() & QtCore.Qt.ItemIsEnabled
                       for i in range(parent_item.childCount())):
                parent_item.setFlags(parent_item.flags() & ~QtCore.Qt.ItemIsEnabled)
                parent_item.setText(1, "empty")
        tables_layout.addWidget(self.tree)
        picks = QtWidgets.QHBoxLayout()
        self.show_empty = QtWidgets.QCheckBox("Show empty tables")
        self.show_empty.toggled.connect(self._filter)
        all_btn = QtWidgets.QPushButton("Select all")
        none_btn = QtWidgets.QPushButton("Select none")
        all_btn.clicked.connect(lambda: self._set_all(QtCore.Qt.Checked))
        none_btn.clicked.connect(lambda: self._set_all(QtCore.Qt.Unchecked))
        self.count_label = QtWidgets.QLabel("")
        picks.addWidget(all_btn)
        picks.addWidget(none_btn)
        picks.addWidget(self.show_empty)
        picks.addStretch(1)
        picks.addWidget(self.count_label)
        tables_layout.addLayout(picks)
        layout.addWidget(tables_box, 1)
        self.tree.itemChanged.connect(lambda *_a: self._sync())

        folder_row = QtWidgets.QHBoxLayout()
        folder_row.addWidget(QtWidgets.QLabel("Folder:"))
        self.folder = QtWidgets.QLineEdit(start_dir)
        self.folder.setPlaceholderText("Where the export folder is created")
        browse = QtWidgets.QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        layout.addLayout(folder_row)
        self.folder.textChanged.connect(lambda *_a: self._sync())

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        cancel = QtWidgets.QPushButton("Cancel")
        self.ok = QtWidgets.QPushButton("Export")
        self.ok.setDefault(True)
        if _theme is not None:
            _theme.set_variant(self.ok, "primary")
            _theme.set_variant(cancel, "ghost")
            for b in (all_btn, none_btn, browse):
                _theme.set_variant(b, "ghost")
        cancel.clicked.connect(self.reject)
        self.ok.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.ok)
        layout.addLayout(buttons)
        self._filter(False)
        self._sync()
        if _theme is not None:
            _theme.apply_theme(self)

    def _filter(self, show_empty):
        """Empty tables (most of them, on a partial parse) hidden unless asked for."""
        for g in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(g)
            shown = 0
            for c in range(group.childCount()):
                child = group.child(c)
                hide = not show_empty and child.data(0, QtCore.Qt.UserRole + 1) == "empty"
                child.setHidden(hide)
                shown += not hide
            group.setHidden(shown == 0)
            group.setExpanded(shown > 0)

    def _items(self):
        it = QtWidgets.QTreeWidgetItemIterator(self.tree)
        while it.value():
            item = it.value()
            if item.data(0, QtCore.Qt.UserRole) is not None:
                yield item
            it += 1

    def _set_all(self, state):
        for item in self._items():
            if item.flags() & QtCore.Qt.ItemIsEnabled:
                item.setCheckState(0, state)

    def _browse(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Export folder", self.folder.text(),
                                                          QtWidgets.QFileDialog.ShowDirsOnly)
        if path:
            self.folder.setText(path)

    def _sync(self):
        n = len(self.selected())
        self.count_label.setText("%d table%s selected" % (n, "" if n == 1 else "s"))
        self.ok.setEnabled(n > 0 and bool(self.folder.text().strip()))

    def selected(self):
        return [item.data(0, QtCore.Qt.UserRole) for item in self._items()
                if item.flags() & QtCore.Qt.ItemIsEnabled and item.checkState(0) == QtCore.Qt.Checked]

    def fmt(self):
        button = self._formats.checkedButton()
        return button.property("fmt") if button is not None else "csv"


def export_tables(chosen, fmt, root_dir, case_name="", report=None, cancelled=None):
    """Write `chosen` [(name, frozen source)] under a new UTC-stamped folder.

    Runs on the export worker. `report(message, done, total)` is the worker's progress;
    `cancelled()` is checked every 2000 rows. Returns {folder, done, stopped, fmt, case}."""
    from utils.time_utils import get_current_forensic_timestamp, get_current_utc
    stamp = get_current_utc().strftime("%Y%m%d_%H%M%SZ")
    when = get_current_forensic_timestamp()
    folder = os.path.join(root_dir, "CrowEye_Export_%s" % stamp)
    sub = {"csv": os.path.join(folder, "CSV") if fmt == "both" else folder,
           "json": os.path.join(folder, "JSON") if fmt == "both" else folder,
           "html": folder}
    for path in set(sub.values()):
        os.makedirs(path, exist_ok=True)
    fmt_label = dict((k, l) for k, l, _h in FORMATS)[fmt]
    done, files, stopped = [], 0, False
    for i, (name, src) in enumerate(chosen):
        if cancelled is not None and cancelled():
            stopped = True
            break
        total = int(src.get("total") or 0)
        if report is not None:
            report(STEP_PREFIX + name, 0, 0)
            report("%s - 0 of %s rows" % (name, "{:,}".format(total)), 0, total)
        stem = safe_name(name)
        paths = {"csv": os.path.join(sub["csv"], stem + ".csv"),
                 "json": os.path.join(sub["json"], stem + ".json"),
                 "html": os.path.join(sub["html"], stem + ".html"), "title": name,
                 "facts": ([("Case", case_name)] if case_name else []) + [("Exported (UTC)", when)]}

        def on_rows(n, _name=name, _total=total):
            if report is not None:
                report("%s - %s of %s rows" % (_name, "{:,}".format(n), "{:,}".format(_total)), n, _total)
        try:
            written, rows = write_table(src, paths, fmt, on_rows, cancelled)
            files += written
            done.append((name, stem, rows, ""))
        except Stopped as e:
            done.append((name, stem, 0, "incomplete: %s" % e))
            stopped = True
            break
        except Exception as e:                                   # one bad table does not stop the rest
            done.append((name, stem, 0, str(e)))
    rows_total = sum(d[2] for d in done)
    with open(os.path.join(folder, "export_summary.txt"), "w", encoding="utf-8") as f:
        f.write("Crow-Eye export\n")
        f.write("Exported (UTC): %s\n" % when)
        if case_name:
            f.write("Case: %s\n" % case_name)
        f.write("Format: %s\n" % fmt_label)
        f.write("Tables: %d   Files: %d   Rows: %s%s\n\n" % (len(done), files, "{:,}".format(rows_total),
                                                            "   (stopped)" if stopped else ""))
        for name, _stem, rows, err in done:
            f.write("%-60s %10s%s\n" % (name, "{:,}".format(rows), ("   FAILED: " + err) if err else ""))
    index = None
    if fmt == "html":
        index = os.path.join(folder, "index.html")
        with open(index, "w", encoding="utf-8") as f:
            f.write(HTML_HEAD % {"title": "Crow-Eye export"})
            facts = ([("Case", case_name)] if case_name else []) + [
                ("Exported (UTC)", when), ("Tables", len(done)), ("Rows", "{:,}".format(rows_total))]
            if stopped:
                facts.append(("Status", "stopped before the end"))
            f.write(_head_card("Crow-Eye export", facts))
            f.write('<div class="wrap"><table><thead><tr><th>Table</th><th class="num">Rows</th></tr></thead><tbody>\n')
            for name, stem, rows, err in done:
                cell = (html.escape(name) if err else
                        '<a href="%s.html">%s</a>' % (stem, html.escape(name)))
                f.write('<tr><td>%s</td><td class="num%s">%s</td></tr>\n'
                        % (cell, " failed" if err else "", html.escape("failed: " + err) if err else "{:,}".format(rows)))
            f.write('</tbody></table></div><p class="foot">Written by Crow-Eye. Times are UTC.</p></body></html>\n')
    return {"folder": folder, "done": done, "stopped": stopped, "fmt": fmt, "fmt_label": fmt_label,
            "rows": rows_total, "index": index, "case": case_name, "planned": len(chosen)}


# ------------------------------------------------------------------ progress and result window
class ExportWindow(QtWidgets.QDialog):
    """The export's own window: Crow-Eye's loading screen while it writes, then the result.

    Not modal - the export runs on a worker thread, so Crow-Eye stays usable throughout. The
    same window turns into the result card: what was written, where, and buttons to open the
    report or the folder."""

    def __init__(self, chosen, fmt, root_dir, case_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export")
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowMinimizeButtonHint)
        self.setModal(False)
        self.setMinimumSize(560, 460)
        if _theme is not None:
            _theme.begin_theme(self)
        self._result = None
        self.pages = QtWidgets.QStackedWidget()
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(10)
        outer.addWidget(self.pages, 1)

        # page 0: the loading screen
        busy = QtWidgets.QWidget()
        bl = QtWidgets.QVBoxLayout(busy)
        bl.setContentsMargins(0, 0, 0, 0)
        names = [n for n, _s in chosen]
        self.loading = LoadingPanel("Exporting %d table%s" % (len(names), "" if len(names) == 1 else "s"),
                                    "%s to %s. Crow-Eye stays usable while this runs."
                                    % (dict((k, l) for k, l, _h in FORMATS)[fmt], root_dir), names)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(self.loading)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        bl.addWidget(scroll, 1)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setToolTip("Stop after the next 2,000 rows; what is written so far is kept and listed")
        row.addWidget(self.stop_btn)
        bl.addLayout(row)
        self.pages.addWidget(busy)

        # page 1: the result card
        self.result_page = QtWidgets.QWidget()
        self.pages.addWidget(self.result_page)

        if _theme is not None:
            _theme.set_variant(self.stop_btn, "ghost")
            _theme.apply_theme(self, clear_inline=False)

        from ui.app_acquisition_dialog import _Worker
        self.worker = _Worker(lambda report: export_tables(chosen, fmt, root_dir, case_name, report,
                                                           lambda: self.worker.cancelled), self)
        self.worker.progress.connect(self.loading.report)
        self.worker.finished_ok.connect(self._finished)
        self.worker.failed.connect(self._failed)
        self.stop_btn.clicked.connect(self._stop)

    def start(self):
        global _RUNNING
        _RUNNING = self
        self.show()
        self.worker.start()

    def _stop(self):
        self.worker.cancelled = True
        self.stop_btn.setEnabled(False)
        self.stop_btn.setText("Stopping...")

    def _release(self):
        global _RUNNING
        if _RUNNING is self:
            _RUNNING = None

    def _failed(self, message):
        self._release()
        self.loading.fail(message)
        self.stop_btn.setText("Close")
        self.stop_btn.setEnabled(True)
        self.stop_btn.clicked.disconnect()
        self.stop_btn.clicked.connect(self.close)

    def _finished(self, result):
        self._release()
        self._result = result
        done = result["done"]
        failed = [d for d in done if d[3]]
        ok = len(done) - len(failed)
        lay = QtWidgets.QVBoxLayout(self.result_page)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(10)
        head = QtWidgets.QHBoxLayout()
        mark = QtWidgets.QLabel("✓" if not failed and not result["stopped"] else "!")
        mark.setAlignment(QtCore.Qt.AlignCenter)
        mark.setFixedSize(34, 34)
        good = not failed and not result["stopped"]
        mark.setProperty("keepStyle", True)
        mark.setStyleSheet("QLabel { border-radius: 17px; font-size: 18px; font-weight: 700; color: %s;"
                           " background: %s; }" % (("#4ADE80", "rgba(74,222,128,0.14)") if good
                                                   else ("#FBBF24", "rgba(251,191,36,0.14)")))
        title = QtWidgets.QLabel("Export complete" if good else
                                 ("Export stopped" if result["stopped"] else "Export finished with problems"))
        head.addWidget(mark)
        head.addWidget(title, 1)
        lay.addLayout(head)
        facts = QtWidgets.QLabel(
            "%d of %d table%s written, %s rows, as %s.%s" % (
                ok, result["planned"], "" if result["planned"] == 1 else "s", "{:,}".format(result["rows"]),
                result["fmt_label"], ("  Case: %s." % result["case"]) if result["case"] else ""))
        facts.setWordWrap(True)
        where = QtWidgets.QLabel(result["folder"])
        where.setWordWrap(True)
        where.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        lay.addWidget(facts)
        lay.addWidget(where)
        if failed:
            bad = QtWidgets.QLabel("Not written: " + "; ".join("%s (%s)" % (d[0], d[3]) for d in failed))
            bad.setWordWrap(True)
            bad.setProperty("keepStyle", True)
            bad.setStyleSheet("QLabel { color: #FBBF24; }")
            lay.addWidget(bad)
        table = QtWidgets.QTableWidget(len(done), 2)
        table.setHorizontalHeaderLabels(["Table", "Rows"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        for r, (name, _stem, rows, err) in enumerate(done):
            table.setItem(r, 0, QtWidgets.QTableWidgetItem(name))
            it = QtWidgets.QTableWidgetItem(err and "failed" or "{:,}".format(rows))
            it.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            table.setItem(r, 1, it)
        lay.addWidget(table, 1)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        open_folder = QtWidgets.QPushButton("Open folder")
        open_folder.clicked.connect(lambda: self._open(result["folder"]))
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(open_folder)
        if result.get("index"):
            open_report = QtWidgets.QPushButton("Open report")
            open_report.clicked.connect(lambda: self._open(result["index"]))
            buttons.addWidget(open_report)
            primary = open_report
        else:
            primary = open_folder
        buttons.addWidget(close)
        lay.addLayout(buttons)
        if _theme is not None:
            _theme.set_role(title, "title")
            _theme.set_role(facts, "label")
            _theme.set_role(where, "mono")
            _theme.set_variant(primary, "primary")
            for b in (open_folder, close):
                if b is not primary:
                    _theme.set_variant(b, "ghost")
            _theme.apply_theme(self.result_page, clear_inline=False)
        self.pages.setCurrentIndex(1)
        # Brought to the front when it finishes, so the success is seen even if the
        # investigator went on working meanwhile.
        self.showNormal()
        self.raise_()
        self.activateWindow()

    @staticmethod
    def _open(path):
        from PyQt5 import QtGui
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

    def closeEvent(self, event):
        if self.worker.isRunning():
            # Closing the window does not abandon a half-written file silently: it stops
            # the export at the next 2,000 rows and keeps the window until it has.
            self._stop()
            event.ignore()
            self.worker.finished.connect(self.close)
            return
        self._release()
        super().closeEvent(event)


_RUNNING = None


def run(ui):
    """The side menu's Export: ask, then write on a worker with its own window."""
    parent = getattr(ui, "main_window", None)
    if _RUNNING is not None:
        _RUNNING.showNormal()
        _RUNNING.raise_()
        _RUNNING.activateWindow()
        return
    main_tab = getattr(ui, "main_tab", None)
    if main_tab is None:
        return
    tables = discover_tables(main_tab, ui)
    case_name, start_dir = "", ""
    paths = getattr(ui, "case_paths", None) or {}
    if paths.get("case_root"):
        case_name = os.path.basename(paths["case_root"].rstrip("\\/"))
        start_dir = paths["case_root"]
    dialog = ExportDialog(tables, parent, start_dir)
    if dialog.exec_() != QtWidgets.QDialog.Accepted:
        return
    fmt, root_dir = dialog.fmt(), dialog.folder.text().strip()
    # Frozen here, on the GUI thread: the worker never touches a Qt table.
    chosen = [(name, freeze(widget)) for name, widget in dialog.selected()]
    window = ExportWindow(chosen, fmt, root_dir, case_name, parent)
    window.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
    window.start()
    return window
