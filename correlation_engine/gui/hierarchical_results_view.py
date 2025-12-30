"""
Hierarchical Results View for Identity-Based Correlation

This module provides a PyQt widget for displaying correlation results in a
hierarchical tree structure: Identity → Anchor → Evidence

Implements Task 8: Convert Results View to Hierarchical Tree
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QDateTimeEdit, QComboBox, QLineEdit, QPushButton,
    QTextEdit, QSplitter, QGroupBox, QFileDialog, QMessageBox,
    QHeaderView, QStyle
)
from PyQt5.QtCore import Qt, QDateTime, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QBrush
from datetime import datetime
from typing import List, Optional, Dict, Any

from correlation_engine.engine.query_interface import QueryInterface
from correlation_engine.engine.data_structures import Identity, Anchor, EvidenceRow, QueryFilters
from correlation_engine.gui.identity_detail_dialog import IdentityDetailDialog
from correlation_engine.gui.anchor_detail_dialog import AnchorDetailDialog


class HierarchicalResultsView(QWidget):
    """
    Hierarchical tree view for correlation results.
    
    Displays Identity → Anchor → Evidence hierarchy with:
    - Identity grouping
    - Temporal anchor clustering
    - Evidence role classification
    - Semantic enrichment display
    - Double-click detail dialogs
    
    Implements Requirements: 8, 20.5
    """
    
    # Signals
    identity_double_clicked = pyqtSignal(object)  # Identity object
    anchor_double_clicked = pyqtSignal(object)    # Anchor object
    evidence_double_clicked = pyqtSignal(object)  # EvidenceRow object
    
    def __init__(self, db_path: str, parent=None):
        """
        Initialize hierarchical results view.
        
        Args:
            db_path: Path to correlation database
            parent: Parent widget
        """
        super().__init__(parent)
        self.db_path = db_path
        self.query_interface = QueryInterface(db_path)
        
        # Data cache
        self.identities: List[Identity] = []
        self.current_filters = QueryFilters()
        
        self.setup_ui()
    
    def setup_ui(self):
        """Setup UI components."""
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        
        # Filter section
        filter_layout = self._create_filter_section()
        layout.addLayout(filter_layout)
        
        # Summary section
        self.summary_label = QLabel("No results loaded")
        self.summary_label.setStyleSheet("padding: 5px; background-color: #2d2d2d;")
        layout.addWidget(self.summary_label)
        
        # Main content: Tree widget
        self.results_tree = QTreeWidget()
        self._setup_tree_widget()
        layout.addWidget(self.results_tree)
        
        # Details panel (bottom)
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(150)
        self.details_text.setPlaceholderText("Select an item to view details...")
        layout.addWidget(self.details_text)
        
        # Export button
        export_layout = QHBoxLayout()
        export_layout.addStretch()
        export_button = QPushButton("Export Results")
        export_button.clicked.connect(self.export_results)
        export_layout.addWidget(export_button)
        layout.addLayout(export_layout)
    
    def _create_filter_section(self) -> QHBoxLayout:
        """Create filter controls section."""
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(10)
        
        # Time range filters
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
        
        # Identity type filter
        filter_layout.addWidget(QLabel("Type:"))
        self.identity_type_combo = QComboBox()
        self.identity_type_combo.addItems(["All", "name", "path", "hash", "composite"])
        self.identity_type_combo.setMaximumWidth(100)
        filter_layout.addWidget(self.identity_type_combo)
        
        # Search filter
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search identities...")
        self.search_edit.setMaximumWidth(200)
        filter_layout.addWidget(self.search_edit)
        
        # Apply button
        apply_button = QPushButton("Apply Filters")
        apply_button.setMaximumWidth(100)
        apply_button.clicked.connect(self.apply_filters)
        filter_layout.addWidget(apply_button)
        
        # Refresh button
        refresh_button = QPushButton("Refresh")
        refresh_button.setMaximumWidth(80)
        refresh_button.clicked.connect(self.refresh_results)
        filter_layout.addWidget(refresh_button)
        
        filter_layout.addStretch()
        
        return filter_layout
    
    def _setup_tree_widget(self):
        """
        Setup tree widget with columns and behavior.
        
        Task 8.1: Replace QTableWidget with QTreeWidget
        """
        # Define 6 columns
        columns = [
            "Name / Description",
            "Type / Role",
            "Count / Time",
            "Semantic / Category",
            "Confidence",
            "Actions"
        ]
        
        self.results_tree.setColumnCount(len(columns))
        self.results_tree.setHeaderLabels(columns)
        
        # Set column widths
        self.results_tree.setColumnWidth(0, 300)  # Name
        self.results_tree.setColumnWidth(1, 120)  # Type
        self.results_tree.setColumnWidth(2, 150)  # Count/Time
        self.results_tree.setColumnWidth(3, 200)  # Semantic
        self.results_tree.setColumnWidth(4, 100)  # Confidence
        self.results_tree.setColumnWidth(5, 100)  # Actions
        
        # Enable features
        self.results_tree.setAlternatingRowColors(True)
        self.results_tree.setSelectionMode(QTreeWidget.SingleSelection)
        self.results_tree.setExpandsOnDoubleClick(False)  # We handle double-click
        
        # Enable sorting
        self.results_tree.setSortingEnabled(True)
        self.results_tree.sortByColumn(0, Qt.AscendingOrder)
        
        # Connect signals
        self.results_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.results_tree.itemSelectionChanged.connect(self._on_selection_changed)
        
        # Style
        self.results_tree.setStyleSheet("""
            QTreeWidget {
                background-color: #1e1e1e;
                alternate-background-color: #2d2d2d;
                color: #ffffff;
                border: 1px solid #3a3a3a;
            }
            QTreeWidget::item:selected {
                background-color: #094771;
            }
            QTreeWidget::item:hover {
                background-color: #2a2a2a;
            }
            QHeaderView::section {
                background-color: #2d2d2d;
                color: #ffffff;
                padding: 5px;
                border: 1px solid #3a3a3a;
            }
        """)
    
    def create_identity_item(self, identity: Identity) -> QTreeWidgetItem:
        """
        Create tree item for an identity.
        
        Task 8.2: Implement identity row creation
        
        Args:
            identity: Identity object
            
        Returns:
            QTreeWidgetItem configured for identity display
        """
        item = QTreeWidgetItem()
        
        # Column 0: Identity name
        item.setText(0, identity.primary_name)
        item.setToolTip(0, f"Identity: {identity.identity_value}\nType: {identity.identity_type}")
        
        # Make identity name bold
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        item.setFont(0, font)
        
        # Column 1: Identity type
        item.setText(1, identity.identity_type.capitalize())
        
        # Column 2: Evidence and anchor counts
        anchor_count = len(identity.anchors)
        evidence_count = len(identity.all_evidence)
        item.setText(2, f"{evidence_count} evidence, {anchor_count} anchors")
        
        # Column 3: Semantic categories (from artifacts involved)
        artifacts = ", ".join(identity.artifacts_involved[:3])
        if len(identity.artifacts_involved) > 3:
            artifacts += "..."
        item.setText(3, artifacts)
        
        # Column 4: Confidence
        confidence_text = f"{identity.confidence:.2f}"
        item.setText(4, confidence_text)
        
        # Color code by confidence
        if identity.confidence >= 0.8:
            item.setForeground(4, QBrush(QColor(100, 255, 100)))  # Green
        elif identity.confidence >= 0.5:
            item.setForeground(4, QBrush(QColor(255, 255, 100)))  # Yellow
        else:
            item.setForeground(4, QBrush(QColor(255, 100, 100)))  # Red
        
        # Column 5: Actions
        item.setText(5, "View Details")
        
        # Store identity object in UserRole
        item.setData(0, Qt.UserRole, {"type": "identity", "object": identity})
        
        # Add icon based on identity type
        if identity.identity_type == "path":
            item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
        elif identity.identity_type == "hash":
            item.setIcon(0, self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        else:
            item.setIcon(0, self.style().standardIcon(QStyle.SP_ComputerIcon))
        
        return item
    
    def create_anchor_item(self, anchor: Anchor) -> QTreeWidgetItem:
        """
        Create tree item for an anchor.
        
        Task 8.3: Implement anchor row creation
        
        Args:
            anchor: Anchor object
            
        Returns:
            QTreeWidgetItem configured for anchor display
        """
        item = QTreeWidgetItem()
        
        # Column 0: Time window
        start_str = anchor.start_time.strftime("%H:%M:%S") if anchor.start_time else "N/A"
        end_str = anchor.end_time.strftime("%H:%M:%S") if anchor.end_time else "N/A"
        item.setText(0, f"⏱ {start_str} - {end_str}")
        item.setToolTip(0, f"Anchor ID: {anchor.anchor_id}\nDuration: {anchor.duration_minutes:.1f} minutes")
        
        # Column 1: Duration
        item.setText(1, f"{anchor.duration_minutes:.1f} min")
        
        # Column 2: Evidence count
        evidence_count = len(anchor.rows)
        primary_count = anchor.primary_count
        secondary_count = anchor.secondary_count
        item.setText(2, f"{evidence_count} evidence ({primary_count}P, {secondary_count}S)")
        
        # Column 3: Primary artifact
        primary_artifact = anchor.primary_artifact or "Unknown"
        item.setText(3, f"Primary: {primary_artifact}")
        
        # Column 4: Confidence
        confidence_text = f"{anchor.confidence:.2f}" if anchor.confidence else "N/A"
        item.setText(4, confidence_text)
        
        # Column 5: Actions
        item.setText(5, "View Timeline")
        
        # Store anchor object in UserRole
        item.setData(0, Qt.UserRole, {"type": "anchor", "object": anchor})
        
        # Add time icon
        item.setIcon(0, self.style().standardIcon(QStyle.SP_BrowserReload))
        
        # Indent style
        font = QFont()
        font.setItalic(True)
        item.setFont(0, font)
        
        return item
    
    def create_evidence_item(self, evidence: EvidenceRow) -> QTreeWidgetItem:
        """
        Create tree item for evidence.
        
        Task 8.4: Implement evidence row creation
        
        Args:
            evidence: EvidenceRow object
            
        Returns:
            QTreeWidgetItem configured for evidence display
        """
        item = QTreeWidgetItem()
        
        # Column 0: Artifact name
        item.setText(0, f"  📄 {evidence.artifact}")
        item.setToolTip(0, f"Feather ID: {evidence.feather_id}\nTable: {evidence.table}\nRow: {evidence.row_id}")
        
        # Column 1: Role badge
        role_badge = {
            "primary": "[PRIMARY]",
            "secondary": "[SECONDARY]",
            "supporting": "[SUPPORTING]"
        }.get(evidence.role, "[UNKNOWN]")
        item.setText(1, role_badge)
        
        # Color code by role
        if evidence.role == "primary":
            item.setForeground(1, QBrush(QColor(255, 100, 100)))  # Red
            font = QFont()
            font.setBold(True)
            item.setFont(1, font)
        elif evidence.role == "secondary":
            item.setForeground(1, QBrush(QColor(255, 255, 100)))  # Yellow
        else:  # supporting
            item.setForeground(1, QBrush(QColor(100, 255, 100)))  # Green
        
        # Column 2: Timestamp
        if evidence.timestamp:
            timestamp_str = evidence.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            item.setText(2, timestamp_str)
        else:
            item.setText(2, "No timestamp")
            item.setForeground(2, QBrush(QColor(150, 150, 150)))  # Gray
        
        # Column 3: Semantic meaning
        if evidence.semantic_data and 'meaning' in evidence.semantic_data:
            meaning = evidence.semantic_data['meaning']
            category = evidence.semantic_data.get('category', '')
            item.setText(3, f"{meaning} ({category})")
            item.setToolTip(3, f"Category: {category}\nSeverity: {evidence.semantic_data.get('severity', 'N/A')}")
        else:
            item.setText(3, "No semantic data")
        
        # Column 4: Confidence
        confidence_text = f"{evidence.confidence:.2f}" if evidence.confidence else "N/A"
        item.setText(4, confidence_text)
        
        # Column 5: Actions
        item.setText(5, "View Details")
        
        # Store evidence object in UserRole
        item.setData(0, Qt.UserRole, {"type": "evidence", "object": evidence})
        
        # Add artifact icon
        item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
        
        return item
    
    def populate_tree(self, wing_id: Optional[str] = None):
        """
        Populate tree with identities from database.
        
        Task 8.5: Implement tree population
        
        Args:
            wing_id: Optional wing ID to filter results
        """
        # Clear existing items
        self.results_tree.clear()
        self.details_text.clear()
        
        try:
            # Query identities from database
            # Note: This assumes the query interface has been enhanced to return Identity objects
            # For now, we'll create a placeholder implementation
            
            # TODO: Implement actual database query
            # self.identities = self.query_interface.query_identities(filters=self.current_filters)
            
            # Placeholder: Show message
            placeholder_item = QTreeWidgetItem()
            placeholder_item.setText(0, "Database query not yet implemented")
            placeholder_item.setText(1, "Phase 5 backend ready")
            placeholder_item.setText(2, "Awaiting integration")
            self.results_tree.addTopLevelItem(placeholder_item)
            
            # Update summary
            self.summary_label.setText(f"Loaded {len(self.identities)} identities")
            
            # For each identity, create hierarchy
            for identity in self.identities:
                # Create identity item
                identity_item = self.create_identity_item(identity)
                self.results_tree.addTopLevelItem(identity_item)
                
                # Add anchors
                for anchor in identity.anchors:
                    anchor_item = self.create_anchor_item(anchor)
                    identity_item.addChild(anchor_item)
                    
                    # Add evidence in anchor
                    for evidence in anchor.rows:
                        evidence_item = self.create_evidence_item(evidence)
                        anchor_item.addChild(evidence_item)
                
                # Add supporting evidence (no anchor)
                supporting_evidence = [e for e in identity.all_evidence if not e.has_anchor]
                if supporting_evidence:
                    # Create supporting evidence group
                    supporting_group = QTreeWidgetItem()
                    supporting_group.setText(0, "Supporting Evidence (No Timestamp)")
                    supporting_group.setText(2, f"{len(supporting_evidence)} items")
                    font = QFont()
                    font.setItalic(True)
                    supporting_group.setFont(0, font)
                    identity_item.addChild(supporting_group)
                    
                    for evidence in supporting_evidence:
                        evidence_item = self.create_evidence_item(evidence)
                        supporting_group.addChild(evidence_item)
            
            # Expand first level by default
            if self.results_tree.topLevelItemCount() > 0:
                self.results_tree.topLevelItem(0).setExpanded(True)
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load results: {str(e)}")
    
    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """
        Handle double-click on tree item.
        
        Task 8.6: Implement double-click handlers
        
        Args:
            item: Clicked tree item
            column: Column index
        """
        # Get item data
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        
        item_type = data.get("type")
        obj = data.get("object")
        
        if item_type == "identity":
            # Open Identity Detail Dialog
            dialog = IdentityDetailDialog(obj, self)
            dialog.exec_()
            
        elif item_type == "anchor":
            # Open Anchor Detail Dialog
            dialog = AnchorDetailDialog(obj, self)
            dialog.exec_()
            
        elif item_type == "evidence":
            # Emit signal for evidence detail dialog
            self.evidence_double_clicked.emit(obj)
    
    def _on_selection_changed(self):
        """Handle selection change to update details panel."""
        selected_items = self.results_tree.selectedItems()
        if not selected_items:
            self.details_text.clear()
            return
        
        item = selected_items[0]
        data = item.data(0, Qt.UserRole)
        
        if not data:
            self.details_text.clear()
            return
        
        item_type = data.get("type")
        obj = data.get("object")
        
        # Display details based on type
        if item_type == "identity":
            self._display_identity_details(obj)
        elif item_type == "anchor":
            self._display_anchor_details(obj)
        elif item_type == "evidence":
            self._display_evidence_details(obj)
    
    def _display_identity_details(self, identity: Identity):
        """Display identity details in details panel."""
        details = f"""
