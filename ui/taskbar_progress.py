"""Progress on the Windows taskbar button, and a colour on the Crow-Eye icon.

Crow-Eye's loading window no longer blocks the app, so a long parse usually runs
with the window minimized or behind something else. This puts how far along it is
where it can be seen without switching to it.

Two halves, because Windows will only do half of it:

* **The percentage goes on the native taskbar progress bar.** It fills the whole
  taskbar button and is unmissable.
* **The phase goes on the icon**, as a coloured strip composited into the
  Crow-Eye icon: green while parsing, blue while loading.

The split is not a preference. The taskbar progress bar's colour is painted by
the shell from its state - green for normal, yellow for paused, red for error -
and there is no API for any other colour. `QWinTaskbarProgress` exposes
`setValue`/`setRange`/`pause`/`stop`/`resume` and nothing else, and the
`ITaskbarList3::SetProgressState` beneath it has exactly those four flags. Blue
is only possible in pixels we draw ourselves.

Windows-only, and never fatal: an operation that runs without a taskbar
indicator is fine, an operation that fails to start because of one is not.
"""
import sys

from PyQt5 import QtCore, QtGui, QtWidgets

PARSING = "parsing"
LOADING = "loading"

# The app's own palette (styles.Colors): SUCCESS green, ACCENT_BLUE blue.
_PHASE_COLOURS = {
    PARSING: "#10B981",
    LOADING: "#3B82F6",
}

# Sizes Windows asks for. The strip is drawn into each one separately rather
# than drawn once and downscaled: a bar that reads well at 256 is a smudge by
# the time it reaches 16, and 16 is the size a crowded taskbar actually shows.
_ICON_SIZES = (16, 20, 24, 32, 48, 64, 128, 256)


def _is_windows():
    return sys.platform.startswith("win")


