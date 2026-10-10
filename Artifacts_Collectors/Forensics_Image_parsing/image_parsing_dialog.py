"""
Forensic Image Parsing - the window that reads a disk image into a case.

Layout (two columns and a fixed action bar):

    header      title, the open case, the image summary once scanned
    left        SETUP, scrolls: (1) Image - file, format, health badges
                                (2) Partitions - file system, size, Windows, BitLocker
                                (3) Extraction settings
    right       progress strip, then tabs: Artifacts / Log / Issues
    action bar  Start analysis + Cancel  ...  Parse artifacts, Export results, Close
                - outside the scroll area, so it can never be clipped

Everything an investigator can get wrong, and everything wrong with an image,
is found before or during the run (image_preflight.py) and named as a session
issue: shown in the Issues tab, and written into the same Parse Status Report
the live parse shows - one report for the whole session.

Author: Ghassan Elsman
License: GPL-3.0
"""

import hashlib
import logging
import os
import sys
import time

# Task 11.2: Use PathUtils for robust root resolution in EXE mode
try:
    from utils.path_utils import PathUtils
    app_root = PathUtils.get_app_root()
    current_dir = app_root / 'Artifacts_Collectors' / 'Forensics_Image_parsing'
    parent_dir = app_root / 'Artifacts_Collectors'
except ImportError:
    # Fallback if PathUtils is not accessible
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.abspath(os.path.join(current_dir, '..'))

if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from datetime import datetime
from typing import List, Optional, Union

from PyQt5.QtCore import QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget
)

logger = logging.getLogger("image_parsing.dialog")

# The animated loading bar (a light sweep that keeps moving between updates,
# so long work never looks frozen). Falls back to the plain bar when this
# module runs standalone without the Crow-Eye root on sys.path.
try:
    from ui.animated_progress_bar import AnimatedProgressBar
except ImportError:
    AnimatedProgressBar = None


def _mark_busy(reason, thread):
    """Tell the main window Crow-Eye is working while `thread` runs, so its
    feature windows refuse to open against data still being written
    (ui/busy_guard.py). Released by itself when the thread stops."""
    try:
        from ui import busy_guard
        busy_guard.begin(reason, alive=thread.isRunning)
    except Exception:
        pass


# Import image parsing components
try:
    if __package__ or "." in __name__:
        from .image_parser import ImageParser
        from .data_models import PartitionInfo, ImageInfo, ExtractionOptions
        from .image_collection_wrapper import ImageCollectionCoordinator
        from .image_preflight import (PartitionFacts, check_case, human_size,
                                      issue_for_open_error, partition_issues, preflight_image)
    else:
        from image_parser import ImageParser
        from data_models import PartitionInfo, ImageInfo, ExtractionOptions
        from image_collection_wrapper import ImageCollectionCoordinator
        from image_preflight import (PartitionFacts, check_case, human_size,
                                     issue_for_open_error, partition_issues, preflight_image)
except (ImportError, ValueError):
    from image_parser import ImageParser
    from data_models import PartitionInfo, ImageInfo, ExtractionOptions
    from image_collection_wrapper import ImageCollectionCoordinator
    from image_preflight import (PartitionFacts, check_case, human_size,
                                 issue_for_open_error, partition_issues, preflight_image)

# The Offline Importer, through the package: one copy of its modules, the same
# classes the importer and ParserInvoker use, and records that reach its log.
try:
    from Artifacts_Collectors.Offline_Importer.collection_coordinator import (
        CollectionCoordinator, CollectionSummary, ProgressUpdate)
    from Artifacts_Collectors.Offline_Importer.artifact_collector import CollectedArtifactInfo
    from Artifacts_Collectors.Offline_Importer.parse_artifacts_dialog import ParseArtifactsDialog
    from Artifacts_Collectors.Offline_Importer.artifact_scan_index import (
        ArtifactScanIndex, ScannedArtifact)
    from Artifacts_Collectors.Offline_Importer.parser_invoker import ParserInvoker
    from Artifacts_Collectors.Offline_Importer.parse_artifacts_dialog import ParsingWorker
except ImportError:
    from Offline_Importer.collection_coordinator import (
        CollectionCoordinator, CollectionSummary, ProgressUpdate)
    from Offline_Importer.artifact_collector import CollectedArtifactInfo
    from Offline_Importer.parse_artifacts_dialog import ParseArtifactsDialog
    from Offline_Importer.artifact_scan_index import ArtifactScanIndex, ScannedArtifact
    from Offline_Importer.parser_invoker import ParserInvoker
    from Offline_Importer.parse_artifacts_dialog import ParsingWorker

try:
    from utils.parse_status import make_issue, record_outcomes
except ImportError:  # pragma: no cover - standalone without the app root
    make_issue = None
    record_outcomes = None

try:
    from ui.parse_status_dialog import IssuesPanel, ParseStatusDialog
except ImportError:  # pragma: no cover
    IssuesPanel = None
    ParseStatusDialog = None

# Load Crow-Eye styles REGARDLESS of how the imports above resolved.
try:
    from utils.path_utils import PathUtils
    styles_path = PathUtils.get_app_root()
    if str(styles_path) not in sys.path:
        sys.path.insert(0, str(styles_path))
    from styles import CrowEyeStyles, Colors
    STYLES_AVAILABLE = True
except ImportError:
    logger.warning("Could not import CrowEyeStyles. Using default styling.")
    STYLES_AVAILABLE = False

    class Colors:
        BG_PRIMARY = "#0F172A"
        BG_PANELS = "#1E293B"
        TEXT_PRIMARY = "#E2E8F0"
        ACCENT_BLUE = "#3B82F6"
        BORDER_SUBTLE = "#334155"
        BORDER_ACCENT = "#3B82F6"


# ============================================================================
# Icons (Crow-Eye's own SVG set - never emoji)
# ============================================================================

def _ip_icon(name):
    from correlation_engine.gui.crow_eye_icons import CrowEyeIcons
    return getattr(CrowEyeIcons, name)()


def _ip_pbtn(text, name):
    b = QPushButton(text)
    try:
        b.setIcon(_ip_icon(name))
        b.setIconSize(QSize(16, 16))
    except Exception:
        pass
    return b


def _ip_cbox(text, name):
    c = QCheckBox(text)
    try:
        c.setIcon(_ip_icon(name))
        c.setIconSize(QSize(16, 16))
    except Exception:
        pass
    return c


# ============================================================================
# Style - every rule keyed by objectName, so nothing leaks into child widgets
# (the old panel rule `QFrame { margin: 5px }` matched every QLabel, list,
# text box and table inside it, because they are all QFrames).
# ============================================================================

