"""
Identity Detail Dialog

Displays comprehensive information about an identity including:
- Overview with statistics
- All evidence (anchored and supporting)
- Semantic mappings
- Raw data export

Implements Task 9: Create Identity Detail Dialog
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QTableWidget, QTableWidgetItem, QTextEdit,
    QPushButton, QTreeWidget, QTreeWidgetItem, QFileDialog,
    QMessageBox, QHeaderView
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor
import json
from datetime import datetime
from typing import Optional

from correlation_engine.engine.data_structures import Identity
from correlation_engine.gui.timeline_widget import TimelineWidget


class IdentityDetailDialog(QDialog):
    """
    Detailed view of an identity with all associated evidence and metadata.
    
    Implements Task 9: Identity Detail Dialog
    """
    
    def __init__(self, identity: Identity, parent=None):
        """
        Initialize identity detail dialog.
        
        Args:
            identity: Identity object to display
            parent: Parent widget
        """
        super().__init__(parent)
        self.identity = identity
        self.setup_ui()
        self.load_data()
    
    def setup_ui(self):
        """Setup dialog UI with tabs."""
        self.setWindowTitle(f"Identity Details: {self.identity.primary_name}")
        self.setMinimumSize(1000, 700)
        
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel(f"<h2>{self.identity.primary_name}</h2>")
        layout.addWidget(title)
        
        # Tab widget
        self.tabs = QTabWidget()
        
        # Tab 1: Overview
        self.overview_tab = self._create_overview_tab()
        self.tabs.addTab(self.overview_tab, "Overview")
        
        # Tab 2: All Evidence
        self.evidence_tab = self._create_evidence_tab()
        self.tabs.addTab(self.evidence_tab, "All Evidence")
        
        # Tab 3: Timeline
        self.timeline_tab = TimelineWidget()
        self.tabs.addTab(self.timeline_tab, "Timeline")
        
        # Tab 4: Semantic Mappings
        self.semantic_tab = self._create_semantic_tab()
        self.tabs.addTab(self.semantic_tab, "Semantic Mappings")
        
        # Tab 5: Raw Data
        self.raw_tab = self._create_raw_tab()
        self.tabs.addTab(self.raw_tab, "Raw Data")
        
        layout.addWidget(self.tabs)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        export_btn = QPushButton("Export to JSON")
        export_btn.clicked.connect(self.export_to_json)
        button_layout.addWidget(export_btn)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
    
    def _create_overview_tab(self) -> QWidget:
        """Create overview tab with statistics."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Statistics section
        stats_label = QLabel("<h3>Statistics</h3>")
        layout.addWidget(stats_label)
        
        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        self.stats_text.setMaximumHeight(200)
        layout.addWidget(self.stats_text)
        
        # Artifact breakdown
        artifact_label = QLabel("<h3>Artifact Breakdown</h3>")
        layout.addWidget(artifact_label)
        
        self.artifact_table = QTableWidget()
        self.artifact_table.setColumnCount(2)
        self.artifact_table.setHorizontalHeaderLabels(["Artifact", "Count"])
        self.artifact_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.artifact_table)
        
        layout.addStretch()
        return widget
    
    def _create_evidence_tab(self) -> QWidget:
        """Create evidence tab showing all evidence."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Evidence tree
        self.evidence_tree = QTreeWidget()
        self.evidence_tree.setHeaderLabels(["Evidence", "Role", "Timestamp", "Artifact"])
        self.evidence_tree.setAlternatingRowColors(True)
        layout.addWidget(self.evidence_tree)
        
        return widget
    
    def _create_semantic_tab(self) -> QWidget:
        """Create semantic mappings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Semantic table
        self.semantic_table = QTableWidget()
        self.semantic_table.setColumnCount(5)
        self.semantic_table.setHorizontalHeaderLabels([
            "Evidence", "Category", "Meaning", "Severity", "Confidence"
        ])
        self.semantic_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.semantic_table)
        
        return widget
    
    def _create_raw_tab(self) -> QWidget:
        """Create raw data tab with JSON export."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Raw data text
        self.raw_text = QTextEdit()
        self.raw_text.setReadOnly(True)
        self.raw_text.setFont(QFont("Courier", 9))
        layout.addWidget(self.raw_text)
        
        # Copy button
        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.clicked.connect(self.copy_raw_data)
        layout.addWidget(copy_btn)
        
        return widget
    
    def load_data(self):
        """Load identity data into all tabs."""
        self._load_overview()
        self._load_evidence()
        self._load_timeline()
        self._load_semantic()
        self._load_raw()
    
    def _load_timeline(self):
        """Load timeline visualization."""
        # Set evidence for timeline
        self.timeline_tab.set_evidence(self.identity.all_evidence)
    
    def _load_overview(self):
        """Load overview statistics."""
        # Statistics
        stats_html = f"""
