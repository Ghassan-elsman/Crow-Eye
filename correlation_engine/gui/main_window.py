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
from .pipeline_builder import PipelineBuilderWidget
from .execution_control import ExecutionControlWidget
from .results_viewer import DynamicResultsTabWidget
from .identity_results_view import IdentityResultsView
from .timebased_results_viewer import TimeBasedResultsViewer
from ..integration.auto_feather_generator import AutoFeatherGenerator
from ..integration.default_wings_loader import DefaultWingsLoader


from ..integration.auto_feather_generator import AutoFeatherGenerator
from ..integration.default_wings_loader import DefaultWingsLoader


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
        
        info_label = QLabel("💡 Feathers are auto-generated from Crow-Eye artifacts on first load.")
        info_label.setStyleSheet("color: #888; font-size: 9pt;")
        info_layout.addWidget(info_label)
        
        info_layout.addStretch()
        
        self.regenerate_btn = QPushButton("🔄 Regenerate Feathers")
        self.regenerate_btn.setToolTip("Manually regenerate all feathers from Crow-Eye artifacts")
        self.regenerate_btn.clicked.connect(self._manual_generate_feathers)
        self.regenerate_btn.setEnabled(False)
        info_layout.addWidget(self.regenerate_btn)
        
        self.update_wings_btn = QPushButton("🔄 Update Default Wings")
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
        self.feathers_generated = False  # Reset flag when case changes
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
            
            # Check if Correlation/feathers directory exists
            feathers_dir = Path(self.case_directory) / "Correlation" / "feathers"
            
            if not feathers_dir.exists():
                return (True, "Feathers directory does not exist")
            
            # Check if there are any .json feather config files
            json_files = list(feathers_dir.glob("*.json"))
            
            if len(json_files) == 0:
                return (True, "No feather configuration files found")
            
            # Get expected feather count from mappings
            from ..integration.feather_mappings import get_feather_mappings
            expected_mappings = get_feather_mappings()
            expected_count = len(expected_mappings)
            
            # Check if we have all expected feathers
            if len(json_files) < expected_count:
                return (True, f"Missing feathers: found {len(json_files)}, expected {expected_count}")
            
            # Check if corresponding .db files exist for each .json config
            missing_dbs = []
            for json_file in json_files:
                db_file = json_file.with_suffix('.db')
                if not db_file.exists():
                    missing_dbs.append(json_file.stem)
            
            if missing_dbs:
                return (True, f"Missing database files for: {', '.join(missing_dbs[:3])}")
            
            # All checks passed
            return (False, "All feathers present and complete")
            
        except Exception as e:
            print(f"[Auto-Generation] Error checking feather status: {e}")
            # If we can't check, assume we need to generate
            return (True, f"Error checking status: {e}")
    
    def _auto_generate_feathers(self):
        """Automatically generate Feathers from Crow-Eye output"""
        try:
            # Check if Target_Artifacts directory exists
            from pathlib import Path
            target_artifacts = Path(self.case_directory) / "Target_Artifacts"
            
            if not target_artifacts.exists():
                print(f"[Auto-Generation] Target_Artifacts not found: {target_artifacts}")
                return
            
            # Create progress dialog
            progress = QProgressDialog(
                "Initializing Feather generation...",
                "Cancel",
                0, 100,
                self
            )
            progress.setWindowTitle("Generating Feathers")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)  # Show immediately
            progress.setValue(0)
            progress.show()
            
            # Create generator
            generator = AutoFeatherGenerator(self.case_directory)
            
            # Progress callback
            def update_progress(current, total, feather_name, status):
                if progress.wasCanceled():
                    return
                
                # Update progress bar
                percentage = int((current / total) * 100)
                progress.setValue(percentage)
                
                # Update label based on status
                if status == 'processing':
                    progress.setLabelText(f"Generating {feather_name}...\n({current}/{total})")
                elif status == 'success':
                    progress.setLabelText(f"✓ Generated {feather_name}\n({current}/{total})")
                elif status == 'skipped':
                    progress.setLabelText(f"⊘ Skipped {feather_name} (source not found)\n({current}/{total})")
                elif status == 'failed':
                    progress.setLabelText(f"✗ Failed {feather_name}\n({current}/{total})")
                
                # Process events to keep UI responsive
                from PyQt5.QtWidgets import QApplication
                QApplication.processEvents()
            
            # Generate all feathers with progress tracking
            results = generator.generate_all_feathers(progress_callback=update_progress)
            
            # Mark as generated
            self.feathers_generated = True
            progress.setValue(100)
            
            # Show summary message
            success_count = results['success_count']
            failure_count = results['failure_count']
            total = results['total']
            
            if failure_count == 0:
                QMessageBox.information(
                    self,
                    "Feathers Generated",
                    f"Successfully generated all {success_count} Feathers from Crow-Eye output.\n\n"
                    f"Feathers are now available in the Pipeline Builder."
                )
            else:
                # Build detailed message
                message = f"Generated {success_count} out of {total} Feathers.\n\n"
                
                if results['failed']:
                    message += f"{failure_count} Feathers were skipped or failed:\n\n"
                    for name, error in results['failed'][:5]:  # Show first 5
                        message += f"• {name}\n  {error}\n\n"
                    
                    if len(results['failed']) > 5:
                        message += f"... and {len(results['failed']) - 5} more.\n\n"
                
                message += "Check the console for detailed information."
                
                QMessageBox.warning(
                    self,
                    "Feather Generation Complete",
                    message
                )
            
            # Refresh pipeline builder to show new feathers
            if self.pipeline_builder:
                self.pipeline_builder.load_existing_configs()
            
            print(f"[Auto-Generation] Complete: {success_count}/{total} successful")
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Feather Generation Error",
                f"Failed to generate Feathers:\n\n{str(e)}\n\n"
                f"Check the console for detailed error information."
            )
            import traceback
            traceback.print_exc()
        finally:
            if 'progress' in locals():
                progress.close()
    
    def _manual_generate_feathers(self):
        """Manually regenerate all feathers from Crow-Eye artifacts with validation"""
        try:
            from pathlib import Path
            
            # Validate case directory is set
            if not self.case_directory:
                QMessageBox.warning(
                    self,
                    "No Case Directory",
                    "Case directory is not set. Please load a case first."
                )
                return
            
            # Check if Target_Artifacts directory exists
            target_artifacts = Path(self.case_directory) / "Target_Artifacts"
            
            if not target_artifacts.exists():
                QMessageBox.warning(
                    self,
                    "Target Artifacts Not Found",
                    f"Target_Artifacts directory not found:\n{target_artifacts}\n\n"
                    "Please ensure Crow-Eye has parsed artifacts for this case."
                )
                return
            
            # Check if any database files exist in Target_Artifacts
            db_files = list(target_artifacts.glob("*.db"))
            if not db_files:
                QMessageBox.warning(
                    self,
                    "No Database Files",
                    f"No database files found in:\n{target_artifacts}\n\n"
                    "Please run Crow-Eye parsers first to generate artifact databases."
                )
                return
            
            # Check/create Correlation directory structure
            correlation_dir = Path(self.case_directory) / "Correlation"
            feathers_dir = correlation_dir / "feathers"
            
            # Create directories if they don't exist
            feathers_dir.mkdir(parents=True, exist_ok=True)
            print(f"[Generate Feathers] Feathers directory ready: {feathers_dir}")
            
            # Confirm with user before regenerating
            reply = QMessageBox.question(
                self,
                "Generate Feathers",
                f"This will generate Feathers from {len(db_files)} database(s) in:\n"
                f"{target_artifacts}\n\n"
                f"Output directory:\n{feathers_dir}\n\n"
                "Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            
            if reply != QMessageBox.Yes:
                return
            
            # Create progress dialog
            progress = QProgressDialog(
                "Initializing Feather generation...",
                "Cancel",
                0, 100,
                self
            )
            progress.setWindowTitle("Generating Feathers")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)  # Show immediately
            progress.setValue(0)
            progress.show()
            
            # Create generator
            generator = AutoFeatherGenerator(self.case_directory)
            
            # Progress callback
            def update_progress(current, total, feather_name, status):
                if progress.wasCanceled():
                    return
                
                # Update progress bar
                percentage = int((current / total) * 100)
                progress.setValue(percentage)
                
                # Update label based on status
                if status == 'processing':
                    progress.setLabelText(f"Generating {feather_name}...\n({current}/{total})")
                elif status == 'success':
                    progress.setLabelText(f"✓ Generated {feather_name}\n({current}/{total})")
                elif status == 'skipped':
                    progress.setLabelText(f"⊘ Skipped {feather_name} (source not found)\n({current}/{total})")
                elif status == 'failed':
                    progress.setLabelText(f"✗ Failed {feather_name}\n({current}/{total})")
                
                # Process events to keep UI responsive
                from PyQt5.QtWidgets import QApplication
                QApplication.processEvents()
            
            # Generate all feathers with progress tracking
            results = generator.generate_all_feathers(progress_callback=update_progress)
            
            # Mark as generated
            self.feathers_generated = True
            progress.setValue(100)
            
            # Show summary message
            success_count = results['success_count']
            failure_count = results['failure_count']
            total = results['total']
            
            if failure_count == 0:
                QMessageBox.information(
                    self,
                    "Feathers Generated",
                    f"Successfully generated all {success_count} Feathers from Crow-Eye output.\n\n"
                    f"Feathers are now available in the Pipeline Builder."
                )
            else:
                # Build detailed message
                message = f"Generated {success_count} out of {total} Feathers.\n\n"
                
                if results['failed']:
                    message += f"{failure_count} Feathers were skipped or failed:\n\n"
                    for name, error in results['failed'][:5]:  # Show first 5
                        message += f"• {name}\n  {error}\n\n"
                    
                    if len(results['failed']) > 5:
                        message += f"... and {len(results['failed']) - 5} more.\n\n"
                
                message += "Check the console for detailed information."
                
                QMessageBox.warning(
                    self,
                    "Feather Generation Complete",
                    message
                )
            
            # Refresh pipeline builder to show new feathers
            if self.pipeline_builder:
                self.pipeline_builder.load_existing_configs()
            
            print(f"[Generate Feathers] Complete: {success_count}/{total} successful")
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Feather Generation Error",
                f"Failed to generate Feathers:\n\n{str(e)}\n\n"
                f"Check the console for detailed error information."
            )
            import traceback
            traceback.print_exc()
        finally:
            if 'progress' in locals():
                progress.close()


