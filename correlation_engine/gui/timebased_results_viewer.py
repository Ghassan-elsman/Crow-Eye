"""
Time Window-Based Correlation Results View - Hierarchical Design

Features:
- Hierarchical tree structure: Time Windows → Identities → Sub-Identities → Evidence
- Dynamic window size adjustment (re-group on-the-fly)
- Compact layout matching Identity Viewer style
- Temporal pattern analysis
- Comprehensive statistics tables
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QLineEdit, QPushButton, QGroupBox, QDialog, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QMessageBox, QTextEdit, QTabWidget, QFrame, QSpinBox, QDateTimeEdit,
    QProgressDialog, QApplication, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal, QDateTime
from PyQt5.QtGui import QColor, QFont, QBrush
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from collections import defaultdict


class TimeBasedResultsViewer(QWidget):
    """Time Window-Based Correlation Results View with Hierarchical Tree and Dynamic Grouping."""
    
    match_selected = pyqtSignal(dict)
    
    # Pagination settings
    PAGE_SIZE = 100  # Load 100 windows at a time
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.time_windows = []  # List of time window data
        self.filtered_windows = []
        self.current_results = None
        self.current_page = 0
        self.original_window_size_minutes = 180  # Default from scan (3 hours)
        self.viewing_window_size_minutes = 180  # Current viewing size
        self.all_matches = []  # Store all matches for re-grouping
        self.scoring_enabled = False
        self.semantic_enabled = False
        self.database_path = None  # Path to correlation_results.db
        self.setup_ui()

    def setup_ui(self):
        """Setup compact UI with labeled filters matching Identity Viewer style."""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(2)
        main_layout.setContentsMargins(4, 4, 4, 4)
        
        # === TOP: Summary + Filters (single compact row) ===
        top_frame = QFrame()
        top_frame.setMaximumHeight(32)
        top_layout = QHBoxLayout(top_frame)
        top_layout.setSpacing(8)
        top_layout.setContentsMargins(4, 2, 4, 2)
        
        # Summary labels (compact - values only, tooltips for context)
        self.windows_lbl = QLabel("0")
        self.windows_lbl.setStyleSheet("color: #2196F3; font-weight: bold; font-size: 8pt;")
        self.windows_lbl.setToolTip("Windows")
        top_layout.addWidget(self.windows_lbl)
        
        self.identities_lbl = QLabel("0")
        self.identities_lbl.setStyleSheet("font-size: 7pt;")
        self.identities_lbl.setToolTip("Identities")
        top_layout.addWidget(self.identities_lbl)
        
        self.records_lbl = QLabel("0")
        self.records_lbl.setStyleSheet("font-size: 7pt;")
        self.records_lbl.setToolTip("Records")
        top_layout.addWidget(self.records_lbl)
        
        self.time_lbl = QLabel("0s")
        self.time_lbl.setStyleSheet("font-size: 7pt;")
        self.time_lbl.setToolTip("Execution Time")
        top_layout.addWidget(self.time_lbl)
        
        self.feathers_used_lbl = QLabel("0")
        self.feathers_used_lbl.setStyleSheet("color: #4CAF50; font-size: 7pt;")
        self.feathers_used_lbl.setToolTip("Feathers")
        top_layout.addWidget(self.feathers_used_lbl)
        
        # Scoring indicator
        self.scoring_lbl = QLabel("📊")
        self.scoring_lbl.setStyleSheet("font-size: 7pt; color: #888;")
        self.scoring_lbl.setToolTip("Scoring: Off")
        top_layout.addWidget(self.scoring_lbl)
        
        # Legend button
        legend_btn = QPushButton("?")
        legend_btn.setMaximumWidth(16)
        legend_btn.setMaximumHeight(16)
        legend_btn.setStyleSheet("font-size: 6pt; padding: 0px; background-color: #444; border-radius: 8px;")
        legend_btn.setToolTip("Show visual indicators legend")
        legend_btn.clicked.connect(self._show_legend)
        top_layout.addWidget(legend_btn)
        
        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #444;")
        top_layout.addWidget(sep)
        
        # Search filter
        search_lbl = QLabel("Search:")
        search_lbl.setStyleSheet("font-size: 7pt; color: #aaa;")
        top_layout.addWidget(search_lbl)
        
        self.identity_filter = QLineEdit()
        self.identity_filter.setPlaceholderText("identity...")
        self.identity_filter.setMaximumWidth(200)
        self.identity_filter.setStyleSheet("font-size: 7pt; padding: 1px 3px;")
        self.identity_filter.textChanged.connect(self._apply_filters)
        top_layout.addWidget(self.identity_filter)
        
        # Feather filter
        feather_lbl = QLabel("Feather:")
        feather_lbl.setStyleSheet("font-size: 7pt; color: #aaa;")
        top_layout.addWidget(feather_lbl)
        
        self.feather_filter = QComboBox()
        self.feather_filter.addItem("All")
        self.feather_filter.setMaximumWidth(180)
        self.feather_filter.setStyleSheet("font-size: 7pt;")
        self.feather_filter.currentTextChanged.connect(self._apply_filters)
        top_layout.addWidget(self.feather_filter)
        
        # Time range filter
        time_lbl = QLabel("Time:")
        time_lbl.setStyleSheet("font-size: 7pt; color: #aaa;")
        top_layout.addWidget(time_lbl)
        
        self.time_start_edit = QDateTimeEdit()
        self.time_start_edit.setDisplayFormat("MM-dd HH:mm")
        self.time_start_edit.setMaximumWidth(140)
        self.time_start_edit.setStyleSheet("font-size: 7pt;")
        self.time_start_edit.setCalendarPopup(True)
        self.time_start_edit.dateTimeChanged.connect(self._apply_filters)
        top_layout.addWidget(self.time_start_edit)
        
        to_lbl = QLabel("-")
        to_lbl.setStyleSheet("font-size: 7pt; color: #aaa;")
        top_layout.addWidget(to_lbl)
        
        self.time_end_edit = QDateTimeEdit()
        self.time_end_edit.setDisplayFormat("MM-dd HH:mm")
        self.time_end_edit.setMaximumWidth(140)
        self.time_end_edit.setStyleSheet("font-size: 7pt;")
        self.time_end_edit.setCalendarPopup(True)
        self.time_end_edit.dateTimeChanged.connect(self._apply_filters)
        top_layout.addWidget(self.time_end_edit)
        
        # Window status filter
        status_lbl = QLabel("Status:")
        status_lbl.setStyleSheet("font-size: 7pt; color: #aaa;")
        top_layout.addWidget(status_lbl)
        
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All", "With Data", "Empty"])
        self.status_filter.setMaximumWidth(90)
        self.status_filter.setStyleSheet("font-size: 7pt;")
        self.status_filter.currentTextChanged.connect(self._apply_filters)
        top_layout.addWidget(self.status_filter)
        
        # Reset button
        reset_btn = QPushButton("Reset")
        reset_btn.setMaximumWidth(40)
        reset_btn.setStyleSheet("font-size: 7pt; padding: 1px 4px;")
        reset_btn.clicked.connect(self._reset_filters)
        top_layout.addWidget(reset_btn)
        
        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("color: #444;")
        top_layout.addWidget(sep2)
        
        # Pagination controls
        self.prev_btn = QPushButton("<")
        self.prev_btn.setMaximumWidth(20)
        self.prev_btn.setStyleSheet("font-size: 7pt; padding: 1px;")
        self.prev_btn.clicked.connect(self._prev_page)
        top_layout.addWidget(self.prev_btn)
        
        self.page_lbl = QLabel("1/1")
        self.page_lbl.setStyleSheet("font-size: 7pt;")
        top_layout.addWidget(self.page_lbl)
        
        self.next_btn = QPushButton(">")
        self.next_btn.setMaximumWidth(20)
        self.next_btn.setStyleSheet("font-size: 7pt; padding: 1px;")
        self.next_btn.clicked.connect(self._next_page)
        top_layout.addWidget(self.next_btn)
        
        top_layout.addStretch()
        main_layout.addWidget(top_frame)
        
        # === MIDDLE: Results Tree ===
        self.results_tree = self._create_tree()
        main_layout.addWidget(self.results_tree, stretch=1)
        
        # === BOTTOM: Ultra Compact Stats Tables ===
        stats_frame = QFrame()
        stats_frame.setMaximumHeight(160)
        stats_layout = QHBoxLayout(stats_frame)
        stats_layout.setSpacing(6)
        stats_layout.setContentsMargins(2, 2, 2, 2)
        
        # Time Windows Table
        self.windows_table = self._create_compact_table(["Time Range", "IDs", "Rec", "Status"])
        stats_layout.addWidget(self._wrap_table("Time Windows", self.windows_table), stretch=2)
        
        # Feather Contribution Table
        self.feather_table = self._create_compact_table(["Feather", "Win", "Rec", "IDs"])
        stats_layout.addWidget(self._wrap_table("Feathers", self.feather_table), stretch=2)
        
        # Identity Activity Table
        self.identity_table = self._create_compact_table(["Identity", "Win", "First", "Last"])
        stats_layout.addWidget(self._wrap_table("Identities", self.identity_table), stretch=2)
        
        # Temporal Patterns Table
        self.patterns_table = self._create_compact_table(["Pattern", "Count", "%"])
        stats_layout.addWidget(self._wrap_table("Patterns", self.patterns_table), stretch=1)
        
        main_layout.addWidget(stats_frame)

    def _create_tree(self) -> QTreeWidget:
        """Create tree with app-matching background and hierarchical structure."""
        tree = QTreeWidget()
        tree.setHeaderLabels(["Time Window / Identity / Evidence", "Feathers", "Time", "Score", "Records", "Artifact"])
        
        tree.setColumnWidth(0, 300)
        tree.setColumnWidth(1, 150)
        tree.setColumnWidth(2, 140)
        tree.setColumnWidth(3, 60)
        tree.setColumnWidth(4, 60)
        tree.setColumnWidth(5, 80)
        
        tree.setAlternatingRowColors(True)
        tree.itemDoubleClicked.connect(self._on_double_click)
        tree.itemClicked.connect(self._on_item_clicked)
        tree.setContextMenuPolicy(Qt.CustomContextMenu)
        tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        
        # Match app background - transparent/inherit
        tree.setStyleSheet("""
            QTreeWidget {
                font-size: 8pt;
                background-color: transparent;
                alternate-background-color: rgba(255,255,255,0.02);
                border: 1px solid #333;
            }
            QTreeWidget::item { padding: 1px; }
            QTreeWidget::item:selected { background-color: #0d47a1; }
            QHeaderView::section {
                background-color: #2196F3;
                color: white;
                padding: 2px;
                font-size: 7pt;
                font-weight: bold;
                border: none;
            }
        """)
        return tree
    
    def _create_compact_table(self, headers: List[str]) -> QTableWidget:
        """Create ultra compact table with smaller headers."""
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setMaximumHeight(110)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(14)
        table.horizontalHeader().setFixedHeight(18)
        table.setStyleSheet("""
            QTableWidget {
                font-size: 7pt;
                background-color: transparent;
                border: 1px solid #333;
            }
            QTableWidget::item { padding: 0px; }
            QHeaderView::section {
                background-color: #1a1a2e;
                color: #aaa;
                padding: 1px;
                font-size: 6pt;
                border: none;
                border-right: 1px solid #333;
            }
        """)
        return table
    
    def _wrap_table(self, title: str, table: QTableWidget) -> QGroupBox:
        """Wrap table in ultra compact group box matching tab style."""
        group = QGroupBox(title)
        group.setStyleSheet("""
            QGroupBox { 
                font-size: 7pt; 
                font-weight: bold; 
                color: #aaa;
                padding-top: 10px; 
                margin-top: 4px;
                border: 1px solid #333;
                background-color: #1a1a2e;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 3px;
                background-color: #1a1a2e;
            }
        """)
        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        layout.addWidget(table)
        group.setLayout(layout)
        return group

    def load_from_correlation_result(self, result):
        """Load from CorrelationResult object and organize by time windows with progress indicator."""
        print(f"[TimeWindowResultsView] load_from_correlation_result called with {result.total_matches} matches")
        
        # Show progress dialog if we have many windows
        progress = None
        if result.total_matches > 50:
            progress = QProgressDialog("Loading time windows...", "Cancel", 0, 100, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(500)
            progress.setWindowTitle("Loading Results")
            progress.show()
            QApplication.processEvents()
        
        try:
            # Store all matches for re-grouping
            self.all_matches = result.matches
            
            # Get original window size from config if available
            if hasattr(result, 'performance_metrics') and result.performance_metrics:
                config_data = result.performance_metrics.get('configuration', {})
                self.original_window_size_minutes = config_data.get('window_size_minutes', 180)
            
            self.viewing_window_size_minutes = self.original_window_size_minutes
            
            if progress:
                progress.setLabelText("Grouping matches into time windows...")
                progress.setValue(20)
                QApplication.processEvents()
            
            # Group matches into time windows
            self.time_windows = self._group_matches_into_windows(self.all_matches, self.viewing_window_size_minutes, progress)
            
            if progress and progress.wasCanceled():
                print("[TimeWindowResultsView] Loading cancelled by user")
                return
            
            print(f"[TimeWindowResultsView] Grouped into {len(self.time_windows)} time windows")
            
            if progress:
                progress.setLabelText("Processing metadata...")
                progress.setValue(70)
                QApplication.processEvents()
            
            # Use feather_metadata from result if available
            feather_metadata = result.feather_metadata if hasattr(result, 'feather_metadata') and result.feather_metadata else {}
            
            # Filter out non-dict metadata entries
            filtered_metadata = {}
            for fid, data in feather_metadata.items():
                if isinstance(data, dict):
                    filtered_metadata[fid] = data
            feather_metadata = filtered_metadata
            
            # Build results dict
            results_dict = {
                'time_windows': self.time_windows,
                'statistics': {
                    'total_windows': len(self.time_windows),
                    'windows_with_data': sum(1 for w in self.time_windows if w['identities']),
                    'empty_windows_skipped': sum(1 for w in self.time_windows if not w['identities']),
                    'total_identities': len(set(m.matched_application for m in self.all_matches if m.matched_application)),
                    'total_records': result.total_records_scanned,
                    'execution_time': result.execution_duration_seconds,
                    'feathers_used': result.feathers_processed
                },
                'wing_name': result.wing_name,
                'feather_metadata': feather_metadata,
                'original_window_size': self.original_window_size_minutes,
                'viewing_window_size': self.viewing_window_size_minutes
            }
            
            if progress:
                progress.setLabelText("Displaying results...")
                progress.setValue(90)
                QApplication.processEvents()
            
            print(f"[TimeWindowResultsView] Calling load_results with {len(self.time_windows)} windows")
            self.load_results(results_dict)
            print(f"[TimeWindowResultsView] load_results completed, tree has {self.results_tree.topLevelItemCount()} items")
            
            if progress:
                progress.setValue(100)
                progress.close()
                
        except Exception as e:
            if progress:
                progress.close()
            print(f"[Error] Failed to load results: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Load Error", f"Failed to load results:\n{str(e)}")
    
    def set_database_path(self, db_path: str):
        """Set the database path for loading results from database."""
        self.database_path = db_path
        print(f"[TimeWindowResultsView] Database path set to: {db_path}")
    
    def load_results_from_execution(self, execution_id: int):
        """Load results from a specific execution in the database."""
        if not self.database_path:
            print("[TimeWindowResultsView] No database path set, cannot load from execution")
            return
        
        try:
            from pathlib import Path
            from ..engine.database_persistence import ResultsDatabase
            
            print(f"[TimeWindowResultsView] Loading execution {execution_id} from {self.database_path}")
            
            with ResultsDatabase(self.database_path) as db:
                # Load all results for the execution
                correlation_results = db.load_execution_results(execution_id)
                
                if not correlation_results:
                    print(f"[TimeWindowResultsView] No results found for execution {execution_id}")
                    return
                
                print(f"[TimeWindowResultsView] Loaded {len(correlation_results)} correlation results")
                
                # Use the first result or combine multiple results if needed
                primary_result = correlation_results[0]
                
                # If multiple results, combine matches
                if len(correlation_results) > 1:
                    print(f"[TimeWindowResultsView] Combining {len(correlation_results)} result sets...")
                    for additional_result in correlation_results[1:]:
                        primary_result.matches.extend(additional_result.matches)
                        primary_result.total_matches += additional_result.total_matches
                
                # Load the combined result
                self.load_from_correlation_result(primary_result)
                print(f"[TimeWindowResultsView] Successfully loaded execution {execution_id}")
                
        except Exception as e:
            print(f"[TimeWindowResultsView] Error loading execution {execution_id}: {e}")
            import traceback
            traceback.print_exc()
    
    def _group_matches_into_windows(self, matches: List, window_size_minutes: int, progress=None) -> List[Dict]:
        """Group matches into time windows of specified size."""
        if not matches:
            return []
        
        # Parse timestamps and find range
        window_map = defaultdict(lambda: {'identities': defaultdict(list), 'start_time': None, 'end_time': None})
        
        for match in matches:
            # Parse timestamp
            ts_str = match.timestamp
            try:
                if isinstance(ts_str, str):
                    # Try multiple formats
                    for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S.%f']:
                        try:
                            ts = datetime.strptime(ts_str[:19], fmt[:19])
                            break
                        except:
                            continue
                    else:
                        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                elif isinstance(ts_str, datetime):
                    ts = ts_str
                else:
                    continue
            except:
                continue
            
            # Calculate window start (round down to window boundary)
            window_delta = timedelta(minutes=window_size_minutes)
            epoch = datetime(2000, 1, 1)
            minutes_since_epoch = int((ts - epoch).total_seconds() / 60)
            window_start_minutes = (minutes_since_epoch // window_size_minutes) * window_size_minutes
            window_start = epoch + timedelta(minutes=window_start_minutes)
            window_end = window_start + window_delta
            
            window_key = window_start.isoformat()
            
            # Store window boundaries
            if window_map[window_key]['start_time'] is None:
                window_map[window_key]['start_time'] = window_start
                window_map[window_key]['end_time'] = window_end
            
            # Group by identity (normalized application name)
            identity_name = match.matched_application or "Unknown"
            window_map[window_key]['identities'][identity_name].append(match)
        
        # Convert to list format
        windows = []
        for window_key in sorted(window_map.keys()):
            window_data = window_map[window_key]
            
            # Convert identities dict to list
            identities_list = []
            for identity_name, identity_matches in window_data['identities'].items():
                # Group by original filename (sub-identities)
                sub_identities_map = defaultdict(list)
                for match in identity_matches:
                    # Try to extract original filename
                    original_name = identity_name
                    for fid, data in match.feather_records.items():
                        if isinstance(data, dict):
                            for field in ['name', 'filename', 'file_name', 'executable_name']:
                                if field in data and data[field]:
                                    original_name = str(data[field])
                                    break
                            if original_name != identity_name:
                                break
                    
                    sub_identities_map[original_name].append(match)
                
                # Build sub-identities list
                sub_identities = []
                for original_name, sub_matches in sub_identities_map.items():
                    sub_identities.append({
                        'original_name': original_name,
                        'matches': sub_matches,
                        'feathers_found': list(set(fid for m in sub_matches for fid in m.feather_records.keys()))
                    })
                
                identities_list.append({
                    'identity_name': identity_name,
                    'sub_identities': sub_identities,
                    'total_matches': len(identity_matches),
                    'feathers_found': list(set(fid for m in identity_matches for fid in m.feather_records.keys()))
                })
            
            windows.append({
                'start_time': window_data['start_time'],
                'end_time': window_data['end_time'],
                'identities': identities_list,
                'total_records': sum(len(id['sub_identities']) for id in identities_list),
                'status': 'Active' if identities_list else 'Empty'
            })
        
        return windows

    def load_results(self, results: Dict[str, Any] = None, output_dir: str = None, db_path: str = None):
        """
        Load time window results with pagination.
        
        Args:
            results: Results dictionary (if already loaded)
            output_dir: Output directory path (for loading from files)
            db_path: Database path (for loading from database)
        """
        # If output_dir is provided, try to load from database first
        if output_dir and not results:
            from pathlib import Path
            
            # Try to load from database if available
            if db_path:
                self.database_path = db_path
            else:
                # Check for database in output directory
                db_file = Path(output_dir) / "correlation_results.db"
                if db_file.exists():
                    self.database_path = str(db_file)
            
            if self.database_path:
                try:
                    from ..engine.database_persistence import ResultsDatabase
                    
                    print(f"[TimeWindowResultsView] Loading from database: {self.database_path}")
                    
                    with ResultsDatabase(self.database_path) as db:
                        # Get the latest execution
                        latest_execution_id = db.get_latest_execution_id()
                        
                        if latest_execution_id:
                            print(f"[TimeWindowResultsView] Loading latest execution: {latest_execution_id}")
                            self.load_results_from_execution(latest_execution_id)
                            return
                        else:
                            print("[TimeWindowResultsView] No executions found in database")
                            
                except Exception as e:
                    print(f"[TimeWindowResultsView] Error loading from database: {e}")
                    import traceback
                    traceback.print_exc()
        
        # If results dict is not provided, create empty results
        if not results:
            results = {
                'time_windows': [],
                'statistics': {
                    'total_windows': 0,
                    'windows_with_data': 0,
                    'empty_windows_skipped': 0,
                    'total_identities': 0,
                    'total_records': 0,
                    'execution_time': 0,
                    'feathers_used': 0
                },
                'wing_name': 'Unknown',
                'feather_metadata': {},
                'original_window_size': 5,
                'viewing_window_size': 5
            }
        
        self.current_results = results
        self.time_windows = results.get('time_windows', [])
        self.filtered_windows = self.time_windows.copy()
        self.current_page = 0
        
        # Update window size display
        self.original_window_size_minutes = results.get('original_window_size', 180)
        self.viewing_window_size_minutes = results.get('viewing_window_size', 180)
        
        # Initialize time range filter with data range
        self._initialize_time_range()
        
        self._update_summary(results)
        self._update_feather_filter(results)
        self._populate_current_page()
        self._update_stats(results)
    
    def _update_summary(self, results: Dict):
        """Update summary labels with cancelled indicator if applicable."""
        stats = results.get('statistics', {})
        
        # Check if execution was cancelled
        status = results.get('status', 'Completed')
        is_cancelled = status == "Cancelled"
        
        total_windows = stats.get('total_windows', len(self.time_windows))
        windows_with_data = stats.get('windows_with_data', 0)
        empty_skipped = stats.get('empty_windows_skipped', 0)
        
        # Update windows label with cancelled indicator
        if is_cancelled:
            self.windows_lbl.setText(f"⚠️ {total_windows:,} ({windows_with_data}/{empty_skipped})")
            self.windows_lbl.setStyleSheet("color: #FF9800; font-weight: bold; font-size: 8pt;")
            tooltip_text = (
                f"⚠️ EXECUTION CANCELLED\n"
                f"Showing partial results\n\n"
                f"Total Windows: {total_windows:,}\n"
                f"With Data: {windows_with_data:,}\n"
                f"Empty (Skipped): {empty_skipped:,}\n"
                f"Scanned: {self.original_window_size_minutes} min\n"
                f"Viewing: {self.viewing_window_size_minutes} min"
            )
        else:
            self.windows_lbl.setText(f"{total_windows:,} ({windows_with_data}/{empty_skipped})")
            self.windows_lbl.setStyleSheet("color: #2196F3; font-weight: bold; font-size: 8pt;")
            tooltip_text = (
                f"Windows\n\n"
                f"Total: {total_windows:,}\n"
                f"With Data: {windows_with_data:,}\n"
                f"Empty (Skipped): {empty_skipped:,}\n"
                f"Scanned: {self.original_window_size_minutes} min\n"
                f"Viewing: {self.viewing_window_size_minutes} min"
            )
        
        self.windows_lbl.setToolTip(tooltip_text)
        
        self.identities_lbl.setText(f"{stats.get('total_identities', 0):,}")
        self.records_lbl.setText(f"{stats.get('total_records', 0):,}")
        self.time_lbl.setText(f"{stats.get('execution_time', 0):.1f}s")
        
        # Show feathers used
        feather_metadata = results.get('feather_metadata', {})
        feathers_used = stats.get('feathers_used', len(feather_metadata))
        if feather_metadata:
            tooltip_lines = ["Feathers\n"]
            for fid, meta in sorted(feather_metadata.items()):
                if isinstance(meta, dict):
                    records = meta.get('records_loaded', meta.get('records', 0))
                    tooltip_lines.append(f"  {fid}: {records:,} records")
            self.feathers_used_lbl.setToolTip("\n".join(tooltip_lines))
        else:
            self.feathers_used_lbl.setToolTip("Feathers")
        
        self.feathers_used_lbl.setText(f"{feathers_used}")
    
    def _update_feather_filter(self, results: Dict):
        """Update feather filter dropdown."""
        self.feather_filter.clear()
        self.feather_filter.addItem("All")
        
        feathers = set()
        for window in self.time_windows:
            for identity in window.get('identities', []):
                for feather in identity.get('feathers_found', []):
                    # Extract base feather name (remove _number suffix)
                    base_name = feather.rsplit('_', 1)[0] if '_' in feather else feather
                    feathers.add(base_name)
        
        for f in sorted(feathers):
            self.feather_filter.addItem(f)
    
    def _initialize_time_range(self):
        """Initialize time range filter with the full data range."""
        if not self.time_windows:
            # Set default range if no data
            default_time = QDateTime.currentDateTime()
            self.time_start_edit.setDateTime(default_time.addDays(-7))
            self.time_end_edit.setDateTime(default_time)
            return
        
        # Find min and max times from all windows
        min_time = None
        max_time = None
        
        for window in self.time_windows:
            start_time = window.get('start_time')
            end_time = window.get('end_time')
            
            if isinstance(start_time, datetime):
                if min_time is None or start_time < min_time:
                    min_time = start_time
            
            if isinstance(end_time, datetime):
                if max_time is None or end_time > max_time:
                    max_time = end_time
        
        # Set the time range controls
        if min_time and max_time:
            self.time_start_edit.setDateTime(QDateTime(min_time))
            self.time_end_edit.setDateTime(QDateTime(max_time))
        else:
            # Fallback to current time if no valid times found
            default_time = QDateTime.currentDateTime()
            self.time_start_edit.setDateTime(default_time.addDays(-7))
            self.time_end_edit.setDateTime(default_time)
    
    def _populate_current_page(self):
        """Populate tree with current page of time windows."""
        total = len(self.filtered_windows)
        total_pages = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        
        start = self.current_page * self.PAGE_SIZE
        end = min(start + self.PAGE_SIZE, total)
        
        page_windows = self.filtered_windows[start:end]
        self._populate_tree(page_windows)
        
        # Update pagination controls
        self.page_lbl.setText(f"Page {self.current_page + 1}/{total_pages} ({total} total)")
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(self.current_page < total_pages - 1)
    
    def _populate_tree(self, windows: List[Dict]):
        """Populate tree with given time windows."""
        self.results_tree.clear()
        
        if not windows:
            empty_item = QTreeWidgetItem(["No time windows found", "", "", "", "", ""])
            empty_item.setForeground(0, QBrush(QColor("#888888")))
            empty_item.setFont(0, QFont("Segoe UI", 9, QFont.Normal))
            self.results_tree.addTopLevelItem(empty_item)
            return
        
        for window in windows:
            item = self._create_window_item(window)
            self.results_tree.addTopLevelItem(item)
        
        # Expand first 3 windows
        for i in range(min(3, self.results_tree.topLevelItemCount())):
            self.results_tree.topLevelItem(i).setExpanded(True)

    def _create_window_item(self, window: Dict) -> QTreeWidgetItem:
        """Create time window tree item (Level 1) with visual indicators."""
        start_time = window.get('start_time')
        end_time = window.get('end_time')
        identities = window.get('identities', [])
        total_records = window.get('total_records', 0)
        status = window.get('status', 'Unknown')
        
        # Format time display
        if isinstance(start_time, datetime):
            start_str = start_time.strftime('%Y-%m-%d %H:%M')
            end_str = end_time.strftime('%H:%M') if isinstance(end_time, datetime) else ''
        else:
            start_str = str(start_time)[:16] if start_time else ''
            end_str = str(end_time)[11:16] if end_time else ''
        
        time_display = f"{start_str} - {end_str}"
        identity_count = len(identities)
        
        # Calculate average score for window
        avg_score = self._calculate_window_score(window)
        score_str = f"{avg_score:.2f}" if avg_score > 0 else "-"
        
        # Collect all feathers in this window
        feathers = set()
        for identity in identities:
            feathers.update(identity.get('feathers_found', []))
        feather_str = ", ".join(sorted(feathers)[:2]) + ("..." if len(feathers) > 2 else "")
        
        # Determine window type and visual indicator
        if identity_count == 0:
            # Empty window (skipped)
            icon = "⚪"  # White circle for empty
            window_type = "Empty"
            color = QColor("#666666")  # Gray
            tooltip = "Empty window - no activity detected (skipped during processing)"
        elif identity_count == 1:
            # Single identity window (isolated activity)
            icon = "🔵"  # Blue circle for single identity
            window_type = "Isolated"
            color = QColor("#FF9800")  # Orange
            tooltip = "Single identity window - isolated activity with no temporal correlation opportunities"
        else:
            # Multi-identity window (correlation opportunity)
            icon = "🟢"  # Green circle for correlation opportunity
            window_type = "Correlation"
            color = QColor("#4CAF50")  # Green
            tooltip = f"Multi-identity window - {identity_count} identities active simultaneously (correlation opportunity)"
        
        # Window item with visual indicator
        item = QTreeWidgetItem([
            f"{icon} {time_display} ({identity_count} identities, {total_records} records) [{window_type}]",
            feather_str,
            start_str,
            score_str,
            str(total_records),
            status
        ])
        item.setFont(0, QFont("Segoe UI", 9, QFont.Bold))
        item.setForeground(0, QBrush(color))
        item.setToolTip(0, tooltip)
        
        # Color score
        if avg_score >= 0.7:
            item.setForeground(3, QBrush(QColor("#4CAF50")))
        elif avg_score >= 0.4:
            item.setForeground(3, QBrush(QColor("#FF9800")))
        elif avg_score > 0:
            item.setForeground(3, QBrush(QColor("#F44336")))
        
        item.setData(0, Qt.UserRole, {'type': 'window', 'data': window, 'window_type': window_type})
        
        # Add identities under window
        for identity in identities:
            identity_item = self._create_identity_item(identity, window_type)
            item.addChild(identity_item)
        
        return item
    
    def _calculate_window_score(self, window: Dict) -> float:
        """Calculate average weighted score for a time window."""
        scores = []
        for identity in window.get('identities', []):
            for sub_identity in identity.get('sub_identities', []):
                for match in sub_identity.get('matches', []):
                    weighted_score = getattr(match, 'weighted_score', None)
                    if isinstance(weighted_score, dict):
                        score = weighted_score.get('score', 0)
                        if score > 0:
                            scores.append(score)
        
        return sum(scores) / len(scores) if scores else 0.0
    
    def _create_identity_item(self, identity: Dict, window_type: str = "Unknown") -> QTreeWidgetItem:
        """Create identity tree item (Level 2) with temporal relationship indicators."""
        identity_name = identity.get('identity_name', 'Unknown')
        sub_identities = identity.get('sub_identities', [])
        total_matches = identity.get('total_matches', 0)
        feathers = identity.get('feathers_found', [])
        
        feather_str = ", ".join(sorted(feathers)[:2]) + ("..." if len(feathers) > 2 else "")
        
        # Calculate average score for identity
        scores = []
        for sub in sub_identities:
            for match in sub.get('matches', []):
                weighted_score = getattr(match, 'weighted_score', None)
                if isinstance(weighted_score, dict) and weighted_score.get('score', 0) > 0:
                    scores.append(weighted_score.get('score', 0))
        
        avg_score = sum(scores) / len(scores) if scores else 0.0
        score_str = f"{avg_score:.2f}" if avg_score > 0 else "-"
        
        # Add temporal relationship indicator
        if window_type == "Correlation":
            # This identity is part of a correlation opportunity
            temporal_indicator = "🔗"  # Link icon for correlation
            tooltip = f"{identity_name} - Part of temporal correlation (multiple identities active in same window)"
        elif window_type == "Isolated":
            # This identity is isolated in its window
            temporal_indicator = "🔸"  # Orange diamond for isolated
            tooltip = f"{identity_name} - Isolated activity (only identity in this window)"
        else:
            temporal_indicator = "🔷"  # Blue diamond default
            tooltip = identity_name
        
        # Identity item with temporal indicator
        item = QTreeWidgetItem([
            f"{temporal_indicator} {identity_name}" + (f" ({len(sub_identities)} variants)" if len(sub_identities) > 1 else ""),
            feather_str,
            "",
            score_str,
            str(total_matches),
            f"{len(feathers)} feathers"
        ])
        item.setFont(0, QFont("Segoe UI", 8, QFont.Bold))
        
        # Color based on temporal relationship
        if window_type == "Correlation":
            item.setForeground(0, QBrush(QColor("#4CAF50")))  # Green for correlation
        elif window_type == "Isolated":
            item.setForeground(0, QBrush(QColor("#FF9800")))  # Orange for isolated
        else:
            item.setForeground(0, QBrush(QColor("#2196F3")))  # Blue default
        
        item.setToolTip(0, tooltip)
        
        # Color score
        if avg_score >= 0.7:
            item.setForeground(3, QBrush(QColor("#4CAF50")))
        elif avg_score >= 0.4:
            item.setForeground(3, QBrush(QColor("#FF9800")))
        elif avg_score > 0:
            item.setForeground(3, QBrush(QColor("#F44336")))
        
        item.setData(0, Qt.UserRole, {'type': 'identity', 'data': identity, 'window_type': window_type})
        
        # Add sub-identities
        for sub in sub_identities:
            sub_item = self._create_sub_identity_item(sub)
            item.addChild(sub_item)
        
        return item
    
    def _create_sub_identity_item(self, sub_identity: Dict) -> QTreeWidgetItem:
        """Create sub-identity tree item (Level 3)."""
        original_name = sub_identity.get('original_name', 'Unknown')
        matches = sub_identity.get('matches', [])
        feathers = sub_identity.get('feathers_found', [])
        
        feather_str = ", ".join(sorted(feathers)[:2]) + ("..." if len(feathers) > 2 else "")
        
        # Calculate average score
        scores = []
        for match in matches:
            weighted_score = getattr(match, 'weighted_score', None)
            if isinstance(weighted_score, dict) and weighted_score.get('score', 0) > 0:
                scores.append(weighted_score.get('score', 0))
        
        avg_score = sum(scores) / len(scores) if scores else 0.0
        score_str = f"{avg_score:.2f}" if avg_score > 0 else "-"
        
        # Sub-identity item with folder icon
        item = QTreeWidgetItem([
            f"📁 {original_name}",
            feather_str,
            "",
            score_str,
            str(len(matches)),
            f"{len(matches)} matches"
        ])
        item.setFont(0, QFont("Segoe UI", 8))
        item.setForeground(0, QBrush(QColor("#FF9800")))  # Orange for sub-identity
        
        # Color score
        if avg_score >= 0.7:
            item.setForeground(3, QBrush(QColor("#4CAF50")))
        elif avg_score >= 0.4:
            item.setForeground(3, QBrush(QColor("#FF9800")))
        elif avg_score > 0:
            item.setForeground(3, QBrush(QColor("#F44336")))
        
        item.setData(0, Qt.UserRole, {'type': 'sub_identity', 'data': sub_identity})
        
        # Add evidence records (matches)
        for match in matches:
            evidence_item = self._create_evidence_item(match)
            item.addChild(evidence_item)
        
        return item
    
    def _create_evidence_item(self, match) -> QTreeWidgetItem:
        """Create evidence tree item (Level 4)."""
        ts = match.timestamp
        if isinstance(ts, str) and len(ts) > 11:
            ts = ts[11:19]
        
        # Get feathers involved
        feathers = list(match.feather_records.keys())
        feather_str = ", ".join(feathers[:2]) + ("..." if len(feathers) > 2 else "")
        
        # Get score
        weighted_score = getattr(match, 'weighted_score', None)
        if isinstance(weighted_score, dict):
            score = weighted_score.get('score', 0)
            score_str = f"{score:.2f}"
        else:
            score = 0
            score_str = "-"
        
        # Evidence item with document icon
        item = QTreeWidgetItem([
            f"📄 Evidence",
            feather_str,
            ts,
            score_str,
            str(len(feathers)),
            match.anchor_artifact_type
        ])
        item.setForeground(0, QBrush(QColor("#4CAF50")))  # Green for evidence
        
        # Color score
        if score >= 0.7:
            item.setForeground(3, QBrush(QColor("#4CAF50")))
        elif score >= 0.4:
            item.setForeground(3, QBrush(QColor("#FF9800")))
        elif score > 0:
            item.setForeground(3, QBrush(QColor("#F44336")))
        
        item.setData(0, Qt.UserRole, {'type': 'evidence', 'data': match})
        
        return item

    def _on_window_size_changed(self, text: str):
        """Handle window size combo box change."""
        if text == "Custom":
            self.custom_window_spin.setVisible(True)
            self._regroup_windows(self.custom_window_spin.value())
        else:
            self.custom_window_spin.setVisible(False)
            # Extract minutes from text (e.g., "5 min" -> 5)
            try:
                minutes = int(text.split()[0])
                self._regroup_windows(minutes)
            except:
                pass
    
    def _on_custom_window_changed(self, value: int):
        """Handle custom window size spinbox change."""
        if self.window_size_combo.currentText() == "Custom":
            self._regroup_windows(value)
    
    def _regroup_windows(self, new_window_size_minutes: int):
        """Dynamically re-group matches into new time windows."""
        if not self.all_matches:
            return
        
        print(f"[TimeWindowResultsView] Re-grouping {len(self.all_matches)} matches into {new_window_size_minutes} min windows")
        
        # Update viewing window size
        self.viewing_window_size_minutes = new_window_size_minutes
        
        # Re-group matches
        self.time_windows = self._group_matches_into_windows(self.all_matches, new_window_size_minutes)
        self.filtered_windows = self.time_windows.copy()
        self.current_page = 0
        
        # Update display
        if self.current_results:
            self.current_results['time_windows'] = self.time_windows
            self.current_results['viewing_window_size'] = new_window_size_minutes
            self.current_results['statistics']['total_windows'] = len(self.time_windows)
            self.current_results['statistics']['windows_with_data'] = sum(1 for w in self.time_windows if w['identities'])
            self.current_results['statistics']['empty_windows_skipped'] = sum(1 for w in self.time_windows if not w['identities'])
            
            self._update_summary(self.current_results)
            self._populate_current_page()
            self._update_stats(self.current_results)
        
        print(f"[TimeWindowResultsView] Re-grouped into {len(self.time_windows)} windows")
    
    def _apply_filters(self):
        """Apply filters with pagination."""
        text = self.identity_filter.text().lower()
        feather = self.feather_filter.currentText()
        status = self.status_filter.currentText()
        
        # Get time range filter values
        time_start = self.time_start_edit.dateTime().toPyDateTime()
        time_end = self.time_end_edit.dateTime().toPyDateTime()
        
        filtered = []
        for window in self.time_windows:
            # Status filter
            if status == "With Data" and not window.get('identities'):
                continue
            if status == "Empty" and window.get('identities'):
                continue
            
            # Time range filter
            window_start = window.get('start_time')
            window_end = window.get('end_time')
            if isinstance(window_start, datetime) and isinstance(window_end, datetime):
                # Check if window overlaps with selected time range
                if window_end < time_start or window_start > time_end:
                    continue
            
            # Identity name filter
            if text:
                has_match = False
                for identity in window.get('identities', []):
                    if text in identity.get('identity_name', '').lower():
                        has_match = True
                        break
                if not has_match:
                    continue
            
            # Feather filter
            if feather != "All":
                has_feather = False
                for identity in window.get('identities', []):
                    for found_feather in identity.get('feathers_found', []):
                        # Match by base name (remove _number suffix)
                        base_name = found_feather.rsplit('_', 1)[0] if '_' in found_feather else found_feather
                        if feather == base_name:
                            has_feather = True
                            break
                    if has_feather:
                        break
                if not has_feather:
                    continue
            
            filtered.append(window)
        
        self.filtered_windows = filtered
        self.current_page = 0
        self._populate_current_page()
    
    def _reset_filters(self):
        """Reset all filters."""
        self.identity_filter.clear()
        self.feather_filter.setCurrentIndex(0)
        self.status_filter.setCurrentIndex(0)
        
        # Reset time range to full data range
        if self.time_windows:
            self._initialize_time_range()
        
        self.filtered_windows = self.time_windows.copy()
        self.current_page = 0
        self._populate_current_page()
    
    def _prev_page(self):
        """Go to previous page."""
        if self.current_page > 0:
            self.current_page -= 1
            self._populate_current_page()
    
    def _next_page(self):
        """Go to next page."""
        total_pages = max(1, (len(self.filtered_windows) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self._populate_current_page()
    
    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle item click."""
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        
        item_type = data.get('type')
        item_data = data.get('data', {})
        
        # Emit signal for external handlers
        self.match_selected.emit({'type': item_type, 'data': item_data})
    
    def _on_double_click(self, item: QTreeWidgetItem, column: int):
        """Handle double-click to show details with feather-specific handling."""
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        
        item_type = data.get('type')
        item_data = data.get('data', {})
        
        # Check if user clicked on the Feathers column (column 1)
        if column == 1 and item_type in ['identity', 'sub_identity']:
            # Extract feather name from the clicked column
            feather_text = item.text(1)
            if feather_text and feather_text != '-':
                # Parse feather name (remove "..." if present)
                feather_names = [f.strip() for f in feather_text.replace('...', '').split(',')]
                if feather_names and feather_names[0]:
                    # Open dialog with specific feather tab active
                    dialog = TimeWindowDetailDialog(item_type, item_data, self, feather_id=feather_names[0])
                    dialog.exec_()
                    return
        
        # Check if user clicked on a window and wants to see feather data across all identities
        # This would require adding a context menu or special handling
        
        # Default: open dialog normally
        dialog = TimeWindowDetailDialog(item_type, item_data, self)
        dialog.exec_()
    
    def _on_tree_context_menu(self, position):
        """Handle right-click context menu on tree items."""
        from PyQt5.QtWidgets import QMenu, QAction
        
        item = self.results_tree.itemAt(position)
        if not item:
            return
        
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        
        item_type = data.get('type')
        item_data = data.get('data', {})
        
        menu = QMenu()
        
        # For window items, offer to show feather data across all identities
        if item_type == 'window':
            # Get all feathers in this window
            identities = item_data.get('identities', [])
            all_feathers = set()
            for identity in identities:
                all_feathers.update(identity.get('feathers_found', []))
            
            if all_feathers:
                feather_menu = menu.addMenu("View Feather Data")
                for feather_id in sorted(all_feathers):
                    action = QAction(f"{feather_id}", self)
                    action.triggered.connect(lambda checked, fid=feather_id, window=item_data: 
                                           self._show_feather_across_identities(fid, window))
                    feather_menu.addAction(action)
        
        # For identity/sub-identity items, offer to view specific feather tabs
        elif item_type in ['identity', 'sub_identity']:
            feathers = item_data.get('feathers_found', [])
            if feathers:
                feather_menu = menu.addMenu("Jump to Feather Tab")
                for feather_id in sorted(feathers):
                    action = QAction(f"{feather_id}", self)
                    action.triggered.connect(lambda checked, fid=feather_id, itype=item_type, idata=item_data: 
                                           self._open_dialog_with_feather(itype, idata, fid))
                    feather_menu.addAction(action)
        
        if not menu.isEmpty():
            menu.exec_(self.results_tree.viewport().mapToGlobal(position))
    
    def _show_feather_across_identities(self, feather_id: str, window_data: Dict):
        """Show all records from a specific feather across all identities in a time window."""
        # Collect all records from this feather across all identities
        feather_records = []
        
        identities = window_data.get('identities', [])
        for identity in identities:
            identity_name = identity.get('identity_name', 'Unknown')
            for sub in identity.get('sub_identities', []):
                for match in sub.get('matches', []):
                    if hasattr(match, 'feather_records') and feather_id in match.feather_records:
                        feather_records.append({
                            'identity': identity_name,
                            'timestamp': match.timestamp,
                            'artifact': getattr(match, 'anchor_artifact_type', 'Unknown'),
                            'data': match.feather_records[feather_id]
                        })
        
        if not feather_records:
            QMessageBox.information(self, "No Data", f"No records found for feather '{feather_id}' in this time window.")
            return
        
        # Show dialog with feather data
        dialog_data = {
            'feather_id': feather_id,
            'records': feather_records
        }
        dialog = TimeWindowDetailDialog('feather', dialog_data, self)
        dialog.exec_()
    
    def _open_dialog_with_feather(self, item_type: str, item_data: Dict, feather_id: str):
        """Open detail dialog with specific feather tab active."""
        dialog = TimeWindowDetailDialog(item_type, item_data, self, feather_id=feather_id)
        dialog.exec_()
    
    def _show_legend(self):
        """Show visual indicators legend dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Visual Indicators Legend")
        dialog.setMinimumSize(500, 400)
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)
        
        # Title
        title = QLabel("<b>Time Window Visual Indicators</b>")
        title.setStyleSheet("font-size: 10pt; color: #2196F3;")
        layout.addWidget(title)
        
        # Legend content
        text = QTextEdit()
        text.setReadOnly(True)
        text.setStyleSheet("font-size: 8pt; background-color: #1a1a2e; border: 1px solid #333;")
        
        legend_text = """
TIME WINDOW INDICATORS:
═══════════════════════════════════════════════════════════

🟢 Multi-Identity Window [Correlation]
   • Multiple identities active simultaneously in the same time window
   • Represents temporal correlation opportunities
   • Green color indicates high forensic value
   • Example: chrome.exe, notepad.exe, and cmd.exe all active at 10:00-10:05

🔵 Single-Identity Window [Isolated]
   • Only one identity active in the time window
   • Isolated activity with no temporal correlation opportunities
   • Orange color indicates standalone activity
   • Example: Only firefox.exe active at 10:05-10:10

⚪ Empty Window [Skipped]
   • No activity detected in this time window
   • Skipped during processing for efficiency
   • Gray color indicates no data
   • Example: No forensic artifacts found between 02:00-02:05


IDENTITY INDICATORS:
═══════════════════════════════════════════════════════════

🔗 Correlated Identity
   • Identity that appears in a multi-identity window
   • Part of temporal correlation with other identities
   • Green color highlights correlation opportunity
   • Shows which other identities were active simultaneously

🔸 Isolated Identity
   • Identity that appears alone in its time window
   • No temporal correlation with other identities
   • Orange color indicates isolated activity
   • Useful for identifying standalone events


TEMPORAL RELATIONSHIP ANALYSIS:
═══════════════════════════════════════════════════════════

The viewer organizes forensic artifacts by time windows to help you:

1. Identify Correlation Opportunities
   • Find when multiple applications/processes were active together
   • Discover temporal relationships between artifacts
   • Understand the sequence of events

2. Detect Isolated Activity
   • Identify standalone events that occurred in isolation
   • Find time periods with single-application activity
   • Spot unusual isolated behavior

3. Optimize Analysis
   • Empty windows are automatically skipped
   • Focus on time periods with actual activity
   • Efficient processing of large datasets


FEATHER CONTRIBUTION:
═══════════════════════════════════════════════════════════

Each identity shows which feathers (artifact types) contributed evidence:
• Prefetch: Application execution evidence
• ShimCache: File modification/access evidence
• AmCache: Installation and execution evidence
• Registry: System configuration changes
• And more...

Multiple feathers for the same identity in the same window provide
stronger evidence and better temporal correlation.
"""
        
        text.setPlainText(legend_text)
        layout.addWidget(text)
        
        # Close button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        
        dialog.exec_()

    def _update_stats(self, results: Dict):
        """Update statistics tables."""
        # 1. Time Windows Table - Top 10 most active windows with visual indicators
        active_windows = [w for w in self.time_windows if w.get('identities')]
        active_windows.sort(key=lambda w: w.get('total_records', 0), reverse=True)
        
        self.windows_table.setRowCount(min(10, len(active_windows)))
        for row, window in enumerate(active_windows[:10]):
            start_time = window.get('start_time')
            end_time = window.get('end_time')
            if isinstance(start_time, datetime):
                time_str = f"{start_time.strftime('%m-%d %H:%M')}-{end_time.strftime('%H:%M')}"
            else:
                time_str = str(start_time)[:16] if start_time else ''
            
            identity_count = len(window.get('identities', []))
            
            # Add visual indicator
            if identity_count > 1:
                indicator = "🟢"
                window_type = "Correlation"
            elif identity_count == 1:
                indicator = "🔵"
                window_type = "Isolated"
            else:
                indicator = "⚪"
                window_type = "Empty"
            
            time_item = QTableWidgetItem(f"{indicator} {time_str}")
            time_item.setToolTip(f"{window_type} window - {identity_count} identities")
            self.windows_table.setItem(row, 0, time_item)
            
            self.windows_table.setItem(row, 1, QTableWidgetItem(str(identity_count)))
            self.windows_table.setItem(row, 2, QTableWidgetItem(str(window.get('total_records', 0))))
            
            status_item = QTableWidgetItem(window_type)
            if window_type == "Correlation":
                status_item.setForeground(QBrush(QColor("#4CAF50")))
            elif window_type == "Isolated":
                status_item.setForeground(QBrush(QColor("#FF9800")))
            self.windows_table.setItem(row, 3, status_item)
        
        # 2. Feather Contribution Table
        feather_stats = defaultdict(lambda: {'windows': set(), 'records': 0, 'identities': set()})
        for window in self.time_windows:
            for identity in window.get('identities', []):
                for feather in identity.get('feathers_found', []):
                    # Extract base feather name (remove _number suffix)
                    base_name = feather.rsplit('_', 1)[0] if '_' in feather else feather
                    feather_stats[base_name]['windows'].add(id(window))
                    feather_stats[base_name]['records'] += identity.get('total_matches', 0)
                    feather_stats[base_name]['identities'].add(identity.get('identity_name'))
        
        self.feather_table.setRowCount(len(feather_stats))
        for row, (feather, stats) in enumerate(sorted(feather_stats.items(), 
                                                       key=lambda x: x[1]['records'], 
                                                       reverse=True)):
            self.feather_table.setItem(row, 0, QTableWidgetItem(feather))
            self.feather_table.setItem(row, 1, QTableWidgetItem(str(len(stats['windows']))))
            self.feather_table.setItem(row, 2, QTableWidgetItem(str(stats['records'])))
            self.feather_table.setItem(row, 3, QTableWidgetItem(str(len(stats['identities']))))
        
        # 3. Identity Activity Table
        identity_stats = defaultdict(lambda: {'windows': 0, 'first_seen': None, 'last_seen': None})
        for window in self.time_windows:
            window_time = window.get('start_time')
            for identity in window.get('identities', []):
                identity_name = identity.get('identity_name')
                identity_stats[identity_name]['windows'] += 1
                
                if identity_stats[identity_name]['first_seen'] is None:
                    identity_stats[identity_name]['first_seen'] = window_time
                else:
                    if window_time < identity_stats[identity_name]['first_seen']:
                        identity_stats[identity_name]['first_seen'] = window_time
                
                if identity_stats[identity_name]['last_seen'] is None:
                    identity_stats[identity_name]['last_seen'] = window_time
                else:
                    if window_time > identity_stats[identity_name]['last_seen']:
                        identity_stats[identity_name]['last_seen'] = window_time
        
        self.identity_table.setRowCount(min(10, len(identity_stats)))
        for row, (identity, stats) in enumerate(sorted(identity_stats.items(), 
                                                        key=lambda x: x[1]['windows'], 
                                                        reverse=True)[:10]):
            self.identity_table.setItem(row, 0, QTableWidgetItem(identity[:20]))
            self.identity_table.setItem(row, 1, QTableWidgetItem(str(stats['windows'])))
            
            first_seen = stats['first_seen']
            last_seen = stats['last_seen']
            if isinstance(first_seen, datetime):
                first_str = first_seen.strftime('%m-%d %H:%M')
                last_str = last_seen.strftime('%m-%d %H:%M')
            else:
                first_str = str(first_seen)[:11] if first_seen else '-'
                last_str = str(last_seen)[:11] if last_seen else '-'
            
            self.identity_table.setItem(row, 2, QTableWidgetItem(first_str))
            self.identity_table.setItem(row, 3, QTableWidgetItem(last_str))
        
        # 4. Temporal Patterns Table with visual indicators
        multi_identity_windows = sum(1 for w in self.time_windows if len(w.get('identities', [])) > 1)
        single_identity_windows = sum(1 for w in self.time_windows if len(w.get('identities', [])) == 1)
        empty_windows = sum(1 for w in self.time_windows if len(w.get('identities', [])) == 0)
        total = len(self.time_windows)
        
        patterns = [
            ("🟢 Multi-Identity Windows", multi_identity_windows, 
             f"{(multi_identity_windows/total*100):.1f}%" if total > 0 else "0%",
             "Correlation opportunities - multiple identities active simultaneously"),
            ("🔵 Single-Identity Windows", single_identity_windows, 
             f"{(single_identity_windows/total*100):.1f}%" if total > 0 else "0%",
             "Isolated activity - single identity active in window"),
            ("⚪ Empty Windows Skipped", empty_windows, 
             f"{(empty_windows/total*100):.1f}%" if total > 0 else "0%",
             "No activity detected - skipped during processing")
        ]
        
        self.patterns_table.setRowCount(len(patterns))
        for row, (pattern, count, percentage, tooltip) in enumerate(patterns):
            pattern_item = QTableWidgetItem(pattern)
            pattern_item.setToolTip(tooltip)
            self.patterns_table.setItem(row, 0, pattern_item)
            
            count_item = QTableWidgetItem(str(count))
            count_item.setToolTip(tooltip)
            
            # Color code with visual indicators
            if "Multi-Identity" in pattern:
                count_item.setForeground(QBrush(QColor("#4CAF50")))  # Green - correlation opportunities
                pattern_item.setForeground(QBrush(QColor("#4CAF50")))
            elif "Single-Identity" in pattern:
                count_item.setForeground(QBrush(QColor("#FF9800")))  # Orange - isolated activity
                pattern_item.setForeground(QBrush(QColor("#FF9800")))
            elif "Empty" in pattern:
                count_item.setForeground(QBrush(QColor("#888")))  # Gray - skipped
                pattern_item.setForeground(QBrush(QColor("#888")))
            
            self.patterns_table.setItem(row, 1, count_item)
            
            percentage_item = QTableWidgetItem(percentage)
            percentage_item.setToolTip(tooltip)
            self.patterns_table.setItem(row, 2, percentage_item)
        
        # Update scoring indicator
        total_scored = sum(1 for w in self.time_windows 
                          for i in w.get('identities', []) 
                          for s in i.get('sub_identities', []) 
                          for m in s.get('matches', []) 
                          if getattr(m, 'weighted_score', None))
        
        if total_scored > 0:
            self.scoring_enabled = True
            self.scoring_lbl.setText(f"📊 Scoring: On ({total_scored})")
            self.scoring_lbl.setStyleSheet("font-size: 7pt; color: #4CAF50;")
        else:
            self.scoring_enabled = False
            self.scoring_lbl.setText("📊 Scoring: Off")
            self.scoring_lbl.setStyleSheet("font-size: 7pt; color: #888;")


class TimeWindowDetailDialog(QDialog):
    """Detail dialog for time window items with full data display matching IdentityDetailDialog."""
    
    def __init__(self, item_type: str, data: Dict, parent=None, feather_id: str = None):
        super().__init__(parent)
        self.item_type = item_type
        self.data = data
        self.feather_id = feather_id  # For opening specific feather tab
        self.setup_ui()
    
    def setup_ui(self):
        """Setup dialog with same structure as IdentityDetailDialog."""
        # Set window title based on item type
        if self.item_type == 'window':
            start_time = self.data.get('start_time')
            if isinstance(start_time, datetime):
                time_str = start_time.strftime('%Y-%m-%d %H:%M')
            else:
                time_str = str(start_time)[:16] if start_time else 'Unknown'
            self.setWindowTitle(f"Time Window: {time_str}")
        elif self.item_type == 'identity':
            self.setWindowTitle(f"Identity: {self.data.get('identity_name', 'Unknown')}")
        elif self.item_type == 'feather':
            self.setWindowTitle(f"Feather: {self.data.get('feather_id', 'Unknown')}")
        else:
            self.setWindowTitle(f"{self.item_type.capitalize()} Details")
        
        # Use same sizing rules as IdentityDetailDialog (800x600 min, 90% screen max)
        self.setMinimumSize(900, 600)
        
        # Get screen size and set maximum to 90%
        from PyQt5.QtWidgets import QDesktopWidget
        screen = QDesktopWidget().screenGeometry()
        max_width = int(screen.width() * 0.9)
        max_height = int(screen.height() * 0.9)
        self.setMaximumSize(max_width, max_height)
        
        # Set initial size to something reasonable
        self.resize(950, 650)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Only add header for window, feather, and evidence types
        # For identity type, the Summary tab contains all header info
        if self.item_type not in ['identity', 'sub_identity']:
            header = self._create_header()
            layout.addWidget(header)
        
        # Content based on item type
        if self.item_type == 'window':
            content = self._create_window_content()
        elif self.item_type == 'identity':
            content = self._create_identity_content()
        elif self.item_type == 'feather':
            content = self._create_feather_only_content()
        elif self.item_type == 'sub_identity':
            content = self._create_sub_identity_content()
        else:
            content = self._create_evidence_content()
        
        # Ensure content expands to fill available space
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(content, stretch=1)
        
        # Close button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setMinimumWidth(100)
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
    
    def _create_header(self) -> QFrame:
        """Create header with visual indicators."""
        frame = QFrame()
        frame.setMaximumHeight(50)
        frame.setStyleSheet("background-color: #1a1a2e; border: 1px solid #333; padding: 4px;")
        layout = QHBoxLayout(frame)
        
        if self.item_type == 'window':
            start_time = self.data.get('start_time')
            end_time = self.data.get('end_time')
            if isinstance(start_time, datetime):
                time_str = f"{start_time.strftime('%Y-%m-%d %H:%M')} - {end_time.strftime('%H:%M')}"
            else:
                time_str = str(start_time)
            
            identity_count = len(self.data.get('identities', []))
            
            # Add visual indicator for window type
            if identity_count > 1:
                indicator = "🟢 Multi-Identity"
                tooltip = "Correlation window - multiple identities active simultaneously"
            elif identity_count == 1:
                indicator = "🔵 Single-Identity"
                tooltip = "Isolated window - only one identity active"
            else:
                indicator = "⚪ Empty"
                tooltip = "No activity detected"
            
            indicator_lbl = QLabel(indicator)
            indicator_lbl.setToolTip(tooltip)
            indicator_lbl.setStyleSheet("font-weight: bold; font-size: 9pt;")
            layout.addWidget(indicator_lbl)
            
            layout.addWidget(QLabel(f"<b>Time:</b> {time_str}"))
            layout.addWidget(QLabel(f"<b>Identities:</b> {identity_count}"))
            layout.addWidget(QLabel(f"<b>Records:</b> {self.data.get('total_records', 0)}"))
            
        elif self.item_type == 'identity':
            layout.addWidget(QLabel(f"<b>Identity:</b> {self.data.get('identity_name', 'Unknown')}"))
            layout.addWidget(QLabel(f"<b>Matches:</b> {self.data.get('total_matches', 0)}"))
            feathers = self.data.get('feathers_found', [])
            if feathers:
                layout.addWidget(QLabel(f"<b>Feathers:</b> {', '.join(feathers[:3])}{'...' if len(feathers) > 3 else ''}"))
                
        elif self.item_type == 'feather':
            layout.addWidget(QLabel(f"<b>Feather:</b> {self.data.get('feather_id', 'Unknown')}"))
            layout.addWidget(QLabel(f"<b>Records:</b> {len(self.data.get('records', []))}"))
            layout.addWidget(QLabel(f"<b>Identities:</b> {len(set(r.get('identity') for r in self.data.get('records', []) if r.get('identity')))}"))
            
        elif self.item_type == 'sub_identity':
            layout.addWidget(QLabel(f"<b>Original Name:</b> {self.data.get('original_name', 'Unknown')}"))
            layout.addWidget(QLabel(f"<b>Matches:</b> {len(self.data.get('matches', []))}"))
        else:
            layout.addWidget(QLabel(f"<b>Evidence Record</b>"))
        
        layout.addStretch()
        return frame
    
    def _create_window_content(self) -> QWidget:
        """Create window content with temporal relationship visualization."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        text = QTextEdit()
        text.setReadOnly(True)
        
        # Format window data with temporal relationship analysis
        lines = []
        lines.append(f"Time Window Details")
        lines.append(f"=" * 50)
        lines.append(f"Start: {self.data.get('start_time')}")
        lines.append(f"End: {self.data.get('end_time')}")
        lines.append(f"Status: {self.data.get('status')}")
        lines.append(f"Total Records: {self.data.get('total_records')}")
        
        identities = self.data.get('identities', [])
        identity_count = len(identities)
        
        # Temporal relationship analysis
        lines.append(f"\n{'='*50}")
        lines.append(f"TEMPORAL RELATIONSHIP ANALYSIS")
        lines.append(f"{'='*50}")
        
        if identity_count == 0:
            lines.append(f"⚪ Empty Window - No activity detected")
            lines.append(f"   This window was skipped during processing for efficiency.")
        elif identity_count == 1:
            lines.append(f"🔵 Single-Identity Window - Isolated Activity")
            lines.append(f"   Only one identity was active in this time window.")
            lines.append(f"   No temporal correlation opportunities detected.")
        else:
            lines.append(f"🟢 Multi-Identity Window - Correlation Opportunity")
            lines.append(f"   {identity_count} identities were active simultaneously in this window.")
            lines.append(f"   This represents a temporal correlation opportunity where multiple")
            lines.append(f"   applications/processes were running at the same time.")
        
        lines.append(f"\n{'='*50}")
        lines.append(f"Identities in this window:")
        lines.append(f"{'='*50}")
        
        for idx, identity in enumerate(identities, 1):
            lines.append(f"\n{idx}. 🔗 {identity.get('identity_name')}")
            lines.append(f"   Matches: {identity.get('total_matches')}")
            lines.append(f"   Feathers: {', '.join(identity.get('feathers_found', []))}")
            
            # Show temporal relationship with other identities
            if identity_count > 1:
                other_identities = [i.get('identity_name') for i in identities if i != identity]
                lines.append(f"   Temporal Correlation With: {', '.join(other_identities[:3])}")
                if len(other_identities) > 3:
                    lines.append(f"      ... and {len(other_identities) - 3} more")
        
        # Feather contribution analysis
        if identities:
            lines.append(f"\n{'='*50}")
            lines.append(f"Feather Contribution Analysis:")
            lines.append(f"{'='*50}")
            
            feather_identity_map = {}
            for identity in identities:
                for feather in identity.get('feathers_found', []):
                    if feather not in feather_identity_map:
                        feather_identity_map[feather] = []
                    feather_identity_map[feather].append(identity.get('identity_name'))
            
            for feather, identity_names in sorted(feather_identity_map.items()):
                lines.append(f"\n  📊 {feather}:")
                lines.append(f"     Contributed to {len(identity_names)} identities:")
                for name in identity_names:
                    lines.append(f"       • {name}")
        
        text.setPlainText("\n".join(lines))
        layout.addWidget(text)
        
        return widget
    
    def _create_identity_content(self) -> QWidget:
        """Create identity content with Summary tab + per-feather tabs (matching IdentityDetailDialog)."""
        tabs = QTabWidget()
        # Tabs matching the main app tab style
        tabs.setStyleSheet("""
            QTabWidget::pane { 
                border: 1px solid #333; 
                background-color: #1a1a2e;
            }
            QTabBar::tab { 
                font-size: 7pt; 
                padding: 4px 12px; 
                min-width: 80px;
                background-color: #1a1a2e;
                color: #888;
                border: 1px solid #333;
                border-bottom: none;
                margin-right: 1px;
            }
            QTabBar::tab:selected { 
                background-color: #2a3a5e; 
                color: #fff;
                border-top: 2px solid #2196F3;
            }
            QTabBar::tab:hover:!selected { 
                background-color: #252540;
                color: #aaa;
            }
        """)
        
        # Collect all evidence rows grouped by feather
        feather_records = {}  # feather_id -> list of evidence rows
        all_matches = []
        timestamps = []
        
        sub_identities = self.data.get('sub_identities', [])
        if sub_identities:
            for sub in sub_identities:
                for match in sub.get('matches', []):
                    all_matches.append(match)
                    if hasattr(match, 'timestamp'):
                        timestamps.append(match.timestamp)
                    # Extract feather records from match
                    if hasattr(match, 'feather_records'):
                        for fid, data in match.feather_records.items():
                            if fid not in feather_records:
                                feather_records[fid] = []
                            feather_records[fid].append({
                                'feather_id': fid,
                                'timestamp': match.timestamp,
                                'artifact': getattr(match, 'anchor_artifact_type', 'Unknown'),
                                'role': 'primary' if fid == getattr(match, 'anchor_feather_id', None) else 'secondary',
                                'data': data
                            })
        
        # Tab 1: Summary
        summary_tab = self._create_identity_summary_tab(sub_identities, all_matches, timestamps, feather_records)
        tabs.addTab(summary_tab, "📊 Summary")
        
        # Per-feather tabs
        for fid in sorted(feather_records.keys()):
            records = feather_records[fid]
            tab = self._create_feather_tab(fid, records)
            tab_label = f"{fid} ({len(records)})"
            if len(tab_label) > 20:
                tab_label = f"{fid[:15]}... ({len(records)})"
            tabs.addTab(tab, tab_label)
        
        # If a specific feather was requested, open that tab
        if self.feather_id and self.feather_id in feather_records:
            for i in range(tabs.count()):
                if tabs.tabText(i).startswith(self.feather_id):
                    tabs.setCurrentIndex(i)
                    break
        
        return tabs
    
    def _create_identity_summary_tab(self, sub_identities: list, all_matches: list, 
                                     timestamps: list, feather_records: dict) -> QWidget:
        """Create Summary tab for identity in time window."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Identity name header
        name = self.data.get('identity_name', 'Unknown')
        name_lbl = QLabel(f"<h2 style='color: #2196F3;'>{name}</h2>")
        layout.addWidget(name_lbl)
        
        # Statistics frame
        stats_frame = QFrame()
        stats_frame.setStyleSheet("background-color: #1a1a2e; border: 1px solid #333; padding: 8px;")
        stats_layout = QHBoxLayout(stats_frame)
        
        # Variants count
        sub_count = len(sub_identities) if sub_identities else 0
        stats_layout.addWidget(QLabel(f"<b>Variants:</b> {sub_count}"))
        
        # Matches count
        stats_layout.addWidget(QLabel(f"<b>Matches:</b> {len(all_matches)}"))
        
        # Time range
        if timestamps:
            sorted_ts = sorted([t for t in timestamps if t])
            if sorted_ts:
                first = str(sorted_ts[0])[:19]
                last = str(sorted_ts[-1])[:19]
                stats_layout.addWidget(QLabel(f"<b>Time Range:</b> {first} → {last}"))
        
        # Feathers count
        stats_layout.addWidget(QLabel(f"<b>Feathers:</b> {len(feather_records)}"))
        stats_layout.addStretch()
        layout.addWidget(stats_frame)
        
        # Feather contribution table
        feather_group = QGroupBox("Feather Contributions")
        feather_group.setStyleSheet("""
            QGroupBox { 
                font-size: 9pt; font-weight: bold; color: #aaa;
                padding-top: 12px; margin-top: 8px;
                border: 1px solid #333; background-color: #1a1a2e;
            }
            QGroupBox::title { subcontrol-origin: margin; padding: 0 5px; }
        """)
        feather_layout = QVBoxLayout(feather_group)
        
        # Group feather records by base name
        grouped_feather_records = defaultdict(list)
        for fid, records in feather_records.items():
            # Extract base feather name (remove _number suffix)
            base_name = fid.rsplit('_', 1)[0] if '_' in fid else fid
            grouped_feather_records[base_name].extend(records)
        
        feather_table = QTableWidget()
        feather_table.setColumnCount(2)
        feather_table.setHorizontalHeaderLabels(["Feather", "Records"])
        feather_table.setRowCount(len(grouped_feather_records))
        feather_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        feather_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        feather_table.setAlternatingRowColors(True)
        
        for row, (base_name, records) in enumerate(sorted(grouped_feather_records.items(), 
                                                     key=lambda x: len(x[1]), reverse=True)):
            feather_table.setItem(row, 0, QTableWidgetItem(base_name))
            feather_table.setItem(row, 1, QTableWidgetItem(str(len(records))))
        
        feather_layout.addWidget(feather_table)
        layout.addWidget(feather_group)
        
        layout.addStretch()
        return widget
    
    def _create_feather_tab(self, feather_id: str, records: list) -> QWidget:
        """Create tab showing all records from a specific feather with search."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Header
        header = QLabel(f"<b>{feather_id}</b> - {len(records)} records")
        header.setStyleSheet("font-size: 9pt; color: #aaa; padding: 4px;")
        layout.addWidget(header)
        
        # Search box
        search_box = QLineEdit()
        search_box.setPlaceholderText("Search records...")
        search_box.setStyleSheet("padding: 4px; font-size: 8pt;")
        layout.addWidget(search_box)
        
        # Collect all unique keys from all records
        all_keys = set()
        for rec in records:
            data = rec.get('data', {})
            if isinstance(data, dict):
                all_keys.update(data.keys())
        
        # Create table with all fields (timestamp prominently in first column)
        table = QTableWidget()
        cols = ['Timestamp', 'Artifact', 'Role'] + sorted(list(all_keys))
        table.setColumnCount(len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.setRowCount(len(records))
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)  # Enable column sorting
        
        for row, rec in enumerate(records):
            table.setItem(row, 0, QTableWidgetItem(str(rec.get('timestamp', ''))[:19]))
            table.setItem(row, 1, QTableWidgetItem(rec.get('artifact', '')))
            table.setItem(row, 2, QTableWidgetItem(rec.get('role', 'secondary').capitalize()))
            
            data = rec.get('data', {})
            for col, key in enumerate(sorted(list(all_keys)), 3):
                val = str(data.get(key, ''))
                display_val = val[:80] + "..." if len(val) > 80 else val
                item = QTableWidgetItem(display_val)
                item.setToolTip(val)  # Full value in tooltip
                table.setItem(row, col, item)
        
        # Enable column resizing
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        
        # Connect search box to filter function
        def filter_table(search_text):
            search_text = search_text.lower()
            for row in range(table.rowCount()):
                match = False
                if not search_text:
                    match = True
                else:
                    for col in range(table.columnCount()):
                        item = table.item(row, col)
                        if item and search_text in item.text().lower():
                            match = True
                            break
                table.setRowHidden(row, not match)
        
        search_box.textChanged.connect(filter_table)
        
        # Add row selection highlighting
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        
        layout.addWidget(table)
        
        return widget
    
    def _create_sub_identity_content(self) -> QWidget:
        """Create sub-identity content."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        text = QTextEdit()
        text.setReadOnly(True)
        
        lines = []
        lines.append(f"Sub-Identity: {self.data.get('original_name')}")
        lines.append(f"=" * 50)
        lines.append(f"Matches: {len(self.data.get('matches', []))}")
        lines.append(f"Feathers: {', '.join(self.data.get('feathers_found', []))}")
        
        text.setPlainText("\n".join(lines))
        layout.addWidget(text)
        
        return widget
    
    def _create_feather_only_content(self) -> QWidget:
        """Create content for feather-only view (all records from a feather across all identities)."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        
        feather_id = self.data.get('feather_id', 'Unknown')
        records = self.data.get('records', [])
        
        # Header
        header = QLabel(f"<b>{feather_id}</b> - All records across all identities in this time window")
        header.setStyleSheet("font-size: 9pt; color: #aaa; padding: 4px;")
        layout.addWidget(header)
        
        # Search box
        search_box = QLineEdit()
        search_box.setPlaceholderText("Search records...")
        search_box.setStyleSheet("padding: 4px; font-size: 8pt;")
        layout.addWidget(search_box)
        
        # Collect all unique keys from all records
        all_keys = set()
        for rec in records:
            data = rec.get('data', {})
            if isinstance(data, dict):
                all_keys.update(data.keys())
        
        # Create table with Identity column first, then Timestamp prominently
        table = QTableWidget()
        cols = ['Identity', 'Timestamp', 'Artifact'] + sorted(list(all_keys))
        table.setColumnCount(len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.setRowCount(len(records))
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)  # Enable column sorting
        
        for row, rec in enumerate(records):
            # Identity column
            table.setItem(row, 0, QTableWidgetItem(rec.get('identity', 'Unknown')))
            # Timestamp column (prominent)
            table.setItem(row, 1, QTableWidgetItem(str(rec.get('timestamp', ''))[:19]))
            # Artifact column
            table.setItem(row, 2, QTableWidgetItem(rec.get('artifact', 'Unknown')))
            
            data = rec.get('data', {})
            for col, key in enumerate(sorted(list(all_keys)), 3):
                val = str(data.get(key, ''))
                display_val = val[:80] + "..." if len(val) > 80 else val
                item = QTableWidgetItem(display_val)
                item.setToolTip(val)  # Full value in tooltip
                table.setItem(row, col, item)
        
        # Enable column resizing
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        
        # Connect search box to filter function
        def filter_table(search_text):
            search_text = search_text.lower()
            for row in range(table.rowCount()):
                match = False
                if not search_text:
                    match = True
                else:
                    for col in range(table.columnCount()):
                        item = table.item(row, col)
                        if item and search_text in item.text().lower():
                            match = True
                            break
                table.setRowHidden(row, not match)
        
        search_box.textChanged.connect(filter_table)
        
        # Add row selection highlighting
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        
        layout.addWidget(table)
        
        return widget
    
    def _create_evidence_content(self) -> QWidget:
        """Create evidence content."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        text = QTextEdit()
        text.setReadOnly(True)
        
        # Format match data
        match = self.data
        lines = []
        lines.append(f"Evidence Record")
        lines.append(f"=" * 50)
        lines.append(f"Match ID: {getattr(match, 'match_id', 'N/A')}")
        lines.append(f"Timestamp: {getattr(match, 'timestamp', 'N/A')}")
        lines.append(f"Application: {getattr(match, 'matched_application', 'N/A')}")
        lines.append(f"Anchor: {getattr(match, 'anchor_artifact_type', 'N/A')}")
        lines.append(f"\nFeather Records:")
        
        for fid, data in getattr(match, 'feather_records', {}).items():
            lines.append(f"\n  {fid}:")
            if isinstance(data, dict):
                for k, v in list(data.items())[:10]:
                    lines.append(f"    {k}: {v}")
        
        text.setPlainText("\n".join(lines))
        layout.addWidget(text)
        
        return widget
