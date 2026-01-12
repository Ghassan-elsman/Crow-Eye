"""
Scoring Breakdown Widget

Displays weighted scoring information for correlation matches.
Shows overall score, interpretation, and detailed per-Feather breakdown.
"""

from typing import Dict, Any, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QFrame
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from .ui_styling import CorrelationEngineStyles



class ScoringBreakdownWidget(QWidget):
    """
    Widget for displaying weighted scoring breakdown.
    
    This widget provides a comprehensive view of how a match score was calculated,
    including:
    - Overall weighted score (prominently displayed)
    - Score interpretation label (e.g., "Confirmed Execution")
    - Detailed breakdown table showing all Feathers
    - Visual highlighting of matched vs unmatched Feathers
    - Weight, contribution, and tier information for each Feather
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Store semantic information for tooltips
        self.semantic_info = {}
        
        self._init_ui()
    
    def _init_ui(self):
        """Initialize UI components"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Overall score section (prominent display)
        score_section = self._create_score_section()
        layout.addWidget(score_section)
        
        # Breakdown table section
        breakdown_section = self._create_breakdown_section()
        layout.addWidget(breakdown_section)
    
    def _create_score_section(self) -> QWidget:
        """Create the prominent score display section"""
        widget = QFrame()
        widget.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        layout = QHBoxLayout(widget)
        
        # Score label
        score_label_text = QLabel("Weighted Score:")
        score_label_text.setFont(QFont("Arial", 10, QFont.Bold))
        layout.addWidget(score_label_text)
        
        self.score_value_label = QLabel("0.00")
        score_font = QFont("Arial", 16, QFont.Bold)
        self.score_value_label.setFont(score_font)
        self.score_value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.score_value_label)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)
        
        # Interpretation label
        interp_label_text = QLabel("Interpretation:")
        interp_label_text.setFont(QFont("Arial", 10, QFont.Bold))
        layout.addWidget(interp_label_text)
        
        self.interpretation_label = QLabel("N/A")
        interp_font = QFont("Arial", 14, QFont.Bold)
        self.interpretation_label.setFont(interp_font)
        self.interpretation_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.interpretation_label)
        
        layout.addStretch()
        
        # Match summary
        self.match_summary_label = QLabel("")
        self.match_summary_label.setFont(QFont("Arial", 9))
        layout.addWidget(self.match_summary_label)
        
        return widget
    
    def _create_breakdown_section(self) -> QWidget:
        """Create the detailed breakdown table section"""
        group = QGroupBox("Feather Contribution Breakdown")
        layout = QVBoxLayout(group)
        
        # Create breakdown table
        self.breakdown_table = QTableWidget()
        self.breakdown_table.setColumnCount(7)  # Added column for semantic info
        self.breakdown_table.setHorizontalHeaderLabels([
            "Feather", "Status", "Weight", "Contribution", "Tier", "Tier Description", "Semantic Info"
        ])
        
        # Configure table appearance
        self.breakdown_table.setAlternatingRowColors(True)
        self.breakdown_table.setSelectionMode(QTableWidget.NoSelection)
        self.breakdown_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.breakdown_table.verticalHeader().setVisible(False)
        
        # Set column resize modes
        header = self.breakdown_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)  # Feather name
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Status
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Weight
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Contribution
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Tier
        header.setSectionResizeMode(5, QHeaderView.Stretch)  # Tier description
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)  # Semantic info
        
        # Enable tooltips for the table
        self.breakdown_table.setMouseTracking(True)
        self.breakdown_table.cellEntered.connect(self._show_cell_tooltip)
        
        layout.addWidget(self.breakdown_table)
        
        # Legend
        legend_layout = QHBoxLayout()
        legend_layout.addWidget(QLabel("Legend:"))
        
        matched_label = QLabel("✓ = Matched")
        matched_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        legend_layout.addWidget(matched_label)
        
        unmatched_label = QLabel("✗ = Not Matched")
        unmatched_label.setStyleSheet("color: #9E9E9E;")
        legend_layout.addWidget(unmatched_label)
        
        semantic_label = QLabel("🔍 = Semantic Info Available")
        semantic_label.setStyleSheet("color: #2196F3; font-weight: bold;")
        legend_layout.addWidget(semantic_label)
        
        legend_layout.addStretch()
        layout.addLayout(legend_layout)
        
        return group
    
    def display_scoring(self, weighted_score: Optional[Dict[str, Any]], semantic_info: Optional[Dict[str, Any]] = None):
        """
        Display weighted scoring information with optional semantic data.
        
        Args:
            weighted_score: Dictionary containing:
                - score: float (overall weighted score)
                - interpretation: str (human-readable interpretation)
                - breakdown: dict (per-Feather breakdown)
                - matched_feathers: int (count of matched Feathers)
                - total_feathers: int (total Feathers in Wing)
            semantic_info: Optional dictionary containing semantic mapping information:
                - semantic_mappings: dict (field -> semantic data)
                - mapping_summary: dict (statistics about mappings)
        """
        if not weighted_score or not isinstance(weighted_score, dict):
            self._display_no_scoring()
            return
        
        # Store semantic info for tooltip display
        self.semantic_info = semantic_info or {}
        
        # Extract data
        score = weighted_score.get('score', 0.0)
        interpretation = weighted_score.get('interpretation', 'Unknown')
        breakdown = weighted_score.get('breakdown', {})
        matched_count = weighted_score.get('matched_feathers', 0)
        total_count = weighted_score.get('total_feathers', 0)
        
        # Update score display
        self.score_value_label.setText(f"{score:.2f}")
        self._apply_score_color(score, interpretation)
        
        # Update interpretation display
        self.interpretation_label.setText(interpretation)
        self._apply_interpretation_color(interpretation)
        
        # Update match summary with semantic info if available
        match_summary = f"({matched_count}/{total_count} Feathers matched)"
        if semantic_info and 'mapping_summary' in semantic_info:
            mapping_summary = semantic_info['mapping_summary']
            mapped_fields = mapping_summary.get('mapped_fields', 0)
            total_fields = mapping_summary.get('total_fields', 0)
            if total_fields > 0:
                match_summary += f", {mapped_fields}/{total_fields} fields mapped"
        
        self.match_summary_label.setText(match_summary)
        
        # Populate breakdown table with semantic information
        self._populate_breakdown_table(breakdown, semantic_info)
    
    def _display_no_scoring(self):
        """Display message when no weighted scoring is available"""
        self.score_value_label.setText("N/A")
        self.score_value_label.setStyleSheet("color: #9E9E9E;")
        
        self.interpretation_label.setText("Simple Scoring")
        self.interpretation_label.setStyleSheet("color: #9E9E9E;")
        
        self.match_summary_label.setText("(Weighted scoring not enabled)")
        
        self.breakdown_table.setRowCount(0)
    
    def _apply_score_color(self, score: float, interpretation: str):
        """Apply color coding to score based on interpretation"""
        if 'Confirmed' in interpretation:
            color = CorrelationEngineStyles.SCORE_CONFIRMED  # Green
        elif 'Probable' in interpretation or 'Likely' in interpretation:
            color = CorrelationEngineStyles.SCORE_PROBABLE  # Orange
        elif 'Weak' in interpretation or 'Insufficient' in interpretation:
            color = CorrelationEngineStyles.SCORE_WEAK  # Red
        else:
            color = CorrelationEngineStyles.SCORE_DEFAULT  # Blue (default)
        
        self.score_value_label.setStyleSheet(f"color: {color};")
    
    def _apply_interpretation_color(self, interpretation: str):
        """Apply color coding to interpretation label"""
        if 'Confirmed' in interpretation:
            color = CorrelationEngineStyles.SCORE_CONFIRMED  # Green
        elif 'Probable' in interpretation or 'Likely' in interpretation:
            color = CorrelationEngineStyles.SCORE_PROBABLE  # Orange
        elif 'Weak' in interpretation or 'Insufficient' in interpretation:
            color = CorrelationEngineStyles.SCORE_WEAK  # Red
        else:
            color = CorrelationEngineStyles.SCORE_DEFAULT  # Blue (default)
        
        self.interpretation_label.setStyleSheet(f"color: {color};")
    
    def _populate_breakdown_table(self, breakdown: Dict[str, Dict[str, Any]], semantic_info: Optional[Dict[str, Any]] = None):
        """
        Populate the breakdown table with Feather details and semantic information.
        
        Args:
            breakdown: Dictionary mapping feather_id to breakdown data:
                - matched: bool
                - weight: float
                - contribution: float
                - tier: int
                - tier_name: str
            semantic_info: Optional semantic mapping information
        """
        self.breakdown_table.setRowCount(0)
        
        # Sort by tier, then by weight (descending)
        sorted_items = sorted(
            breakdown.items(),
            key=lambda x: (x[1].get('tier', 999), -x[1].get('weight', 0.0))
        )
        
        semantic_mappings = {}
        if semantic_info and 'semantic_mappings' in semantic_info:
            semantic_mappings = semantic_info['semantic_mappings']
        
        for feather_id, data in sorted_items:
            row = self.breakdown_table.rowCount()
            self.breakdown_table.insertRow(row)
            
            matched = data.get('matched', False)
            weight = data.get('weight', 0.0)
            contribution = data.get('contribution', 0.0)
            tier = data.get('tier', 0)
            tier_name = data.get('tier_name', '')
            
            # Feather name
            feather_item = QTableWidgetItem(feather_id)
            if matched:
                feather_item.setFont(QFont("Arial", 9, QFont.Bold))
            
            # Add tooltip with detailed information
            tooltip_text = self._generate_feather_tooltip(feather_id, data, semantic_mappings)
            feather_item.setToolTip(tooltip_text)
            
            self.breakdown_table.setItem(row, 0, feather_item)
            
            # Status (matched/unmatched)
            status_item = QTableWidgetItem("✓" if matched else "✗")
            status_font = QFont("Arial", 12, QFont.Bold)
            status_item.setFont(status_font)
            status_item.setTextAlignment(Qt.AlignCenter)
            
            if matched:
                status_item.setForeground(QColor(CorrelationEngineStyles.MATCHED_COLOR))  # Green
                status_item.setBackground(QColor(CorrelationEngineStyles.MATCHED_BG))  # Light green background
            else:
                status_item.setForeground(QColor(CorrelationEngineStyles.UNMATCHED_COLOR))  # Gray
            
            # Add tooltip for status
            status_tooltip = f"{'Matched' if matched else 'Not matched'} in correlation results"
            if matched and contribution > 0:
                status_tooltip += f"\nContributed {contribution:.3f} to final score"
            status_item.setToolTip(status_tooltip)
            
            self.breakdown_table.setItem(row, 1, status_item)
            
            # Weight
            weight_item = QTableWidgetItem(f"{weight:.2f}")
            weight_item.setTextAlignment(Qt.AlignCenter)
            if matched:
                weight_item.setFont(QFont("Arial", 9, QFont.Bold))
            
            # Add tooltip for weight
            weight_tooltip = f"Weight: {weight:.3f}\nDetermines importance in scoring calculation"
            weight_item.setToolTip(weight_tooltip)
            
            self.breakdown_table.setItem(row, 2, weight_item)
            
            # Contribution
            contrib_item = QTableWidgetItem(f"{contribution:.2f}")
            contrib_item.setTextAlignment(Qt.AlignCenter)
            
            if matched and contribution > 0:
                contrib_item.setForeground(QColor(CorrelationEngineStyles.MATCHED_COLOR))  # Green
                contrib_item.setFont(QFont("Arial", 9, QFont.Bold))
            else:
                contrib_item.setForeground(QColor(CorrelationEngineStyles.UNMATCHED_COLOR))  # Gray
            
            # Add tooltip for contribution
            contrib_tooltip = f"Contribution: {contribution:.3f}\nActual contribution to final score"
            if matched:
                contrib_tooltip += f"\nCalculated as: weight ({weight:.3f}) × match factor"
            else:
                contrib_tooltip += "\nNo contribution (not matched)"
            contrib_item.setToolTip(contrib_tooltip)
            
            self.breakdown_table.setItem(row, 3, contrib_item)
            
            # Tier number
            tier_item = QTableWidgetItem(str(tier) if tier > 0 else "-")
            tier_item.setTextAlignment(Qt.AlignCenter)
            
            # Add tooltip for tier
            tier_tooltip = f"Tier {tier}: {tier_name}\nIndicates evidence priority level"
            tier_item.setToolTip(tier_tooltip)
            
            self.breakdown_table.setItem(row, 4, tier_item)
            
            # Tier description
            tier_desc_item = QTableWidgetItem(tier_name if tier_name else "-")
            if matched:
                tier_desc_item.setFont(QFont("Arial", 9, QFont.Bold))
            self.breakdown_table.setItem(row, 5, tier_desc_item)
            
            # Semantic information column
            semantic_item = self._create_semantic_info_item(feather_id, semantic_mappings)
            self.breakdown_table.setItem(row, 6, semantic_item)
            
            # Highlight matched rows
            if matched:
                for col in range(self.breakdown_table.columnCount()):
                    item = self.breakdown_table.item(row, col)
                    if item and col not in [1]:  # Skip status column (already colored)
                        item.setBackground(QColor(CorrelationEngineStyles.MATCHED_BG))  # Very light green
        
        self.breakdown_table.resizeRowsToContents()
    
    def _create_semantic_info_item(self, feather_id: str, semantic_mappings: Dict[str, Any]) -> QTableWidgetItem:
        """
        Create semantic information item for the breakdown table.
        
        Args:
            feather_id: Feather identifier
            semantic_mappings: Dictionary of semantic mappings
            
        Returns:
            QTableWidgetItem with semantic information
        """
        # Check if this feather has semantic mappings
        feather_semantic_info = semantic_mappings.get(feather_id, {})
        
        if feather_semantic_info:
            # Count semantic mappings for this feather
            mapping_count = len(feather_semantic_info)
            
            semantic_item = QTableWidgetItem("🔍")
            semantic_item.setTextAlignment(Qt.AlignCenter)
            semantic_item.setFont(QFont("Arial", 12))
            semantic_item.setForeground(QColor("#2196F3"))  # Blue
            
            # Create detailed tooltip
            tooltip_lines = [f"Semantic mappings for {feather_id}:"]
            
            for field_name, mapping_data in feather_semantic_info.items():
                semantic_value = mapping_data.get('semantic_value', 'N/A')
                category = mapping_data.get('category', 'N/A')
                confidence = mapping_data.get('confidence', 0.0)
                
                tooltip_lines.append(f"• {field_name}: {semantic_value}")
                tooltip_lines.append(f"  Category: {category}, Confidence: {confidence:.2f}")
            
            semantic_item.setToolTip("\n".join(tooltip_lines))
            
        else:
            semantic_item = QTableWidgetItem("-")
            semantic_item.setTextAlignment(Qt.AlignCenter)
            semantic_item.setForeground(QColor("#9E9E9E"))  # Gray
            semantic_item.setToolTip(f"No semantic mappings available for {feather_id}")
        
        return semantic_item
    
    def _generate_feather_tooltip(self, feather_id: str, breakdown_data: Dict[str, Any], 
                                semantic_mappings: Dict[str, Any]) -> str:
        """
        Generate comprehensive tooltip for feather item.
        
        Args:
            feather_id: Feather identifier
            breakdown_data: Breakdown data for this feather
            semantic_mappings: Semantic mapping information
            
        Returns:
            Formatted tooltip string
        """
        tooltip_lines = [f"Feather: {feather_id}"]
        
        # Scoring information
        matched = breakdown_data.get('matched', False)
        weight = breakdown_data.get('weight', 0.0)
        contribution = breakdown_data.get('contribution', 0.0)
        tier = breakdown_data.get('tier', 0)
        tier_name = breakdown_data.get('tier_name', '')
        
        tooltip_lines.append(f"Status: {'Matched' if matched else 'Not matched'}")
        tooltip_lines.append(f"Weight: {weight:.3f}")
        tooltip_lines.append(f"Contribution: {contribution:.3f}")
        tooltip_lines.append(f"Tier: {tier} ({tier_name})")
        
        # Semantic information
        feather_semantic_info = semantic_mappings.get(feather_id, {})
        if feather_semantic_info:
            tooltip_lines.append("")
            tooltip_lines.append("Semantic Mappings:")
            
            for field_name, mapping_data in feather_semantic_info.items():
                semantic_value = mapping_data.get('semantic_value', 'N/A')
                category = mapping_data.get('category', 'N/A')
                tooltip_lines.append(f"• {field_name}: {semantic_value} ({category})")
        else:
            tooltip_lines.append("")
            tooltip_lines.append("No semantic mappings available")
        
        return "\n".join(tooltip_lines)
    
    def _show_cell_tooltip(self, row: int, column: int):
        """
        Show tooltip when mouse enters a cell.
        
        Args:
            row: Row index
            column: Column index
        """
        item = self.breakdown_table.item(row, column)
        if item and item.toolTip():
            # The tooltip is already set on the item, Qt will handle display
            pass
    
    def clear(self):
        """Clear all displayed data"""
        self.score_value_label.setText("0.00")
        self.score_value_label.setStyleSheet("")
        
        self.interpretation_label.setText("N/A")
        self.interpretation_label.setStyleSheet("")
        
        self.match_summary_label.setText("")
        
        self.breakdown_table.setRowCount(0)
        
        # Clear semantic info
        self.semantic_info = {}
    
    def update_semantic_info(self, semantic_info: Dict[str, Any]):
        """
        Update semantic information for current scoring display.
        
        Args:
            semantic_info: Dictionary with semantic mapping information
        """
        self.semantic_info = semantic_info
        
        # If we have current scoring data, refresh the display
        if self.breakdown_table.rowCount() > 0:
            # Get current breakdown data from table and refresh with semantic info
            # This is a simplified refresh - in practice, you'd store the original data
            pass
    
    def get_semantic_info_for_feather(self, feather_id: str) -> Dict[str, Any]:
        """
        Get semantic information for a specific feather.
        
        Args:
            feather_id: Feather identifier
            
        Returns:
            Dictionary with semantic information for the feather
        """
        if not self.semantic_info or 'semantic_mappings' not in self.semantic_info:
            return {}
        
        return self.semantic_info['semantic_mappings'].get(feather_id, {})
