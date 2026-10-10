"""Parse Status Report + "why is this table empty" popups.

ParseStatusDialog       shown once after each live / offline / image parse,
                        when the data has loaded into the GUI; reopenable from
                        the Parse Status action. One row per artifact, under
                        the run's session issues (wrong input, unreadable or
                        encrypted image, nothing extracted, ...).
IssuesPanel             those issues as cards; also the image window's Issues tab.
EmptyTableReasonDialog  opened by the i button above an empty table.

Both read what utils/parse_status.py recorded in <case>/logs/parse_status.json.
"""
import html
import os

from PyQt5 import QtCore, QtGui, QtWidgets

from utils.parse_status import (NOT_A_FAILURE, STATUS_INFO, ParseStatus,
                                ParseStatusStore, status_color, status_label,
                                status_severity)

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
_SEVERITY_WORD = {"error": "Problem", "warning": "Warning", "info": "Note"}

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
        # The header was polished when the tree was built - under the PARENT's
        # style when the report opens over the main window (the after-parse
        # popup) - and a later setStyleSheet on the tree or the dialog does not
        # re-polish that sub-widget, so it painted as a plain white Qt header.
        # Opened from the Case menu with no parent it looked right.
        h = tree.header()
        h.style().unpolish(h)
        h.style().polish(h)
        h.viewport().update()
    for btn in dialog.findChildren(QtWidgets.QPushButton):
        btn.setStyleSheet(btn.styleSheet() + " QPushButton { font-size: 14px; font-weight: 700; }")


def _open_folder(path):
    try:
        os.makedirs(path, exist_ok=True)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
    except Exception:
        pass


class IssuesPanel(QtWidgets.QWidget):
    """Session issues as cards: severity, title, what it means, what to do."""

    def __init__(self, issues=None, parent=None, max_height=None):
        super().__init__(parent)
        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._scroll = QtWidgets.QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; }")
        if max_height:
            self._scroll.setMaximumHeight(max_height)
        self._host = QtWidgets.QWidget()
        self._host.setObjectName("issuesHost")
        self._host.setStyleSheet("QWidget#issuesHost { background: transparent; }")
        self._cards = QtWidgets.QVBoxLayout(self._host)
        self._cards.setContentsMargins(0, 0, 4, 0)
        self._cards.setSpacing(8)
        self._scroll.setWidget(self._host)
        self._layout.addWidget(self._scroll)
        self.set_issues(issues or [])

    def set_issues(self, issues):
        while self._cards.count():
            w = self._cards.takeAt(0).widget()
            if w is not None:
                # hidden and detached now: deleteLater alone left the old card
                # painting under the new one until the next event loop pass
                w.hide()
                w.setParent(None)
                w.deleteLater()
        issues = sorted(issues, key=lambda i: _SEVERITY_ORDER.get(i.severity, 3))
        if not issues:
            empty = QtWidgets.QLabel("No problems recorded for this run.")
            empty.setStyleSheet("QLabel { color: #94A3B8; font-size: 14px; padding: 8px; }")
            self._cards.addWidget(empty)
        for issue in issues:
            self._cards.addWidget(self._card(issue))
        self._cards.addStretch(1)

    @staticmethod
    def _card(issue):
        card = QtWidgets.QFrame()
        card.setObjectName("issueCard")
        card.setStyleSheet(
            "QFrame#issueCard { background: rgba(15, 23, 42, 0.85); border: 1px solid #1E293B;"
            " border-left: 4px solid %s; border-radius: 8px; }" % issue.color)
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(4)
        head = QtWidgets.QLabel("<span style='color:%s;'>%s</span> &nbsp;<b>%s</b>" % (
            issue.color, _SEVERITY_WORD.get(issue.severity, "Note"), html.escape(issue.title, quote=False)))
        head.setTextFormat(QtCore.Qt.RichText)
        head.setStyleSheet("QLabel { color: #F1F5F9; font-size: 15px; }")
        lay.addWidget(head)
        body = QtWidgets.QLabel(issue.message)
        body.setTextFormat(QtCore.Qt.PlainText)
        body.setWordWrap(True)
        body.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        body.setStyleSheet("QLabel { color: #CBD5E1; font-size: 14px; }")
        lay.addWidget(body)
        if issue.fix:
            fix = QtWidgets.QLabel("<b>What to do:</b> %s" % html.escape(issue.fix, quote=False))
            fix.setTextFormat(QtCore.Qt.RichText)
            fix.setWordWrap(True)
            fix.setStyleSheet("QLabel { color: #E2E8F0; font-size: 14px; }")
            lay.addWidget(fix)
        if issue.context:
            ctx = "  |  ".join("%s: %s" % (k.replace("_", " "), v)
                               for k, v in sorted(issue.context.items()) if v not in (None, ""))
            if ctx:
                c = QtWidgets.QLabel(ctx)
                c.setTextFormat(QtCore.Qt.PlainText)
                c.setWordWrap(True)
                c.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
                c.setStyleSheet("QLabel { color: #94A3B8; font-size: 12px;"
                                " font-family: Consolas, monospace; }")
                lay.addWidget(c)
        return card


