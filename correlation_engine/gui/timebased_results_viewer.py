"""
Time-Based Results Viewer
Display, filter, and analyze time-based correlation results.
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QGroupBox, QFormLayout,
    QPushButton, QLineEdit, QSlider, QCheckBox, QComboBox,
    QSplitter, QTextEdit, QMessageBox, QFileDialog, QDateTimeEdit,
    QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal, QDateTime
from PyQt5.QtGui import QColor
from .ui_styling import CorrelationEngineStyles


from ..engine.correlation_result import CorrelationResult, CorrelationMatch
from .scoring_breakdown_widget import ScoringBreakdownWidget


class TimeBasedResultsTableWidget(QTableWidget):
    """Table widget for displaying time-based correlation matches"""
    
    match_selected = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.all_matches: List[CorrelationMatch] = []
        self.filtered_matches: List[CorrelationMatch] = []
        
        self._init_ui()
    
    def _init_ui(self):
        """Initialize table"""
        # Set columns - added Interpretation column for weighted scoring
        self.setColumnCount(8)
        self.setHorizontalHeaderLabels([
            "Match ID", "Timestamp", "Score", "Interpretation",
            "Feather Count", "Time Spread (s)", "Application", "File Path"
        ])
        
        # Configure table
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSortingEnabled(True)
        
        # Resize columns
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        header.setSectionResizeMode(7, QHeaderView.Stretch)
        
        # Connect selection
        self.itemSelectionChanged.connect(self._on_selection_changed)
    
    def populate_results(self, matches: List[CorrelationMatch]):
        """Populate table with matches"""
        self.all_matches = matches
        self.filtered_matches = matches.copy()
        self._update_table()
    
    def _update_table(self):
        """Update table display"""
        self.setSortingEnabled(False)
        self.setRowCount(0)
        
        for match in self.filtered_matches:
            row = self.rowCount()
            self.insertRow(row)
            
            # Match ID
            self.setItem(row, 0, QTableWidgetItem(match.match_id[:8]))
            
            # Timestamp
            self.setItem(row, 1, QTableWidgetItem(match.timestamp))
            
            # Score - check if weighted scoring is used
            if match.weighted_score:
                score_value = match.weighted_score.get('score', match.match_score)
                score_item = QTableWidgetItem(f"{score_value:.2f}")
                score_item.setData(Qt.UserRole, score_value)
                
                # Color code based on interpretation
                interpretation = match.weighted_score.get('interpretation', '')
                if 'Confirmed' in interpretation:
                    score_item.setForeground(QColor(CorrelationEngineStyles.SCORE_CONFIRMED))
                elif 'Probable' in interpretation or 'Likely' in interpretation:
                    score_item.setForeground(QColor(CorrelationEngineStyles.SCORE_PROBABLE))
                elif 'Weak' in interpretation or 'Insufficient' in interpretation:
                    score_item.setForeground(QColor(CorrelationEngineStyles.SCORE_WEAK))
            else:
                score_item = QTableWidgetItem(f"{match.match_score:.2f}")
                score_item.setData(Qt.UserRole, match.match_score)
            
            self.setItem(row, 2, score_item)
            
            # Interpretation (for weighted scoring)
            if match.weighted_score:
                interpretation = match.weighted_score.get('interpretation', '-')
                interp_item = QTableWidgetItem(interpretation)
                if 'Confirmed' in interpretation:
                    interp_item.setForeground(QColor(CorrelationEngineStyles.SCORE_CONFIRMED))
                elif 'Probable' in interpretation or 'Likely' in interpretation:
                    interp_item.setForeground(QColor(CorrelationEngineStyles.SCORE_PROBABLE))
                elif 'Weak' in interpretation or 'Insufficient' in interpretation:
                    interp_item.setForeground(QColor(CorrelationEngineStyles.SCORE_WEAK))
                self.setItem(row, 3, interp_item)
            else:
                self.setItem(row, 3, QTableWidgetItem('-'))
            
            # Feather count
            count_item = QTableWidgetItem(str(match.feather_count))
            count_item.setData(Qt.UserRole, match.feather_count)
            self.setItem(row, 4, count_item)
            
            # Time spread
            spread_item = QTableWidgetItem(f"{match.time_spread_seconds:.1f}")
            spread_item.setData(Qt.UserRole, match.time_spread_seconds)
            self.setItem(row, 5, spread_item)
            
            # Application
            app = match.matched_application or "-"
            self.setItem(row, 6, QTableWidgetItem(app))
            
            # File path
            path = match.matched_file_path or "-"
            self.setItem(row, 7, QTableWidgetItem(path))
            
            # Store full match data
            self.item(row, 0).setData(Qt.UserRole + 1, match)
        
        self.setSortingEnabled(True)
    
    def apply_filters(self, filters: Dict[str, Any]):
        """Apply filter criteria"""
        self.filtered_matches = []
        
        for match in self.all_matches:
            # Application filter
            if filters.get('application'):
                if not match.matched_application:
                    continue
                if filters['application'].lower() not in match.matched_application.lower():
                    continue
            
            # File path filter
            if filters.get('file_path'):
                if not match.matched_file_path:
                    continue
                if filters['file_path'].lower() not in match.matched_file_path.lower():
                    continue
            
            # Score range filter
            if 'score_min' in filters and match.match_score < filters['score_min']:
                continue
            if 'score_max' in filters and match.match_score > filters['score_max']:
                continue
            
            self.filtered_matches.append(match)
        
        self._update_table()
    
    def _on_selection_changed(self):
        """Handle selection change"""
        selected_items = self.selectedItems()
        if selected_items:
            row = selected_items[0].row()
            match = self.item(row, 0).data(Qt.UserRole + 1)
            if match:
                self.match_selected.emit(match.to_dict())


class TimeBasedMatchDetailViewer(QWidget):
    """Widget for displaying time-based match details"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
    
    def _init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout(self)
        
        # Match info section
        info_group = QGroupBox("Match Information")
        info_layout = QFormLayout()
        
        self.match_id_label = QLabel("-")
        info_layout.addRow("Match ID:", self.match_id_label)
        
        self.timestamp_label = QLabel("-")
        info_layout.addRow("Timestamp:", self.timestamp_label)
        
        self.feather_count_label = QLabel("-")
        info_layout.addRow("Feather Count:", self.feather_count_label)
        
        self.time_spread_label = QLabel("-")
        info_layout.addRow("Time Spread:", self.time_spread_label)
        
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        
        # Weighted scoring breakdown widget
        self.scoring_widget = ScoringBreakdownWidget()
        layout.addWidget(self.scoring_widget)
        
        # Feather records section
        self.records_text = QTextEdit()
        self.records_text.setReadOnly(True)
        layout.addWidget(QLabel("Feather Records:"))
        layout.addWidget(self.records_text)
    
    def display_match(self, match_data: dict):
        """Display match details with semantic value highlighting"""
        self.match_id_label.setText(match_data.get('match_id', '-'))
        self.timestamp_label.setText(match_data.get('timestamp', '-'))
        self.feather_count_label.setText(str(match_data.get('feather_count', 0)))
        self.time_spread_label.setText(f"{match_data.get('time_spread_seconds', 0):.1f} seconds")
        
        # Display weighted scoring
        weighted_score = match_data.get('weighted_score')
        self.scoring_widget.display_scoring(weighted_score)
        
        # Display feather records
        records_text = ""
        feather_records = match_data.get('feather_records', {})
        
        for feather_id, record in feather_records.items():
            records_text += f"\n{'='*60}\n"
            records_text += f"Feather: {feather_id}\n"
            records_text += f"{'='*60}\n"
            
            regular_fields = {}
            semantic_fields = {}
            
            for key, value in record.items():
                if key.endswith('_semantic'):
                    continue
                elif key.endswith('_display'):
                    base_key = key.replace('_display', '')
                    semantic_fields[base_key] = value
                else:
                    regular_fields[key] = value
            
            for key, value in regular_fields.items():
                if key in semantic_fields:
                    records_text += f"{key}: {semantic_fields[key]} ✨\n"
                else:
                    records_text += f"{key}: {value}\n"
        
        self.records_text.setPlainText(records_text)