<b>Identity Details</b><br>
<b>Name:</b> {identity.primary_name}<br>
<b>Type:</b> {identity.identity_type}<br>
<b>Value:</b> {identity.identity_value}<br>
<b>Confidence:</b> {identity.confidence:.2f}<br>
<b>Match Method:</b> {identity.match_method}<br>
<b>Total Evidence:</b> {len(identity.all_evidence)}<br>
<b>Total Anchors:</b> {len(identity.anchors)}<br>
<b>Artifacts Involved:</b> {', '.join(identity.artifacts_involved)}<br>
<br>
<i>Double-click to view full details</i>
        """
        self.details_text.setHtml(details)
    
    def _display_anchor_details(self, anchor: Anchor):
        """Display anchor details in details panel."""
        start_str = anchor.start_time.strftime("%Y-%m-%d %H:%M:%S") if anchor.start_time else "N/A"
        end_str = anchor.end_time.strftime("%Y-%m-%d %H:%M:%S") if anchor.end_time else "N/A"
        confidence_str = f"{anchor.confidence:.2f}" if anchor.confidence else "N/A"
        
        details = f"""
<b>Anchor Details</b><br>
<b>Anchor ID:</b> {anchor.anchor_id}<br>
<b>Start Time:</b> {start_str}<br>
<b>End Time:</b> {end_str}<br>
<b>Duration:</b> {anchor.duration_minutes:.1f} minutes<br>
<b>Evidence Count:</b> {len(anchor.rows)}<br>
<b>Primary Evidence:</b> {anchor.primary_count}<br>
<b>Secondary Evidence:</b> {anchor.secondary_count}<br>
<b>Primary Artifact:</b> {anchor.primary_artifact or 'N/A'}<br>
<b>Confidence:</b> {confidence_str}<br>
<br>
<i>Double-click to view timeline</i>
        """
        self.details_text.setHtml(details)
    
    def _display_evidence_details(self, evidence: EvidenceRow):
        """Display evidence details in details panel."""
        timestamp_str = evidence.timestamp.strftime("%Y-%m-%d %H:%M:%S") if evidence.timestamp else "No timestamp"
        
        details = f"""