class MainWindow(QMainWindow):
    """Main application window with tabbed interface"""
    
    pipeline_loaded = pyqtSignal(PipelineConfig)
    
    def __init__(self):
        super().__init__()
        
        # Application state
        self.current_pipeline: Optional[PipelineConfig] = None
        self.current_pipeline_path: Optional[str] = None
        self.is_modified = False
        self.default_directory = None  # Will be set by correlation integration
        
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
        
        # Auto-load session if available
        self._load_session_state()
        
    def _init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("Correlation Engine")
        self.setMinimumSize(1280, 720)
        
        # Load and apply Crow-Eye styles
        self._load_styles()
        
        # Create central widget with tab widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #334155;
                background: #1E293B;
                border-radius: 8px;
            }
            
            QTabBar::tab {
                background: #1E293B;
                color: #94A3B8;
                border: 1px solid #334155;
                padding: 4px 12px;
                font-weight: 600;
                font-size: 7pt;
                min-height: 14px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            
            QTabBar::tab:selected {
                background-color: #0B1220;
                color: #00FFFF;
                border-bottom: 2px solid #00FFFF;
            }
            
            QTabBar::tab:hover:!selected {
                background-color: #334155;
                color: #FFFFFF;
            }
        """)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tab_widget)
        
        # Create tabs - use custom PipelineManagerTab
        self.pipeline_manager_tab = PipelineManagerTab()
        self.pipeline_manager_tab.set_main_window(self)
        self.execution_tab = QWidget()
        self.results_tab = QWidget()
        
        self.tab_widget.addTab(self.pipeline_manager_tab, "Pipeline Manager")
        self.tab_widget.addTab(self.execution_tab, "Execution")
        self.tab_widget.addTab(self.results_tab, "Results")
        
        # Initialize Pipeline Manager tab with builder
        pipeline_manager_layout = self.pipeline_manager_tab.layout()
        
        # Add pipeline builder widget
        self.pipeline_builder = PipelineBuilderWidget()
        self.pipeline_builder.pipeline_modified.connect(self._on_pipeline_modified)
        pipeline_manager_layout.addWidget(self.pipeline_builder)
        
        # Set pipeline builder reference in tab
        self.pipeline_manager_tab.pipeline_builder = self.pipeline_builder
        
        # Initialize Execution tab with execution control
        execution_layout = QVBoxLayout(self.execution_tab)
        execution_layout.setContentsMargins(10, 10, 10, 10)
        
        # Add execution control widget
        self.execution_control = ExecutionControlWidget()
        self.execution_control.execution_completed.connect(self._on_execution_completed)
        self.execution_control.load_results_requested.connect(self._on_load_results_requested)
        execution_layout.addWidget(self.execution_control)
        
        # Initialize Results tab with sub-tabs for different viewers
        results_layout = QVBoxLayout(self.results_tab)
        results_layout.setContentsMargins(10, 10, 10, 10)
        
        # Create a QTabWidget inside the Results tab for Summary and engine viewers
        self.results_sub_tabs = QTabWidget()
        self.results_sub_tabs.setTabPosition(QTabWidget.North)
        
        # Add Summary tab (default viewer)
        self.summary_viewer = DynamicResultsTabWidget()
        self.results_sub_tabs.addTab(self.summary_viewer, "Summary")
        
        # Keep reference to current viewer (for backward compatibility)
        self.current_results_viewer = self.summary_viewer
        
        results_layout.addWidget(self.results_sub_tabs)
        
        # Create menu bar
        self._create_menu_bar()
        
        # Create status bar
        self._create_status_bar()
    
    def _load_styles(self):
        """Load and apply Crow-Eye stylesheet"""
        try:
            # Get the directory where this file is located
            current_dir = Path(__file__).parent
            style_file = current_dir / "crow_eye_styles.qss"
            
            if style_file.exists():
                with open(style_file, 'r') as f:
                    stylesheet = f.read()
                self.setStyleSheet(stylesheet)
                print(f"[Correlation Engine] Loaded styles from: {style_file}")
            else:
                print(f"[Correlation Engine] Warning: Style file not found: {style_file}")
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
        self.recent_list.itemDoubleClicked.connect(self._open_recent_pipeline)
        
        self.recent_dock.setWidget(self.recent_list)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.recent_dock)
        
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
            
            # Update window title
            self._update_window_title()
            
            # Load into pipeline builder
            self.pipeline_builder.load_pipeline(self.current_pipeline)
            
            # Load into execution control
            self.execution_control.display_pipeline_overview(self.current_pipeline)
            
            # Emit signal
            self.pipeline_loaded.emit(self.current_pipeline)
            
            # Switch to execution tab
            self.tab_widget.setCurrentIndex(1)
            
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
        # Set color based on level
        colors = {
            "info": "#2196F3",
            "success": "#4CAF50",
            "warning": "#FF9800",
            "error": "#F44336"
        }
        
        color = colors.get(level, colors["info"])
        self.status_label.setStyleSheet(f"color: {color};")
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
        self.tab_widget.setCurrentIndex(0)
        
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
            self.tab_widget.setCurrentIndex(0)
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
                
                # Restore tab
                last_tab = session_data.get('last_tab', 0)
                self.tab_widget.setCurrentIndex(last_tab)
                
                print(f"[Main Window] Restored session: {last_pipeline}")
                
        except Exception as e:
            print(f"[Main Window] Failed to load session state: {e}")
    
    def _show_preferences(self):
        """Show preferences dialog"""
        try:
            from .settings_dialog import SettingsDialog
            from ..config.integrated_configuration_manager import IntegratedConfigurationManager
            
            # Initialize configuration manager if not already done
            if not hasattr(self, 'config_manager'):
                self.config_manager = IntegratedConfigurationManager()
            
            # Create and show settings dialog
            dialog = SettingsDialog(self.config_manager, self)
            
            # Connect configuration change signal
            dialog.configuration_changed.connect(self._on_configuration_changed)
            
            # Show dialog
            dialog.exec_()
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Settings Error",
                f"Failed to open settings dialog: {str(e)}"
            )
    
    def _on_configuration_changed(self, new_config):
        """Handle configuration changes from settings dialog"""
        try:
            # Update any components that depend on configuration
            # This will be expanded as more components are integrated
            
            # Update status bar
            self.status_bar.showMessage("Configuration updated", 3000)
            
            # Log the change
            print(f"[Main Window] Configuration updated: "
                  f"Semantic mapping: {'enabled' if new_config.semantic_mapping.enabled else 'disabled'}, "
                  f"Weighted scoring: {'enabled' if new_config.weighted_scoring.enabled else 'disabled'}")
            
        except Exception as e:
            print(f"[Main Window] Error handling configuration change: {e}")
    
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
    
    def closeEvent(self, event):
        """Handle window close event - auto-save pipeline and session"""
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
                    print(f"[Main Window] Auto-saved pipeline on close: {pipeline_file}")
                except Exception as e:
                    print(f"[Main Window] Failed to auto-save pipeline: {e}")
            
            # Save session state
            self._save_session_state()
            
            # Save window geometry
            self.settings.setValue("geometry", self.saveGeometry())
            
            print("[Main Window] Closed with auto-save")
            
        except Exception as e:
            print(f"[Main Window] Error in closeEvent: {e}")
        
        # Accept the close event
        event.accept()
    
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
    
    def _on_execution_completed(self, summary: dict):
        """Handle execution completion and open appropriate results viewer"""
        # Get engine type from summary
        engine_type = summary.get('engine_type', 'time_window_scanning')
        output_dir = self.current_pipeline.output_directory if self.current_pipeline else "output"
        
        print(f"[MainWindow] Execution completed with engine type: {engine_type}")
        
        # Pass engine type to Summary Tab
        self.summary_viewer.set_engine_type(engine_type)
        self.summary_viewer.load_results(output_dir)
        
        # Create appropriate results viewer based on engine type
        new_viewer = self._create_results_viewer_for_engine(engine_type, output_dir)
        
        if new_viewer:
            # Add as sub-tab with engine-specific name
            tab_name = engine_type.replace('_', ' ').title()
            self._switch_results_viewer(new_viewer, tab_name)
            
            # Load results into the new viewer
            self._load_results_into_viewer(new_viewer, engine_type, output_dir)
        else:
            # Fallback to current viewer
            print(f"[MainWindow] Using fallback viewer for engine type: {engine_type}")
            self.current_results_viewer.set_engine_type(engine_type)
            self.current_results_viewer.load_results(output_dir)
    
    def _on_load_results_requested(self, request: dict):
        """Handle request to load results from execution control (enhanced for multiple selections)."""
        selected_executions = request.get('selected_executions', [])
        output_dir = request.get('output_dir', '')
        
        if not selected_executions:
            print("[MainWindow] No executions selected")
            return
        
        print(f"[MainWindow] Loading {len(selected_executions)} execution(s)")
        
        # Show progress dialog
        from PyQt5.QtWidgets import QProgressDialog
        progress = QProgressDialog(
            f"Loading {len(selected_executions)} execution(s)...",
            "Cancel",
            0,
            len(selected_executions),
            self
        )
        progress.setWindowTitle("Loading Results")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)  # Show immediately
        progress.setValue(0)
        
        # Load each selected execution into its appropriate viewer
        for idx, (db_path, execution_id, engine_type) in enumerate(selected_executions):
            if progress.wasCanceled():
                print("[MainWindow] Loading cancelled by user")
                break
                
            progress.setLabelText(f"Loading execution {execution_id} ({engine_type})...\n{idx + 1} of {len(selected_executions)}")
            progress.setValue(idx)
            QApplication.processEvents()  # Update UI
            
            print(f"[MainWindow] Loading execution {execution_id} ({engine_type}) from {db_path}")
            
            # Create appropriate results viewer based on engine type
            new_viewer = self._create_results_viewer_for_engine(engine_type, output_dir)
            
            if new_viewer:
                # Add as sub-tab with execution-specific name
                tab_name = f"{engine_type.replace('_', ' ').title()} - Exec {execution_id}"
                self._switch_results_viewer(new_viewer, tab_name)
                
                # Load results from specific execution
                self._load_results_from_execution(new_viewer, engine_type, db_path, execution_id)
            else:
                print(f"[MainWindow] Failed to create viewer for engine type: {engine_type}")
        
        progress.setValue(len(selected_executions))
        progress.close()
        
        if not progress.wasCanceled():
            self.show_notification(f"Loaded {len(selected_executions)} execution(s)", "success")
    
    def _load_results_from_execution(self, viewer, engine_type: str, db_path: str, execution_id: int):
        """Load results from a specific execution into the viewer."""
        try:
            if isinstance(viewer, IdentityResultsView):
                # Identity viewer expects CorrelationResult objects
                print(f"[MainWindow] Loading execution {execution_id} into Identity Results Viewer")
                self._load_identity_results_from_execution(viewer, db_path, execution_id)
                
            elif isinstance(viewer, TimeBasedResultsViewer):
                # Time-based viewer can load from database
                print(f"[MainWindow] Loading execution {execution_id} into Time-Based Results Viewer")
                viewer.set_database_path(db_path)
                viewer.load_results_from_execution(execution_id)
                
            else:
                # Generic viewer
                print(f"[MainWindow] Loading execution {execution_id} into generic viewer")
                if hasattr(viewer, 'load_results_from_execution'):
                    viewer.load_results_from_execution(db_path, execution_id)
                else:
                    print(f"[MainWindow] Viewer does not support loading from execution")
                    
        except Exception as e:
            print(f"[MainWindow] Error loading execution {execution_id}: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self,
                "Load Error",
                f"Failed to load execution {execution_id}:\n\n{str(e)}"
            )
    
    def _load_identity_results_from_execution(self, viewer: IdentityResultsView, db_path: str, execution_id: int):
        """Load identity results from a specific execution."""
        try:
            from ..engine.database_persistence import ResultsDatabase
            
            with ResultsDatabase(db_path) as db:
                print(f"[MainWindow] Loading results for execution {execution_id}")
                
                # Load all results for the execution
                correlation_results = db.load_execution_results(execution_id)
                
                if not correlation_results:
                    print(f"[MainWindow] No results found for execution {execution_id}")
                    QMessageBox.information(
                        self,
                        "No Results",
                        f"No correlation results found for execution {execution_id}."
                    )
                    return
                
                print(f"[MainWindow] Loaded {len(correlation_results)} correlation results from database")
                
                # Use the first result or combine multiple results if needed
                primary_result = correlation_results[0]
                
                # If multiple results, combine matches
                if len(correlation_results) > 1:
                    print(f"[MainWindow] Combining {len(correlation_results)} result sets...")
                    for idx, additional_result in enumerate(correlation_results[1:], 2):
                        print(f"[MainWindow]   Merging result {idx}/{len(correlation_results)}...")
                        primary_result.matches.extend(additional_result.matches)
                        primary_result.total_matches += additional_result.total_matches
                    print(f"[MainWindow]   ✓ Combined into {primary_result.total_matches:,} total matches")
                
                print(f"[MainWindow] Loading {len(primary_result.matches):,} matches into identity viewer...")
                viewer.load_from_correlation_result(primary_result)
                print(f"[MainWindow] ✓ Successfully loaded into Identity viewer from database")
                
        except Exception as e:
            print(f"[MainWindow] Error loading identity results from execution {execution_id}: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def _create_results_viewer_for_engine(self, engine_type: str, output_dir: str):
        """Create the appropriate results viewer for the given engine type"""
        try:
            if engine_type == "identity_based":
                print("[MainWindow] Creating Identity Results Viewer")
                viewer = IdentityResultsView()
                return viewer
            
            elif engine_type in ["time_window_scanning", "time_based"]:
                print("[MainWindow] Creating Time-Based Results Viewer")
                viewer = TimeBasedResultsViewer()
                
                # Set database path for hierarchical view if available
                db_path = Path(output_dir) / "correlation_results.db"
                if db_path.exists():
                    viewer.set_database_path(str(db_path))
                    print(f"[MainWindow] Set database path: {db_path}")
                
                return viewer
            
            else:
                print(f"[MainWindow] Unknown engine type: {engine_type}, using generic viewer")
                return DynamicResultsTabWidget()
                
        except Exception as e:
            print(f"[MainWindow] Error creating viewer for {engine_type}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _switch_results_viewer(self, new_viewer, tab_name="Results"):
        """Add results viewer as a sub-tab within the Results tab"""
        try:
            # Check if a sub-tab with this name already exists
            existing_index = -1
            for i in range(self.results_sub_tabs.count()):
                if self.results_sub_tabs.tabText(i) == tab_name:
                    existing_index = i
                    break
            
            if existing_index >= 0:
                # Sub-tab exists - replace its content
                old_widget = self.results_sub_tabs.widget(existing_index)
                self.results_sub_tabs.removeTab(existing_index)
                if old_widget:
                    old_widget.setParent(None)
                    old_widget.deleteLater()
                
                # Add new viewer at the same position
                self.results_sub_tabs.insertTab(existing_index, new_viewer, tab_name)
                self.results_sub_tabs.setCurrentIndex(existing_index)
            else:
                # Sub-tab doesn't exist - add new sub-tab
                new_index = self.results_sub_tabs.addTab(new_viewer, tab_name)
                self.results_sub_tabs.setCurrentIndex(new_index)
            
            # Switch to Results tab (main tab)
            self.tab_widget.setCurrentWidget(self.results_tab)
            
            self.current_results_viewer = new_viewer
            print(f"[MainWindow] Added {tab_name} sub-tab in Results")
            
        except Exception as e:
            print(f"[MainWindow] Error switching viewer: {e}")
            import traceback
            traceback.print_exc()
            
            print(f"[MainWindow] Switched to {type(new_viewer).__name__}")
            
        except Exception as e:
            print(f"[MainWindow] Error switching viewers: {e}")
            import traceback
            traceback.print_exc()
    
    def _load_results_into_viewer(self, viewer, engine_type: str, output_dir: str):
        """Load results into the appropriate viewer"""
        try:
            if isinstance(viewer, IdentityResultsView):
                # Identity viewer expects CorrelationResult objects
                print("[MainWindow] Loading results into Identity Results Viewer")
                self._load_identity_results(viewer, output_dir)
                
            elif isinstance(viewer, TimeBasedResultsViewer):
                # Time-based viewer can load from directory with database integration
                print("[MainWindow] Loading results into Time-Based Results Viewer")
                from pathlib import Path
                db_path = Path(output_dir) / "correlation_results.db"
                
                # Call load_results with output_dir and db_path
                viewer.load_results(
                    output_dir=output_dir,
                    db_path=str(db_path) if db_path.exists() else None
                )
                
            else:
                # Generic viewer
                print("[MainWindow] Loading results into generic viewer")
                viewer.set_engine_type(engine_type)
                viewer.load_results(output_dir)
                
        except Exception as e:
            print(f"[MainWindow] Error loading results into viewer: {e}")
            import traceback
            traceback.print_exc()
    
    def _load_identity_results(self, viewer: IdentityResultsView, output_dir: str):
        """Load results specifically for Identity Results Viewer from database"""
        try:
            from ..engine.database_persistence import ResultsDatabase
            
            output_path = Path(output_dir)
            db_path = output_path / "correlation_results.db"
            
            if not db_path.exists():
                print(f"[MainWindow] Database not found: {db_path}")
                QMessageBox.warning(
                    self,
                    "Database Not Found",
                    f"Correlation results database not found:\n{db_path}\n\n"
                    "Please ensure the correlation engine has been executed and results saved to database."
                )
                return
            
            print(f"[MainWindow] Loading identity results from database: {db_path}")
            
            with ResultsDatabase(str(db_path)) as db:
                # Get the latest execution
                latest_execution_id = db.get_latest_execution_id()
                
                if not latest_execution_id:
                    print("[MainWindow] No executions found in database")
                    QMessageBox.information(
                        self,
                        "No Results",
                        "No correlation results found in database."
                    )
                    return
                
                print(f"[MainWindow] Loading results for execution {latest_execution_id}")
                
                # Load all results for the latest execution
                correlation_results = db.load_execution_results(latest_execution_id)
                
                if not correlation_results:
                    print("[MainWindow] No results found for latest execution")
                    QMessageBox.information(
                        self,
                        "No Results",
                        f"No correlation results found for execution {latest_execution_id}."
                    )
                    return
                
                print(f"[MainWindow] Loaded {len(correlation_results)} correlation results from database")
                
                # Use the first result or combine multiple results if needed
                primary_result = correlation_results[0]
                
                # If multiple results, combine matches
                if len(correlation_results) > 1:
                    print(f"[MainWindow] Combining {len(correlation_results)} result sets...")
                    for idx, additional_result in enumerate(correlation_results[1:], 2):
                        print(f"[MainWindow]   Merging result {idx}/{len(correlation_results)}...")
                        primary_result.matches.extend(additional_result.matches)
                        primary_result.total_matches += additional_result.total_matches
                    print(f"[MainWindow]   ✓ Combined into {primary_result.total_matches:,} total matches")
                
                print(f"[MainWindow] Loading {len(primary_result.matches):,} matches into identity viewer...")
                viewer.load_from_correlation_result(primary_result)
                print(f"[MainWindow] ✓ Successfully loaded into Identity viewer from database")
                
        except Exception as e:
            print(f"[MainWindow] Error loading identity results from database: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self,
                "Database Error",
                f"Failed to load results from database:\n\n{str(e)}"
            )
    
    def closeEvent(self, event):
        """Handle window close event"""
        # Check for unsaved changes
        if not self._check_unsaved_changes():
            event.ignore()
            return
        
        # Save settings
        self._save_settings()
        
        event.accept()
