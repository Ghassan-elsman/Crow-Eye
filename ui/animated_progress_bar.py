"""A progress bar that never looks frozen while work is running.

A plain QProgressBar only moves when a value arrives. A parser that takes three
minutes between two steps leaves it static for three minutes, and the
investigator cannot tell "working" from "hung". AnimatedProgressBar is a drop-in
replacement that keeps a light sweep moving across it at all times:

  * value > 0    a soft bright band sweeps across the FILLED part;
  * busy / 0     a segment glides back and forth across the groove;
  * finished     still (value == maximum), or setAnimated(False).

The percentage is never faked - only the motion is continuous.

Two things drive the frames:

  * one shared QTimer (~30 fps) for every visible bar, which runs whenever the
    GUI thread is free (workers, child processes, nested event loops);
  * keep_alive(), for when the GUI thread itself is busy - filling tens of
    thousands of table rows blocks every timer. Hot loops (and every print()
    captured by the loading dialog) call it; it repaints synchronously WITHOUT
    running the event loop, so nothing re-enters the code that is loading, and
    it tells Windows the thread is alive so the window is not ghosted as
    "Not Responding".

Frames read their phase from the clock, not a frame counter, so the motion is
the same whichever of the two delivers them.
"""

import math
import sys
import time
import weakref

from PyQt5 import QtCore, QtGui, QtWidgets

_FRAME_S = 0.033              # ~30 fps
_SWEEP_S = 1.6                # one pass of the band across the filled part
_SWEEP_PAUSE_S = 0.35         # rest between passes
_GLIDE_S = 1.8                # one traverse of the busy segment
_EASE_S = 0.35                # value changes glide over this long

_bars = weakref.WeakSet()
_frame_callbacks = []         # weakref.WeakMethod / plain callables
_ticker = None
_last_frame = 0.0
_last_peek = 0.0


def _on_gui_thread():
    app = QtWidgets.QApplication.instance()
    return app is not None and QtCore.QThread.currentThread() is app.thread()


def _run_callbacks():
    dead = []
    for ref in list(_frame_callbacks):
        fn = ref() if isinstance(ref, weakref.WeakMethod) else ref
        if fn is None:
            dead.append(ref)
            continue
        try:
            fn()
        except Exception:
            pass
    for ref in dead:
        try:
            _frame_callbacks.remove(ref)
        except ValueError:
            pass


def add_frame_callback(fn):
    """Run `fn()` on every animation frame (timer or keep_alive). Bound methods
    are held weakly, so a closed dialog drops out by itself."""
    ref = weakref.WeakMethod(fn) if hasattr(fn, "__self__") else fn
    _frame_callbacks.append(ref)
    _ensure_ticker()
    return ref


def remove_frame_callback(ref):
    try:
        _frame_callbacks.remove(ref)
    except ValueError:
        pass


def _tick():
    """Timer frame: the event loop is running, so a plain update() suffices."""
    global _last_frame
    _last_frame = time.monotonic()
    _run_callbacks()
    alive = False
    for bar in list(_bars):
        try:
            if bar.isVisible():
                bar._advance()
                bar.update()
                alive = True
        except RuntimeError:          # C++ side already deleted
            pass
    if not alive and not _frame_callbacks and _ticker is not None:
        _ticker.stop()


def _ensure_ticker():
    global _ticker
    if not _on_gui_thread():
        return
    if _ticker is None:
        _ticker = QtCore.QTimer()
        _ticker.setTimerType(QtCore.Qt.PreciseTimer)
        _ticker.timeout.connect(_tick)
    if not _ticker.isActive():
        _ticker.start(int(_FRAME_S * 1000))


def _peek_messages():
    """Tell Windows this thread still services its queue, without dispatching
    anything: PM_NOREMOVE looks and leaves. Without it a GUI thread busy for
    5 s is ghosted as "Not Responding" and the ghost hides every repaint."""
    global _last_peek
    now = time.monotonic()
    if now - _last_peek < 1.0 or sys.platform != "win32":
        return
    _last_peek = now
    try:
        import ctypes
        from ctypes import wintypes
        msg = wintypes.MSG()
        ctypes.windll.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # PM_NOREMOVE
    except Exception:
        pass