class TaskbarProgress(QtCore.QObject):
    """Drives the taskbar button and the window icon for the main window.

    Reference-counted: several operations can be in flight at once (a parse can
    open a second dialog, and the offline path turns one dialog from a scan into
    a parse mid-life), so the indicator clears when the last of them ends rather
    than when the first does.
    """

    def __init__(self):
        super().__init__()
        self._window = None
        self._button = None
        self._base_icon = None
        # [phase, percent] per operation in flight, innermost last. The
        # percentage is held per operation, not globally: Parse All opens a
        # second dialog part-way through, and a single figure would be reset
        # to zero by the inner one and never recovered when it closed.
        self._active = []
        self._last_drawn = None      # (phase, percent) actually painted

    # ---- lifetime ----------------------------------------------------------
    def begin(self, phase=LOADING):
        """An operation started. Returns a token to pass back to end()."""
        if phase not in _PHASE_COLOURS:
            phase = LOADING
        self._active.append([phase, 0])
        self._show(0)
        return len(self._active)

    def set_phase(self, phase):
        """Change the current operation's phase - a scan that became a parse.

        A phase that is already current is not a change. _repaint() forces a
        rebuild past the throttle by design, so a caller that reasserts its
        phase on every progress update - which the image dialog does, having
        no single point where its parse starts - would rebuild eight pixmaps
        per update and throw the throttle away.
        """
        if phase not in _PHASE_COLOURS or not self._active:
            return
        if self._active[-1][0] == phase:
            return
        self._active[-1][0] = phase
        self._repaint()

    def set_value(self, completed, total):
        """Report progress. Ignores nonsense rather than drawing it."""
        try:
            completed = int(completed)
            total = int(total)
        except (TypeError, ValueError):
            return
        if total <= 0:
            return
        completed = max(0, min(completed, total))
        self._show(int(completed * 100 / total))

    def set_percent(self, percent):
        try:
            percent = int(percent)
        except (TypeError, ValueError):
            return
        self._show(max(0, min(100, percent)))

    def end(self, _token=None):
        """An operation finished. Clears only when the last one has."""
        if self._active:
            self._active.pop()
        if self._active:
            # An outer operation is still running: back to its colour and to
            # where it had got to, not to zero.
            self._repaint()
            return
        self._clear()

    def reset(self):
        """Forget everything. For a hard stop, and for tests."""
        self._active = []
        self._clear()

    def _repaint(self):
        """Redraw the innermost operation, past the throttle.

        _last_drawn exists to stop a rebuild when nothing changed, so a repaint
        that is wanted for another reason - a new colour, or a different
        operation now being the innermost - has to clear it first.
        """
        if not self._active:
            return
        self._last_drawn = None
        self._show(self._active[-1][1])

    # ---- the native bar ----------------------------------------------------
    def _main_window(self):
        """The main window, not whatever happens to be in front.

        Dialogs are parented to `QApplication.activeWindow()` in several places,
        which during a parse is another dialog - so the parent chain is not a
        reliable route to the window that owns the taskbar button.
        """
        if self._window is not None:
            try:
                if self._window.isVisible() or self._window.windowHandle():
                    return self._window
            except RuntimeError:              # the C++ object went away
                self._window = None
        app = QtWidgets.QApplication.instance()
        if app is None:
            return None
        for widget in app.topLevelWidgets():
            if isinstance(widget, QtWidgets.QMainWindow):
                self._window = widget
                return widget
        return None

    def _progress(self):
        if not _is_windows():
            return None
        window = self._main_window()
        if window is None:
            return None
        try:
            handle = window.windowHandle()
            if handle is None:
                window.winId()                # realise it
                handle = window.windowHandle()
            if handle is None:
                return None
            if self._button is None:
                from PyQt5.QtWinExtras import QWinTaskbarButton
                self._button = QWinTaskbarButton(self)
            self._button.setWindow(handle)
            progress = self._button.progress()
            progress.setRange(0, 100)
            return progress
        except Exception:
            return None

    # ---- the icon ----------------------------------------------------------
    def _icon(self):
        if self._base_icon is None:
            try:
                from styles import CrowEyeStyles
                self._base_icon = CrowEyeStyles.crow_eye_icon()
            except Exception:
                self._base_icon = None
        return self._base_icon

    def _composite(self, phase, percent):
        """The Crow-Eye icon with a progress strip across the bottom."""
        base = self._icon()
        if base is None:
            return None
        colour = QtGui.QColor(_PHASE_COLOURS.get(phase, _PHASE_COLOURS[LOADING]))
        # The empty part of the bar is the phase colour dimmed, not black.
        # The Crow-Eye artwork is nearly black along its bottom edge, so a
        # dark track over it is invisible - at 0% the icon looked untouched
        # and there was no way to tell the operation had started at all.
        track = QtGui.QColor(colour)
        track.setRgb(colour.red() // 4, colour.green() // 4, colour.blue() // 4)
        out = QtGui.QIcon()
        for size in _ICON_SIZES:
            pixmap = base.pixmap(size, size)
            if pixmap.isNull():
                continue
            pixmap = QtGui.QPixmap(pixmap)     # copy: never paint on the source
            # A fixed fraction of the height, but never less than two pixels -
            # at 16px a "12% tall" bar rounds to one and disappears.
            bar_h = max(2, int(round(size * 0.18)))
            painter = QtGui.QPainter(pixmap)
            try:
                painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
                painter.setPen(QtCore.Qt.NoPen)
                top = pixmap.height() - bar_h
                painter.fillRect(0, top, pixmap.width(), bar_h, track)
                filled = int(round(pixmap.width() * max(0, min(100, percent)) / 100.0))
                if filled > 0:
                    painter.fillRect(0, top, filled, bar_h, colour)
            finally:
                painter.end()
            out.addPixmap(pixmap)
        return out

    def _paint_icon(self, percent):
        if not self._active:
            return
        phase = self._active[-1][0]
        if self._last_drawn == (phase, percent):
            return                              # nothing changed; do not repaint
        self._last_drawn = (phase, percent)
        icon = self._composite(phase, percent)
        window = self._main_window()
        if icon is None or window is None:
            return
        try:
            window.setWindowIcon(icon)
        except Exception:
            pass

    # ---- both --------------------------------------------------------------
    def _show(self, percent):
        if self._active:
            self._active[-1][1] = percent
        progress = self._progress()
        if progress is not None:
            try:
                progress.setValue(percent)
                progress.show()
            except Exception:
                pass
        self._paint_icon(percent)

    def _clear(self):
        self._last_drawn = None
        progress = self._progress()
        if progress is not None:
            try:
                progress.reset()
                progress.hide()
            except Exception:
                pass
        window = self._main_window()
        icon = self._icon()
        if window is not None and icon is not None:
            try:
                window.setWindowIcon(icon)      # the plain icon back
            except Exception:
                pass


_instance = None


def taskbar():
    """The one controller. Cheap to call; builds nothing until it is used."""
    global _instance
    if _instance is None:
        _instance = TaskbarProgress()
    return _instance
