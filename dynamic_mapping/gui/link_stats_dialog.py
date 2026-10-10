"""Dynamic Linking statistics: what one run linked, and where it came from.

Shown after "Link Gathering" and after "Run Dynamic Linking", and reopened
from the Dynamic Linking window's "Statistics of last run" button. It reads a
LinkRun (dynamic_mapping/core/run_stats.py); the same numbers are written to
dynamic_linking.log.

* By source - every rule under the database and table it read, with the
  columns it took the value and the name from, the rows it read and what
  became of them: new, merged into a known value, already known, rejected.
  Rules that were skipped or failed say why.
* By category - SIDs, MACs, hashes, executions... what kind of link was made.
* Linked in tables - after Run Dynamic Linking: for each artifact table, how
  many of its rows now carry a linked name, and which sources supplied them.
* Mapping database - every link in the case's intelligence database by source.
"""
import os

from PyQt5 import QtCore, QtGui, QtWidgets

from dynamic_mapping.core.run_stats import DUPLICATE, INSERTED, MERGED, REJECTED

try:
    from ui.parse_status_dialog import _chip, _finish_styling, _open_folder, _readable
except Exception:                                    # standalone use
    def _chip(text, color, parent=None):
        lbl = QtWidgets.QLabel(text, parent)
        lbl.setStyleSheet("QLabel { color: %s; border: 1px solid %s; border-radius: 9px;"
                          " padding: 4px 12px; font-size: 14px; font-weight: 700; }" % (color, color))
        return lbl

    def _finish_styling(dialog):
        pass

    def _readable(dialog):
        pass

    def _open_folder(path):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

_STATUS_COLOR = {"ok": "#22C55E", "skipped": "#38BDF8", "failed": "#EF4444"}
_STATUS_WORD = {"ok": "Ran", "skipped": "Skipped", "failed": "Failed"}


def _n(value):
    return "{:,}".format(int(value or 0))


