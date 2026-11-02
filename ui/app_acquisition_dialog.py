"""App Acquisition: collect an application, or files and folders, into the case.

Source (this machine or a forensic image) -> pick a program from the list, or
add files / folders -> review what belongs to it, each item with the reason it
was included -> Collect. The engine is Artifacts_Collectors/app_acquisition;
this window only drives it, off the GUI thread.
"""
from __future__ import annotations

import os
import subprocess
from typing import Callable, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

try:
    from ui import app_theme as _theme
except Exception:   # pragma: no cover
    _theme = None

_KIND_ROLE = QtCore.Qt.UserRole + 1


def _human(n: Optional[int]) -> str:
    if n is None:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return ""


class _Worker(QtCore.QThread):
    """Run fn(report) off the GUI thread; report(message, done, total)."""
    progress = QtCore.pyqtSignal(str, int, int)
    finished_ok = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, fn: Callable, parent=None):
        super().__init__(parent)
        self._fn = fn
        self.cancelled = False

    def run(self):
        try:
            self.finished_ok.emit(self._fn(lambda m, d=0, t=0: self.progress.emit(str(m), int(d), int(t))))
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.failed.emit("%s: %s" % (type(exc).__name__, exc))


class AppAcquisitionDialog(QtWidgets.QDialog):
    """The App Acquisition window."""

    LIVE, OFFLINE = "live", "offline"

    def __init__(self, case_root: Optional[str] = None, parent=None, open_database_search=None, source=None,
                 mode: str = "live"):
        super().__init__(parent)
        # Live: this machine's programs. Offline: a forensic image's. A source handed over by another
        # window decides for itself.
        self.mode = mode if mode in (self.LIVE, self.OFFLINE) else self.LIVE
        self.setWindowTitle("App Acquisition" if source is not None else
                            "Live App Acquisition" if self.mode == self.LIVE else "Offline App Acquisition")
        # A source handed over by another window (the File Browser's shadow copy): used as it is
        # and left open when this window is done with it, because its owner still browses it.
        self._preset_source = source
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowMinMaxButtonsHint)
        self.resize(1180, 760)
        self.case_root = case_root
        self._open_database_search = open_database_search
        self._source = None
        self._view = None
        self._apps = []
        self._footprint = None
        self._worker = None
        self._busy_token = None
        self._last_folder = None
        if _theme is not None:
            _theme.begin_theme(self)
        self._build()
        if _theme is not None:
            _theme.apply_theme(self, clear_inline=False)
        QtCore.QTimer.singleShot(0, self._auto_load)
        try:
            from styles import CrowEyeStyles
            CrowEyeStyles.give_window_a_taskbar_button(self)
        except Exception:
            pass

    # ── layout ───────────────────────────────────────────────────────
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

    def _role(self, widget, role):
        if _theme is not None:
            _theme.set_role(widget, role)
        return widget

    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 14)
        root.setSpacing(12)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(12)
        titles = QtWidgets.QVBoxLayout()
        titles.setSpacing(4)
        live = self.mode == self.LIVE
        title = self._role(QtWidgets.QLabel(self.windowTitle()), "title")
        subtitle = self._role(QtWidgets.QLabel(
            ("Collect a program installed or run on this machine" if live else
             "Collect a program from a forensic image") +
            " - its folder, saved data, caches, shortcuts, Prefetch and registry keys - or chosen files and "
            "folders into the case. Originals are never changed: every file is copied, hashed and recorded in "
            "the chain of custody."), "muted")
        subtitle.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        head.addLayout(titles, 1)
        root.addLayout(head)
        if _theme is not None:
            self.help_btn, self.help_panel = _theme.how_it_works(
                "<b>1. Pick the source.</b> This machine, or a forensic image and one of its partitions; "
                "Load programs reads every program the source knows of - installed (Uninstall keys), run "
                "(Prefetch, Amcache, BAM, UserAssist) or simply present in Program Files.<br><br>"
                "<b>2. Pick a program.</b> Everything that belongs to it is worked out and listed on the right: "
                "its install folder, each user's AppData, caches, shortcuts and Start menu entries, its Prefetch "
                "files and its registry keys, with why each one is there and its size. Untick what you do not "
                "want.<br><br>"
                "<b>3. Collect.</b> The files are copied into the case under Acquisitions, hashed (SHA-256) and "
                "recorded in the chain of custody; registry keys are exported. Nothing on the source is changed. "
                "The Files and folders tab collects any paths you choose instead of a program.")
            head.addWidget(self.help_btn, 0, QtCore.Qt.AlignBottom)
            root.addWidget(self.help_panel)

        # Source.
        src_card, src_v, _sh = self._card(
            "Source", "This machine's programs load by themselves; Load programs reads them again." if live else
            "Choose a forensic image and one of its partitions, then load its programs.")
        src = QtWidgets.QGridLayout()
        src.setHorizontalSpacing(12)
        src.setVerticalSpacing(10)
        self.live_radio = QtWidgets.QRadioButton("This machine")
        self.image_radio = QtWidgets.QRadioButton("Forensic image")
        self.live_radio.setChecked(True)
        self.image_path = QtWidgets.QLineEdit()
        self.image_path.setPlaceholderText("E01, VHD/VHDX, VMDK, raw ...")
        self.image_browse = self._variant(QtWidgets.QPushButton("Browse..."), "ghost")
        self.partition_combo = QtWidgets.QComboBox()
        self.partition_combo.setMinimumWidth(300)
        self.load_btn = self._variant(QtWidgets.QPushButton("Load programs"), "primary",
                                      "Read every program the source knows of")
        self.load_btn.setMinimumWidth(150)
        src.addWidget(self.live_radio, 0, 0)
        src.addWidget(self.image_radio, 0, 1)
        src.addWidget(self.image_path, 0, 2)
        src.addWidget(self.image_browse, 0, 3)
        self.partition_label = self._role(QtWidgets.QLabel("Partition"), "label")
        src.addWidget(self.partition_label, 0, 4)
        src.addWidget(self.partition_combo, 0, 5)
        src.addWidget(self.load_btn, 0, 6)
        src.setColumnStretch(2, 1)
        if self._preset_source is not None:
            for w in (self.live_radio, self.image_radio, self.image_path, self.image_browse, self.partition_combo):
                w.setEnabled(False)
            preset = self._role(QtWidgets.QLabel("Recovering from %s" % self._preset_source.describe()), "note")
            src.addWidget(preset, 1, 0, 1, 7)
        src_v.addLayout(src)
        if self._preset_source is None:
            if live:
                for w in (self.image_radio, self.image_path, self.image_browse, self.partition_label,
                          self.partition_combo):
                    w.hide()
                self.live_radio.setText("This machine (%s)" % os.environ.get("SystemDrive", "C:"))
            else:
                self.live_radio.hide()
                self.image_radio.setChecked(True)
                self.load_btn.setText("Load the image's programs")
        root.addWidget(src_card)

        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(10)

        # Left: what to collect.
        left, lv, _lh = self._card("Choose what to collect")
        self.mode_tabs = QtWidgets.QTabWidget()
        self.mode_tabs.setDocumentMode(True)
        apps_page = QtWidgets.QWidget()
        av = QtWidgets.QVBoxLayout(apps_page)
        av.setContentsMargins(0, 8, 0, 0)
        av.setSpacing(8)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search programs by name or publisher...")
        self.app_list = QtWidgets.QListWidget()
        self.app_list.setAlternatingRowColors(True)
        self.app_list.setUniformItemSizes(True)
        self.app_list.setIconSize(QtCore.QSize(18, 18))
        av.addWidget(self.search)
        from ui.loading_panel import LoadingPanel
        self.list_loading = LoadingPanel(
            "Reading the programs", "Installed (Uninstall keys), run (Prefetch, Amcache, BAM, UserAssist) or "
            "present in Program Files.", compact=True)
        self.list_stack = QtWidgets.QStackedWidget()
        self.list_stack.addWidget(self.app_list)
        self.list_stack.addWidget(self.list_loading)
        av.addWidget(self.list_stack, 1)
        files_page = QtWidgets.QWidget()
        fv = QtWidgets.QVBoxLayout(files_page)
        fv.setContentsMargins(0, 8, 0, 0)
        fv.setSpacing(8)
        files_note = self._role(QtWidgets.QLabel(
            "Add files or folders to collect as they are, with their paths kept. For an image, type the path "
            "inside it (Users\\name\\Documents)."), "muted")
        files_note.setWordWrap(True)
        self.path_input = QtWidgets.QLineEdit()
        self.path_input.setPlaceholderText("Path inside the image, or use the buttons")
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        self.add_folder_btn = self._variant(QtWidgets.QPushButton("Add folder..."), "ghost")
        self.add_file_btn = self._variant(QtWidgets.QPushButton("Add files..."), "ghost")
        self.add_path_btn = self._variant(QtWidgets.QPushButton("Add path"), "ghost")
        for b in (self.add_folder_btn, self.add_file_btn, self.add_path_btn):
            row.addWidget(b)
        row.addStretch(1)
        fv.addWidget(files_note)
        fv.addWidget(self.path_input)
        fv.addLayout(row)
        fv.addStretch(1)
        self.mode_tabs.addTab(apps_page, "Application")
        self.mode_tabs.addTab(files_page, "Files and folders")
        lv.addWidget(self.mode_tabs, 1)
        split.addWidget(left)

        # Right: what belongs to it.
        right, rv, _rh = self._card("What will be collected")
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(10)
        self.fp_icon = QtWidgets.QLabel()
        self.fp_icon.setFixedSize(28, 28)
        top.addWidget(self.fp_icon, 0, QtCore.Qt.AlignTop)
        names = QtWidgets.QVBoxLayout()
        names.setSpacing(2)
        self.fp_title = QtWidgets.QLabel("No program chosen")
        self.fp_title.setProperty("keepStyle", True)
        self.fp_title.setStyleSheet("color: #F8FAFC; font-size: 18px; font-weight: 700; background: transparent;")
        self.fp_sub = self._role(QtWidgets.QLabel("Pick a program on the left: its folders, data and registry keys "
                                                  "are worked out and listed here."), "muted")
        self.fp_sub.setWordWrap(True)
        names.addWidget(self.fp_title)
        names.addWidget(self.fp_sub)
        top.addLayout(names, 1)
        rv.addLayout(top)
        self.fp_busy = QtWidgets.QProgressBar()
        self.fp_busy.setRange(0, 0)
        self.fp_busy.setTextVisible(False)
        self.fp_busy.setMaximumHeight(4)
        self.fp_busy.hide()
        rv.addWidget(self.fp_busy)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Item", "Why", "User", "Size"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIconSize(QtCore.QSize(16, 16))
        # A path's end says what it is (...\\Google\\Chrome): cut the middle.
        self.tree.setTextElideMode(QtCore.Qt.ElideMiddle)
        self.tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for col in (1, 2, 3):
            self.tree.header().setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)
        self.notes = self._role(QtWidgets.QLabel(""), "note")
        self.notes.setWordWrap(True)
        self.fp_loading = LoadingPanel(
            "Working out what belongs to it", "Its folder, each user's data and caches, shortcuts and Start "
            "menu entries, Prefetch files and registry keys - then how big each one is.", compact=True)
        self.fp_stack = QtWidgets.QStackedWidget()
        self.fp_stack.addWidget(self.tree)
        self.fp_stack.addWidget(self.fp_loading)
        rv.addWidget(self.fp_stack, 1)
        rv.addWidget(self.notes)
        self.notes.hide()
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 5)
        split.setSizes([420, 1000])
        root.addWidget(split, 1)

        # Progress and actions.
        self.status = self._role(QtWidgets.QLabel("Choose a source and load its programs."), "muted")
        self.progress = QtWidgets.QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(6)
        self.progress.hide()
        actions = QtWidgets.QHBoxLayout()
        actions.setSpacing(8)
        self.total_label = self._role(QtWidgets.QLabel(""), "caption")
        self.open_folder_btn = self._variant(QtWidgets.QPushButton("Open folder"), "ghost")
        self.open_search_btn = self._variant(QtWidgets.QPushButton("Open in Database Search"), "ghost")
        self.cancel_btn = self._variant(QtWidgets.QPushButton("Cancel"), "ghost")
        self.collect_btn = self._variant(QtWidgets.QPushButton("Collect into the case"), "primary")
        self.close_btn = self._variant(QtWidgets.QPushButton("Close"), "ghost")
        for b in (self.open_folder_btn, self.open_search_btn, self.cancel_btn):
            b.hide()
        self.collect_btn.setEnabled(False)
        actions.addWidget(self.total_label)
        actions.addStretch(1)
        for b in (self.open_folder_btn, self.open_search_btn, self.cancel_btn, self.collect_btn):
            actions.addWidget(b)
        actions.addSpacing(16)
        actions.addWidget(self.close_btn)
        root.addWidget(self.status)
        root.addWidget(self.progress)
        root.addLayout(actions)

        # Wiring.
        self.live_radio.toggled.connect(self._source_kind_changed)
        self.image_browse.clicked.connect(self._browse_image)
        self.image_path.editingFinished.connect(self._list_partitions)
        self.load_btn.clicked.connect(self._load)
        self.search.textChanged.connect(self._filter)
        self.app_list.currentItemChanged.connect(self._app_selected)
        self.add_folder_btn.clicked.connect(self._add_folder)
        self.add_file_btn.clicked.connect(self._add_files)
        self.add_path_btn.clicked.connect(self._add_typed_path)
        self.tree.itemChanged.connect(lambda *_: self._update_total())
        self.collect_btn.clicked.connect(self._collect)
        self.cancel_btn.clicked.connect(self._cancel)
        self.open_folder_btn.clicked.connect(self._open_folder)
        self.open_search_btn.clicked.connect(self._open_search)
        self.close_btn.clicked.connect(self.close)
        self.mode_tabs.currentChanged.connect(self._mode_changed)
        self._source_kind_changed()

    def _icon(self, name, colour="#A5B4FC"):
        try:
            from ui.artifact_icons import artifact_icon
            return artifact_icon(name, colour)
        except Exception:
            return None

    def _auto_load(self):
        """This machine's programs at once, when nothing else was asked for."""
        if self._preset_source is None and self.mode == self.LIVE and self._worker is None and not self._apps:
            self._load()

    # ── case ─────────────────────────────────────────────────────────
    def set_case(self, case_root):
        self.case_root = case_root

    # ── source ───────────────────────────────────────────────────────
    def _source_kind_changed(self, *_):
        image = self.image_radio.isChecked()
        for w in (self.image_path, self.image_browse, self.partition_combo):
            w.setEnabled(image)
        self.add_folder_btn.setEnabled(not image)
        self.add_file_btn.setEnabled(not image)
        self._close_source()

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

    def _close_source(self):
        if self._source is not None and self._source is not self._preset_source:
            try:
                self._source.close()
            except Exception:
                pass
        self._source = self._view = None
        self._apps = []
        self.app_list.clear()
        self.tree.clear()
        self._footprint = None
        self.collect_btn.setEnabled(False)

    def _make_source(self):
        from Artifacts_Collectors.app_acquisition.sources import ImageSource, LiveSource
        if self._preset_source is not None:
            return self._preset_source
        if self.live_radio.isChecked():
            return LiveSource()
        path = self.image_path.text().strip()
        if not path or not os.path.isfile(path):
            raise ValueError("Choose a forensic image first.")
        if self.partition_combo.currentData() is None:
            raise ValueError("The image has no partition to read.")
        return ImageSource(path, int(self.partition_combo.currentData()))

    def _artifacts_dir(self):
        """The case's parsed databases - only for this machine: a case parsed
        from another machine says nothing about an image's programs."""
        # A shadow copy of this machine is this machine at an earlier moment: its case applies.
        same_machine = self.live_radio.isChecked() and (
            self._preset_source is None or getattr(self._preset_source, "kind", "") in ("shadow", "hidden_shadow"))
        if not self.case_root or not same_machine:
            return None
        path = os.path.join(self.case_root, "Target_Artifacts")
        return path if os.path.isdir(path) else None

    def _load(self):
        if self._worker is not None:
            return
        self._close_source()
        artifacts_dir = self._artifacts_dir()

        def work(report):
            from Artifacts_Collectors.app_acquisition.catalog import list_applications
            from Artifacts_Collectors.app_acquisition.registry import RegistryView
            from ui.loading_panel import step
            step(report, "Opening the source")
            source = self._make_source()
            step(report, "Opening its registry hives")
            view = RegistryView(source)
            step(report, "Reading the installed and executed programs")
            return source, view, list_applications(source, artifacts_dir, view)

        def done(res):
            self._source, self._view, self._apps = res
            self._filter()
            self._say("%d programs on %s. Pick one to see what belongs to it."
                      % (len(self._apps), self._source.describe()))
        self._run(work, done, panel=(self.list_stack, self.list_loading))

    def _filter(self):
        text = self.search.text().strip().lower()
        self.app_list.clear()
        for app in self._apps:
            if text and text not in app.name.lower() and text not in (app.publisher or "").lower():
                continue
            item = QtWidgets.QListWidgetItem(app.label())
            icon = self._icon("app_acquisition")
            if icon is not None:
                item.setIcon(icon)
            item.setData(QtCore.Qt.UserRole, app)
            item.setToolTip("Folder: %s\nSeen in: %s%s" % (
                app.install_dir or "(none)", ", ".join(app.sources),
                ("\nLast run: " + app.last_run) if app.last_run else ""))
            self.app_list.addItem(item)

    # ── footprint ────────────────────────────────────────────────────
    def _app_selected(self, current, _previous=None):
        if current is None or self._source is None or self._worker is not None:
            return
        app = current.data(QtCore.Qt.UserRole)
        artifacts_dir = self._artifacts_dir()
        source, view = self._source, self._view
        self.fp_title.setText(app.label())
        self.fp_sub.setText("Working out what belongs to it: folders, each user's data, shortcuts, Prefetch and "
                            "registry keys...")
        icon = self._icon("app_acquisition")
        if icon is not None:
            self.fp_icon.setPixmap(icon.pixmap(28, 28))
        self.tree.clear()

        def work(report):
            from Artifacts_Collectors.app_acquisition.footprint import build_footprint, measure
            from ui.loading_panel import step
            step(report, "Finding its folders, data, shortcuts and registry keys")
            fp = build_footprint(app, source, artifacts_dir, view, progress=report)
            step(report, "Measuring the %d item(s) found" % len(fp.items))
            for n, item in enumerate(fp.items, 1):
                report("Measuring %s" % item.path, n, len(fp.items))
                measure(item, source)
            return fp
        self._run(work, self._show_footprint, panel=(self.fp_stack, self.fp_loading))

    def _show_footprint(self, fp):
        self._footprint = fp
        self.fp_busy.hide()
        self.fp_title.setText(fp.app.label())
        self.fp_sub.setText(self._summary(fp.items) + "  Untick anything you do not want, then Collect.")
        self.tree.blockSignals(True)
        self.tree.clear()
        for item in fp.items:
            label = ("%s\\%s" % ("HKLM\\SOFTWARE" if item.hive == "SOFTWARE" else
                                 "HKU\\" + item.hive.split(":", 1)[-1], item.path)) if item.kind == "registry" \
                else item.path
            row = QtWidgets.QTreeWidgetItem([label, item.reason, item.user or "all users",
                                             "key" if item.kind == "registry" else
                                             "%s (%d file%s)" % (_human(item.size), item.files or 0,
                                                                 "" if item.files == 1 else "s")
                                             if item.kind == "folder" else _human(item.size)])
            row.setFlags(row.flags() | QtCore.Qt.ItemIsUserCheckable)
            row.setCheckState(0, QtCore.Qt.Checked if item.selected else QtCore.Qt.Unchecked)
            row.setData(0, _KIND_ROLE, item)
            icon = self._icon({"registry": "registry", "folder": "folder"}.get(item.kind, "parse_offline"))
            if icon is not None:
                row.setIcon(0, icon)
            row.setToolTip(0, label)
            self.tree.addTopLevelItem(row)
        self.tree.blockSignals(False)
        self._note("\n".join(fp.notes))
        self._update_total()
        self._say("Untick anything you do not want, then Collect.")

    def _summary(self, items, chosen_only=False):
        """What a footprint holds, in one line: its size, files and folders, and its registry keys
        by hive - or that it has none, which is a finding too."""
        items = [i for i in items if i.selected] if chosen_only else list(items)
        files = sum(i.files or (1 if i.kind == "file" else 0) for i in items if i.kind != "registry")
        folders = sum(1 for i in items if i.kind == "folder")
        size = sum(i.size or 0 for i in items if i.kind != "registry")
        keys = [i for i in items if i.kind == "registry"]
        hives = {}
        for k in keys:
            h = "HKLM" if k.hive == "SOFTWARE" else "HKU" if k.hive.startswith("NTUSER") or ":" in k.hive \
                else k.hive
            hives[h] = hives.get(h, 0) + 1
        reg = ("%d registry key%s (%s)" % (len(keys), "" if len(keys) == 1 else "s",
                                           ", ".join("%s %d" % kv for kv in sorted(hives.items())))
               if keys else "no registry keys found")
        return "%s in %s file%s and %d folder%s  \u00b7  %s." % (
            _human(size), "{:,}".format(files), "" if files == 1 else "s", folders, "" if folders == 1 else "s", reg)

    def _update_total(self):
        total = files = 0
        chosen = 0
        for i in range(self.tree.topLevelItemCount()):
            row = self.tree.topLevelItem(i)
            item = row.data(0, _KIND_ROLE)
            item.selected = row.checkState(0) == QtCore.Qt.Checked
            if item.selected:
                chosen += 1
                total += item.size or 0
                files += item.files or 0
        self.total_label.setText(("To collect: " + self._summary(self._footprint.items, chosen_only=True))
                                 if chosen and self._footprint is not None else "")
        self.collect_btn.setEnabled(chosen > 0 and self._worker is None and bool(self.case_root))

    # ── files and folders mode ───────────────────────────────────────
    def _mode_changed(self, index):
        if index == 1 and self._source is None:
            try:
                self._source = self._make_source()
                from Artifacts_Collectors.app_acquisition.registry import RegistryView
                self._view = RegistryView(self._source)
            except Exception as exc:
                self._say(str(exc), error=True)
                return
        if index == 1 and (self._footprint is None or self._footprint.app.name != "Chosen files and folders"):
            from Artifacts_Collectors.app_acquisition.catalog import AppEntry
            from Artifacts_Collectors.app_acquisition.footprint import Footprint
            self._show_footprint(Footprint(AppEntry(name="Chosen files and folders", sources=["examiner"])))

    def _add_rel(self, rel: str, is_dir: bool):
        from Artifacts_Collectors.app_acquisition.footprint import FootprintItem, measure, _user_of
        if self._footprint is None:
            self._mode_changed(1)
        item = FootprintItem("folder" if is_dir else "file", rel, "chosen by the examiner", _user_of(rel))
        measure(item, self._source)
        self._footprint.add(item)
        self._show_footprint(self._footprint)

    def _live_rel(self, path: str) -> Optional[str]:
        drive, rest = os.path.splitdrive(os.path.abspath(path))
        if drive.upper() + "\\" != self._source.volume.upper():
            # One volume per acquisition: the copy keeps paths below it.
            from Artifacts_Collectors.app_acquisition.sources import LiveSource
            if self._footprint and self._footprint.items:
                self._say("%s is on another drive. Collect it in a separate acquisition." % path, error=True)
                return None
            self._source = LiveSource(drive)
        return rest.strip("\\")

    def _add_folder(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder to collect")
        if path and self._source is not None:
            rel = self._live_rel(path)
            if rel is not None:
                self._add_rel(rel, True)

    def _add_files(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Files to collect")
        for path in paths:
            rel = self._live_rel(path)
            if rel is not None:
                self._add_rel(rel, False)

    def _add_typed_path(self):
        if self._source is None:
            self._mode_changed(1)
        if self._source is None:
            return
        text = self.path_input.text().strip()
        rel = os.path.splitdrive(text)[1].replace("/", "\\").strip("\\") if text else ""
        if not rel:
            return
        if self._source.isdir(rel):
            self._add_rel(rel, True)
        elif self._source.isfile(rel):
            self._add_rel(rel, False)
        else:
            self._say("Not found on %s: %s" % (self._source.describe(), rel), error=True)
            return
        self.path_input.clear()

    # ── collect ──────────────────────────────────────────────────────
    def _collect(self):
        if not self.case_root:
            self._say("Open a case first: the acquisition is collected into it.", error=True)
            return
        if self._footprint is None or self._source is None:
            return
        fp, source, view, case_root = self._footprint, self._source, self._view, self.case_root
        self.cancel_btn.show()
        worker_ref = {}

        def work(report):
            from Artifacts_Collectors.app_acquisition.collector import acquire
            return acquire(fp, source, case_root, progress=report,
                           is_cancelled=lambda: bool(worker_ref.get("w") and worker_ref["w"].cancelled),
                           view=view)

        def done(result):
            self.cancel_btn.hide()
            self._last_folder = result.folder
            self.open_folder_btn.show()
            self.open_search_btn.setVisible(bool(result.databases) and self._open_database_search is not None)
            msg = "%s: %d file(s), %s, %d registry key(s)" % (
                {"completed": "Collected", "partial": "Collected with problems",
                 "cancelled": "Stopped", "failed": "Nothing was collected"}[result.status],
                result.files, _human(result.bytes), result.registry_keys)
            if result.databases:
                msg += "; %d database(s) ready in Database Search" % len(result.databases)
            if result.failed:
                msg += "; %d file(s) could not be read" % result.failed
            self._say(msg, error=result.status == "failed", ok=result.status == "completed")
            if result.errors:
                self._note("\n".join(result.errors[:8]))
        self._run(work, done, busy="App Acquisition is copying files")
        worker_ref["w"] = self._worker

    def _cancel(self):
        if self._worker is not None:
            self._worker.cancelled = True
            self._say("Stopping after the current file...")

    def _open_folder(self):
        if self._last_folder and os.path.isdir(self._last_folder):
            if os.name == "nt":
                os.startfile(self._last_folder)
            else:
                subprocess.Popen(["xdg-open", self._last_folder])

    def _open_search(self):
        if self._open_database_search is not None:
            self._open_database_search()

    # ── plumbing ─────────────────────────────────────────────────────
    def _note(self, text):
        """The note line, hidden when there is nothing to say (its frame
        would otherwise show as an empty box)."""
        self.notes.setText(text)
        self.notes.setVisible(bool(text))

    def _say(self, text, error=False, ok=False):
        self.status.setText(text)
        if _theme is not None:
            _theme.set_status(self.status, "bad" if error else ("ok" if ok else "neutral"))

    def _run(self, fn, on_done, busy=None, panel=None):
        """`panel`: (stack, LoadingPanel) shown in place of the stack's content while `fn` runs."""
        worker = _Worker(fn, self)
        if panel is not None:
            stack, loading = panel
            loading.restart()
            stack.setCurrentWidget(loading)
            worker.progress.connect(loading.report)
        self._worker = worker
        for w in (self.load_btn, self.collect_btn, self.app_list, self.tree):
            w.setEnabled(False)
        # One bar at a time: a loading panel in front carries its own.
        if panel is None:
            self.progress.show()
            self.progress.setRange(0, 0)
        if busy:
            try:
                from ui import busy_guard
                self._busy_token = busy_guard.begin(busy, alive=worker.isRunning)
            except Exception:
                self._busy_token = None

        def progress(msg, done, total):
            self.status.setText(msg)
            if total:
                self.progress.setRange(0, total)
                self.progress.setValue(done)

        def finish():
            self._worker = None
            self.fp_busy.hide()
            if panel is not None:
                panel[1].finish()
                panel[0].setCurrentIndex(0)
            if self._busy_token is not None:
                try:
                    from ui import busy_guard
                    busy_guard.end(self._busy_token)
                except Exception:
                    pass
                self._busy_token = None
            self.progress.hide()
            for w in (self.load_btn, self.app_list, self.tree):
                w.setEnabled(True)
            self._update_total()

        def ok(result):
            finish()
            on_done(result)

        def bad(message):
            if panel is not None:
                panel[1].fail(message)
            finish()
            self.cancel_btn.hide()
            self._say(message, error=True)
        worker.progress.connect(progress)
        worker.finished_ok.connect(ok)
        worker.failed.connect(bad)
        worker.start()

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancelled = True
            self._say("Finishing the current file before closing...")
            self._worker.wait(15000)
        self._close_source()
        super().closeEvent(event)