# The site's look (ui/site_theme.py tokens): the window carries the site sheet
# (begin_site_theme) and this objectName-keyed sheet on ipRoot shapes the
# layout's own pieces. Tab text has no colour here on purpose: the Issues tab
# shows its severity through setTabTextColor, which a QSS colour overrides.
_QSS_TEMPLATE = """
QWidget#ipRoot { background: #0A0C10; }
QWidget#ipRoot QLabel { color: #E2E8F0; }
QLabel#ipTitle { color: #F8FAFC; font-size: 22px; font-weight: 800; }
QLabel#ipCase { color: #94A3B8; font-size: 13px; }
QLabel#ipImageSummary { color: #E2E8F0; font-size: 13px; font-weight: 600; }

QScrollArea#ipSetupScroll, QWidget#ipSetupHost { background: transparent; border: none; }
QFrame#ipCard { background: #0F172A; border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; }
QLabel#ipStepNum { color: #FFFFFF; border-radius: 11px; font-weight: 800; font-size: 12px;
                   background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #6366F1, stop:1 #22D3EE); }
QLabel#ipStepTitle { color: #F8FAFC; font-size: 15px; font-weight: 700; }
QLabel#ipMuted { color: #94A3B8; font-size: 12px; }
QLabel#ipPath { color: #E2E8F0; background: #0A0C10; border: 1px solid rgba(255,255,255,0.14);
                border-radius: 10px; padding: 7px 10px; font-family: '%(mono)s', Consolas, monospace;
                font-size: 12px; }
QLabel#ipBadge { border-radius: 9px; padding: 3px 10px; font-size: 12px; font-weight: 700;
                 background: transparent; }

QListWidget#ipPartitions { background: #0A0C10; color: #E2E8F0; border: 1px solid rgba(255,255,255,0.08);
                           border-radius: 12px; padding: 4px; font-size: 13px; }
QListWidget#ipPartitions::item { padding: 6px 4px; border-radius: 6px; }
QListWidget#ipPartitions::item:selected { background: rgba(99,102,241,0.28); color: #F8FAFC; }

QComboBox#ipCombo { color: #F8FAFC; background: #0A0C10; border: 1px solid rgba(255,255,255,0.14);
                    border-radius: 10px; padding: 5px 10px; min-height: 26px; font-size: 13px; }
QComboBox#ipCombo:hover, QComboBox#ipCombo:focus { border: 1px solid #6366F1; }
QComboBox#ipCombo QAbstractItemView { background: #0F172A; color: #E2E8F0;
                                      selection-background-color: rgba(99,102,241,0.30); }
QCheckBox#ipOption { color: #E2E8F0; font-size: 13px; spacing: 8px; }

QFrame#ipProgress { background: #0F172A; border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; }
QLabel#ipOperation { color: #F8FAFC; font-size: 14px; font-weight: 600; }
QLabel#ipStat { color: #94A3B8; font-size: 13px; }
QLabel#ipStatValue { color: #F8FAFC; font-size: 15px; font-weight: 800;
                     font-family: '%(mono)s', Consolas, monospace; }

QTabWidget#ipTabs::pane { border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; background: #0F172A;
                          top: -1px; }
QTabWidget#ipTabs QTabBar::tab { background: transparent; padding: 6px 16px;
                                 border: 1px solid transparent; border-radius: 13px;
                                 margin: 0 4px 8px 0; font-size: 13px; font-weight: 700; }
QTabWidget#ipTabs QTabBar::tab:hover { border-color: rgba(255,255,255,0.12); }
QTabWidget#ipTabs QTabBar::tab:selected { background: rgba(99,102,241,0.16); border-color: #6366F1; }

QTableWidget#ipResults { background: rgba(10,12,16,0.55); alternate-background-color: rgba(255,255,255,0.02);
                         color: #E2E8F0; border: none; gridline-color: rgba(255,255,255,0.04); font-size: 12px; }
QTableWidget#ipResults::item { border-bottom: 1px solid rgba(255,255,255,0.04); }
QTableWidget#ipResults::item:selected { background: rgba(99,102,241,0.28); color: #F8FAFC; }
QTableWidget#ipResults QHeaderView::section { background: transparent; color: #94A3B8;
                                             padding: 8px 6px 6px 6px; border: none;
                                             border-bottom: 1px solid rgba(255,255,255,0.08); font-weight: 700; }
QTextEdit#ipLog { background: #0A0C10; color: #E2E8F0; border: none;
                  font-family: '%(mono)s', Consolas, monospace; font-size: 12px; padding: 8px; }

QFrame#ipActionBar { background: #0F172A; border-top: 1px solid rgba(255,255,255,0.08); }
QPushButton#ipPrimary { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #6366F1, stop:1 #4F46E5);
                        color: white; border: none; border-radius: 16px; padding: 8px 22px;
                        font-size: 13px; font-weight: 800; min-height: 20px; }
QPushButton#ipPrimary:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #818CF8, stop:1 #22D3EE); }
QPushButton#ipPrimary:disabled { background: rgba(99,102,241,0.18); color: #64748B; }
QPushButton#ipSecondary { background: transparent; color: #94A3B8; border: 1px solid rgba(255,255,255,0.14);
                          border-radius: 16px; padding: 8px 18px; font-size: 13px;
                          font-weight: 700; min-height: 20px; }
QPushButton#ipSecondary:hover { color: #F8FAFC; background: rgba(255,255,255,0.06);
                                border-color: rgba(255,255,255,0.28); }
QPushButton#ipSecondary:disabled { color: #475569; border-color: rgba(255,255,255,0.08); }
QPushButton#ipSmall { background: transparent; color: #94A3B8; border: 1px solid rgba(255,255,255,0.12);
                      border-radius: 12px; padding: 3px 11px; font-size: 12px; font-weight: 600; }
QPushButton#ipSmall:hover { color: #F8FAFC; border: 1px solid #6366F1; }

QWidget#ipRoot QScrollBar:vertical { background: transparent; width: 10px; margin: 0; border: none; }
QWidget#ipRoot QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; border: none; }
QWidget#ipRoot QScrollBar::handle:vertical { background: #334155; min-height: 30px; border-radius: 5px; }
QWidget#ipRoot QScrollBar::handle:horizontal { background: #334155; min-width: 30px; border-radius: 5px; }
QWidget#ipRoot QScrollBar::handle:hover { background: #6366F1; }
QWidget#ipRoot QScrollBar::add-line, QWidget#ipRoot QScrollBar::sub-line { width: 0; height: 0; border: none; }
QWidget#ipRoot QScrollBar::add-page, QWidget#ipRoot QScrollBar::sub-page { background: transparent; }
QWidget#ipRoot QAbstractScrollArea::corner { background: transparent; }

QProgressBar#ipBar { border: none; border-radius: 7px; background: #1E293B;
                     color: #F8FAFC; text-align: center; font-weight: 700; font-size: 11px; }
QProgressBar#ipBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #6366F1, stop:1 #22D3EE);
                            border-radius: 7px; }
"""


def _qss():
    try:
        from ui.site_theme import families
        mono = families()[1]
    except Exception:
        mono = "Consolas"
    return _QSS_TEMPLATE % {"mono": mono}


_QSS = _QSS_TEMPLATE % {"mono": "JetBrains Mono"}

_BADGE = {
    "ok": ("#22C55E", "rgba(34,197,94,0.10)"),
    "warn": ("#F59E0B", "rgba(245,158,11,0.10)"),
    "bad": ("#EF4444", "rgba(239,68,68,0.10)"),
    "idle": ("#64748B", "transparent"),
}

_FILTER_MAP = {
    "All types": None, "Registry hives": "Registry", "Prefetch": "Prefetch",
    "LNK & Jump Lists": "link_jumplist", "$MFT": "MFT", "USN journal": "USN",
    "Recycle Bin": "RecycleBin", "Event logs": "EVTX", "AmCache": "AmCache",
    "ShimCache": "ShimCache", "SRUM": "SRUM", "Browsers": "Browser",
}


# ============================================================================
# Workers
# ============================================================================

class ScanWorker(QThread):
    """Pre-flight, open probe and partition listing - off the GUI thread.

    Emits one dict: preflight, image_info, format, issues (open + partitions
    are named, never just "could not open").
    """
    scan_done = pyqtSignal(object)

    def __init__(self, parser, file_paths):
        super().__init__()
        self.parser = parser
        self.file_paths = list(file_paths)

    def run(self):
        out = {"preflight": None, "image_info": None, "format": "UNKNOWN", "issues": []}
        try:
            pre = preflight_image(self.file_paths)
            out["preflight"] = pre
            out["issues"].extend(pre.issues)
            if pre.blocked:
                self.scan_done.emit(out)
                return
            image = os.path.basename(pre.segments.first or self.file_paths[0])
            # Open the container ourselves first: the parser's own open
            # swallows the reason and returns None.
            if pre.sniff.kind != "ISO":
                try:
                    from dissect.target.container import open as open_container
                    c = open_container(pre.segments.first or self.file_paths[0])
                    try:
                        c.close()
                    except Exception:
                        pass
                except Exception as exc:
                    logger.warning("Image did not open: %s", exc, exc_info=True)
                    out["issues"].append(issue_for_open_error(exc, image))
                    self.scan_done.emit(out)
                    return
            out["format"] = self.parser.detect_format(self.file_paths)
            info = self.parser.get_image_info(self.file_paths)
            out["image_info"] = info
            if not info or not info.partitions:
                out["issues"].append(make_issue(
                    "image_unreadable",
                    "The container opened, but no partition or file system could be listed.",
                    image=image))
        except Exception as exc:
            logger.error("Scan failed: %s", exc, exc_info=True)
            out["issues"].append(issue_for_open_error(exc))
        # Opening an image only reads it, so a ledger line (not a run record):
        # which image, what it was, and what was wrong with it.
        try:
            from utils import custody
            info = out.get("image_info")
            custody.ledger(None, "image scanned", image=self.file_paths, format=out.get("format"),
                           partitions=len(getattr(info, "partitions", None) or []),
                           issues=[getattr(i, "code", None) or (i.get("code") if isinstance(i, dict)
                                                                else str(i))
                                   for i in out.get("issues") or []])
        except Exception:
            pass
        self.scan_done.emit(out)