def _item(texts, numeric=()):
    item = QtWidgets.QTreeWidgetItem([str(t) for t in texts])
    for col in numeric:
        item.setTextAlignment(col, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
    return item


def _bold(item, col=0):
    f = item.font(col)
    f.setBold(True)
    item.setFont(col, f)


class LinkStatsDialog(QtWidgets.QDialog):
    """The statistics of one Dynamic Linking run."""

    def __init__(self, run, case_directory=None, mapping_sources=None, parent=None):
        super().__init__(parent)
        self.run = run
        self.case_directory = case_directory
        # [(source, count)] from the Mapping table; read here when not given.
        self.mapping_sources = (mapping_sources if mapping_sources is not None
                                else self._read_mapping_sources())
        self.setWindowTitle("Crow-Eye - Dynamic Linking Statistics")
        self.setObjectName("LinkStatsDialog")
        self.resize(1120, 700)
        self.setMinimumSize(780, 460)
        self._build()
        _finish_styling(self)
        _readable(self)

    # ------------------------------------------------------------------ data
    def _read_mapping_sources(self):
        if not self.case_directory:
            return []
        path = os.path.join(self.case_directory, "Crow_Intelligence.db")
        if not os.path.exists(path):
            return []
        import sqlite3
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
            try:
                return conn.execute("SELECT source, COUNT(*) FROM Mapping GROUP BY source "
                                    "ORDER BY COUNT(*) DESC").fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return []

    # ------------------------------------------------------------------- ui
    def _build(self):
        run = self.run
        t = run.totals()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        heading = QtWidgets.QLabel("Dynamic Linking Statistics")
        try:
            from ui.site_theme import set_role
            set_role(heading, "title")
        except Exception:
            heading.setStyleSheet("QLabel { color: #E2E8F0; font-size: 22px; font-weight: 800; }")
        layout.addWidget(heading)

        kind = {"gather": "Link Gathering", "link": "Run Dynamic Linking"}.get(run.kind, run.kind)
        import time as _time
        when = _time.strftime("%Y-%m-%d %H:%M:%S UTC", _time.gmtime(run.started))
        sub = "%s  |  run %s  |  %s  |  %.1fs%s" % (kind, run.run_id, when, run.duration,
                                                    "  |  CANCELLED" if run.cancelled else "")
        sub_lbl = QtWidgets.QLabel(sub)
        sub_lbl.setStyleSheet("QLabel { color: #CBD5E1; font-size: 14px; font-weight: 600; }")
        layout.addWidget(sub_lbl)
        src = getattr(run, "rules_from", None)
        if src:
            from_kind = {"gather": "Link Gathering", "link": "Run Dynamic Linking"}.get(
                src.get("kind"), src.get("kind") or "run")
            from_lbl = QtWidgets.QLabel(
                "Rules and link counts from the %s at %s (run %s); this run linked the tables "
                "with them." % (from_kind, _time.strftime("%Y-%m-%d %H:%M:%S UTC",
                                                           _time.gmtime(src.get("started") or 0)),
                                src.get("run_id")))
            from_lbl.setWordWrap(True)
            from_lbl.setStyleSheet("QLabel { color: #38BDF8; font-size: 13px; }")
            layout.addWidget(from_lbl)

        chips = QtWidgets.QHBoxLayout()
        chips.setSpacing(8)
        chips2 = QtWidgets.QHBoxLayout()
        chips2.setSpacing(8)
        chips.addWidget(_chip("New links  %s" % _n(t["new_links"]), "#22C55E", self))
        chips.addWidget(_chip("New values  %s" % _n(t[INSERTED]), "#4ADE80", self))
        chips.addWidget(_chip("Merged  %s" % _n(t[MERGED]), "#A3E635", self))
        chips.addWidget(_chip("Already known  %s" % _n(t[DUPLICATE]), "#94A3B8", self))
        if t[REJECTED]:
            chips.addWidget(_chip("Rejected  %s" % _n(t[REJECTED]), "#F59E0B", self))
        chips.addStretch(1)
        layout.addLayout(chips)
        chips2.addWidget(_chip("Rules ran  %d" % t["rules_ok"], "#22C55E", self))
        chips2.addWidget(_chip("Skipped  %d" % t["rules_skipped"], "#38BDF8", self))
        if t["rules_failed"]:
            chips2.addWidget(_chip("Failed  %d" % t["rules_failed"], "#EF4444", self))
        if run.enriched_tables:
            chips2.addWidget(_chip("Rows linked  %s in %d table(s)"
                                   % (_n(t["enriched_rows"]), len(run.enriched_tables)),
                                   "#C084FC", self))
        chips2.addWidget(_chip("In database  %s" % _n(run.mappings_total), "#22D3EE", self))
        chips2.addStretch(1)
        layout.addLayout(chips2)

        note = QtWidgets.QLabel(
            "<b>New</b>: a value the intelligence database did not have. <b>Merged</b>: a "
            "known value gained another name. <b>Already known</b>: found again, nothing "
            "added. <span style='color:#38BDF8;'>Skipped</span> rules are not failures - the "
            "artifact they read was not parsed in this case.")
        note.setWordWrap(True)
        note.setTextFormat(QtCore.Qt.RichText)
        note.setStyleSheet("QLabel { color: #E2E8F0; font-size: 13px; }")
        layout.addWidget(note)

        self.tabs = QtWidgets.QTabWidget(self)
        self.tabs.addTab(self._by_source_tab(), "By source")
        self.tabs.addTab(self._by_category_tab(), "By category")
        if run.enriched_tables:
            self.tabs.addTab(self._tables_tab(), "Linked in tables")
            self.tabs.setCurrentIndex(2)
        self.tabs.addTab(self._database_tab(), "Mapping database")
        layout.addWidget(self.tabs, 1)

        tip = QtWidgets.QLabel("Every rule's line and this summary are also in "
                               "Settings -> Logs -> Dynamic Linking (dynamic_linking.log).")
        tip.setWordWrap(True)
        tip.setStyleSheet("QLabel { color: #CBD5E1; font-size: 13px; }")
        layout.addWidget(tip)

        buttons = QtWidgets.QHBoxLayout()
        if self.case_directory:
            logs_btn = QtWidgets.QPushButton("Open logs folder")
            logs_btn.clicked.connect(lambda: _open_folder(os.path.join(self.case_directory, "logs")))
            buttons.addWidget(logs_btn)
        copy_btn = QtWidgets.QPushButton("Copy summary")
        copy_btn.clicked.connect(self._copy_summary)
        buttons.addWidget(copy_btn)
        buttons.addStretch(1)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def _tree(self, headers, widths):
        tree = QtWidgets.QTreeWidget(self)
        tree.setColumnCount(len(headers))
        tree.setHeaderLabels(headers)
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.header().setStretchLastSection(True)
        for col, width in enumerate(widths):
            tree.setColumnWidth(col, width)
        return tree

    def _by_source_tab(self):
        tree = self._tree(["Source / rule", "Value -> name", "Rows read", "New", "Merged",
                           "Known", "Status"], (300, 230, 90, 70, 70, 70))
        groups = {}
        for r in self.run.rules:
            db = r.source_db or ("(built in)" if r.rule_type == "internal" else "(none)")
            groups.setdefault(db, {}).setdefault(r.source_table or "-", []).append(r)
        def _weight(db):
            rules = [r for rs in groups[db].values() for r in rs]
            ran = any(r.status != "skipped" for r in rules)
            return (not ran, -sum(r.new_links for r in rules), db.lower())

        # Databases that produced links first; ones whose rules were all
        # skipped (not parsed in this case) last, folded.
        for db in sorted(groups, key=_weight):
            tables = groups[db]
            rules = [r for rs in tables.values() for r in rs]
            all_skipped = all(r.status == "skipped" for r in rules)
            db_item = _item([db, "", _n(sum(r.rows_read for r in rules)),
                             _n(sum(r.inserted for r in rules)), _n(sum(r.merged for r in rules)),
                             _n(sum(r.duplicate for r in rules)), ""], numeric=(2, 3, 4, 5))
            _bold(db_item)
            tree.addTopLevelItem(db_item)
            for table in sorted(tables, key=str.lower):
                t_rules = tables[table]
                t_item = _item([table, "", _n(sum(r.rows_read for r in t_rules)),
                                _n(sum(r.inserted for r in t_rules)),
                                _n(sum(r.merged for r in t_rules)),
                                _n(sum(r.duplicate for r in t_rules)), ""], numeric=(2, 3, 4, 5))
                db_item.addChild(t_item)
                for r in t_rules:
                    cols = "%s -> %s" % (r.value_column or "?", r.key_column or "?") \
                        if (r.value_column or r.key_column) else ""
                    status = _STATUS_WORD.get(r.status, r.status)
                    if r.reason:
                        status += ": " + r.reason
                    if r.rejected:
                        status += " (%s rejected)" % _n(r.rejected)
                    r_item = _item([r.rule, cols, _n(r.rows_read), _n(r.inserted), _n(r.merged),
                                    _n(r.duplicate), status], numeric=(2, 3, 4, 5))
                    r_item.setForeground(6, QtGui.QBrush(QtGui.QColor(
                        _STATUS_COLOR.get(r.status, "#E2E8F0"))))
                    r_item.setToolTip(0, r.description or r.rule)
                    r_item.setToolTip(6, status)
                    t_item.addChild(r_item)
                t_item.setExpanded(True)
            if all_skipped:
                db_item.setText(6, "not parsed in this case")
                db_item.setForeground(6, QtGui.QBrush(QtGui.QColor("#38BDF8")))
                for col in range(6):
                    db_item.setForeground(col, QtGui.QBrush(QtGui.QColor("#94A3B8")))
            db_item.setExpanded(not all_skipped)
        return tree

    def _by_category_tab(self):
        tree = self._tree(["Category", "Rules", "Rows read", "New", "Merged", "Known"],
                          (260, 90, 100, 90, 90))
        cats = {}
        for r in self.run.rules:
            c = cats.setdefault(r.category or r.rule_type or "Other",
                                {"rules": 0, "rows": 0, INSERTED: 0, MERGED: 0, DUPLICATE: 0})
            c["rules"] += 1
            c["rows"] += r.rows_read
            for k in (INSERTED, MERGED, DUPLICATE):
                c[k] += getattr(r, k)
        for name, c in sorted(cats.items(), key=lambda kv: -(kv[1][INSERTED] + kv[1][MERGED])):
            tree.addTopLevelItem(_item([name, c["rules"], _n(c["rows"]), _n(c[INSERTED]),
                                        _n(c[MERGED]), _n(c[DUPLICATE])], numeric=(1, 2, 3, 4, 5)))
        return tree

    def _tables_tab(self):
        tree = self._tree(["Artifact table", "Linked column", "Rows", "Rows linked", "%",
                           "Linked from"], (240, 170, 90, 100, 60))
        for e in sorted(self.run.enriched_tables, key=lambda e: -int(e.get("enriched") or 0)):
            rows, enriched = int(e.get("rows") or 0), int(e.get("enriched") or 0)
            counted = not (e.get("note") and not enriched)
            pct = ("%.0f%%" % (100.0 * enriched / rows)) if rows and counted else ""
            sources = ", ".join("%s (%s)" % (s, _n(n)) for s, n in sorted(
                (e.get("sources") or {}).items(), key=lambda kv: -kv[1]))
            if e.get("note"):
                sources = (sources + "  - " if sources else "") + e["note"]
            item = _item([e.get("title") or e.get("table"), e.get("column") or "", _n(rows),
                          _n(enriched) if counted else "-", pct, sources], numeric=(2, 3, 4))
            if not enriched:
                for col in range(6):
                    item.setForeground(col, QtGui.QBrush(QtGui.QColor("#94A3B8")))
            item.setToolTip(5, sources)
            tree.addTopLevelItem(item)
        return tree

    def _database_tab(self):
        tree = self._tree(["Source", "Links"], (360,))
        total = 0
        for source, count in self.mapping_sources:
            total += int(count or 0)
            tree.addTopLevelItem(_item([source or "(unknown)", _n(count)], numeric=(1,)))
        if not self.mapping_sources:
            tree.addTopLevelItem(_item(["(the intelligence database is empty)", ""]))
        else:
            total_item = _item(["Total", _n(total)], numeric=(1,))
            _bold(total_item)
            _bold(total_item, 1)
            tree.addTopLevelItem(total_item)
        return tree

    def summary_text(self):
        run, t = self.run, self.run.totals()
        lines = ["Dynamic Linking %s %s" % (run.kind, run.run_id),
                 "New links %d (new values %d, merged %d), already known %d, rejected %d"
                 % (t["new_links"], t[INSERTED], t[MERGED], t[DUPLICATE], t[REJECTED]),
                 "Rules: %d ran, %d skipped, %d failed; %d mappings in the database"
                 % (t["rules_ok"], t["rules_skipped"], t["rules_failed"], run.mappings_total)]
        if getattr(run, "rules_from", None):
            lines.append("Rules from %s %s" % (run.rules_from.get("kind"),
                                               run.rules_from.get("run_id")))
        for r in run.rules:
            lines.append("  %-36s %s > %s: read %d, new %d, merged %d, known %d %s"
                         % (r.rule, r.source_db or "-", r.source_table or "-", r.rows_read,
                            r.inserted, r.merged, r.duplicate,
                            "" if r.status == "ok" else "[%s: %s]" % (r.status, r.reason)))
        for e in run.enriched_tables:
            lines.append("  linked %s.%s: %s of %s rows"
                         % (e.get("table"), e.get("column"), e.get("enriched"), e.get("rows")))
        return "\n".join(lines)

    def _copy_summary(self):
        QtWidgets.QApplication.clipboard().setText(self.summary_text())