def keep_alive():
    """Advance every visible animation one frame while the GUI thread is busy.

    Cheap enough to call per row: it does nothing off the GUI thread, and
    nothing until a frame interval has passed. It never runs the event loop.
    """
    global _last_frame
    if not _bars and not _frame_callbacks:
        return
    now = time.monotonic()
    if now - _last_frame < _FRAME_S:
        return
    if not _on_gui_thread():
        return
    _last_frame = now
    _peek_messages()
    _run_callbacks()
    for bar in list(_bars):
        try:
            if bar.isVisible():
                bar._advance()
                bar.repaint()
        except RuntimeError:
            pass


class AnimatedProgressBar(QtWidgets.QProgressBar):
    """QProgressBar with a continuous light sweep. Drop-in: same API.

    setRange(0, 0) means "busy" exactly as for QProgressBar, but the real range
    stays 0..100 so the stylesheet still draws the groove and the text; the
    gliding segment supplies the motion. minimum()/maximum() report 0/0 while
    busy, so code that tests for indeterminate mode keeps working.
    """

    def __init__(self, parent=None, accent="#00FFFF"):
        super().__init__(parent)
        self._busy = False
        self._animated = True
        self._accent = QtGui.QColor(accent)
        # How far the motion sits inside the bar's edge: 2 px clears the
        # 2 px border most bars draw; a borderless pill uses 0 (setInset).
        self._inset = 2
        self._t0 = time.monotonic()
        self._target = super().value()
        self._from = self._target
        self._ease_start = 0.0
        self.paint_count = 0          # read by the tests
        _bars.add(self)

    # -- API -----------------------------------------------------------------
    def setAccent(self, color):
        self._accent = QtGui.QColor(color)
        self.update()

    def accent(self):
        return QtGui.QColor(self._accent)

    def setInset(self, px):
        """0 for a borderless pill: the sweep then fills it edge to edge,
        with fully rounded ends."""
        self._inset = max(0, int(px))
        self.update()

    def setAnimated(self, on):
        self._animated = bool(on)
        self.update()

    def isAnimated(self):
        return self._animated

    def isBusy(self):
        return self._busy

    def setRange(self, minimum, maximum):
        if minimum == 0 and maximum == 0:
            self._busy = True
            super().setRange(0, 100)
            self._set_now(0)
        else:
            self._busy = False
            super().setRange(minimum, maximum)
            self._target = max(minimum, min(self._target, maximum))
        self.update()

    def setMinimum(self, minimum):
        self.setRange(minimum, super().maximum())

    def setMaximum(self, maximum):
        self.setRange(super().minimum(), maximum)

    def minimum(self):
        return 0 if self._busy else super().minimum()

    def maximum(self):
        return 0 if self._busy else super().maximum()

    def value(self):
        return self._target

    def setValue(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return
        lo, hi = super().minimum(), super().maximum()
        value = max(lo, min(value, hi))
        if self._busy:
            self._target = value
            return
        shown = super().value()
        if not self.isVisible() or value < shown or shown < lo:
            # Hidden, reset, or going back: no glide.
            self._set_now(value)
            return
        self._from = shown
        self._target = value
        self._ease_start = time.monotonic()
        _ensure_ticker()

    def reset(self):
        super().reset()
        self._target = self._from = super().value()

    def _set_now(self, value):
        self._target = self._from = value
        self._ease_start = 0.0
        super().setValue(value)

    # -- frames --------------------------------------------------------------
    def _advance(self):
        """Move the displayed value toward the target (ease-out)."""
        if self._busy:
            return
        shown = super().value()
        if shown == self._target:
            return
        t = (time.monotonic() - self._ease_start) / _EASE_S if self._ease_start else 1.0
        if t >= 1.0:
            super().setValue(self._target)
            return
        k = 1.0 - (1.0 - t) ** 3
        super().setValue(int(round(self._from + (self._target - self._from) * k)))

    def showEvent(self, event):
        super().showEvent(event)
        _bars.add(self)
        _ensure_ticker()

    def paintEvent(self, event):
        super().paintEvent(event)
        self.paint_count += 1
        if not self._animated:
            return
        lo, hi = super().minimum(), super().maximum()
        shown = super().value()
        finished = (not self._busy) and hi > lo and shown >= hi
        if finished:
            return

        i = self._inset
        inner = self.rect().adjusted(i, i, -i, -i)
        if inner.width() <= 4 or inner.height() <= 2:
            return
        if i:
            radius = max(2.0, min(6.0, inner.height() / 2.0 - 1))
        else:
            radius = inner.height() / 2.0
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(QtCore.QRectF(inner), radius, radius)

        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setClipPath(clip)
        now = time.monotonic() - self._t0

        frac = 0.0 if self._busy or hi <= lo else (shown - lo) / float(hi - lo)
        if self._busy or frac <= 0.0:
            self._paint_glide(p, inner, now)
        else:
            filled = QtCore.QRectF(inner.x(), inner.y(), inner.width() * frac, inner.height())
            self._paint_sweep(p, filled, now)
        p.end()

    def _paint_glide(self, p, inner, now):
        """Busy / nothing yet: a feathered accent segment gliding left <-> right."""
        seg_w = max(24.0, inner.width() * 0.28)
        travel = inner.width() + seg_w
        # Sine ease over a there-and-back cycle.
        phase = (now % (2 * _GLIDE_S)) / (2 * _GLIDE_S)
        pos = (1 - math.cos(phase * 2 * math.pi)) / 2.0           # 0..1..0
        x = inner.x() - seg_w + travel * pos
        rect = QtCore.QRectF(x, inner.y(), seg_w, inner.height())
        c = QtGui.QColor(self._accent)
        g = QtGui.QLinearGradient(rect.left(), 0, rect.right(), 0)
        for stop, alpha in ((0.0, 0), (0.25, 110), (0.5, 190), (0.75, 110), (1.0, 0)):
            c.setAlpha(alpha)
            g.setColorAt(stop, QtGui.QColor(c))
        p.fillRect(rect, g)
        self._paint_text_again(p)

    def _paint_sweep(self, p, filled, now):
        """Progress present: a soft bright band crossing the filled part."""
        if filled.width() < 6:
            return
        cycle = _SWEEP_S + _SWEEP_PAUSE_S
        t = (now % cycle) / _SWEEP_S
        if t > 1.0:
            return                                              # resting
        band_w = max(30.0, filled.width() * 0.18)
        x = filled.x() - band_w + (filled.width() + band_w) * t
        band = QtCore.QRectF(x, filled.y(), band_w, filled.height()).intersected(filled)
        if band.isEmpty():
            return
        g = QtGui.QLinearGradient(x, 0, x + band_w, 0)
        g.setColorAt(0.0, QtGui.QColor(255, 255, 255, 0))
        g.setColorAt(0.5, QtGui.QColor(255, 255, 255, 105))
        g.setColorAt(1.0, QtGui.QColor(255, 255, 255, 0))
        p.fillRect(band, g)

    def _paint_text_again(self, p):
        """The glide segment is opaque enough to wash out the label beneath
        it, so the label is drawn once more on top, in the bar's own text
        colour (a stylesheet `color:` lands in the palette)."""
        if not self.isTextVisible():
            return
        text = self.text()
        if not text:
            return
        p.setClipping(False)
        p.setFont(self.font())
        p.setPen(self.palette().color(QtGui.QPalette.Text))
        # Centred: every Crow-Eye bar centres its text, mostly through a
        # stylesheet `text-align`, which alignment() does not report.
        p.drawText(QtCore.QRectF(self.rect()), QtCore.Qt.AlignCenter, text)

    def text(self):
        # Busy bars keep their real 0..100 range internally; "%p%" would read
        # "0%" while nothing is known, so busy shows the format only if it has
        # no placeholder in it.
        if self._busy:
            fmt = self.format()
            return "" if ("%p" in fmt or "%v" in fmt or "%m" in fmt) else fmt
        return super().text()
