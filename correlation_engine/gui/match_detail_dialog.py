"""
Match Detail Dialog
Displays comprehensive details about a correlation match.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QGroupBox, QTreeWidget,
    QTreeWidgetItem, QScrollArea, QWidget
)
from PyQt5.QtCore import Qt


class MatchDetailDialog(QDialog):
    """
    Dialog for displaying detailed match information.
    
    Shows:
    - Match ID and anchor information
    - Matched feathers table with time deltas
    - Score breakdown
    - Semantic mappings
    - Duplicate information
    - Raw record data
    """
    
    def __init__(self, match, parent=None):
        """
        Initialize match detail dialog.
        
        Args:
            match: CorrelationMatch object
            parent: Parent widget
        """
        super().__init__(parent)
        self.match = match
        self.setup_ui()
    
    def setup_ui(self):
        """Setup dialog UI."""
        self.setWindowTitle("Match Details")
        self.setMinimumSize(800, 600)
        
        layout = QVBoxLayout(self)
        
        # Header section
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel(f"<b>Match ID:</b> {self.match.match_id}"))
        header_layout.addWidget(QLabel(
            f"<b>Anchor:</b> {self.match.anchor_feather_id} @ {self.match.timestamp}"
        ))
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        # Matched feathers table
        scroll_layout.addWidget(self.create_feathers_table())
        
        # Score breakdown
        scroll_layout.addWidget(self.create_score_breakdown())
        
        # Semantic mappings
        scroll_layout.addWidget(self.create_semantic_mappings_section())
        
        # Duplicate information
        scroll_layout.addWidget(self.create_duplicate_info_section())
        
        # Raw data tree
        scroll_layout.addWidget(self.create_raw_data_tree())
        
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        
        # Close button
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)
    
    def create_feathers_table(self):
        """Create matched feathers table."""
        group = QGroupBox("Matched Feathers")
        layout = QVBoxLayout()
        
        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels([
            "Feather", "Time Delta", "Application", "Path"
        ])
        table.setRowCount(len(self.match.feather_records))
        
        time_deltas = getattr(self.match, 'time_deltas', {})
        
        for row, (feather_id, record) in enumerate(self.match.feather_records.items()):
            table.setItem(row, 0, QTableWidgetItem(feather_id))
            
            # Time delta
            time_delta = time_deltas.get(feather_id, 0.0)
            delta_text = f"+{time_delta:.1f}s" if time_delta > 0 else f"{time_delta:.1f}s"
            table.setItem(row, 1, QTableWidgetItem(delta_text))
            
            # Application
            app = record.get('application', record.get('app_name', ''))
            table.setItem(row, 2, QTableWidgetItem(app))
            
            # Path
            path = record.get('file_path', record.get('path', ''))
            table.setItem(row, 3, QTableWidgetItem(path))
        
        table.resizeColumnsToContents()
        layout.addWidget(table)
        group.setLayout(layout)
        return group
    
    def create_score_breakdown(self):
        """Create score breakdown section."""
        group = QGroupBox("Score Breakdown")
        layout = QVBoxLayout()
        
        score_breakdown = getattr(self.match, 'score_breakdown', {})
        
        # Coverage
        coverage = score_breakdown.get('coverage', 0.0)
        layout.addWidget(QLabel(
            f"<b>Coverage:</b> {coverage:.4f} ({self.match.feather_count} feathers)"
        ))
        
        # Time Proximity
        time_prox = score_breakdown.get('time_proximity', 0.0)
        layout.addWidget(QLabel(
            f"<b>Time Proximity:</b> {time_prox:.4f} (spread: {self.match.time_spread_seconds:.1f}s)"
        ))
        
        # Field Similarity
        field_sim = score_breakdown.get('field_similarity', 0.0)
        layout.addWidget(QLabel(
            f"<b>Field Similarity:</b> {field_sim:.4f}"
        ))
        
        # Final Score
        layout.addWidget(QLabel(
            f"<b>Final Score:</b> {self.match.match_score:.4f}"
        ))
        
        # Confidence
        confidence_score = getattr(self.match, 'confidence_score', 0.0)
        confidence_category = getattr(self.match, 'confidence_category', 'Unknown')
        layout.addWidget(QLabel(
            f"<b>Confidence:</b> {confidence_category} ({confidence_score:.4f})"
        ))
        
        group.setLayout(layout)
        return group
    
    def create_semantic_mappings_section(self):
        """Create semantic mappings section."""
        group = QGroupBox("Semantic Mappings")
        layout = QVBoxLayout()
        
        semantic_data = getattr(self.match, 'semantic_data', None)
        
        if semantic_data and semantic_data.get('semantic_matches'):
            for mapping in semantic_data['semantic_matches']:
                text = (
                    f"• <b>{mapping['field']}:</b> "
                    f"{mapping['value1']} ≡ {mapping['value2']} "
                    f"(normalized to: {mapping['normalized']})"
                )
                label = QLabel(text)
                label.setWordWrap(True)
                layout.addWidget(label)
            
            # Show similarity scores
            if semantic_data.get('similarity_scores'):
                layout.addWidget(QLabel("<br><b>Similarity Scores:</b>"))
                for field, score in semantic_data['similarity_scores'].items():
                    layout.addWidget(QLabel(f"  • {field}: {score:.4f}"))
        else:
            layout.addWidget(QLabel("No semantic mappings applied"))
        
        group.setLayout(layout)
        return group
    
    def create_duplicate_info_section(self):
        """Create duplicate information section."""
        group = QGroupBox("Duplicate Information")
        layout = QVBoxLayout()
        
        is_duplicate = getattr(self.match, 'is_duplicate', False)
        
        if is_duplicate:
            dup_info = getattr(self.match, 'duplicate_info', None)
            if dup_info:
                layout.addWidget(QLabel(
                    f"<b>Status:</b> <span style='color: red;'>Duplicate</span>"
                ))
                layout.addWidget(QLabel(
                    f"<b>Original Match ID:</b> {dup_info.original_match_id}"
                ))
                layout.addWidget(QLabel(
                    f"<b>Original Anchor:</b> {dup_info.original_anchor_feather} @ {dup_info.original_anchor_time}"
                ))
                layout.addWidget(QLabel(
                    f"<b>Duplicate Count:</b> {dup_info.duplicate_count}"
                ))
            else:
                layout.addWidget(QLabel("<b>Status:</b> Duplicate (no details available)"))
        else:
            layout.addWidget(QLabel(
                "<b>Status:</b> <span style='color: green;'>Not a duplicate</span>"
            ))
        
        group.setLayout(layout)
        return group
    
    def create_raw_data_tree(self):
        """Create raw data tree view."""
        group = QGroupBox("Raw Record Data")
        layout = QVBoxLayout()
        
        tree = QTreeWidget()
        tree.setHeaderLabels(["Field", "Value"])
        tree.setMaximumHeight(300)
        
        for feather_id, record in self.match.feather_records.items():
            feather_item = QTreeWidgetItem([feather_id, ""])
            feather_item.setExpanded(True)
            
            for key, value in record.items():
                # Skip internal fields
                if key.startswith('_'):
                    continue
                
                value_str = str(value)
                if len(value_str) > 100:
                    value_str = value_str[:100] + "..."
                
                field_item = QTreeWidgetItem([key, value_str])
                field_item.setToolTip(1, str(value))
                feather_item.addChild(field_item)
            
            tree.addTopLevelItem(feather_item)
        
        tree.resizeColumnToContents(0)
        layout.addWidget(tree)
        group.setLayout(layout)
        return group
