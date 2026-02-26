"""
Identity-Based Correlation Results View - Compact Design

Features:
- Compact layout with summary and filters on same row
- Tree view matching app background
- Smaller tab text
- Compact statistics tables
- Weighted scoring display
- Semantic mapping information
"""

import logging
from collections import defaultdict
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QLineEdit, QPushButton, QGroupBox, QDialog, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QMessageBox, QTextEdit, QTabWidget, QFrame, QProgressDialog, QApplication
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QColor, QFont, QBrush
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def _search_semantic_data(semantic_data: dict, search_term: str) -> bool:
    """
    Search for a term in semantic data structures.
    
    Handles all three semantic data structures:
    1. semantic_mappings array (current structure)
    2. Direct semantic_value field (legacy structure)
    3. String values (legacy structure)
    
    Args:
        semantic_data: Dictionary containing semantic data fields
        search_term: Search term (already lowercased)
    
    Returns:
        True if search term found in any semantic value or rule name, False otherwise
    """
    if not semantic_data or not isinstance(semantic_data, dict):
        return False
    
    for key, value in semantic_data.items():
        # Skip internal keys
        if key.startswith('_'):
            continue
        
        # Check for semantic_mappings array (current structure)
        if isinstance(value, dict) and 'semantic_mappings' in value:
            mappings = value['semantic_mappings']
            if isinstance(mappings, list) and len(mappings) > 0:
                first_mapping = mappings[0]
                if isinstance(first_mapping, dict) and 'semantic_value' in first_mapping:
                    sem_val = str(first_mapping['semantic_value']).lower()
                    rule_name = first_mapping.get('rule_name', key).lower()
                    if search_term in sem_val or search_term in rule_name:
                        return True
        
        # Check for direct semantic_value field (legacy structure)
        elif isinstance(value, dict) and 'semantic_value' in value:
            sem_val = str(value['semantic_value']).lower()
            rule_name = value.get('rule_name', key).lower()
            if search_term in sem_val or search_term in rule_name:
                return True
        
        # Check for string value (legacy structure)
        elif isinstance(value, str):
            if search_term in value.lower() or search_term in key.lower():
                return True
    
    return False


