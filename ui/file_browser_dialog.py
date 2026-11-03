"""File Browser: browse the examined machine's file system, and collect from it.

Four ways to reach it:

- This machine - any drive of the running computer;
- Shadow copy - any shadow copy of this machine's volumes: the ones Windows exposes,
  through their own device, and the ones it keeps only in the volume's catalog,
  rebuilt from their store (the Shadow Copies window lists both);
- Forensic image - a partition of an E01 / VHD(X) / VMDK / raw image, or one of
  that partition's own shadow copies;
- Saved listing - the case's parsed $MFT: the machine's whole file system as it
  was when the case was parsed, browsable later with no access to the machine,
  deleted entries the MFT still holds included (marked).

Whatever is selected, the panel on the right says what the case's parsed artifacts
record about it (related_artifacts.py): executed, present, opened, deleted.

Ticked files and folders are collected into the case by App Acquisition's
collector (chain of custody, SHA-256, manifest), and from a shadow copy they can
also be restored to this machine (restore.py: never over a file, hashed, in the
custody ledger). A saved listing holds names, sizes and times but not contents,
so it offers the listing itself (CSV).
"""
from __future__ import annotations

import csv
import os
from typing import Dict, List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

try:
    from ui import app_theme as _theme
except Exception:   # pragma: no cover
    _theme = None

_MAX_ROWS = 5000
_REL = QtCore.Qt.UserRole
_LOADED = QtCore.Qt.UserRole + 1


def _human(n) -> str:
    if n is None:
        return ""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return ""


def _when(text) -> str:
    """'2026-10-29T17:15:23.48+00:00' -> '2026-10-29 17:15:23' (UTC)."""
    if not text:
        return ""
    return str(text).replace("T", " ")[:19]


# A source chip: a volume, "now", or a shadow copy. Its colour is what it is - indigo a volume,
# cyan the live moment, the shadow-copy yellow a copy (the Shadow Copies window's colour) - and a
# chosen chip takes a 2 px border and a tinted fill, so the open source is seen at a glance.
CHIP_QSS = """
QPushButton { background: #111A2E; color: #CBD5E1; border: 1px solid #24314A; border-radius: 12px;
              padding: 7px 14px 7px 10px; text-align: left; }
QPushButton:hover { border-color: %(c)s; color: #F8FAFC; }
QPushButton:checked { background: %(bg)s; border: 2px solid %(c)s; color: #F8FAFC; }
QPushButton:disabled { color: #475569; border-color: #1E293B; }
"""
VOLUME_C, NOW_C, COPY_C = "#818CF8", "#22D3EE", "#FACC15"


def _tint(colour, alpha=0.18):
    c = QtGui.QColor(colour)
    return "rgba(%d, %d, %d, %.2f)" % (c.red(), c.green(), c.blue(), alpha)


def make_chip(title, detail, icon=None, colour=VOLUME_C, tip=None):
    chip = QtWidgets.QPushButton("%s\n%s" % (title, detail) if detail else title)
    chip.setCheckable(True)
    chip.setProperty("keepStyle", True)
    chip.setStyleSheet(CHIP_QSS % {"c": colour, "bg": _tint(colour)})
    chip.setCursor(QtCore.Qt.PointingHandCursor)
    if icon:
        try:
            from ui.artifact_icons import artifact_icon
            ic = artifact_icon(icon, colour)
            if ic is not None:
                chip.setIcon(ic)
                chip.setIconSize(QtCore.QSize(22, 22))
        except Exception:
            pass
    if tip:
        chip.setToolTip(tip)
    return chip


def volume_facts(letter):
    """(total bytes, label, file system) of a mounted volume, as far as Windows says."""
    import shutil
    letter = letter.rstrip(":\\")
    root = letter + ":\\"
    total, label, fs = 0, "", ""
    try:
        total = shutil.disk_usage(root).total
    except OSError:
        pass
    if os.name == "nt":
        try:
            import ctypes
            name, fsname = ctypes.create_unicode_buffer(261), ctypes.create_unicode_buffer(261)
            if ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(root), name, 261, None, None, None,
                                                            fsname, 261):
                label, fs = name.value, fsname.value
        except Exception:
            pass
    return total, label, fs


_SHARE = QtCore.Qt.UserRole + 5        # the Share column: (fraction or None, provisional)
SIZE_COL, SHARE_COL = 1, 2


def root_prefix(source) -> str:
    """Where a path starts for this source: 'C:\\' for a volume or one of its shadow copies, the
    partition for an image."""
    if source is None:
        return ""
    copy = getattr(source, "copy", None)
    if copy and copy.get("volume"):
        return "%s:\\" % copy["volume"].rstrip(":\\")
    vol = str(getattr(source, "volume", "") or "")
    if len(vol) == 1 and vol.isalpha():                       # the saved listing's "C"
        return vol.upper() + ":\\"
    if len(vol) >= 2 and vol[1] == ":":
        return vol[:2] + "\\"
    letter = getattr(source, "volume_letter", None)
    if letter:
        return "%s:\\" % str(letter).rstrip(":\\")
    part = getattr(source, "partition_number", None)
    if part is not None and getattr(source, "kind", "") != "hidden_shadow":
        return "Partition %s:\\" % part
    return "\\"

def _no_copy_reasons(copies, current=None, max_age=None):
    """{letter: why it has no shadow copies}, for each volume Windows keeps shadow storage on
    (and the one on screen) that has none - from volsnap's own removal events and the storage
    settings. Runs on the worker; an empty dict when Windows cannot be asked."""
    try:
        import shutil
        from Artifacts_Collectors import shadow_copies as sc, volume_layout as vl
        snap = sc.snapshot(provenance=False, max_age=max_age)
        storage = vl.shadow_storage(snapshot=snap)
        have = {(c.get("volume") or "").rstrip(":\\").upper() for c in copies}
        out = {}
        for letter in set(storage) | ({current} if current else set()):
            if not letter or letter in have:
                continue
            try:
                du = shutil.disk_usage("%s:\\" % letter)
                size, used = du.total, du.used
            except OSError:
                size = used = None
            out[letter] = sc.explain_no_copies(letter, sc.removals(letter, rows=snap.get("removals")),
                                               storage.get(letter), size, used)
        return out
    except Exception:
        return {}


class _ShareDelegate(QtWidgets.QStyledItemDelegate):
    """The Share column: a bar of the entry's share of the folder, and the percentage beside it."""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        data = index.data(_SHARE)
        if not data:
            return
        frac, provisional = data
        if frac is None:
            return
        r = option.rect.adjusted(8, 0, -8, 0)
        text_w = 52
        bar = QtCore.QRectF(r.left(), r.center().y() - 3, max(0, r.width() - text_w - 8), 6)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor("#1E293B"))
        painter.drawRoundedRect(bar, 3, 3)
        fill = QtCore.QRectF(bar.left(), bar.top(), max(2.0 if frac > 0 else 0, bar.width() * min(1.0, frac)), 6)
        painter.setBrush(QtGui.QColor("#64748B" if provisional else "#818CF8"))
        painter.drawRoundedRect(fill, 3, 3)
        painter.setPen(QtGui.QColor("#94A3B8" if provisional else "#E2E8F0"))
        pct = 100.0 * frac
        label = ("%.1f%%" % pct) if pct >= 0.1 or pct == 0 else "<0.1%"
        painter.drawText(QtCore.QRectF(bar.right() + 8, r.top(), text_w, r.height()),
                         QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, ("~" if provisional else "") + label)
        painter.restore()

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        return QtCore.QSize(max(s.width(), 170), s.height())


class _SizesThread(QtCore.QThread):
    """Adds up the open folder's child folders, one by one, in the background: each total goes to
    the table as soon as it is known, a running total every second for a big one, and the walk
    stops the moment the folder is left. Every step on the source is taken under `lock`, because an
    image or a hidden shadow copy reads one file handle the window's own listing also uses."""

    folder = QtCore.pyqtSignal(str, object, object, bool, int)   # rel, bytes, files, final, unreadable
    file_size = QtCore.pyqtSignal(str, object)               # rel, bytes (a file the listing gave none)

    def __init__(self, source, lock, folders, files, parent=None):
        super().__init__(parent)
        self.source, self.lock = source, lock
        self.folders, self.files = folders, files
        self.cancelled = False

    def run(self):
        import time as _t
        for rel in self.files:
            if self.cancelled:
                return
            try:
                with self.lock:
                    size = self.source.size(rel)
            except Exception:
                size = None
            if size is not None:
                self.file_size.emit(rel, size)
        for rel in self.folders:
            if self.cancelled:
                return
            total = files = 0
            last = _t.time()
            failed = False
            self.unreadable = 0
            try:
                walker = self._walk(rel)
                while True:
                    if self.cancelled:
                        return
                    with self.lock:
                        try:
                            _p, size = next(walker)
                        except StopIteration:
                            break
                    total += size or 0
                    files += 1
                    if _t.time() - last > 1.0:
                        last = _t.time()
                        self.folder.emit(rel, total, files, False, self.unreadable)
            except Exception:
                failed = True                    # unknown, never a made-up 0 B
            self.folder.emit(rel, None if failed else total, None if failed else files, True, self.unreadable)

    def _walk(self, rel):
        """(path, size) of every file below `rel`. A live volume or an exposed shadow copy is walked
        here, so a folder Windows refuses to list is counted as unreadable; any other source walks
        itself (its listing says nothing about a refusal)."""
        root = getattr(self.source, "abspath", None)
        if root is None or getattr(self.source, "kind", "") not in ("live", "shadow"):
            yield from self.source.walk_files(rel)
            return
        stack = [root(rel)]
        while stack:
            cur = stack.pop()
            try:
                it = os.scandir(cur)
            except OSError:
                self.unreadable += 1
                continue
            with it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if not entry.is_symlink():
                                stack.append(entry.path)
                        else:
                            yield entry.path, entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        self.unreadable += 1


# Sources whose folder listing reads through Crow-Eye's own NTFS/VSS readers and can take seconds:
# listed off the GUI thread. A live volume answers in milliseconds and is listed in place.
_SLOW_KINDS = ("image", "image_shadow", "hidden_shadow")


class _ListThread(QtCore.QThread):
    listed = QtCore.pyqtSignal(object)

    def __init__(self, source, lock, rel, token, parent=None):
        super().__init__(parent)
        self.source, self.lock, self.rel, self.token = source, lock, rel, token

    def run(self):
        try:
            with self.lock:
                rows = self.source.entries(self.rel)
                isdir = bool(rows) or not self.rel or self.source.isdir(self.rel)
        except Exception:
            rows, isdir = [], False
        self.listed.emit((self.token, self.rel, rows, isdir))


