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

from collections import defaultdict
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QLineEdit, QPushButton, QGroupBox, QDialog, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QMessageBox, QTextEdit, QTabWidget, QFrame, QProgressDialog, QApplication
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QBrush
from typing import List, Dict, Any


class IdentityResultsView(QWidget):
    """Compact Identity-Based Correlation Results View with Pagination and Scoring."""
    
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
        self.setup_ui()
    
    def setup_ui(self):
        """Setup compact UI with labeled filters."""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(2)
        main_layout.setContentsMargins(4, 4, 4, 4)
        
        # === TOP: Summary + Filters (single compact row) ===
        top_frame = QFrame()
        top_frame.setMaximumHeight(32)
        top_layout = QHBoxLayout(top_frame)
        top_layout.setSpacing(8)
        top_layout.setContentsMargins(4, 2, 4, 2)
        
        # Summary labels (compact)
        self.identities_lbl = QLabel("Identities: 0")
        self.identities_lbl.setStyleSheet("color: #2196F3; font-weight: bold; font-size: 8pt;")
        top_layout.addWidget(self.identities_lbl)
        
        self.anchors_lbl = QLabel("Anchors: 0")
        self.anchors_lbl.setStyleSheet("font-size: 7pt;")
        top_layout.addWidget(self.anchors_lbl)
        
        self.evidence_lbl = QLabel("Evidence: 0")
        self.evidence_lbl.setStyleSheet("font-size: 7pt;")
        top_layout.addWidget(self.evidence_lbl)
        
        self.time_lbl = QLabel("Time: 0s")
        self.time_lbl.setStyleSheet("font-size: 7pt;")
        top_layout.addWidget(self.time_lbl)
        
        self.feathers_used_lbl = QLabel("Feathers: 0")
        self.feathers_used_lbl.setStyleSheet("color: #4CAF50; font-size: 7pt;")
        top_layout.addWidget(self.feathers_used_lbl)
        
        # Scoring indicator
        self.scoring_lbl = QLabel("📊 Scoring: Off")
        self.scoring_lbl.setStyleSheet("font-size: 7pt; color: #888;")
        top_layout.addWidget(self.scoring_lbl)
        
        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #444;")
        top_layout.addWidget(sep)
        
        # Filters with labels
        search_lbl = QLabel("Search:")
        search_lbl.setStyleSheet("font-size: 7pt; color: #aaa;")
        top_layout.addWidget(search_lbl)
        
        self.identity_filter = QLineEdit()
        self.identity_filter.setPlaceholderText("name...")
        self.identity_filter.setMaximumWidth(90)
        self.identity_filter.setStyleSheet("font-size: 7pt; padding: 1px 3px;")
        self.identity_filter.textChanged.connect(self._apply_filters)
        top_layout.addWidget(self.identity_filter)
        
        feather_lbl = QLabel("Feather:")
        feather_lbl.setStyleSheet("font-size: 7pt; color: #aaa;")
        top_layout.addWidget(feather_lbl)
        
        self.feather_filter = QComboBox()
        self.feather_filter.addItem("All")
        self.feather_filter.setMaximumWidth(90)
        self.feather_filter.setStyleSheet("font-size: 7pt;")
        self.feather_filter.currentTextChanged.connect(self._apply_filters)
        top_layout.addWidget(self.feather_filter)
        
        min_lbl = QLabel("Min:")
        min_lbl.setStyleSheet("font-size: 7pt; color: #aaa;")
        top_layout.addWidget(min_lbl)
        
        self.min_filter = QComboBox()
        self.min_filter.addItems(["1", "2", "3", "5", "10"])
        self.min_filter.setMaximumWidth(35)
        self.min_filter.setStyleSheet("font-size: 7pt;")
        self.min_filter.currentTextChanged.connect(self._apply_filters)
        top_layout.addWidget(self.min_filter)
        
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
        
        # Feather Contribution
        self.feather_table = self._create_compact_table(["Feather", "Rec", "ID"])
        stats_layout.addWidget(self._wrap_table("Feathers", self.feather_table), stretch=2)
        
        # Identity Types
        self.type_table = self._create_compact_table(["Type", "#"])
        stats_layout.addWidget(self._wrap_table("Types", self.type_table), stretch=1)
        
        # Evidence Roles
        self.role_table = self._create_compact_table(["Role", "#"])
        stats_layout.addWidget(self._wrap_table("Roles", self.role_table), stretch=1)
        
        # Scoring Summary (new)
        self.scoring_table = self._create_compact_table(["Score Range", "#"])
        stats_layout.addWidget(self._wrap_table("Scores", self.scoring_table), stretch=1)
        
        main_layout.addWidget(stats_frame)
    
    def _create_tree(self) -> QTreeWidget:
        """Create tree with app-matching background and score column."""
        tree = QTreeWidget()
        tree.setHeaderLabels(["Identity / Anchor / Evidence", "Feathers", "Time", "Score", "Semantic", "Ev", "Artifact"])
        
        tree.setColumnWidth(0, 280)
        tree.setColumnWidth(1, 150)
        tree.setColumnWidth(2, 140)
        tree.setColumnWidth(3, 60)  # Score column
        tree.setColumnWidth(4, 120)  # Semantic column
        tree.setColumnWidth(5, 40)  # Evidence count
        tree.setColumnWidth(6, 80)  # Artifact
        
        tree.setAlternatingRowColors(True)
        tree.itemDoubleClicked.connect(self._on_double_click)
        tree.itemClicked.connect(self._on_item_clicked)
        
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
    
    def load_from_correlation_result(self, result):
        """Load from CorrelationResult object with progress indicator."""
        print(f"[IdentityResultsView] load_from_correlation_result called with {result.total_matches} matches")
        
        # Show progress dialog if we have many matches
        progress = None
        if result.total_matches > 100:
            progress = QProgressDialog("Loading identity data...", "Cancel", 0, 100, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(500)
            progress.setWindowTitle("Loading Results")
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
            
            # Main identity (normalized name)
            main_app = match.matched_application or "Unknown"
            
            if main_app not in identity_map:
                identity_map[main_app] = {
                    'identity_id': main_app,
                    'identity_type': 'name',
                    'primary_name': main_app,
                    'sub_identities': {},  # original_name -> sub_identity data
                    'feathers_found': set()
                }
            
            identity_map[main_app]['feathers_found'].update(match.feather_records.keys())
            
            # Extract original name from the first evidence row
            original_name = main_app
            for fid, data in match.feather_records.items():
                if isinstance(data, dict):
                    # Try to get original filename
                    for field in ['name', 'filename', 'file_name', 'fn_filename', 'executable_name',
                                  'Source_Name', 'original_filename', 'app_name', 'value', 'Value',
                                  'FileName', 'Name']:
                        if field in data and data[field]:
                            original_name = str(data[field])
                            break
                    if original_name != main_app:
                        break
                    # Try path
                    for field in ['path', 'file_path', 'Local_Path', 'app_path', 'full_path']:
                        if field in data and data[field]:
                            from pathlib import Path
                            path_val = str(data[field])
                            if '\\' in path_val or '/' in path_val:
                                original_name = Path(path_val.replace('\\', '/')).name
                                break
                    if original_name != main_app:
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
            self.identities_lbl.setStyleSheet("color: #FF9800; font-weight: bold; font-size: 8pt;")
            self.identities_lbl.setToolTip("Execution was cancelled by user. Showing partial results.")
        else:
            self.identities_lbl.setText(f"Identities: {identity_count:,}")
            self.identities_lbl.setStyleSheet("color: #2196F3; font-weight: bold; font-size: 8pt;")
            self.identities_lbl.setToolTip("")
        
        self.anchors_lbl.setText(f"Anchors: {stats.get('total_anchors', 0):,}")
        self.evidence_lbl.setText(f"Evidence: {stats.get('total_evidence', 0):,}")
        self.time_lbl.setText(f"Time: {stats.get('execution_time', 0):.1f}s")
        
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
        
        for f in sorted(feathers):
            # Remove path prefix (e.g., "feathers/") from display name
            display_name = f.split('/')[-1] if '/' in f else f
            self.feather_filter.addItem(display_name)
    
    def _populate_tree(self, identities: List[Dict]):
        """Populate tree with given identities (used internally)."""
        self.results_tree.clear()
        
        if not identities:
            # Show a message when there are no results
            empty_item = QTreeWidgetItem(["No correlation matches found", "", "", "", ""])
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
        
        name = identity.get('primary_name', 'Unknown')
        feather_str = ", ".join(sorted(feathers)[:2]) + ("..." if len(feathers) > 2 else "")
        sub_count = len(sub_identities) if sub_identities else 0
        
        # Calculate average score for identity
        avg_score = self._calculate_identity_score(identity)
        score_str = f"{avg_score:.2f}" if avg_score > 0 else "-"
        
        # Main identity item with blue diamond icon (7 columns now - added Semantic)
        item = QTreeWidgetItem([
            f"🔷 {name}" + (f" ({sub_count} variants)" if sub_count > 1 else ""),
            feather_str, 
            "", 
            score_str,
            "-",  # Semantic column (identities don't have semantic values)
            str(total_evidence), 
            f"{total_anchors} anchors"
        ])
        item.setFont(0, QFont("Segoe UI", 9, QFont.Bold))
        item.setForeground(0, QBrush(QColor("#2196F3")))
        
        # Color score based on value
        if avg_score >= 0.7:
            item.setForeground(3, QBrush(QColor("#4CAF50")))  # Green - high score
        elif avg_score >= 0.4:
            item.setForeground(3, QBrush(QColor("#FF9800")))  # Orange - medium score
        elif avg_score > 0:
            item.setForeground(3, QBrush(QColor("#F44336")))  # Red - low score
        
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
        
        original_name = sub_identity.get('original_name', 'Unknown')
        feather_str = ", ".join(sorted(feathers)[:2]) + ("..." if len(feathers) > 2 else "")
        avg_score = sum(scores) / len(scores) if scores else 0.0
        score_str = f"{avg_score:.2f}" if avg_score > 0 else "-"
        
        # Sub-identity item with folder icon (orange/yellow) - 7 columns now
        item = QTreeWidgetItem([
            f"📁 {original_name}",
            feather_str,
            "",
            score_str,
            "-",  # Semantic column (sub-identities don't have semantic values)
            str(evidence),
            f"{len(anchors)} anchors"
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
        
        # Get semantic value for display
        semantic_value = "-"
        semantic_data = anchor.get('semantic_data')
        if semantic_data and isinstance(semantic_data, dict) and not semantic_data.get('_unavailable'):
            # Extract first semantic value for display
            for key, value in semantic_data.items():
                if not key.startswith('_') and value:
                    if isinstance(value, dict) and 'semantic_value' in value:
                        semantic_value = str(value['semantic_value'])
                    elif isinstance(value, str):
                        semantic_value = value
                    break
        
        # 7 columns now - added Semantic column
        artifact_info = anchor.get('primary_artifact', '-')
        if record_count > 0:
            artifact_info = f"{artifact_info} ({record_count} rec)"
        
        item = QTreeWidgetItem([
            "⏱️ Anchor",
            ", ".join(feathers[:2]) + ("..." if len(feathers) > 2 else ""),
            time_display,
            score_str,
            semantic_value,  # New semantic column
            str(count),
            artifact_info
        ])
        item.setForeground(0, QBrush(QColor("#FFC107")))
        
        # Color score and add tooltip
        if score >= 0.7:
            item.setForeground(3, QBrush(QColor("#4CAF50")))  # Green
        elif score >= 0.4:
            item.setForeground(3, QBrush(QColor("#FF9800")))  # Orange
        elif score > 0:
            item.setForeground(3, QBrush(QColor("#F44336")))  # Red
        
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
        
        # 7 columns now - added Semantic column
        item = QTreeWidgetItem([
            f"📄 {original_name}" + (" 🔍" if has_semantic else ""),
            evidence.get('feather_id', ''),
            ts,
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
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        
        item_type = data.get('type')
        item_data = data.get('data', {})
        
        # Emit signal for external handlers
        self.match_selected.emit({'type': item_type, 'data': item_data})
    
    def _update_stats(self, results: Dict):
        """Update statistics tables."""
        # Feather contribution - use feather_metadata from results
        feather_metadata = results.get('feather_metadata', {})
        
        if feather_metadata:
            # Use the pre-calculated feather metadata - group by base name
            grouped_metadata = defaultdict(lambda: {'records_loaded': 0, 'identities_found': set()})
            for fid, meta in feather_metadata.items():
                # Extract base feather name (remove _number suffix)
                base_name = fid.rsplit('_', 1)[0] if '_' in fid else fid
                grouped_metadata[base_name]['records_loaded'] += meta.get('records_loaded', meta.get('records', 0))
                grouped_metadata[base_name]['identities_found'].add(meta.get('identities_found', 0))
            
            self.feather_table.setRowCount(len(grouped_metadata))
            for row, (base_name, meta) in enumerate(sorted(grouped_metadata.items(), 
                                                      key=lambda x: x[1]['records_loaded'], 
                                                      reverse=True)):
                # Remove path prefix (e.g., "feathers/") from display name
                display_name = base_name.split('/')[-1] if '/' in base_name else base_name
                self.feather_table.setItem(row, 0, QTableWidgetItem(display_name))
                records = meta['records_loaded']
                self.feather_table.setItem(row, 1, QTableWidgetItem(f"{records:,}"))
                identities = sum(meta['identities_found'])
                self.feather_table.setItem(row, 2, QTableWidgetItem(str(identities)))
        else:
            # Fallback: calculate from identities - group by base name
            feather_stats = {}
            for identity in self.identities:
                # Handle both old and new format
                sub_identities = identity.get('sub_identities', [])
                if sub_identities:
                    for sub in sub_identities:
                        for anchor in sub.get('anchors', []):
                            for f in anchor.get('feathers', []):
                                # Extract base feather name (remove _number suffix)
                                base_name = f.rsplit('_', 1)[0] if '_' in f else f
                                if base_name not in feather_stats:
                                    feather_stats[base_name] = {'records': 0, 'identities': set()}
                                feather_stats[base_name]['records'] += anchor.get('evidence_count', 0)
                                feather_stats[base_name]['identities'].add(identity.get('identity_id', ''))
                else:
                    for anchor in identity.get('anchors', []):
                        for f in anchor.get('feathers', []):
                            # Extract base feather name (remove _number suffix)
                            base_name = f.rsplit('_', 1)[0] if '_' in f else f
                            if base_name not in feather_stats:
                                feather_stats[base_name] = {'records': 0, 'identities': set()}
                            feather_stats[base_name]['records'] += anchor.get('evidence_count', 0)
                            feather_stats[base_name]['identities'].add(identity.get('identity_id', ''))
            
            self.feather_table.setRowCount(len(feather_stats))
            for row, (f, s) in enumerate(sorted(feather_stats.items())):
                # Remove path prefix (e.g., "feathers/") from display name
                display_name = f.split('/')[-1] if '/' in f else f
                self.feather_table.setItem(row, 0, QTableWidgetItem(display_name))
                self.feather_table.setItem(row, 1, QTableWidgetItem(str(s['records'])))
                self.feather_table.setItem(row, 2, QTableWidgetItem(str(len(s['identities']))))
        
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
    
    def _apply_filters(self):
        """Apply filters with pagination."""
        text = self.identity_filter.text().lower()
        feather = self.feather_filter.currentText()
        min_ev = int(self.min_filter.currentText())
        
        filtered = []
        for i in self.identities:
            name = i.get('primary_name', '').lower()
            if text and text not in name:
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
                has = any(feather in a.get('feathers', []) for a in all_anchors)
                if not has:
                    continue
            
            total = sum(a.get('evidence_count', len(a.get('evidence_rows', []))) for a in all_anchors)
            if total < min_ev:
                continue
            
            filtered.append(i)
        
        self.filtered_identities = filtered
        self.current_page = 0
        self._populate_current_page()
    
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
        
        # Tab 1: Summary
        summary_tab = self._create_summary_tab(sub_identities, all_anchors, timestamps, feather_records)
        tabs.addTab(summary_tab, "📊 Summary")
        
        # Per-feather tabs
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
        
        # Create table with all fields
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
        """Create evidence content."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        data = self.data.get('data', {})
        if data and isinstance(data, dict):
            table = QTableWidget()
            table.setColumnCount(2)
            table.setHorizontalHeaderLabels(['Field', 'Value'])
            table.setRowCount(len(data))
            
            for row, (k, v) in enumerate(sorted(data.items())):
                table.setItem(row, 0, QTableWidgetItem(str(k)))
                val = str(v)[:150]
                item = QTableWidgetItem(val)
                item.setToolTip(str(v))
                table.setItem(row, 1, item)
            
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            table.setAlternatingRowColors(True)
            layout.addWidget(table)
        else:
            text = QTextEdit()
            text.setReadOnly(True)
            text.setPlainText(str(self.data))
            layout.addWidget(text)
        
        return widget
