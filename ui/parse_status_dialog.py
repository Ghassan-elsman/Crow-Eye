"""Parse Status Report + "why is this table empty" popups.

ParseStatusDialog       shown once after each live / offline / image parse,
                        when the data has loaded into the GUI; reopenable from
                        the Parse Status action. One row per artifact.
EmptyTableReasonDialog  opened by the i button above an empty table.

Both read what utils/parse_status.py recorded in <case>/logs/parse_status.json.
"""
import html
import os

from PyQt5 import QtCore, QtGui, QtWidgets

from utils.parse_status import (NOT_A_FAILURE, STATUS_INFO, ParseStatus,
                                ParseStatusStore, status_color, status_label,
                                status_severity)

_DISPLAY_ERROR = "DISPLAY_ERROR"

_MODE_LABEL = {"live": "Live system", "offline": "Offline artifacts", "image": "Forensic image"}


def _label(status):
    if status == _DISPLAY_ERROR:
        return "Display error"
    return status_label(status)


def _color(status):
    if status == _DISPLAY_ERROR:
        return "#EF4444"
    return status_color(status)


def _chip(text, color, parent=None):
    lbl = QtWidgets.QLabel(text, parent)
    lbl.setStyleSheet(
        "QLabel { color: %s; border: 1px solid %s; border-radius: 9px;"
        " padding: 4px 12px; background: transparent; font-size: 14px; font-weight: 700; }" % (color, color))
    return lbl


def _finish_styling(dialog):
    try:
        from styles import CrowEyeStyles as _CES
        _CES.give_window_a_taskbar_button(dialog)
    except Exception:
        pass
    try:
        from correlation_engine.gui.ui_styling import CorrelationEngineStyles
        CorrelationEngineStyles.apply_evidence_detail_styling(dialog)
    except Exception:
        pass


def _readable(dialog):
    """Larger, heavier text - applied AFTER apply_evidence_detail_styling,
    which restyles trees and buttons and would otherwise undo it."""
    for tree in dialog.findChildren(QtWidgets.QTreeWidget):
        # The shared tree style colours every item, and a stylesheet item
        # colour beats the per-cell colour - so "Parsed" / "Access denied"
        # all came out white. Drop that one declaration; the tree's base
        # `color` still covers every cell that sets none.
        import re
        base = re.sub(r"(QTreeWidget::item\s*\{[^}]*?)\bcolor:[^;]*;", r"\1",
                      tree.styleSheet(), count=1)
        tree.setStyleSheet(base + """
            QTreeWidget { font-size: 14px; }
            QTreeWidget::item { padding: 6px 4px; }
            QHeaderView::section { font-size: 14px; font-weight: 700; padding: 6px; }
        """)
    for btn in dialog.findChildren(QtWidgets.QPushButton):
        btn.setStyleSheet(btn.styleSheet() + " QPushButton { font-size: 14px; font-weight: 700; }")


def _open_folder(path):
    try:
        os.makedirs(path, exist_ok=True)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
    except Exception:
        pass