class CollectionWorker(QThread):
    """Extract artifacts from the image into the case (background).

    collection_failed carries the exception object, so the window can name the
    problem instead of showing a traceback.
    """

    progress_update = pyqtSignal(object)    # ProgressUpdate
    artifact_found = pyqtSignal(object)     # CollectedArtifactInfo
    collection_complete = pyqtSignal(object)  # CollectionSummary
    collection_failed = pyqtSignal(object, str)  # exception, traceback text
    collection_cancelled = pyqtSignal()

    def __init__(self, case_root: str, image_source: Union[str, List[str]],
                 selected_partitions: List[int],
                 artifact_type_filter: Optional[str] = None,
                 calculate_hashes: bool = True,
                 include_browser_cache: bool = True):
        super().__init__()
        self.case_root = case_root
        self.image_source = image_source
        self.selected_partitions = selected_partitions
        self.artifact_type_filter = artifact_type_filter
        self.calculate_hashes = calculate_hashes
        self.include_browser_cache = include_browser_cache
        self._cancelled = False
        self.coordinator = None
        self.session_issues = []

    def run(self):
        """Extraction inside a chain-of-custody record (utils/custody.py).

        An image is not the live machine, so there is no footprint to speak
        of - but which image, which segments, whether it was complete and what
        hash it carries are what the extracted rows rest on, and they belong in
        the case beside the live runs' records.
        """
        rec = None
        try:
            from utils import custody
            try:
                from image_integrity import check_image
            except ImportError:
                from .image_integrity import check_image
            paths = self.image_source if isinstance(self.image_source, list) else [self.image_source]
            rec = custody.begin(self.case_root, "image parse", options={
                "image": paths, "partitions": list(self.selected_partitions or []),
                "artifact_filter": self.artifact_type_filter,
                "calculate_hashes": self.calculate_hashes,
                "include_browser_cache": self.include_browser_cache})
            rec.data["image"] = check_image(paths)
            try:
                from utils.parse_status import ISSUE_CATALOG
            except Exception:
                ISSUE_CATALOG = {}
            for problem in rec.data["image"].get("problems", []):
                title = ISSUE_CATALOG.get(problem, (None, problem))[1]
                rec.warn("Image: %s" % title)
        except Exception as exc:
            logger.warning("Chain-of-custody record not started: %s", exc)
            rec = None
        self._outcome = "failed"
        try:
            self._run()
        finally:
            if rec is not None:
                try:
                    from utils import custody
                    custody.end(self._outcome, rec=rec)
                except Exception as exc:
                    logger.warning("Chain-of-custody record not written: %s", exc)

    def _run(self):
        import traceback
        import types
        try:
            self.coordinator = ImageCollectionCoordinator(
                case_root=self.case_root, calculate_hashes=self.calculate_hashes,
                validate_artifacts=False, scan_only=False)

            def progress_callback(progress: ProgressUpdate):
                if self._cancelled:
                    self.coordinator.cancel()
                self.progress_update.emit(progress)
            self.coordinator.set_progress_callback(progress_callback)

            # Hook into the collector so each artifact shows up as it lands.
            collector = self.coordinator.artifact_collector
            original_process = getattr(collector, '_process_image_entry_by_path', None)
            if original_process:
                def hooked_process(accessor, entry_path, artifact_type):
                    result = original_process(accessor, entry_path, artifact_type)
                    if result:
                        self.artifact_found.emit(result)
                    return result
                collector._process_image_entry_by_path = types.MethodType(
                    lambda _s, a, e, t: hooked_process(a, e, t), collector)
            original_tree = getattr(collector, '_collect_preserved_tree', None)
            if original_tree:
                def hooked_tree(accessor, art_def, partition_num):
                    infos = original_tree(accessor, art_def, partition_num)
                    for info in infos or []:
                        self.artifact_found.emit(info)
                    return infos
                collector._collect_preserved_tree = types.MethodType(
                    lambda _s, a, d, p: hooked_tree(a, d, p), collector)

            self.progress_update.emit(ProgressUpdate("Opening the image...", 0, 0, 0, 0, 0, 0.0))
            summary = self.coordinator.collect_from_image(
                image_path=self.image_source,
                selected_partitions=self.selected_partitions,
                artifact_type_filter=self.artifact_type_filter,
                include_browser_cache=self.include_browser_cache)
            self.session_issues = self.coordinator.session_issues
            if self._cancelled:
                self._outcome = "cancelled"
                self.collection_cancelled.emit()
                return
            self._outcome = "completed"
            self.collection_complete.emit(summary)
        except InterruptedError:
            self._outcome = "cancelled"
            self.collection_cancelled.emit()
        except Exception as exc:
            if self.coordinator is not None:
                self.session_issues = self.coordinator.session_issues
            logger.error("Extraction failed: %s", exc, exc_info=True)
            self.collection_failed.emit(exc, traceback.format_exc())

    def cancel(self):
        self._cancelled = True
        if self.coordinator:
            self.coordinator.cancel()


# ============================================================================
# The window
# ============================================================================