class TimeBasedFilterPanelWidget(QWidget):
    """Widget for filtering time-based results"""
    
    filters_changed = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
    
    def _init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout(self)
        
        # Application filter
        app_layout = QHBoxLayout()
        app_layout.addWidget(QLabel("Application:"))
        self.app_input = QLineEdit()
        self.app_input.setPlaceholderText("Filter by application...")
        self.app_input.textChanged.connect(self._emit_filters)
        app_layout.addWidget(self.app_input)
        layout.addLayout(app_layout)
        
        # File path filter
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("File Path:"))
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Filter by file path...")
        self.path_input.textChanged.connect(self._emit_filters)
        path_layout.addWidget(self.path_input)
        layout.addLayout(path_layout)
        
        # Score range
        score_layout = QVBoxLayout()
        score_layout.addWidget(QLabel("Score Range:"))
        
        self.score_slider = QSlider(Qt.Horizontal)
        self.score_slider.setMinimum(0)
        self.score_slider.setMaximum(100)
        self.score_slider.setValue(0)
        self.score_slider.valueChanged.connect(self._emit_filters)
        score_layout.addWidget(self.score_slider)
        
        self.score_label = QLabel("Min: 0.00")
        score_layout.addWidget(self.score_label)
        
        layout.addLayout(score_layout)
        
        # Reset button
        reset_btn = QPushButton("Reset Filters")
        reset_btn.clicked.connect(self.reset_filters)
        layout.addWidget(reset_btn)
        
        layout.addStretch()
    
    def get_filter_criteria(self) -> dict:
        """Get current filter settings"""
        return {
            'application': self.app_input.text().strip(),
            'file_path': self.path_input.text().strip(),
            'score_min': self.score_slider.value() / 100.0
        }
    
    def reset_filters(self):
        """Clear all filters"""
        self.app_input.clear()
        self.path_input.clear()
        self.score_slider.setValue(0)
    
    def _emit_filters(self):
        """Emit filter change signal"""
        self.score_label.setText(f"Min: {self.score_slider.value() / 100.0:.2f}")
        self.filters_changed.emit(self.get_filter_criteria())