class FileBrowserWidget(QtWidgets.QWidget):
    """Folder tree + folder contents over any app_acquisition source.
    Ticks are kept across folders; checked() returns them. Every folder's size is added up in the
    background as soon as it is shown, and each entry shows its share of the folder."""

    checked_changed = QtCore.pyqtSignal(int)
    selected = QtCore.pyqtSignal(str, bool)        # rel, is_dir: what the related panel describes
    sizing = QtCore.pyqtSignal(int, int)           # folders added up, folders in all
    # A right-click choice the window acts on: (action, [(rel, is_dir), ...]).
    context_action = QtCore.pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        import threading
        self.source = None
        self.current = ""
        self.pages = None
        self.lock = threading.RLock()
        self.folder_sizes: Dict[str, tuple] = {}     # rel.lower() -> (bytes, files, final)
        self.file_sizes: Dict[str, int] = {}         # rel.lower() -> bytes, for files listed without one
        self._checked: Dict[str, bool] = {}     # rel -> is_dir
        self._rows = []
        self._row_of: Dict[str, int] = {}
        self._sizer = None
        self._back: List[str] = []                   # folders visited before this one
        self._forward: List[str] = []
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QtWidgets.QHBoxLayout()
        self.back_btn = QtWidgets.QPushButton("\u2190  Back")
        self.back_btn.setToolTip("The folder you were in before (Alt+Left, or the mouse's back button)")
        self.forward_btn = QtWidgets.QPushButton("Forward  \u2192")
        self.forward_btn.setToolTip("Forward again (Alt+Right)")
        self.up_btn = QtWidgets.QPushButton("\u2191  Up")
        self.up_btn.setToolTip("The folder above this one (Alt+Up)")
        for b in (self.back_btn, self.forward_btn, self.up_btn):
            b.setEnabled(False)
            if _theme is not None:
                _theme.set_variant(b, "ghost")
        self.path_edit = QtWidgets.QLineEdit()
        self.path_edit.setPlaceholderText("The full path, e.g. C:\\Users\\name\\AppData")
        self.path_edit.setToolTip("The full path of the open folder; type one and press Enter to go there")
        self.filter_edit = QtWidgets.QLineEdit()
        self.filter_edit.setPlaceholderText("Filter this folder...")
        self.filter_edit.setMaximumWidth(260)
        bar.setSpacing(8)
        bar.addWidget(self.back_btn)
        bar.addWidget(self.forward_btn)
        bar.addWidget(self.up_btn)
        bar.addWidget(self.path_edit, 1)
        bar.addWidget(self.filter_edit)
        v.addLayout(bar)
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(8)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Folders"])
        self.tree.setUniformRowHeights(True)
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Name", "Size", "Share of this folder", "Modified (UTC)",
                                              "Created (UTC)", "Status"])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setTextElideMode(QtCore.Qt.ElideMiddle)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setItemDelegateForColumn(SHARE_COL, _ShareDelegate(self.table))
        hdr = self.table.horizontalHeader()
        hdr.setHighlightSections(False)
        hdr.setDefaultAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        # The name keeps a readable width of its own (a stretched column is the first to give way
        # when the panel narrows); the last column takes what is left.
        hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.Interactive)
        self.table.setColumnWidth(0, 300)
        for col in (1, 3, 4):
            hdr.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(5, QtWidgets.QHeaderView.Stretch)
        hdr.setMinimumSectionSize(60)
        hdr.setSectionResizeMode(SHARE_COL, QtWidgets.QHeaderView.Fixed)
        self.table.setColumnWidth(SHARE_COL, 170)
        split.addWidget(self.tree)
        split.addWidget(self.table)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 5)
        split.setSizes([300, 760])
        self.pages = QtWidgets.QStackedWidget()
        self.empty = empty = QtWidgets.QLabel("Nothing open yet. Pick a source above - this machine, a forensic image, "
                                              "one of its shadow copies or the case's saved listing - and press Open.")
        empty.setWordWrap(True)
        empty.setAlignment(QtCore.Qt.AlignCenter)
        empty.setMargin(40)
        if _theme is not None:
            _theme.set_role(empty, "muted")
        self.pages.addWidget(empty)
        self.pages.addWidget(split)
        from ui.loading_panel import LoadingPanel
        self.loading = LoadingPanel("Opening", "", compact=True)
        self.pages.addWidget(self.loading)
        self._list_token = 0
        self._list_threads = []
        v.addWidget(self.pages, 1)
        self.note = QtWidgets.QLabel("")
        if _theme is not None:
            _theme.set_role(self.note, "muted")
        v.addWidget(self.note)

        self.up_btn.clicked.connect(self.go_up)
        self.back_btn.clicked.connect(self.go_back)
        self.forward_btn.clicked.connect(self.go_forward)
        for keys, fn in (("Alt+Left", self.go_back), ("Alt+Right", self.go_forward), ("Alt+Up", self.go_up),
                         ("Backspace", self.go_up)):
            sc = QtWidgets.QShortcut(QtGui.QKeySequence(keys), self)
            sc.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.viewport().installEventFilter(self)
        self.tree.viewport().installEventFilter(self)
        self.path_edit.returnPressed.connect(lambda: self.open(self._typed_path()))
        self.filter_edit.textChanged.connect(lambda *_: self._fill())
        self.tree.itemExpanded.connect(self._expand)
        self.tree.itemClicked.connect(lambda item, _c: (self.open(item.data(0, _REL)),
                                                        self.selected.emit(item.data(0, _REL) or "", True)))
        self.table.currentCellChanged.connect(self._current_changed)
        self.table.cellDoubleClicked.connect(self._double_clicked)
        self.table.itemChanged.connect(self._tick_changed)

    # ── navigation ───────────────────────────────────────────────────
    def go_back(self):
        if self._back:
            self._forward.append(self.current)
            self.open(self._back.pop(), record=False)

    def go_forward(self):
        if self._forward:
            self._back.append(self.current)
            self.open(self._forward.pop(), record=False)

    def go_up(self):
        if self.current:
            self.open(self.current.rpartition("\\")[0])

    def _nav_state(self):
        self.back_btn.setEnabled(bool(self._back))
        self.forward_btn.setEnabled(bool(self._forward))
        self.up_btn.setEnabled(bool(self.current))
        if self._back:
            self.back_btn.setToolTip("Back to %s (Alt+Left)" % self.full_path(self._back[-1]))
        if self._forward:
            self.forward_btn.setToolTip("Forward to %s (Alt+Right)" % self.full_path(self._forward[-1]))

    def eventFilter(self, obj, event):
        # The mouse's own back and forward buttons, over the list or the tree.
        if event.type() == QtCore.QEvent.MouseButtonPress:
            if event.button() == QtCore.Qt.BackButton:
                self.go_back()
                return True
            if event.button() == QtCore.Qt.ForwardButton:
                self.go_forward()
                return True
        return super().eventFilter(obj, event)

    # ── right click ──────────────────────────────────────────────────
    def _picked(self, row):
        """The rows the menu is about: the selection, or the row clicked when it is not in it."""
        rows = sorted(set(i.row() for i in self.table.selectedIndexes()))
        if row >= 0 and row not in rows:
            rows = [row]
        out = []
        for r in rows:
            item = self.table.item(r, 0)
            if item is not None and item.data(_REL):
                rel, is_dir = item.data(_REL)
                out.append((rel, bool(is_dir)))
        return out

    def _context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        picks = self._picked(row)
        menu = QtWidgets.QMenu(self)
        if not picks:
            here = [(self.current, True)]
            act = menu.addAction("Acquire this folder with App Acquisition...")
            act.triggered.connect(lambda: self.context_action.emit("acquire", here))
            menu.addAction("Copy this folder's full path").triggered.connect(
                lambda: QtWidgets.QApplication.clipboard().setText(self.full_path(self.current)))
            menu.exec_(self.table.viewport().mapToGlobal(pos))
            return
        one = picks[0] if len(picks) == 1 else None
        what = ("\"%s\"" % one[0].rsplit("\\", 1)[-1]) if one else "%d items" % len(picks)
        if one and one[1]:
            menu.addAction("Open %s" % what).triggered.connect(lambda: self.open(one[0]))
            menu.addSeparator()
        can_copy = bool(self.source and self.source.can_copy)
        if can_copy:
            menu.addAction("Tick %s" % what).triggered.connect(lambda: self._tick(picks, True))
            menu.addAction("Untick %s" % what).triggered.connect(lambda: self._tick(picks, False))
            menu.addSeparator()
            menu.addAction("Acquire %s with App Acquisition..." % what).triggered.connect(
                lambda: self.context_action.emit("acquire", picks))
            if one and one[1]:
                menu.addAction("Find the program installed in %s..." % what).triggered.connect(
                    lambda: self.context_action.emit("find_app", picks))
            menu.addAction("Collect %s into the case" % what).triggered.connect(
                lambda: self.context_action.emit("collect", picks))
            menu.addAction("Recover %s..." % what).triggered.connect(
                lambda: self.context_action.emit("recover", picks))
            menu.addSeparator()
        if getattr(self.source, "kind", "") == "saved":
            gone = [p for p in picks if not p[1] and (self.source._entry(p[0]) or {}).get("deleted")]
            if gone:
                what_gone = ("\"%s\"" % gone[0][0].rsplit("\\", 1)[-1]) if len(gone) == 1 \
                    else "%d deleted files" % len(gone)
                menu.addAction("Recover deleted %s into the case..." % what_gone).triggered.connect(
                    lambda: self.context_action.emit("carve", gone))
                menu.addSeparator()
        menu.addAction("Copy full path" + ("s" if len(picks) > 1 else "")).triggered.connect(
            lambda: QtWidgets.QApplication.clipboard().setText("\n".join(self.full_path(r) for r, _d in picks)))
        menu.exec_(self.table.viewport().mapToGlobal(pos))

    def _tick(self, picks, on):
        want = set(r for r, _d in picks)
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item is not None and item.data(_REL) and item.data(_REL)[0] in want:
                item.setCheckState(QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)

    def show_loading(self, title, subtitle="", steps=None):
        """The loading page in place of the listing (opening a source)."""
        self.loading.restart(title, subtitle, steps or [])
        if steps:
            self.loading.start(steps[0])
        self.pages.setCurrentIndex(2)

    def hide_loading(self, failed=None):
        if failed:
            self.loading.fail(failed)
            return
        self.loading.finish()
        self.pages.setCurrentIndex(1 if self.source is not None else 0)

    # ── source ───────────────────────────────────────────────────────
    def set_source(self, source):
        self._stop_sizing()
        self._back, self._forward = [], []
        self.source = source
        self.folder_sizes = {}
        self.file_sizes = {}
        self._checked.clear()
        self.checked_changed.emit(0)
        self.tree.clear()
        if source is None:
            self.table.setRowCount(0)
            self.pages.setCurrentIndex(0)
            return
        self.pages.setCurrentIndex(1)
        root = QtWidgets.QTreeWidgetItem(["%s  -  %s" % (root_prefix(source).rstrip("\\") or "\\", source.describe())])
        root.setData(0, _REL, "")
        root.addChild(QtWidgets.QTreeWidgetItem(["..."]))
        self.tree.addTopLevelItem(root)
        root.setExpanded(True)
        self.open("")

    def full_path(self, rel) -> str:
        return root_prefix(self.source) + (rel or "")

    def _typed_path(self) -> str:
        text = self.path_edit.text().strip().replace("/", "\\")
        prefix = root_prefix(self.source)
        if prefix and text.lower().startswith(prefix.lower()):
            return text[len(prefix):]
        if len(text) >= 2 and text[1] == ":":                    # another drive letter typed
            return text[2:]
        return text

    def checked(self):
        return sorted(self._checked.items())

    # ── tree ─────────────────────────────────────────────────────────
    def _expand(self, item):
        if item.data(0, _LOADED):
            return
        item.setData(0, _LOADED, True)
        item.takeChildren()
        rel = item.data(0, _REL) or ""
        for e in sorted((e for e in self._entries(rel) if e["is_dir"]), key=lambda e: e["name"].lower())[:_MAX_ROWS]:
            child = QtWidgets.QTreeWidgetItem([e["name"]])
            child.setData(0, _REL, (rel + "\\" + e["name"]) if rel else e["name"])
            child.addChild(QtWidgets.QTreeWidgetItem(["..."]))
            if e.get("deleted"):
                child.setForeground(0, QtGui.QColor("#64748B"))
                child.setToolTip(0, "Deleted: still in the MFT, not in use")
            item.addChild(child)

    def _entries(self, rel):
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            with self.lock:
                return self.source.entries(rel) if self.source is not None else []
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    # ── folder contents ──────────────────────────────────────────────
    def open(self, rel, record=True):
        if self.source is None:
            return
        rel = (rel or "").replace("/", "\\").strip("\\")
        if getattr(self.source, "kind", "") in _SLOW_KINDS:
            # Off the GUI thread; the newest request wins, an older answer is dropped.
            self._list_token += 1
            self.note.setText("Listing %s ..." % self.full_path(rel))
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.BusyCursor)
            t = _ListThread(self.source, self.lock, rel, self._list_token, self)
            t.listed.connect(lambda res, record=record: self._listed(res, record))
            t.finished.connect(lambda t=t: self._list_threads.remove(t) if t in self._list_threads else None)
            self._list_threads.append(t)
            t.start()
            return
        rows = self._entries(rel)
        if rel and not rows and not self.source.isdir(rel):
            self.note.setText("Not found: %s" % self.full_path(rel))
            return
        self._show_folder(rel, rows, record)

    def _listed(self, res, record):
        QtWidgets.QApplication.restoreOverrideCursor()
        token, rel, rows, isdir = res
        if token != self._list_token:
            return
        if rel and not rows and not isdir:
            self.note.setText("Not found: %s" % self.full_path(rel))
            return
        self._show_folder(rel, rows, record)

    def _show_folder(self, rel, rows, record):
        self._stop_sizing()
        if record and self.table.rowCount() and rel != self.current:
            self._back.append(self.current)
            self._forward = []
        self.current = rel
        self._rows = sorted(rows, key=lambda e: (not e["is_dir"], e["name"].lower()))
        self.path_edit.setText(self.full_path(rel))
        self._nav_state()
        self._fill()
        self._start_sizing()

    # ── sizes: added up in the background, shares from them ─────────────
    def _start_sizing(self):
        if self.source is None or getattr(self.source, "kind", "") == "saved" and not hasattr(self.source, "walk_files"):
            return
        base = self.current
        folders = [((base + "\\" + e["name"]) if base else e["name"]) for e in self._rows
                   if e["is_dir"] and not e.get("deleted")
                   and ((base + "\\" + e["name"]) if base else e["name"]).lower() not in self.folder_sizes]
        files = [((base + "\\" + e["name"]) if base else e["name"]) for e in self._rows
                 if not e["is_dir"] and e.get("size") is None and not e.get("deleted")]
        if not folders and not files:
            return
        self._sizing_total = len(folders)
        self._sizing_done = 0
        t = _SizesThread(self.source, self.lock, folders[:_MAX_ROWS], files[:_MAX_ROWS], self)
        t.folder.connect(self._folder_sized)
        t.file_size.connect(self._file_sized)
        t.finished.connect(lambda t=t: self._sizing_finished(t))
        self._sizer = t
        self.sizing.emit(0, len(folders))
        t.start()

    def _stop_sizing(self):
        t = self._sizer
        if t is not None:
            t.cancelled = True
            self._sizer = None

    def wait_sizing(self, ms=5000):
        t = self._sizer
        if t is not None:
            t.cancelled = True
            t.wait(ms)
        for t in list(self._list_threads):
            t.wait(ms)

    def _sizing_finished(self, t):
        if self._sizer is t:
            self._sizer = None
        self._refresh_shares()

    def _folder_sized(self, rel, total, files, final, unreadable=0):
        if self.sender() is not self._sizer:
            return
        self.folder_sizes[rel.lower()] = (total, files, final, unreadable)
        if final:
            self._sizing_done += 1
            self.sizing.emit(self._sizing_done, self._sizing_total)
            self.note.setText(self._note_base + ("  -  sizes: %d of %d folders added up" % (
                self._sizing_done, self._sizing_total) if self._sizing_done < self._sizing_total else ""))
        self._update_row(rel)
        self._refresh_shares()

    def _file_sized(self, rel, size):
        self.file_sizes[rel.lower()] = size
        self._update_row(rel)

    def _size_of(self, rel, e):
        """(bytes or None, text, final) for one entry."""
        if e["is_dir"]:
            fs = self.folder_sizes.get(rel.lower())
            if fs is None:
                return None, "adding up...", False
            total, files, final = fs[:3]
            unreadable = fs[3] if len(fs) > 3 else 0
            if total is None:
                return None, "-", True
            text = "%s%s  (%s file%s%s)" % ("\u2265 " if (not final or unreadable) else "", _human(total),
                                           "{:,}".format(files), "" if files == 1 else "s",
                                           "; %d unreadable" % unreadable if unreadable else "")
            return total, text, final
        size = e.get("size")
        if size is None:
            size = self.file_sizes.get(rel.lower())
        if size is None:
            return None, "-", True
        return size, _human(size), True

    def _update_row(self, rel):
        r = self._row_of.get(rel.lower())
        if r is None:
            return
        e = self._shown[r]
        _b, text, final = self._size_of(rel, e)
        item = self.table.item(r, SIZE_COL)
        fs = self.folder_sizes.get(rel.lower()) or ()
        if item is not None and len(fs) > 3 and fs[3]:
            item.setToolTip("%d folder(s) or file(s) below it could not be read (run Crow-Eye as "
                            "administrator to read them): the size is at least this much" % fs[3])
        if item is not None:
            self.table.blockSignals(True)
            item.setText(text)
            item.setForeground(QtGui.QColor("#E2E8F0" if final else "#94A3B8"))
            self.table.blockSignals(False)

    def _refresh_shares(self):
        """Each entry's share of everything the folder holds (its files and every folder below)."""
        if not getattr(self, "_shown", None):
            return
        base = self.current
        sizes, pending = [], 0
        for e in self._rows:
            rel = (base + "\\" + e["name"]) if base else e["name"]
            b, _t, final = self._size_of(rel, e)
            if e["is_dir"] and not final:
                pending += 1
            sizes.append(b or 0)
        total = float(sum(sizes)) or 0.0
        self.table.blockSignals(True)
        for r, e in enumerate(self._shown):
            rel = (base + "\\" + e["name"]) if base else e["name"]
            b, _t, final = self._size_of(rel, e)
            item = self.table.item(r, SHARE_COL)
            if item is None:
                continue
            frac = (b / total) if (total and b is not None) else (0.0 if total else None)
            item.setData(_SHARE, (frac, bool(pending)))
            item.setToolTip("%s of %s in this folder%s" % (_human(b or 0), _human(total),
                                                           "; %d folder(s) still being added up" % pending
                                                           if pending else ""))
        self.table.blockSignals(False)
        self.table.viewport().update()

    def _fill(self):
        text = self.filter_edit.text().strip().lower()
        rows = [e for e in self._rows if not text or text in e["name"].lower()]
        shown = rows[:_MAX_ROWS]
        self._shown = shown
        self._row_of = {}
        self.table.blockSignals(True)
        self.table.setRowCount(len(shown))
        folder_icon = self.style().standardIcon(QtWidgets.QStyle.SP_DirIcon)
        file_icon = self.style().standardIcon(QtWidgets.QStyle.SP_FileIcon)
        can_tick = bool(self.source and self.source.can_copy)
        for r, e in enumerate(shown):
            rel = (self.current + "\\" + e["name"]) if self.current else e["name"]
            self._row_of[rel.lower()] = r
            name = QtWidgets.QTableWidgetItem(folder_icon if e["is_dir"] else file_icon, e["name"])
            name.setData(_REL, (rel, e["is_dir"]))
            name.setToolTip(self.full_path(rel))
            if can_tick:
                name.setFlags(name.flags() | QtCore.Qt.ItemIsUserCheckable)
                name.setCheckState(QtCore.Qt.Checked if rel in self._checked else QtCore.Qt.Unchecked)
            _b, size_text, final = self._size_of(rel, e)
            size_item = QtWidgets.QTableWidgetItem(size_text)
            if not final:
                size_item.setForeground(QtGui.QColor("#94A3B8"))
            cells = [name, size_item, QtWidgets.QTableWidgetItem(""),
                     QtWidgets.QTableWidgetItem(_when(e.get("modified"))),
                     QtWidgets.QTableWidgetItem(_when(e.get("created"))),
                     QtWidgets.QTableWidgetItem("deleted (in the MFT only)" if e.get("deleted") else "")]
            for c, cell in enumerate(cells):
                if e.get("deleted"):
                    cell.setForeground(QtGui.QColor("#64748B"))
                    font = cell.font()
                    font.setItalic(True)
                    cell.setFont(font)
                self.table.setItem(r, c, cell)
        self.table.blockSignals(False)
        self._refresh_shares()
        folders = sum(1 for e in rows if e["is_dir"])
        msg = "%s  -  %d folder(s), %d file(s)" % (self.full_path(self.current), folders, len(rows) - folders)
        if len(rows) > len(shown):
            msg += " - showing the first %d; filter to narrow it" % len(shown)
        deleted = sum(1 for e in rows if e.get("deleted"))
        if deleted:
            msg += " - %d deleted entr%s the MFT still holds" % (deleted, "y" if deleted == 1 else "ies")
        self._note_base = msg
        self.note.setText(msg)

    def set_folder_sizes(self, sizes):
        """{rel: (bytes, files)} for folders below the current one; shown in the Size column."""
        self.folder_sizes.update({k.lower(): (v[0], v[1], True, 0) for k, v in sizes.items()})
        self._fill()

    def _current_changed(self, row, _col, _prow, _pcol):
        item = self.table.item(row, 0) if row >= 0 else None
        if item is not None and item.data(_REL):
            rel, is_dir = item.data(_REL)
            self.selected.emit(rel, bool(is_dir))

    def _double_clicked(self, row, _col):
        item = self.table.item(row, 0)
        rel, is_dir = item.data(_REL)
        if is_dir:
            self.open(rel)

    def _tick_changed(self, item):
        if item.column() != 0 or not item.data(_REL):
            return
        rel, is_dir = item.data(_REL)
        if item.checkState() == QtCore.Qt.Checked:
            self._checked[rel] = is_dir
        else:
            self._checked.pop(rel, None)
        self.checked_changed.emit(len(self._checked))

    def visible_rows(self):
        return [((self.current + "\\" + e["name"]) if self.current else e["name"], e) for e in self._rows]