def artifact_log_lines(case_root, artifact, limit=4000):
    """The lines of <case>/logs/parsers.log that belong to one artifact.

    Parsers log under Artifacts_Collectors.run.<artifact>; the lines without
    that tag (a traceback's frames) follow the tagged line they belong to.
    """
    path = os.path.join(case_root or "", "logs", "parsers.log")
    tag = "run.%s" % artifact
    out, keep = [], False
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\r\n")
                if tag in line:
                    keep = True
                elif line[:4].isdigit() and " [" in line[:40]:
                    keep = False                  # another logger's line
                if keep:
                    out.append(line)
    except OSError:
        return []
    return out[-limit:]


class ParseStatusDialog(QtWidgets.QDialog):
    """Per-artifact outcome of one parse run (or the latest of each)."""

    def __init__(self, case_root, run_id=None, parent=None):
        super().__init__(parent)
        self.case_root = case_root
        self.store = ParseStatusStore(case_root)
        self.run = self.store.run_info(run_id) if run_id else None
        self.outcomes = self.store.run_outcomes(run_id if self.run else None)
        self.issues = self.store.run_issues(run_id) if self.run else []

        self.setWindowTitle("Crow-Eye - Parse Status Report")
        self.setObjectName("ParseStatusDialog")
        self.resize(1080, 640)
        self.setMinimumSize(760, 420)
        self._build()
        _finish_styling(self)
        _readable(self)

    def _selected_artifact(self):
        item = self.tree.currentItem()
        while item is not None and item.parent() is not None:
            item = item.parent()
        if item is None:
            return None
        idx = self.tree.indexOfTopLevelItem(item)
        return self.outcomes[idx].artifact if 0 <= idx < len(self.outcomes) else None

    def _show_full_log(self):
        artifact = self._selected_artifact()
        if artifact is None:
            bad = [o for o in self.outcomes if status_severity(o.status) in ("warning", "error")]
            artifact = bad[0].artifact if bad else (self.outcomes[0].artifact if self.outcomes else None)
        lines = artifact_log_lines(self.case_root, artifact) if artifact else []
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Crow-Eye - %s log" % (artifact or "parser"))
        dlg.resize(1100, 640)
        v = QtWidgets.QVBoxLayout(dlg)
        view = QtWidgets.QPlainTextEdit()
        view.setReadOnly(True)
        view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        view.setStyleSheet("QPlainTextEdit { background: #0A0C10; color: #E2E8F0;"
                           " font-family: 'JetBrains Mono', Consolas; font-size: 12px; }")
        view.setPlainText("\n".join(lines) if lines else
                          "No lines for this artifact in logs/parsers.log.")
        try:
            from ui.log_highlighter import LogHighlighter
            dlg._hl = LogHighlighter(view.document())
        except Exception:
            pass
        v.addWidget(view)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(dlg.accept)
        v.addWidget(close, 0, QtCore.Qt.AlignRight)
        view.moveCursor(QtGui.QTextCursor.End)
        self._log_dialog = dlg
        dlg.show()
        return dlg

    def _build(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        heading = QtWidgets.QLabel("Parse Status Report")
        heading.setObjectName("headingLabel")
        try:
            from ui.site_theme import set_role
            set_role(heading, "title")
        except Exception:
            heading.setStyleSheet("QLabel { color: #E2E8F0; font-size: 22px; font-weight: 800; }")
        layout.addWidget(heading)

        if self.run:
            sub = "%s  |  started %s UTC  |  finished %s UTC" % (
                _MODE_LABEL.get(self.run.get("mode"), self.run.get("mode", "")),
                self.run.get("started") or "-", self.run.get("finished") or "-")
            src = self.run.get("source") or {}
            bits = [str(src[k]) for k in ("image", "partitions", "folder") if src.get(k)]
            if bits:
                sub += "\n" + "  |  ".join(bits)
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
        if self.issues:
            worst = min(self.issues, key=lambda i: _SEVERITY_ORDER.get(i.severity, 3))
            chips.addWidget(_chip("Issues  %d" % len(self.issues), worst.color, self))
        for status in ParseStatus.ALL:
            if counts.get(status):
                chips.addWidget(_chip("%s  %d" % (_label(status), counts[status]),
                                      _color(status), self))
        # What the run added, across artifacts: a re-parse of the same
        # machine should show mostly "already present".
        known = [o for o in self.outcomes if o.inserted is not None]
        if known:
            new = sum(max(0, o.inserted or 0) for o in known)
            dup = sum(o.duplicates or 0 for o in known)
            chips.addWidget(_chip("New rows  {:,}".format(new), "#22C55E", self))
            chips.addWidget(_chip("Already present  {:,}".format(dup), "#94A3B8", self))
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

        if self.issues:
            issues_head = QtWidgets.QLabel("Issues with this run")
            issues_head.setStyleSheet("QLabel { color: #F1F5F9; font-size: 16px; font-weight: 800; }")
            layout.addWidget(issues_head)
            self.issues_panel = IssuesPanel(self.issues, self, max_height=260)
            layout.addWidget(self.issues_panel)

        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setObjectName("parseStatusTree")
        # Records = rows this run read; New = rows it added to the case;
        # Already present = rows the case held before (a re-parse adds only
        # what is new).
        self.tree.setColumnCount(7)
        self.tree.setHeaderLabels(["Artifact", "Status", "Records", "New", "Already present",
                                   "Mode", "Reason"])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setWordWrap(True)
        self.tree.setAlternatingRowColors(True)
        hdr = self.tree.header()
        hdr.setStretchLastSection(True)
        for col, width in ((0, 190), (1, 150), (2, 100), (3, 80), (4, 140), (5, 60)):
            self.tree.setColumnWidth(col, width)
        # The count headers sit over right-aligned numbers.
        for col in (2, 3, 4):
            self.tree.headerItem().setTextAlignment(col, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.tree.headerItem().setToolTip(2, "Rows this run read from the evidence")
        self.tree.headerItem().setToolTip(3, "Rows this run added to the case")
        self.tree.headerItem().setToolTip(
            4, "Rows the case already held from an earlier parse - not stored again")

        if not self.outcomes:
            reason = ("No artifact was parsed in this run - see the issues above."
                      if self.issues else
                      "No parse status has been recorded for this case yet. It is written "
                      "by every live, offline and image parse.")
            item = QtWidgets.QTreeWidgetItem(["(nothing recorded)", "", "", "", "", "", reason])
            self.tree.addTopLevelItem(item)

        for o in self.outcomes:
            item = QtWidgets.QTreeWidgetItem(
                [o.label, _label(o.status), "{:,}".format(o.records) if o.records else "0",
                 "" if o.inserted is None else "{:,}".format(max(0, o.inserted)),
                 "" if o.duplicates is None else "{:,}".format(o.duplicates),
                 o.mode, o.message])
            for col in (3, 4):
                item.setTextAlignment(col, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            if o.inserted:
                item.setForeground(3, QtGui.QBrush(QtGui.QColor("#22C55E")))
            color = QtGui.QColor(_color(o.status))
            item.setForeground(1, QtGui.QBrush(color))
            f = item.font(1)
            f.setWeight(QtGui.QFont.ExtraBold)
            item.setFont(1, f)
            f0 = item.font(0)
            f0.setBold(True)
            item.setFont(0, f0)
            item.setToolTip(6, o.message)
            item.setToolTip(1, STATUS_INFO.get(o.status, ("", "", "", ""))[3])
            item.setTextAlignment(2, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            if o.status in NOT_A_FAILURE:
                item.setToolTip(1, "Not a failure - " + STATUS_INFO[o.status][3])

            for s in o.sources_checked:
                state = "found" if s.get("exists") else "missing"
                extra = (" - %s" % s["note"]) if s.get("note") else ""
                child = QtWidgets.QTreeWidgetItem(
                    ["Source checked", state, "", "", "", "", "%s%s" % (s.get("path", ""), extra)])
                child.setForeground(1, QtGui.QBrush(QtGui.QColor(
                    "#22C55E" if s.get("exists") else "#94A3B8")))
                item.addChild(child)
            # The failure itself, before anything else.
            if o.error and o.error != o.message:
                err = QtWidgets.QTreeWidgetItem(["Error", "", "", "", "", "", o.error])
                err.setForeground(6, QtGui.QBrush(QtGui.QColor("#FCA5A5")))
                err.setToolTip(6, o.error)
                item.addChild(err)
            for d in o.details:
                child = QtWidgets.QTreeWidgetItem(["Detail", "", "", "", "", "", d])
                child.setToolTip(6, d)
                item.addChild(child)
            # What the parser printed: the warning / error lines and any
            # traceback (they used to stop at parsers.log).
            if o.log_excerpt and status_severity(o.status) in ("warning", "error"):
                block = QtWidgets.QTreeWidgetItem(
                    ["Log excerpt", "%d line(s)" % len(o.log_excerpt), "", "", "", "", ""])
                mono = QtGui.QFont("JetBrains Mono")
                mono.setStyleHint(QtGui.QFont.Monospace)
                mono.setPixelSize(12)
                for ln in o.log_excerpt:
                    child = QtWidgets.QTreeWidgetItem(["", "", "", "", "", "", ln])
                    child.setFont(6, mono)
                    child.setForeground(6, QtGui.QBrush(QtGui.QColor(
                        "#FCA5A5" if ln.startswith(("ERROR", "CRITICAL")) else
                        "#FDE68A" if ln.startswith("WARNING") else "#CBD5E1")))
                    child.setToolTip(6, ln)
                    block.addChild(child)
                item.addChild(block)
                # Expanded once the row is in the tree (setExpanded on an item
                # that is not yet in a tree does nothing).
                if o.status in ("FAILED", "PARTIAL"):
                    item._expand_excerpt = block
            if o.rows_before is not None or o.rows_after is not None:
                item.addChild(QtWidgets.QTreeWidgetItem(
                    ["Database rows", "", "", "", "", "",
                     "before this run: %s, after: %s" % (
                         "-" if o.rows_before is None else "{:,}".format(o.rows_before),
                         "-" if o.rows_after is None else "{:,}".format(o.rows_after))]))
            if o.parsed_at:
                item.addChild(QtWidgets.QTreeWidgetItem(
                    ["Recorded", "", "", "", "", "", "%s UTC" % o.parsed_at]))
            self.tree.addTopLevelItem(item)
            # Problems open by default; quiet rows stay folded.
            item.setExpanded(status_severity(o.status) in ("warning", "error"))
            if getattr(item, "_expand_excerpt", None) is not None:
                item._expand_excerpt.setExpanded(True)

        layout.addWidget(self.tree, 1)

        tip = QtWidgets.QLabel(
            "Tip: an empty table shows an  i  button at its top-left - click it for the "
            "reason that specific table is empty. Every outcome is also written to "
            "Settings -> Logs -> Parse status.")
        tip.setWordWrap(True)
        tip.setStyleSheet("QLabel { color: #CBD5E1; font-size: 13px; }")
        layout.addWidget(tip)

        buttons = QtWidgets.QHBoxLayout()
        self.full_log_btn = QtWidgets.QPushButton("Show parser log")
        self.full_log_btn.setToolTip("The parsers' log (parsers.log), filtered to the selected "
                                     "artifact")
        self.full_log_btn.clicked.connect(self._show_full_log)
        buttons.addWidget(self.full_log_btn)
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
        try:
            from ui.site_theme import set_role
            set_role(heading, "title")
        except Exception:
            heading.setStyleSheet("QLabel { color: #E2E8F0; font-size: 20px; font-weight: 800; }")
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
