"""The whole of a log, not the tail of it.

The Settings -> Logs viewer shows the last 256 KB of a file so that selecting a
large log never stalls the dialog. That is the right default and the wrong
answer when the line you need is older than the last 256 KB, which is exactly
when anyone goes looking. This opens the selection in full:

  * a single file, together with its rotated backups (`crow_eye.log.3` through
    `crow_eye.log.1` and then `crow_eye.log`, oldest first, so the result reads
    as one continuous run rather than three files in reverse);
  * or every file in a component group, when a group is what was selected.

Loading happens on a worker thread and arrives in chunks, so a large file draws
progressively instead of freezing the GUI while it is read.
"""
import os
import re

from PyQt5 import QtCore, QtGui, QtWidgets


# Rotated siblings look like "<name>.1", "<name>.2"... Sorted oldest first so a
# concatenated read runs forwards in time.
_ROTATION = re.compile(r"^(?P<base>.+?)\.(?P<n>\d+)$")


def rotation_siblings(path):
    """[paths] for `path` and its rotated backups, oldest first.

    `crow_eye.log` with backups 1..3 returns .3, .2, .1, then the live file.
    A path that is itself a backup is resolved against its own base name, so
    selecting `crow_eye.log.2` still shows the whole history.
    """
    if not path:
        return []
    directory = os.path.dirname(path)
    name = os.path.basename(path)
    m = _ROTATION.match(name)
    base = m.group("base") if m else name
    live = os.path.join(directory, base)

    numbered = []
    try:
        for fn in os.listdir(directory or "."):
            mm = _ROTATION.match(fn)
            if mm and mm.group("base") == base:
                numbered.append((int(mm.group("n")), os.path.join(directory, fn)))
    except OSError:
        pass
    # Highest backup number is the oldest data.
    numbered.sort(key=lambda t: -t[0])

    out = [p for _n, p in numbered if os.path.exists(p)]
    if os.path.exists(live):
        out.append(live)
    return out or ([path] if os.path.exists(path) else [])


class _Reader(QtCore.QThread):
    """Reads the files off the GUI thread and hands back decoded chunks."""

    chunk = QtCore.pyqtSignal(str)
    done = QtCore.pyqtSignal(int, int)          # files read, bytes read
    failed = QtCore.pyqtSignal(str)

    CHUNK = 512 * 1024

    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self._paths = list(paths)
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        read_files = 0
        read_bytes = 0
        try:
            for path in self._paths:
                if self._stop:
                    break
                header = "\n===== %s =====\n" % path
                self.chunk.emit(header if read_files else header.lstrip("\n"))
                read_files += 1
                try:
                    with open(path, "rb") as fh:
                        while not self._stop:
                            data = fh.read(self.CHUNK)
                            if not data:
                                break
                            read_bytes += len(data)
                            self.chunk.emit(data.decode("utf-8", errors="replace"))
                except OSError as exc:
                    self.chunk.emit("  [could not read this file: %s]\n" % exc)
            self.done.emit(read_files, read_bytes)
        except Exception as exc:                # never take the GUI down with it
            self.failed.emit(str(exc))


