"""
Main Window
Primary container for all GUI components with tabbed navigation.
"""

import os
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QMenuBar, QMenu, QAction, QStatusBar, QFileDialog, QMessageBox,
    QDockWidget, QListWidget, QListWidgetItem, QLabel, QSplitter,
    QProgressDialog, QPushButton, QDialog
)
from PyQt5.QtCore import Qt, pyqtSignal, QSettings
from PyQt5.QtGui import QIcon, QKeySequence

from ..config import PipelineConfig
from ..integration.default_wings_loader import sync_and_augment_pipeline_wings
from .pipeline_builder import PipelineBuilderWidget
from .execution_control import ExecutionControlWidget
from .results_viewer import DynamicResultsTabWidget
from ..integration.auto_feather_generator import AutoFeatherGenerator
from ..integration.default_wings_loader import DefaultWingsLoader
from .crow_eye_icons import apply_status_to_label, engine_icon, CrowEyeIcons
from ui.app_theme import set_status, set_role, font as theme_font


from PyQt5.QtCore import QThread


class FeatherBuildWorker(QThread):
    """Builds the feathers off the GUI thread (AutoFeatherGenerator.generate_all_feathers).

    Every callback the generator makes - from its pool threads or this one - becomes a
    signal, so the tab is updated on the GUI thread. The registry is left to the GUI
    thread too (register=False): ConfigurationManager is a QObject."""
    started_one = pyqtSignal(str)
    finished_one = pyqtSignal(str, str, int, int, str)     # name, status, finished, total, detail
    uba_progress = pyqtSignal(int, str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, case_directory, only=None, parent=None):
        super().__init__(parent)
        self.case_directory = case_directory
        self.only = only
        self.cancelled = False

    def run(self):
        try:
            generator = AutoFeatherGenerator(self.case_directory)
            last = {}

            def finished(current, total, name, status):
                self.finished_one.emit(name, status, int(current), int(total), str(last.get(name, "")))

            results = generator.generate_all_feathers(
                progress_callback=finished,
                should_cancel=lambda: self.cancelled,
                started_callback=lambda name: self.started_one.emit(name),
                only=self.only, register=False,
                uba_progress=lambda pct, label: self.uba_progress.emit(int(pct), str(label)))
            self.done.emit(results)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit("%s: %s" % (type(e).__name__, e))