class ParseStatusDialog(QtWidgets.QDialog):
    """Per-artifact outcome of one parse run (or the latest of each)."""

    def __init__(self, case_root, run_id=None, parent=None):
        super().__init__(parent)
        self.case_root = case_root
        self.store = ParseStatusStore(case_root)
        self.run = self.store.run_info(run_id) if run_id else None
        self.outcomes = self.store.run_outcomes(run_id if self.run else None)

        self.setWindowTitle("Crow-Eye - Parse Status Report")
        self.setObjectName("ParseStatusDialog")
        self.resize(1080, 640)
        self.setMinimumSize(760, 420)
        self._build()
        _finish_styling(self)
        _readable(self)

    def _build(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        heading = QtWidgets.QLabel("Parse Status Report")
        heading.setObjectName("headingLabel")
        heading.setStyleSheet("QLabel { color: #00FFFF; font-size: 22px; font-weight: 800; }")
        layout.addWidget(heading)

        if self.run:
            sub = "%s  |  started %s UTC  |  finished %s UTC" % (
                _MODE_LABEL.get(self.run.get("mode"), self.run.get("mode", "")),
                self.run.get("started") or "-", self.run.get("finished") or "-")
        else:
            sub = "Latest recorded outcome for every artifact in this case"
        sub_lbl = QtWidgets.QLabel(sub)
        sub_lbl.setStyleSheet("QLabel { color: #CBD5E1; font-size: 14px; font-weight: 600; }")
        layout.addWidget(sub_lbl)

        # Counts per status, in vocabulary order.
        counts = {}
        for o in self.outcomes:
            counts[o.status] = counts.get(o.status, 0) + 1
        chips = QtWidgets.QHBoxLayout()
        chips.setSpacing(8)
        for status in ParseStatus.ALL:
            if counts.get(status):
                chips.addWidget(_chip("%s  %d" % (_label(status), counts[status]),
                                      _color(status), self))
        chips.addStretch(1)
        layout.addLayout(chips)

        note = QtWidgets.QLabel(
            "<span style='color:#38BDF8;'>&#9679;</span> Blue outcomes are <b>not failures</b>: "
            "the artifact does not exist on this evidence, the OS/settings do not produce it, "
            "or it held no records - an empty table there is expected. "
            "<span style='color:#F59E0B;'>&#9679;</span> Amber and "
            "<span style='color:#EF4444;'>&#9679;</span> red outcomes need attention.")
        note.setWordWrap(True)
        note.setTextFormat(QtCore.Qt.RichText)
        note.setStyleSheet("QLabel { color: #E2E8F0; font-size: 14px; }")
        layout.addWidget(note)

        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setObjectName("parseStatusTree")
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Artifact", "Status", "Records", "Mode", "Reason"])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setWordWrap(True)
        self.tree.setAlternatingRowColors(True)
        hdr = self.tree.header()
        hdr.setStretchLastSection(True)
        for col, width in ((0, 190), (1, 150), (2, 90), (3, 70)):
            self.tree.setColumnWidth(col, width)

        if not self.outcomes:
            item = QtWidgets.QTreeWidgetItem(
                ["(nothing recorded)", "", "", "",
                 "No parse status has been recorded for this case yet. It is written "
                 "by every live, offline and image parse."])
            self.tree.addTopLevelItem(item)

        for o in self.outcomes:
            item = QtWidgets.QTreeWidgetItem(
                [o.label, _label(o.status), "{:,}".format(o.records) if o.records else "0",
                 o.mode, o.message])
            color = QtGui.QColor(_color(o.status))
            item.setForeground(1, QtGui.QBrush(color))
            f = item.font(1)
            f.setWeight(QtGui.QFont.ExtraBold)
            item.setFont(1, f)
            f0 = item.font(0)
            f0.setBold(True)
            item.setFont(0, f0)
            item.setToolTip(4, o.message)
            item.setToolTip(1, STATUS_INFO.get(o.status, ("", "", "", ""))[3])
            item.setTextAlignment(2, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            if o.status in NOT_A_FAILURE:
                item.setToolTip(1, "Not a failure - " + STATUS_INFO[o.status][3])

            for s in o.sources_checked:
                state = "found" if s.get("exists") else "missing"
                extra = (" - %s" % s["note"]) if s.get("note") else ""
                child = QtWidgets.QTreeWidgetItem(
                    ["Source checked", state, "", "", "%s%s" % (s.get("path", ""), extra)])
                child.setForeground(1, QtGui.QBrush(QtGui.QColor(
                    "#22C55E" if s.get("exists") else "#94A3B8")))
                item.addChild(child)
            for d in o.details:
                child = QtWidgets.QTreeWidgetItem(["Detail", "", "", "", d])
                child.setToolTip(4, d)
                item.addChild(child)
            if o.parsed_at:
                item.addChild(QtWidgets.QTreeWidgetItem(
                    ["Recorded", "", "", "", "%s UTC" % o.parsed_at]))
            self.tree.addTopLevelItem(item)
            # Problems open by default; quiet rows stay folded.
            item.setExpanded(status_severity(o.status) in ("warning", "error"))

        layout.addWidget(self.tree, 1)

        tip = QtWidgets.QLabel(
            "Tip: an empty table shows an  i  button at its top-left - click it for the "
            "reason that specific table is empty. Every outcome is also written to "
            "Settings -> Logs -> Parse status.")
        tip.setWordWrap(True)
        tip.setStyleSheet("QLabel { color: #CBD5E1; font-size: 13px; }")
        layout.addWidget(tip)

        buttons = QtWidgets.QHBoxLayout()
        logs_btn = QtWidgets.QPushButton("Open logs folder")
        logs_btn.clicked.connect(lambda: _open_folder(os.path.join(self.case_root, "logs")))
        buttons.addWidget(logs_btn)
        buttons.addStretch(1)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)


class EmptyTableReasonDialog(QtWidgets.QDialog):
    """Why one table is empty (utils.table_sources.EmptyReason)."""

    def __init__(self, reason, table_title="", parent=None, open_report=None):
        super().__init__(parent)
        self.reason = reason
        self._open_report = open_report
        self.setWindowTitle("Crow-Eye - Why is this table empty?")
        self.setObjectName("EmptyTableReasonDialog")
        self.resize(640, 460)
        self.setMinimumSize(480, 320)
        self._build(table_title)
        _finish_styling(self)
        _readable(self)

    def _build(self, table_title):
        r = self.reason
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        heading = QtWidgets.QLabel(table_title or r.sqlite_table)
        heading.setObjectName("headingLabel")
        heading.setStyleSheet("QLabel { color: #00FFFF; font-size: 20px; font-weight: 800; }")
        layout.addWidget(heading)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(_chip(_label(r.status), _color(r.status), self))
        verdict = ("Not a failure" if r.status in NOT_A_FAILURE
                   else "Not parsed yet" if r.status == ParseStatus.NOT_RUN
                   else "Needs attention")
        v = QtWidgets.QLabel(verdict)
        v.setStyleSheet("QLabel { color: %s; font-size: 15px; font-weight: 700; }" % _color(r.status))
        top.addWidget(v)
        top.addStretch(1)
        layout.addLayout(top)

        headline = QtWidgets.QLabel(r.headline)
        headline.setWordWrap(True)
        headline.setStyleSheet("QLabel { color: #F1F5F9; font-size: 17px; font-weight: 700; }")
        layout.addWidget(headline)

        body = QtWidgets.QLabel(r.explanation)
        body.setWordWrap(True)
        body.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        body.setStyleSheet("QLabel { color: #E2E8F0; font-size: 15px; }")
        layout.addWidget(body)

        if r.hint:
            hint = QtWidgets.QLabel("<b>When this is normal:</b> %s" % html.escape(r.hint))
            hint.setWordWrap(True)
            hint.setTextFormat(QtCore.Qt.RichText)
            hint.setStyleSheet(
                "QLabel { color: #BAE6FD; font-size: 14px; border-left: 3px solid #38BDF8;"
                " padding: 4px 8px; background: rgba(56,189,248,0.08); }")
            layout.addWidget(hint)

        facts = [("Artifact", r.outcome.label if r.outcome else r.artifact),
                 ("Database", r.db_file),
                 ("SQLite table", r.sqlite_table),
                 ("Rows in database", "table not present" if r.db_rows is None
                  else "{:,}".format(r.db_rows))]
        if r.outcome is not None:
            facts.append(("Last parse", "%s - %s UTC - %s" % (
                _MODE_LABEL.get(r.outcome.mode, r.outcome.mode), r.outcome.parsed_at,
                _label(r.outcome.status))))
        for s in r.sources[:6]:
            facts.append(("Source checked", "%s  [%s]" % (
                s.get("path", ""), "found" if s.get("exists") else "missing")))

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        for i, (k, val) in enumerate(facts):
            kl = QtWidgets.QLabel(k)
            kl.setStyleSheet("QLabel { color: #CBD5E1; font-size: 14px; font-weight: 600; }")
            vl = QtWidgets.QLabel(str(val))
            vl.setWordWrap(True)
            vl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            vl.setStyleSheet("QLabel { color: #F1F5F9; font-size: 14px; font-family: Consolas, monospace; }")
            grid.addWidget(kl, i, 0, QtCore.Qt.AlignTop)
            grid.addWidget(vl, i, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch(1)

        buttons = QtWidgets.QHBoxLayout()
        if self._open_report is not None:
            rep = QtWidgets.QPushButton("Open Parse Status Report")
            rep.clicked.connect(self._report)
            buttons.addWidget(rep)
        buttons.addStretch(1)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def _report(self):
        self.accept()
        try:
            self._open_report()
        except Exception:
            pass