class FullLogDialog(QtWidgets.QDialog):
    """Read-only, searchable view of one log section in full."""

    def __init__(self, title, paths, parent=None):
        super().__init__(parent)
        self._paths = [p for p in (paths or []) if p]
        self._reader = None
        self._matches = 0

        self.setWindowTitle("Crow Eye - %s" % title)
        # Minimize as well as maximize: a log you are comparing against
        # something else belongs in the taskbar like any other window.
        self.setWindowFlags(QtCore.Qt.Window
                            | QtCore.Qt.WindowMinimizeButtonHint
                            | QtCore.Qt.WindowMaximizeButtonHint
                            | QtCore.Qt.WindowCloseButtonHint)
        # Owned windows get no taskbar button on Windows, whatever their title
        # says - so a minimized Crow-Eye window had nowhere to show its name.
        # See CrowEyeStyles.give_window_a_taskbar_button for the measurements.
        try:
            from styles import CrowEyeStyles as _CES
            _CES.give_window_a_taskbar_button(self)
        except Exception:
            pass
        self.resize(1100, 760)
        self.setMinimumSize(700, 420)

        self._build_ui(title)
        self._start_load()

        # Must be last: the helper restyles the dialog's children, and anything
        # built after it keeps Qt's default white chrome.
        try:
            from correlation_engine.gui.ui_styling import CorrelationEngineStyles
            CorrelationEngineStyles.apply_evidence_detail_styling(self)
        except Exception:
            pass

    # ---- ui ---------------------------------------------------------------
    def _build_ui(self, title):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        heading = QtWidgets.QLabel(title)
        heading.setStyleSheet(
            "QLabel { color: #E2E8F0; font-size: 15px; font-weight: 700; }")
        layout.addWidget(heading)

        sub = "%d file%s" % (len(self._paths), "" if len(self._paths) == 1 else "s")
        self._sub = QtWidgets.QLabel("%s - reading..." % sub)
        self._sub.setStyleSheet("QLabel { color: #64748B; font-size: 11px; }")
        self._sub.setWordWrap(True)
        layout.addWidget(self._sub)

        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(8)
        self._find = QtWidgets.QLineEdit()
        self._find.setPlaceholderText("Find in this log...")
        self._find.returnPressed.connect(self._find_next)
        self._find.textChanged.connect(self._highlight_all)
        bar.addWidget(self._find, 1)
        for label, slot in (("Find next", self._find_next),
                            ("Find previous", self._find_prev),
                            ("Copy all", self._copy_all),
                            ("Save as...", self._save_as)):
            btn = QtWidgets.QPushButton(label)
            btn.clicked.connect(slot)
            bar.addWidget(btn)
        layout.addLayout(bar)

        self._view = QtWidgets.QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        # A log is only readable in a fixed-width face; the byte columns and the
        # timestamps line up or they do not.
        self._view.setStyleSheet("""
            QPlainTextEdit { background-color: #0B1226; color: #CBD5E1;
                             border: 1px solid #334155; border-radius: 6px;
                             font-family: 'JetBrains Mono','Consolas',monospace;
                             font-size: 12px; }
            QScrollBar:vertical { background: #0B1226; width: 11px; margin: 0; border: none; }
            QScrollBar:horizontal { background: #0B1226; height: 11px; margin: 0; border: none; }
            QScrollBar::handle:vertical { background: #334155; border-radius: 5px; min-height: 30px; }
            QScrollBar::handle:horizontal { background: #334155; border-radius: 5px; min-width: 30px; }
            QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: #475569; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; background: none; border: none; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; background: none; border: none; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: #0B1226; }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: #0B1226; }
            QScrollBar::corner { background: #0B1226; }
        """)
        layout.addWidget(self._view, 1)

        close_row = QtWidgets.QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.close)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    # ---- loading ----------------------------------------------------------
    def _start_load(self):
        if not self._paths:
            self._view.setPlainText("Nothing to show: no log files in this selection.")
            self._sub.setText("0 files")
            return
        self._reader = _Reader(self._paths, self)
        self._reader.chunk.connect(self._append, QtCore.Qt.QueuedConnection)
        self._reader.done.connect(self._on_done, QtCore.Qt.QueuedConnection)
        self._reader.failed.connect(self._on_failed, QtCore.Qt.QueuedConnection)
        self._reader.start()

    def _append(self, text):
        self._view.appendPlainText(text.rstrip("\n"))

    def _on_done(self, files, size):
        self._sub.setText("%d file%s, %s - complete\n%s"
                          % (files, "" if files == 1 else "s",
                             self._human(size), "\n".join(self._paths)))
        self._view.moveCursor(QtGui.QTextCursor.End)

    def _on_failed(self, message):
        self._sub.setText("Could not finish reading: %s" % message)

    @staticmethod
    def _human(n):
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return "%.0f %s" % (n, unit) if unit == "B" else "%.1f %s" % (n, unit)
            n /= 1024.0
        return "%d B" % n

    # ---- find -------------------------------------------------------------
    def _highlight_all(self):
        """Mark every occurrence, so the density of hits is visible at a glance."""
        needle = self._find.text()
        extra = []
        if needle:
            fmt = QtGui.QTextCharFormat()
            fmt.setBackground(QtGui.QColor("#1E3A5F"))
            fmt.setForeground(QtGui.QColor("#00FFFF"))
            doc = self._view.document()
            cursor = QtGui.QTextCursor(doc)
            while True:
                cursor = doc.find(needle, cursor)
                if cursor.isNull():
                    break
                sel = QtWidgets.QTextEdit.ExtraSelection()
                sel.cursor = cursor
                sel.format = fmt
                extra.append(sel)
                if len(extra) >= 5000:      # a needle like "e" should not hang the view
                    break
        self._matches = len(extra)
        self._view.setExtraSelections(extra)

    def _find_next(self):
        self._step(False)

    def _find_prev(self):
        self._step(True)

    def _step(self, backwards):
        needle = self._find.text()
        if not needle:
            return
        flags = QtGui.QTextDocument.FindFlags()
        if backwards:
            flags |= QtGui.QTextDocument.FindBackward
        if not self._view.find(needle, flags):
            # Wrap around rather than stopping silently at the end.
            cursor = self._view.textCursor()
            cursor.movePosition(QtGui.QTextCursor.End if backwards
                                else QtGui.QTextCursor.Start)
            self._view.setTextCursor(cursor)
            self._view.find(needle, flags)

    # ---- actions ----------------------------------------------------------
    def _copy_all(self):
        QtWidgets.QApplication.clipboard().setText(self._view.toPlainText())

    def _save_as(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save log as", "crow_eye_log.txt", "Text files (*.txt);;All files (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", errors="replace") as fh:
                fh.write(self._view.toPlainText())
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Save log", "Could not save:\n%s" % exc)

    # ---- lifetime ---------------------------------------------------------
    def closeEvent(self, event):
        if self._reader is not None:
            self._reader.stop()
            self._reader.wait(2000)
        super().closeEvent(event)