<b>Identity Information:</b><br>
Name: {self.identity.primary_name}<br>
Type: {self.identity.identity_type}<br>
Value: {self.identity.identity_value}<br>
Confidence: {self.identity.confidence:.2f}<br>
Match Method: {self.identity.match_method}<br>
<br>
<b>Evidence Summary:</b><br>
Total Evidence: {len(self.identity.all_evidence)}<br>
Total Anchors: {len(self.identity.anchors)}<br>
Artifacts Involved: {len(self.identity.artifacts_involved)}<br>
        """
        self.stats_text.setHtml(stats_html)
        
        # Artifact breakdown
        artifact_counts = {}
        for evidence in self.identity.all_evidence:
            artifact = evidence.artifact
            artifact_counts[artifact] = artifact_counts.get(artifact, 0) + 1
        
        self.artifact_table.setRowCount(len(artifact_counts))
        for i, (artifact, count) in enumerate(sorted(artifact_counts.items())):
            self.artifact_table.setItem(i, 0, QTableWidgetItem(artifact))
            self.artifact_table.setItem(i, 1, QTableWidgetItem(str(count)))
    
    def _load_evidence(self):
        """Load all evidence into tree."""
        self.evidence_tree.clear()
        
        # Group by anchors
        for anchor in self.identity.anchors:
            # Anchor item
            anchor_item = QTreeWidgetItem()
            start_str = anchor.start_time.strftime("%H:%M:%S") if anchor.start_time else "N/A"
            end_str = anchor.end_time.strftime("%H:%M:%S") if anchor.end_time else "N/A"
            anchor_item.setText(0, f"Anchor: {start_str} - {end_str}")
            anchor_item.setText(1, f"{len(anchor.rows)} evidence")
            anchor_item.setText(2, f"{anchor.duration_minutes:.1f} min")
            anchor_item.setText(3, anchor.primary_artifact or "N/A")
            
            font = QFont()
            font.setBold(True)
            anchor_item.setFont(0, font)
            
            self.evidence_tree.addTopLevelItem(anchor_item)
            
            # Evidence items
            for evidence in anchor.rows:
                evidence_item = QTreeWidgetItem()
                evidence_item.setText(0, evidence.feather_id)
                evidence_item.setText(1, evidence.role.upper())
                evidence_item.setText(2, evidence.timestamp.strftime("%Y-%m-%d %H:%M:%S") if evidence.timestamp else "N/A")
                evidence_item.setText(3, evidence.artifact)
                
                # Color by role
                if evidence.role == "primary":
                    evidence_item.setForeground(1, QColor(255, 100, 100))
                elif evidence.role == "secondary":
                    evidence_item.setForeground(1, QColor(255, 255, 100))
                else:
                    evidence_item.setForeground(1, QColor(100, 255, 100))
                
                anchor_item.addChild(evidence_item)
        
        # Supporting evidence
        supporting = [e for e in self.identity.all_evidence if not e.has_anchor]
        if supporting:
            support_item = QTreeWidgetItem()
            support_item.setText(0, "Supporting Evidence (No Timestamp)")
            support_item.setText(1, f"{len(supporting)} items")
            
            font = QFont()
            font.setBold(True)
            support_item.setFont(0, font)
            
            self.evidence_tree.addTopLevelItem(support_item)
            
            for evidence in supporting:
                evidence_item = QTreeWidgetItem()
                evidence_item.setText(0, evidence.feather_id)
                evidence_item.setText(1, "SUPPORTING")
                evidence_item.setText(2, "No timestamp")
                evidence_item.setText(3, evidence.artifact)
                evidence_item.setForeground(1, QColor(100, 255, 100))
                support_item.addChild(evidence_item)
        
        # Expand first level
        for i in range(self.evidence_tree.topLevelItemCount()):
            self.evidence_tree.topLevelItem(i).setExpanded(True)
    
    def _load_semantic(self):
        """Load semantic mappings."""
        semantic_evidence = [e for e in self.identity.all_evidence if e.semantic_data]
        
        self.semantic_table.setRowCount(len(semantic_evidence))
        
        for i, evidence in enumerate(semantic_evidence):
            self.semantic_table.setItem(i, 0, QTableWidgetItem(evidence.feather_id))
            
            if evidence.semantic_data:
                category = evidence.semantic_data.get('category', 'N/A')
                meaning = evidence.semantic_data.get('meaning', 'N/A')
                severity = evidence.semantic_data.get('severity', 'N/A')
                confidence = evidence.semantic_data.get('confidence', 0)
                
                self.semantic_table.setItem(i, 1, QTableWidgetItem(category))
                self.semantic_table.setItem(i, 2, QTableWidgetItem(meaning))
                self.semantic_table.setItem(i, 3, QTableWidgetItem(severity))
                self.semantic_table.setItem(i, 4, QTableWidgetItem(f"{confidence:.2f}"))
    
    def _load_raw(self):
        """Load raw data as JSON."""
        # Convert identity to dict
        data = {
            'identity_id': self.identity.identity_id,
            'identity_type': self.identity.identity_type,
            'identity_value': self.identity.identity_value,
            'primary_name': self.identity.primary_name,
            'confidence': self.identity.confidence,
            'match_method': self.identity.match_method,
            'total_evidence': len(self.identity.all_evidence),
            'total_anchors': len(self.identity.anchors),
            'artifacts_involved': self.identity.artifacts_involved,
            'anchors': [
                {
                    'anchor_id': a.anchor_id,
                    'start_time': a.start_time.isoformat() if a.start_time else None,
                    'end_time': a.end_time.isoformat() if a.end_time else None,
                    'duration_minutes': a.duration_minutes,
                    'evidence_count': len(a.rows),
                    'primary_artifact': a.primary_artifact
                }
                for a in self.identity.anchors
            ],
            'evidence': [
                {
                    'feather_id': e.feather_id,
                    'artifact': e.artifact,
                    'role': e.role,
                    'timestamp': e.timestamp.isoformat() if e.timestamp else None,
                    'has_anchor': e.has_anchor,
                    'confidence': e.confidence,
                    'semantic_data': e.semantic_data
                }
                for e in self.identity.all_evidence
            ]
        }
        
        json_str = json.dumps(data, indent=2)
        self.raw_text.setPlainText(json_str)
    
    def export_to_json(self):
        """Export identity data to JSON file."""
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Identity Data",
            f"{self.identity.primary_name}_identity.json",
            "JSON Files (*.json)"
        )
        
        if filename:
            try:
                with open(filename, 'w') as f:
                    f.write(self.raw_text.toPlainText())
                QMessageBox.information(self, "Success", f"Exported to {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export: {str(e)}")
    
    def copy_raw_data(self):
        """Copy raw data to clipboard."""
        from PyQt5.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(self.raw_text.toPlainText())
        QMessageBox.information(self, "Copied", "Raw data copied to clipboard")