class ImageParsingDialog(QMainWindow):
    """Forensic image -> case: pre-flight, extraction, parsing, one report."""

    def __init__(self, case_root: str, parent=None):
        super().__init__(parent)
        self.case_root = case_root
        self.crow_eye_main_window = None
        self.image_parser = ImageParser()
        self._reset_state()

        self.setWindowTitle("Forensic Image Parsing - Crow-Eye")
        try:
            self.setWindowIcon(_ip_icon("search"))
        except Exception:
            pass
        # The site look underneath ipRoot's own sheet (ui/site_theme.py), set
        # before the widgets exist so they are polished under it.
        try:
            from ui.site_theme import begin_site_theme
            begin_site_theme(self)
        except Exception:
            if STYLES_AVAILABLE:
                self.setStyleSheet(CrowEyeStyles.MAIN_WINDOW)
        self._build_ui()
        self._size_to_screen()
        self._set_phase("empty")
        # Header and tab fonts (capitals through QFont); every sheet is kept -
        # ipRoot's own sheet, the badges and the Issues cards carry meaning.
        try:
            from ui.site_theme import apply_site_theme
            apply_site_theme(self, clear_inline=False)
        except Exception:
            pass

    # ------------------------------------------------------------------ state
    def _reset_state(self):
        self.image_paths: List[str] = []
        self.image_path = None
        self.image_info = None
        self.preflight = None
        self.scan_issues = []          # from the scan (image + partitions)
        self.session_issues = []       # everything this run will report
        self.collection_failures = {}  # collector type -> [reason]
        self.extracted_ids: List[str] = []
        self.run_source = {}
        self.selected_partitions: List[int] = []
        self.collection_thread = None
        self.scan_worker = None
        self.parsing_worker = None
        self.all_results = []
        self._phase = "empty"          # empty / scanning / ready / blocked / running / done
        self._run_started = 0.0

    def set_case(self, case_root: str):
        """Called each time the window opens from Crow-Eye: a different case
        clears the previous case's image, results and issues."""
        if case_root == self.case_root:
            return
        if self._phase == "running":
            logger.warning("Case changed while an extraction is running; keeping %s", self.case_root)
            return
        self.case_root = case_root
        self._reset_state()
        self.image_path_display.setText("No image selected")
        self.image_path_display.setToolTip("")
        self.format_display.setText("")
        self.partition_list.clear()
        self.results_table.setRowCount(0)
        self.log_text_area.clear()
        self._set_issues([])
        self._set_badges({})
        self.case_label.setText(self._case_text())
        self.image_summary.setText("")
        self._refresh_actions()

    def _case_text(self):
        return "Case: %s" % (os.path.basename(os.path.normpath(self.case_root)) if self.case_root else "none open")

    # --------------------------------------------------------------- layout
    def _size_to_screen(self):
        """85% x 88% of the screen, never larger than it, never below 960x640.

        The old fixed setMinimumSize(1100, 800) overrode what the layouts
        needed and pushed the Start button off the bottom.
        """
        try:
            avail = QApplication.primaryScreen().availableGeometry()
            w = max(960, min(int(avail.width() * 0.85), avail.width()))
            h = max(640, min(int(avail.height() * 0.88), avail.height()))
            self.resize(min(w, avail.width()), min(h, avail.height()))
        except Exception:
            self.resize(1280, 800)
        self.setMinimumSize(960, 640)

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("ipRoot")
        root.setStyleSheet(_qss())
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(16, 14, 16, 10)
        body_lay.setSpacing(10)
        body_lay.addLayout(self._build_header())

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(6)
        split.setStyleSheet("QSplitter::handle { background: transparent; }")
        split.addWidget(self._build_setup_column())
        split.addWidget(self._build_run_column())
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 6)
        split.setSizes([420, 760])
        body_lay.addWidget(split, 1)
        outer.addWidget(body, 1)
        outer.addWidget(self._build_action_bar())

    def _build_header(self):
        row = QHBoxLayout()
        row.setSpacing(14)
        title = QLabel("Forensic Image Parsing")
        title.setObjectName("ipTitle")
        row.addWidget(title)
        self.case_label = QLabel(self._case_text())
        self.case_label.setObjectName("ipCase")
        row.addWidget(self.case_label)
        row.addStretch(1)
        self.image_summary = QLabel("")
        self.image_summary.setObjectName("ipImageSummary")
        row.addWidget(self.image_summary)
        return row

    def _card(self, number, title):
        card = QFrame()
        card.setObjectName("ipCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(10)
        num = QLabel(str(number))
        num.setObjectName("ipStepNum")
        num.setFixedSize(22, 22)
        num.setAlignment(Qt.AlignCenter)
        head.addWidget(num)
        t = QLabel(title)
        t.setObjectName("ipStepTitle")
        head.addWidget(t)
        head.addStretch(1)
        lay.addLayout(head)
        card.head = head
        return card, lay

    def _build_setup_column(self):
        scroll = QScrollArea()
        scroll.setObjectName("ipSetupScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("ipSetupHost")
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 0, 6, 0)
        col.setSpacing(12)

        # (1) Image
        card, lay = self._card(1, "Image")
        path_row = QHBoxLayout()
        self.image_path_display = QLabel("No image selected")
        self.image_path_display.setObjectName("ipPath")
        self.image_path_display.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        path_row.addWidget(self.image_path_display, 1)
        self.browse_image_button = _ip_pbtn("Browse", "folder")
        self.browse_image_button.setObjectName("ipSecondary")
        self.browse_image_button.clicked.connect(self._on_browse_image)
        path_row.addWidget(self.browse_image_button)
        lay.addLayout(path_row)
        self.format_display = QLabel("")
        self.format_display.setObjectName("ipMuted")
        self.format_display.setWordWrap(True)
        lay.addWidget(self.format_display)
        badges = QGridLayout()
        badges.setHorizontalSpacing(6)
        badges.setVerticalSpacing(6)
        self.badges = {}
        for i, key in enumerate(("readable", "segments", "filesystem", "windows", "encryption")):
            b = QLabel("")
            b.setObjectName("ipBadge")
            b.setVisible(False)
            self.badges[key] = b
            badges.addWidget(b, i // 3, i % 3)
        lay.addLayout(badges)
        col.addWidget(card)

        # (2) Partitions
        card, lay = self._card(2, "Partitions")
        self.check_all_btn = QPushButton("All")
        self.check_all_btn.setObjectName("ipSmall")
        self.check_all_btn.clicked.connect(self._on_check_all_partitions)
        self.uncheck_all_btn = QPushButton("None")
        self.uncheck_all_btn.setObjectName("ipSmall")
        self.uncheck_all_btn.clicked.connect(self._on_uncheck_all_partitions)
        card.head.addWidget(self.check_all_btn)
        card.head.addWidget(self.uncheck_all_btn)
        self.partition_list = QListWidget()
        self.partition_list.setObjectName("ipPartitions")
        self.partition_list.setMinimumHeight(80)
        self.partition_list.setMaximumHeight(130)
        self.partition_list.setWordWrap(True)
        self.partition_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.partition_list.itemChanged.connect(self._on_partition_toggled)
        self.partition_list.setToolTip("Choose the partition marked Windows - it holds the "
                                       "registry and most artifacts.")
        lay.addWidget(self.partition_list)
        col.addWidget(card)

        # (3) Extraction settings
        card, lay = self._card(3, "Extraction settings")
        type_row = QHBoxLayout()
        lbl = QLabel("Artifacts")
        lbl.setObjectName("ipMuted")
        type_row.addWidget(lbl)
        self.artifact_type_combo = QComboBox()
        self.artifact_type_combo.setObjectName("ipCombo")
        self.artifact_type_combo.addItems(list(_FILTER_MAP))
        type_row.addWidget(self.artifact_type_combo, 1)
        lay.addLayout(type_row)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        self.calculate_hashes_checkbox = _ip_cbox("Calculate hashes", "lock")
        self.include_browser_cache_checkbox = _ip_cbox("Include browser cache", "package")
        self.auto_parse_checkbox = _ip_cbox("Parse automatically after extraction", "bolt")
        for cb in (self.calculate_hashes_checkbox, self.include_browser_cache_checkbox,
                   self.auto_parse_checkbox):
            cb.setObjectName("ipOption")
            cb.setChecked(True)
        # Starts from Settings -> Parsing; still changeable for this run.
        try:
            from config.case_history_manager import auto_parse_after_collection
            self.auto_parse_checkbox.setChecked(auto_parse_after_collection())
        except Exception:
            pass
        self.include_browser_cache_checkbox.setToolTip(
            "Copy and parse browser caches (HTTP cache, Service Worker CacheStorage, Firefox cache2).\n"
            "Most of a browser profile's size on disk; history, cookies, downloads and the\n"
            "other browser tables are extracted either way.")
        self.auto_parse_checkbox.setToolTip(
            "Run the artifact parsers as soon as extraction finishes, then show the report.")
        grid.addWidget(self.calculate_hashes_checkbox, 0, 0)
        grid.addWidget(self.include_browser_cache_checkbox, 0, 1)
        grid.addWidget(self.auto_parse_checkbox, 1, 0, 1, 2)
        lay.addLayout(grid)
        col.addWidget(card)

        col.addStretch(1)
        scroll.setWidget(host)
        scroll.setMinimumWidth(360)
        return scroll

    def _build_run_column(self):
        col_w = QWidget()
        col = QVBoxLayout(col_w)
        col.setContentsMargins(6, 0, 0, 0)
        col.setSpacing(10)

        prog = QFrame()
        prog.setObjectName("ipProgress")
        pl = QVBoxLayout(prog)
        pl.setContentsMargins(14, 12, 14, 12)
        pl.setSpacing(8)
        self.operation_value = QLabel("Choose an image to begin.")
        self.operation_value.setObjectName("ipOperation")
        self.operation_value.setWordWrap(True)
        pl.addWidget(self.operation_value)
        self.progress_bar = (AnimatedProgressBar(accent="#60A5FA") if AnimatedProgressBar
                             else QProgressBar())
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setFixedHeight(20)
        self.progress_bar.setObjectName("ipBar")
        pl.addWidget(self.progress_bar)
        stats = QHBoxLayout()
        stats.setSpacing(18)

        def stat(label):
            box = QHBoxLayout()
            box.setSpacing(6)
            l = QLabel(label)
            l.setObjectName("ipStat")
            v = QLabel("0")
            v.setObjectName("ipStatValue")
            box.addWidget(l)
            box.addWidget(v)
            stats.addLayout(box)
            return v
        self.found_value = stat("Found")
        self.extracted_value = stat("Extracted")
        self.failed_value = stat("Failed")
        stats.addStretch(1)
        self.time_value = stat("Elapsed")
        self.time_value.setText("00:00:00")
        pl.addLayout(stats)
        col.addWidget(prog)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("ipTabs")

        # Artifacts
        art = QWidget()
        al = QVBoxLayout(art)
        al.setContentsMargins(10, 10, 10, 10)
        al.setSpacing(8)
        fr = QHBoxLayout()
        fl = QLabel("Show")
        fl.setObjectName("ipMuted")
        fr.addWidget(fl)
        self.results_type_filter = QComboBox()
        self.results_type_filter.setObjectName("ipCombo")
        self.results_type_filter.addItems([
            "All types", "Registry", "Prefetch", "link_jumplist", "MFT", "USN",
            "RecycleBin", "AmCache", "ShimCache", "EVTX", "SRUM", "Browser", "Failed only"])
        self.results_type_filter.currentTextChanged.connect(self._apply_results_filters)
        fr.addWidget(self.results_type_filter)
        fr.addStretch(1)
        al.addLayout(fr)
        self.results_table = QTableWidget(0, 5)
        self.results_table.setObjectName("ipResults")
        self.results_table.setHorizontalHeaderLabels(["Type", "Source path", "Status", "Size", "Hash"])
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setSortingEnabled(True)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.verticalHeader().setDefaultSectionSize(30)
        h = self.results_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.Interactive)
        self.results_table.setColumnWidth(4, 150)
        al.addWidget(self.results_table, 1)
        self.tabs.addTab(art, "Artifacts")

        # Log
        self.log_text_area = QTextEdit()
        self.log_text_area.setObjectName("ipLog")
        self.log_text_area.setReadOnly(True)
        self.tabs.addTab(self.log_text_area, "Log")

        # Issues
        iss = QWidget()
        il = QVBoxLayout(iss)
        il.setContentsMargins(10, 10, 10, 10)
        il.setSpacing(8)
        if IssuesPanel is not None:
            self.issues_panel = IssuesPanel([], iss)
            il.addWidget(self.issues_panel, 1)
        else:  # pragma: no cover
            self.issues_panel = None
            il.addWidget(QLabel("Issues are unavailable in this build."), 1)
        irow = QHBoxLayout()
        irow.addStretch(1)
        self.open_report_button = _ip_pbtn("Open Parse Status Report", "clipboard")
        self.open_report_button.setObjectName("ipSecondary")
        self.open_report_button.clicked.connect(self._open_latest_report)
        irow.addWidget(self.open_report_button)
        il.addLayout(irow)
        self.tabs.addTab(iss, "Issues")
        self._issues_tab_index = 2

        col.addWidget(self.tabs, 1)
        return col_w

    def _build_action_bar(self):
        bar = QFrame()
        bar.setObjectName("ipActionBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 10, 16, 12)
        lay.setSpacing(10)
        self.start_extraction_button = _ip_pbtn("Start analysis", "play")
        self.start_extraction_button.setObjectName("ipPrimary")
        self.start_extraction_button.clicked.connect(self._on_start_extraction)
        lay.addWidget(self.start_extraction_button)
        self.cancel_button = _ip_pbtn("Cancel", "stop")
        self.cancel_button.setObjectName("ipSecondary")
        self.cancel_button.clicked.connect(self._on_cancel)
        lay.addWidget(self.cancel_button)
        lay.addStretch(1)
        self.parse_artifacts_button = _ip_pbtn("Parse artifacts", "search")
        self.parse_artifacts_button.setObjectName("ipSecondary")
        self.parse_artifacts_button.clicked.connect(lambda: self._on_parse_artifacts(False))
        lay.addWidget(self.parse_artifacts_button)
        self.export_results_button = _ip_pbtn("Export results", "upload")
        self.export_results_button.setObjectName("ipSecondary")
        self.export_results_button.clicked.connect(self._on_export_results)
        lay.addWidget(self.export_results_button)
        self.close_button = _ip_pbtn("Close", "close")
        self.close_button.setObjectName("ipSecondary")
        self.close_button.clicked.connect(self.close)
        lay.addWidget(self.close_button)
        return bar

    # ---------------------------------------------------------- state machine
    def _refresh_actions(self):
        running = self._phase in ("scanning", "running")
        self.browse_image_button.setEnabled(not running)
        self.start_extraction_button.setEnabled(self._phase in ("ready", "done"))
        self.cancel_button.setEnabled(self._phase == "running")
        have = any(r.get('collection_status') in ("success", "skipped_duplicate")
                   for r in self.all_results)
        self.parse_artifacts_button.setEnabled(have and not running)
        self.export_results_button.setEnabled(bool(self.all_results) and not running)
        for w in (self.partition_list, self.artifact_type_combo, self.calculate_hashes_checkbox,
                  self.include_browser_cache_checkbox, self.auto_parse_checkbox,
                  self.check_all_btn, self.uncheck_all_btn):
            w.setEnabled(not running)

    def _set_phase(self, phase):
        self._phase = phase
        self._refresh_actions()
        # The sweep means "working": only while something runs.
        if hasattr(self.progress_bar, "setAnimated"):
            self.progress_bar.setAnimated(phase in ("scanning", "running"))

    # ---------------------------------------------------------------- badges
    def _set_badges(self, states):
        """states: key -> (state, text); keys not given are hidden."""
        for key, lbl in self.badges.items():
            if key not in states:
                lbl.setVisible(False)
                continue
            state, text = states[key]
            fg, bg = _BADGE.get(state, _BADGE["idle"])
            lbl.setText(text)
            lbl.setStyleSheet("QLabel#ipBadge { color: %s; border: 1px solid %s; background: %s; }"
                              % (fg, fg, bg))
            lbl.setVisible(True)

    def _badges_for_scan(self):
        codes = {i.code for i in self.scan_issues}
        st = {}
        pre = self.preflight
        if pre is None:
            return st
        if codes & {"not_an_image", "unsupported_image_format", "image_unreadable",
                    "image_corrupted", "image_locked", "dependency_missing"}:
            st["readable"] = ("bad", "Not readable")
        elif self.image_info:
            st["readable"] = ("ok", "Readable")
        if codes & {"missing_segments", "wrong_segment_selected"}:
            st["segments"] = ("bad", "Segments incomplete")
        elif len(pre.segments.segments) > 1:
            st["segments"] = ("ok", "%d segments present" % len(pre.segments.segments))
        facts = self._partition_facts(selected_only=False)
        if facts:
            fs = [f for f in facts if f.file_system not in ("Unknown", "UNKNOWN", "")]
            st["filesystem"] = (("ok", "File system: %s" % ", ".join(sorted({f.file_system for f in fs})))
                                if fs else ("warn", "No file system"))
            win = [f for f in facts if f.has_windows]
            if win:
                st["windows"] = ("ok", "Windows found")
            elif fs:
                st["windows"] = ("warn", "No Windows found")
            if any(f.encrypted for f in facts):
                st["encryption"] = ("warn", "BitLocker")
        return st

    # ---------------------------------------------------------------- issues
    def _set_issues(self, issues):
        issues = [i for i in issues if i is not None]
        if self.issues_panel is not None:
            self.issues_panel.set_issues(issues)
        n = len(issues)
        self.tabs.setTabText(self._issues_tab_index, "Issues (%d)" % n if n else "Issues")
        if any(i.severity == "error" for i in issues):
            self.tabs.tabBar().setTabTextColor(self._issues_tab_index, Qt.red)
        elif n:
            self.tabs.tabBar().setTabTextColor(self._issues_tab_index, Qt.yellow)
        else:
            self.tabs.tabBar().setTabTextColor(self._issues_tab_index, Qt.lightGray)

    def _partition_facts(self, selected_only=True):
        facts = []
        for i in range(self.partition_list.count()):
            item = self.partition_list.item(i)
            p = item.data(Qt.UserRole + 1)
            if p is None:
                continue
            sel = item.checkState() == Qt.Checked
            if selected_only and not sel:
                continue
            facts.append(PartitionFacts(
                label=item.data(Qt.UserRole + 2) or "Partition %s" % p.partition_number,
                file_system=p.file_system_type or "Unknown",
                boot_kind=getattr(p, "boot_kind", "unknown"),
                has_windows=getattr(p, "has_windows", None),
                verified=getattr(p, "verified", True),
                selected=sel))
        return facts

    def _live_issues(self):
        """Scan issues about the image + issues about the current selection."""
        image_level = [i for i in self.scan_issues
                       if i.code not in ("bitlocker_volume", "no_filesystem", "no_windows_partition",
                                         "no_partition_selected")]
        return image_level + partition_issues(self._partition_facts(selected_only=False))

    # ------------------------------------------------------------- handlers
    def _on_check_all_partitions(self):
        for i in range(self.partition_list.count()):
            self.partition_list.item(i).setCheckState(Qt.Checked)

    def _on_uncheck_all_partitions(self):
        for i in range(self.partition_list.count()):
            self.partition_list.item(i).setCheckState(Qt.Unchecked)

    def _on_partition_toggled(self, _item):
        if self._phase in ("ready", "done"):
            self._set_issues(self._live_issues())

    def _on_browse_image(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Select the forensic image (first segment)", "",
            "Forensic images (*.E01 *.e01 *.Ex01 *.E* *.vhdx *.vhd *.vmdk *.iso *.dd *.raw *.img "
            "*.001 *.bin);;All files (*.*)")
        if file_paths:
            self.load_image(sorted(file_paths))

    def load_image(self, file_paths: List[str]):
        """Scan an image: pre-flight, open probe, partitions (background)."""
        self.image_paths = list(file_paths)
        self.image_path = self.image_paths[0]
        self.image_info = None
        self.preflight = None
        self.scan_issues = []
        main_file = os.path.basename(self.image_paths[0])
        extra = " (+%d more)" % (len(self.image_paths) - 1) if len(self.image_paths) > 1 else ""
        self.image_path_display.setText(main_file + extra)
        self.image_path_display.setToolTip("\n".join(self.image_paths))
        self.format_display.setText("Checking the image...")
        self.partition_list.blockSignals(True)
        self.partition_list.clear()
        loading = QListWidgetItem("Reading partitions...")
        loading.setFlags(Qt.NoItemFlags)
        self.partition_list.addItem(loading)
        self.partition_list.blockSignals(False)
        self._set_badges({})
        self._set_issues([])
        self.image_summary.setText("")
        self.operation_value.setText("Checking %s..." % main_file)
        self._append_log("Image selected: %s" % "; ".join(self.image_paths), "INFO")
        self._set_phase("scanning")
        self.scan_worker = ScanWorker(self.image_parser, self.image_paths)
        self.scan_worker.scan_done.connect(self._on_scan_done)
        self.scan_worker.start()
        _mark_busy("Scanning the forensic image", self.scan_worker)

    def _on_scan_done(self, res):
        self.preflight = res.get("preflight")
        self.image_info = res.get("image_info")
        self.scan_issues = [i for i in res.get("issues", []) if i is not None]
        pre = self.preflight

        # Partitions
        self.partition_list.blockSignals(True)
        self.partition_list.clear()
        parts = list(getattr(self.image_info, "partitions", None) or [])
        for p in parts:
            label = self._partition_label(p)
            item = QListWidgetItem(self._partition_text(p, label))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            # Pre-select what is worth extracting: a Windows volume when there
            # is one, otherwise every partition with a file system.
            want = (p.has_windows is True) if any(x.has_windows for x in parts) else \
                p.file_system_type not in ("Unknown", "UNKNOWN", "")
            item.setCheckState(Qt.Checked if want or len(parts) == 1 else Qt.Unchecked)
            item.setData(Qt.UserRole, p.partition_number)
            item.setData(Qt.UserRole + 1, p)
            item.setData(Qt.UserRole + 2, label)
            try:
                if getattr(p, "boot_kind", "") == "BitLocker":
                    item.setIcon(_ip_icon("lock"))
                elif p.has_windows:
                    item.setIcon(_ip_icon("success"))
                elif p.file_system_type in ("Unknown", "UNKNOWN", ""):
                    item.setIcon(_ip_icon("warning"))
                else:
                    item.setIcon(_ip_icon("disk"))
            except Exception:
                pass
            self.partition_list.addItem(item)
        if not parts:
            empty = QListWidgetItem("No partitions - the image could not be read. See Issues.")
            empty.setFlags(Qt.NoItemFlags)
            self.partition_list.addItem(empty)
        self.partition_list.blockSignals(False)

        issues = self._live_issues()
        blocked = any(i.severity == "error" for i in self.scan_issues)
        if pre is not None:
            fmt = res.get("format") or pre.sniff.kind
            self.format_display.setText("%s - %s" % (pre.sniff.kind if fmt == "UNKNOWN" else fmt,
                                                     pre.sniff.detail or ""))
            self.image_summary.setText("%s  |  %s" % (os.path.basename(pre.segments.first or
                                                                         self.image_paths[0]),
                                                        pre.summary))
        self._set_badges(self._badges_for_scan())
        self._set_issues(issues)
        self.run_source = {
            "image": "%s  (%s)" % (os.path.basename(self.image_paths[0]),
                                   pre.summary if pre else "?"),
        }
        if blocked:
            self._set_phase("blocked")
            self.operation_value.setText("This image cannot be parsed - see Issues.")
            self.tabs.setCurrentIndex(self._issues_tab_index)
            self._append_log("Image cannot be parsed: %s" % "; ".join(
                i.title for i in self.scan_issues if i.severity == "error"), "ERROR")
            self._record_issues_only(self.scan_issues, show=False)
            self._explain("This image cannot be parsed",
                          [i for i in self.scan_issues if i.severity == "error"], error=True)
            return
        self._set_phase("ready")
        self.operation_value.setText("Ready. Check the partitions, then start the analysis.")
        if issues:
            self.tabs.setCurrentIndex(self._issues_tab_index)
        self._append_log("Format: %s; partitions: %d" % (self.format_display.text(), len(parts)),
                         "INFO")
        for p in parts:
            self._append_log("  %s" % self._partition_text(p, self._partition_label(p)), "INFO")

    @staticmethod
    def _partition_label(p):
        desc = (p.description or "").strip()
        if not desc or desc.lower() in ("unknown", "none"):
            desc = "Partition %s" % p.partition_number
        return desc

    @staticmethod
    def _partition_text(p, label):
        bits = [label, p.file_system_type if p.file_system_type not in ("UNKNOWN", "") else "Unknown",
                human_size(p.size_bytes)]
        if getattr(p, "boot_kind", "") == "BitLocker":
            bits.append("BitLocker-encrypted")
        if p.has_windows:
            bits.append("Windows")
        if not getattr(p, "verified", True):
            bits.append("unverified")
        return "  |  ".join(bits)

    def _on_start_extraction(self):
        self.selected_partitions = [self.partition_list.item(i).data(Qt.UserRole)
                                    for i in range(self.partition_list.count())
                                    if self.partition_list.item(i).checkState() == Qt.Checked
                                    and self.partition_list.item(i).data(Qt.UserRole) is not None]
        facts = self._partition_facts(selected_only=False)
        checks = check_case(self.case_root, self.image_paths) + partition_issues(facts)
        errors = [i for i in checks if i.severity == "error"]
        if errors:
            self._set_issues(self._live_issues() + [i for i in checks if i.code not in
                                                   {x.code for x in self._live_issues()}])
            self._explain("The analysis cannot start", errors, error=True)
            return
        warnings = [i for i in self._live_issues() + checks if i.severity == "warning"]
        seen, uniq = set(), []
        for w in warnings:
            key = (w.code, tuple(sorted(w.context.items())))
            if key not in seen:
                seen.add(key)
                uniq.append(w)
        if uniq and not self._explain("Continue with these warnings?", uniq, ask=True):
            return

        self.session_issues = [i for i in self.scan_issues if i.severity != "error"
                               and i.code not in ("bitlocker_volume", "no_filesystem",
                                                  "no_windows_partition")]
        self.session_issues += [i for i in uniq if i not in self.session_issues]
        self.collection_failures = {}
        self.extracted_ids = []
        self.run_source["partitions"] = ", ".join(f.label + " " + f.file_system
                                                  for f in facts if f.selected)

        self.results_table.setRowCount(0)
        self.all_results = []
        self.progress_bar.setValue(0)
        for v in (self.found_value, self.extracted_value, self.failed_value):
            v.setText("0")
        self.time_value.setText("00:00:00")
        self.operation_value.setText("Starting extraction...")
        self.tabs.setCurrentIndex(0)
        self._append_log("Extraction started - partitions: %s" % self.run_source["partitions"], "INFO")
        self._taskbar_begin("loading")
        self._run_started = time.time()

        self.collection_thread = CollectionWorker(
            case_root=self.case_root,
            image_source=self.image_paths,
            selected_partitions=self.selected_partitions,
            artifact_type_filter=_FILTER_MAP.get(self.artifact_type_combo.currentText()),
            calculate_hashes=self.calculate_hashes_checkbox.isChecked(),
            include_browser_cache=self.include_browser_cache_checkbox.isChecked())
        self.collection_thread.progress_update.connect(self._on_progress_update)
        self.collection_thread.artifact_found.connect(self._on_artifact_found)
        self.collection_thread.collection_complete.connect(self._on_collection_complete)
        self.collection_thread.collection_failed.connect(self._on_collection_failed)
        self.collection_thread.collection_cancelled.connect(self._on_collection_cancelled)
        self._set_phase("running")
        self.collection_thread.start()
        _mark_busy("Collecting artifacts from the forensic image", self.collection_thread)

    def _on_cancel(self):
        if self.collection_thread and self.collection_thread.isRunning():
            reply = QMessageBox.question(self, "Cancel extraction",
                                         "Stop extracting artifacts from this image?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self._append_log("Cancelling extraction...", "WARNING")
                self.collection_thread.cancel()
        elif getattr(self, "parsing_worker", None) is not None and self.parsing_worker.isRunning():
            # The automated parse used to be handed cancellation_check=lambda:
            # False, so Cancel reached nothing once extraction had finished.
            reply = QMessageBox.question(self, "Cancel parsing",
                                         "Stop parsing? The artifact being parsed finishes "
                                         "first; the rest are left unparsed.",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self._append_log("Cancelling parsing after the current artifact...", "WARNING")
                self._parse_cancelled = True

    # ------------------------------------------------------------- progress
    def _on_progress_update(self, progress: ProgressUpdate):
        if progress.total_count > 0:
            pct = int((progress.processed_count / progress.total_count) * 100)
            self.progress_bar.setValue(pct)
            self._taskbar("set_percent", pct)
        self.operation_value.setText(progress.current_file)
        self.found_value.setText(str(progress.artifacts_found))
        self.extracted_value.setText(str(progress.artifacts_collected))
        self.failed_value.setText(str(getattr(progress, "artifacts_failed", 0) or 0))
        e = progress.elapsed_time or (time.time() - self._run_started)
        self.time_value.setText("%02d:%02d:%02d" % (e // 3600, (e % 3600) // 60, e % 60))

    def _on_artifact_found(self, info: CollectedArtifactInfo):
        artifact = {
            'source_path': info.source_path, 'artifact_type': info.artifact_type,
            'collection_status': info.collection_status, 'file_size': info.file_size,
            'file_hash': info.file_hash, 'timestamp': info.timestamp,
            'error_message': getattr(info, "error_message", None),
        }
        self.all_results.append(artifact)
        if self._passes_filter(artifact):
            self._add_result_row(artifact)
        if info.collection_status == "failed":
            self._append_log("Not extracted: %s - %s" % (info.source_path, info.error_message), "WARNING")

    def _on_collection_complete(self, summary: CollectionSummary):
        self._taskbar_end()
        self.progress_bar.setValue(100)
        worker_issues = list(getattr(self.collection_thread, "session_issues", []) or [])

        # What was found but not copied, per artifact type, with the reason.
        failed = [a for a in (summary.artifacts or []) if a.collection_status == "failed"]
        for a in failed:
            self.collection_failures.setdefault(a.artifact_type, []).append(
                "%s: %s" % (os.path.basename(str(a.source_path).replace("image:", "")),
                            a.error_message or "unknown error"))
        issues = list(self.session_issues) + worker_issues
        if failed:
            names = ", ".join(os.path.basename(str(a.source_path).replace("image:", ""))
                              for a in failed[:8])
            issues.append(make_issue("artifacts_failed_to_extract",
                                     "%d artifact(s): %s%s" % (len(failed), names,
                                                               " ..." if len(failed) > 8 else "")))
        if summary.total_collected == 0:
            issues.append(make_issue("no_artifacts_extracted",
                                     "Found %d, extracted 0." % summary.total_found))
        self.session_issues = [i for i in issues if i is not None]
        self._set_issues(self.session_issues)

        self._index_extracted(summary)
        self.failed_value.setText(str(summary.failed))
        verdict = ("Extraction finished" if not failed else
                   "Extraction finished with %d failure(s)" % len(failed))
        if summary.total_collected == 0:
            verdict = "Nothing could be extracted"
        self._append_log("%s: found %d, extracted %d, failed %d, %.1f s" % (
            verdict, summary.total_found, summary.total_collected, summary.failed,
            summary.collection_time), "ERROR" if summary.total_collected == 0 else
            ("WARNING" if failed else "SUCCESS"))
        self.operation_value.setText(verdict + ".")
        self._set_phase("done")

        if summary.total_collected == 0:
            run_id = self._record_issues_only(self.session_issues, show=False)
            self._show_report(run_id)
            return
        if self.auto_parse_checkbox.isChecked():
            self._append_log("Parsing the extracted artifacts...", "INFO")
            self._on_parse_artifacts(automated=True)
        else:
            self._explain(verdict, [i for i in self.session_issues if i.severity != "info"],
                          info="Extracted %d of %d artifact(s). Click Parse artifacts to read them "
                               "into the case." % (summary.total_collected, summary.total_found))

    def _index_extracted(self, summary):
        """Add this run's artifacts to the case scan index (for parsing)."""
        if not summary.artifacts:
            return
        try:
            index = ArtifactScanIndex(self.case_root)
            image_key = os.path.abspath(self.image_paths[0]).lower() if self.image_paths else ""
            for info in summary.artifacts:
                if info.collection_status not in ("success", "skipped_duplicate"):
                    continue
                current = info.destination_path or info.source_path
                # The image is part of the id: the same path in two images of
                # one case used to overwrite the first image's entry.
                aid = hashlib.md5(("%s|%s" % (image_key, info.source_path)).encode()).hexdigest()[:16]
                index.add_artifact(ScannedArtifact(
                    artifact_id=aid, artifact_type=info.artifact_type,
                    original_path=info.source_path, current_path=current,
                    file_size=info.file_size, file_hash=info.file_hash,
                    scan_timestamp=info.timestamp.isoformat() if hasattr(info.timestamp, 'isoformat')
                    else str(info.timestamp),
                    collected=bool(info.destination_path), parsed=False))
                self.extracted_ids.append(aid)
            index.save()
            self._append_log("Added %d artifact(s) to the case index." % len(self.extracted_ids),
                             "INFO")
        except Exception as e:
            logger.error("Failed to update the artifact index: %s", e, exc_info=True)
            self._append_log("Failed to update artifact index: %s" % e, "ERROR")

    def _on_collection_failed(self, exc, tb):
        self._taskbar_end()
        self._append_log("Extraction failed: %s" % exc, "ERROR")
        self._append_log(tb, "DEBUG")
        image = os.path.basename(self.image_paths[0]) if self.image_paths else ""
        issue = issue_for_open_error(exc, image)
        if issue.code == "image_unreadable":
            issue = make_issue("extraction_failed", "%s: %s" % (type(exc).__name__, exc), image=image)
        worker_issues = list(getattr(self.collection_thread, "session_issues", []) or [])
        self.session_issues = list(self.session_issues) + worker_issues + [issue]
        self._set_issues(self.session_issues)
        self.operation_value.setText("Extraction failed - see Issues.")
        self._set_phase("done" if self.image_info else "blocked")
        run_id = self._record_issues_only(self.session_issues, show=False)
        self._show_report(run_id)

    def _on_collection_cancelled(self):
        self._taskbar_end()
        self._append_log("Extraction cancelled.", "WARNING")
        self.operation_value.setText("Extraction cancelled.")
        self._set_phase("done")
        QMessageBox.information(self, "Extraction cancelled",
                                "Extraction was cancelled. Anything already copied stays in the "
                                "case and can still be parsed.")

    # -------------------------------------------------------------- parsing
    def _configure_invoker(self, invoker):
        invoker.mode = 'image'
        invoker.include_browser_cache = self.include_browser_cache_checkbox.isChecked()
        invoker.session_issues = list(self.session_issues)
        invoker.collection_failures = dict(self.collection_failures)
        invoker.run_source = dict(self.run_source)
        chosen = _FILTER_MAP.get(self.artifact_type_combo.currentText())
        invoker.extraction_scope = [chosen] if chosen else None

    def _on_parse_artifacts(self, automated: bool = False):
        try:
            if not automated:
                self._append_log("Choose the artifacts to parse.", "INFO")
                dialog = ParseArtifactsDialog(self.case_root, self)
                dialog.source_mode = 'image'       # labels the parse-status record
                dialog.session_issues = list(self.session_issues)
                dialog.collection_failures = dict(self.collection_failures)
                dialog.run_source = dict(self.run_source)
                chosen = _FILTER_MAP.get(self.artifact_type_combo.currentText())
                dialog.extraction_scope = [chosen] if chosen else None
                dialog.artifacts_selected.connect(self._on_artifacts_parsing_started)
                if dialog.exec_() == QDialog.Accepted:
                    self._append_log("Parsing finished; databases written to Target_Artifacts/.",
                                     "SUCCESS")
                    main = self.crow_eye_main_window
                    if main is not None and hasattr(main, 'refresh_gui_tabs_after_parsing'):
                        try:
                            main.refresh_gui_tabs_after_parsing()
                        except Exception as e:
                            self._append_log("Refresh failed: %s" % e, "ERROR")
                else:
                    self._append_log("Parsing cancelled.", "WARNING")
                return

            index = ArtifactScanIndex(self.case_root)
            everything = index.get_all_artifacts()
            ids = set(self.extracted_ids)
            # This extraction only - the index also holds earlier imports and
            # other images, which used to be re-parsed on every run.
            to_parse = [a for a in everything if a.artifact_id in ids] or \
                [a for a in everything if not a.parsed]
            if not to_parse:
                self._append_log("Nothing to parse.", "WARNING")
                run_id = self._record_issues_only(self.session_issues +
                                                  [make_issue("no_artifacts_extracted")], show=False)
                self._show_report(run_id)
                return
            self._append_log("Parsing %d artifact file(s)..." % len(to_parse), "INFO")
            self.operation_value.setText("Parsing artifacts...")
            invoker = ParserInvoker(self.case_root)
            self._configure_invoker(invoker)
            self._parsing_ids = [a.artifact_id for a in to_parse]
            self._parse_cancelled = False
            self.parsing_worker = ParsingWorker(
                parser=invoker, artifacts=to_parse, progress_callback=None,
                cancellation_check=lambda: bool(getattr(self, "_parse_cancelled", False)),
                error_log_path=os.path.join(self.case_root, "parsing_errors.log"))
            self.parsing_worker.progress_update.connect(self._on_automated_progress_update,
                                                        Qt.QueuedConnection)
            self.parsing_worker.parsing_complete.connect(self._on_automated_parsing_complete,
                                                         Qt.QueuedConnection)
            self.parsing_worker.parsing_error.connect(self._on_automated_parsing_error,
                                                      Qt.QueuedConnection)
            self._set_phase("running")
            self.parsing_worker.start()
            _mark_busy("Parsing artifacts from the forensic image", self.parsing_worker)
        except Exception as e:
            logger.error("Failed to start parsing: %s", e, exc_info=True)
            self._append_log("Failed to start parsing: %s" % e, "ERROR")
            self._set_phase("done")
            QMessageBox.critical(self, "Parser error",
                                 "The parsers could not be started:\n\n%s\n\nSee the Log tab." % e)

    def _on_automated_progress_update(self, curr, tot, name, typ):
        self.operation_value.setText("Parsing %s: %s (%d/%d)" % (typ, os.path.basename(str(name)),
                                                                 curr, tot))
        self._taskbar_begin("parsing")
        self._taskbar("set_value", curr, tot)

    def _on_automated_parsing_error(self, err):
        # parse_artifacts_batch has already recorded the run (rows reached, the
        # rest NOT_RUN, a parsing_failed issue) - show it.
        self._taskbar_end()
        self._set_phase("done")
        self._append_log("Parsing stopped: %s" % err, "ERROR")
        self.operation_value.setText("Parsing stopped - see the report.")
        main = self.crow_eye_main_window
        if main is not None and hasattr(main, '_after_data_loaded'):
            main._after_data_loaded()
        else:
            self._show_report(None)

    def _on_automated_parsing_complete(self, results):
        self._taskbar_end()
        self._set_phase("done")
        try:
            index = ArtifactScanIndex(self.case_root)
            # Only what parsed: every id in the batch was marked, failures
            # included, so a failed artifact was never offered again.
            ok_ids = {getattr(r, "artifact_id", None) for r in results if r.success}
            if None in ok_ids or not any(getattr(r, "artifact_id", None) for r in results):
                ok_ids = set(getattr(self, "_parsing_ids", []))     # results without ids
            for aid in getattr(self, "_parsing_ids", []):
                if aid in ok_ids:
                    index.mark_as_parsed(aid)
            index.save()
        except Exception as e:
            logger.warning("Could not mark artifacts parsed: %s", e)
        parsed_types = sorted({r.artifact_type for r in results if r.success})
        self._append_log("Parsing finished: %d of %d file(s) parsed." % (
            sum(1 for r in results if r.success), len(results)), "SUCCESS")
        self.operation_value.setText("Done. Loading the results into Crow-Eye...")
        main = self.crow_eye_main_window
        if main is not None and parsed_types and hasattr(main, 'refresh_gui_tabs_after_parsing'):
            self._on_artifacts_parsing_started(parsed_types)
            try:
                main.refresh_gui_tabs_after_parsing(parsed_types)
            except Exception as e:
                self._append_log("Refresh failed: %s" % e, "ERROR")
        elif main is not None and hasattr(main, '_after_data_loaded'):
            main._after_data_loaded()        # nothing to load: the report still says why
        else:
            self._show_report(None)
        self.operation_value.setText("Done - see the Parse Status Report.")

    def _on_artifacts_parsing_started(self, artifact_types: List[str]):
        if artifact_types:
            self._append_log("Loading into Crow-Eye: %s" % ", ".join(artifact_types), "INFO")
            self.operation_value.setText("Loading the results into Crow-Eye...")
        else:
            self._append_log("No artifacts were parsed.", "WARNING")

    # --------------------------------------------------------------- report
    def _record_issues_only(self, issues, show=False):
        if record_outcomes is None or not self.case_root:
            return None
        try:
            return record_outcomes(self.case_root, [], "image", show=show, issues=issues,
                                   source=self.run_source or None)
        except Exception as e:
            logger.warning("Could not record the session issues: %s", e)
            return None

    def _show_report(self, run_id):
        if ParseStatusDialog is None or not self.case_root:
            return
        if run_id is None:
            # The run the parsers just recorded, taken so the main window does
            # not show it a second time.
            try:
                from utils.parse_status import ParseStatusStore
                run_id = ParseStatusStore(self.case_root).take_pending()
            except Exception:
                run_id = None
        try:
            ParseStatusDialog(self.case_root, run_id, self).exec_()
        except Exception as e:
            logger.warning("Could not open the report: %s", e)

    def _open_latest_report(self):
        """The case's most recent run, without touching the pending flag."""
        try:
            from utils.parse_status import ParseStatusStore
            last = ParseStatusStore(self.case_root).last_run() if self.case_root else None
        except Exception:
            last = None
        if ParseStatusDialog is not None and self.case_root:
            ParseStatusDialog(self.case_root, last.get("run_id") if last else None, self).exec_()

    def _explain(self, title, issues, error=False, ask=False, info=None):
        """A message box that names each problem and what to do about it."""
        lines = []
        if info:
            lines.append(info)
        for i in issues:
            lines.append("<p><b>%s</b><br>%s<br><i>What to do:</i> %s</p>" % (
                i.title, i.message, i.fix))
        if issues and not ask:
            lines.append("<p>These are also listed under <b>Issues</b> and in the Parse Status "
                         "Report.</p>")
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setTextFormat(Qt.RichText)
        box.setText("<h3>%s</h3>%s" % (title, "".join(
            l if l.startswith("<p>") else "<p>%s</p>" % l for l in lines)))
        box.setIcon(QMessageBox.Critical if error else QMessageBox.Warning if issues else
                    QMessageBox.Information)
        if ask:
            box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            box.button(QMessageBox.Yes).setText("Continue anyway")
            box.button(QMessageBox.No).setText("Go back")
            box.setDefaultButton(QMessageBox.No)
            return box.exec_() == QMessageBox.Yes
        box.exec_()
        return True

    # --------------------------------------------------------------- export
    def _on_export_results(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Export results", "",
                                                   "CSV files (*.csv);;All files (*.*)")
        if not file_path:
            return
        try:
            import csv
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(['Type', 'Source Path', 'Status', 'Size', 'Hash', 'Error'])
                for a in self.all_results:
                    w.writerow([a.get('artifact_type', ''), a.get('source_path', ''),
                                a.get('collection_status', ''), a.get('file_size', ''),
                                a.get('file_hash', ''), a.get('error_message') or ''])
            QMessageBox.information(self, "Export complete", "Results exported to:\n%s" % file_path)
        except Exception as e:
            QMessageBox.critical(self, "Export error", "Failed to export results:\n%s" % e)

    # ---------------------------------------------------------------- table
    def _passes_filter(self, artifact):
        f = self.results_type_filter.currentText()
        if f == "All types":
            return artifact.get('artifact_type') != "Unknown"
        if f == "Failed only":
            return artifact.get('collection_status') == "failed"
        return artifact.get('artifact_type') == f

    def _apply_results_filters(self):
        self.results_table.setRowCount(0)
        for a in self.all_results:
            if self._passes_filter(a):
                self._add_result_row(a)

    def _add_result_row(self, artifact: dict):
        try:
            self.results_table.setSortingEnabled(False)
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            self.results_table.setItem(row, 0, QTableWidgetItem(artifact.get('artifact_type', 'Unknown')))
            src = QTableWidgetItem(str(artifact.get('source_path', '')))
            src.setToolTip(str(artifact.get('source_path', '')))
            self.results_table.setItem(row, 1, src)
            ok = artifact.get('collection_status') in ("success", "skipped_duplicate")
            st = QTableWidgetItem("Extracted" if ok else "Not extracted")
            st.setForeground(Qt.green if ok else Qt.red)
            if not ok and artifact.get('error_message'):
                st.setToolTip(str(artifact['error_message']))
            self.results_table.setItem(row, 2, st)
            size = QTableWidgetItem(human_size(artifact.get('file_size', 0) or 0))
            size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.results_table.setItem(row, 3, size)
            hv = artifact.get('file_hash', '') or ''
            hi = QTableWidgetItem(hv[:16] + "..." if len(hv) > 16 else hv)
            hi.setToolTip(hv)
            self.results_table.setItem(row, 4, hi)
            self.results_table.setSortingEnabled(True)
        except Exception as e:
            logger.error("Failed to add a result row: %s", e)

    # -------------------------------------------------------------- helpers
    def _append_log(self, message: str, level: str = "INFO"):
        """The Log tab - and the case's image_parsing.log, so it outlives the window."""
        lvl = {"ERROR": logging.ERROR, "WARNING": logging.WARNING, "DEBUG": logging.DEBUG}.get(
            level, logging.INFO)
        logger.log(lvl, "%s", message)
        if level == "DEBUG":
            return
        color = {"ERROR": "#EF4444", "WARNING": "#F59E0B", "SUCCESS": "#10B981"}.get(
            level, Colors.TEXT_PRIMARY)
        import html as _html
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text_area.append('<span style="color: %s;">[%s] %s</span>' % (
            color, stamp, _html.escape(str(message))))

    def _taskbar(self, action, *args):
        """Drive the taskbar indicator. Never lets it affect the extraction."""
        try:
            from ui.taskbar_progress import taskbar
            getattr(taskbar(), action)(*args)
        except Exception:
            pass

    def _taskbar_begin(self, phase):
        if getattr(self, "_taskbar_open", False):
            self._taskbar("set_phase", phase)
            return
        self._taskbar_open = True
        self._taskbar("begin", phase)

    def _taskbar_end(self):
        if getattr(self, "_taskbar_open", False):
            self._taskbar_open = False
            self._taskbar("end")

    def closeEvent(self, event):
        """Closing mid-run must not leave the taskbar showing a percentage."""
        self._taskbar_end()
        super().closeEvent(event)


# ============================================================================
# Standalone entry point
# ============================================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    test_case_root = os.path.join(os.path.expanduser("~"), ".crow_eye", "test_case")
    os.makedirs(test_case_root, exist_ok=True)
    window = ImageParsingDialog(test_case_root)
    window.show()
    sys.exit(app.exec_())
