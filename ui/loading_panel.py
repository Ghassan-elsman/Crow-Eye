"""A loading screen for a window or a part of one: what is being read, step by step.

A window that opens on empty panes and a line of grey text ("Reading...") cannot be told apart from one
that has hung, and says nothing about what is taking the time. LoadingPanel shows the work as it
happens: a title, Crow-Eye's own animated bar (ui/animated_progress_bar.py - it never looks frozen,
and shows a real fraction when a step reports counts), and the steps, each waiting, running, done with
how long it took, or failed with the reason.

Steps are driven from the GUI thread. A worker reports through the usual
`report(message, done, total)` callback; `LoadingPanel.report` takes those arguments, and a message
starting with STEP_PREFIX ("step:") opens the next step of that name, any other message updates the
running step's line.
"""
import time
from typing import List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

try:
    from ui import app_theme as _theme
except Exception:                                         # pragma: no cover
    _theme = None
from ui.animated_progress_bar import AnimatedProgressBar

STEP_PREFIX = "step:"
_STATE = {
    "waiting": ("○", "#64748B", "#94A3B8"),     # hollow circle
    "running": ("●", "#22D3EE", "#F8FAFC"),     # filled circle, cyan: happening now
    "done": ("✓", "#4ADE80", "#CBD5E1"),        # tick, green: finished
    "failed": ("✕", "#F59E0B", "#FBBF24"),      # cross, amber (red is for what is urgent)
}


def step(report, name):
    """Open the step `name` from a worker: `step(report, "Reading the catalog")`."""
    try:
        report(STEP_PREFIX + name, 0, 0)
    except Exception:
        pass


class _StepRow(QtWidgets.QWidget):
    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.name = name
        self.started = None
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(10)
        self.mark = QtWidgets.QLabel()
        self.mark.setFixedWidth(16)
        self.mark.setAlignment(QtCore.Qt.AlignCenter)
        self.text = QtWidgets.QLabel(name)
        self.text.setWordWrap(True)
        self.when = QtWidgets.QLabel("")
        self.when.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        for w in (self.mark, self.text, self.when):
            w.setProperty("keepStyle", True)
        lay.addWidget(self.mark)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.when)
        self.set_state("waiting")

    def set_state(self, state, detail=None):
        glyph, colour, text_colour = _STATE[state]
        self.state = state
        self.mark.setText(glyph)
        self.mark.setStyleSheet("color: %s; font-size: 14px; font-weight: 700; background: transparent;" % colour)
        weight = 700 if state == "running" else 400
        self.text.setStyleSheet("color: %s; font-size: 13px; font-weight: %d; background: transparent;"
                                % (text_colour, weight))
        self.when.setStyleSheet("color: #64748B; font-size: 12px; background: transparent;")
        if state == "running":
            self.started = time.monotonic()
            self.text.setText(detail or self.name)
        elif state == "done" and self.started is not None:
            self.when.setText(_took(time.monotonic() - self.started))
            self.text.setText(self.name if not detail else "%s - %s" % (self.name, detail))
        elif state == "failed":
            self.text.setText("%s - %s" % (self.name, detail) if detail else self.name)


def _took(seconds):
    return ("%.1f s" % seconds) if seconds < 60 else "%d min %02d s" % divmod(int(seconds), 60)


class LoadingPanel(QtWidgets.QFrame):
    """The loading screen. Put it in a QStackedWidget beside the content and switch when ready."""

    def __init__(self, title="Loading", subtitle="", steps: Optional[List[str]] = None, parent=None,
                 compact=False):
        super().__init__(parent)
        self.setObjectName("loadingPanel")
        self.setProperty("keepStyle", True)
        self.setStyleSheet("QFrame#loadingPanel { background: transparent; }")
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(24, 18 if compact else 28, 24, 18)
        outer.addStretch(1)
        box = QtWidgets.QWidget()
        box.setMaximumWidth(620)
        v = QtWidgets.QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        self.title = QtWidgets.QLabel(title)
        self.title.setProperty("keepStyle", True)
        self.title.setStyleSheet("color: #F8FAFC; font-size: %dpx; font-weight: 700; background: transparent;"
                                 % (15 if compact else 18))
        self.subtitle = QtWidgets.QLabel(subtitle)
        self.subtitle.setWordWrap(True)
        self.subtitle.setProperty("keepStyle", True)
        self.subtitle.setStyleSheet("color: #94A3B8; font-size: 12px; background: transparent;")
        self.subtitle.setVisible(bool(subtitle))
        self.bar = AnimatedProgressBar(accent="#22D3EE")
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setRange(0, 0)
        self.steps_box = QtWidgets.QVBoxLayout()
        self.steps_box.setSpacing(2)
        v.addWidget(self.title)
        v.addWidget(self.subtitle)
        v.addWidget(self.bar)
        v.addLayout(self.steps_box)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        row.addWidget(box, 10)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)
        self._rows: List[_StepRow] = []
        self._current: Optional[_StepRow] = None
        self.started = time.monotonic()
        self.set_steps(steps or [])

    # ---- the steps ------------------------------------------------------------------------------
    def set_steps(self, names: List[str]):
        """The steps expected, shown waiting; a step not listed is added when it starts."""
        for r in self._rows:
            r.setParent(None)
            r.deleteLater()
        self._rows, self._current = [], None
        for n in names:
            self._add(n)

    def _add(self, name):
        row = _StepRow(name, self)
        self.steps_box.addWidget(row)
        self._rows.append(row)
        return row

    def start(self, name, detail=None):
        """Finish the running step and run `name` (listed or new)."""
        if self._current is not None and self._current.state == "running":
            self._current.set_state("done")
        row = next((r for r in self._rows if r.name == name and r.state == "waiting"), None) or self._add(name)
        row.set_state("running", detail)
        self._current = row
        self.bar.setRange(0, 0)

    def finish(self, detail=None):
        """The running step is done; the bar stops when nothing else is waiting."""
        if self._current is not None and self._current.state == "running":
            self._current.set_state("done", detail)
        if not any(r.state in ("waiting", "running") for r in self._rows):
            self.bar.setRange(0, 1)
            self.bar.setValue(1)

    def fail(self, reason):
        if self._current is not None:
            self._current.set_state("failed", reason)
        else:
            self._add("Could not finish").set_state("failed", reason)
        self.bar.setRange(0, 1)
        self.bar.setValue(0)

    def report(self, message, done=0, total=0):
        """A worker's report: "step:<name>" opens a step, anything else updates the running one;
        counts turn the bar into a real fraction."""
        message = str(message or "")
        if message.startswith(STEP_PREFIX):
            self.start(message[len(STEP_PREFIX):].strip())
            return
        if self._current is None:
            self.start(message or "Working")
        elif message:
            self._current.text.setText(message)
        if total:
            self.bar.setRange(0, int(total))
            self.bar.setValue(int(done))

    def restart(self, title=None, subtitle=None, steps=None):
        if title is not None:
            self.title.setText(title)
        if subtitle is not None:
            self.subtitle.setText(subtitle)
            self.subtitle.setVisible(bool(subtitle))
        self.started = time.monotonic()
        self.set_steps(steps or [])
        self.bar.setRange(0, 0)
