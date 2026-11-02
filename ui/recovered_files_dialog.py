"""Case -> Recovered & Collected Files: everything this case took from evidence.

Every program acquired (App Acquisition), every file collected or recovered
from the File Browser or the Shadow Copies window, every deleted file
recovered from its MFT record, and every file restored onto the examined
machine is a run with its own manifest:

    <case>/app_acquisition/<run>/app_manifest.json    acquired, collected, recovered
    <case>/Restores/restore_<UTC>.json                restored onto the machine

Before this window the files were only reachable from the window that made
them, in the same session ("Open collected folder"). Here every run is
listed, newest first, with its files: the path below the volume, the copy in
the case, the SHA-256, whether the copy matched its source, and - for a
recovered deleted file - the risk that its clusters were reused. The folder
and the run's chain-of-custody record open from here. Nothing is changed.
"""
import datetime as _dt
import glob
import json
import os

from PyQt5 import QtCore, QtWidgets

try:
    from ui import app_theme as _theme
except Exception:            # pragma: no cover - the theme is optional
    _theme = None

KIND_WORDS = {
    "crow-eye application acquisition 1": "Program acquired",
    "crow-eye deleted file recovery 1": "Deleted files recovered (MFT)",
    "restore": "Restored onto the machine",
}


def _when(stamp):
    """'2026-11-01T09:12:17+00:00' or '20261101T091217Z' -> '2026-11-01 09:12:17'."""
    s = str(stamp or "")
    for fmt in ("%Y%m%dT%H%M%SZ",):
        try:
            return _dt.datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return s.replace("T", " ")[:19]