class TimeBasedResultsViewer(QWidget):
    """Main widget for time-based correlation results with dynamic tabs"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.results_data: Dict[str, CorrelationResult] = {}
        self.engine_type = "time_based"
        
        self._init_ui()
    
    def _init_ui(self):
        """Initialize UI"""
        layout = QVBoxLayout(self)
        
        # Create tab widget with wider tabs and smaller text
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #3a3a3a;
            }
            QTabBar::tab {
                padding: 4px 12px;
                font-size: 8pt;
                min-width: 150px;
                max-width: 250px;
            }
            QTabBar::tab:selected {
                background-color: #2d2d2d;
                color: #2196F3;
            }
            QTabBar::tab:!selected {
                background-color: #1e1e1e;
            }
        """)
        layout.addWidget(self.tab_widget)
        
        # Create summary tab
        self.summary_tab = self._create_summary_tab()
        self.tab_widget.addTab(self.summary_tab, "Summary")
    
    def _create_summary_tab(self) -> QWidget:
        """Create summary statistics tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Statistics labels
        stats_group = QGroupBox("Overall Statistics")
        stats_layout = QFormLayout()
        
        self.total_matches_label = QLabel("0")
        stats_layout.addRow("Total Matches:", self.total_matches_label)
        
        self.wings_executed_label = QLabel("0")
        stats_layout.addRow("Wings Executed:", self.wings_executed_label)
        
        self.avg_score_label = QLabel("0.00")
        stats_layout.addRow("Average Score:", self.avg_score_label)
        
        self.engine_type_label = QLabel("Time-Based")
        stats_layout.addRow("Engine Type:", self.engine_type_label)
        
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        # Wing breakdown
        breakdown_group = QGroupBox("Wing Breakdown")
        breakdown_layout = QVBoxLayout()
        
        self.breakdown_table = QTableWidget()
        self.breakdown_table.setColumnCount(3)
        self.breakdown_table.setHorizontalHeaderLabels(["Wing Name", "Matches", "Avg Score"])
        self.breakdown_table.horizontalHeader().setStretchLastSection(True)
        breakdown_layout.addWidget(self.breakdown_table)
        
        breakdown_group.setLayout(breakdown_layout)
        layout.addWidget(breakdown_group)
        
        layout.addStretch()
        
        return widget
    
    def set_engine_type(self, engine_type: str):
        """Set the engine type for results display."""
        self.engine_type = engine_type
        if engine_type == "identity_based":
            self.engine_type_label.setText("Identity-Based")
        else:
            self.engine_type_label.setText("Time-Based")
    
    def load_results(self, output_dir: str, wing_id: Optional[str] = None, pipeline_id: Optional[str] = None):
        """Load results from output directory."""
        output_path = Path(output_dir)
        
        if not output_path.exists():
            QMessageBox.warning(self, "Directory Not Found", f"Output directory not found:\n{output_dir}")
            return
        
        from ..engine.results_formatter import apply_semantic_mappings_to_result
        
        # Clear existing tabs (except summary)
        while self.tab_widget.count() > 1:
            self.tab_widget.removeTab(1)
        
        self.results_data.clear()
        
        # Try to detect engine type
        summary_file = output_path / "pipeline_summary.json"
        if summary_file.exists():
            try:
                with open(summary_file, 'r') as f:
                    summary_data = json.load(f)
                    if 'engine_type' in summary_data:
                        self.set_engine_type(summary_data['engine_type'])
            except Exception:
                pass
        
        # Load result files
        total_matches = 0
        all_scores = []
        
        for result_file in output_path.glob("result_*.json"):
            try:
                result = CorrelationResult.load_from_file(str(result_file))
                result = apply_semantic_mappings_to_result(
                    result, 
                    wing_id=wing_id or result.wing_id,
                    pipeline_id=pipeline_id
                )
                
                self.results_data[result.wing_name] = result
                
                if result.total_matches > 0:
                    self._create_wing_tab(result.wing_name, result.matches)
                
                total_matches += result.total_matches
                all_scores.extend([m.match_score for m in result.matches])
                
            except Exception as e:
                print(f"Error loading result file {result_file}: {e}")
        
        # Update summary
        self.total_matches_label.setText(str(total_matches))
        self.wings_executed_label.setText(str(len(self.results_data)))
        
        if all_scores:
            avg_score = sum(all_scores) / len(all_scores)
            self.avg_score_label.setText(f"{avg_score:.2f}")
        
        self._update_breakdown_table()
    
    def _create_wing_tab(self, wing_name: str, matches: List[CorrelationMatch]):
        """Create tab for wing results with compact design"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(4)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # === TOP: Summary + Filters (single compact row) ===
        top_frame = QFrame()
        top_frame.setMaximumHeight(60)
        top_layout = QHBoxLayout(top_frame)
        top_layout.setSpacing(15)
        top_layout.setContentsMargins(5, 2, 5, 2)
        
        # Calculate statistics
        total_matches = len(matches)
        avg_score = sum(m.match_score for m in matches) / total_matches if total_matches > 0 else 0
        avg_feather_count = sum(m.feather_count for m in matches) / total_matches if total_matches > 0 else 0
        uses_weighted = any(m.weighted_score is not None for m in matches)
        
        # Summary labels (compact)
        matches_lbl = QLabel(f"Matches: {total_matches:,}")
        matches_lbl.setStyleSheet("color: #2196F3; font-weight: bold; font-size: 9pt;")
        top_layout.addWidget(matches_lbl)
        
        if uses_weighted:
            weighted_scores = [m.weighted_score.get('score', 0) for m in matches if m.weighted_score]
            avg_weighted = sum(weighted_scores) / len(weighted_scores) if weighted_scores else 0
            score_lbl = QLabel(f"Avg Score: {avg_weighted:.2f}")
        else:
            score_lbl = QLabel(f"Avg Score: {avg_score:.2f}")
        score_lbl.setStyleSheet("font-size: 8pt;")
        top_layout.addWidget(score_lbl)
        
        feather_lbl = QLabel(f"Avg Feathers: {avg_feather_count:.1f}")
        feather_lbl.setStyleSheet("font-size: 8pt;")
        top_layout.addWidget(feather_lbl)
        
        scoring_lbl = QLabel(f"Scoring: {'Weighted' if uses_weighted else 'Simple'}")
        scoring_lbl.setStyleSheet("color: #4CAF50; font-size: 8pt;")
        top_layout.addWidget(scoring_lbl)
        
        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #555;")
        top_layout.addWidget(sep)
        
        # Filters (compact)
        app_filter = QLineEdit()
        app_filter.setPlaceholderText("Application...")
        app_filter.setMaximumWidth(120)
        app_filter.setStyleSheet("font-size: 8pt; padding: 2px;")
        top_layout.addWidget(app_filter)
        
        path_filter = QLineEdit()
        path_filter.setPlaceholderText("File path...")
        path_filter.setMaximumWidth(120)
        path_filter.setStyleSheet("font-size: 8pt; padding: 2px;")
        top_layout.addWidget(path_filter)
        
        score_slider = QSlider(Qt.Horizontal)
        score_slider.setMinimum(0)
        score_slider.setMaximum(100)
        score_slider.setValue(0)
        score_slider.setMaximumWidth(80)
        top_layout.addWidget(score_slider)
        
        score_min_lbl = QLabel("Min: 0.00")
        score_min_lbl.setStyleSheet("font-size: 8pt;")
        top_layout.addWidget(score_min_lbl)
        
        reset_btn = QPushButton("Reset")
        reset_btn.setMaximumWidth(45)
        reset_btn.setStyleSheet("font-size: 8pt; padding: 2px 5px;")
        top_layout.addWidget(reset_btn)
        
        top_layout.addStretch()
        layout.addWidget(top_frame)
        
        # === MIDDLE: Results Table ===
        results_table = TimeBasedResultsTableWidget()
        results_table.populate_results(matches)
        results_table.setStyleSheet("""
            QTableWidget {
                font-size: 9pt;
                background-color: transparent;
                alternate-background-color: rgba(255,255,255,0.02);
                border: 1px solid #333;
            }
            QTableWidget::item { padding: 2px; }
            QTableWidget::item:selected { background-color: #0d47a1; }
            QHeaderView::section {
                background-color: #2196F3;
                color: white;
                padding: 4px;
                font-size: 8pt;
                font-weight: bold;
                border: none;
            }
        """)
        layout.addWidget(results_table, stretch=1)
        
        # === BOTTOM: Match Details Panel ===
        details_frame = QFrame()
        details_frame.setMaximumHeight(150)
        details_layout = QHBoxLayout(details_frame)
        details_layout.setSpacing(8)
        details_layout.setContentsMargins(0, 0, 0, 0)
        
        match_detail = TimeBasedMatchDetailViewer()
        match_detail.setMaximumHeight(140)
        details_layout.addWidget(match_detail)
        
        layout.addWidget(details_frame)
        
        # Connect signals
        def apply_filters():
            filters = {
                'application': app_filter.text().strip(),
                'file_path': path_filter.text().strip(),
                'score_min': score_slider.value() / 100.0
            }
            results_table.apply_filters(filters)
            score_min_lbl.setText(f"Min: {score_slider.value() / 100.0:.2f}")
        
        def reset_filters():
            app_filter.clear()
            path_filter.clear()
            score_slider.setValue(0)
            score_min_lbl.setText("Min: 0.00")
            results_table.apply_filters({})
        
        app_filter.textChanged.connect(apply_filters)
        path_filter.textChanged.connect(apply_filters)
        score_slider.valueChanged.connect(apply_filters)
        reset_btn.clicked.connect(reset_filters)
        results_table.match_selected.connect(match_detail.display_match)
        
        # Add tab with full name visible
        tab_label = f"⏱️ {wing_name} ({len(matches)})"
        self.tab_widget.addTab(widget, tab_label)
    
    def _update_breakdown_table(self):
        """Update wing breakdown table"""
        self.breakdown_table.setRowCount(0)
        
        for wing_name, result in self.results_data.items():
            row = self.breakdown_table.rowCount()
            self.breakdown_table.insertRow(row)
            
            self.breakdown_table.setItem(row, 0, QTableWidgetItem(wing_name))
            self.breakdown_table.setItem(row, 1, QTableWidgetItem(str(result.total_matches)))
            
            if result.matches:
                avg_score = sum(m.match_score for m in result.matches) / len(result.matches)
                self.breakdown_table.setItem(row, 2, QTableWidgetItem(f"{avg_score:.2f}"))
            else:
                self.breakdown_table.setItem(row, 2, QTableWidgetItem("0.00"))