class PipelineManagerTab(QWidget):
    """Custom widget for Pipeline Manager tab with auto-generation trigger"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.feathers_generated = False
        self.case_directory = None
        self.main_window = None
        
        # Create layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Add info bar with manual generation button
        info_bar = QWidget()
        info_layout = QHBoxLayout(info_bar)
        info_layout.setContentsMargins(0, 0, 0, 10)
        
        info_label = QLabel("Tip: Feathers are auto-generated from Crow-Eye artifacts on first case load. This may take a few moments.")
        set_role(info_label, "muted")
        info_label.setWordWrap(True)
        # Stretch 1: the tip takes the free width. With a bare addStretch()
        # beside it, it wrapped into a three-line column at the left edge.
        info_layout.addWidget(info_label, 1)
        
        # Add status indicator
        self.feather_status_label = QLabel("Checking feathers...")
        self.feather_status_label.setFont(theme_font("ui", 12, 63))     # DemiBold
        set_status(self.feather_status_label, "warn")
        info_layout.addWidget(self.feather_status_label)
        self.feather_status_label.hide() # Hidden by default
        
        self.regenerate_btn = QPushButton("Regenerate Feathers")
        self.regenerate_btn.setIcon(CrowEyeIcons.feather())
        self.regenerate_btn.setToolTip("Manually regenerate all feathers from Crow-Eye artifacts")
        self.regenerate_btn.clicked.connect(self._manual_generate_feathers)
        self.regenerate_btn.setEnabled(False)
        info_layout.addWidget(self.regenerate_btn)
        
        self.update_wings_btn = QPushButton("Update Default Wings")
        self.update_wings_btn.setIcon(CrowEyeIcons.wing())
        self.update_wings_btn.setToolTip("Update default Wings with latest feather configurations (includes MFT_USN)")
        self.update_wings_btn.clicked.connect(self._update_default_wings)
        self.update_wings_btn.setEnabled(False)
        info_layout.addWidget(self.update_wings_btn)
        
        layout.addWidget(info_bar)
        
        # Add pipeline builder widget (will be set by main window)
        self.pipeline_builder = None
    
    def set_case_directory(self, case_directory: str):
        """Set the case directory for auto-generation"""
        self.case_directory = case_directory
        self.feathers_generated = False # Reset flag when case changes
        # Enable buttons when case directory is set
        self.regenerate_btn.setEnabled(True)
        self.update_wings_btn.setEnabled(True)
    
    def set_main_window(self, main_window):
        """Set reference to main window"""
        self.main_window = main_window
    
    def _update_default_wings(self):
        """Update default Wings with latest configurations"""
        try:
            from pathlib import Path
            
            if not self.case_directory:
                QMessageBox.warning(self, "No Case", "Please load a case first.")
                return
            
            correlation_dir = Path(self.case_directory) / "Correlation"
            
            # Confirm with user
            reply = QMessageBox.question(
                self,
                "Update Default Wings",
                "This will update the default Wings with the latest configurations.\n\n"
                "This includes:\n"
                "• MFT_USN feather support\n"
                "• System Logs feather support\n"
                "• Updated anchor priorities\n\n"
                "Your custom Wings will NOT be affected.\n\n"
                "Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            
            if reply != QMessageBox.Yes:
                return
            
            # Force update wings
            updated = DefaultWingsLoader.force_update_case_wings(correlation_dir)
            
            if updated:
                QMessageBox.information(
                    self,
                    "Wings Updated",
                    f"Successfully updated {len(updated)} default Wing(s):\n\n"
                    + "\n".join(f"• {p.name}" for p in updated) +
                    "\n\nPlease reload your pipeline to use the updated Wings."
                )
                
                # Refresh pipeline builder
                if self.pipeline_builder:
                    self.pipeline_builder.load_existing_configs()
            else:
                QMessageBox.information(
                    self,
                    "No Updates",
                    "Default Wings are already up to date."
                )
                
        except Exception as e:
            QMessageBox.critical(
                self,
                "Update Error",
                f"Failed to update Wings:\n\n{str(e)}"
            )
            import traceback
            traceback.print_exc()
    
    def showEvent(self, event):
        """Called when tab becomes visible - trigger auto-generation if needed"""
        super().showEvent(event)
        
        # Only auto-generate once per case and if case directory is set
        if not self.feathers_generated and self.case_directory:
            # Check if feathers need to be generated
            needs_generation, reason = self._check_feathers_status()
            
            if needs_generation:
                print(f"[Auto-Generation] {reason}")
                self._auto_generate_feathers()
            else:
                print("[Auto-Generation] Feathers are complete, skipping generation")
                self.feathers_generated = True
                # Still load existing configs
                if self.pipeline_builder:
                    self.pipeline_builder.load_existing_configs()
    
    def _check_feathers_status(self) -> tuple[bool, str]:
        """
        Check if feathers need to be generated.
        
        Returns:
            Tuple of (needs_generation: bool, reason: str)
        """
        try:
            from pathlib import Path
            from PyQt5.QtWidgets import QApplication
            
            # Show status label
            if hasattr(self, 'feather_status_label'):
                self.feather_status_label.show()
                self.feather_status_label.setText("Checking feathers...")
                set_status(self.feather_status_label, "warn")
                QApplication.processEvents()
            
            # Check if Correlation/feathers directory exists
            feathers_dir = Path(self.case_directory) / "Correlation" / "feathers"
            
            if not feathers_dir.exists():
                if hasattr(self, 'feather_status_label'):
                    apply_status_to_label(self.feather_status_label, "WARN", "Feathers not found")
                    set_status(self.feather_status_label, "bad")
                return (True, "Feathers directory does not exist")
            
            # Check if there are any .json feather config files
            json_files = list(feathers_dir.glob("*.json"))
            
            if len(json_files) == 0:
                if hasattr(self, 'feather_status_label'):
                    apply_status_to_label(self.feather_status_label, "WARN", "No feathers configured")
                    set_status(self.feather_status_label, "bad")
                return (True, "No feather configuration files found")
            
            # Get expected feather count from mappings
            from ..integration.feather_mappings import get_feather_mappings
            expected_mappings = get_feather_mappings()
            expected_count = len(expected_mappings)
            
            # Check if we have all expected feathers
            if len(json_files) < expected_count:
                if hasattr(self, 'feather_status_label'):
                    apply_status_to_label(self.feather_status_label, "WARN", f"Missing feathers ({len(json_files)}/{expected_count})")
                    set_status(self.feather_status_label, "warn")
                return (True, f"Missing feathers: found {len(json_files)}, expected {expected_count}")
            
            # Check if corresponding .db files exist for each .json config
            missing_dbs = []
            for json_file in json_files:
                db_file = json_file.with_suffix('.db')
                if not db_file.exists():
                    missing_dbs.append(json_file.stem)
            
            if missing_dbs:
                if hasattr(self, 'feather_status_label'):
                    apply_status_to_label(self.feather_status_label, "WARN", f"Generating databases... ({len(missing_dbs)} remaining)")
                    set_status(self.feather_status_label, "warn")
                return (True, f"Missing database files for: {', '.join(missing_dbs[:3])}")

            # A feather built from an older parse: counting files said "ready"
            # after a re-parse, and the engines read the old rows.
            from ..integration.auto_feather_generator import stale_feathers
            stale = stale_feathers(feathers_dir)
            if stale:
                if hasattr(self, 'feather_status_label'):
                    apply_status_to_label(self.feather_status_label, "WARN",
                                          f"Updating feathers ({len(stale)} out of date)")
                    set_status(self.feather_status_label, "warn")
                return (True, f"{len(stale)} feather(s) older than their source: {', '.join(stale[:3])}")

            # All checks passed
            if hasattr(self, 'feather_status_label'):
                apply_status_to_label(self.feather_status_label, "OK", "Feathers ready")
                set_status(self.feather_status_label, "ok")
            return (False, "All feathers present and complete")
            
        except Exception as e:
            print(f"[Auto-Generation] Error checking feather status: {e}")
            if hasattr(self, 'feather_status_label'):
                apply_status_to_label(self.feather_status_label, "ERROR", "Error checking feathers")
                set_status(self.feather_status_label, "bad")
            # If we can't check, assume we need to generate
            return (True, f"Error checking status: {e}")
    
    # ------------------------------------------------------------------ feather building
    # Feathers are built on FeatherBuildWorker, a QThread: Crow-Eye stays usable while they
    # build. Until 2026-11-01 the build ran inside showEvent, the GUI thread waiting in a loop
    # that pumped processEvents, then SHA-256-hashed ~330 MB of feathers with no pump at all.
    def _auto_generate_feathers(self):
        """Build what is missing or stale, in the background (the tab opened)."""
        from pathlib import Path
        from ..integration.auto_feather_generator import feathers_to_build
        target_artifacts = Path(self.case_directory) / "Target_Artifacts"
        live_acquisition = Path(self.case_directory) / "live_acquisition"
        if not target_artifacts.exists() and not live_acquisition.exists():
            print("[Auto-Generation] Neither Target_Artifacts nor live_acquisition found")
            apply_status_to_label(self.feather_status_label, "WARN", "No artifact directories found")
            set_status(self.feather_status_label, "bad")
            return
        try:
            needed = feathers_to_build(Path(self.case_directory) / "Correlation" / "feathers")
        except Exception as e:
            print(f"[Auto-Generation] Could not list the feathers to build ({e}); building all")
            needed = None
        self._start_feather_build(needed, auto=True)

    def _manual_generate_feathers(self):
        """Regenerate every feather (the button), after a confirmation."""
        from pathlib import Path
        from PyQt5.QtWidgets import QMessageBox
        if not self.case_directory:
            QMessageBox.warning(self, "No Case Directory", "Case directory is not set. Please load a case first.")
            return
        target_artifacts = Path(self.case_directory) / "Target_Artifacts"
        live_acquisition = Path(self.case_directory) / "live_acquisition"
        db_files = []
        for d in (target_artifacts, live_acquisition):
            if d.exists():
                db_files.extend(d.glob("*.db"))
        if not db_files:
            QMessageBox.warning(
                self, "No Database Files",
                "No parsed artifact databases were found in:\n - %s\n - %s\n\n"
                "Parse the case first (Parse all Artifacts, or the offline parsers)." % (target_artifacts, live_acquisition))
            return
        feathers_dir = Path(self.case_directory) / "Correlation" / "feathers"
        feathers_dir.mkdir(parents=True, exist_ok=True)
        reply = QMessageBox.question(
            self, "Regenerate Feathers",
            "Rebuild every Feather from the %d parsed databases?\n\nOutput: %s\n\n"
            "It runs in the background; Crow-Eye stays usable." % (len(db_files), feathers_dir),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply == QMessageBox.Yes:
            self._start_feather_build(None, auto=False)

    def _start_feather_build(self, only, auto):
        """Start the worker for `only` (feather names) or every feather; returns at once."""
        from ..integration.feather_mappings import get_feather_mappings
        if getattr(self, "_feather_worker", None) is not None and self._feather_worker.isRunning():
            return
        names = [m['name'] for m in get_feather_mappings()]
        if only is not None:
            names = [n for n in names if n in set(only)]
        if not names:
            self.feathers_generated = True
            apply_status_to_label(self.feather_status_label, "OK", "Feathers ready")
            set_status(self.feather_status_label, "ok")
            if self.pipeline_builder:
                self.pipeline_builder.load_existing_configs()
            return
        self._ensure_feather_panel()
        # The explanation is the panel's tooltip, not a subtitle line: in the
        # short panel that line cost a Feather row.
        self._fb_panel.restart("Building %d Feather%s" % (len(names), "" if len(names) == 1 else "s"),
                               "", [self._fb_label(n) for n in names])
        self._fb_panel.setToolTip("Built from the case's parsed databases, four at a time. "
                                  "Crow-Eye stays usable while they build.")
        self._fb_panel.bar.setRange(0, len(names))
        self._fb_panel.bar.setValue(0)
        self._fb_result.setText("")
        self._fb_stop.setText("Stop")
        self._fb_stop.setEnabled(True)
        self._fb_box.show()
        self.regenerate_btn.setEnabled(False)
        self.feather_status_label.show()
        apply_status_to_label(self.feather_status_label, "INFO", "Building feathers...")
        set_status(self.feather_status_label, "info")

        worker = FeatherBuildWorker(self.case_directory, only, self)
        worker.started_one.connect(self._on_feather_started)
        worker.finished_one.connect(self._on_feather_finished)
        worker.uba_progress.connect(self._on_uba_progress)
        worker.done.connect(lambda results: self._on_feathers_done(results, auto))
        worker.failed.connect(self._on_feathers_failed)
        self._feather_worker = worker
        worker.start()

    @staticmethod
    def _fb_label(name):
        return name.replace("_CrowEyeFeather", "").replace("_", " ")

    def _ensure_feather_panel(self):
        if getattr(self, "_fb_box", None) is not None:
            return
        from PyQt5.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QHBoxLayout, QPushButton
        from ui.loading_panel import LoadingPanel
        box = QFrame()
        box.setObjectName("featherBuildBox")
        # The list on the left, Stop and the outcome on its right: a row of its
        # own under the list made the panel one button taller.
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 8)
        self._fb_panel = LoadingPanel("Building Feathers", "", [], compact=True)
        # Tight margins here only (the shared panel keeps its own elsewhere):
        # the space goes to the Feather rows, not to padding.
        self._fb_panel.layout().setContentsMargins(8, 4, 8, 4)
        scroll = QScrollArea()
        scroll.setWidget(self._fb_panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # About three rows under the title and bar (Ghassan, 2026-11-02: the
        # panel was too tall above the pipeline; it took 220-320 px). The row
        # being built is kept in view (_on_feather_started), so the list scrolls
        # by itself.
        scroll.setMinimumHeight(120)
        scroll.setMaximumHeight(150)
        lay.addWidget(scroll, 1)
        self._fb_scroll = scroll
        side = QVBoxLayout()
        self._fb_stop = QPushButton("Stop")
        self._fb_stop.setToolTip("Stop: the feathers already building finish, the rest are left as they were")
        self._fb_stop.clicked.connect(self._feather_stop_or_hide)
        side.addWidget(self._fb_stop, 0, Qt.AlignRight)
        self._fb_result = QLabel("")
        self._fb_result.setWordWrap(True)
        self._fb_result.setFixedWidth(280)
        self._fb_result.setAlignment(Qt.AlignRight | Qt.AlignTop)
        side.addWidget(self._fb_result)
        side.addStretch(1)
        lay.addLayout(side)
        try:
            from ui.app_theme import set_variant
            set_variant(self._fb_stop, "ghost")
        except Exception:
            pass
        self.layout().insertWidget(1, box)
        self._fb_box = box

    def _fb_row(self, name):
        label = self._fb_label(name)
        return next((r for r in self._fb_panel._rows if r.name == label), None)

    def _feather_stop_or_hide(self):
        worker = getattr(self, "_feather_worker", None)
        if worker is not None and worker.isRunning():
            worker.cancelled = True
            self._fb_stop.setEnabled(False)
            self._fb_stop.setText("Stopping...")
        else:
            self._fb_box.hide()

    def _on_feather_started(self, name):
        row = self._fb_row(name)
        if row is not None:
            row.set_state("running", "%s - building" % self._fb_label(name))
            scroll = getattr(self, "_fb_scroll", None)
            if scroll is not None:
                scroll.ensureWidgetVisible(row, 0, 8)

    def _on_uba_progress(self, percent, label):
        row = next((r for r in self._fb_panel._rows if r.state == "running" and "Behaviour" in r.name), None)
        if row is not None:
            row.text.setText("%s - user behaviour analysis %d%%: %s" % (row.name, percent, label))

    def _on_feather_finished(self, name, status, current, total, detail):
        row = self._fb_row(name)
        if row is not None:
            if row.state == "waiting":
                row.set_state("running")
            if status == "success":
                row.set_state("done")
            elif status == "skipped":
                row.set_state("done", "no source in this case")
            else:
                row.set_state("failed", detail[:160])
        self._fb_panel.bar.setRange(0, max(1, total))
        self._fb_panel.bar.setValue(current)

    def _on_feathers_done(self, results, auto):
        self._feather_worker = None
        self.regenerate_btn.setEnabled(True)
        # The registry on the GUI thread (ConfigurationManager is a QObject).
        try:
            from config.configuration_manager import ConfigurationManager
            if results.get('registrations'):
                ConfigurationManager.get_instance().add_feathers(results['registrations'])
        except Exception as e:
            print(f"[Feathers] Registry not updated: {e}")
        self.feathers_generated = True
        ok, total = results['success_count'], results['total']
        failed = [(n, e) for n, e in results['failed'] if not str(e).startswith("Source database not found")]
        skipped = len(results['failed']) - len(failed)
        for name, err in failed:
            row = self._fb_row(name)
            if row is not None:
                row.set_state("failed", str(err)[:160])
        self._fb_panel.bar.setRange(0, max(1, total))
        self._fb_panel.bar.setValue(total)
        took = sum((results.get('seconds') or {}).values())
        parts = ["%d of %d Feather%s built" % (ok, total, "" if total == 1 else "s")]
        if skipped:
            parts.append("%d with no source in this case" % skipped)
        if failed:
            parts.append("%d failed: %s" % (len(failed), ", ".join(self._fb_label(n) for n, _e in failed[:4])))
        if results.get('cancelled'):
            parts.append("stopped before the end")
        self._fb_result.setText("; ".join(parts) + ".")
        good = not failed and not results.get('cancelled')
        set_status(self._fb_result, "ok" if good else "warn")
        apply_status_to_label(self.feather_status_label, "OK" if good else "WARN",
                              "Feathers ready" if good else "Feathers built with problems")
        set_status(self.feather_status_label, "ok" if good else "warn")
        self._fb_stop.setEnabled(True)
        self._fb_stop.setText("Hide")
        if self.pipeline_builder:
            self.pipeline_builder.load_existing_configs()
        print(f"[Feathers] {'; '.join(parts)} ({took:.0f} s of build time)")

    def _on_feathers_failed(self, message):
        self._feather_worker = None
        self.regenerate_btn.setEnabled(True)
        self._fb_panel.fail(message)
        self._fb_result.setText("The feather build stopped: %s" % message)
        set_status(self._fb_result, "warn")
        apply_status_to_label(self.feather_status_label, "ERROR", "Feather build failed")
        set_status(self.feather_status_label, "bad")
        self._fb_stop.setEnabled(True)
        self._fb_stop.setText("Hide")


def _engine_sheet_extra(engine_extra):
    """The engine's own rules plus 3 px outlines on cards, fields, buttons,
    tables, tabs and outlined labels (ui/app_theme.thick_outlines)."""
    from ui.app_theme import thick_outlines
    return engine_extra() + chr(10) + thick_outlines("QMainWindow#CorrelationEngine")


class MainWindow(QMainWindow):
    """Main application window with tabbed interface"""

    # Which tab is which. Eight places decide what the analyst is looking at
    # by writing a bare integer; named, the decision can be read.
    TAB_PIPELINE_MANAGER = 0
    TAB_EXECUTION = 1
    TAB_RESULTS = 2

    pipeline_loaded = pyqtSignal(PipelineConfig)
    
    def __init__(self):
        super().__init__()
        
        # Application state
        self.current_pipeline: Optional[PipelineConfig] = None
        self.current_pipeline_path: Optional[str] = None
        self.is_modified = False
        self.default_directory = None # Will be set by correlation integration
        
        # Settings
        self.settings = QSettings("Crow-Eye", "CorrelationEngine")
        
        # Initialize UI
        self._init_ui()
        self._load_settings()
    
    def set_default_directory(self, directory: str):
        """
        Set the default directory for saving/loading files.
        This should be the case's Correlation directory.
        
        Args:
            directory: Path to Correlation directory
        """
        self.default_directory = directory
        print(f"[Main Window] Default directory set to: {directory}")
        
        # Extract case directory (parent of Correlation directory)
        from pathlib import Path
        case_directory = str(Path(directory).parent)
        
        # Set case directory in Pipeline Manager tab for auto-generation
        self.pipeline_manager_tab.set_case_directory(case_directory)
        print(f"[Main Window] Case directory set for auto-generation: {case_directory}")
        
        # Set case directory in Pipeline Builder for case-based naming
        self.pipeline_builder.set_case_directory(case_directory)
        print(f"[Main Window] Case directory set in Pipeline Builder: {case_directory}")

        # The Execution tab hands it to engines that read the case itself.
        self.execution_control.case_directory = case_directory
        
        # Set default output directory to case's results directory
        results_dir = str(Path(directory) / "results")
        self.pipeline_builder.output_dir_input.setText(results_dir)
        print(f"[Main Window] Output directory set to: {results_dir}")
        
        # Initialize default wings for the case
        try:
            from pathlib import Path
            correlation_dir = Path(directory)
            copied_wings = DefaultWingsLoader.initialize_case_wings_directory(correlation_dir)
            if copied_wings:
                print(f"[Main Window] Initialized {len(copied_wings)} default Wings")
            else:
                print("[Main Window] Default Wings already exist in case directory")
        except Exception as e:
            print(f"[Main Window] Error initializing default Wings: {e}")

        # Load default Wings into the pipeline builder
        try:
            from PyQt5.QtCore import Qt
            default_wings = DefaultWingsLoader.load_all_default_wings()
            added_count = 0
            # Precompute existing wing ids once (was O(n*m): a full list scan per
            # default wing) and dedupe within the defaults too.
            existing_ids = set()
            for i in range(self.pipeline_builder.wings_list.count()):
                existing = self.pipeline_builder.wings_list.item(i).data(Qt.UserRole)
                wid = getattr(existing, 'wing_id', None) if existing else None
                if wid:
                    existing_ids.add(wid)
            for wing_config in default_wings:
                if wing_config.wing_id in existing_ids:
                    continue
                self.pipeline_builder._add_wing_to_list(wing_config)
                existing_ids.add(wing_config.wing_id)
                added_count += 1
            if added_count:
                print(f"[Main Window] Loaded {added_count} default Wings into pipeline")
        except Exception as e:
            print(f"[Main Window] Error loading default Wings into pipeline: {e}")
        
        # Auto-load session if available
        self._load_session_state()
        
    @staticmethod
    def _scrolling(page):
        from PyQt5.QtWidgets import QFrame, QScrollArea
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        area.setWidget(page)
        return area

    def _init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("Correlation Engine")
        # What a 1280 x 720 screen leaves after the taskbar; the tabs scroll.
        self.setMinimumSize(1100, 640)
        
        # This used to be setWindowIcon(QIcon()) - deliberately blank, "to match
        # clean Crow-Eye aesthetic". That predated this window having a taskbar
        # button; a blank icon in the taskbar reads as a broken app rather than
        # a clean one, and there is nowhere else the icon shows.
        try:
            from styles import CrowEyeStyles as _CES
            _icon = _CES.crow_eye_icon()
            if _icon is not None:
                self.setWindowIcon(_icon)
        except Exception:
            pass
        
        # Load and apply Crow-Eye styles
        self._load_styles()
        
        # Create central widget with tab widget
        central_widget = QWidget()
        # The theme paints a window's ground only on QDialog or #siteWindow:
        # without it the tab bar sat on Qt's light grey.
        central_widget.setObjectName("siteWindow")
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tab_widget)
        
        # Create tabs - use custom PipelineManagerTab
        self.pipeline_manager_tab = PipelineManagerTab()
        self.pipeline_manager_tab.set_main_window(self)
        self.execution_tab = QWidget()
        self.results_tab = QWidget()
        
        # The two form tabs need about 1050 px of height. In a window smaller
        # than that their layouts squeezed every list and form row to nothing
        # (the Wings list, Wing selection, the pipeline metadata); in a scroll
        # area they keep their size and the page scrolls instead. Results
        # fills the window with its own tables and scrolls itself.
        # Numbered in the order an investigator works through them: build the
        # pipeline, run it, read what it found (Ghassan, 2026-11-02). The User
        # Guide's Correlation Engine section uses the same numbers.
        self.tab_widget.addTab(self._scrolling(self.pipeline_manager_tab), "1  Pipeline Manager")
        self.tab_widget.addTab(self._scrolling(self.execution_tab), "2  Execution")
        self.tab_widget.addTab(self.results_tab, "3  Results")
        for _i, _tip in enumerate((
                "Step 1: choose the engine, the Feathers and the Wings, and save the pipeline",
                "Step 2: pick the Wings to run, add filters, and run the pipeline",
                "Step 3: every run's Summary and matches, down to the original rows")):
            self.tab_widget.setTabToolTip(_i, _tip)
        
        # Initialize Pipeline Manager tab with builder
        pipeline_manager_layout = self.pipeline_manager_tab.layout()
        
        # Add pipeline builder widget
        self.pipeline_builder = PipelineBuilderWidget()
        self.pipeline_builder.pipeline_modified.connect(self._on_pipeline_modified)
        pipeline_manager_layout.addWidget(self.pipeline_builder, 1)
        
        # Set pipeline builder reference in tab
        self.pipeline_manager_tab.pipeline_builder = self.pipeline_builder
        
        # Initialize Execution tab with execution control
        execution_layout = QVBoxLayout(self.execution_tab)
        execution_layout.setContentsMargins(10, 10, 10, 10)
        
        # Add execution control widget
        self.execution_control = ExecutionControlWidget()
        self.execution_control.execution_completed.connect(self._on_execution_completed)
        self.execution_control.wing_completed.connect(self._on_wing_completed) # NEW: Connect wing_completed signal
        self.execution_control.load_results_requested.connect(self._on_load_results_requested)
        self.execution_control.open_wing_in_creator_requested.connect(self._open_wing_in_creator)
        self.execution_control.augment_wings_for_engine = self._augment_wings_for_engine
        execution_layout.addWidget(self.execution_control)
        
        # Initialize Results tab with results viewer
        results_layout = QVBoxLayout(self.results_tab)
        results_layout.setContentsMargins(10, 10, 10, 10)
        
        # Add results viewer widget
        self.results_viewer = DynamicResultsTabWidget()
        results_layout.addWidget(self.results_viewer)
        
        # Create menu bar
        self._create_menu_bar()
        
        # Create status bar
        self._create_status_bar()

        # The site look (ui/app_theme.py): the per-widget sheets the tabs set
        # while they were built become roles; the window keeps ONE sheet.
        self._apply_theme()

    def _apply_theme(self, root=None):
        """One sheet for the engine window, or re-theme a page built later
        (results tabs are rebuilt on every run and load)."""
        try:
            from ui.app_theme import apply_theme
            from correlation_engine.gui.ui_styling import engine_extra
            apply_theme(self, root=root, extra=_engine_sheet_extra(engine_extra))
        except Exception as e:
            print(f"[Correlation Engine] site look not applied: {e}")

    def _load_styles(self):
        """The site look, set BEFORE the children exist (ui/app_theme.py).

        It used to load crow_eye_styles.qss here, and the integration set it a
        second time after the window was built - a replaced sheet leaves the
        children in the old fonts. One source now: the theme sheet plus the
        engine's own rules (ui_styling.engine_extra)."""
        try:
            from ui.app_theme import begin_theme
            from correlation_engine.gui.ui_styling import engine_extra
            self.setObjectName("CorrelationEngine")     # scopes the 3 px outlines
            begin_theme(self, extra=_engine_sheet_extra(engine_extra))
        except Exception as e:
            print(f"[Correlation Engine] Error loading styles: {e}")

    def _create_menu_bar(self):
        """Create the menu bar"""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        new_action = QAction("&New Pipeline", self)
        new_action.setShortcut(QKeySequence.New)
        new_action.triggered.connect(self._new_pipeline)
        file_menu.addAction(new_action)
        
        open_action = QAction("&Open Pipeline...", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self._open_pipeline)
        file_menu.addAction(open_action)
        
        save_action = QAction("&Save Pipeline", self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self._save_pipeline)
        file_menu.addAction(save_action)
        
        save_as_action = QAction("Save Pipeline &As...", self)
        save_as_action.setShortcut(QKeySequence.SaveAs)
        save_as_action.triggered.connect(self._save_pipeline_as)
        file_menu.addAction(save_as_action)
        
        file_menu.addSeparator()
        
        load_session_action = QAction("Load &Session...", self)
        load_session_action.triggered.connect(self._load_session)
        file_menu.addAction(load_session_action)
        
        save_session_action = QAction("Save S&ession...", self)
        save_session_action.triggered.connect(self._save_session)
        file_menu.addAction(save_session_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Edit menu
        edit_menu = menubar.addMenu("&Edit")
        
        preferences_action = QAction("&Preferences...", self)
        preferences_action.triggered.connect(self._show_preferences)
        edit_menu.addAction(preferences_action)
        
        # View menu
        view_menu = menubar.addMenu("&View")
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
        
    def _create_status_bar(self):
        """Create the status bar"""
        self.status_bar = QStatusBar()
        # Outside #siteWindow, so it keeps its own ground (the theme has none for it).
        self.status_bar.setProperty("keepStyle", True)
        self.status_bar.setStyleSheet("QStatusBar { background: #0B0F1A; color: #94A3B8; "
                                      "border-top: 1px solid #1E293B; }")
        self.setStatusBar(self.status_bar)

        # Add permanent widgets
        self.status_label = QLabel("Ready")
        self.status_bar.addWidget(self.status_label)
        
    def _create_recent_pipelines_sidebar(self):
        """Create collapsible recent pipelines sidebar"""
        self.recent_dock = QDockWidget("Recent Pipelines", self)
        self.recent_dock.setObjectName("RecentPipelinesDock")
        self.recent_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        
        # Create list widget
        self.recent_list = QListWidget()
        self.recent_list.itemDoubleClicked.connect(self._open_recent_pipeline_item)

        self.recent_dock.setWidget(self.recent_list)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.recent_dock)

    def _open_recent_pipeline_item(self, item):
        """Open a pipeline from the Recent Pipelines list via double-click.
        Path is stored on the item (UserRole) or falls back to item text."""
        filepath = item.data(Qt.UserRole) or item.text()
        if filepath and os.path.exists(str(filepath)):
            self.load_pipeline(str(filepath))

    def load_pipeline(self, filepath: str) -> bool:
        """
        Load pipeline configuration from file.
        
        Args:
            filepath: Path to pipeline JSON file
            
        Returns:
            True if loaded successfully, False otherwise
        """
        try:
            # Check if file exists
            if not os.path.exists(filepath):
                self.show_notification(f"File not found: {filepath}", "error")
                return False

            # Load pipeline config
            self.current_pipeline = PipelineConfig.load_from_file(filepath)
            self.current_pipeline_path = filepath
            self.is_modified = False

            # Sync newly-shipped default Wings into the case folder and append
            # any case Wings (defaults + user-created) missing from the JSON.
            # default_directory IS the case's Correlation directory.
            if self.default_directory:
                sync_and_augment_pipeline_wings(
                    self.current_pipeline, Path(self.default_directory)
                )
            
            # Update window title
            self._update_window_title()
            
            # Load into pipeline builder
            self.pipeline_builder.load_pipeline(self.current_pipeline)
            
            # Load into execution control
            self.execution_control.display_pipeline_overview(self.current_pipeline)
            
            # Emit signal
            self.pipeline_loaded.emit(self.current_pipeline)
            
            # Switch to execution tab
            self.tab_widget.setCurrentIndex(self.TAB_EXECUTION)
            
            self.show_notification(f"Loaded pipeline: {self.current_pipeline.pipeline_name}", "success")
            return True
            
        except Exception as e:
            self.show_notification(f"Failed to load pipeline: {str(e)}", "error")
            QMessageBox.critical(self, "Load Error", f"Failed to load pipeline:\n{str(e)}")
            return False
    
    def save_pipeline(self, filepath: str) -> bool:
        """
        Save current pipeline configuration to file.
        
        Args:
            filepath: Path to save pipeline JSON file
            
        Returns:
            True if saved successfully, False otherwise
        """
        try:
            # Get pipeline from builder
            self.current_pipeline = self.pipeline_builder.get_pipeline_config()
            
            if self.current_pipeline is None:
                self.show_notification("No pipeline to save", "warning")
                return False
            
            # Validate before saving
            is_valid, errors = self.pipeline_builder.validate_pipeline()
            if not is_valid:
                QMessageBox.warning(
                    self,
                    "Validation Error",
                    "Cannot save invalid pipeline:\n" + "\n".join(errors)
                )
                return False
            
            # Update last modified date
            self.current_pipeline.last_modified = datetime.now().isoformat()
            
            # Save to file
            self.current_pipeline.save_to_file(filepath)
            
            self.current_pipeline_path = filepath
            self.is_modified = False
            
            # Update window title
            self._update_window_title()
            
            self.show_notification(f"Saved pipeline: {filepath}", "success")
            return True
            
        except Exception as e:
            self.show_notification(f"Failed to save pipeline: {str(e)}", "error")
            QMessageBox.critical(self, "Save Error", f"Failed to save pipeline:\n{str(e)}")
            return False
    
    def show_notification(self, message: str, level: str = "info"):
        """
        Display notification in status bar.
        
        Args:
            message: Notification message
            level: Notification level (info, success, warning, error)
        """
        # The level is the label's status colour (the site's meaning colours)
        kinds = {"info": "info", "success": "ok", "warning": "warn", "error": "bad"}
        set_status(self.status_label, kinds.get(level, "info"))
        self.status_label.setText(message)
        
        # Show in status bar for 5 seconds
        self.status_bar.showMessage(message, 5000)
    
    def _update_window_title(self):
        """Update window title with current pipeline name"""
        title = "Correlation Engine"
        
        if self.current_pipeline:
            title += f" - {self.current_pipeline.pipeline_name}"
            if self.is_modified:
                title += " *"
        
        self.setWindowTitle(title)
    
    def _new_pipeline(self):
        """Create new pipeline"""
        # Check for unsaved changes
        if not self._check_unsaved_changes():
            return
        
        # Clear current pipeline
        self.current_pipeline = None
        self.current_pipeline_path = None
        self.is_modified = False
        
        # Clear pipeline builder
        self.pipeline_builder.clear()
        
        # Switch to pipeline manager tab
        self.tab_widget.setCurrentIndex(self.TAB_PIPELINE_MANAGER)
        
        self.show_notification("Ready to create new pipeline", "info")
    
    def _open_pipeline(self):
        """Open pipeline file dialog"""
        # Check for unsaved changes
        if not self._check_unsaved_changes():
            return
        
        # Determine default directory
        from pathlib import Path
        
        # Try to use case-specific pipelines directory first
        default_dir = None
        if hasattr(self, 'default_directory') and self.default_directory:
            # Use case's Correlation/pipelines directory
            default_dir = Path(self.default_directory) / "pipelines"
            default_dir.mkdir(parents=True, exist_ok=True)
        else:
            # Fallback to demo_configs
            default_dir = Path("demo_configs/pipelines")
            default_dir.mkdir(parents=True, exist_ok=True)
        
        # Show file dialog
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Open Pipeline",
            str(default_dir),
            "Pipeline Files (*.json);;All Files (*)"
        )
        
        if filepath:
            if self.load_pipeline(filepath):
                # Save session state
                self._save_session_state()
    
    def _save_pipeline(self):
        """Save current pipeline"""
        if self.current_pipeline_path:
            if self.save_pipeline(self.current_pipeline_path):
                # Save session state
                self._save_session_state()
        else:
            self._save_pipeline_as()
    
    def _save_pipeline_as(self):
        """Save pipeline with new name"""
        # Get pipeline from builder
        pipeline = self.pipeline_builder.get_pipeline_config()
        
        if pipeline is None:
            self.show_notification("No pipeline to save", "warning")
            return
        
        # Validate before saving
        is_valid, errors = self.pipeline_builder.validate_pipeline()
        if not is_valid:
            QMessageBox.warning(
                self,
                "Validation Error",
                "Cannot save invalid pipeline:\n" + "\n".join(errors)
            )
            return
        
        # Determine default directory
        from pathlib import Path
        
        # Try to use case-specific pipelines directory first
        default_dir = None
        if hasattr(self, 'default_directory') and self.default_directory:
            # Use case's Correlation/pipelines directory
            default_dir = Path(self.default_directory) / "pipelines"
            default_dir.mkdir(parents=True, exist_ok=True)
        else:
            # Fallback to demo_configs
            default_dir = Path("demo_configs/pipelines")
            default_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate default filename from pipeline name
        default_filename = pipeline.config_name + ".json" if pipeline.config_name else "pipeline.json"
        default_path = default_dir / default_filename
        
        # Show file dialog
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Save Pipeline As",
            str(default_path),
            "Pipeline Files (*.json);;All Files (*)"
        )
        
        if filepath:
            # Ensure .json extension
            if not filepath.endswith('.json'):
                filepath += '.json'
            
            if self.save_pipeline(filepath):
                # Save session state
                self._save_session_state()
    
    def _load_session(self):
        """Load analysis session"""
        if not hasattr(self, 'default_directory') or not self.default_directory:
            self.show_notification("No case directory set", "warning")
            return
        
        from pathlib import Path
        session_file = Path(self.default_directory) / "session.json"
        
        if not session_file.exists():
            self.show_notification("No saved session found", "info")
            return
        
        try:
            with open(session_file, 'r') as f:
                session_data = json.load(f)
            
            # Load last pipeline if available
            last_pipeline = session_data.get('last_pipeline')
            if last_pipeline and os.path.exists(last_pipeline):
                self.load_pipeline(last_pipeline)
                
                # Restore tab
                last_tab = session_data.get('last_tab', 0)
                self.tab_widget.setCurrentIndex(last_tab)
                
                self.show_notification("Session restored", "success")
            else:
                self.show_notification("Session pipeline not found", "warning")
                
        except Exception as e:
            self.show_notification(f"Failed to load session: {str(e)}", "error")
    
    def _save_session(self):
        """Save analysis session"""
        if not hasattr(self, 'default_directory') or not self.default_directory:
            self.show_notification("No case directory set", "warning")
            return
        
        self._save_session_state()
        self.show_notification("Session saved", "success")
    
    def _save_session_state(self):
        """Save current session state to session.json"""
        if not hasattr(self, 'default_directory') or not self.default_directory:
            return
        
        from pathlib import Path
        session_file = Path(self.default_directory) / "session.json"
        
        try:
            session_data = {
                'last_pipeline': self.current_pipeline_path,
                'last_tab': self.tab_widget.currentIndex(),
                'last_modified': datetime.now().isoformat()
            }
            
            with open(session_file, 'w') as f:
                json.dump(session_data, f, indent=2)
                
        except Exception as e:
            print(f"[Main Window] Failed to save session: {e}")
    
    def _on_tab_changed(self, index: int):
        """
        Handle tab change event.
        
        When switching to Execution tab, check if a pipeline is loaded.
        If not, try to auto-load default pipeline or show selection dialog.
        
        Args:
            index: Index of the newly selected tab
        """
        # Check if switching to Execution tab (index 1)
        if index == 1:
            # If no pipeline is currently loaded, try to load default
            if not self.current_pipeline:
                self._load_default_pipeline_or_prompt()
    
    def _load_default_pipeline_or_prompt(self):
        """
        Load default pipeline if set, otherwise show pipeline selection dialog.
        """
        if not hasattr(self, 'default_directory') or not self.default_directory:
            print("[Main Window] No case directory set, cannot load default pipeline")
            return
        
        from pathlib import Path
        
        # Check for case config with default pipeline
        case_dir = Path(self.default_directory).parent
        config_file = case_dir / "Correlation" / "case_config.json"
        
        default_pipeline_name = None
        auto_load_enabled = True
        
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    case_config = json.load(f)
                
                default_pipeline_name = case_config.get('default_pipeline')
                correlation_settings = case_config.get('correlation_settings', {})
                auto_load_enabled = correlation_settings.get('auto_load_default_pipeline', True)
                
            except Exception as e:
                print(f"[Main Window] Error reading case config: {e}")
        
        # If default pipeline is set and auto-load is enabled, load it
        if default_pipeline_name and auto_load_enabled:
            pipelines_dir = Path(self.default_directory) / "pipelines"
            pipeline_file = pipelines_dir / f"{default_pipeline_name}.json"
            
            if pipeline_file.exists():
                print(f"[Main Window] Auto-loading default pipeline: {default_pipeline_name}")
                if self.load_pipeline(str(pipeline_file)):
                    self.show_notification(f"Loaded default pipeline: {default_pipeline_name}", "success")
                    return
                else:
                    print(f"[Main Window] Failed to load default pipeline: {default_pipeline_name}")
            else:
                print(f"[Main Window] Default pipeline file not found: {pipeline_file}")
        
        # No default pipeline or auto-load failed, show selection dialog
        self._show_pipeline_selection_dialog()
    
    def _show_pipeline_selection_dialog(self):
        """Show pipeline selection dialog."""
        if not hasattr(self, 'default_directory') or not self.default_directory:
            QMessageBox.warning(
                self,
                "No Case Directory",
                "No case directory is set. Please load a case first."
            )
            return
        
        from pathlib import Path
        from .pipeline_selection_dialog import PipelineSelectionDialog
        
        case_dir = Path(self.default_directory).parent
        
        # Show selection dialog
        dialog = PipelineSelectionDialog(str(case_dir), self)
        
        if dialog.exec_() == QDialog.Accepted:
            selected_path = dialog.get_selected_pipeline_path()
            if selected_path:
                if self.load_pipeline(selected_path):
                    self.show_notification(f"Loaded pipeline", "success")
                else:
                    QMessageBox.warning(
                        self,
                        "Load Failed",
                        "Failed to load the selected pipeline."
                    )
        else:
            # User cancelled, switch back to Pipeline Manager tab
            self.tab_widget.setCurrentIndex(self.TAB_PIPELINE_MANAGER)
            self.show_notification("No pipeline selected", "info")
    
    def _load_session_state(self):
        """Load session state on startup"""
        if not hasattr(self, 'default_directory') or not self.default_directory:
            return
        
        from pathlib import Path
        session_file = Path(self.default_directory) / "session.json"
        
        if not session_file.exists():
            return
        
        try:
            with open(session_file, 'r') as f:
                session_data = json.load(f)
            
            # Auto-load last pipeline
            last_pipeline = session_data.get('last_pipeline')
            if last_pipeline and os.path.exists(last_pipeline):
                self.load_pipeline(last_pipeline)

                # Open on Pipeline Manager, whatever the last session ended on.
                #
                # This used to apply `last_tab` from session.json, and before
                # that `load_pipeline` had already jumped to Execution - so the
                # window opened wherever the previous session happened to stop,
                # which for anyone who had just run a correlation was the
                # Results tab. This must stay AFTER load_pipeline(), which sets
                # the tab itself. `last_tab` is still written to session.json
                # and still honoured by the explicit Load Session action.
                self.tab_widget.setCurrentIndex(self.TAB_PIPELINE_MANAGER)

                print(f"[Main Window] Restored session: {last_pipeline}")
                
        except Exception as e:
            print(f"[Main Window] Failed to load session state: {e}")
    
    def _show_preferences(self):
        """Show preferences dialog"""
        # TODO: Implement preferences dialog
        self.show_notification("Preferences not yet implemented", "info")
    
    def _show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            "About Correlation Engine",
            "Correlation Engine GUI v1.0\n\n"
            "A forensic analysis tool for correlating artifacts across time.\n\n"
            "Part of the Crow-Eye forensic toolkit."
        )
    
    def _check_unsaved_changes(self) -> bool:
        """
        Check for unsaved changes and prompt user.
        
        Returns:
            True if OK to proceed, False if cancelled
        """
        if self.is_modified and self.current_pipeline:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                f"Pipeline '{self.current_pipeline.pipeline_name}' has unsaved changes.\n"
                "Do you want to save before continuing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel
            )
            
            if reply == QMessageBox.Save:
                self._save_pipeline()
                return True
            elif reply == QMessageBox.Discard:
                return True
            else:
                return False
        
        return True
    
    def _autosave_on_close(self):
        """Auto-save the pipeline, session state and geometry.

        This was the body of a SECOND `closeEvent` defined earlier in the class
        than the real one. Python keeps the last definition, so none of it ever
        ran - the pipeline was not auto-saved, the session state was not
        written, and the docstring saying otherwise had been wrong for as long
        as both definitions existed. It is a plain method now, called from the
        one closeEvent, so there is no way for it to be shadowed again.
        """
        try:
            # Get current pipeline from builder
            pipeline = self.pipeline_builder.get_pipeline_config()

            if pipeline and self.pipeline_builder.name_input.text().strip():
                # Auto-save pipeline if it has a name
                from pathlib import Path
                
                # Determine save location
                if hasattr(self, 'default_directory') and self.default_directory:
                    pipelines_dir = Path(self.default_directory) / "pipelines"
                    pipelines_dir.mkdir(parents=True, exist_ok=True)
                else:
                    pipelines_dir = Path("demo_configs/pipelines")
                    pipelines_dir.mkdir(parents=True, exist_ok=True)
                
                # Generate filename from pipeline name
                pipeline_name = pipeline.config_name or "pipeline"
                pipeline_file = pipelines_dir / f"{pipeline_name}.json"
                
                # Save pipeline
                try:
                    self.save_pipeline(str(pipeline_file))
                    # save_pipeline clears is_modified on success, which is what
                    # stops closeEvent prompting for changes it has just saved.
                    print(f"[Main Window] Auto-saved pipeline on close: {pipeline_file}")
                except Exception as e:
                    print(f"[Main Window] Failed to auto-save pipeline: {e}")

            # Save session state
            self._save_session_state()

            # Save window geometry
            self.settings.setValue("geometry", self.saveGeometry())

            print("[Main Window] Closed with auto-save")

        except Exception as e:
            print(f"[Main Window] Error during auto-save on close: {e}")


    def _load_settings(self):
        """Load application settings"""
        # Restore window geometry
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        
        # Restore window state
        state = self.settings.value("windowState")
        if state:
            self.restoreState(state)
    
    def _save_settings(self):
        """Save application settings"""
        # Save window geometry
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
    
    def _on_pipeline_modified(self):
        """Handle pipeline modification"""
        self.is_modified = True
        self._update_window_title()
    
    def _on_wing_completed(self, wing_summary: dict) -> None:
        """
        Note a wing finishing. Builds nothing.

        This used to call `create_wing_result_tab` immediately, which for
        identity wings rebuilt the unified viewer from the database — every
        match of every wing so far, re-read and re-parsed on the UI thread —
        after each wing, while the next wing was already running. Results are
        now built once, when the run finishes, in `_on_execution_completed`.

        Args:
            wing_summary: the per-wing summary emitted by the execution worker
        """
        wing_name = wing_summary.get('wing_name', 'Unknown Wing')
        wing_index = wing_summary.get('wing_index', 0)
        total_wings = wing_summary.get('total_wings', 0)
        matches = wing_summary.get('total_matches', 0)
        print(f"[MainWindow] Wing completed: {wing_name} "
              f"({wing_index}/{total_wings}, {matches} matches) — "
              f"results are built when the run finishes")

        # A new run starts at wing 1 (the worker always numbers from 1), so that
        # is where the accumulator resets — a previous run's wings must not be
        # rebuilt into this one's tabs.
        if wing_index == 1 or not hasattr(self, '_run_wing_summaries'):
            self._run_wing_summaries = []
        self._run_wing_summaries.append(wing_summary)

    def _on_execution_completed(self, summary: dict):
        """
        Handle execution completion - all wings finished.

        Requirements: 4.5, 5.1, 6.1, 6.3

        Builds every result tab for the run in one pass, then updates the
        Summary tab with aggregate statistics across ALL wings.
        """
        print(f"[MainWindow] All wings completed")

        # Build the run's tabs once. Prefer the worker's own list; fall back to
        # what wing_completed collected if a caller emitted only the aggregate.
        wing_summaries = summary.get('wing_summaries') or \
            getattr(self, '_run_wing_summaries', [])
        if summary.get('cancelled') and wing_summaries:
            # A stopped run's wing summaries carry no results (the executor's
            # cancelled summary has none), so the Summary would have no
            # statistics. Read the wings back from the database, where the
            # engine saved their statistics before it stopped.
            wing_summaries = self._stopped_wings_from_database(wing_summaries)
            summary = dict(summary, wing_summaries=wing_summaries,
                           total_wings_executed=len(wing_summaries),
                           total_matches_all_wings=sum(w.get('total_matches', 0) or 0
                                                       for w in wing_summaries),
                           execution_times=[w.get('execution_time', 0) for w in wing_summaries])
        if wing_summaries:
            # With progress: this is the moment the run ends and the results
            # start loading, and a run's worth of matches takes long enough
            # that a silent window reads as a hang.
            self.results_viewer.create_run_result_tabs(wing_summaries,
                                                       show_progress=True)
        self._run_wing_summaries = []

        # Update Summary tab with aggregate statistics
        self.results_viewer.update_summary_tab(summary)

        # Switch to Results tab (index 2)
        self.tab_widget.setCurrentIndex(self.TAB_RESULTS)

        # Switch to Summary tab within Results (index 0)
        self.results_viewer.enhanced_tab_widget.tab_widget.setCurrentIndex(0)
    
    def _stopped_wings_from_database(self, wing_summaries):
        """Each stopped wing as the results database holds it (statistics,
        counts, the stored cancel), marked cancelled; a wing it cannot read
        back is kept as it came."""
        out = []
        for ws in wing_summaries:
            db, eid = ws.get('database_path'), ws.get('execution_id')
            detected = []
            if db and eid:
                try:
                    detected = self.results_viewer._detect_wings_from_execution(db, eid)
                except Exception as e:
                    print(f"[MainWindow] Could not read stopped wing back: {e}")
            for d in detected:
                d['cancelled'] = True
                d.setdefault('run_group_id', ws.get('run_group_id'))
            out.extend(detected or [ws])
        return out

    def _augment_wings_for_engine(self, pipeline_config, engine_type):
        """Offer the case Wings the newly selected engine runs (Execution tab)."""
        if self.default_directory:
            sync_and_augment_pipeline_wings(
                pipeline_config, Path(self.default_directory), engine_type=engine_type)

    def _case_wing_file(self, wing_config):
        """The case's own file for a Wing (Correlation/wings), if it has one."""
        if not self.default_directory:
            return None
        wings_dir = Path(self.default_directory) / "wings"
        if not wings_dir.is_dir():
            return None
        import json as _json
        for path in sorted(wings_dir.glob("*.json")):
            try:
                with open(path, encoding="utf-8") as handle:
                    if _json.load(handle).get("wing_id") == getattr(wing_config, "wing_id", None):
                        return path
            except Exception:
                continue
        return None

    def _open_wing_in_creator(self, wing_config):
        """Open a Wing in the Wing Creator, which asks for its category first.

        Saved, the Wing replaces its old copy in the loaded pipeline and the
        Execution tab's list is drawn again, so a Wing that had no category
        moves out of "Needs a category" without reloading the pipeline.
        """
        try:
            from ..gui.execution_control import _crow_eye_busy
            busy = _crow_eye_busy()
        except Exception:
            busy = None
        if busy:
            QMessageBox.information(
                self, "Crow-Eye is still working",
                "Crow-Eye is still working: %s.\n\nOpen the Wing once it has finished." % busy)
            return
        try:
            from ..wings.ui.main_window import WingsCreatorWindow
            from ..wings.core.wing_model import Wing
            window = WingsCreatorWindow()
            if self.default_directory:
                window.set_case_directory(str(Path(self.default_directory).parent))
            source = self._case_wing_file(wing_config)
            window.source_path = str(source) if source else None
            window.wing = Wing.from_dict(wing_config.to_dict())
            window.wing_saved.connect(self._on_creator_wing_saved)
            window.show()
            window.load_wing_to_ui()
            self._wing_creator_windows = [w for w in getattr(self, '_wing_creator_windows', [])
                                          if w is not None]
            self._wing_creator_windows.append(window)
            window.destroyed.connect(lambda *_a, w=window: self._wing_creator_windows.remove(w)
                                     if w in self._wing_creator_windows else None)
        except Exception as e:
            QMessageBox.critical(self, "Wing Creator", f"Could not open the Wing:\n{e}")

    def _on_creator_wing_saved(self, path):
        """Put a Wing saved in the Wing Creator back into the loaded pipeline."""
        if not self.current_pipeline or not path:
            return
        try:
            from ..config import WingConfig
            saved = WingConfig.load_from_file(str(path))
        except Exception as e:
            self.show_notification(f"Saved Wing could not be read back: {e}", "error")
            return
        wings = self.current_pipeline.wing_configs
        for index, existing in enumerate(wings):
            if getattr(existing, 'wing_id', None) == saved.wing_id:
                wings[index] = saved
                break
        else:
            wings.append(saved)
        self.execution_control._populate_wing_list(keep_checked=True)

    def _on_load_results_requested(self, request_data: dict):
        """
        Handle request to load results from database with loading dialog.
        
        Updated to use selected_executions from DatabaseResultsLoaderDialog.
        Creates proper tab structure with Summary tab and individual wing tabs.
        
        Requirements: 9.1, 9.3, 9.4
        """
        from PyQt5.QtWidgets import QProgressDialog, QApplication, QMessageBox
        from PyQt5.QtCore import Qt
        
        output_dir = request_data.get('output_dir', '')
        selected_executions = request_data.get('selected_executions', [])

        if not output_dir:
            QMessageBox.warning(self, "No Output Directory", "Please specify an output directory.")
            return

        # Loading while this window's own run is still going shows that run
        # half-written. Say so; it still loads what is saved.
        worker = getattr(getattr(self, 'execution_control', None), 'worker_thread', None)
        try:
            running = worker is not None and worker.isRunning()
        except RuntimeError:
            running = False
        if running:
            QMessageBox.information(
                self, "Correlation Still Running",
                "A correlation is still running in this window - its results open by "
                "themselves when it finishes.\n\nThe latest run's saved results will load "
                "now, marked as not finished.")

        if not selected_executions:
            # Fallback to load_last_results if no specific executions selected
            print("[MainWindow] No specific executions selected, loading most recent")
            
            # Create and show loading dialog
            progress = QProgressDialog("Loading last correlation results...", "Cancel", 0, 100, self)
            progress.setWindowTitle("Loading Results")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setAutoClose(True)
            progress.setAutoReset(True)
            
            # Apply Crow Eye styling
            from .ui_styling import CorrelationEngineStyles
            CorrelationEngineStyles.apply_progress_dialog_style(progress)
            
            # Define progress callback
            def update_progress(message: str, percent: int):
                """Update progress dialog with message and percentage."""
                progress.setLabelText(message)
                progress.setValue(percent)
                QApplication.processEvents()
                
                if progress.wasCanceled():
                    raise InterruptedError("Loading cancelled by user")
            
            try:
                self.results_viewer.load_last_results(output_dir, progress_callback=update_progress)
                
                # Switch to Results tab
                self.tab_widget.setCurrentIndex(self.TAB_RESULTS)
                
                # Switch to Summary tab within Results (index 0)
                self.results_viewer.enhanced_tab_widget.tab_widget.setCurrentIndex(0)
                
            except InterruptedError:
                progress.close()
                print("[MainWindow] Loading cancelled by user")
            except Exception as e:
                progress.close()
                QMessageBox.critical(self, "Error Loading Results", f"Failed to load results:\n\n{str(e)}")
                import traceback
                traceback.print_exc()
            
            return
        
        # Load specific selected executions
        print(f"[MainWindow] Loading {len(selected_executions)} selected execution(s)")
        
        # Create and show loading dialog
        progress = QProgressDialog(f"Loading {len(selected_executions)} execution(s)...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Loading Results")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(True)
        progress.setAutoReset(True)
        
        # Apply Crow Eye styling
        from .ui_styling import CorrelationEngineStyles
        CorrelationEngineStyles.apply_progress_dialog_style(progress)
        
        try:
            # Don't clear existing tabs - add new tabs for selected executions
            tab_widget = self.results_viewer.enhanced_tab_widget.tab_widget
            
            # Process each selected execution
            for idx, (db_path, execution_id, engine_type) in enumerate(selected_executions):
                if progress.wasCanceled():
                    raise InterruptedError("Loading cancelled by user")
                
                progress_percent = int((idx / len(selected_executions)) * 90)
                progress.setLabelText(f"Loading execution {idx + 1}/{len(selected_executions)}: {execution_id}")
                progress.setValue(progress_percent)
                QApplication.processEvents()
                
                print(f"[MainWindow] Loading execution {execution_id} from {db_path}")
                
                # Detect wings from this execution
                wing_summaries = self.results_viewer._detect_wings_from_execution(db_path, execution_id)
                
                if not wing_summaries:
                    print(f"[MainWindow] WARNING: No wings found for execution {execution_id}")
                    continue
                
                # Create ONE Results tab per execution with all wings as sub-tabs
                exec_id_str = str(execution_id) if isinstance(execution_id, int) else execution_id
                exec_id_display = exec_id_str[:8] if len(exec_id_str) > 8 else exec_id_str
                
                print(f"[MainWindow] Creating Results tab for execution {exec_id_display} with {len(wing_summaries)} wings")
                
                # Create a tabbed widget to hold all wing viewers from this execution
                from PyQt5.QtWidgets import QTabWidget
                combined_viewer = QTabWidget()
                
                # Identity wings share ONE unified sub-tab (with per-identity
                # wing attribution); time-window wings keep one sub-tab per wing
                from ..engine import engine_registry
                identity_wings = [w for w in wing_summaries
                                  if engine_registry.results_view_or_none(w.get('engine_type')) == 'identity']
                time_wings = [w for w in wing_summaries
                              if engine_registry.results_view_or_none(w.get('engine_type')) == 'timebased']
                behaviour_wings = [w for w in wing_summaries
                                   if engine_registry.results_view_or_none(w.get('engine_type')) == 'behaviour']
                wing_count = len(time_wings) + (1 if identity_wings else 0)

                if behaviour_wings:
                    viewer = self.results_viewer._create_behaviour_viewer(
                        behaviour_wings[0].get('database_path', db_path), [execution_id])
                    index = combined_viewer.addTab(
                        viewer, self.results_viewer.behaviour_tab_title(len(behaviour_wings)))
                    icon = self.results_viewer._behaviour_tab_icon()
                    if icon is not None:
                        combined_viewer.setTabIcon(index, icon)

                if identity_wings:
                    n_wings = len(identity_wings)
                    identity_db_path = identity_wings[0].get('database_path', db_path)

                    progress.setLabelText(f"Loading execution {idx + 1}/{len(selected_executions)}: {execution_id}\nIdentity wings (unified view)")
                    QApplication.processEvents()

                    viewer = self.results_viewer._create_identity_viewer(
                        identity_db_path, [execution_id],
                        show_progress=False, wing_count=n_wings
                    )
                    if viewer:
                        index = combined_viewer.addTab(viewer, f"Identity Results ({n_wings} wing{'s' if n_wings != 1 else ''})")
                        combined_viewer.setTabIcon(index, engine_icon("identity_based"))
                        print(f"[MainWindow] [OK] Added unified identity view ({n_wings} wings)")
                    QApplication.processEvents()

                for wing_idx, wing_summary in enumerate(time_wings):
                    wing_name = wing_summary.get('wing_name', 'Unknown Wing')
                    wing_engine_type = wing_summary.get('engine_type', 'unknown')
                    wing_db_path = wing_summary.get('database_path', db_path)

                    # Update progress for this wing
                    base_progress = int((idx / len(selected_executions)) * 90)
                    wing_progress = int((wing_idx / max(wing_count, 1)) * (90 / len(selected_executions)))
                    total_progress = base_progress + wing_progress
                    progress.setLabelText(f"Loading execution {idx + 1}/{len(selected_executions)}: {execution_id}\nWing {wing_idx + 1}/{wing_count}: {wing_name}")
                    progress.setValue(total_progress)
                    QApplication.processEvents()

                    print(f"[MainWindow] Creating viewer for wing: {wing_name} ({wing_engine_type})")

                    # Create appropriate viewer based on engine type
                    viewer = None
                    if engine_registry.results_view_or_none(wing_engine_type) == 'timebased':
                        viewer = self.results_viewer._create_timebased_viewer(wing_db_path, execution_id, show_progress=False)

                    if viewer:
                        index = combined_viewer.addTab(viewer, wing_name)
                        combined_viewer.setTabIcon(index, engine_icon(wing_engine_type))
                        print(f"[MainWindow] [OK] Added {wing_name} to combined viewer")

                    # Update progress after wing is loaded
                    QApplication.processEvents()
                
                # Add the combined viewer as a single Results tab for this execution
                tab_widget.addTab(combined_viewer, f"Results - Exec {exec_id_display}")
                self._apply_theme(root=combined_viewer)
                print(f"[MainWindow] [OK] Results tab created for execution {exec_id_display} with {len(wing_summaries)} wings")
            
            # Update Summary tab with aggregate statistics
            progress.setLabelText("Calculating aggregate statistics...")
            progress.setValue(95)
            QApplication.processEvents()
            
            # Collect all wing summaries for aggregate stats
            all_wing_summaries = []
            for db_path, execution_id, engine_type in selected_executions:
                wing_summaries = self.results_viewer._detect_wings_from_execution(db_path, execution_id)
                all_wing_summaries.extend(wing_summaries)
            
            # Calculate aggregate statistics
            aggregate_stats = {
                'total_wings_executed': len(all_wing_summaries),
                'total_matches_all_wings': sum(ws.get('total_matches', 0) for ws in all_wing_summaries),
                'execution_times': [ws.get('execution_time', 0) for ws in all_wing_summaries],
                'wing_summaries': all_wing_summaries,
                'feather_statistics': {}
            }
            
            # Aggregate feather statistics
            for wing_summary in all_wing_summaries:
                wing_feather_metadata = wing_summary.get('feather_metadata', {})
                for feather_id, metadata in wing_feather_metadata.items():
                    if feather_id.startswith('_'):
                        continue
                    
                    if feather_id not in aggregate_stats['feather_statistics']:
                        aggregate_stats['feather_statistics'][feather_id] = {
                            'identities_found': 0,
                            'identities_extracted': 0,
                            'records_processed': 0,
                            'matches_created': 0
                        }
                    
                    if isinstance(metadata, dict):
                        aggregate_stats['feather_statistics'][feather_id]['identities_found'] += metadata.get('identities_found', metadata.get('identities_final', 0))
                        aggregate_stats['feather_statistics'][feather_id]['identities_extracted'] += metadata.get('identities_extracted', metadata.get('identities_found', 0))
                        aggregate_stats['feather_statistics'][feather_id]['records_processed'] += metadata.get('records_processed', 0)
                        aggregate_stats['feather_statistics'][feather_id]['matches_created'] += metadata.get('matches_created', 0)
            
            # Update Summary tab
            self.results_viewer.update_summary_tab(aggregate_stats)
            
            progress.setValue(100)
            
            # Switch to Results tab
            self.tab_widget.setCurrentIndex(self.TAB_RESULTS)
            
            # Switch to Summary tab within Results (index 0)
            self.results_viewer.enhanced_tab_widget.tab_widget.setCurrentIndex(0)
            
            print(f"[MainWindow] Successfully loaded {len(selected_executions)} execution(s)")
            
            # Build tab list for message
            tab_list = [" • Summary (aggregate statistics)"]
            for db_path, execution_id, engine_type in selected_executions:
                exec_id_str = str(execution_id) if isinstance(execution_id, int) else execution_id
                exec_id_display = exec_id_str[:8] if len(exec_id_str) > 8 else exec_id_str
                wing_count = len(self.results_viewer._detect_wings_from_execution(db_path, execution_id))
                tab_list.append(f" • Results - Exec {exec_id_display} ({wing_count} wings)")
            
            QMessageBox.information(
                self,
                "Results Loaded",
                f"Successfully loaded {len(selected_executions)} execution(s)\n\n"
                f"Total Wings: {len(all_wing_summaries)}\n"
                f"Total Matches: {aggregate_stats['total_matches_all_wings']:,}\n\n"
                f"Tabs created:\n" + '\n'.join(tab_list)
            )
            
        except InterruptedError:
            progress.close()
            print("[MainWindow] Loading cancelled by user")
        except Exception as e:
            progress.close()
            QMessageBox.critical(
                self,
                "Error Loading Results",
                f"Failed to load results:\n\n{str(e)}"
            )
            import traceback
            traceback.print_exc()
    
    def closeEvent(self, event):
        """Handle window close event - auto-save, then confirm, then close.

        The auto-save runs FIRST, and that ordering is the whole point.
        `_check_unsaved_changes` opens a modal QMessageBox whenever the pipeline
        is modified, and a modal blocks forever anywhere there is nobody to
        answer it - which is why closing this window inside a test hung the
        process indefinitely after every assertion had already passed.

        Auto-saving first means there is nothing unsaved left to ask about:
        `save_pipeline` clears `is_modified`, so the check returns True without
        prompting. The prompt still appears for the case it exists for - a
        modification that could NOT be auto-saved, such as a pipeline with no
        name - and there it is a real question worth asking.
        """
        # Persist first: pipeline, session state, geometry.
        self._autosave_on_close()

        # Only prompts if something is still modified after the auto-save.
        if not self._check_unsaved_changes():
            event.ignore()
            return

        # Save settings
        self._save_settings()

        event.accept()