def runs_in(case_root):
    """Every acquisition, collection, recovery and restore of the case, newest
    first: [{kind, when, source, status, files, failed, folder, custody, items}].
    items: [{path, copy, size, sha256, verified, note}]."""
    out = []
    if not case_root:
        return out
    for path in glob.glob(os.path.join(case_root, "app_acquisition", "*", "app_manifest.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                m = json.load(fh)
        except (OSError, ValueError):
            continue
        folder = os.path.dirname(path)
        kind = KIND_WORDS.get(m.get("format"), "Collected")
        app = (m.get("application") or {}).get("name") or ""
        if kind == "Program acquired" and (app.startswith("Files from ") or app.startswith("Recovered from ")):
            kind = "Files collected" if app.startswith("Files from ") else "Recovered from a shadow copy"
        items = []
        for f in m.get("files") or []:
            note = f.get("risk") or ("matched its source" if f.get("verified") is True else
                                     "did not match its source" if f.get("verified") is False else
                                     "no source to compare (image or rebuilt copy)")
            items.append({"path": f.get("path"), "copy": os.path.join(folder, f.get("copy") or ""),
                          "size": f.get("size"), "sha256": f.get("sha256"),
                          "verified": f.get("verified"), "note": note})
        totals = m.get("totals") or {}
        out.append({"kind": kind, "when": _when(m.get("finished_utc") or m.get("started_utc")),
                    "source": m.get("source") or "", "status": m.get("status") or "",
                    "files": totals.get("files", len(items)), "failed": totals.get("failed", 0),
                    "folder": folder, "custody": m.get("custody_record"), "items": items,
                    "name": app})
    for path in glob.glob(os.path.join(case_root, "Restores", "restore_*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                m = json.load(fh)
        except (OSError, ValueError):
            continue
        items = [{"path": f.get("path"), "copy": f.get("restored_to"), "size": f.get("size"),
                  "sha256": f.get("sha256"), "verified": None,
                  "note": "restored %s" % ("beside the current file" if f.get("how") == "beside"
                                           else "to its place")} for f in m.get("files") or []]
        out.append({"kind": KIND_WORDS["restore"], "when": _when(m.get("restored_utc")),
                    "source": m.get("source") or "", "status": m.get("status") or "",
                    "files": len(items), "failed": len(m.get("failed") or []),
                    "folder": os.path.dirname(path), "custody": path, "items": items, "name": ""})
    return sorted(out, key=lambda r: r["when"], reverse=True)


def _size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


class RecoveredFilesDialog(QtWidgets.QDialog):
    def __init__(self, case_root, parent=None):
        super().__init__(parent)
        self.case_root = case_root
        self.setWindowTitle("Recovered & Collected Files")
        self.resize(1180, 720)
        lay = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            "Everything this case took from evidence: programs acquired, files collected or recovered "
            "from the File Browser and the Shadow Copies window, deleted files recovered from their MFT "
            "records, and files restored onto the machine. Each run has its own folder, manifest and "
            "chain-of-custody record.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        split = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.runs = QtWidgets.QTableWidget(0, 6)
        self.runs.setHorizontalHeaderLabels(["When (UTC)", "What", "Source", "Files", "Status", "Folder"])
        self.files = QtWidgets.QTableWidget(0, 5)
        self.files.setHorizontalHeaderLabels(["Path", "Size", "Check", "SHA-256", "Copy in the case"])
        for t in (self.runs, self.files):
            t.verticalHeader().hide()
            t.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            t.setAlternatingRowColors(True)
            t.horizontalHeader().setStretchLastSection(True)
            split.addWidget(t)
        split.setSizes([260, 400])
        lay.addWidget(split, 1)
        row = QtWidgets.QHBoxLayout()
        self.count = QtWidgets.QLabel("")
        row.addWidget(self.count)
        row.addStretch(1)
        self.folder_btn = QtWidgets.QPushButton("Open folder")
        self.custody_btn = QtWidgets.QPushButton("Open custody record")
        refresh = QtWidgets.QPushButton("Refresh")
        close = QtWidgets.QPushButton("Close")
        for b in (self.folder_btn, self.custody_btn, refresh, close):
            row.addWidget(b)
        lay.addLayout(row)
        self.folder_btn.clicked.connect(lambda: self._open("folder"))
        self.custody_btn.clicked.connect(lambda: self._open("custody"))
        refresh.clicked.connect(self.load)
        close.clicked.connect(self.close)
        self.runs.itemSelectionChanged.connect(self._show_files)
        self.files.cellDoubleClicked.connect(self._open_copy)
        self._runs = []
        self._finish_styling()
        self.load()

    def _finish_styling(self):
        """The app's look, as the custody viewer finishes it: the theme on the window,
        the buttons in the role family, a taskbar button of its own."""
        try:
            from styles import CrowEyeStyles as _CES
            _CES.give_window_a_taskbar_button(self)
        except Exception:
            pass
        try:
            from ui.app_theme import apply_theme, set_variant
            apply_theme(self)
            set_variant(self.folder_btn, "primary")
            for b in self.findChildren(QtWidgets.QPushButton):
                if b.property("variant") is None:
                    set_variant(b, "ghost")
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        # Widths from the font actually in use (the theme's), not the default one.
        QtCore.QTimer.singleShot(0, self._fit_columns)

    def _fit_columns(self):
        for t, wide in ((self.runs, (2, 5)), (self.files, (0, 2))):
            t.resizeColumnsToContents()
            for c in wide:
                t.setColumnWidth(c, min(max(t.columnWidth(c), 160), 520))

    def load(self):
        self._runs = runs_in(self.case_root)
        self.runs.setRowCount(len(self._runs))
        for r, run in enumerate(self._runs):
            what = run["kind"] + (": " + run["name"] if run["kind"] == "Program acquired" and run["name"] else "")
            files = "%d" % run["files"] + (" (%d not)" % run["failed"] if run["failed"] else "")
            for c, v in enumerate([run["when"], what, run["source"], files, run["status"],
                                   os.path.relpath(run["folder"], self.case_root)]):
                self.runs.setItem(r, c, QtWidgets.QTableWidgetItem(str(v)))
        self.runs.resizeColumnsToContents()
        total = sum(r["files"] for r in self._runs)
        self.count.setText("%d run(s), %d file(s)" % (len(self._runs), total) if self._runs
                           else "Nothing has been collected or recovered into this case yet.")
        if self._runs:
            self.runs.selectRow(0)
        self._show_files()

    def _current(self):
        rows = self.runs.selectionModel().selectedRows()
        return self._runs[rows[0].row()] if rows and rows[0].row() < len(self._runs) else None

    def _show_files(self):
        run = self._current()
        items = run["items"] if run else []
        self.files.setRowCount(len(items))
        for r, f in enumerate(items):
            for c, v in enumerate([f["path"], _size(f["size"]), f["note"], f["sha256"] or "", f["copy"] or ""]):
                self.files.setItem(r, c, QtWidgets.QTableWidgetItem(str(v or "")))
        self.files.resizeColumnsToContents()
        self.folder_btn.setEnabled(bool(run))
        self.custody_btn.setEnabled(bool(run and run["custody"] and os.path.exists(run["custody"])))

    def _open(self, what):
        run = self._current()
        target = run and (run["folder"] if what == "folder" else run["custody"])
        if target and os.path.exists(target) and os.name == "nt":
            os.startfile(target)

    def _open_copy(self, row, _col):
        run = self._current()
        if not run or row >= len(run["items"]):
            return
        copy = run["items"][row]["copy"]
        if copy and os.path.exists(copy) and os.name == "nt":
            os.startfile(os.path.dirname(copy))