class IdentityResultsView(QWidget):
    """Compact Identity-Based Correlation Results View with Pagination and Scoring."""
    
    # VERSION STAMP - to verify correct file is loaded
    SEMANTIC_FIX_VERSION = "2026-01-24-v3-IDENTITY-FIX"
    
    match_selected = pyqtSignal(dict)
    
    # Pagination settings
    PAGE_SIZE = 100  # Load 100 identities at a time
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.identities = []
        self.filtered_identities = []
        self.current_results = None
        self.current_page = 0
        self.scoring_enabled = False
        self.semantic_enabled = False
        
        # Debounce timer for search filter
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300)  # 300ms delay
        self.search_timer.timeout.connect(self._apply_filters)
        
        self.setup_ui()
    
    def setup_ui(self):
        """Setup compact UI with labeled filters."""
        # Print version stamp to console
        print(f"[IdentityResultsView] VERSION: {self.SEMANTIC_FIX_VERSION}")
        print(f"[IdentityResultsView] Semantic fix is ACTIVE")
        
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(4)
        main_layout.setContentsMargins(4, 4, 4, 4)
        
        # Set widget background
        self.setStyleSheet("background-color: #0B1220;")
        
        # === TOP: Summary + Filters (single compact row) ===
        top_frame = QFrame()
        top_frame.setMaximumHeight(36)
        top_frame.setStyleSheet("""
            QFrame {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 6px;
            }
        """)
        top_layout = QHBoxLayout(top_frame)
        top_layout.setSpacing(10)
        top_layout.setContentsMargins(8, 4, 8, 4)
        
        # Summary labels (compact)
        self.identities_lbl = QLabel("Identities: 0")
        self.identities_lbl.setStyleSheet("color: #00FFFF; font-weight: bold; font-size: 9pt;")
        top_layout.addWidget(self.identities_lbl)
        
        self.anchors_lbl = QLabel("Anchors: 0")
        self.anchors_lbl.setStyleSheet("font-size: 8pt; color: #94A3B8;")
        top_layout.addWidget(self.anchors_lbl)
        
        self.evidence_lbl = QLabel("Evidence: 0")
        self.evidence_lbl.setStyleSheet("font-size: 8pt; color: #94A3B8;")
        top_layout.addWidget(self.evidence_lbl)
        
        self.feathers_used_lbl = QLabel("Feathers: 0")
        self.feathers_used_lbl.setStyleSheet("color: #4CAF50; font-size: 8pt; font-weight: bold;")
        top_layout.addWidget(self.feathers_used_lbl)
        
        # Scoring indicator
        self.scoring_lbl = QLabel("📊 Scoring: Off")
        self.scoring_lbl.setStyleSheet("font-size: 8pt; color: #94A3B8;")
        top_layout.addWidget(self.scoring_lbl)
        
        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #334155;")
        top_layout.addWidget(sep)
        
        # Filters with labels
        search_lbl = QLabel("Search:")
        search_lbl.setStyleSheet("font-size: 8pt; color: #94A3B8;")
        top_layout.addWidget(search_lbl)
        
        self.identity_filter = QLineEdit()
        self.identity_filter.setPlaceholderText("🔍 Search name or semantic value...")
        self.identity_filter.setMaximumWidth(250)
        self.identity_filter.setStyleSheet("""
            QLineEdit {
                font-size: 8pt; 
                padding: 2px 4px;
                background-color: #0B1220;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #E2E8F0;
            }
            QLineEdit:focus {
                border: 1px solid #00FFFF;
            }
        """)
        self.identity_filter.textChanged.connect(self._on_search_text_changed)
        top_layout.addWidget(self.identity_filter)
        
        feather_lbl = QLabel("Feather:")
        feather_lbl.setStyleSheet("font-size: 8pt; color: #94A3B8;")
        top_layout.addWidget(feather_lbl)
        
        self.feather_filter = QComboBox()
        self.feather_filter.addItem("All")
        self.feather_filter.setMaximumWidth(100)
        self.feather_filter.setStyleSheet("""
            QComboBox {
                font-size: 8pt;
                background-color: #0B1220;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #E2E8F0;
                padding: 2px 4px;
            }
            QComboBox:hover {
                border: 1px solid #00FFFF;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #1E293B;
                color: #E2E8F0;
                selection-background-color: #334155;
            }
        """)
        self.feather_filter.currentTextChanged.connect(self._apply_filters)
        top_layout.addWidget(self.feather_filter)
        
        min_lbl = QLabel("Min:")
        min_lbl.setStyleSheet("font-size: 8pt; color: #94A3B8;")
        top_layout.addWidget(min_lbl)
        
        self.min_filter = QComboBox()
        self.min_filter.addItems(["1", "2", "3", "5", "10"])
        self.min_filter.setMaximumWidth(50)
        self.min_filter.setStyleSheet("""
            QComboBox {
                font-size: 8pt;
                background-color: #0B1220;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #E2E8F0;
                padding: 2px 4px;
            }
            QComboBox:hover {
                border: 1px solid #00FFFF;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #1E293B;
                color: #E2E8F0;
                selection-background-color: #334155;
            }
        """)
        self.min_filter.currentTextChanged.connect(self._apply_filters)
        top_layout.addWidget(self.min_filter)
        
        reset_btn = QPushButton("Reset")
        reset_btn.setMaximumWidth(50)
        reset_btn.setStyleSheet("""
            QPushButton {
                font-size: 8pt; 
                padding: 2px 6px;
                background-color: #334155;
                border: 1px solid #475569;
                border-radius: 4px;
                color: #E2E8F0;
            }
            QPushButton:hover {
                background-color: #475569;
                border: 1px solid #00FFFF;
            }
        """)
        reset_btn.clicked.connect(self._reset_filters)
        top_layout.addWidget(reset_btn)
        
        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("color: #334155;")
        top_layout.addWidget(sep2)
        
        # Pagination controls
        self.prev_btn = QPushButton("<")
        self.prev_btn.setMaximumWidth(24)
        self.prev_btn.setStyleSheet("""
            QPushButton {
                font-size: 8pt; 
                padding: 2px;
                background-color: #334155;
                border: 1px solid #475569;
                border-radius: 4px;
                color: #E2E8F0;
            }
            QPushButton:hover {
                background-color: #475569;
                border: 1px solid #00FFFF;
            }
        """)
        self.prev_btn.clicked.connect(self._prev_page)
        top_layout.addWidget(self.prev_btn)
        
        self.page_lbl = QLabel("1/1")
        self.page_lbl.setStyleSheet("font-size: 8pt; color: #94A3B8;")
        top_layout.addWidget(self.page_lbl)
        
        self.next_btn = QPushButton(">")
        self.next_btn.setMaximumWidth(24)
        self.next_btn.setStyleSheet("""
            QPushButton {
                font-size: 8pt; 
                padding: 2px;
                background-color: #334155;
                border: 1px solid #475569;
                border-radius: 4px;
                color: #E2E8F0;
            }
            QPushButton:hover {
                background-color: #475569;
                border: 1px solid #00FFFF;
            }
        """)
        self.next_btn.clicked.connect(self._next_page)
        top_layout.addWidget(self.next_btn)
        
        top_layout.addStretch()
        main_layout.addWidget(top_frame)
        
        # === MIDDLE: Results Tree ===
        self.results_tree = self._create_tree()
        main_layout.addWidget(self.results_tree, stretch=1)
        
        # === BOTTOM: Stats Section with compact tables ===
        stats_frame = QFrame()
        stats_frame.setMinimumHeight(80)
        stats_frame.setMaximumHeight(120)
        stats_frame.setStyleSheet("""
            QFrame {
                background-color: #0B1220;
                border-top: 1px solid #334155;
            }
        """)
        stats_main_layout = QVBoxLayout(stats_frame)
        stats_main_layout.setSpacing(4)
        stats_main_layout.setContentsMargins(4, 4, 4, 4)
        
        # Stats row: Types, Roles, Scores
        bottom_stats = QHBoxLayout()
        bottom_stats.setSpacing(12)
        
        # Identity Types
        self.type_table = self._create_compact_table(["Type", "#"])
        bottom_stats.addWidget(self._wrap_table("Types", self.type_table), stretch=1)
        
        # Evidence Roles
        self.role_table = self._create_compact_table(["Role", "#"])
        bottom_stats.addWidget(self._wrap_table("Roles", self.role_table), stretch=1)
        
        # Scoring Summary
        self.scoring_table = self._create_compact_table(["Score", "#"])
        bottom_stats.addWidget(self._wrap_table("Scores", self.scoring_table), stretch=1)
        
        stats_main_layout.addLayout(bottom_stats)
        main_layout.addWidget(stats_frame)

    def _create_tree(self) -> QTreeWidget:
        """Create tree with app-matching background and score column."""
        tree = QTreeWidget()
        tree.setHeaderLabels(["Identity / Anchor / Evidence", "Feathers", "Score", "Semantic", "Ev", "Artifact"])
        
        tree.setColumnWidth(0, 280)
        tree.setColumnWidth(1, 150)
        tree.setColumnWidth(2, 60)  # Score column
        tree.setColumnWidth(3, 350)  # Semantic column - WIDER: Increased to 350 for better readability
        tree.setColumnWidth(4, 40)  # Evidence count
        tree.setColumnWidth(5, 80)  # Artifact
        
        tree.setAlternatingRowColors(True)
        tree.itemDoubleClicked.connect(self._on_double_click)
        tree.itemClicked.connect(self._on_item_clicked)
        tree.itemExpanded.connect(self._on_item_expanded)
        tree.itemCollapsed.connect(self._on_item_collapsed)
        
        # Match app background - dark theme with expand/collapse indicators
        tree.setStyleSheet("""
            QTreeWidget {
                font-size: 8pt;
                background-color: #0B1220;
                alternate-background-color: #1E293B;
                border: 1px solid #334155;
                color: #E2E8F0;
            }
            QTreeWidget::item { 
                padding: 4px 2px;
                min-height: 24px;
            }
            QTreeWidget::item:selected { 
                background-color: #334155; 
                color: #00FFFF;
            }
            QTreeWidget::branch {
                background-color: transparent;
            }
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:closed:has-children:has-siblings {
                border-image: none;
                image: none;
            }
            QTreeWidget::branch:open:has-children:!has-siblings,
            QTreeWidget::branch:open:has-children:has-siblings {
                border-image: none;
                image: none;
            }
            QHeaderView::section {
                background-color: #1E293B;
                color: #00FFFF;
                padding: 6px 4px;
                font-size: 8pt;
                font-weight: bold;
                border: none;
                border-bottom: 2px solid #00FFFF;
                min-height: 26px;
            }
        """)
        return tree
    
    def _create_compact_table(self, headers: List[str]) -> QTableWidget:
        """Create compact table with smaller sizing."""
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setMaximumHeight(100)  # Smaller table
        table.setMinimumHeight(60)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(18)  # Compact rows
        table.horizontalHeader().setFixedHeight(22)  # Compact header
        table.setStyleSheet("""
            QTableWidget {
                font-size: 8pt;
                background-color: #0B1220;
                alternate-background-color: #1E293B;
                border: 1px solid #334155;
                color: #E2E8F0;
            }
            QTableWidget::item { 
                padding: 2px; 
            }
            QTableWidget::item:selected {
                background-color: #334155;
                color: #00FFFF;
            }
            QHeaderView::section {
                background-color: #1E293B;
                color: #00FFFF;
                padding: 2px;
                font-size: 8pt;
                font-weight: bold;
                border: none;
                border-bottom: 1px solid #00FFFF;
            }
        """)
        return table
    
    def _wrap_table(self, title: str, table: QTableWidget) -> QGroupBox:
        """Wrap table in group box with dark theme styling."""
        group = QGroupBox(title)
        group.setStyleSheet("""
            QGroupBox { 
                font-size: 8pt; 
                font-weight: bold; 
                color: #00FFFF;
                padding-top: 12px; 
                margin-top: 4px;
                border: 1px solid #334155;
                border-radius: 4px;
                background-color: #0B1220;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 1px 6px;
                background-color: #1E293B;
                border-radius: 3px;
            }
        """)
        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(1)
        layout.addWidget(table)
        group.setLayout(layout)
        return group
    
    def load_results(self, results: Dict[str, Any]):
        """Load correlation results with pagination."""
        self.current_results = results
        self.identities = results.get('identities', [])
        self.filtered_identities = self.identities.copy()
        self.current_page = 0
        self._update_summary(results)
        self._update_feather_filter(results)
        self._populate_current_page()
        self._update_stats(results)
    
    def load_from_correlation_result(self, result, show_progress=True):
        """Load from CorrelationResult object with progress indicator.
        
        Args:
            result: CorrelationResult object
            show_progress: If False, suppresses the progress dialog (useful when parent already shows progress)
        """
        print(f"[IdentityResultsView] load_from_correlation_result called with {result.total_matches} matches")
        
        # Show progress dialog if we have many matches and show_progress is True
        progress = None
        if show_progress and result.total_matches > 100:
            progress = QProgressDialog("Loading identity data...", "Cancel", 0, 100, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setWindowTitle("Loading Results")
            
            # Apply Crow Eye styling
            from .ui_styling import CorrelationEngineStyles
            CorrelationEngineStyles.apply_progress_dialog_style(progress)
            progress.show()
            QApplication.processEvents()
        
        try:
            identities = self._convert_matches(result.matches, progress)
            
            if progress and progress.wasCanceled():
                print("[IdentityResultsView] Loading cancelled by user")
                return
            
            print(f"[IdentityResultsView] Converted to {len(identities)} identities")
            
            # Use feather_metadata from result if available (contains records_loaded and identities_found)
            feather_metadata = result.feather_metadata if hasattr(result, 'feather_metadata') and result.feather_metadata else {}
            
            # Filter out non-dict metadata entries
            filtered_metadata = {}
            for fid, data in feather_metadata.items():
                if isinstance(data, dict):
                    filtered_metadata[fid] = data
            feather_metadata = filtered_metadata
            
            # If feather_metadata doesn't have the right format, build it from matches
            if feather_metadata and not any('records_loaded' in v for v in feather_metadata.values() if isinstance(v, dict)):
                # Old format - convert
                new_metadata = {}
                for fid, data in feather_metadata.items():
                    if isinstance(data, dict):
                        new_metadata[fid] = {
                            'records_loaded': data.get('records', data.get('records_loaded', 0)),
                            'artifact_type': data.get('artifact', data.get('artifact_type', 'Unknown')),
                            'identities_found': data.get('identities_found', 0)
                        }
                feather_metadata = new_metadata
            
            # Calculate total anchors properly for new format
            total_anchors = 0
            for identity in identities:
                sub_identities = identity.get('sub_identities', [])
                if sub_identities:
                    for sub in sub_identities:
                        total_anchors += len(sub.get('anchors', []))
                else:
                    total_anchors += len(identity.get('anchors', []))
            
            results_dict = {
                'identities': identities,
                'statistics': {
                    'total_identities': len(identities),
                    'total_anchors': total_anchors,
                    'total_evidence': result.total_records_scanned,
                    'execution_time': result.execution_duration_seconds,
                    'feathers_used': result.feathers_processed
                },
                'wing_name': result.wing_name,
                'feather_metadata': feather_metadata
            }
            
            if progress:
                progress.setLabelText("Displaying results...")
                progress.setValue(90)
                QApplication.processEvents()
            
            print(f"[IdentityResultsView] Calling load_results with {len(identities)} identities, {total_anchors} anchors")
            self.load_results(results_dict)
            print(f"[IdentityResultsView] load_results completed, tree has {self.results_tree.topLevelItemCount()} items")
            
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
    
    def _convert_matches(self, matches, progress=None) -> List[Dict]:
        """Convert matches to identity format with sub-identities."""
        identity_map = {}
        
        # Debug: Check if matches is iterable and has items
        if not matches:
            print(f"[IdentityResultsView] _convert_matches: No matches provided (matches is {type(matches)})")
            return []
        
        total_matches = len(matches)
        
        match_count = 0
        for match in matches:
            match_count += 1
            
            # Update progress every 100 matches
            if progress and match_count % 100 == 0:
                percentage = int((match_count / total_matches) * 80)  # 0-80% for processing
                progress.setValue(percentage)
                progress.setLabelText(f"Loading identity data: {match_count}/{total_matches} identities...")
                QApplication.processEvents()
                
                if progress.wasCanceled():
                    return []
            
            # Debug first few matches
            if match_count <= 3:
                print(f"[IdentityResultsView] Match {match_count}: app={getattr(match, 'matched_application', 'N/A')}, "
                      f"path={getattr(match, 'matched_file_path', 'N/A')}, "
                      f"records={len(getattr(match, 'feather_records', {}))}")
            
            # FIXED: Normalize the application name for grouping
            # This ensures "chrome.exe", "CHROME~1.EXE", "chrome123.exe" all group together
            raw_app = match.matched_application or "Unknown"
            main_app = self._normalize_for_grouping(raw_app)
            
            if main_app not in identity_map:
                # Use a clean display name (not fully normalized) for primary_name
                display_name = self._get_display_name_for_gui(raw_app)
                
                identity_map[main_app] = {
                    'identity_id': main_app,
                    'identity_type': 'name',
                    'primary_name': display_name,  # Clean, readable display name
                    'sub_identities': {},  # original_name -> sub_identity data
                    'feathers_found': set()
                }
            
            identity_map[main_app]['feathers_found'].update(match.feather_records.keys())
            
            # Extract original name from the first evidence row
            # FIXED: Start with raw_app (not normalized main_app) as fallback
            # 
            # NAME EXTRACTION PRIORITY:
            # 1. First, try to find a 'name' field in evidence data
            # 2. If name field matches raw_app, also check path fields (may have different case)
            # 3. If no suitable name found, fall back to raw_app
            # 
            # This ensures we get the most representative original name while preserving
            # case variations (e.g., "CHROME.EXE" from path vs "chrome.exe" from name field)
            original_name = raw_app
            for fid, data in match.feather_records.items():
                if isinstance(data, dict):
                    # Try to get original filename from name fields
                    for field in ['name', 'filename', 'file_name', 'fn_filename', 'executable_name',
                                  'Source_Name', 'original_filename', 'app_name', 'value', 'Value',
                                  'FileName', 'Name']:
                        if field in data and data[field]:
                            original_name = str(data[field])
                            break
                    if original_name != raw_app:
                        break
                    # Try path extraction with validation
                    for field in ['path', 'file_path', 'Local_Path', 'app_path', 'full_path']:
                        if field in data and data[field]:
                            from pathlib import Path
                            path_val = str(data[field])
                            if '\\' in path_val or '/' in path_val:
                                extracted_name = Path(path_val.replace('\\', '/')).name
                                # FIXED: Validate that extracted name is not empty
                                if extracted_name:
                                    original_name = extracted_name
                                    break
                    if original_name != raw_app:
                        break
            
            # Create or get sub-identity
            if original_name not in identity_map[main_app]['sub_identities']:
                identity_map[main_app]['sub_identities'][original_name] = {
                    'original_name': original_name,
                    'anchors': [],
                    'feathers_found': set()
                }
            
            sub_identity = identity_map[main_app]['sub_identities'][original_name]
            sub_identity['feathers_found'].update(match.feather_records.keys())
            
            # Get anchor metadata if available (from streaming mode)
            anchor_start_time = getattr(match, 'anchor_start_time', match.timestamp)
            anchor_end_time = getattr(match, 'anchor_end_time', match.timestamp)
            anchor_record_count = getattr(match, 'anchor_record_count', len(match.feather_records))
            
            # Get scoring data
            weighted_score = getattr(match, 'weighted_score', None)
            score_breakdown = getattr(match, 'score_breakdown', None)
            confidence_score = getattr(match, 'confidence_score', None)
            confidence_category = getattr(match, 'confidence_category', None)
            
            # Get semantic data
            semantic_data = getattr(match, 'semantic_data', None)
            
            anchor = {
                'anchor_id': match.match_id,
                'start_time': anchor_start_time,
                'end_time': anchor_end_time,
                'record_count': anchor_record_count,
                'feathers': list(match.feather_records.keys()),
                'primary_artifact': match.anchor_artifact_type,
                'evidence_count': match.feather_count,
                'weighted_score': weighted_score,
                'score_breakdown': score_breakdown,
                'confidence_score': confidence_score,
                'confidence_category': confidence_category,
                'semantic_data': semantic_data,
                'evidence_rows': [
                    {'feather_id': fid, 'artifact': match.anchor_artifact_type, 
                     'timestamp': match.timestamp, 'data': data,
                     'role': 'primary' if fid == match.anchor_feather_id else 'secondary'}
                    for fid, data in match.feather_records.items()
                ]
            }
            sub_identity['anchors'].append(anchor)
        
        # Convert to list format
        result = []
        for identity in identity_map.values():
            identity['feathers_found'] = list(identity['feathers_found'])
            # Convert sub_identities dict to list
            sub_list = []
            for sub in identity['sub_identities'].values():
                sub['feathers_found'] = list(sub['feathers_found'])
                sub_list.append(sub)
            identity['sub_identities'] = sub_list
            result.append(identity)
        
        # Debug: Show conversion summary
        print(f"[IdentityResultsView] _convert_matches: Processed {match_count} matches -> {len(result)} identities")
        
        return result
    
    def _normalize_for_grouping(self, name: str) -> str:
        """
        Normalize application name for identity grouping.
        
        Uses the SAME aggressive normalization as the identity engine to ensure
        identities are grouped correctly in the GUI.
        
        This ensures "chrome.exe", "CHROME~1.EXE", "chrome123.exe" all become "chrome"
        and are grouped together under the same main identity.
        
        LIMITATION: Only ASCII alphanumeric characters are preserved. Unicode characters
        (accents, non-Latin scripts) are removed during normalization. This is acceptable
        for Windows forensics where most application names use ASCII.
        
        Examples:
        - "chrome.exe" → "chrome"
        - "CHROME~1.EXE" → "chrome"
        - "chrome123.exe" → "chrome"
        - "Naïve.exe" → "nave" (accent removed)
        
        Args:
            name: Raw application name
        
        Returns:
            Aggressively normalized name for grouping (ASCII alphanumeric only)
        """
        if not name:
            return "Unknown"
        
        import re
        
        result = name.strip()
        
        # Step -1: Handle Prefetch filenames (APPNAME.EXE HASH.pf)
        # Extract just the APPNAME.EXE part before the hash
        # Pattern: ends with space + 8 hex chars + .pf
        # Examples: "BRAVE.EXE 3118B3E3.pf" → "BRAVE.EXE"
        #           "chrome.exe AF43252D.pf" → "chrome.exe"
        if result.lower().endswith('.pf'):
            # Check if there's a space followed by hex hash before .pf
            match = re.match(r'^(.+?)\s+[0-9A-Fa-f]{8}\.pf$', result, re.IGNORECASE)
            if match:
                result = match.group(1)  # Extract just the app name part
        
        # Step 0: Remove ~ and everything after it (FIRST - before any other processing)
        # This handles cases like "CHROME~1.EXE", "file~123.txt"
        if '~' in result:
            result = result.split('~')[0]
        
        # Step 1: Remove common file extensions (case-insensitive)
        extensions = [
            '.exe', '.lnk', '.dll', '.msi', '.bat', '.cmd', '.ps1', '.vbs', '.js',
            '.com', '.scr', '.pif', '.application', '.gadget', '.msp', '.hta',
            '.cpl', '.msc', '.jar', '.py', '.pyc', '.pyw'
        ]
        lower_result = result.lower()
        for ext in extensions:
            if lower_result.endswith(ext):
                result = result[:-len(ext)]
                lower_result = result.lower()
                break
        
        # Step 2: Remove copy indicators like (1), (2), (3), etc.
        result = re.sub(r'[\s_]*\(\d+\)\s*$', '', result)
        
        # Step 3: Remove " - Copy", "_copy", " copy" at the end
        result = re.sub(r'[\s_]*[-_]?\s*[Cc]opy\s*\d*\s*$', '', result)
        result = re.sub(r'[\s_]*\([Cc]opy\s*\d*\)\s*$', '', result)
        
        # Step 4: Remove version patterns like v1, v2, v1.0, 1.0.0 at the end
        # FIXED: More specific pattern - requires space/underscore OR 'v' prefix
        # This prevents removing numbers that are part of the name (e.g., "chrome1")
        result = re.sub(r'[\s_]+[vV]?\d+(\.\d+)*\s*$', '', result)  # Requires space/underscore
        result = re.sub(r'[vV]\d+(\.\d+)*\s*$', '', result)  # OR explicit v prefix without space
        
        # Step 5: AGGRESSIVE NORMALIZATION for grouping
        # Convert to lowercase first
        result = result.lower()
        
        # Remove ALL spaces, hyphens, underscores, dots, parentheses, brackets
        result = re.sub(r'[\s\-_\.\(\)\[\]]+', '', result)
        
        # Remove any remaining special characters except alphanumeric
        result = re.sub(r'[^a-z0-9]', '', result)
        
        # Step 6: Remove ALL numbers for better grouping
        # This ensures "chrome1", "chrome2", "chrome123" all become "chrome"
        result = re.sub(r'\d+', '', result)
        
        # If result is empty after all processing, fall back to original
        if not result:
            # Fall back to simpler normalization (keep some characters)
            result = name.strip().lower()
            if '~' in result:
                result = result.split('~')[0]
            result = re.sub(r'[\s\-_\.\(\)\[\]]+', '', result)
            result = re.sub(r'[^a-z0-9]', '', result)
            # Don't remove numbers in fallback to avoid empty result
        
        return result.strip() if result else "Unknown"
    
    def _get_display_name_for_gui(self, raw_name: str) -> str:
        """
        Get a clean, readable display name from the raw name for GUI display.
        
        This is used for the primary_name field to show a user-friendly version
        while the aggressive normalization is used for grouping.
        
        Removes:
        - File extensions (.exe, .lnk, etc.)
        - Copy indicators: (1), (2), - Copy
        - Version indicators: v1, v2, v1.0
        - Tilde and everything after it (~1, ~123)
        
        Preserves:
        - Original capitalization
        - Spaces and readable formatting
        
        Examples:
        - "Chrome.exe" → "Chrome"
        - "CHROME~1.EXE" → "CHROME"
        - "Microsoft Edge.exe" → "Microsoft Edge"
        - "chrome-browser (1).exe" → "chrome-browser"
        
        Args:
            raw_name: Original application name
        
        Returns:
            Clean, readable display name
        """
        if not raw_name:
            return "Unknown"
        
        import re
        
        result = raw_name.strip()
        
        # Step -1: Handle Prefetch filenames (APPNAME.EXE HASH.pf)
        # Extract just the APPNAME.EXE part before the hash
        # Pattern: ends with space + 8 hex chars + .pf
        # Examples: "BRAVE.EXE 3118B3E3.pf" → "BRAVE.EXE"
        #           "chrome.exe AF43252D.pf" → "chrome.exe"
        if result.lower().endswith('.pf'):
            # Check if there's a space followed by hex hash before .pf
            match = re.match(r'^(.+?)\s+[0-9A-Fa-f]{8}\.pf$', result, re.IGNORECASE)
            if match:
                result = match.group(1)  # Extract just the app name part
        
        # Step 0: Remove ~ and everything after it (FIRST)
        if '~' in result:
            result = result.split('~')[0]
        
        # Step 1: Remove common file extensions (case-insensitive)
        extensions = [
            '.exe', '.lnk', '.dll', '.msi', '.bat', '.cmd', '.ps1', '.vbs', '.js',
            '.com', '.scr', '.pif', '.application', '.gadget', '.msp', '.hta',
            '.cpl', '.msc', '.jar', '.py', '.pyc', '.pyw'
        ]
        lower_result = result.lower()
        for ext in extensions:
            if lower_result.endswith(ext):
                result = result[:-len(ext)]
                break
        
        # Step 2: Remove copy indicators like (1), (2), (3), etc.
        result = re.sub(r'[\s_]*\(\d+\)\s*$', '', result)
        
        # Step 3: Remove " - Copy", "_copy", " copy" at the end
        result = re.sub(r'[\s_]*[-_]?\s*[Cc]opy\s*\d*\s*$', '', result)
        
        # Step 4: Remove version patterns like v1, v2, v1.0, 1.0.0 at the end
        # FIXED: More specific pattern - requires space/underscore OR 'v' prefix
        # This prevents removing numbers that are part of the name (e.g., "chrome1")
        result = re.sub(r'[\s_]+[vV]?\d+(\.\d+)*\s*$', '', result)  # Requires space/underscore
        result = re.sub(r'[vV]\d+(\.\d+)*\s*$', '', result)  # OR explicit v prefix without space
        
        # Step 5: Clean up trailing special characters
        result = result.rstrip(' _-.')
        
        # Step 6: Normalize multiple spaces to single space
        result = re.sub(r'\s+', ' ', result)
        
        return result.strip() if result else "Unknown"
    
    def _update_summary(self, results: Dict):
        """Update summary labels with cancelled indicator if applicable."""
        stats = results.get('statistics', {})
        
        # Check if execution was cancelled
        status = results.get('status', 'Completed')
        is_cancelled = status == "Cancelled"
        
        # Update identity label with cancelled indicator
        identity_count = stats.get('total_identities', len(self.identities))
        if is_cancelled:
            self.identities_lbl.setText(f"⚠️ Identities: {identity_count:,} (Cancelled)")
            self.identities_lbl.setStyleSheet("color: #FF9800; font-weight: bold; font-size: 9pt;")
            self.identities_lbl.setToolTip("Execution was cancelled by user. Showing partial results.")
        else:
            self.identities_lbl.setText(f"Identities: {identity_count:,}")
            self.identities_lbl.setStyleSheet("color: #00FFFF; font-weight: bold; font-size: 9pt;")
            self.identities_lbl.setToolTip("")
        
        self.anchors_lbl.setText(f"Anchors: {stats.get('total_anchors', 0):,}")
        self.evidence_lbl.setText(f"Evidence: {stats.get('total_evidence', 0):,}")
        
        # Show feathers used with details
        feather_metadata = results.get('feather_metadata', {})
        feathers_used = stats.get('feathers_used', len(feather_metadata))
        if feather_metadata:
            # Build tooltip with feather details
            tooltip_lines = ["Feather Details:"]
            for fid, meta in sorted(feather_metadata.items(), 
                                    key=lambda x: x[1].get('records_loaded', 0), 
                                    reverse=True):
                records = meta.get('records_loaded', meta.get('records', 0))
                identities = meta.get('identities_found', 0)
                tooltip_lines.append(f"  {fid}: {records:,} records, {identities} identities")
            self.feathers_used_lbl.setToolTip("\n".join(tooltip_lines))
        
        self.feathers_used_lbl.setText(f"Feathers: {feathers_used}")
    
    def _update_feather_filter(self, results: Dict):
        """Update feather filter."""
        self.feather_filter.clear()
        self.feather_filter.addItem("All")
        
        feathers = set()
        for identity in self.identities:
            # Handle both old format (anchors) and new format (sub_identities)
            sub_identities = identity.get('sub_identities', [])
            if sub_identities:
                for sub in sub_identities:
                    for anchor in sub.get('anchors', []):
                        feathers.update(anchor.get('feathers', []))
            else:
                for anchor in identity.get('anchors', []):
                    feathers.update(anchor.get('feathers', []))
        
        # Group feathers by base name (remove numeric suffix like _0, _1, _2)
        base_feathers = set()
        for f in feathers:
            # Remove path prefix (e.g., "feathers/") from display name
            display_name = f.split('/')[-1] if '/' in f else f
            # Extract base name by removing numeric suffix (_0, _1, etc.)
            base_name = display_name.rsplit('_', 1)[0] if '_' in display_name and display_name.rsplit('_', 1)[-1].isdigit() else display_name
            base_feathers.add(base_name)
        
        for base_name in sorted(base_feathers):
            self.feather_filter.addItem(base_name)
    
    def _populate_tree(self, identities: List[Dict]):
        """Populate tree with given identities (used internally)."""
        self.results_tree.clear()
        
        if not identities:
            # Show a message when there are no results (6 columns - removed Time)
            empty_item = QTreeWidgetItem(["No correlation matches found", "", "", "", "", ""])
            empty_item.setForeground(0, QBrush(QColor("#888888")))
            empty_item.setFont(0, QFont("Segoe UI", 9, QFont.Normal))
            self.results_tree.addTopLevelItem(empty_item)
            return
        
        for identity in identities:
            item = self._create_identity_item(identity)
            self.results_tree.addTopLevelItem(item)
        
        # Expand first 3
        for i in range(min(3, self.results_tree.topLevelItemCount())):
            self.results_tree.topLevelItem(i).setExpanded(True)
    
    def _populate_current_page(self):
        """Populate tree with current page of identities."""
        total = len(self.filtered_identities)
        total_pages = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        
        start = self.current_page * self.PAGE_SIZE
        end = min(start + self.PAGE_SIZE, total)
        
        page_identities = self.filtered_identities[start:end]
        self._populate_tree(page_identities)
        
        # Update pagination controls
        self.page_lbl.setText(f"Page {self.current_page + 1}/{total_pages} ({total} total)")
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(self.current_page < total_pages - 1)
    
    def _prev_page(self):
        """Go to previous page."""
        if self.current_page > 0:
            self.current_page -= 1
            self._populate_current_page()
    
    def _next_page(self):
        """Go to next page."""
        total_pages = max(1, (len(self.filtered_identities) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self._populate_current_page()
    
    def _create_identity_item(self, identity: Dict) -> QTreeWidgetItem:
        """Create identity tree item with sub-identities."""
        # Calculate totals across all sub-identities
        feathers = set(identity.get('feathers_found', []))
        total_evidence = 0
        total_anchors = 0
        
        sub_identities = identity.get('sub_identities', [])
        
        # If no sub_identities, use old format (anchors directly)
        if not sub_identities:
            for a in identity.get('anchors', []):
                feathers.update(a.get('feathers', []))
                total_evidence += a.get('evidence_count', len(a.get('evidence_rows', [])))
                total_anchors += 1
        else:
            for sub in sub_identities:
                feathers.update(sub.get('feathers_found', []))
                for a in sub.get('anchors', []):
                    total_evidence += a.get('evidence_count', len(a.get('evidence_rows', [])))
                    total_anchors += 1
        
        # Group feathers by base name (remove numeric suffix)
        base_feathers = set()
        for f in feathers:
            display_name = f.split('/')[-1] if '/' in f else f
            base_name = display_name.rsplit('_', 1)[0] if '_' in display_name and display_name.rsplit('_', 1)[-1].isdigit() else display_name
            base_feathers.add(base_name)
        
        name = identity.get('primary_name', 'Unknown')
        feather_str = ", ".join(sorted(base_feathers)[:2]) + ("..." if len(base_feathers) > 2 else "")
        sub_count = len(sub_identities) if sub_identities else 0
        
        # Calculate average score for identity
        avg_score = self._calculate_identity_score(identity)
        score_str = f"{avg_score:.2f}" if avg_score > 0 else "-"
        
        # Task 6.2: Get aggregated semantic value for identity with error handling
        try:
            semantic_value, semantic_tooltip = self._get_identity_semantic_value(identity)
        except Exception as e:
            logger.error(f"Error getting identity semantic value: {e}")
            semantic_value, semantic_tooltip = "Error", "Error retrieving semantic data"
        
        # Check if has children for expand indicator
        has_children = bool(sub_identities) or bool(identity.get('anchors', []))
        expand_indicator = "▶ " if has_children else "  "
        
        # Task 6.2: Check if identity has semantic data for [S] indicator with error handling
        try:
            has_semantic = semantic_value not in ["-", "Error", "Fallback", None, ""]
            semantic_indicator = "[S] " if has_semantic else ""
        except Exception as e:
            logger.warning(f"Error checking semantic indicator: {e}")
            semantic_indicator = ""
        
        # Main identity item with expand indicator and blue diamond icon (6 columns - removed Time)
        item = QTreeWidgetItem([
            f"{expand_indicator}🔷 {semantic_indicator}{name}" + (f" ({sub_count} variants)" if sub_count > 1 else ""),
            feather_str, 
            score_str,
            semantic_value,  # Semantic column with aggregated value
            str(total_evidence), 
            f"{total_anchors} anchors"
        ])
        item.setFont(0, QFont("Segoe UI", 9, QFont.Bold))
        item.setForeground(0, QBrush(QColor("#2196F3")))
        
        # Color score based on value
        if avg_score >= 0.7:
            item.setForeground(2, QBrush(QColor("#4CAF50")))  # Green - high score
        elif avg_score >= 0.4:
            item.setForeground(2, QBrush(QColor("#FF9800")))  # Orange - medium score
        elif avg_score > 0:
            item.setForeground(2, QBrush(QColor("#F44336")))  # Red - low score
        
        # Task 6.2: Color semantic column with error handling
        try:
            if semantic_value == "Error":
                item.setForeground(3, QBrush(QColor("#F44336")))  # Red for errors
                item.setToolTip(3, "Error retrieving semantic data")
            elif semantic_value == "Fallback":
                item.setForeground(3, QBrush(QColor("#FF9800")))  # Orange for fallback
                item.setToolTip(3, "Using fallback semantic data")
            elif semantic_value != "-":
                item.setForeground(3, QBrush(QColor("#9C27B0")))  # Purple for semantic values
                if semantic_tooltip:
                    item.setToolTip(3, semantic_tooltip)
        except Exception as e:
            logger.warning(f"Error setting semantic column color: {e}")
        
        item.setData(0, Qt.UserRole, {'type': 'identity', 'data': identity})
        
        # Add sub-identities if present
        if sub_identities:
            for sub in sub_identities:
                sub_item = self._create_sub_identity_item(sub)
                item.addChild(sub_item)
        else:
            # Old format - add anchors directly
            for anchor in identity.get('anchors', []):
                item.addChild(self._create_anchor_item(anchor))
        
        return item
    
    def _calculate_identity_score(self, identity: Dict) -> float:
        """Calculate average weighted score for an identity."""
        scores = []
        sub_identities = identity.get('sub_identities', [])
        
        if sub_identities:
            for sub in sub_identities:
                for anchor in sub.get('anchors', []):
                    weighted_score = anchor.get('weighted_score', {})
                    if isinstance(weighted_score, dict):
                        score = weighted_score.get('score', 0)
                        if score > 0:
                            scores.append(score)
        else:
            for anchor in identity.get('anchors', []):
                weighted_score = anchor.get('weighted_score', {})
                if isinstance(weighted_score, dict):
                    score = weighted_score.get('score', 0)
                    if score > 0:
                        scores.append(score)
        
        return sum(scores) / len(scores) if scores else 0.0
    
    def _get_identity_semantic_value(self, identity: Dict) -> tuple:
        """
        Extract aggregated semantic value from all anchors in an identity.
        
        Returns:
            Tuple of (display_value, tooltip_text) where:
            - display_value: Short string for the Semantic column
            - tooltip_text: Detailed tooltip with all semantic values
        """
        semantic_values = []
        sub_identities = identity.get('sub_identities', [])
        
        # Collect semantic data from all anchors
        anchors_to_check = []
        if sub_identities:
            for sub in sub_identities:
                anchors_to_check.extend(sub.get('anchors', []))
        else:
            anchors_to_check = identity.get('anchors', [])
        
        for anchor in anchors_to_check:
            semantic_data = anchor.get('semantic_data')
            if semantic_data and isinstance(semantic_data, dict) and not semantic_data.get('_unavailable'):
                for key, value in semantic_data.items():
                    if key.startswith('_'):
                        continue
                    
                    # NEW: Check for semantic_mappings array (current structure)
                    if isinstance(value, dict) and 'semantic_mappings' in value:
                        mappings = value['semantic_mappings']
                        if isinstance(mappings, list) and len(mappings) > 0:
                            first_mapping = mappings[0]
                            if isinstance(first_mapping, dict) and 'semantic_value' in first_mapping:
                                sem_val = str(first_mapping['semantic_value'])
                                rule_name = first_mapping.get('rule_name', key)
                                if sem_val and sem_val not in [v[0] for v in semantic_values]:
                                    semantic_values.append((sem_val, rule_name))
                    
                    # LEGACY: Direct semantic_value in value dict
                    elif isinstance(value, dict) and 'semantic_value' in value:
                        sem_val = str(value['semantic_value'])
                        rule_name = value.get('rule_name', key)
                        if sem_val and sem_val not in [v[0] for v in semantic_values]:
                            semantic_values.append((sem_val, rule_name))
                    
                    # LEGACY: String value
                    elif isinstance(value, str) and value:
                        if value not in [v[0] for v in semantic_values]:
                            semantic_values.append((value, key))
        
        if not semantic_values:
            return ("-", "")
        
        # Build display value (first value + count if multiple)
        first_value = semantic_values[0][0]
        if len(semantic_values) == 1:
            display_value = first_value
        else:
            display_value = f"{first_value} (+{len(semantic_values)-1})"
        
        # Build tooltip with all values
        tooltip_lines = ["🏷️ Semantic Values:"]
        for sem_val, rule_name in semantic_values:
            tooltip_lines.append(f"  • {rule_name}: {sem_val}")
        
        return (display_value, "\n".join(tooltip_lines))
    
    def _get_semantic_value(self, anchor: Dict) -> str:
        """
        Extract semantic value from anchor data with comprehensive error handling.
        
        Task 6.2: Handle corrupted or invalid semantic_data gracefully
        Requirements: 7.3, 7.4 - Prevent crashes when semantic values are malformed
        
        Checks:
        1. Anchor-level semantic_data field (new structure with semantic_mappings)
        2. Evidence rows for _semantic_mappings key (legacy)
        
        Returns:
            Semantic value string or "-" if not available
        """
        try:
            # Task 6.2: Check anchor-level semantic data with error handling
            semantic_data = anchor.get('semantic_data')
            if semantic_data:
                # Task 6.2: Handle corrupted semantic_data gracefully
                if not isinstance(semantic_data, dict):
                    logger.warning(f"Invalid semantic_data type: {type(semantic_data)}, expected dict")
                    return "Error: Invalid data"
                
                # Check for unavailable marker
                if semantic_data.get('_unavailable'):
                    return "-"
                
                # Check for error metadata
                metadata = semantic_data.get('_metadata', {})
                if isinstance(metadata, dict):
                    if metadata.get('error'):
                        return "Error"
                    if metadata.get('fallback_reason'):
                        return "Fallback"
                
                # Extract semantic values with error handling
                # New structure: field_info contains semantic_mappings array
                for field_name, field_info in semantic_data.items():
                    # Skip metadata and internal keys
                    if field_name.startswith('_'):
                        continue
                    
                    try:
                        # NEW: Check for semantic_mappings array (current structure)
                        if isinstance(field_info, dict) and 'semantic_mappings' in field_info:
                            semantic_mappings = field_info['semantic_mappings']
                            if isinstance(semantic_mappings, list) and len(semantic_mappings) > 0:
                                first_mapping = semantic_mappings[0]
                                if isinstance(first_mapping, dict) and 'semantic_value' in first_mapping:
                                    semantic_value = first_mapping['semantic_value']
                                    if semantic_value is not None:
                                        return str(semantic_value)
                        
                        # LEGACY: Direct semantic_value in field_info
                        elif isinstance(field_info, dict) and 'semantic_value' in field_info:
                            semantic_value = field_info['semantic_value']
                            if semantic_value is not None:
                                return str(semantic_value)
                        
                        # LEGACY: String value
                        elif isinstance(field_info, str) and field_name != '_reason':
                            return field_info
                        
                        # Fallback: Convert to string
                        elif field_info is not None:
                            return str(field_info)
                    except Exception as e:
                        logger.warning(f"Error processing semantic field {field_name}: {e}")
                        continue
            
            # Task 6.2: Check evidence rows for semantic mappings with error handling
            evidence_rows = anchor.get('evidence_rows', [])
            if not isinstance(evidence_rows, list):
                logger.warning(f"Invalid evidence_rows type: {type(evidence_rows)}, expected list")
                return "-"
            
            for evidence in evidence_rows:
                try:
                    if not isinstance(evidence, dict):
                        continue
                    
                    data = evidence.get('data', {})
                    if not isinstance(data, dict):
                        continue
                    
                    semantic_mappings = data.get('_semantic_mappings', {})
                    if not isinstance(semantic_mappings, dict):
                        continue
                    
                    for field_name, mapping_info in semantic_mappings.items():
                        # Skip internal keys
                        if field_name.startswith('_'):
                            continue
                        
                        try:
                            if isinstance(mapping_info, dict) and 'semantic_value' in mapping_info:
                                semantic_value = mapping_info['semantic_value']
                                if semantic_value is not None:
                                    return str(semantic_value)
                            elif isinstance(mapping_info, str):
                                return mapping_info
                            elif mapping_info is not None:
                                # Handle unexpected data types gracefully
                                return str(mapping_info)
                        except Exception as e:
                            logger.warning(f"Error processing semantic mapping {field_name}: {e}")
                            continue
                            
                except Exception as e:
                    logger.warning(f"Error processing evidence row: {e}")
                    continue
        
        except Exception as e:
            # Task 6.2: Show appropriate fallback content in semantic column
            # Requirements: 7.3, 7.4 - Never crash, always show something meaningful
            logger.error(f"Critical error in _get_semantic_value: {e}")
            return "Error"
        
        return "-"  # Default when no semantic data available
    
    def _create_sub_identity_item(self, sub_identity: Dict) -> QTreeWidgetItem:
        """Create sub-identity tree item (original filename)."""
        feathers = set(sub_identity.get('feathers_found', []))
        evidence = 0
        anchors = sub_identity.get('anchors', [])
        scores = []
        
        for a in anchors:
            feathers.update(a.get('feathers', []))
            evidence += a.get('evidence_count', len(a.get('evidence_rows', [])))
            weighted_score = a.get('weighted_score', {})
            if isinstance(weighted_score, dict) and weighted_score.get('score', 0) > 0:
                scores.append(weighted_score.get('score', 0))
        
        # Group feathers by base name (remove numeric suffix)
        base_feathers = set()
        for f in feathers:
            display_name = f.split('/')[-1] if '/' in f else f
            base_name = display_name.rsplit('_', 1)[0] if '_' in display_name and display_name.rsplit('_', 1)[-1].isdigit() else display_name
            base_feathers.add(base_name)
        
        original_name = sub_identity.get('original_name', 'Unknown')
        feather_str = ", ".join(sorted(base_feathers)[:2]) + ("..." if len(base_feathers) > 2 else "")
        avg_score = sum(scores) / len(scores) if scores else 0.0
        score_str = f"{avg_score:.2f}" if avg_score > 0 else "-"
        
        # Check if has children for expand indicator
        has_children = bool(anchors)
        expand_indicator = "▶ " if has_children else "  "
        
        # Sub-identity item with expand indicator and folder icon (orange/yellow) - 6 columns (removed Time)
        item = QTreeWidgetItem([
            f"{expand_indicator}📁 {original_name}",
            feather_str,
            score_str,
            "-",  # Semantic column (sub-identities don't have semantic values)
            str(evidence),
            f"{len(anchors)} anchors"
        ])
        item.setFont(0, QFont("Segoe UI", 8))
        item.setForeground(0, QBrush(QColor("#FF9800")))  # Orange for sub-identity
        
        # Color score
        if avg_score >= 0.7:
            item.setForeground(2, QBrush(QColor("#4CAF50")))
        elif avg_score >= 0.4:
            item.setForeground(2, QBrush(QColor("#FF9800")))
        elif avg_score > 0:
            item.setForeground(2, QBrush(QColor("#F44336")))
        
        item.setData(0, Qt.UserRole, {'type': 'sub_identity', 'data': sub_identity})
        
        # Add anchors under sub-identity
        for anchor in anchors:
            item.addChild(self._create_anchor_item(anchor))
        
        return item
    
    def _create_anchor_item(self, anchor: Dict) -> QTreeWidgetItem:
        """Create anchor tree item with score and time range."""
        start_time = anchor.get('start_time', '')
        end_time = anchor.get('end_time', start_time)
        record_count = anchor.get('record_count', 0)
        
        # Format time display
        if isinstance(start_time, str):
            start_time = start_time[:19] if start_time else ""
        if isinstance(end_time, str):
            end_time = end_time[:19] if end_time else ""
        
        # Show time range if different, otherwise just start time
        if start_time and end_time and start_time != end_time:
            time_display = f"{start_time[:10]} {start_time[11:16]}-{end_time[11:16]}"
        else:
            time_display = start_time
        
        feathers = anchor.get('feathers', [])
        
        # Group feathers by base name (remove numeric suffix)
        base_feathers = set()
        for f in feathers:
            display_name = f.split('/')[-1] if '/' in f else f
            base_name = display_name.rsplit('_', 1)[0] if '_' in display_name and display_name.rsplit('_', 1)[-1].isdigit() else display_name
            base_feathers.add(base_name)
        
        count = anchor.get('evidence_count', len(anchor.get('evidence_rows', [])))
        
        # Get weighted score
        weighted_score = anchor.get('weighted_score', {})
        if isinstance(weighted_score, dict):
            score = weighted_score.get('score', 0)
            interpretation = weighted_score.get('interpretation', '')
            score_str = f"{score:.2f}"
        else:
            score = 0
            interpretation = ''
            score_str = "-"
        
        # Get semantic value for display using the dedicated method
        semantic_value = self._get_semantic_value(anchor)
        
        # 7 columns now - added Semantic column
        artifact_info = anchor.get('primary_artifact', '-')
        if record_count > 0:
            artifact_info = f"{artifact_info} ({record_count} rec)"
        
        # Check if has children for expand indicator
        evidence_rows = anchor.get('evidence_rows', [])
        has_children = bool(evidence_rows)
        expand_indicator = "▶ " if has_children else "  "
        
        feather_display = ", ".join(sorted(base_feathers)[:2]) + ("..." if len(base_feathers) > 2 else "")
        
        item = QTreeWidgetItem([
            f"{expand_indicator}⏱️ Anchor",
            feather_display,
            score_str,
            semantic_value,  # New semantic column
            str(count),
            artifact_info
        ])
        item.setForeground(0, QBrush(QColor("#FFC107")))
        
        # Color score and add tooltip
        if score >= 0.7:
            item.setForeground(2, QBrush(QColor("#4CAF50")))  # Green
        elif score >= 0.4:
            item.setForeground(2, QBrush(QColor("#FF9800")))  # Orange
        elif score > 0:
            item.setForeground(2, QBrush(QColor("#F44336")))  # Red
        
        # Build comprehensive tooltip
        tooltip_lines = []
        if start_time:
            tooltip_lines.append(f"Start: {start_time}")
        if end_time and end_time != start_time:
            tooltip_lines.append(f"End: {end_time}")
        if record_count > 0:
            tooltip_lines.append(f"Records: {record_count}")
        
        # Add scoring information
        if score > 0:
            tooltip_lines.append(f"\n📊 Scoring:")
            tooltip_lines.append(f"  Score: {score:.3f}")
            if interpretation:
                tooltip_lines.append(f"  {interpretation}")
        
        # Add confidence information
        confidence_score = anchor.get('confidence_score')
        confidence_category = anchor.get('confidence_category')
        if confidence_score is not None:
            tooltip_lines.append(f"  Confidence: {confidence_score:.2f} ({confidence_category or 'Unknown'})")
        
        # Add semantic data if available
        semantic_data = anchor.get('semantic_data')
        if semantic_data and isinstance(semantic_data, dict) and not semantic_data.get('_unavailable'):
            tooltip_lines.append(f"\n🔗 Semantic Mapping:")
            for key, value in semantic_data.items():
                if not key.startswith('_') and value:
                    tooltip_lines.append(f"  {key}: {value}")
        
        if tooltip_lines:
            item.setToolTip(0, "\n".join(tooltip_lines))
        
        item.setData(0, Qt.UserRole, {'type': 'anchor', 'data': anchor})
        
        for ev in anchor.get('evidence_rows', []):
            item.addChild(self._create_evidence_item(ev))
        
        return item
    
    def _create_evidence_item(self, evidence: Dict) -> QTreeWidgetItem:
        """Create evidence tree item showing original filename."""
        ts = evidence.get('timestamp', '')
        if isinstance(ts, str) and len(ts) > 11:
            ts = ts[11:19]
        
        # Extract original filename from evidence data
        data = evidence.get('data', {})
        original_name = ""
        
        # Try to get the original filename from various fields
        name_fields = ['name', 'filename', 'file_name', 'fn_filename', 'executable_name', 
                       'Source_Name', 'original_filename', 'app_name', 'value', 'Value',
                       'FileName', 'Name']
        for field in name_fields:
            if field in data and data[field]:
                original_name = str(data[field])
                break
        
        # If no name found, try to extract from path
        if not original_name:
            path_fields = ['path', 'file_path', 'Local_Path', 'app_path', 'full_path', 
                          'reconstructed_path', 'Path', 'FilePath']
            for field in path_fields:
                if field in data and data[field]:
                    path_val = str(data[field])
                    if '\\' in path_val or '/' in path_val:
                        from pathlib import Path
                        original_name = Path(path_val.replace('\\', '/')).name
                        break
        
        # Fallback to artifact type
        if not original_name:
            original_name = evidence.get('artifact', '-')
        
        # Check for semantic info
        semantic_info = evidence.get('semantic_info', {})
        has_semantic = bool(semantic_info)
        
        # Extract semantic value for display
        semantic_value = "-"
        if has_semantic:
            # Get first semantic value
            for field, value in semantic_info.items():
                if value:
                    semantic_value = str(value)
                    break
        
        # 6 columns - removed Time column
        item = QTreeWidgetItem([
            f"📄 {original_name}" + (" 🔍" if has_semantic else ""),
            evidence.get('feather_id', ''),
            "-",  # Score column (evidence doesn't have individual scores)
            semantic_value,  # New semantic column
            "1",
            evidence.get('artifact', '-')
        ])
        item.setForeground(0, QBrush(QColor("#4CAF50")))
        
        # Add semantic tooltip if available
        if has_semantic:
            tooltip_lines = ["Semantic Information:"]
            for field, value in semantic_info.items():
                tooltip_lines.append(f"  {field}: {value}")
            item.setToolTip(0, "\n".join(tooltip_lines))
        
        item.setData(0, Qt.UserRole, {'type': 'evidence', 'data': evidence})
        return item
    
    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle item click to show scoring details."""
        # Toggle expand/collapse when clicking on first column (where the arrow is)
        if column == 0 and item.childCount() > 0:
            text = item.text(0)
            if text.startswith("▶ ") or text.startswith("▼ "):
                if item.isExpanded():
                    item.setExpanded(False)
                else:
                    item.setExpanded(True)
                return
        
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        
        item_type = data.get('type')
        item_data = data.get('data', {})
        
        # Emit signal for external handlers
        self.match_selected.emit({'type': item_type, 'data': item_data})
    
    def _on_item_expanded(self, item: QTreeWidgetItem):
        """Update expand indicator when item is expanded."""
        text = item.text(0)
        if text.startswith("▶ "):
            item.setText(0, "▼ " + text[2:])
    
    def _on_item_collapsed(self, item: QTreeWidgetItem):
        """Update expand indicator when item is collapsed."""
        text = item.text(0)
        if text.startswith("▼ "):
            item.setText(0, "▶ " + text[2:])
    
    def _update_stats(self, results: Dict):
        """Update statistics tables (Types, Roles, Scores only - feather stats are in Summary)."""
        # Identity types
        types = {}
        for i in self.identities:
            t = i.get('identity_type', 'unknown')
            types[t] = types.get(t, 0) + 1
        
        self.type_table.setRowCount(len(types))
        for row, (t, c) in enumerate(sorted(types.items())):
            self.type_table.setItem(row, 0, QTableWidgetItem(t.capitalize()))
            self.type_table.setItem(row, 1, QTableWidgetItem(str(c)))
        
        # Evidence roles
        roles = {'Primary': 0, 'Secondary': 0}
        for i in self.identities:
            # Handle both old and new format
            sub_identities = i.get('sub_identities', [])
            if sub_identities:
                for sub in sub_identities:
                    for a in sub.get('anchors', []):
                        for e in a.get('evidence_rows', []):
                            r = e.get('role', 'secondary').capitalize()
                            roles[r] = roles.get(r, 0) + 1
            else:
                for a in i.get('anchors', []):
                    for e in a.get('evidence_rows', []):
                        r = e.get('role', 'secondary').capitalize()
                        roles[r] = roles.get(r, 0) + 1
        
        self.role_table.setRowCount(len(roles))
        for row, (r, c) in enumerate(roles.items()):
            self.role_table.setItem(row, 0, QTableWidgetItem(r))
            self.role_table.setItem(row, 1, QTableWidgetItem(str(c)))
        
        # Scoring statistics
        score_ranges = {'High (≥0.7)': 0, 'Medium (0.4-0.7)': 0, 'Low (<0.4)': 0, 'No Score': 0}
        for i in self.identities:
            sub_identities = i.get('sub_identities', [])
            if sub_identities:
                for sub in sub_identities:
                    for a in sub.get('anchors', []):
                        ws = a.get('weighted_score', {})
                        if isinstance(ws, dict) and ws.get('score', 0) > 0:
                            score = ws.get('score', 0)
                            if score >= 0.7:
                                score_ranges['High (≥0.7)'] += 1
                            elif score >= 0.4:
                                score_ranges['Medium (0.4-0.7)'] += 1
                            else:
                                score_ranges['Low (<0.4)'] += 1
                        else:
                            score_ranges['No Score'] += 1
            else:
                for a in i.get('anchors', []):
                    ws = a.get('weighted_score', {})
                    if isinstance(ws, dict) and ws.get('score', 0) > 0:
                        score = ws.get('score', 0)
                        if score >= 0.7:
                            score_ranges['High (≥0.7)'] += 1
                        elif score >= 0.4:
                            score_ranges['Medium (0.4-0.7)'] += 1
                        else:
                            score_ranges['Low (<0.4)'] += 1
                    else:
                        score_ranges['No Score'] += 1
        
        # Update scoring indicator
        total_scored = score_ranges['High (≥0.7)'] + score_ranges['Medium (0.4-0.7)'] + score_ranges['Low (<0.4)']
        if total_scored > 0:
            self.scoring_enabled = True
            self.scoring_lbl.setText(f"📊 Scoring: On ({total_scored})")
            self.scoring_lbl.setStyleSheet("font-size: 7pt; color: #4CAF50;")
        else:
            self.scoring_enabled = False
            self.scoring_lbl.setText("📊 Scoring: Off")
            self.scoring_lbl.setStyleSheet("font-size: 7pt; color: #888;")
        
        # Populate scoring table
        self.scoring_table.setRowCount(len(score_ranges))
        for row, (range_name, count) in enumerate(score_ranges.items()):
            self.scoring_table.setItem(row, 0, QTableWidgetItem(range_name))
            count_item = QTableWidgetItem(str(count))
            # Color code
            if 'High' in range_name:
                count_item.setForeground(QBrush(QColor("#4CAF50")))
            elif 'Medium' in range_name:
                count_item.setForeground(QBrush(QColor("#FF9800")))
            elif 'Low' in range_name:
                count_item.setForeground(QBrush(QColor("#F44336")))
            self.scoring_table.setItem(row, 1, count_item)
    
    def _on_search_text_changed(self):
        """Handle search text changes with debouncing."""
        self.search_timer.stop()
        self.search_timer.start()
    
    def _apply_filters(self):
        """Apply filters with pagination, including semantic value search."""
        text = self.identity_filter.text().lower()
        feather = self.feather_filter.currentText()
        min_ev = int(self.min_filter.currentText())
        
        filtered = []
        for i in self.identities:
            # Search in identity name
            name = i.get('primary_name', '').lower()
            name_match = not text or text in name
            
            # Search in semantic values if name doesn't match
            semantic_match = False
            if text and not name_match:
                # Get all semantic values for this identity
                sub_identities = i.get('sub_identities', [])
                anchors_to_check = []
                if sub_identities:
                    for sub in sub_identities:
                        anchors_to_check.extend(sub.get('anchors', []))
                else:
                    anchors_to_check = i.get('anchors', [])
                
                # Check if search text matches any semantic value using helper
                for anchor in anchors_to_check:
                    semantic_data = anchor.get('semantic_data')
                    if _search_semantic_data(semantic_data, text):
                        semantic_match = True
                        break
            
            # Skip if neither name nor semantic value matches
            if text and not name_match and not semantic_match:
                continue
            
            # Handle both old format (anchors) and new format (sub_identities)
            sub_identities = i.get('sub_identities', [])
            if sub_identities:
                # New format: anchors are inside sub_identities
                all_anchors = []
                for sub in sub_identities:
                    all_anchors.extend(sub.get('anchors', []))
            else:
                # Old format: anchors directly on identity
                all_anchors = i.get('anchors', [])
            
            if feather != "All":
                # Match against base feather name (without numeric suffix)
                has = False
                for a in all_anchors:
                    for f in a.get('feathers', []):
                        # Extract base name from feather
                        display_name = f.split('/')[-1] if '/' in f else f
                        base_name = display_name.rsplit('_', 1)[0] if '_' in display_name and display_name.rsplit('_', 1)[-1].isdigit() else display_name
                        if feather == base_name:
                            has = True
                            break
                    if has:
                        break
                if not has:
                    continue
            
            total = sum(a.get('evidence_count', len(a.get('evidence_rows', []))) for a in all_anchors)
            if total < min_ev:
                continue
            
            filtered.append(i)
        
        self.filtered_identities = filtered
        self.current_page = 0
        self._populate_current_page()
    def _on_search_text_changed(self):
        """Handle search text changes with debouncing."""
        self.search_timer.stop()
        self.search_timer.start()

    
    def _reset_filters(self):
        """Reset filters."""
        self.identity_filter.clear()
        self.feather_filter.setCurrentIndex(0)
        self.min_filter.setCurrentIndex(0)
        self.filtered_identities = self.identities.copy()
        self.current_page = 0
        self._populate_current_page()
    
    def _on_double_click(self, item: QTreeWidgetItem, column: int):
        """Handle double-click."""
        data = item.data(0, Qt.UserRole)
        if data:
            dialog = IdentityDetailDialog(data.get('type'), data.get('data', {}), self)
            dialog.exec_()


class IdentityDetailDialog(QDialog):
    """Compact detail dialog."""
    
    def __init__(self, item_type: str, data: Dict, parent=None):
        super().__init__(parent)
        self.item_type = item_type
        self.data = data
        self.setup_ui()
    
    def setup_ui(self):
        """Setup dialog."""
        self.setWindowTitle(f"{self.item_type.capitalize()} Details")
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
        
        # Only add header for anchor and evidence types
        # For identity type, the Summary tab contains all header info
        if self.item_type not in ['identity']:
            header = self._create_header()
            layout.addWidget(header)
        
        # Content
        if self.item_type == 'identity':
            content = self._create_identity_content()
        elif self.item_type == 'anchor':
            content = self._create_anchor_content()
        else:
            content = self._create_evidence_content()
        
        # Ensure content expands to fill available space
        from PyQt5.QtWidgets import QSizePolicy
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
        """Create header."""
        frame = QFrame()
        frame.setMaximumHeight(50)
        layout = QHBoxLayout(frame)
        
        if self.item_type == 'identity':
            layout.addWidget(QLabel(f"<b>Identity:</b> {self.data.get('primary_name', 'Unknown')}"))
            layout.addWidget(QLabel(f"<b>Anchors:</b> {len(self.data.get('anchors', []))}"))
        elif self.item_type == 'anchor':
            layout.addWidget(QLabel(f"<b>Time:</b> {self.data.get('start_time', '')}"))
            layout.addWidget(QLabel(f"<b>Feathers:</b> {', '.join(self.data.get('feathers', []))}"))
        else:
            layout.addWidget(QLabel(f"<b>Feather:</b> {self.data.get('feather_id', '')}"))
            layout.addWidget(QLabel(f"<b>Artifact:</b> {self.data.get('artifact', '')}"))
        
        layout.addStretch()
        return frame
    
    def _create_identity_content(self) -> QWidget:
        """Create identity content with Summary tab + per-feather tabs."""
        tabs = QTabWidget()
        # Tabs matching the main app tab style - dark background, smaller text
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
        all_anchors = []
        timestamps = []
        
        sub_identities = self.data.get('sub_identities', [])
        if sub_identities:
            for sub in sub_identities:
                for anchor in sub.get('anchors', []):
                    all_anchors.append(anchor)
                    if anchor.get('start_time'):
                        timestamps.append(anchor.get('start_time'))
                    for ev in anchor.get('evidence_rows', []):
                        fid = ev.get('feather_id', 'Unknown')
                        if fid not in feather_records:
                            feather_records[fid] = []
                        feather_records[fid].append(ev)
        else:
            for anchor in self.data.get('anchors', []):
                all_anchors.append(anchor)
                if anchor.get('start_time'):
                    timestamps.append(anchor.get('start_time'))
                for ev in anchor.get('evidence_rows', []):
                    fid = ev.get('feather_id', 'Unknown')
                    if fid not in feather_records:
                        feather_records[fid] = []
                    feather_records[fid].append(ev)
        
        # Tab 1: Summary - REMOVED per user request
        # summary_tab = self._create_summary_tab(sub_identities, all_anchors, timestamps, feather_records)
        # tabs.addTab(summary_tab, "📊 Summary")
        
        # Per-feather tabs (now the only tabs)
        for fid in sorted(feather_records.keys()):
            records = feather_records[fid]
            tab = self._create_feather_tab(fid, records)
            tab_label = f"{fid} ({len(records)})"
            if len(tab_label) > 20:
                tab_label = f"{fid[:15]}... ({len(records)})"
            tabs.addTab(tab, tab_label)
        
        return tabs
    
    def _create_summary_tab(self, sub_identities: list, all_anchors: list, 
                            timestamps: list, feather_records: dict) -> QWidget:
        """Create Summary tab with identity overview."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Identity name header
        name = self.data.get('primary_name', 'Unknown')
        name_lbl = QLabel(f"<h2 style='color: #2196F3;'>{name}</h2>")
        layout.addWidget(name_lbl)
        
        # Statistics frame
        stats_frame = QFrame()
        stats_frame.setStyleSheet("background-color: #1a1a2e; border: 1px solid #333; padding: 8px;")
        stats_layout = QHBoxLayout(stats_frame)
        
        # Sub-identities count
        sub_count = len(sub_identities) if sub_identities else 0
        stats_layout.addWidget(QLabel(f"<b>Variants:</b> {sub_count}"))
        
        # Anchors count
        stats_layout.addWidget(QLabel(f"<b>Anchors:</b> {len(all_anchors)}"))
        
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
        
        # Sub-identities list (if any)
        if sub_identities:
            variants_group = QGroupBox("Filename Variants")
            variants_group.setStyleSheet("""
                QGroupBox { 
                    font-size: 9pt; font-weight: bold; color: #aaa;
                    padding-top: 12px; margin-top: 8px;
                    border: 1px solid #333; background-color: #1a1a2e;
                }
                QGroupBox::title { subcontrol-origin: margin; padding: 0 5px; }
            """)
            variants_layout = QVBoxLayout(variants_group)
            
            variants_table = QTableWidget()
            variants_table.setColumnCount(3)
            variants_table.setHorizontalHeaderLabels(["Original Name", "Anchors", "Feathers"])
            variants_table.setRowCount(len(sub_identities))
            variants_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            variants_table.setAlternatingRowColors(True)
            
            for row, sub in enumerate(sub_identities):
                variants_table.setItem(row, 0, QTableWidgetItem(sub.get('original_name', 'Unknown')))
                variants_table.setItem(row, 1, QTableWidgetItem(str(len(sub.get('anchors', [])))))
                variants_table.setItem(row, 2, QTableWidgetItem(", ".join(sub.get('feathers_found', []))))
            
            variants_layout.addWidget(variants_table)
            layout.addWidget(variants_group)
        
        layout.addStretch()
        return widget
    
    def _create_feather_tab(self, feather_id: str, records: list) -> QWidget:
        """Create tab showing all records from a specific feather with search."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Header - compact, takes minimal space
        header = QLabel(f"<b>{feather_id}</b> - {len(records)} records")
        header.setStyleSheet("font-size: 9pt; color: #aaa; padding: 4px;")
        header.setMaximumHeight(30)  # Limit header height
        layout.addWidget(header)
        
        # Search box - compact, takes minimal space
        search_box = QLineEdit()
        search_box.setPlaceholderText("Search records...")
        search_box.setStyleSheet("padding: 4px; font-size: 8pt;")
        search_box.setMaximumHeight(30)  # Limit search box height
        layout.addWidget(search_box)
        
        # Collect all unique keys from all records
        all_keys = set()
        for rec in records:
            data = rec.get('data', {})
            if isinstance(data, dict):
                all_keys.update(data.keys())
        
        # Create table with all fields - THIS SHOULD TAKE 75% OF SPACE
        table = QTableWidget()
        cols = ['Timestamp', 'Artifact', 'Role'] + sorted(list(all_keys))
        table.setColumnCount(len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.setRowCount(len(records))
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)  # Enable column sorting
        
        # Set size policy to expand and fill available space
        from PyQt5.QtWidgets import QSizePolicy
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
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
        
        # Add table with stretch factor to take most of the space
        # The stretch factor makes the table expand to fill available space
        layout.addWidget(table, stretch=10)  # High stretch factor = takes most space
        
        return widget
    
    def _create_sub_identity_tab(self, sub_identity: Dict) -> QWidget:
        """Create tab content for a sub-identity."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Header with sub-identity info
        header = QLabel(f"<b>Original Name:</b> {sub_identity.get('original_name', 'Unknown')} | "
                       f"<b>Anchors:</b> {len(sub_identity.get('anchors', []))} | "
                       f"<b>Feathers:</b> {', '.join(sub_identity.get('feathers_found', []))}")
        header.setStyleSheet("font-size: 8pt; color: #aaa; padding: 4px;")
        layout.addWidget(header)
        
        # Create inner tabs for anchors
        anchor_tabs = QTabWidget()
        anchor_tabs.setStyleSheet("""
            QTabBar::tab { 
                font-size: 6pt; 
                padding: 2px 8px; 
                background-color: #1a1a2e;
                color: #777;
                border: 1px solid #333;
            }
            QTabBar::tab:selected { 
                background-color: #2a3a5e; 
                color: #ccc;
            }
        """)
        
        for i, anchor in enumerate(sub_identity.get('anchors', []), 1):
            tab = self._create_anchor_table(anchor)
            time = anchor.get('start_time', f'Anchor {i}')
            if isinstance(time, str) and len(time) > 12:
                time = time[11:19] if len(time) > 11 else time[:12]
            anchor_tabs.addTab(tab, f"{time}")
        
        layout.addWidget(anchor_tabs)
        return widget
    
    def _create_anchor_table(self, anchor: Dict) -> QWidget:
        """Create anchor evidence table."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        table = QTableWidget()
        rows = anchor.get('evidence_rows', [])
        
        if rows:
            all_keys = set()
            for r in rows:
                if 'data' in r and isinstance(r['data'], dict):
                    all_keys.update(r['data'].keys())
            
            cols = ['Feather', 'Artifact', 'Time', 'Role'] + sorted(list(all_keys))[:6]
            table.setColumnCount(len(cols))
            table.setHorizontalHeaderLabels(cols)
            table.setRowCount(len(rows))
            
            for row, ev in enumerate(rows):
                table.setItem(row, 0, QTableWidgetItem(ev.get('feather_id', '')))
                table.setItem(row, 1, QTableWidgetItem(ev.get('artifact', '')))
                table.setItem(row, 2, QTableWidgetItem(str(ev.get('timestamp', ''))[:19]))
                table.setItem(row, 3, QTableWidgetItem(ev.get('role', 'secondary').capitalize()))
                
                data = ev.get('data', {})
                for col, key in enumerate(sorted(list(all_keys))[:6], 4):
                    val = str(data.get(key, ''))[:60]
                    item = QTableWidgetItem(val)
                    item.setToolTip(str(data.get(key, '')))
                    table.setItem(row, col, item)
            
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            table.horizontalHeader().setStretchLastSection(True)
        
        table.setAlternatingRowColors(True)
        layout.addWidget(table)
        return widget
    
    def _create_anchor_content(self) -> QWidget:
        """Create anchor content."""
        return self._create_anchor_table(self.data)
    
    def _create_evidence_content(self) -> QWidget:
        """Create evidence content with semantic mappings and feather records in table format."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Transform evidence structure to match expected format
        # Evidence from tree: {'feather_id': 'X', 'data': {...}, 'semantic_info': {...}}
        # Expected format: {'feather_records': {'X': {...}}, 'semantic_data': {...}}
        
        feather_id = self.data.get('feather_id', 'Unknown')
        feather_data = self.data.get('data', {})
        semantic_info = self.data.get('semantic_info', {})
        
        # Build feather_records dict
        feather_records = {feather_id: feather_data} if feather_data else {}
        
        # Build semantic_data dict (transform semantic_info to semantic_data structure)
        semantic_data = {}
        if semantic_info:
            # semantic_info is a flat dict, wrap it in the expected structure
            semantic_data[feather_id] = {
                'identity_type': feather_id,
                'semantic_mappings': [{
                    'semantic_value': str(v),
                    'rule_name': k,
                    'category': 'Unknown',
                    'confidence': 1.0,
                    'severity': 'info'
                } for k, v in semantic_info.items() if v]
            }
        
        # Determine if we have semantic data and feather records to display
        has_semantic_data = bool(semantic_data and isinstance(semantic_data, dict))
        has_feather_records = bool(feather_records and isinstance(feather_records, dict))
        
        # Check if we have semantic_data to display
        if has_semantic_data:
            # Add Semantic Mappings section
            semantic_group = QGroupBox("🔍 Semantic Mappings")
            semantic_group.setStyleSheet("""
                QGroupBox { 
                    font-size: 9pt; font-weight: bold; color: #2196F3;
                    padding-top: 12px; margin-top: 8px;
                    border: 2px solid #2196F3; background-color: #1a1a2e;
                }
                QGroupBox::title { subcontrol-origin: margin; padding: 0 5px; }
            """)
            semantic_layout = QVBoxLayout(semantic_group)
            
            # Create semantic mappings table
            semantic_table = QTableWidget()
            semantic_table.setColumnCount(6)
            semantic_table.setHorizontalHeaderLabels([
                'Semantic Value', 'Identity Type', 'Rule Name', 
                'Category', 'Confidence', 'Severity'
            ])
            
            # Count total mappings
            total_mappings = 0
            for entry in semantic_data.values():
                if isinstance(entry, dict) and 'semantic_mappings' in entry:
                    total_mappings += len(entry['semantic_mappings'])
            
            semantic_table.setRowCount(total_mappings)
            
            row = 0
            for key, entry in sorted(semantic_data.items()):
                if isinstance(entry, dict) and 'semantic_mappings' in entry:
                    mappings = entry['semantic_mappings']
                    identity_type = entry.get('identity_type', 'unknown')
                    
                    for mapping in mappings:
                        semantic_table.setItem(row, 0, QTableWidgetItem(mapping.get('semantic_value', '')))
                        semantic_table.setItem(row, 1, QTableWidgetItem(identity_type))
                        semantic_table.setItem(row, 2, QTableWidgetItem(mapping.get('rule_name', '')))
                        semantic_table.setItem(row, 3, QTableWidgetItem(mapping.get('category', '')))
                        
                        confidence = mapping.get('confidence', 0)
                        conf_item = QTableWidgetItem(f"{confidence:.0%}")
                        semantic_table.setItem(row, 4, conf_item)
                        
                        severity = mapping.get('severity', 'info')
                        sev_item = QTableWidgetItem(severity.upper())
                        # Color code severity
                        if severity == 'high':
                            sev_item.setForeground(QColor('#ff5252'))
                        elif severity == 'medium':
                            sev_item.setForeground(QColor('#ffa726'))
                        else:
                            sev_item.setForeground(QColor('#66bb6a'))
                        semantic_table.setItem(row, 5, sev_item)
                        
                        row += 1
            
            semantic_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            semantic_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            semantic_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            semantic_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
            semantic_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
            semantic_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
            semantic_table.setAlternatingRowColors(True)
            semantic_table.setMaximumHeight(200)
            
            semantic_layout.addWidget(semantic_table)
            # Add with no stretch factor when semantic data exists
            layout.addWidget(semantic_group)
        
        # Check if we have feather_records to display
        if has_feather_records:
            # Add Feather Records section
            feather_group = QGroupBox("📋 Feather Records")
            feather_group.setStyleSheet("""
                QGroupBox { 
                    font-size: 9pt; font-weight: bold; color: #aaa;
                    padding-top: 12px; margin-top: 8px;
                    border: 1px solid #333; background-color: #1a1a2e;
                }
                QGroupBox::title { subcontrol-origin: margin; padding: 0 5px; }
            """)
            feather_layout = QVBoxLayout(feather_group)
            
            # Create tabs for each feather
            feather_tabs = QTabWidget()
            feather_tabs.setStyleSheet("""
                QTabBar::tab { 
                    font-size: 7pt; 
                    padding: 3px 10px; 
                    background-color: #1a1a2e;
                    color: #777;
                    border: 1px solid #333;
                }
                QTabBar::tab:selected { 
                    background-color: #2a3a5e; 
                    color: #ccc;
                }
            """)
            
            for feather_name, feather_data_item in sorted(feather_records.items()):
                if isinstance(feather_data_item, list) and feather_data_item:
                    # Create table for this feather's records
                    feather_table = self._create_feather_records_table(feather_name, feather_data_item)
                    feather_tabs.addTab(feather_table, f"{feather_name} ({len(feather_data_item)})")
                elif isinstance(feather_data_item, dict):
                    # Single record as dict
                    feather_table = self._create_feather_records_table(feather_name, [feather_data_item])
                    feather_tabs.addTab(feather_table, feather_name)
            
            feather_layout.addWidget(feather_tabs)
            
            # Add with stretch factor 1 to fill remaining space
            # If semantic data exists, this takes remaining space (80%)
            # If no semantic data, this takes all available space (100%)
            layout.addWidget(feather_group, 1)
        
        # Fallback: display basic data if no semantic or feather records
        if not has_semantic_data and not has_feather_records:
            table = QTableWidget()
            table.setColumnCount(2)
            table.setHorizontalHeaderLabels(['Field', 'Value'])
            table.setRowCount(len(self.data))
            
            for row, (k, v) in enumerate(sorted(self.data.items())):
                table.setItem(row, 0, QTableWidgetItem(str(k)))
                val = str(v)[:150]
                item = QTableWidgetItem(val)
                item.setToolTip(str(v))
                table.setItem(row, 1, item)
            
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            table.setAlternatingRowColors(True)
            # Add with stretch factor 1 to fill available space
            layout.addWidget(table, 1)
        
        return widget
    
    def _create_feather_records_table(self, feather_name: str, records: list) -> QWidget:
        """Create a table displaying feather records with vertical layout (fields as rows)."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Handle case where records might be a list with a single dict
        # Database format: {'prefetch': [{'field': 'value', ...}]}
        # Expected format: [{'field': 'value', ...}]
        if records and len(records) == 1 and isinstance(records[0], dict):
            # Check if it's already the correct format (has actual field names)
            first_record = records[0]
            # If it has typical feather fields, it's correct
            if any(key in first_record for key in ['filename', 'executable_name', 'path', 'timestamp', 'name']):
                # Already correct format
                pass
            else:
                # Might be wrapped, but let's use it as-is
                pass
        
        # Collect all unique keys from all records
        all_keys = set()
        for record in records:
            if isinstance(record, dict):
                all_keys.update(record.keys())
        
        # Remove internal/metadata keys
        excluded_keys = {'semantic_data', 'semantic_mappings', '_metadata', '_internal', '_feather_id', '_table'}
        all_keys = sorted([k for k in all_keys if k not in excluded_keys])
        
        # Create table with VERTICAL layout (fields as rows)
        # Columns: Record 1 | Record 2 | ... | Record N
        # Rows: Field names (shown in vertical header)
        table = QTableWidget()
        table.setRowCount(len(all_keys))  # Each field is a row
        table.setColumnCount(len(records))  # One column per record
        
        # Set headers
        headers = [f"Record {i+1}" if len(records) > 1 else "Value" for i in range(len(records))]
        table.setHorizontalHeaderLabels(headers)
        
        # Set vertical headers (field names)
        table.setVerticalHeaderLabels(all_keys)
        
        table.setAlternatingRowColors(True)
        
        # Populate table
        for row, key in enumerate(all_keys):
            # Populate values from each record
            for col, record in enumerate(records):
                if isinstance(record, dict):
                    value = record.get(key, '')
                    
                    # Handle different value types
                    if isinstance(value, (list, dict)):
                        display_val = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
                    else:
                        display_val = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
                    
                    item = QTableWidgetItem(display_val)
                    item.setToolTip(str(value))  # Full value in tooltip
                    table.setItem(row, col, item)
        
        # Enable column resizing
        for i in range(len(records)):
            table.horizontalHeader().setSectionResizeMode(i, QHeaderView.Stretch)  # Value columns
        
        # Add row selection highlighting
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        
        layout.addWidget(table)
        return widget