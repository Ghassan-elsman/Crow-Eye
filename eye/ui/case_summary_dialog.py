"""
Case Summary Dialog for EYE AI Forensic Assistant

This module provides a dialog for displaying the investigation timeline from the
investigation log. It shows a chronological list of queries, findings, and suggestions
with filtering capabilities.

Enhanced with tabbed interface for Investigation Timeline, Report Findings, and Charts.

"""

import logging
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from collections import Counter

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QGroupBox, QAbstractItemView, QMessageBox, QSizePolicy,
    QTabWidget, QWidget, QTextBrowser, QFileDialog
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPalette, QColor, QFont
from PyQt5.QtWebEngineWidgets import QWebEngineView

from eye.models.report_blocks import ReportBlock, TextBlock, TableBlock, ImageBlock, ChartBlock


logger = logging.getLogger(__name__)


class CaseSummaryDialog(QDialog):
    """
    Dialog for displaying investigation timeline from investigation log.
    
    Shows a chronological list of all queries, findings, and suggestions from the
    investigation log with filtering capabilities by evidence_found status.
    
    Enhanced with tabbed interface for Investigation Timeline, Report Findings, and Charts.
    
    The dialog follows the UI pattern from CaseSetupDialog and CaseContextEditDialog
    with dark theme styling and user-friendly layout.
    
    """
    
    def __init__(
        self, 
        timeline_entries: List[Dict[str, Any]],
        report_blocks: Optional[List[ReportBlock]] = None,
        parent=None
    ):
        """
        Initialize the case summary dialog.
        
        Args:
            timeline_entries: List of investigation log entries from get_investigation_timeline()
            report_blocks: Optional list of imported report blocks
            parent: Parent widget (typically the main window or EYE tab)
            
        """
        super().__init__(parent)
        
        # Set window flags for independent styling
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        
        # Store timeline entries and report blocks
        self.timeline_entries = timeline_entries or []
        self.filtered_entries = self.timeline_entries.copy()
        self.report_blocks = report_blocks or []
        self.filtered_blocks = self.report_blocks.copy()
        
        # UI components
        self.tab_widget = None
        self.filter_combo = None
        self.timeline_table = None
        self.entry_count_label = None
        self.findings_filter = None
        self.findings_table = None
        self.detail_pane = None
        
        self._init_ui()
        self._apply_styling()
    
    def _init_ui(self):
        """
        Initialize the user interface components with tabbed interface.
        
        """
        self.setWindowTitle("Case Summary")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(40, 40, 40, 20)
        
        # Title
        title = QLabel("Case Summary")
        title.setStyleSheet(
            "font-size: 18pt; font-weight: bold; color: #00FFFF; background: transparent;"
        )
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)
        
        # Subtitle
        subtitle = QLabel(
            "Investigation timeline, report findings, and analysis charts."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            "font-size: 11pt; color: #9CA3AF; background: transparent;"
        )
        subtitle.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(subtitle)
        
        main_layout.addSpacing(10)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 2px solid #334155;
                border-radius: 8px;
                background: #111827;
                padding: 10px;
            }
            QTabBar::tab {
                background: #1E293B;
                color: #9CA3AF;
                padding: 10px 20px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 11pt;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: #334155;
                color: #00FFFF;
            }
            QTabBar::tab:hover {
                background: #334155;
                color: #F8FAFC;
            }
        """)
        
        # Add tabs
        self.tab_widget.addTab(self._init_timeline_tab(), "Investigation Timeline")
        self.tab_widget.addTab(self._init_report_findings_tab(), "Report Findings")
        self.tab_widget.addTab(self._init_charts_tab(), "Charts")
        
        main_layout.addWidget(self.tab_widget, 1)
        
        # Button layout
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        button_layout.setContentsMargins(0, 12, 0, 0)
        
        button_layout.addStretch()
        
        # Export Summary button
        export_button = QPushButton("Export Summary")
        export_button.setFixedHeight(40)
        export_button.setMinimumWidth(160)
        export_button.setStyleSheet("""
            QPushButton {
                background-color: #06b6d4;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 11pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0891b2;
            }
            QPushButton:pressed {
                background-color: #0e7490;
            }
        """)
        export_button.clicked.connect(self._on_export_summary_clicked)
        button_layout.addWidget(export_button)
        
        # Close button
        close_button = QPushButton("Close")
        close_button.setFixedHeight(40)
        close_button.setMinimumWidth(140)
        close_button.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 11pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #475569;
            }
            QPushButton:pressed {
                background-color: #1E293B;
            }
        """)
        close_button.clicked.connect(self.accept)
        button_layout.addWidget(close_button)
        
        main_layout.addLayout(button_layout)
    
    def _init_timeline_tab(self) -> QWidget:
        """
        Initialize the Investigation Timeline tab.
        
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Filter controls
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(12)
        
        filter_label = QLabel("Filter by Evidence:")
        filter_label.setStyleSheet(
            "font-size: 11pt; font-weight: bold; color: #E5E7EB; background: transparent;"
        )
        filter_layout.addWidget(filter_label)
        
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "Evidence Found", "No Evidence"])
        self.filter_combo.setMinimumWidth(200)
        self.filter_combo.setStyleSheet("""
            QComboBox {
                background: #1E293B;
                border: 2px solid #334155;
                padding: 8px 12px;
                color: #F8FAFC;
                font-size: 10pt;
                border-radius: 4px;
            }
            QComboBox:hover {
                border: 2px solid #00FFFF;
            }
            QComboBox::drop-down {
                border: none;
                padding-right: 8px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #F8FAFC;
                margin-right: 5px;
            }
            QComboBox QAbstractItemView {
                background: #1E293B;
                border: 2px solid #334155;
                color: #F8FAFC;
                selection-background-color: #334155;
                selection-color: #00FFFF;
            }
        """)
        self.filter_combo.currentTextChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.filter_combo)
        
        filter_layout.addStretch()
        
        # Entry count label
        self.entry_count_label = QLabel()
        self.entry_count_label.setStyleSheet(
            "font-size: 10pt; color: #9CA3AF; background: transparent;"
        )
        filter_layout.addWidget(self.entry_count_label)
        
        layout.addLayout(filter_layout)
        
        # Timeline table
        self.timeline_table = QTableWidget()
        self.timeline_table.setColumnCount(6)
        self.timeline_table.setHorizontalHeaderLabels([
            "Timestamp", "Action/Query", "Forensic Summary", "Evidence", "Artifacts", "Next Steps"
        ])
        
        # Table styling
        self.timeline_table.setStyleSheet("""
            QTableWidget {
                background: #0F172A;
                border: none;
                color: #E5E7EB;
                gridline-color: #334155;
                font-size: 10pt;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #334155;
            }
            QTableWidget::item:selected {
                background: #1E293B;
                color: #00FFFF;
            }
            QHeaderView::section {
                background: #1E293B;
                color: #00FFFF;
                padding: 10px;
                border: none;
                border-bottom: 2px solid #334155;
                font-weight: bold;
                font-size: 10pt;
            }
            QScrollBar:vertical {
                background: #1E293B;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #334155;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #475569;
            }
            QScrollBar:horizontal {
                background: #1E293B;
                height: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal {
                background: #334155;
                border-radius: 6px;
                min-width: 20px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #475569;
            }
        """)
        
        # Table behavior
        self.timeline_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.timeline_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.timeline_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.timeline_table.setAlternatingRowColors(False)
        self.timeline_table.verticalHeader().setVisible(False)
        
        # Column sizing
        # Column sizing - optimized for uncollapsed view
        header = self.timeline_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Timestamp
        header.setSectionResizeMode(1, QHeaderView.Interactive)       # Query
        header.setSectionResizeMode(2, QHeaderView.Stretch)           # Forensic Summary
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Evidence
        header.setSectionResizeMode(4, QHeaderView.Interactive)       # Artifacts
        header.setSectionResizeMode(5, QHeaderView.Interactive)       # Next Steps
        
        # Set specific widths to prevent 'collapsed' look
        self.timeline_table.setColumnWidth(0, 160)  # Timestamp
        self.timeline_table.setColumnWidth(1, 250)  # Query
        self.timeline_table.setColumnWidth(3, 80)   # Evidence
        self.timeline_table.setColumnWidth(4, 150)  # Artifacts
        self.timeline_table.setColumnWidth(5, 200)  # Next Steps
        
        layout.addWidget(self.timeline_table)
        
        # Populate timeline
        self._populate_timeline()
        
        return tab
    
    def _init_report_findings_tab(self) -> QWidget:
        """
        Initialize the Report Findings tab.
        
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Statistics panel
        stats_group = QGroupBox("Report Statistics")
        stats_group.setStyleSheet("""
            QGroupBox {
                border: 2px solid #334155;
                border-radius: 6px;
                padding-top: 15px;
                margin-top: 10px;
                background: #1E293B;
                color: #00FFFF;
                font-weight: bold;
                font-size: 11pt;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(20)
        
        # Count blocks by type
        text_count = len([b for b in self.report_blocks if b.block_type == "text"])
        table_count = len([b for b in self.report_blocks if b.block_type == "table"])
        image_count = len([b for b in self.report_blocks if b.block_type == "image"])
        chart_count = len([b for b in self.report_blocks if b.block_type == "chart"])
        
        stats_layout.addWidget(self._create_stat_label("Total", len(self.report_blocks)))
        stats_layout.addWidget(self._create_stat_label("Text", text_count))
        stats_layout.addWidget(self._create_stat_label("Tables", table_count))
        stats_layout.addWidget(self._create_stat_label("Images", image_count))
        stats_layout.addWidget(self._create_stat_label("Charts", chart_count))
        stats_layout.addStretch()
        
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        # Filter dropdown
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(12)
        
        filter_label = QLabel("Filter by Type:")
        filter_label.setStyleSheet(
            "font-size: 11pt; font-weight: bold; color: #E5E7EB; background: transparent;"
        )
        filter_layout.addWidget(filter_label)
        
        self.findings_filter = QComboBox()
        self.findings_filter.addItems(["All", "Text", "Table", "Image", "Chart"])
        self.findings_filter.setMinimumWidth(200)
        self.findings_filter.setStyleSheet("""
            QComboBox {
                background: #1E293B;
                border: 2px solid #334155;
                padding: 8px 12px;
                color: #F8FAFC;
                font-size: 10pt;
                border-radius: 4px;
            }
            QComboBox:hover {
                border: 2px solid #00FFFF;
            }
            QComboBox::drop-down {
                border: none;
                padding-right: 8px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #F8FAFC;
                margin-right: 5px;
            }
            QComboBox QAbstractItemView {
                background: #1E293B;
                border: 2px solid #334155;
                color: #F8FAFC;
                selection-background-color: #334155;
                selection-color: #00FFFF;
            }
        """)
        self.findings_filter.currentTextChanged.connect(self._on_findings_filter_changed)
        filter_layout.addWidget(self.findings_filter)
        filter_layout.addStretch()
        
        layout.addLayout(filter_layout)
        
        # Findings table
        self.findings_table = QTableWidget()
        self.findings_table.setColumnCount(4)
        self.findings_table.setHorizontalHeaderLabels([
            "Type", "Title/Caption", "Timestamp", "Source Report"
        ])
        
        # Table styling
        self.findings_table.setStyleSheet("""
            QTableWidget {
                background: #0F172A;
                border: none;
                color: #E5E7EB;
                gridline-color: #334155;
                font-size: 10pt;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #334155;
            }
            QTableWidget::item:selected {
                background: #1E293B;
                color: #00FFFF;
            }
            QHeaderView::section {
                background: #1E293B;
                color: #00FFFF;
                padding: 10px;
                border: none;
                border-bottom: 2px solid #334155;
                font-weight: bold;
                font-size: 10pt;
            }
            QScrollBar:vertical {
                background: #1E293B;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #334155;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #475569;
            }
        """)
        
        # Table behavior
        self.findings_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.findings_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.findings_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.findings_table.verticalHeader().setVisible(False)
        
        # Column sizing
        header = self.findings_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Type
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Title/Caption
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Timestamp
        header.setSectionResizeMode(3, QHeaderView.Stretch)  # Source Report
        
        self.findings_table.itemSelectionChanged.connect(self._on_finding_selected)
        layout.addWidget(self.findings_table, 1)
        
        # Detail pane
        detail_label = QLabel("Detail View:")
        detail_label.setStyleSheet(
            "font-size: 11pt; font-weight: bold; color: #E5E7EB; background: transparent; margin-top: 10px;"
        )
        layout.addWidget(detail_label)
        
        self.detail_pane = QTextBrowser()
        self.detail_pane.setMinimumHeight(200)
        self.detail_pane.setMaximumHeight(300)
        self.detail_pane.setStyleSheet("""
            QTextBrowser {
                background: #0F172A;
                border: 2px solid #334155;
                border-radius: 6px;
                color: #E5E7EB;
                padding: 10px;
                font-size: 10pt;
            }
            QScrollBar:vertical {
                background: #1E293B;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #334155;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #475569;
            }
        """)
        layout.addWidget(self.detail_pane)
        
        # Populate findings table
        self._populate_findings_table()
        
        return tab
    
    def _init_charts_tab(self) -> QWidget:
        """
        Initialize the Charts tab with investigation visualizations.
        
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)
        layout.setContentsMargins(10, 10, 10, 10)
        
        if len(self.timeline_entries) < 3:
            label = QLabel(
                "Insufficient data for visualization\n"
                "(minimum 3 entries required)"
            )
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(
                "font-size: 14pt; color: #9CA3AF; background: transparent; padding: 50px;"
            )
            layout.addWidget(label)
            return tab
        
        # Chart 1: Timeline Activity (entries per day)
        activity_chart = self._create_activity_chart()
        layout.addWidget(activity_chart)
        
        # Chart 2: Evidence Ratio (pie chart)
        evidence_chart = self._create_evidence_chart()
        layout.addWidget(evidence_chart)
        
        # Chart 3: Top Artifact Types (bar chart)
        artifact_chart = self._create_artifact_types_chart()
        layout.addWidget(artifact_chart)
        
        return tab
    
    def _apply_styling(self):
        """Apply comprehensive dark theme styling to the dialog."""
        # Set palette for backup styling
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor("#0B1220"))
        palette.setColor(QPalette.WindowText, QColor("#E5E7EB"))
        palette.setColor(QPalette.Base, QColor("#1E293B"))
        palette.setColor(QPalette.Text, QColor("#F8FAFC"))
        self.setPalette(palette)
        
        # Main dialog stylesheet
        dialog_style = """
            QDialog {
                background-color: #0B1220;
                color: #E5E7EB;
                font-size: 10pt;
            }
            QWidget {
                background-color: #0B1220;
                color: #E5E7EB;
            }
            QLabel {
                color: #E5E7EB;
                font-size: 10pt;
                background: transparent;
            }
        """
        
        self.setStyleSheet(dialog_style)
    
    def _populate_timeline(self):
        """
        Populate the timeline table with investigation log entries.
        
        Displays entries in chronological order with all relevant information.
        
        """
        # Clear existing rows
        self.timeline_table.setRowCount(0)
        
        if not self.filtered_entries:
            logger.info("No timeline entries to display")
            self._update_entry_count()
            return
        
        # Sort entries by timestamp (chronological order)
        sorted_entries = sorted(
            self.filtered_entries,
            key=lambda x: x.get("timestamp", ""),
            reverse=False  # Oldest first
        )
        
        # Populate table
        for entry in sorted_entries:
            row_position = self.timeline_table.rowCount()
            self.timeline_table.insertRow(row_position)
            
            # Timestamp
            timestamp_str = entry.get("timestamp", "")
            formatted_timestamp = self._format_timestamp(timestamp_str)
            timestamp_item = QTableWidgetItem(formatted_timestamp)
            timestamp_item.setFont(QFont("Consolas", 9))
            self.timeline_table.setItem(row_position, 0, timestamp_item)
            
            # Query
            query = entry.get("query", "")
            query_item = QTableWidgetItem(query)
            query_item.setToolTip(query)
            self.timeline_table.setItem(row_position, 1, query_item)
            
            # Response Summary
            response_summary = entry.get("response_summary", "")
            response_item = QTableWidgetItem(response_summary)
            response_item.setToolTip(response_summary)
            self.timeline_table.setItem(row_position, 2, response_item)
            
            # Evidence Found
            evidence_found = entry.get("evidence_found", False)
            if evidence_found:
                evidence_item = QTableWidgetItem("FOUND")
                evidence_item.setForeground(QColor("#00FFFF")) # Cyan
                evidence_item.setFont(QFont("", 9, QFont.Bold))
            else:
                evidence_item = QTableWidgetItem("-")
                evidence_item.setForeground(QColor("#6B7280"))
            evidence_item.setTextAlignment(Qt.AlignCenter)
            self.timeline_table.setItem(row_position, 3, evidence_item)
            
            # Artifacts Queried (New Column)
            artifacts = entry.get("artifacts_queried", [])
            art_text = ", ".join(artifacts) if artifacts else "—"
            art_item = QTableWidgetItem(art_text)
            art_item.setFont(QFont("Consolas", 8))
            art_item.setToolTip(art_text)
            self.timeline_table.setItem(row_position, 4, art_item)
            
            # Suggested Next Steps
            suggested_next_steps = entry.get("suggested_next_steps", "")
            steps_item = QTableWidgetItem(suggested_next_steps or "—")
            steps_item.setToolTip(suggested_next_steps)
            self.timeline_table.setItem(row_position, 5, steps_item)
            
            # Set row height
            self.timeline_table.setRowHeight(row_position, 50)
        
        logger.info(f"Populated timeline table with {len(sorted_entries)} entries")
        self._update_entry_count()
    
    def _format_timestamp(self, timestamp_str: str) -> str:
        """
        Format ISO 8601 timestamp for display.
        
        Args:
            timestamp_str: ISO 8601 timestamp string
            
        Returns:
            Formatted timestamp string (YYYY-MM-DD HH:MM:SS)
        """
        if not timestamp_str:
            return "Unknown"
        
        try:
            # Parse ISO 8601 timestamp
            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            # Format for display
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            logger.warning(f"Error formatting timestamp '{timestamp_str}': {e}")
            return timestamp_str
    
    def _on_filter_changed(self, filter_text: str):
        """
        Handle filter selection change.
        
        Filters timeline entries based on evidence_found status.
        
        Args:
            filter_text: Selected filter text ("All", "Evidence Found", "No Evidence")
            
        """
        logger.info(f"Filter changed to: {filter_text}")
        
        if filter_text == "All":
            # Show all entries
            self.filtered_entries = self.timeline_entries.copy()
        elif filter_text == "Evidence Found":
            # Show only entries with evidence
            self.filtered_entries = [
                entry for entry in self.timeline_entries
                if entry.get("evidence_found")
            ]
        elif filter_text == "No Evidence":
            # Show only entries without evidence
            self.filtered_entries = [
                entry for entry in self.timeline_entries
                if not entry.get("evidence_found")
            ]
        else:
            logger.warning(f"Unknown filter: {filter_text}")
            self.filtered_entries = self.timeline_entries.copy()
        
        # Repopulate table with filtered entries
        self._populate_timeline()
    
    def _update_entry_count(self):
        """Update the entry count label."""
        total = len(self.timeline_entries)
        filtered = len(self.filtered_entries)
        
        if total == filtered:
            self.entry_count_label.setText(f"Showing {total} entries")
        else:
            self.entry_count_label.setText(f"Showing {filtered} of {total} entries")
    
    def _create_stat_label(self, label: str, count: int) -> QLabel:
        """
        Create a statistics label for the Report Findings tab.
        
        Args:
            label: Label text
            count: Count value
            
        Returns:
            Styled QLabel widget
        """
        stat_label = QLabel(f"{label}: {count}")
        stat_label.setStyleSheet(
            "font-size: 11pt; color: #F8FAFC; background: transparent; font-weight: bold;"
        )
        return stat_label
    
    def _populate_findings_table(self):
        """
        Populate the findings table with report blocks.
        
        """
        # Clear existing rows
        self.findings_table.setRowCount(0)
        
        if not self.filtered_blocks:
            logger.info("No report blocks to display")
            return
        
        # Sort blocks by timestamp
        sorted_blocks = sorted(
            self.filtered_blocks,
            key=lambda x: x.metadata.get("timestamp", ""),
            reverse=False
        )
        
        # Populate table
        for block in sorted_blocks:
            row_position = self.findings_table.rowCount()
            self.findings_table.insertRow(row_position)
            
            # Type
            type_item = QTableWidgetItem(block.block_type.capitalize())
            type_item.setFont(QFont("", 10, QFont.Bold))
            self.findings_table.setItem(row_position, 0, type_item)
            
            # Title/Caption
            title_caption = ""
            if hasattr(block, 'title') and block.title:
                title_caption = block.title
            elif hasattr(block, 'caption') and block.caption:
                title_caption = block.caption
            else:
                title_caption = f"{block.block_type.capitalize()} Block"
            
            title_item = QTableWidgetItem(title_caption)
            title_item.setToolTip(title_caption)
            self.findings_table.setItem(row_position, 1, title_item)
            
            # Timestamp
            timestamp_str = block.metadata.get("timestamp", "")
            formatted_timestamp = self._format_timestamp(timestamp_str)
            timestamp_item = QTableWidgetItem(formatted_timestamp)
            timestamp_item.setFont(QFont("Consolas", 9))
            self.findings_table.setItem(row_position, 2, timestamp_item)
            
            # Source Report
            source = block.metadata.get("source", "Unknown")
            source_item = QTableWidgetItem(source)
            source_item.setToolTip(source)
            self.findings_table.setItem(row_position, 3, source_item)
            
            # Set row height
            self.findings_table.setRowHeight(row_position, 50)
            
            # Store block reference in row
            self.findings_table.item(row_position, 0).setData(Qt.UserRole, block)
        
        logger.info(f"Populated findings table with {len(sorted_blocks)} blocks")
    
    def _on_findings_filter_changed(self, filter_text: str):
        """
        Handle findings filter selection change.
        
        Args:
            filter_text: Selected filter text
            
        """
        logger.info(f"Findings filter changed to: {filter_text}")
        
        if filter_text == "All":
            self.filtered_blocks = self.report_blocks.copy()
        else:
            # Filter by block type (lowercase for comparison)
            filter_type = filter_text.lower()
            self.filtered_blocks = [
                block for block in self.report_blocks
                if block.block_type == filter_type
            ]
        
        # Repopulate table with filtered blocks
        self._populate_findings_table()
    
    def _on_finding_selected(self):
        """
        Handle finding selection in the findings table.
        
        Displays the selected block content in the detail pane.
        
        """
        selected_items = self.findings_table.selectedItems()
        if not selected_items:
            self.detail_pane.clear()
            return
        
        # Get the block from the first column item
        row = selected_items[0].row()
        type_item = self.findings_table.item(row, 0)
        block = type_item.data(Qt.UserRole)
        
        if not block:
            self.detail_pane.clear()
            return
        
        # Render block content based on type
        self._render_block_detail(block)
    
    def _render_block_detail(self, block: ReportBlock):
        """
        Render block content in the detail pane.
        
        Args:
            block: ReportBlock to render
            
        """
        if isinstance(block, TextBlock):
            # Render markdown content as HTML
            html = f"""
            <html>
            <head>
                <style>
                    body {{ background: #0F172A; color: #E5E7EB; font-family: sans-serif; padding: 10px; }}
                    h1, h2, h3 {{ color: #00FFFF; }}
                    p {{ line-height: 1.6; }}
                </style>
            </head>
            <body>
                <h2>{block.title}</h2>
                <div>{block.markdown_content}</div>
            </body>
            </html>
            """
            self.detail_pane.setHtml(html)
        
        elif isinstance(block, TableBlock):
            # Render table with styling
            rows_html = ""
            for row in block.rows[:10]:  # Limit to first 10 rows for detail pane
                row_html = "<tr>"
                for col in block.columns:
                    value = row.get(col, "")
                    row_html += f"<td>{value}</td>"
                row_html += "</tr>"
                rows_html += row_html
            
            html = f"""
            <html>
            <head>
                <style>
                    body {{ background: #0F172A; color: #E5E7EB; font-family: sans-serif; padding: 10px; }}
                    h3 {{ color: #00FFFF; margin-bottom: 10px; }}
                    table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
                    th, td {{ border: 1px solid #334155; padding: 8px; text-align: left; }}
                    th {{ background: #1E293B; color: #00FFFF; font-weight: bold; }}
                    tr:nth-child(even) {{ background: #1E293B; }}
                    .caption {{ color: #9CA3AF; font-style: italic; margin-bottom: 10px; }}
                </style>
            </head>
            <body>
                <h3>Table: {block.caption}</h3>
                <div class="caption">Showing first 10 rows of {len(block.rows)} total</div>
                <table>
                    <thead>
                        <tr>{''.join(f'<th>{col}</th>' for col in block.columns)}</tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </body>
            </html>
            """
            self.detail_pane.setHtml(html)
        
        elif isinstance(block, ImageBlock):
            # Display image with caption
            html = f"""
            <html>
            <head>
                <style>
                    body {{ background: #0F172A; color: #E5E7EB; font-family: sans-serif; padding: 10px; text-align: center; }}
                    img {{ max-width: 100%; height: auto; border: 2px solid #334155; border-radius: 6px; }}
                    .caption {{ color: #9CA3AF; font-style: italic; margin-top: 10px; }}
                </style>
            </head>
            <body>
                <img src="file:///{block.image_path}" alt="{block.caption}">
                <div class="caption">{block.caption}</div>
            </body>
            </html>
            """
            self.detail_pane.setHtml(html)
        
        else:
            # Generic block display
            html = f"""
            <html>
            <head>
                <style>
                    body {{ background: #0F172A; color: #E5E7EB; font-family: sans-serif; padding: 10px; }}
                    h3 {{ color: #00FFFF; }}
                </style>
            </head>
            <body>
                <h3>{block.block_type.capitalize()} Block</h3>
                <p>Block ID: {block.block_id}</p>
                <p>Timestamp: {block.metadata.get('timestamp', 'Unknown')}</p>
            </body>
            </html>
            """
            self.detail_pane.setHtml(html)
    
    def _create_activity_chart(self) -> QWebEngineView:
        """
        Create timeline activity bar chart.
        
        """
        # Group entries by date
        date_counts = {}
        for entry in self.timeline_entries:
            timestamp = entry.get("timestamp", "")
            if timestamp:
                try:
                    date = timestamp.split("T")[0]
                except:
                    date = "Unknown"
            else:
                date = "Unknown"
            date_counts[date] = date_counts.get(date, 0) + 1
        
        # Sort by date
        sorted_dates = sorted([d for d in date_counts.keys() if d != "Unknown"])
        if "Unknown" in date_counts:
            sorted_dates.append("Unknown")
        counts = [date_counts[d] for d in sorted_dates]
        
        # Generate Chart.js HTML
        chart_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
            <style>
                body {{ background: #0B1220; margin: 0; padding: 20px; }}
                canvas {{ max-height: 250px; }}
            </style>
        </head>
        <body>
            <canvas id="activityChart"></canvas>
            <script>
                new Chart(document.getElementById('activityChart'), {{
                    type: 'bar',
                    data: {{
                        labels: {json.dumps(sorted_dates)},
                        datasets: [{{
                            label: 'Timeline Entries',
                            data: {json.dumps(counts)},
                            backgroundColor: '#f97316'
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{
                            title: {{
                                display: true,
                                text: 'Investigation Activity Over Time',
                                color: '#f97316',
                                font: {{ size: 16 }}
                            }},
                            legend: {{ labels: {{ color: '#e8edf5' }} }}
                        }},
                        scales: {{
                            y: {{ 
                                ticks: {{ color: '#8899aa' }},
                                grid: {{ color: '#1e2a3a' }}
                            }},
                            x: {{ 
                                ticks: {{ color: '#8899aa' }},
                                grid: {{ color: '#1e2a3a' }}
                            }}
                        }}
                    }}
                }});
            </script>
        </body>
        </html>
        """
        
        view = QWebEngineView()
        view.setHtml(chart_html)
        view.setMinimumHeight(300)
        view.setMaximumHeight(300)
        return view
    
    def _create_evidence_chart(self) -> QWebEngineView:
        """
        Create evidence ratio pie chart.
        
        """
        # Count evidence found vs not found
        evidence_found = sum(1 for entry in self.timeline_entries if entry.get("evidence_found"))
        no_evidence = len(self.timeline_entries) - evidence_found
        
        # Generate Chart.js HTML
        chart_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
            <style>
                body {{ background: #0B1220; margin: 0; padding: 20px; }}
                canvas {{ max-height: 250px; }}
            </style>
        </head>
        <body>
            <canvas id="evidenceChart"></canvas>
            <script>
                new Chart(document.getElementById('evidenceChart'), {{
                    type: 'pie',
                    data: {{
                        labels: ['Evidence Found', 'No Evidence'],
                        datasets: [{{
                            label: 'Queries',
                            data: [{evidence_found}, {no_evidence}],
                            backgroundColor: ['#10b981', '#6b7280']
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{
                            title: {{
                                display: true,
                                text: 'Evidence Found Ratio',
                                color: '#f97316',
                                font: {{ size: 16 }}
                            }},
                            legend: {{ 
                                labels: {{ color: '#e8edf5' }},
                                position: 'right'
                            }}
                        }}
                    }}
                }});
            </script>
        </body>
        </html>
        """
        
        view = QWebEngineView()
        view.setHtml(chart_html)
        view.setMinimumHeight(300)
        view.setMaximumHeight(300)
        return view
    
    def _create_artifact_types_chart(self) -> QWebEngineView:
        """
        Create top artifact types bar chart.
        
        """
        # Extract artifact types from queries
        artifact_keywords = [
            "prefetch", "mft", "registry", "usn", "browser", 
            "amcache", "shellbags", "lnk", "jumplists", "timeline"
        ]
        
        artifact_counts = Counter()
        for entry in self.timeline_entries:
            query = entry.get("query", "").lower()
            for keyword in artifact_keywords:
                if keyword in query:
                    artifact_counts[keyword] += 1
        
        # Get top 5
        top_artifacts = artifact_counts.most_common(5)
        if not top_artifacts:
            # No artifacts found, show placeholder
            labels = ["No Data"]
            counts = [0]
        else:
            labels = [artifact.capitalize() for artifact, _ in top_artifacts]
            counts = [count for _, count in top_artifacts]
        
        # Generate Chart.js HTML
        chart_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
            <style>
                body {{ background: #0B1220; margin: 0; padding: 20px; }}
                canvas {{ max-height: 250px; }}
            </style>
        </head>
        <body>
            <canvas id="artifactChart"></canvas>
            <script>
                new Chart(document.getElementById('artifactChart'), {{
                    type: 'bar',
                    data: {{
                        labels: {json.dumps(labels)},
                        datasets: [{{
                            label: 'Query Count',
                            data: {json.dumps(counts)},
                            backgroundColor: '#06b6d4'
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{
                            title: {{
                                display: true,
                                text: 'Top 5 Queried Artifact Types',
                                color: '#f97316',
                                font: {{ size: 16 }}
                            }},
                            legend: {{ labels: {{ color: '#e8edf5' }} }}
                        }},
                        scales: {{
                            y: {{ 
                                ticks: {{ color: '#8899aa' }},
                                grid: {{ color: '#1e2a3a' }}
                            }},
                            x: {{ 
                                ticks: {{ color: '#8899aa' }},
                                grid: {{ color: '#1e2a3a' }}
                            }}
                        }}
                    }}
                }});
            </script>
        </body>
        </html>
        """
        
        view = QWebEngineView()
        view.setHtml(chart_html)
        view.setMinimumHeight(300)
        view.setMaximumHeight(300)
        return view
    
    def get_chart_data(self, chart_type: str) -> Dict[str, Any]:
        """
        Get data for a specific chart type.
        
        Args:
            chart_type: One of "activity", "evidence_ratio", "artifact_types"
            
        Returns:
            Chart data dictionary with Chart.js format
            
        Raises:
            ValueError: If chart_type is invalid
            
        """
        if chart_type == "activity":
            # Group entries by date
            date_counts = {}
            for entry in self.timeline_entries:
                timestamp = entry.get("timestamp", "")
                if timestamp:
                    try:
                        date = timestamp.split("T")[0]
                    except:
                        date = "Unknown"
                else:
                    date = "Unknown"
                date_counts[date] = date_counts.get(date, 0) + 1
            
            sorted_dates = sorted([d for d in date_counts.keys() if d != "Unknown"])
            if "Unknown" in date_counts:
                sorted_dates.append("Unknown")
            counts = [date_counts[d] for d in sorted_dates]
            
            return {
                "chart_type": "bar",
                "title": "Investigation Activity Over Time",
                "labels": sorted_dates,
                "datasets": [{
                    "label": "Timeline Entries",
                    "data": counts,
                    "backgroundColor": "#f97316"
                }]
            }
        
        elif chart_type == "evidence_ratio":
            evidence_found = sum(1 for entry in self.timeline_entries if entry.get("evidence_found"))
            no_evidence = len(self.timeline_entries) - evidence_found
            
            return {
                "chart_type": "pie",
                "title": "Evidence Found Ratio",
                "labels": ["Evidence Found", "No Evidence"],
                "datasets": [{
                    "label": "Queries",
                    "data": [evidence_found, no_evidence],
                    "backgroundColor": ["#10b981", "#6b7280"]
                }]
            }
        
        elif chart_type == "artifact_types":
            # Extract artifact types from queries
            artifact_keywords = [
                "prefetch", "mft", "registry", "usn", "browser", 
                "amcache", "shellbags", "lnk", "jumplists", "timeline"
            ]
            
            artifact_counts = Counter()
            for entry in self.timeline_entries:
                query = entry.get("query", "").lower()
                for keyword in artifact_keywords:
                    if keyword in query:
                        artifact_counts[keyword] += 1
            
            # Get top 5
            top_artifacts = artifact_counts.most_common(5)
            if not top_artifacts:
                labels = ["No Data"]
                counts = [0]
            else:
                labels = [artifact.capitalize() for artifact, _ in top_artifacts]
                counts = [count for _, count in top_artifacts]
            
            return {
                "chart_type": "bar",
                "title": "Top 5 Queried Artifact Types",
                "labels": labels,
                "datasets": [{
                    "label": "Query Count",
                    "data": counts,
                    "backgroundColor": "#06b6d4"
                }]
            }
        
        else:
            raise ValueError(f"Invalid chart_type: {chart_type}. Must be one of: activity, evidence_ratio, artifact_types")
    
    def _on_export_summary_clicked(self):
        """
        Handle export summary button click.
        
        Opens file dialog and exports case summary to HTML or PDF format.
        
        """
        try:
            file_path, selected_filter = QFileDialog.getSaveFileName(
                self,
                "Export Case Summary",
                "",
                "HTML Report (*.html);;PDF Report (*.pdf)"
            )
            
            # Handle user cancellation
            if not file_path:
                return
            
            # Export based on selected format
            if selected_filter == "HTML Report (*.html)":
                if not file_path.endswith('.html'):
                    file_path += '.html'
                self._export_html(file_path)
            elif selected_filter == "PDF Report (*.pdf)":
                if not file_path.endswith('.pdf'):
                    file_path += '.pdf'
                self._export_pdf(file_path)
            
            # Show success message
            QMessageBox.information(
                self,
                "Export Successful",
                f"Case summary exported to:\n{file_path}"
            )
            
        except PermissionError:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Permission denied writing to:\n{file_path}\n\n"
                "Please check file permissions or choose a different location."
            )
        except ImportError as e:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Missing required library:\n{str(e)}\n\n"
                "For PDF export, install weasyprint:\n"
                "pip install weasyprint"
            )
        except Exception as e:
            logger.error(f"Export error: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Error exporting summary:\n{str(e)}\n\n"
                "Check the logs for more details."
            )
    
    def _generate_summary_html(self) -> str:
        """
        Generate HTML content for case summary export.
        
        Includes timeline entries, report findings, and charts in a styled format.
        
        Returns:
            Complete HTML document as string
            
        """
        # Generate timeline table HTML
        timeline_rows = ""
        for entry in self.timeline_entries:
            timestamp = self._format_timestamp(entry.get("timestamp", ""))
            query = entry.get("query", "")
            response = entry.get("response_summary", "")
            evidence = "✓ Yes" if entry.get("evidence_found") else "✗ No"
            evidence_color = "#10B981" if entry.get("evidence_found") else "#6B7280"
            next_steps = entry.get("suggested_next_steps", "—")
            
            timeline_rows += f"""
            <tr>
                <td>{timestamp}</td>
                <td>{query}</td>
                <td>{response}</td>
                <td style="color: {evidence_color}; font-weight: bold; text-align: center;">{evidence}</td>
                <td>{next_steps}</td>
            </tr>
            """
        
        # Generate report findings table HTML
        findings_rows = ""
        for block in self.report_blocks:
            block_type = block.block_type.capitalize()
            title_caption = ""
            if hasattr(block, 'title') and block.title:
                title_caption = block.title
            elif hasattr(block, 'caption') and block.caption:
                title_caption = block.caption
            else:
                title_caption = f"{block_type} Block"
            
            timestamp = self._format_timestamp(block.metadata.get("timestamp", ""))
            source = block.metadata.get("source", "Unknown")
            
            findings_rows += f"""
            <tr>
                <td>{block_type}</td>
                <td>{title_caption}</td>
                <td>{timestamp}</td>
                <td>{source}</td>
            </tr>
            """
        
        # Get chart data
        activity_data = self.get_chart_data("activity") if len(self.timeline_entries) >= 3 else None
        evidence_data = self.get_chart_data("evidence_ratio") if len(self.timeline_entries) >= 3 else None
        artifact_data = self.get_chart_data("artifact_types") if len(self.timeline_entries) >= 3 else None
        
        # Generate charts HTML
        charts_html = ""
        if activity_data:
            charts_html += f"""
            <div class="chart-container">
                <canvas id="activityChart"></canvas>
            </div>
            <script>
                new Chart(document.getElementById('activityChart'), {{
                    type: '{activity_data['chart_type']}',
                    data: {{
                        labels: {json.dumps(activity_data['labels'])},
                        datasets: {json.dumps(activity_data['datasets'])}
                    }},
                    options: {{
                        responsive: true,
                        plugins: {{
                            title: {{
                                display: true,
                                text: '{activity_data['title']}',
                                color: '#f97316',
                                font: {{ size: 16 }}
                            }},
                            legend: {{ labels: {{ color: '#e8edf5' }} }}
                        }},
                        scales: {{
                            y: {{ ticks: {{ color: '#8899aa' }}, grid: {{ color: '#1e2a3a' }} }},
                            x: {{ ticks: {{ color: '#8899aa' }}, grid: {{ color: '#1e2a3a' }} }}
                        }}
                    }}
                }});
            </script>
            """
        
        if evidence_data:
            charts_html += f"""
            <div class="chart-container">
                <canvas id="evidenceChart"></canvas>
            </div>
            <script>
                new Chart(document.getElementById('evidenceChart'), {{
                    type: '{evidence_data['chart_type']}',
                    data: {{
                        labels: {json.dumps(evidence_data['labels'])},
                        datasets: {json.dumps(evidence_data['datasets'])}
                    }},
                    options: {{
                        responsive: true,
                        plugins: {{
                            title: {{
                                display: true,
                                text: '{evidence_data['title']}',
                                color: '#f97316',
                                font: {{ size: 16 }}
                            }},
                            legend: {{ labels: {{ color: '#e8edf5' }}, position: 'right' }}
                        }}
                    }}
                }});
            </script>
            """
        
        if artifact_data:
            charts_html += f"""
            <div class="chart-container">
                <canvas id="artifactChart"></canvas>
            </div>
            <script>
                new Chart(document.getElementById('artifactChart'), {{
                    type: '{artifact_data['chart_type']}',
                    data: {{
                        labels: {json.dumps(artifact_data['labels'])},
                        datasets: {json.dumps(artifact_data['datasets'])}
                    }},
                    options: {{
                        responsive: true,
                        plugins: {{
                            title: {{
                                display: true,
                                text: '{artifact_data['title']}',
                                color: '#f97316',
                                font: {{ size: 16 }}
                            }},
                            legend: {{ labels: {{ color: '#e8edf5' }} }}
                        }},
                        scales: {{
                            y: {{ ticks: {{ color: '#8899aa' }}, grid: {{ color: '#1e2a3a' }} }},
                            x: {{ ticks: {{ color: '#8899aa' }}, grid: {{ color: '#1e2a3a' }} }}
                        }}
                    }}
                }});
            </script>
            """
        
        # Generate complete HTML document
        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Case Summary Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            background: #0B1220;
            color: #E5E7EB;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            padding: 40px;
            line-height: 1.6;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        
        h1 {{
            color: #00FFFF;
            font-size: 32pt;
            margin-bottom: 10px;
            text-align: center;
        }}
        
        .subtitle {{
            color: #9CA3AF;
            font-size: 14pt;
            text-align: center;
            margin-bottom: 40px;
        }}
        
        .toc {{
            background: #1E293B;
            border: 2px solid #334155;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 40px;
        }}
        
        .toc h2 {{
            color: #00FFFF;
            font-size: 18pt;
            margin-bottom: 15px;
        }}
        
        .toc ul {{
            list-style: none;
            padding-left: 0;
        }}
        
        .toc li {{
            margin: 8px 0;
        }}
        
        .toc a {{
            color: #06b6d4;
            text-decoration: none;
            font-size: 12pt;
        }}
        
        .toc a:hover {{
            color: #00FFFF;
            text-decoration: underline;
        }}
        
        .section {{
            margin-bottom: 50px;
            page-break-inside: avoid;
        }}
        
        .section h2 {{
            color: #00FFFF;
            font-size: 24pt;
            margin-bottom: 20px;
            border-bottom: 2px solid #334155;
            padding-bottom: 10px;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            background: #1E293B;
            border-radius: 8px;
            overflow: hidden;
            margin-bottom: 20px;
        }}
        
        th {{
            background: #334155;
            color: #00FFFF;
            padding: 12px;
            text-align: left;
            font-weight: bold;
            font-size: 11pt;
        }}
        
        td {{
            padding: 12px;
            border-bottom: 1px solid #334155;
            font-size: 10pt;
        }}
        
        tr:last-child td {{
            border-bottom: none;
        }}
        
        tr:nth-child(even) {{
            background: #0F172A;
        }}
        
        .chart-container {{
            background: #1E293B;
            border: 2px solid #334155;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 30px;
            height: 400px;
        }}
        
        .stats {{
            display: flex;
            justify-content: space-around;
            background: #1E293B;
            border: 2px solid #334155;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
        }}
        
        .stat-item {{
            text-align: center;
        }}
        
        .stat-label {{
            color: #9CA3AF;
            font-size: 10pt;
            margin-bottom: 5px;
        }}
        
        .stat-value {{
            color: #00FFFF;
            font-size: 24pt;
            font-weight: bold;
        }}
        
        .footer {{
            text-align: center;
            color: #6B7280;
            font-size: 9pt;
            margin-top: 50px;
            padding-top: 20px;
            border-top: 1px solid #334155;
        }}
        
        @media print {{
            body {{
                background: white;
                color: black;
            }}
            
            .section {{
                page-break-inside: avoid;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Case Summary Report</h1>
        <div class="subtitle">
            Generated on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        </div>
        
        <!-- Table of Contents -->
        <div class="toc">
            <h2>Table of Contents</h2>
            <ul>
                <li><a href="#timeline">Investigation Timeline</a></li>
                <li><a href="#findings">Report Findings</a></li>
                <li><a href="#charts">Analysis Charts</a></li>
            </ul>
        </div>
        
        <!-- Investigation Timeline Section -->
        <div class="section" id="timeline">
            <h2>Investigation Timeline</h2>
            <p style="color: #9CA3AF; margin-bottom: 15px;">
                Total entries: {len(self.timeline_entries)}
            </p>
            <table>
                <thead>
                    <tr>
                        <th>Timestamp</th>
                        <th>Query</th>
                        <th>Response Summary</th>
                        <th>Evidence</th>
                        <th>Next Steps</th>
                    </tr>
                </thead>
                <tbody>
                    {timeline_rows}
                </tbody>
            </table>
        </div>
        
        <!-- Report Findings Section -->
        <div class="section" id="findings">
            <h2>Report Findings</h2>
            
            <div class="stats">
                <div class="stat-item">
                    <div class="stat-label">Total Blocks</div>
                    <div class="stat-value">{len(self.report_blocks)}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Text Blocks</div>
                    <div class="stat-value">{len([b for b in self.report_blocks if b.block_type == "text"])}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Table Blocks</div>
                    <div class="stat-value">{len([b for b in self.report_blocks if b.block_type == "table"])}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Image Blocks</div>
                    <div class="stat-value">{len([b for b in self.report_blocks if b.block_type == "image"])}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Chart Blocks</div>
                    <div class="stat-value">{len([b for b in self.report_blocks if b.block_type == "chart"])}</div>
                </div>
            </div>
            
            <table>
                <thead>
                    <tr>
                        <th>Type</th>
                        <th>Title/Caption</th>
                        <th>Timestamp</th>
                        <th>Source Report</th>
                    </tr>
                </thead>
                <tbody>
                    {findings_rows}
                </tbody>
            </table>
        </div>
        
        <!-- Charts Section -->
        <div class="section" id="charts">
            <h2>Analysis Charts</h2>
            {charts_html if charts_html else '<p style="color: #9CA3AF;">Insufficient data for visualization (minimum 3 entries required)</p>'}
        </div>
        
        <div class="footer">
            EYE AI Forensic Assistant - Case Summary Report
        </div>
    </div>
</body>
</html>
        """
        
        return html
    
    def _export_html(self, file_path: str):
        """
        Export case summary as HTML file.
        
        Args:
            file_path: Output file path
            
        Raises:
            IOError: If file cannot be written
            PermissionError: If file permissions are insufficient
            
        """
        try:
            html_content = self._generate_summary_html()
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            logger.info(f"Exported case summary to HTML: {file_path}")
        except PermissionError:
            logger.error(f"Permission denied writing to: {file_path}")
            raise
        except IOError as e:
            logger.error(f"IO error writing to {file_path}: {e}")
            raise
    
    def _export_pdf(self, file_path: str):
        """
        Export case summary as PDF file using weasyprint.
        
        Args:
            file_path: Output file path
            
        Raises:
            ImportError: If weasyprint is not installed
            IOError: If file cannot be written
            PermissionError: If file permissions are insufficient
            
        """
        try:
            from weasyprint import HTML
        except ImportError:
            logger.error("weasyprint not installed")
            raise ImportError(
                "weasyprint is required for PDF export. "
                "Install with: pip install weasyprint"
            )
        
        try:
            html_content = self._generate_summary_html()
            HTML(string=html_content).write_pdf(file_path)
            logger.info(f"Exported case summary to PDF: {file_path}")
        except PermissionError:
            logger.error(f"Permission denied writing to: {file_path}")
            raise
        except IOError as e:
            logger.error(f"IO error writing to {file_path}: {e}")
            raise