<b>Evidence Details</b><br>
<b>Artifact:</b> {evidence.artifact}<br>
<b>Table:</b> {evidence.table}<br>
<b>Row ID:</b> {evidence.row_id}<br>
<b>Feather ID:</b> {evidence.feather_id}<br>
<b>Timestamp:</b> {timestamp_str}<br>
<b>Role:</b> {evidence.role.upper()}<br>
<b>Has Anchor:</b> {'Yes' if evidence.has_anchor else 'No'}<br>
<b>Confidence:</b> {evidence.confidence:.2f}<br>
<b>Match Method:</b> {evidence.match_method}<br>
<br>
<i>Double-click to view full details</i>
        """
        self.details_text.setHtml(details)
    
    def apply_filters(self):
        """Apply current filter settings and refresh results."""
        # Build filters from UI
        filters = QueryFilters()
        
        # Time range
        filters.start_time = self.start_time_edit.dateTime().toPyDateTime()
        filters.end_time = self.end_time_edit.dateTime().toPyDateTime()
        
        # Identity type
        identity_type = self.identity_type_combo.currentText()
        if identity_type != "All":
            filters.identity_type = identity_type
        
        # Search text
        search_text = self.search_edit.text().strip()
        if search_text:
            filters.identity_value = search_text
        
        self.current_filters = filters
        self.populate_tree()
    
    def refresh_results(self):
        """Refresh results from database."""
        self.populate_tree()
    
    def export_results(self):
        """Export results to file."""
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Results",
            "",
            "JSON Files (*.json);;CSV Files (*.csv);;All Files (*)"
        )
        
        if filename:
            try:
                # TODO: Implement export functionality
                QMessageBox.information(self, "Export", "Export functionality coming soon!")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export: {str(e)}")
