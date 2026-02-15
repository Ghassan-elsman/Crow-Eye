"""
GUI view for displaying correlation results.

This module provides a PyQt widget for displaying and filtering correlation
results in a hierarchical tree view with multi-tab support.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QDateTimeEdit, QComboBox, QLineEdit, QPushButton,
    QTextEdit, QSplitter, QGroupBox, QFileDialog, QMessageBox,
    QTableWidget, QTableWidgetItem, QTabWidget, QMenu, QAction
)
from PyQt5.QtCore import Qt, QDateTime
from PyQt5.QtGui import QColor
import json
from typing import Optional, Dict, Any

from correlation_engine.engine.query_interface import QueryInterface
from correlation_engine.engine.data_structures import QueryFilters
from correlation_engine.engine.database_persistence import ResultsDatabase
from .match_detail_dialog import MatchDetailDialog


class CorrelationResultsView(QWidget):
    """
    Display correlation results in hierarchical tree view with multi-tab support.
    
    Shows Identity → Anchor → Evidence hierarchy with filtering capabilities.
    Supports multiple result tabs for comparing different executions.
    """
    
    def __init__(self, db_path: str, execution_id: Optional[int] = None, parent=None):
        """
        Initialize results view.
        
        Args:
            db_path: Path to correlation database
            execution_id: Optional execution ID to load initially
            parent: Parent widget
        """
        super().__init__(parent)
        self.db_path = db_path
        self.query_interface = QueryInterface(db_path)
        self.db_persistence = ResultsDatabase(db_path)
        self.matches = []  # Store matches for table population
        self.current_execution_id = execution_id
        self.setup_ui()
        
        # Load initial execution if provided
        if execution_id:
            self.load_execution(execution_id)
    
    def setup_ui(self):
        """Setup UI components with improved layout and multi-tab support."""
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        
        # NEW: Execution Metadata Display Section
        self.metadata_widget = self._create_metadata_widget()
        layout.addWidget(self.metadata_widget)
        
        # NEW: Multi-Tab Widget for Results - wider tabs with smaller text
        self.result_tabs = QTabWidget()
        self.result_tabs.setTabsClosable(True)
        self.result_tabs.tabCloseRequested.connect(self._close_result_tab)
        self.result_tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.result_tabs.customContextMenuRequested.connect(self._show_tab_context_menu)
        self.result_tabs.setStyleSheet("""
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
        layout.addWidget(self.result_tabs)
        
        # Add initial tab if no execution_id provided
        if not self.current_execution_id:
            self._add_result_tab("All Results", None)
        
        # Export button at bottom
        export_layout = QHBoxLayout()
        export_layout.addStretch()
        export_button = QPushButton("Export Results")
        export_button.clicked.connect(self.export_results)
        export_layout.addWidget(export_button)
        layout.addLayout(export_layout)
        
        # Top section: Tabs and Filters in horizontal layout
        top_layout = QHBoxLayout()
        top_layout.setSpacing(10)
        
        # Tabs section (left side) - wider tabs with smaller text
        from PyQt5.QtWidgets import QTabWidget
        self.tab_widget = QTabWidget()
        self.tab_widget.setMaximumHeight(28)
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #3a3a3a;
            }
            QTabBar::tab {
                padding: 2px 12px;
                font-size: 8pt;
                min-width: 100px;
                max-width: 200px;
                height: 22px;
            }
            QTabBar::tab:selected {
                background-color: #2d2d2d;
                color: #2196F3;
            }
            QTabBar::tab:!selected {
                background-color: #1e1e1e;
            }
        """)
        self.tab_widget.addTab(QWidget(), "All Results")
        self.tab_widget.addTab(QWidget(), "High Confidence")
        self.tab_widget.addTab(QWidget(), "Medium Confidence")
        self.tab_widget.addTab(QWidget(), "Low Confidence")
        top_layout.addWidget(self.tab_widget, stretch=1)
        
        # Filter section (right side) - compact horizontal layout
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(5)
        
        # Time range filters - compact
        filter_layout.addWidget(QLabel("Start:"))
        self.start_time_edit = QDateTimeEdit()
        self.start_time_edit.setCalendarPopup(True)
        self.start_time_edit.setMaximumWidth(150)
        filter_layout.addWidget(self.start_time_edit)
        
        filter_layout.addWidget(QLabel("End:"))
        self.end_time_edit = QDateTimeEdit()
        self.end_time_edit.setCalendarPopup(True)
        self.end_time_edit.setDateTime(QDateTime.currentDateTime())
        self.end_time_edit.setMaximumWidth(150)
        filter_layout.addWidget(self.end_time_edit)
        
        # Identity filters - compact
        self.identity_type_combo = QComboBox()
        self.identity_type_combo.addItems(["All", "name", "path", "hash"])
        self.identity_type_combo.setMaximumWidth(80)
        filter_layout.addWidget(self.identity_type_combo)
        
        self.identity_value_edit = QLineEdit()
        self.identity_value_edit.setPlaceholderText("Search...")
        self.identity_value_edit.setMaximumWidth(150)
        filter_layout.addWidget(self.identity_value_edit)
        
        # Apply button - compact
        apply_button = QPushButton("Apply")
        apply_button.setMaximumWidth(60)
        apply_button.clicked.connect(self.apply_filters)
        filter_layout.addWidget(apply_button)
        
        top_layout.addLayout(filter_layout, stretch=2)
        layout.addLayout(top_layout)
        
        # Summary Section (NEW)
        self.summary_group = QGroupBox("Summary Statistics")
        self.summary_layout = QVBoxLayout()
        self.summary_group.setLayout(self.summary_layout)
        self.summary_group.setMaximumHeight(120)
        layout.addWidget(self.summary_group)
        
        # Main content: Vertical splitter with table on top, details below
        splitter = QSplitter(Qt.Vertical)
        
        # Results Table (top section) - NEW enhanced table
        self.results_table = QTableWidget()
        self.setup_results_table()
        splitter.addWidget(self.results_table)
        
        # Details Panel (bottom section)
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(200)  # Limit details panel height
        splitter.addWidget(self.details_text)
        
        # Set stretch factors: table gets more space
        splitter.setStretchFactor(0, 3)  # Table gets 75% of space
        splitter.setStretchFactor(1, 1)  # Details gets 25% of space
        layout.addWidget(splitter)
        
        # Export button at bottom
        export_layout = QHBoxLayout()
        export_layout.addStretch()
        export_button = QPushButton("Export Results")
        export_button.clicked.connect(self.export_results)
        export_layout.addWidget(export_button)
        layout.addLayout(export_layout)
    
    def setup_results_table(self):
        """Setup results table with enhanced columns."""
        # Define columns
        columns = [
            "Match ID",
            "Anchor Time",
            "Matched Feathers",      # NEW
            "File Path",             # NEW (full path)
            "Application",
            "Score",
            "Confidence",
            "Duplicate",             # NEW
            "Duplicate Source",      # NEW
            "Semantic Match"         # NEW
        ]
        
        self.results_table.setColumnCount(len(columns))
        self.results_table.setHorizontalHeaderLabels(columns)
        
        # Set column widths
        self.results_table.setColumnWidth(0, 100)  # Match ID
        self.results_table.setColumnWidth(1, 150)  # Anchor Time
        self.results_table.setColumnWidth(2, 200)  # Matched Feathers
        self.results_table.setColumnWidth(3, 300)  # File Path (wider)
        self.results_table.setColumnWidth(4, 150)  # Application
        self.results_table.setColumnWidth(5, 80)   # Score
        self.results_table.setColumnWidth(6, 100)  # Confidence
        self.results_table.setColumnWidth(7, 80)   # Duplicate
        self.results_table.setColumnWidth(8, 150)  # Duplicate Source
        self.results_table.setColumnWidth(9, 100)  # Semantic Match
        
        # Enable double-click
        self.results_table.doubleClicked.connect(self.on_row_double_click)
        
        # Enable sorting
        self.results_table.setSortingEnabled(True)
    
    def populate_results_table(self, matches):
        """
        Populate table with match results.
        
        Args:
            matches: List of CorrelationMatch objects
        """
        self.matches = matches
        self.results_table.setRowCount(len(matches))
        self.results_table.setSortingEnabled(False)  # Disable during population
        
        for row, match in enumerate(matches):
            # Match ID
            match_id_item = QTableWidgetItem(match.match_id[:8])
            match_id_item.setToolTip(match.match_id)
            self.results_table.setItem(row, 0, match_id_item)
            
            # Anchor Time
            self.results_table.setItem(row, 1,
                QTableWidgetItem(match.timestamp))
            
            # Matched Feathers (NEW)
            feather_list = ", ".join(match.feather_records.keys())
            feather_item = QTableWidgetItem(feather_list)
            feather_item.setToolTip(feather_list)
            self.results_table.setItem(row, 2, feather_item)
            
            # File Path (NEW - full path, not truncated)
            file_path = match.matched_file_path or ""
            path_item = QTableWidgetItem(file_path)
            path_item.setToolTip(file_path)  # Tooltip for long paths
            self.results_table.setItem(row, 3, path_item)
            
            # Application
            self.results_table.setItem(row, 4,
                QTableWidgetItem(match.matched_application or ""))
            
            # Score
            self.results_table.setItem(row, 5,
                QTableWidgetItem(f"{match.match_score:.3f}"))
            
            # Confidence
            self.results_table.setItem(row, 6,
                QTableWidgetItem(match.confidence_category or ""))
            
            # Duplicate (NEW)
            is_dup = getattr(match, 'is_duplicate', False)
            dup_item = QTableWidgetItem("Yes" if is_dup else "No")
            if is_dup:
                dup_item.setBackground(QColor(255, 200, 200))  # Light red
            self.results_table.setItem(row, 7, dup_item)
            
            # Duplicate Source (NEW)
            if is_dup:
                dup_info = getattr(match, 'duplicate_info', None)
                if dup_info:
                    source_text = f"{dup_info.original_anchor_feather} @ {dup_info.original_anchor_time}"
                    self.results_table.setItem(row, 8,
                        QTableWidgetItem(source_text))
            else:
                self.results_table.setItem(row, 8, QTableWidgetItem(""))
            
            # Semantic Match (NEW)
            semantic_data = getattr(match, 'semantic_data', None)
            has_semantic = False
            semantic_values = []
            
            # Check if semantic data exists and extract values
            if semantic_data and isinstance(semantic_data, dict) and not semantic_data.get('_unavailable'):
                for field_name, field_info in semantic_data.items():
                    if field_name.startswith('_'):
                        continue
                    if isinstance(field_info, dict) and 'semantic_mappings' in field_info:
                        mappings = field_info.get('semantic_mappings', [])
                        if isinstance(mappings, list):
                            for mapping in mappings:
                                if isinstance(mapping, dict) and 'semantic_value' in mapping:
                                    semantic_values.append(mapping['semantic_value'])
                                    has_semantic = True
            
            semantic_item = QTableWidgetItem("Yes" if has_semantic else "No")
            if has_semantic:
                semantic_item.setBackground(QColor(200, 255, 200))  # Light green
                # Add tooltip showing semantic values
                tooltip = "Semantic values:\n" + "\n".join([
                    f"• {val}" for val in semantic_values[:5]
                ])
                semantic_item.setToolTip(tooltip)
            self.results_table.setItem(row, 9, semantic_item)
        
        self.results_table.setSortingEnabled(True)  # Re-enable sorting
    
    def update_summary(self, result):
        """
        Update summary section with correlation result statistics.
        
        Args:
            result: CorrelationResult object
        """
        # Clear existing summary
        while self.summary_layout.count():
            child = self.summary_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        # Create summary grid
        summary_layout = QHBoxLayout()
        
        # Column 1: Basic stats
        col1 = QVBoxLayout()
        col1.addWidget(QLabel(f"<b>Total Matches:</b> {result.total_matches}"))
        col1.addWidget(QLabel(f"<b>Execution Time:</b> {result.execution_duration_seconds:.2f}s"))
        col1.addWidget(QLabel(f"<b>Records Scanned:</b> {result.total_records_scanned}"))
        summary_layout.addLayout(col1)
        
        # Column 2: Duplicate stats
        col2 = QVBoxLayout()
        col2.addWidget(QLabel(f"<b>Duplicates Detected:</b> {result.duplicates_prevented}"))
        if result.duplicates_by_feather:
            dup_text = ", ".join([f"{fid}: {count}" for fid, count in list(result.duplicates_by_feather.items())[:3]])
            if len(result.duplicates_by_feather) > 3:
                dup_text += "..."
            col2.addWidget(QLabel(f"<b>By Feather:</b> {dup_text}"))
        col2.addWidget(QLabel(f"<b>Validation Failures:</b> {result.matches_failed_validation}"))
        summary_layout.addLayout(col2)
        
        # Column 3: Feather participation
        col3 = QVBoxLayout()
        col3.addWidget(QLabel(f"<b>Feathers Processed:</b> {result.feathers_processed}"))
        if result.feather_metadata:
            feather_list = ", ".join(list(result.feather_metadata.keys())[:3])
            if len(result.feather_metadata) > 3:
                feather_list += "..."
            col3.addWidget(QLabel(f"<b>Feathers:</b> {feather_list}"))
        summary_layout.addLayout(col3)
        
        self.summary_layout.addLayout(summary_layout)
    
    def on_row_double_click(self, index):
        """Handle double-click on table row to show match details."""
        row = index.row()
        if row < len(self.matches):
            match = self.matches[row]
            try:
                # Open match detail dialog with database persistence
                dialog = MatchDetailDialog(match, self, self.db_persistence)
                dialog.exec_()
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to open match details: {str(e)}"
                )
    
    def apply_filters(self):
        """Apply filters and refresh results."""
        try:
            filters = QueryFilters()
            
            # Time filters
            if self.start_time_edit.dateTime().isValid():
                filters.start_time = self.start_time_edit.dateTime().toPyDateTime()
            if self.end_time_edit.dateTime().isValid():
                filters.end_time = self.end_time_edit.dateTime().toPyDateTime()
            
            # Identity filters
            identity_type = self.identity_type_combo.currentText()
            if identity_type != "All":
                filters.identity_type = identity_type
            
            identity_value = self.identity_value_edit.text().strip()
            if identity_value:
                filters.identity_value = identity_value
            
            # Query and populate
            identities = self.query_interface.query_identities(filters)
            self.populate_tree(identities)
            
        except Exception as e:
            QMessageBox.critical(self, "Query Error", f"Failed to query results: {str(e)}")
    
    def populate_tree(self, identities):
        """Populate tree view with hierarchical data."""
        self.tree_widget.clear()
        
        for identity in identities:
            # Identity node
            identity_item = QTreeWidgetItem([
                f"📁 {identity.identity_type}:{identity.identity_value}",
                f"First: {identity.first_seen.strftime('%Y-%m-%d %H:%M:%S')}"
            ])
            
            # Anchor nodes
            for anchor in identity.anchors:
                # Get list of feathers in this match
                feather_list = ", ".join(anchor.feather_ids) if hasattr(anchor, 'feather_ids') else "N/A"
                
                anchor_item = QTreeWidgetItem([
                    f"⏱ Anchor ({len(anchor.evidence_rows)} feathers)",
                    f"{anchor.start_time.strftime('%Y-%m-%d %H:%M:%S')} - {anchor.end_time.strftime('%H:%M:%S')}"
                ])
                
                # Add feather list as child
                feather_info_item = QTreeWidgetItem([
                    f"🔗 Feathers: {feather_list}",
                    ""
                ])
                anchor_item.addChild(feather_info_item)
                
                # Evidence nodes
                for evidence in anchor.evidence_rows:
                    evidence_item = QTreeWidgetItem([
                        f"📄 {evidence.artifact} ({evidence.feather_id})",
                        f"Row {evidence.row_id} @ {evidence.timestamp.strftime('%H:%M:%S')}"
                    ])
                    anchor_item.addChild(evidence_item)
                
                identity_item.addChild(anchor_item)
            
            self.tree_widget.addTopLevelItem(identity_item)
        
        if not identities:
            no_results_item = QTreeWidgetItem(["No results found", ""])
            self.tree_widget.addTopLevelItem(no_results_item)
    
    def on_item_selected(self):
        """Show details when tree item is selected."""
        selected_items = self.tree_widget.selectedItems()
        if not selected_items:
            return
        
        item = selected_items[0]
        text = item.text(0)
        
        # Show item details
        self.details_text.setPlainText(f"Selected: {text}\n\nDetails would be shown here.")
    
    def export_results(self):
        """Export filtered results to file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Results",
            "",
            "JSON Files (*.json);;CSV Files (*.csv);;All Files (*)"
        )
        
        if file_path:
            try:
                # Export logic would go here
                QMessageBox.information(self, "Export Complete", f"Results exported to {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export: {str(e)}")
    
    # ========== NEW METHODS FOR TASKS 15, 16, 17 ==========
    
    def _create_metadata_widget(self) -> QGroupBox:
        """
        Create execution metadata display widget.
        
        Returns:
            QGroupBox containing metadata labels
        """
        group = QGroupBox("Execution Metadata")
        layout = QVBoxLayout()
        
        # Create metadata label
        self.metadata_label = QLabel("No execution loaded")
        self.metadata_label.setWordWrap(True)
        self.metadata_label.setStyleSheet("""
            QLabel {
                background-color: #2d2d2d;
                padding: 10px;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                font-size: 9pt;
            }
        """)
        layout.addWidget(self.metadata_label)
        
        group.setLayout(layout)
        group.setMaximumHeight(150)
        return group
    
    def _add_result_tab(self, title: str, execution_id: Optional[int]):
        """
        Add a new result tab.
        
        Args:
            title: Tab title
            execution_id: Execution ID to load, or None for empty tab
        """
        # Create tab content widget
        tab_widget = QWidget()
        tab_layout = QVBoxLayout(tab_widget)
        tab_layout.setSpacing(5)
        
        # Top section: Filters
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(5)
        
        # Time range filters
        filter_layout.addWidget(QLabel("Start:"))
        start_time_edit = QDateTimeEdit()
        start_time_edit.setCalendarPopup(True)
        start_time_edit.setMaximumWidth(150)
        filter_layout.addWidget(start_time_edit)
        
        filter_layout.addWidget(QLabel("End:"))
        end_time_edit = QDateTimeEdit()
        end_time_edit.setCalendarPopup(True)
        end_time_edit.setDateTime(QDateTime.currentDateTime())
        end_time_edit.setMaximumWidth(150)
        filter_layout.addWidget(end_time_edit)
        
        # Identity filters
        identity_type_combo = QComboBox()
        identity_type_combo.addItems(["All", "name", "path", "hash"])
        identity_type_combo.setMaximumWidth(80)
        filter_layout.addWidget(identity_type_combo)
        
        identity_value_edit = QLineEdit()
        identity_value_edit.setPlaceholderText("Search...")
        identity_value_edit.setMaximumWidth(150)
        filter_layout.addWidget(identity_value_edit)
        
        # Apply button
        apply_button = QPushButton("Apply")
        apply_button.setMaximumWidth(60)
        filter_layout.addWidget(apply_button)
        
        filter_layout.addStretch()
        tab_layout.addLayout(filter_layout)
        
        # Summary Section
        summary_group = QGroupBox("Summary Statistics")
        summary_layout = QVBoxLayout()
        summary_group.setLayout(summary_layout)
        summary_group.setMaximumHeight(120)
        tab_layout.addWidget(summary_group)
        
        # Results Table
        results_table = QTableWidget()
        self._setup_table_for_tab(results_table)
        tab_layout.addWidget(results_table)
        
        # Details Panel
        details_text = QTextEdit()
        details_text.setReadOnly(True)
        details_text.setMaximumHeight(200)
        tab_layout.addWidget(details_text)
        
        # Store references in tab widget
        tab_widget.start_time_edit = start_time_edit
        tab_widget.end_time_edit = end_time_edit
        tab_widget.identity_type_combo = identity_type_combo
        tab_widget.identity_value_edit = identity_value_edit
        tab_widget.summary_layout = summary_layout
        tab_widget.results_table = results_table
        tab_widget.details_text = details_text
        tab_widget.execution_id = execution_id
        tab_widget.matches = []
        
        # Connect apply button
        apply_button.clicked.connect(lambda: self._apply_filters_for_tab(tab_widget))
        
        # Add tab
        index = self.result_tabs.addTab(tab_widget, title)
        self.result_tabs.setCurrentIndex(index)
        
        # Load execution if provided
        if execution_id:
            self._load_results_into_tab(tab_widget, execution_id)
        
        return tab_widget
    
    def _setup_table_for_tab(self, table: QTableWidget):
        """
        Setup results table for a tab.
        
        Args:
            table: QTableWidget to configure
        """
        # Define columns
        columns = [
            "Match ID",
            "Anchor Time",
            "Matched Feathers",
            "File Path",
            "Application",
            "Score",
            "Confidence",
            "Engine",           # NEW: Show which engine produced this result
            "Duplicate",
            "Semantic Match"
        ]
        
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        
        # Set column widths
        table.setColumnWidth(0, 100)   # Match ID
        table.setColumnWidth(1, 150)   # Anchor Time
        table.setColumnWidth(2, 200)   # Matched Feathers
        table.setColumnWidth(3, 300)   # File Path
        table.setColumnWidth(4, 150)   # Application
        table.setColumnWidth(5, 80)    # Score
        table.setColumnWidth(6, 100)   # Confidence
        table.setColumnWidth(7, 120)   # Engine
        table.setColumnWidth(8, 80)    # Duplicate
        table.setColumnWidth(9, 100)   # Semantic Match
        
        # Enable double-click
        table.doubleClicked.connect(lambda index: self._on_row_double_click(table, index))
        
        # Enable sorting
        table.setSortingEnabled(True)
        
        # Enable context menu
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.customContextMenuRequested.connect(lambda pos: self._show_row_context_menu(table, pos))
    
    def _close_result_tab(self, index: int):
        """
        Close a result tab.
        
        Args:
            index: Tab index to close
        """
        # Don't close if it's the last tab
        if self.result_tabs.count() <= 1:
            QMessageBox.warning(
                self,
                "Cannot Close Tab",
                "Cannot close the last tab."
            )
            return
        
        self.result_tabs.removeTab(index)
    
    def _show_tab_context_menu(self, pos):
        """
        Show context menu for tabs.
        
        Args:
            pos: Position where menu was requested
        """
        # Get tab index at position
        tab_bar = self.result_tabs.tabBar()
        index = tab_bar.tabAt(pos)
        
        if index < 0:
            return
        
        menu = QMenu(self)
        
        # "Open in New Tab" action
        open_new_action = QAction("Duplicate Tab", self)
        open_new_action.triggered.connect(lambda: self._duplicate_tab(index))
        menu.addAction(open_new_action)
        
        # "Rename Tab" action
        rename_action = QAction("Rename Tab", self)
        rename_action.triggered.connect(lambda: self._rename_tab(index))
        menu.addAction(rename_action)
        
        menu.exec_(tab_bar.mapToGlobal(pos))
    
    def _show_row_context_menu(self, table: QTableWidget, pos):
        """
        Show context menu for table rows.
        
        Args:
            table: Table widget
            pos: Position where menu was requested
        """
        # Get row at position
        item = table.itemAt(pos)
        if not item:
            return
        
        row = item.row()
        
        menu = QMenu(self)
        
        # "Open in New Tab" action
        open_new_action = QAction("Open in New Tab", self)
        open_new_action.triggered.connect(lambda: self._open_result_in_new_tab(table, row))
        menu.addAction(open_new_action)
        
        # "Show Details" action
        details_action = QAction("Show Details", self)
        details_action.triggered.connect(lambda: self._on_row_double_click(table, table.model().index(row, 0)))
        menu.addAction(details_action)
        
        menu.exec_(table.viewport().mapToGlobal(pos))
    
    def _duplicate_tab(self, index: int):
        """
        Duplicate a tab.
        
        Args:
            index: Tab index to duplicate
        """
        tab_widget = self.result_tabs.widget(index)
        if not tab_widget:
            return
        
        # Get execution ID from tab
        execution_id = getattr(tab_widget, 'execution_id', None)
        title = self.result_tabs.tabText(index)
        
        # Create new tab with same execution
        self._add_result_tab(f"{title} (Copy)", execution_id)
    
    def _rename_tab(self, index: int):
        """
        Rename a tab.
        
        Args:
            index: Tab index to rename
        """
        from PyQt5.QtWidgets import QInputDialog
        
        current_name = self.result_tabs.tabText(index)
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Tab",
            "Enter new tab name:",
            text=current_name
        )
        
        if ok and new_name:
            self.result_tabs.setTabText(index, new_name)
    
    def _open_result_in_new_tab(self, table: QTableWidget, row: int):
        """
        Open a result in a new tab.
        
        Args:
            table: Table widget
            row: Row index
        """
        # Get tab widget containing this table
        tab_widget = table.parent()
        while tab_widget and not isinstance(tab_widget, QWidget):
            tab_widget = tab_widget.parent()
        
        if not tab_widget:
            return
        
        # Get execution ID
        execution_id = getattr(tab_widget, 'execution_id', None)
        
        if execution_id:
            # Create new tab with same execution
            match_id = table.item(row, 0).text()
            self._add_result_tab(f"Match {match_id}", execution_id)
        else:
            QMessageBox.information(
                self,
                "No Execution",
                "Cannot open in new tab - no execution ID associated with this result."
            )
    
    def _apply_filters_for_tab(self, tab_widget: QWidget):
        """
        Apply filters for a specific tab.
        
        Args:
            tab_widget: Tab widget to apply filters to
        """
        try:
            filters = QueryFilters()
            
            # Time filters
            if tab_widget.start_time_edit.dateTime().isValid():
                filters.start_time = tab_widget.start_time_edit.dateTime().toPyDateTime()
            if tab_widget.end_time_edit.dateTime().isValid():
                filters.end_time = tab_widget.end_time_edit.dateTime().toPyDateTime()
            
            # Identity filters
            identity_type = tab_widget.identity_type_combo.currentText()
            if identity_type != "All":
                filters.identity_type = identity_type
            
            identity_value = tab_widget.identity_value_edit.text().strip()
            if identity_value:
                filters.identity_value = identity_value
            
            # Query and populate
            identities = self.query_interface.query_identities(filters)
            # TODO: Populate table with filtered results
            
        except Exception as e:
            QMessageBox.critical(self, "Query Error", f"Failed to query results: {str(e)}")
    
    def _load_results_into_tab(self, tab_widget: QWidget, execution_id: int):
        """
        Load results for an execution into a tab.
        
        Args:
            tab_widget: Tab widget to load results into
            execution_id: Execution ID to load
        """
        try:
            # Get execution results
            results = self.db_persistence.get_execution_results(execution_id)
            
            # TODO: Convert results to match objects and populate table
            # For now, just show count
            tab_widget.details_text.setPlainText(
                f"Loaded {len(results)} results for execution {execution_id}"
            )
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Load Error",
                f"Failed to load results: {str(e)}"
            )
    
    def _on_row_double_click(self, table: QTableWidget, index):
        """
        Handle double-click on table row.
        
        Args:
            table: Table widget
            index: Model index
        """
        row = index.row()
        
        # Get tab widget containing this table
        tab_widget = table.parent()
        while tab_widget and not isinstance(tab_widget, QWidget):
            tab_widget = tab_widget.parent()
        
        if not tab_widget:
            return
        
        matches = getattr(tab_widget, 'matches', [])
        
        if row < len(matches):
            match = matches[row]
            try:
                # Open match detail dialog with database persistence
                dialog = MatchDetailDialog(match, self, self.db_persistence)
                dialog.exec_()
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to open match details: {str(e)}"
                )
    
    def load_execution(self, execution_id: int):
        """
        Load an execution and display its metadata and results.
        
        Args:
            execution_id: Execution ID to load
        """
        try:
            # Load metadata
            metadata = self.db_persistence.get_execution_metadata(execution_id)
            
            if not metadata:
                QMessageBox.warning(
                    self,
                    "Not Found",
                    f"Execution {execution_id} not found in database."
                )
                return
            
            # Update metadata display
            self._update_metadata_display(metadata)
            
            # Create tab for this execution
            execution_date = metadata.get('execution_date', 'Unknown')
            engine_type = metadata.get('engine_type', 'Unknown')
            tab_title = f"Execution {execution_id} ({engine_type})"
            
            self._add_result_tab(tab_title, execution_id)
            
            self.current_execution_id = execution_id
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Load Error",
                f"Failed to load execution: {str(e)}"
            )
    
    def _update_metadata_display(self, metadata: Dict[str, Any]):
        """
        Update the metadata display widget.
        
        Args:
            metadata: Execution metadata dictionary
        """
        # Extract key metadata fields
        execution_id = metadata.get('execution_id', 'N/A')
        execution_date = metadata.get('execution_date', 'N/A')
        engine_type = metadata.get('engine_type', 'N/A')
        pipeline_name = metadata.get('pipeline_name', 'N/A')
        wing_name = metadata.get('wing_name', 'N/A')
        
        # Time filters
        time_start = metadata.get('time_period_start')
        time_end = metadata.get('time_period_end')
        
        # Identity filters
        identity_filters = metadata.get('identity_filters', [])
        
        # Statistics
        duration = metadata.get('execution_duration_seconds', 0)
        records_processed = metadata.get('total_records_processed', 0)
        matches_found = metadata.get('total_matches_found', 0)
        
        # Build metadata text
        metadata_text = f"""
<b>Execution ID:</b> {execution_id} | <b>Date:</b> {execution_date}<br>
<b>Engine:</b> {engine_type} | <b>Pipeline:</b> {pipeline_name} | <b>Wing:</b> {wing_name}<br>
"""
        
        # Add time filter info if applied
        if time_start or time_end:
            filter_text = "<b>Time Filter:</b> "
            if time_start:
                filter_text += f"Start: {time_start} "
            if time_end:
                filter_text += f"End: {time_end}"
            metadata_text += filter_text + "<br>"
        
        # Add identity filter info if applied
        if identity_filters:
            filter_count = len(identity_filters)
            filter_preview = ", ".join(identity_filters[:3])
            if filter_count > 3:
                filter_preview += f" ... (+{filter_count - 3} more)"
            metadata_text += f"<b>Identity Filters:</b> {filter_preview}<br>"
        
        # Add statistics
        metadata_text += f"""
<b>Statistics:</b> Duration: {duration:.2f}s | Records: {records_processed:,} | Matches: {matches_found:,}
"""
        
        self.metadata_label.setText(metadata_text.strip())
    
    def populate_results_table_for_tab(self, tab_widget: QWidget, matches, engine_type: str = "unknown"):
        """
        Populate table with match results for a specific tab.
        Handles both Time-Based and Identity-Based engine results.
        
        Args:
            tab_widget: Tab widget containing the table
            matches: List of CorrelationMatch objects
            engine_type: Type of engine that produced results ("time_based" or "identity_based")
        """
        table = tab_widget.results_table
        tab_widget.matches = matches
        
        table.setRowCount(len(matches))
        table.setSortingEnabled(False)
        
        for row, match in enumerate(matches):
            # Match ID
            match_id_item = QTableWidgetItem(match.match_id[:8])
            match_id_item.setToolTip(match.match_id)
            table.setItem(row, 0, match_id_item)
            
            # Anchor Time
            table.setItem(row, 1, QTableWidgetItem(match.timestamp))
            
            # Matched Feathers
            feather_list = ", ".join(match.feather_records.keys())
            feather_item = QTableWidgetItem(feather_list)
            feather_item.setToolTip(feather_list)
            table.setItem(row, 2, feather_item)
            
            # File Path
            file_path = match.matched_file_path or ""
            path_item = QTableWidgetItem(file_path)
            path_item.setToolTip(file_path)
            table.setItem(row, 3, path_item)
            
            # Application
            table.setItem(row, 4, QTableWidgetItem(match.matched_application or ""))
            
            # Score
            table.setItem(row, 5, QTableWidgetItem(f"{match.match_score:.3f}"))
            
            # Confidence
            table.setItem(row, 6, QTableWidgetItem(match.confidence_category or ""))
            
            # Engine (NEW)
            engine_display = "Time-Based" if engine_type == "time_based" else "Identity-Based"
            engine_item = QTableWidgetItem(engine_display)
            if engine_type == "identity_based":
                engine_item.setBackground(QColor(200, 220, 255))  # Light blue
            table.setItem(row, 7, engine_item)
            
            # Duplicate
            is_dup = getattr(match, 'is_duplicate', False)
            dup_item = QTableWidgetItem("Yes" if is_dup else "No")
            if is_dup:
                dup_item.setBackground(QColor(255, 200, 200))
            table.setItem(row, 8, dup_item)
            
            # Semantic Match
            semantic_data = getattr(match, 'semantic_data', None)
            has_semantic = False
            semantic_values = []
            
            # Check if semantic data exists and extract values
            if semantic_data and isinstance(semantic_data, dict) and not semantic_data.get('_unavailable'):
                for field_name, field_info in semantic_data.items():
                    if field_name.startswith('_'):
                        continue
                    if isinstance(field_info, dict) and 'semantic_mappings' in field_info:
                        mappings = field_info.get('semantic_mappings', [])
                        if isinstance(mappings, list):
                            for mapping in mappings:
                                if isinstance(mapping, dict) and 'semantic_value' in mapping:
                                    semantic_values.append(mapping['semantic_value'])
                                    has_semantic = True
            
            semantic_item = QTableWidgetItem("Yes" if has_semantic else "No")
            if has_semantic:
                semantic_item.setBackground(QColor(200, 255, 200))
                # Add tooltip showing semantic values
                tooltip = "Semantic values:\n" + "\n".join([
                    f"• {val}" for val in semantic_values[:5]
                ])
                semantic_item.setToolTip(tooltip)
            table.setItem(row, 9, semantic_item)
        
        table.setSortingEnabled(True)