class FileBrowserDialog(QtWidgets.QDialog):
    """The File Browser window."""

    LIVE, OFFLINE = "live", "offline"

    def __init__(self, case_root: Optional[str] = None, parent=None, mode: str = "live"):
        super().__init__(parent)
        self.mode = mode if mode in (self.LIVE, self.OFFLINE) else self.LIVE
        self._copies = []
        self.setWindowTitle("Live File Browser" if self.mode == self.LIVE else "Offline File Browser")
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowMinMaxButtonsHint)
        if _theme is not None:
            _theme.fit_to_screen(self, 1560, 1120)
        else:
            self.resize(1240, 780)
        self.case_root = case_root
        self._source = None
        self._worker = None
        self._busy_token = None
        self._last_folder = None
        if _theme is not None:
            _theme.begin_theme(self)
        self._build()
        if _theme is not None:
            _theme.apply_theme(self, clear_inline=False)
        try:
            from styles import CrowEyeStyles
            CrowEyeStyles.give_window_a_taskbar_button(self)
        except Exception:
            pass
        self._refresh_saved()
        QtCore.QTimer.singleShot(0, self._auto_open)

    def _card(self, caption, hint=None):
        if _theme is not None:
            return _theme.section_card(caption, hint)
        box = QtWidgets.QGroupBox(caption)
        v = QtWidgets.QVBoxLayout(box)
        head = QtWidgets.QHBoxLayout()
        if hint:
            head.addWidget(QtWidgets.QLabel(hint), 1)
        v.addLayout(head)
        return box, v, head

    def _variant(self, button, variant, tip=None):
        if _theme is not None:
            _theme.set_variant(button, variant)
        if tip:
            button.setToolTip(tip)
        return button

    def _field(self, text):
        label = QtWidgets.QLabel(text)
        if _theme is not None:
            _theme.set_role(label, "label")
        return label

    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 14)
        root.setSpacing(12)
        live = self.mode == self.LIVE
        title = QtWidgets.QLabel("Live File Browser" if live else "Offline File Browser")
        sub = QtWidgets.QLabel(
            "This machine's file system as it is now, or as any of its shadow copies saw it - hidden copies too. "
            "Pick a volume, then the moment; tick files and folders to collect them into the case with their "
            "hashes and chain of custody, or to recover them." if live else
            "A forensic image's file system - any partition, as it is or as one of its own shadow copies saw it - "
            "or the listing this case saved when it parsed the MFT (names, sizes and times, deleted entries too). "
            "Tick files and folders to collect them into the case with their hashes and chain of custody.")
        sub.setWordWrap(True)
        if _theme is not None:
            _theme.set_role(title, "title")
            _theme.set_role(sub, "muted")
        head = QtWidgets.QHBoxLayout()
        head.setSpacing(12)
        titles = QtWidgets.QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(title)
        titles.addWidget(sub)
        head.addLayout(titles, 1)
        root.addLayout(head)
        if _theme is not None:
            self.help_btn, self.help_panel = _theme.how_it_works(
                '<b>Pick a volume, then a moment.</b> The Volume chips are this machine\'s mounted volumes; the Moment chips are <i>Now</i> (cyan) and each shadow copy of the chosen volume (yellow), newest first - hidden copies Windows no longer lists included, rebuilt by Crow-Eye from the volume\'s own catalog. Hover a copy for when and why it was made; the Shadow Copies window shows all of them in full.<br><br><b>Browse.</b> The folder tree and the folder\'s contents read the file system directly; deleted entries are not shown live. Folder sizes adds up every folder below this one.<br><br><b>Collect or recover.</b> Tick files and folders: <i>Collect ticked</i> copies them into the case with their SHA-256 and a chain-of-custody record; <i>Recover ticked</i> puts an earlier version back (into the case, onto this machine beside the current file - never over it - or both). <i>Recover an app</i> takes a program with its files, settings and registry.<br><br><b>What the case knows.</b> Select a file or folder: every parsed artifact of the case that names it (Prefetch, Amcache, LNK, Shellbags, SRUM, ...) is listed on the right.' if live else '<b>A forensic image.</b> Choose the image file (E01, VHD/VHDX, VMDK, raw), one of its partitions, and the view: the partition as it is, or one of its own shadow copies, read from the partition\'s VSS catalog by Crow-Eye\'s reader. Then Open.<br><br><b>The saved listing.</b> Once the case has parsed a machine\'s MFT, its whole file system - every name with its parent, size and times, deleted entries the MFT still holds included - opens here with no access to the machine. It holds names, not contents: to get a deleted file back, right-click it and choose <i>Recover deleted ... into the case</i> - its bytes are read back through its MFT record from this machine\'s volume or the image the case came from, checked first (the record still deleted, the same sequence, the same name), and each cluster checked against the volume\'s bitmap so a file whose clusters were reused since is marked <i>may be overwritten</i>.<br><br><b>Collect.</b> Tick files and folders from an image and <i>Collect ticked</i>: they are copied into the case with their SHA-256 and a chain-of-custody record.')
            head.addWidget(self.help_btn, 0, QtCore.Qt.AlignBottom)
            root.addWidget(self.help_panel)

        # ---- the source ----
        src_card, sv, self._src_head = self._card(
            "Source", "Pick a volume, then the moment to see it at: now, or one of its shadow copies. "
                      "Yellow chips are shadow copies; hover one for when and why it was made." if live else
            "An image: choose the file, a partition and the view, then Open. The saved listing opens at once.")
        g = QtWidgets.QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        self.live_radio = QtWidgets.QRadioButton("This machine")
        self.drive_combo = QtWidgets.QComboBox()
        self.drive_combo.setMinimumWidth(110)
        try:
            from Artifacts_Collectors.app_acquisition.sources import LiveSource
            self.drive_combo.addItems(LiveSource.drives())
        except Exception:
            self.drive_combo.addItem("C:")
        self.image_radio = QtWidgets.QRadioButton("Forensic image")
        self.image_path = QtWidgets.QLineEdit()
        self.image_path.setPlaceholderText("E01, VHD/VHDX, VMDK, raw ...")
        self.image_browse = self._variant(QtWidgets.QPushButton("Browse..."), "ghost")
        self.partition_combo = QtWidgets.QComboBox()
        self.partition_combo.setMinimumWidth(220)
        self.image_copy_combo = QtWidgets.QComboBox()
        self.image_copy_combo.setMinimumWidth(220)
        self.image_copy_combo.setToolTip("The partition as it is, or one of its own shadow copies")
        self.saved_radio = QtWidgets.QRadioButton("Saved listing (this case's MFT)")
        self.volume_combo = QtWidgets.QComboBox()
        self.volume_combo.setMinimumWidth(110)
        self.shadow_radio = QtWidgets.QRadioButton("Shadow copy of this machine")
        self.shadow_combo = QtWidgets.QComboBox()
        self.shadow_combo.setMinimumWidth(420)
        self.shadow_find_btn = self._variant(QtWidgets.QPushButton("Find copies"), "ghost",
                                             "List every shadow copy of this machine, hidden ones too")
        self.shadow_window_btn = self._variant(QtWidgets.QPushButton("Shadow Copies..."), "ghost",
                                               "The Shadow Copies window: where each copy sits, its trigger, "
                                               "and what changed")
        self.open_btn = self._variant(QtWidgets.QPushButton("Open"), "primary")
        self.open_btn.setMinimumWidth(130)
        self.live_radio.setChecked(True)
        g.addWidget(self.live_radio, 0, 0)
        g.addWidget(self.drive_combo, 0, 1)
        g.addWidget(self.image_radio, 1, 0)
        g.addWidget(self.image_path, 1, 1, 1, 2)
        g.addWidget(self.image_browse, 1, 3)
        pick = QtWidgets.QHBoxLayout()
        pick.setSpacing(8)
        pick.addWidget(self._field("Partition"))
        pick.addWidget(self.partition_combo, 1)
        pick.addSpacing(6)
        pick.addWidget(self._field("View"))
        pick.addWidget(self.image_copy_combo, 1)
        g.addLayout(pick, 1, 4)
        g.addWidget(self.saved_radio, 2, 0)
        g.addWidget(self.volume_combo, 2, 1)
        g.addWidget(self.shadow_radio, 3, 0)
        g.addWidget(self.shadow_combo, 3, 1, 1, 2)
        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.shadow_find_btn)
        buttons.addWidget(self.shadow_window_btn)
        buttons.addStretch(1)
        g.addLayout(buttons, 3, 3, 1, 2)
        g.addWidget(self.open_btn, 0, 5, 4, 1, QtCore.Qt.AlignVCenter)
        g.setColumnStretch(2, 1)
        g.setColumnStretch(4, 1)
        sv.addLayout(g)
        if live:
            # The form's live and shadow rows still drive the opening; the chips stand in for them.
            for w in (self.live_radio, self.drive_combo, self.shadow_radio, self.shadow_combo, self.shadow_find_btn,
                      self.image_radio, self.image_path, self.image_browse, self.partition_combo,
                      self.image_copy_combo, self.saved_radio, self.volume_combo, self.open_btn):
                w.hide()
            for i in range(pick.count()):
                if pick.itemAt(i).widget() is not None:
                    pick.itemAt(i).widget().hide()
            self._build_chips(sv)
            self._src_head.addWidget(self.shadow_window_btn)
        else:
            for w in (self.live_radio, self.drive_combo, self.shadow_radio, self.shadow_combo,
                      self.shadow_find_btn, self.shadow_window_btn):
                w.hide()
            self.image_radio.setChecked(True)
        root.addWidget(src_card)

        # ---- the file system, and what the case knows ----
        fs_card, fv, self._fs_head = self._card("Files", None)
        self.browser = FileBrowserWidget()
        if not live:
            self.browser.empty.setText(
                "Nothing open yet. Choose a forensic image above, its partition and the view - the partition as "
                "it is, or one of its own shadow copies - and press Open. Once the case has parsed an MFT, its "
                "saved listing opens here by itself.")
        fv.addWidget(self.browser, 1)
        side_card, rv, _rh = self._card("What the case knows about it")
        self.related = QtWidgets.QTextBrowser()
        self.related.setOpenExternalLinks(True)
        self.related.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.related.setHtml("<p style='color:#94a3b8'>Select a file or folder: every parsed artifact of the "
                             "case that names it is listed here, with what it shows.</p>")
        head = QtWidgets.QHBoxLayout()
        head.setSpacing(10)
        self.related_icon = QtWidgets.QLabel()
        self.related_icon.setFixedSize(28, 28)
        head.addWidget(self.related_icon, 0, QtCore.Qt.AlignTop)
        names = QtWidgets.QVBoxLayout()
        names.setSpacing(2)
        self.related_name = QtWidgets.QLabel("Nothing selected")
        self.related_name.setWordWrap(True)
        self.related_name.setProperty("keepStyle", True)
        self.related_name.setStyleSheet("color: #F8FAFC; font-size: 18px; font-weight: 700; background: transparent;")
        self.related_path = QtWidgets.QLabel("Select a file or folder in the list.")
        self.related_path.setWordWrap(True)
        self.related_path.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        if _theme is not None:
            _theme.set_role(self.related_path, "muted")
        names.addWidget(self.related_name)
        names.addWidget(self.related_path)
        head.addLayout(names, 1)
        rv.addLayout(head)
        self.related_busy = QtWidgets.QProgressBar()
        self.related_busy.setRange(0, 0)
        self.related_busy.setTextVisible(False)
        self.related_busy.setMaximumHeight(4)
        self.related_busy.hide()
        rv.addWidget(self.related_busy)
        self.related.setFrameShape(QtWidgets.QFrame.NoFrame)
        rv.addWidget(self.related, 1)
        body = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        body.setChildrenCollapsible(False)
        body.setHandleWidth(10)
        body.addWidget(fs_card)
        body.addWidget(side_card)
        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 1)
        body.setSizes([1020, 520])
        root.addWidget(body, 1)
        self._related_timer = QtCore.QTimer(self)
        self._related_timer.setSingleShot(True)
        self._related_timer.setInterval(300)
        self._related_timer.timeout.connect(self._show_related)
        self._related_pick = None
        self._related_worker = None

        # ---- status and actions ----
        self.status = QtWidgets.QLabel("Opening this machine..." if live else "Choose a forensic image, or the "
                                       "case's saved listing, and Open it.")
        if _theme is not None:
            _theme.set_role(self.status, "muted")
        self.progress = QtWidgets.QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(6)
        self.progress.hide()
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        self.count_label = QtWidgets.QLabel("")
        if _theme is not None:
            _theme.set_role(self.count_label, "caption")
        self.sizes_btn = self._variant(QtWidgets.QPushButton("Folder sizes"), "ghost",
                                       "Add up every folder below this one (size and file count)")
        self.export_btn = self._variant(QtWidgets.QPushButton("Export listing (CSV)"), "ghost",
                                        "This folder's listing as a CSV file")
        self.open_folder_btn = self._variant(QtWidgets.QPushButton("Open collected folder"), "ghost")
        self.open_folder_btn.hide()
        self.cancel_btn = self._variant(QtWidgets.QPushButton("Cancel"), "ghost")
        self.cancel_btn.hide()
        self.app_btn = self._variant(QtWidgets.QPushButton("Recover an app..."), "ghost",
                                     "An application with its files, settings and registry, from this source")
        self.recover_btn = self._variant(QtWidgets.QPushButton("Recover ticked..."), "ghost",
                                         "Into the case as evidence, back onto this machine, or both")
        self.collect_btn = self._variant(QtWidgets.QPushButton("Collect ticked into the case"), "primary")
        self.close_btn = self._variant(QtWidgets.QPushButton("Close"), "ghost")
        self.recover_btn.setEnabled(False)
        self.sizes_btn.setEnabled(False)
        self.app_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.collect_btn.setEnabled(False)
        row.addWidget(self.count_label)
        row.addStretch(1)
        for b in (self.sizes_btn, self.export_btn, self.open_folder_btn, self.cancel_btn):
            row.addWidget(b)
        row.addSpacing(16)
        for b in (self.app_btn, self.recover_btn, self.collect_btn):
            row.addWidget(b)
        row.addSpacing(16)
        row.addWidget(self.close_btn)
        root.addWidget(self.status)
        root.addWidget(self.progress)
        root.addLayout(row)

        for r in (self.live_radio, self.image_radio, self.saved_radio, self.shadow_radio):
            r.toggled.connect(self._kind_changed)
        self.shadow_find_btn.clicked.connect(lambda: self._find_copies(fresh=True))
        self.shadow_window_btn.clicked.connect(self._shadow_window)
        self.partition_combo.activated.connect(lambda *_: self._list_image_copies())
        self.browser.selected.connect(self._selected)
        self.sizes_btn.clicked.connect(self._folder_sizes)
        self.recover_btn.clicked.connect(self._recover)
        self.app_btn.clicked.connect(self._recover_app)
        self.image_browse.clicked.connect(self._browse_image)
        self.image_path.editingFinished.connect(self._list_partitions)
        self.open_btn.clicked.connect(self._open_source)
        self.browser.checked_changed.connect(self._checked_changed)
        self.browser.context_action.connect(self._context_action)
        self.export_btn.clicked.connect(self._export)
        self.collect_btn.clicked.connect(self._collect)
        self.cancel_btn.clicked.connect(self._cancel)
        self.open_folder_btn.clicked.connect(self._open_folder)
        self.close_btn.clicked.connect(self.close)
        self._kind_changed()

    def _build_chips(self, sv):
        """Two rows of chips: this machine's volumes, then the moment to see the chosen one at -
        now, or one of its shadow copies (hidden ones too, found from the volume's own catalog)."""
        def row(label_text, hint):
            box = QtWidgets.QHBoxLayout()
            box.setSpacing(10)
            label = self._field(label_text)
            label.setFixedWidth(84)
            label.setToolTip(hint)
            box.addWidget(label, 0, QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
            return box

        vrow = row("Volume", "The volumes Windows has mounted on this machine")
        self._vol_group = QtWidgets.QButtonGroup(self)
        self._vol_group.setExclusive(True)
        self._vol_chips = {}
        for letter in [self.drive_combo.itemText(i) for i in range(self.drive_combo.count())]:
            total, label, fs = volume_facts(letter)
            windows = os.path.isdir(os.path.join(letter.rstrip("\\") + "\\", "Windows", "System32"))
            detail = "  \u00b7  ".join(x for x in (_human(total) if total else "", fs, label) if x)
            chip = make_chip(letter.rstrip("\\"), detail, "part_windows" if windows else "part_data", VOLUME_C,
                             "Browse %s%s" % (letter, " (Windows)" if windows else ""))
            self._vol_group.addButton(chip)
            self._vol_chips[letter.rstrip("\\").upper()] = chip
            chip.clicked.connect(lambda _c=False, l=letter: self._pick_volume(l))
            vrow.addWidget(chip)
        vrow.addStretch(1)
        sv.addLayout(vrow)

        mrow = row("Moment", "Now, or the moment one of the volume's shadow copies was made")
        self._moment_group = QtWidgets.QButtonGroup(self)
        self._moment_group.setExclusive(True)
        self._moment_box = QtWidgets.QHBoxLayout()
        self._moment_box.setContentsMargins(0, 0, 0, 0)
        self._moment_box.setSpacing(10)
        holder = QtWidgets.QWidget()
        holder.setLayout(self._moment_box)
        holder.setProperty("keepStyle", True)
        holder.setStyleSheet("background: transparent;")
        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(holder)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setFixedHeight(76)
        scroll.setProperty("keepStyle", True)
        scroll.setStyleSheet("QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget "
                             "{ background: transparent; }")
        mrow.addWidget(scroll, 1)
        self.shadow_find_btn.setText("Find again")
        self.shadow_find_btn.show()
        mrow.addWidget(self.shadow_find_btn, 0, QtCore.Qt.AlignTop)
        sv.addLayout(mrow)
        first = self._vol_chips.get(self.drive_combo.currentText().rstrip("\\").upper())
        if first is not None:
            first.setChecked(True)
        self._fill_moment_chips()

    def _current_letter(self):
        return self.drive_combo.currentText().rstrip(":\\").upper() or "C"

    def _fill_moment_chips(self, select_id=None):
        """The chosen volume's moments: Now, then its shadow copies newest first."""
        if not hasattr(self, "_moment_box"):
            return
        while self._moment_box.count():
            item = self._moment_box.takeAt(0)
            w = item.widget()
            if w is not None:
                if isinstance(w, QtWidgets.QAbstractButton):
                    self._moment_group.removeButton(w)
                w.deleteLater()
        now = make_chip("Now", "the live volume", None, NOW_C, "The volume as it is at this moment")
        now.setChecked(select_id is None)
        now.clicked.connect(lambda: self._pick_volume(self.drive_combo.currentText()))
        self._moment_group.addButton(now)
        self._moment_box.addWidget(now)
        letter = self._current_letter()
        mine = [c for c in self._copies if (c.get("volume") or "").rstrip(":\\").upper() == letter]
        for c in sorted(mine, key=lambda c: c.get("created") or "", reverse=True):
            when = (c.get("created") or "").replace("T", " ").rstrip("Z")[5:16]
            name = ("#%s" % c["number"]) if c.get("number") else "hidden copy"
            chip = make_chip(name, "%s UTC  \u00b7  %s" % (when, _human(c.get("store_bytes"))), "shadow_copies",
                             COPY_C, "%s - %s UTC%s\n%s" % (
                                 name, (c.get("created") or "").replace("T", " ").rstrip("Z"),
                                 "" if c.get("exposed") else "\nIn the volume's catalog only: Windows exposes no "
                                                             "device for it; rebuilt from its store",
                                 c.get("trigger") or ""))
            if select_id and c.get("shadow_id") == select_id:
                chip.setChecked(True)
            chip.clicked.connect(lambda _c=False, copy=c: self._pick_copy(copy))
            self._moment_group.addButton(chip)
            self._moment_box.addWidget(chip)
        if not mine and getattr(self, "_finding", False):
            finding = QtWidgets.QWidget()
            fl = QtWidgets.QVBoxLayout(finding)
            fl.setContentsMargins(4, 6, 0, 0)
            fl.setSpacing(6)
            note = QtWidgets.QLabel("Finding this volume's shadow copies (hidden ones too)...")
            if _theme is not None:
                _theme.set_role(note, "muted")
            from ui.animated_progress_bar import AnimatedProgressBar
            bar = AnimatedProgressBar(accent="#FACC15")
            bar.setTextVisible(False)
            bar.setFixedSize(260, 5)
            bar.setRange(0, 0)
            fl.addWidget(note)
            fl.addWidget(bar)
            self._moment_box.addWidget(finding)
        elif not mine:
            why = (getattr(self, "_no_copy_reasons", None) or {}).get(letter, "")
            if getattr(self, "_finding", True) and not self._copies:
                note = QtWidgets.QLabel("No shadow copies of %s: found yet" % letter)
            else:
                # The first sentence of why there are none; the rest (storage, free space) on hover.
                note = QtWidgets.QLabel(why.split("  ")[0] if why else "%s: has no shadow copies" % letter)
                note.setWordWrap(True)
                if why:
                    note.setToolTip(why.replace("  ", "\n"))
            if _theme is not None:
                _theme.set_role(note, "muted")
            self._moment_box.addWidget(note)
        self._moment_box.addStretch(1)

    def _pick_volume(self, letter):
        i = self.drive_combo.findText(letter)
        if i >= 0:
            self.drive_combo.setCurrentIndex(i)
        chip = self._vol_chips.get(letter.rstrip(":\\").upper()) if hasattr(self, "_vol_chips") else None
        if chip is not None:
            chip.setChecked(True)
        self._fill_moment_chips()
        self.live_radio.setChecked(True)
        self._open_source()

    def _pick_copy(self, copy):
        i = next((k for k in range(self.shadow_combo.count())
                  if (self.shadow_combo.itemData(k) or {}).get("shadow_id") == copy.get("shadow_id")), -1)
        if i < 0:
            self.shadow_combo.addItem(copy.get("shadow_id") or "", copy)
            i = self.shadow_combo.count() - 1
        self.shadow_combo.setCurrentIndex(i)
        self.shadow_radio.setChecked(True)
        self._open_source()

    def _auto_open(self):
        """Open at once, so the window shows a file system rather than empty panes - this machine
        (live) or the case's saved listing (offline) - unless something else is already being opened
        (a shadow copy from the Shadow Copies window). Live, the shadow copies are listed next."""
        busy = bool(getattr(self, "_bg_workers", None))
        if self.mode == self.LIVE:
            if self._source is None and self.live_radio.isChecked() and not busy:
                self._open_source()
            if not self._copies and not busy:
                self._find_copies()
        elif self._source is None and self.saved_radio.isChecked() and self.saved_radio.isEnabled() and not busy:
            self._open_source()

    # ── case ─────────────────────────────────────────────────────────
    def set_case(self, case_root):
        self.case_root = case_root
        self._refresh_saved()

    def _artifacts_dir(self):
        return os.path.join(self.case_root, "Target_Artifacts") if self.case_root else None

    def _refresh_saved(self):
        self.volume_combo.clear()
        vols = []
        if self.case_root:
            try:
                from Artifacts_Collectors.app_acquisition.sources import SavedSource
                vols = SavedSource.volumes(self._artifacts_dir())
            except Exception:
                vols = []
        for v in vols:
            self.volume_combo.addItem("%s:" % v, v)
        self.saved_radio.setEnabled(bool(vols))
        if vols and self.mode == self.OFFLINE and self._source is None:
            self.saved_radio.setChecked(True)
        self.saved_radio.setToolTip("" if vols else "This case has no parsed MFT yet: parse the MFT and "
                                                     "the file listing is saved with the case.")

    # ── source ───────────────────────────────────────────────────────
    def _kind_changed(self, *_):
        self.drive_combo.setEnabled(self.live_radio.isChecked())
        for w in (self.image_path, self.image_browse, self.partition_combo, self.image_copy_combo):
            w.setEnabled(self.image_radio.isChecked())
        self.volume_combo.setEnabled(self.saved_radio.isChecked())
        self.shadow_combo.setEnabled(self.shadow_radio.isChecked())
        if self.shadow_radio.isChecked() and self.shadow_combo.count() == 0:
            self._find_copies()

    # -- shadow copies --------------------------------------------------
    def _bg(self, fn, done, failed=None, busy="Working..."):
        from ui.app_acquisition_dialog import _Worker
        worker = _Worker(lambda report: fn(), self)
        self._bg_workers = getattr(self, "_bg_workers", [])
        self._bg_workers.append(worker)
        self._say(busy)

        def ok(res):
            self._bg_workers.remove(worker)
            done(res)

        def bad(msg):
            self._bg_workers.remove(worker)
            (failed or (lambda m: self._say(m, error=True)))(msg)
        worker.finished_ok.connect(ok)
        worker.failed.connect(bad)
        worker.start()

    def _find_copies(self, select=None, fresh=False):
        current = self._current_letter()

        def fn():
            from Artifacts_Collectors.shadow_copies import live_copies
            # Shared with the Shadow Copies window for a minute; Find again reads again.
            copies = live_copies(max_age=0 if fresh else None)
            return copies, _no_copy_reasons(copies, current, 0 if fresh else None)

        self._finding = True
        self._fill_moment_chips()

        def done(result):
            copies, reasons = result
            self._finding = False
            self._no_copy_reasons = reasons
            self._copies = list(copies)
            self._fill_moment_chips(select.get("shadow_id") if select else None)
            self.shadow_combo.clear()
            for c in copies:
                label = "%s:  %s  %s UTC  %s  %s" % (
                    c.get("volume"), ("#%s" % c["number"]) if c.get("number") else "hidden",
                    (c.get("created") or "").replace("T", " ").rstrip("Z"), _human(c.get("store_bytes")),
                    "" if c.get("exposed") else "(catalog only)")
                self.shadow_combo.addItem(label, c)
            if select:
                for i in range(self.shadow_combo.count()):
                    if self.shadow_combo.itemData(i).get("shadow_id") == select.get("shadow_id"):
                        self.shadow_combo.setCurrentIndex(i)
            self._say("%d shadow cop%s on this machine." % (len(copies), "y" if len(copies) == 1 else "ies")
                      if copies else (reasons.get(current) or
                                      "This machine has no shadow copies (or this window is not elevated)."))
            if select:
                self._open_source()
        self._bg(fn, done, busy="Finding this machine's shadow copies...")

    def _shadow_window(self):
        from ui.shadow_copies_dialog import ShadowCopiesDialog
        dlg = ShadowCopiesDialog(self.case_root, self, open_in_browser=self.open_shadow_copy)
        dlg.show()

    def open_shadow_copy(self, copy):
        """Browse one shadow copy (from the Shadow Copies window)."""
        self.shadow_radio.setChecked(True)
        self._find_copies(select=copy)

    def _list_image_copies(self):
        path = self.image_path.text().strip()
        part = self.partition_combo.currentData()
        self.image_copy_combo.clear()
        self.image_copy_combo.addItem("The partition", None)
        if not path or part is None:
            return

        def fn():
            from Artifacts_Collectors.shadow_copies import image_copies
            return image_copies(path, int(part))

        def done(copies):
            for c in copies:
                self.image_copy_combo.addItem("Shadow copy %d - %s UTC" % (
                    c["index"] + 1, (c.get("created") or "").replace("T", " ").rstrip("Z")), c["index"])
            self._say("The partition holds %d shadow cop%s." % (len(copies), "y" if len(copies) == 1 else "ies"))
        self._bg(fn, done, failed=lambda m: self._say("No shadow copies read from the image: " + m),
                 busy="Reading the partition's shadow copy catalog...")

    def _browse_image(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Forensic image", "", "Forensic images (*.e01 *.E01 *.ex01 *.vhd *.vhdx *.vmdk *.raw "
                                        "*.dd *.img *.001 *.iso);;All files (*)")
        if path:
            self.image_path.setText(path)
            self._list_partitions()

    def _list_partitions(self):
        path = self.image_path.text().strip()
        self.partition_combo.clear()
        if not path or not os.path.isfile(path):
            return
        try:
            from Artifacts_Collectors.app_acquisition.sources import ImageSource
            for number, label in ImageSource.partitions(path):
                self.partition_combo.addItem(label, number)
        except Exception as exc:
            self._say("The image's partitions could not be read: %s" % exc, error=True)

    def _open_source(self):
        from Artifacts_Collectors.app_acquisition.sources import (ImageSource, ImageShadowSource, LiveSource,
                                                                  SavedSource, ShadowSource)
        if self.live_radio.isChecked():
            make = lambda: LiveSource(self.drive_combo.currentText())
        elif self.shadow_radio.isChecked():
            copy = self.shadow_combo.currentData()
            if not copy:
                self._say("Find the copies first, then pick one.", error=True)
                return
            make = lambda: ShadowSource(copy)
        elif self.image_radio.isChecked():
            path = self.image_path.text().strip()
            if not os.path.isfile(path) or self.partition_combo.currentData() is None:
                self._say("Choose a forensic image and a partition first.", error=True)
                return
            part, idx = int(self.partition_combo.currentData()), self.image_copy_combo.currentData()
            make = (lambda: ImageSource(path, part)) if idx is None else (lambda: ImageShadowSource(path, part, idx))
        else:
            make = lambda: SavedSource(self._artifacts_dir(), self.volume_combo.currentData())
        self.open_btn.setEnabled(False)
        title, subtitle = self._opening_text()
        self.browser.show_loading(title, subtitle, [title])

        def failed(m):
            self.open_btn.setEnabled(True)
            self.browser.hide_loading(failed=m)
            self._say(m, error=True)
        self._bg(make, self._source_opened, failed=failed,
                 busy="Opening the source (a hidden or image shadow copy is rebuilt from its store)...")

    def _opening_text(self):
        """What the loading page says while a source opens."""
        if self.live_radio.isChecked():
            return "Opening %s" % self.drive_combo.currentText(), "This machine's volume, read live."
        if self.shadow_radio.isChecked():
            c = self.shadow_combo.currentData() or {}
            name = ("shadow copy #%s" % c["number"]) if c.get("number") else "a hidden shadow copy"
            how = ("Windows exposes it as a device: its file system opens directly." if c.get("exposed") else
                   "Windows no longer lists it: Crow-Eye finds its store in the volume's VSS catalog, rebuilds "
                   "the copy block by block with its own reader and opens the NTFS inside it.")
            return "Opening %s of %s: (%s UTC)" % (name, (c.get("volume") or "C"),
                                                   (c.get("created") or "").replace("T", " ").rstrip("Z")), how
        if self.image_radio.isChecked():
            return ("Opening the image's partition" if self.image_copy_combo.currentData() is None else
                    "Opening one of the partition's shadow copies"), os.path.basename(self.image_path.text())
        return "Opening the case's saved listing", "The MFT the case parsed: every name, size and time."

    def _source_opened(self, source):
        self.open_btn.setEnabled(True)
        self.browser.loading.finish()
        old = self._source
        if old is not None:
            old.close()
        self._source = source
        live_like = getattr(source, "kind", "") in ("shadow", "hidden_shadow", "image_shadow", "live", "image")
        self.sizes_btn.setEnabled(getattr(source, "kind", "") != "saved")
        self.app_btn.setEnabled(live_like and bool(self.case_root))
        self.browser.set_source(source)
        self.export_btn.setEnabled(True)
        self._sync_chips(source)
        # What was opened for reading, and when: a live volume, a shadow copy
        # or an image is evidence being read, even before anything is copied.
        try:
            from utils import custody
            custody.ledger(self.case_root, "evidence source opened",
                           tool="File Browser", kind=getattr(source, "kind", ""),
                           source=source.describe())
        except Exception:
            pass
        self._say("Browsing %s." % source.describe() + (
            "" if source.can_copy else " A saved listing holds names, sizes and times, not contents: open "
                                       "the machine or its image to collect files."))

    def _sync_chips(self, source):
        if self.mode != self.LIVE or not hasattr(self, "_moment_group"):
            return
        copy = getattr(source, "copy", None)
        letter = ((copy or {}).get("volume") or self._current_letter()).rstrip(":\\").upper()
        chip = self._vol_chips.get(letter)
        if chip is not None:
            chip.setChecked(True)
        if copy:
            if (self.drive_combo.currentText().rstrip(":\\").upper() != letter):
                i = self.drive_combo.findText(letter + ":")
                if i >= 0:
                    self.drive_combo.setCurrentIndex(i)
            self._fill_moment_chips(copy.get("shadow_id"))

    def _checked_changed(self, n):
        self.count_label.setText("%d ticked" % n if n else "")
        self.recover_btn.setEnabled(bool(n) and self._worker is None and bool(self._source and self._source.can_copy))
        self.collect_btn.setEnabled(bool(n) and self._worker is None and bool(self.case_root)
                                    and bool(self._source and self._source.can_copy))

    # ── export ───────────────────────────────────────────────────────
    def _export(self):
        if self._source is None:
            return
        default = os.path.join(self.case_root or os.path.expanduser("~"),
                               "file_listing_%s.csv" % (self.browser.current.replace("\\", "_") or "root"))
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export listing", default, "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["path", "type", "size", "modified_utc", "created_utc", "deleted", "source"])
            for rel, e in self.browser.visible_rows():
                w.writerow([rel, "folder" if e["is_dir"] else "file", e.get("size") or "",
                            e.get("modified") or "", e.get("created") or "", "yes" if e.get("deleted") else "",
                            self._source.describe()])
        try:
            from utils import custody
            custody.record_export(path, "file listing (%s)" % self._source.describe(), case_dir=self.case_root)
        except Exception:
            pass
        self._say("Listing written: %s" % path, ok=True)

    # ── collect ──────────────────────────────────────────────────────
    def _collect(self):
        from Artifacts_Collectors.app_acquisition.catalog import AppEntry
        from Artifacts_Collectors.app_acquisition.footprint import Footprint, FootprintItem, _user_of
        from ui.app_acquisition_dialog import _Worker
        picks = self.browser.checked()
        if not picks or self._source is None or not self.case_root:
            return
        fp = Footprint(AppEntry(name="Files from %s" % (self._source.tag or "source"), sources=["File Browser"]))
        for rel, is_dir in picks:
            fp.add(FootprintItem("folder" if is_dir else "file", rel, "chosen in the File Browser", _user_of(rel)))
        source, case_root = self._source, self.case_root
        worker = None

        locked = LockedSource(source, self.browser.lock)

        def work(report):
            from Artifacts_Collectors.app_acquisition.collector import acquire
            return acquire(fp, locked, case_root, progress=report,
                           is_cancelled=lambda: bool(worker is not None and worker.cancelled),
                           record_kind="file collection")
        worker = _Worker(work, self)
        self._worker = worker
        self.collect_btn.setEnabled(False)
        self.cancel_btn.show()
        self.progress.show()
        self.progress.setRange(0, 0)
        try:
            from ui import busy_guard
            self._busy_token = busy_guard.begin("File Browser is copying files", alive=worker.isRunning)
        except Exception:
            self._busy_token = None

        def progress(msg, done, total):
            self.status.setText(msg)
            if total:
                self.progress.setRange(0, total)
                self.progress.setValue(done)

        def finish():
            self._worker = None
            if self._busy_token is not None:
                try:
                    from ui import busy_guard
                    busy_guard.end(self._busy_token)
                except Exception:
                    pass
                self._busy_token = None
            self.progress.hide()
            self.cancel_btn.hide()
            self._checked_changed(len(self.browser.checked()))

        def done(result):
            finish()
            self._last_folder = result.folder
            self.open_folder_btn.show()
            msg = "%s: %d file(s), %s" % ({"completed": "Collected", "partial": "Collected with problems",
                                            "cancelled": "Stopped", "failed": "Nothing was collected"}[result.status],
                                           result.files, _human(result.bytes))
            if result.failed:
                msg += "; %d could not be read" % result.failed
            if result.databases:
                msg += "; %d database(s) ready in Database Search" % len(result.databases)
            self._say(msg, error=result.status == "failed", ok=result.status == "completed")

        def failed(message):
            finish()
            self._say(message, error=True)
        worker.progress.connect(progress)
        worker.finished_ok.connect(done)
        worker.failed.connect(failed)
        worker.start()

    # -- what the case knows ---------------------------------------------
    def _volume_letter(self):
        src = self._source
        if src is None:
            return "C"
        copy = getattr(src, "copy", None)
        if copy and copy.get("volume"):
            return copy["volume"]
        vol = getattr(src, "volume", "") or ""
        return vol[0] if len(vol) >= 2 and vol[1] == ":" else "C"

    def _selected(self, rel, is_dir):
        """Say at once what was picked and that it is being looked up; the lookup follows."""
        self._related_pick = (rel, is_dir)
        full = self.browser.full_path(rel)
        self.related_name.setText(full.rstrip("\\").rsplit("\\", 1)[-1] or full)
        self.related_path.setText(full)
        try:
            from ui.artifact_icons import artifact_icon
            icon = artifact_icon("folder" if is_dir else "parse_offline", "#A5B4FC")
            self.related_icon.setPixmap(icon.pixmap(28, 28) if icon is not None else QtGui.QPixmap())
        except Exception:
            pass
        if self.case_root:
            self.related_busy.show()
            self.related.setHtml("<p style='color:#94a3b8'>Looking through the case's parsed artifacts for this "
                                 "%s...</p>" % ("folder" if is_dir else "file"))
        self._related_timer.start()

    def _show_related(self):
        if not self._related_pick:
            return
        rel, is_dir = self._related_pick
        if not self.case_root:
            self.related_busy.hide()
            self.related.setHtml("<p style='color:#94a3b8'>Open a case to see what its parsed artifacts "
                                 "record about this path.</p>")
            return
        arts = self._artifacts_dir()
        letter = self._volume_letter()

        def fn():
            from Artifacts_Collectors.related_artifacts import related
            return related(arts, rel, letter, is_dir)

        def done(res):
            if self._related_pick == (rel, is_dir):
                from Artifacts_Collectors.related_artifacts import html
                self.related_busy.hide()
                self.related.setHtml(html(res))

        def failed(m):
            if self._related_pick == (rel, is_dir):
                self.related_busy.hide()
                self.related.setPlainText(m)
        self._bg(fn, done, failed=failed, busy=self.status.text())

    # -- folder sizes -----------------------------------------------------
    def _folder_sizes(self):
        src, here = self._source, self.browser.current
        folders = [rel for rel, e in self.browser.visible_rows() if e["is_dir"]]
        if src is None or not folders:
            return
        self.sizes_btn.setEnabled(False)

        def fn():
            out = {}
            for rel in folders:
                total = files = 0
                for _p, size in src.walk_files(rel):
                    total += size or 0
                    files += 1
                out[rel] = (total, files)
            return out

        def done(sizes):
            self.sizes_btn.setEnabled(True)
            self.browser.set_folder_sizes(sizes)
            self._say("Sizes of %d folder(s) in %s: %s in all." % (
                len(sizes), here or "the root", _human(sum(v[0] for v in sizes.values()))), ok=True)
        self._bg(fn, done, failed=lambda m: (self.sizes_btn.setEnabled(True), self._say(m, error=True)),
                 busy="Adding up %d folder(s)... (large folders take a while)" % len(folders))

    # -- recovery ---------------------------------------------------------
    def _recover(self):
        picks = self.browser.checked()
        src = self._source
        if not picks or src is None:
            return
        from_this_machine = getattr(src, "kind", "") in ("shadow", "hidden_shadow")
        dlg = RecoverDialog(src, len(picks), from_this_machine, bool(self.case_root), self)
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return
        to_case, to_machine, mode, folder = dlg.choice()
        if to_case:
            self._collect()
        if to_machine:
            self._restore(picks, mode, folder)

    def _restore(self, picks, mode, folder):
        from ui.app_acquisition_dialog import _Worker
        src, case_root = self._source, self.case_root
        worker = None

        locked = LockedSource(src, self.browser.lock)

        def work(report):
            from Artifacts_Collectors.app_acquisition.restore import restore
            return restore(locked, picks, case_root, mode=mode, folder=folder, progress=report,
                           is_cancelled=lambda: bool(worker is not None and worker.cancelled))
        worker = _Worker(work, self)
        self._restore_worker = worker
        self.progress.show()
        self.progress.setRange(0, 0)
        self.cancel_btn.show()
        try:
            from ui import busy_guard
            restore_token = busy_guard.begin("File Browser is restoring files", alive=worker.isRunning)
        except Exception:
            restore_token = None

        def finish_restore():
            self._restore_worker = None
            self.cancel_btn.setVisible(self._worker is not None)
            if restore_token is not None:
                try:
                    from ui import busy_guard
                    busy_guard.end(restore_token)
                except Exception:
                    pass

        def progress(msg, done, total):
            self.status.setText(msg)
            if total:
                self.progress.setRange(0, total)
                self.progress.setValue(done)

        def done(res):
            finish_restore()
            self.progress.hide()
            beside = sum(1 for r in res["restored"] if r["how"] == "beside")
            msg = "Restored %d file(s), %s" % (len(res["restored"]), _human(res["bytes"]))
            if beside:
                msg += "; %d beside a file already there, never over it" % beside
            if res["failed"]:
                msg += "; %d could not be restored" % len(res["failed"])
            if res.get("manifest"):
                msg += ". Recorded in %s" % res["manifest"]
            self._say(msg, ok=not res["failed"], error=res["status"] == "failed")
        worker.progress.connect(progress)
        worker.finished_ok.connect(done)
        worker.failed.connect(lambda m: (finish_restore(), self.progress.hide(), self._say(m, error=True)))
        worker.start()

    def _carve(self, picks):
        """Deleted files of the saved listing, recovered into the case from
        their MFT records (app_acquisition/deleted_recovery). The listing holds
        names, not contents, so the bytes are read from the volume it came
        from: this machine's volume, or a partition of a forensic image."""
        from ui.app_acquisition_dialog import _Worker
        src = self._source
        if src is None or getattr(src, "kind", "") != "saved":
            return
        if not self.case_root:
            self._say("Open a case first: recovered files are saved into the case.", error=True)
            return
        items = []
        for rel, is_dir in picks:
            e = src._entry(rel) or {}
            if is_dir or not e.get("deleted") or e.get("record") is None:
                continue
            items.append({"record": e["record"], "sequence": e.get("sequence"),
                          "path": rel, "check_name": True})
        if not items:
            self._say("Only deleted files can be recovered from the listing.", error=True)
            return
        dlg = CarveFromDialog(src.volume, len(items), self)
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return
        where = dlg.choice()
        case_root = self.case_root
        worker = None

        def work(report):
            from Artifacts_Collectors.app_acquisition import deleted_recovery as dr
            report("Opening %s" % where["label"], 0, 0)
            stream = dr.open_volume(where["kind"], **where["args"])
            try:
                return dr.recover_deleted(case_root, stream, where["label"], where["tag"], items,
                                          progress=report,
                                          is_cancelled=lambda: bool(worker is not None and worker.cancelled))
            finally:
                try:
                    stream.close()
                except Exception:
                    pass
        worker = _Worker(work, self)
        self._carve_worker = worker
        self.progress.show()
        self.progress.setRange(0, 0)
        self.cancel_btn.show()
        try:
            from ui import busy_guard
            token = busy_guard.begin("File Browser is recovering deleted files", alive=worker.isRunning)
        except Exception:
            token = None

        def finish():
            self._carve_worker = None
            self.progress.hide()
            self.cancel_btn.setVisible(self._worker is not None)
            if token is not None:
                try:
                    from ui import busy_guard
                    busy_guard.end(token)
                except Exception:
                    pass

        def progress(msg, done, total):
            self.status.setText(msg)
            if total:
                self.progress.setRange(0, total)
                self.progress.setValue(done)

        def done(res):
            finish()
            self._last_folder = res["folder"]
            self.open_folder_btn.show()
            risky = sum(1 for e in res["entries"] if e["risk"].startswith("may be overwritten"))
            msg = "Recovered %d deleted file(s) into the case" % res["files"]
            if risky:
                msg += "; %d may be partly overwritten (their clusters are in use again)" % risky
            if res["failed"]:
                msg += "; %d could not be recovered: %s" % (res["failed"], res["errors"][0])
            self._say(msg, error=res["status"] == "failed", ok=res["status"] == "completed" and not risky)

        def failed(message):
            finish()
            self._say("Not recovered: %s" % message, error=True)
        worker.progress.connect(progress)
        worker.finished_ok.connect(done)
        worker.failed.connect(failed)
        worker.start()

    def _context_action(self, action, picks):
        if self._source is None or not picks:
            return
        if action == "acquire":
            self._acquire(files=picks)
        elif action == "find_app":
            self._acquire(search=picks[0][0].rsplit("\\", 1)[-1])
        elif action in ("collect", "recover"):
            self.browser._tick(picks, True)
            (self._collect if action == "collect" else self._recover)()
        elif action == "carve":
            self._carve(picks)

    def _acquire(self, files=None, search=None):
        """App Acquisition on this window's own source: the chosen files and folders in its Files
        and folders tab, or its program list searched for a folder's name."""
        from ui.app_acquisition_dialog import AppAcquisitionDialog
        dlg = AppAcquisitionDialog(self.case_root, self, source=self._source)
        dlg.show()
        try:
            if files:
                dlg.mode_tabs.setCurrentIndex(1)
                for rel, is_dir in files:
                    dlg._add_rel(rel, is_dir)
            else:
                if search:
                    dlg.search.setText(search)
                dlg._load()
        except Exception as exc:
            self._say("App Acquisition could not take them: %s" % exc, error=True)

    def _recover_app(self):
        if self._source is None:
            return
        from ui.app_acquisition_dialog import AppAcquisitionDialog
        dlg = AppAcquisitionDialog(self.case_root, self, source=self._source)
        dlg.show()
        try:
            dlg._load()
        except Exception:
            pass

    def _cancel(self):
        for w in (self._worker, getattr(self, "_restore_worker", None),
                  getattr(self, "_carve_worker", None)):
            if w is not None:
                w.cancelled = True
                self._say("Stopping after the current file...")

    def _open_folder(self):
        if self._last_folder and os.path.isdir(self._last_folder) and os.name == "nt":
            os.startfile(self._last_folder)

    def _say(self, text, error=False, ok=False):
        self.status.setText(text)
        if _theme is not None:
            _theme.set_status(self.status, "bad" if error else ("ok" if ok else "neutral"))

    def closeEvent(self, event):
        self.browser.wait_sizing()
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancelled = True
            self._worker.wait(15000)
        # Background lookups (copies, sizes, related artifacts, opening a source) finish before the
        # window goes: a QThread destroyed while running takes the whole process down.
        for w in list(getattr(self, "_bg_workers", [])) + [getattr(self, "_restore_worker", None),
                                                           getattr(self, "_carve_worker", None)]:
            if w is not None and w.isRunning():
                w.cancelled = True
                w.wait(60000)
        if self._source is not None:
            self._source.close()
            self._source = None
        super().closeEvent(event)


class RecoverDialog(QtWidgets.QDialog):
    """Where the recovered files go: into the case, back onto this machine, or both."""

    def __init__(self, source, count, from_this_machine, has_case, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recover %d item(s)" % count)
        v = QtWidgets.QVBoxLayout(self)
        v.addWidget(QtWidgets.QLabel("From %s" % source.describe()))
        self.to_case = QtWidgets.QCheckBox("Save into the case as evidence (SHA-256, chain of custody, manifest)")
        self.to_case.setChecked(has_case)
        self.to_case.setEnabled(has_case)
        self.to_machine = QtWidgets.QCheckBox("Restore onto this machine")
        self.original = QtWidgets.QRadioButton("to its original place - beside the current file if one is there, "
                                               "never over it")
        self.folder = QtWidgets.QRadioButton("into a folder I choose (paths below the volume kept)")
        self.folder_edit = QtWidgets.QLineEdit()
        browse = QtWidgets.QPushButton("Browse...")
        self.original.setChecked(from_this_machine)
        self.folder.setChecked(not from_this_machine)
        self.original.setEnabled(from_this_machine)
        v.addWidget(self.to_case)
        v.addWidget(self.to_machine)
        box = QtWidgets.QVBoxLayout()
        box.setContentsMargins(24, 0, 0, 0)
        box.addWidget(self.original)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.folder)
        row.addWidget(self.folder_edit, 1)
        row.addWidget(browse)
        box.addLayout(row)
        v.addLayout(box)
        note = QtWidgets.QLabel("Restoring changes the examined machine: every restored file is hashed and the "
                                "run is recorded in the case's Restores folder and custody ledger.")
        note.setWordWrap(True)
        if _theme is not None:
            _theme.set_role(note, "muted")
        v.addWidget(note)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        v.addWidget(buttons)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        browse.clicked.connect(self._browse)
        if not has_case:
            self.to_machine.setChecked(True)

    def _browse(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Restore into")
        if path:
            self.folder_edit.setText(path)
            self.folder.setChecked(True)

    def _accept(self):
        if not self.to_case.isChecked() and not self.to_machine.isChecked():
            return
        if self.to_machine.isChecked() and self.folder.isChecked() and not self.folder_edit.text().strip():
            self._browse()
            if not self.folder_edit.text().strip():
                return
        self.accept()

    def choice(self):
        from Artifacts_Collectors.app_acquisition.restore import FOLDER, ORIGINAL
        return (self.to_case.isChecked(), self.to_machine.isChecked(),
                FOLDER if self.folder.isChecked() else ORIGINAL, self.folder_edit.text().strip() or None)


class LockedSource:
    """A source whose readers take the browser's lock: an image partition and a
    rebuilt shadow copy share one file handle, which the sizing and listing
    threads also read through. Collect and restore used to read it unguarded,
    and "Recover -> both" ran the two at once."""

    _GUARDED = ("copy_file", "walk_files", "isdir", "isfile", "size", "listdir", "entries",
                "hive_file", "user_profiles")

    def __init__(self, source, lock):
        self._source = source
        self._lock = lock

    def __getattr__(self, name):
        attr = getattr(self._source, name)
        if name not in self._GUARDED or not callable(attr):
            return attr

        def guarded(*args, **kwargs):
            with self._lock:
                out = attr(*args, **kwargs)
                return list(out) if name == "walk_files" else out
        return guarded


class CarveFromDialog(QtWidgets.QDialog):
    """Where a deleted file's bytes are read from: this machine's volume, or a
    partition of a forensic image (the listing holds names, not contents)."""

    def __init__(self, volume, count, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recover deleted files")
        self.setMinimumWidth(560)
        lay = QtWidgets.QVBoxLayout(self)
        letter = str(volume or "").rstrip(":\\").upper()
        self._letter = letter if len(letter) == 1 and os.path.exists(letter + ":\\") else None
        intro = QtWidgets.QLabel(
            "%d deleted file(s) of the saved listing of %s. Their bytes are read back through each "
            "file's MFT record, from the volume the listing came from. Each record is checked first "
            "(still deleted, the same sequence, the same name), and each cluster against the volume's "
            "bitmap: a file whose clusters are in use again is saved and marked <i>may be "
            "overwritten</i>. Every file goes into the case with its SHA-256 and a chain-of-custody "
            "record." % (count, volume))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.live = QtWidgets.QRadioButton(
            "This computer's volume %s: (read raw, as administrator)" % self._letter if self._letter
            else "This computer's volume (the listing's volume is not on this computer)")
        self.live.setEnabled(bool(self._letter))
        self.image = QtWidgets.QRadioButton("A partition of a forensic image (E01, VHD/VHDX, VMDK, raw)")
        lay.addWidget(self.live)
        lay.addWidget(self.image)
        row = QtWidgets.QHBoxLayout()
        self.path = QtWidgets.QLineEdit()
        self.path.setPlaceholderText("image file")
        browse = QtWidgets.QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        self.partition = QtWidgets.QComboBox()
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        row.addWidget(self.partition)
        lay.addLayout(row)
        (self.live if self._letter else self.image).setChecked(True)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Recover into the case")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        try:
            from ui.app_theme import apply_theme, set_variant
            apply_theme(self)
            set_variant(buttons.button(QtWidgets.QDialogButtonBox.Ok), "primary")
            for btn in (buttons.button(QtWidgets.QDialogButtonBox.Cancel), browse):
                set_variant(btn, "ghost")
        except Exception:
            pass

    def _browse(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Forensic image", "",
                                                        "Images (*.E01 *.e01 *.vhd *.vhdx *.vmdk *.raw *.dd *.img);;All files (*)")
        if not path:
            return
        self.path.setText(path)
        self.image.setChecked(True)
        self.partition.clear()
        try:
            from Artifacts_Collectors.app_acquisition.sources import ImageSource
            for number, label in ImageSource.partitions(path):
                self.partition.addItem(label, number)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Forensic image", "Its partitions could not be read: %s" % exc)

    def _accept(self):
        if self.image.isChecked() and (not self.path.text() or self.partition.currentData() is None):
            QtWidgets.QMessageBox.information(self, "Recover deleted files",
                                              "Choose the image and the partition the listing came from.")
            return
        self.accept()

    def choice(self):
        if self.live.isChecked() and self._letter:
            return {"kind": "live", "args": {"volume": self._letter},
                    "label": "this computer's volume %s: (raw)" % self._letter, "tag": self._letter}
        path, part = self.path.text(), self.partition.currentData()
        stem = os.path.splitext(os.path.basename(path))[0] or "image"
        return {"kind": "image", "args": {"image_path": path, "partition": part},
                "label": "%s, partition %s" % (os.path.basename(path), part),
                "tag": "%s_p%s" % (stem, part)}

