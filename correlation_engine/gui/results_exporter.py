"""
Results Exporter

Export correlation results with semantic mapping and scoring metadata.
Supports multiple formats and includes comprehensive metadata about integration features.
"""

import json
import csv
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
import zipfile
import tempfile

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QCheckBox, QComboBox, QLineEdit, QPushButton, QLabel,
    QFileDialog, QMessageBox, QProgressDialog, QTextEdit,
    QTabWidget, QWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont

from ..engine.correlation_result import CorrelationResult, CorrelationMatch


class ExportWorker(QThread):
    """Worker thread for exporting results to avoid UI blocking."""
    
    progress_updated = pyqtSignal(int, str)  # progress, status
    export_completed = pyqtSignal(str, bool, str)  # filepath, success, message
    
    def __init__(self, export_config: Dict[str, Any]):
        """
        Initialize export worker.
        
        Args:
            export_config: Export configuration dictionary
        """
        super().__init__()
        self.export_config = export_config
    
    def run(self):
        """Run the export process."""
        try:
            exporter = ResultsExporter()
            
            # Extract configuration
            tab_states = self.export_config['tab_states']
            output_path = self.export_config['output_path']
            export_format = self.export_config['format']
            options = self.export_config['options']
            
            # Update progress
            self.progress_updated.emit(10, "Preparing export data...")
            
            # Perform export based on format
            if export_format == 'json':
                success, message = exporter.export_to_json(tab_states, output_path, options)
            elif export_format == 'csv':
                success, message = exporter.export_to_csv(tab_states, output_path, options)
            elif export_format == 'xml':
                success, message = exporter.export_to_xml(tab_states, output_path, options)
            elif export_format == 'archive':
                success, message = exporter.export_to_archive(tab_states, output_path, options)
            else:
                success, message = False, f"Unsupported export format: {export_format}"
            
            self.progress_updated.emit(100, "Export completed")
            self.export_completed.emit(output_path, success, message)
            
        except Exception as e:
            self.export_completed.emit("", False, f"Export failed: {str(e)}")


class ExportOptionsDialog(QDialog):
    """Dialog for configuring export options."""
    
    def __init__(self, tab_states: Dict[str, Any], parent=None):
        """
        Initialize export options dialog.
        
        Args:
            tab_states: Dictionary of tab states to export
            parent: Parent widget
        """
        super().__init__(parent)
        self.tab_states = tab_states
        self.export_config = {}
        
        self.setWindowTitle("Export Results with Metadata")
        self.setMinimumSize(600, 500)
        
        self._init_ui()
    
    def _init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout(self)
        
        # Create tabs for different option categories
        tab_widget = QTabWidget()
        
        # General options tab
        general_tab = self._create_general_options_tab()
        tab_widget.addTab(general_tab, "General")
        
        # Content options tab
        content_tab = self._create_content_options_tab()
        tab_widget.addTab(content_tab, "Content")
        
        # Metadata options tab
        metadata_tab = self._create_metadata_options_tab()
        tab_widget.addTab(metadata_tab, "Metadata")
        
        # Preview tab
        preview_tab = self._create_preview_tab()
        tab_widget.addTab(preview_tab, "Preview")
        
        layout.addWidget(tab_widget)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.export_button = QPushButton("Export")
        self.export_button.clicked.connect(self.accept)
        button_layout.addWidget(self.export_button)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
        
        # Update preview when options change
        self._connect_option_signals()
    
    def _create_general_options_tab(self) -> QWidget:
        """Create general export options tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Export format
        format_group = QGroupBox("Export Format")
        format_layout = QFormLayout()
        
        self.format_combo = QComboBox()
        self.format_combo.addItems([
            "JSON (Structured data with full metadata)",
            "CSV (Tabular data with basic metadata)",
            "XML (Structured markup with metadata)",
            "Archive (ZIP with multiple formats)"
        ])
        self.format_combo.setCurrentIndex(0)
        format_layout.addRow("Format:", self.format_combo)
        
        format_group.setLayout(format_layout)
        layout.addWidget(format_group)
        
        # Output options
        output_group = QGroupBox("Output Options")
        output_layout = QFormLayout()
        
        # Output path
        path_layout = QHBoxLayout()
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("Select output file path...")
        path_layout.addWidget(self.output_path_edit)
        
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._browse_output_path)
        path_layout.addWidget(browse_button)
        
        output_layout.addRow("Output Path:", path_layout)
        
        # Compression
        self.compress_checkbox = QCheckBox("Compress output (for large datasets)")
        self.compress_checkbox.setChecked(True)
        output_layout.addRow("Compression:", self.compress_checkbox)
        
        output_group.setLayout(output_layout)
        layout.addWidget(output_group)
        
        # Tab selection
        tabs_group = QGroupBox("Tab Selection")
        tabs_layout = QVBoxLayout()
        
        self.tab_checkboxes = {}
        for tab_id, tab_state in self.tab_states.items():
            checkbox = QCheckBox(f"{tab_state['wing_name']} ({len(tab_state.get('matches', []))} matches)")
            checkbox.setChecked(True)
            self.tab_checkboxes[tab_id] = checkbox
            tabs_layout.addWidget(checkbox)
        
        tabs_group.setLayout(tabs_layout)
        layout.addWidget(tabs_group)
        
        layout.addStretch()
        
        return widget
    
    def _create_content_options_tab(self) -> QWidget:
        """Create content export options tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Match data options
        match_group = QGroupBox("Match Data")
        match_layout = QVBoxLayout()
        
        self.include_feather_records = QCheckBox("Include feather records")
        self.include_feather_records.setChecked(True)
        self.include_feather_records.setToolTip("Include detailed feather record data for each match")
        match_layout.addWidget(self.include_feather_records)
        
        self.include_raw_values = QCheckBox("Include raw field values")
        self.include_raw_values.setChecked(True)
        self.include_raw_values.setToolTip("Include original raw values alongside semantic values")
        match_layout.addWidget(self.include_raw_values)
        
        self.include_timestamps = QCheckBox("Include detailed timestamps")
        self.include_timestamps.setChecked(True)
        self.include_timestamps.setToolTip("Include creation and modification timestamps")
        match_layout.addWidget(self.include_timestamps)
        
        match_group.setLayout(match_layout)
        layout.addWidget(match_group)
        
        # Filtering options
        filter_group = QGroupBox("Data Filtering")
        filter_layout = QVBoxLayout()
        
        self.include_current_filters = QCheckBox("Apply current tab filters")
        self.include_current_filters.setChecked(False)
        self.include_current_filters.setToolTip("Export only matches that pass current filter criteria")
        filter_layout.addWidget(self.include_current_filters)
        
        # Score threshold
        score_layout = QHBoxLayout()
        self.score_threshold_checkbox = QCheckBox("Minimum score threshold:")
        self.score_threshold_edit = QLineEdit("0.0")
        self.score_threshold_edit.setMaximumWidth(60)
        self.score_threshold_edit.setEnabled(False)
        
        self.score_threshold_checkbox.toggled.connect(self.score_threshold_edit.setEnabled)
        
        score_layout.addWidget(self.score_threshold_checkbox)
        score_layout.addWidget(self.score_threshold_edit)
        score_layout.addStretch()
        
        filter_layout.addLayout(score_layout)
        
        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)
        
        layout.addStretch()
        
        return widget
    
    def _create_metadata_options_tab(self) -> QWidget:
        """Create metadata export options tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Semantic mapping metadata
        semantic_group = QGroupBox("Semantic Mapping Metadata")
        semantic_layout = QVBoxLayout()
        
        self.include_semantic_mappings = QCheckBox("Include semantic mapping configuration")
        self.include_semantic_mappings.setChecked(True)
        self.include_semantic_mappings.setToolTip("Include semantic mapping rules and applied mappings")
        semantic_layout.addWidget(self.include_semantic_mappings)
        
        self.include_semantic_statistics = QCheckBox("Include semantic mapping statistics")
        self.include_semantic_statistics.setChecked(True)
        self.include_semantic_statistics.setToolTip("Include coverage statistics and mapping effectiveness")
        semantic_layout.addWidget(self.include_semantic_statistics)
        
        self.include_unmapped_fields = QCheckBox("Include unmapped field information")
        self.include_unmapped_fields.setChecked(False)
        self.include_unmapped_fields.setToolTip("Include information about fields without semantic mappings")
        semantic_layout.addWidget(self.include_unmapped_fields)
        
        semantic_group.setLayout(semantic_layout)
        layout.addWidget(semantic_group)
        
        # Scoring metadata
        scoring_group = QGroupBox("Scoring Metadata")
        scoring_layout = QVBoxLayout()
        
        self.include_scoring_config = QCheckBox("Include scoring configuration")
        self.include_scoring_config.setChecked(True)
        self.include_scoring_config.setToolTip("Include weighted scoring configuration and weights")
        scoring_layout.addWidget(self.include_scoring_config)
        
        self.include_scoring_breakdown = QCheckBox("Include detailed scoring breakdown")
        self.include_scoring_breakdown.setChecked(True)
        self.include_scoring_breakdown.setToolTip("Include per-feather scoring contributions")
        scoring_layout.addWidget(self.include_scoring_breakdown)
        
        self.include_score_interpretation = QCheckBox("Include score interpretation labels")
        self.include_score_interpretation.setChecked(True)
        self.include_score_interpretation.setToolTip("Include human-readable score interpretations")
        scoring_layout.addWidget(self.include_score_interpretation)
        
        scoring_group.setLayout(scoring_layout)
        layout.addWidget(scoring_group)
        
        # System metadata
        system_group = QGroupBox("System Metadata")
        system_layout = QVBoxLayout()
        
        self.include_export_metadata = QCheckBox("Include export metadata")
        self.include_export_metadata.setChecked(True)
        self.include_export_metadata.setToolTip("Include export timestamp, version, and configuration")
        system_layout.addWidget(self.include_export_metadata)
        
        self.include_engine_metadata = QCheckBox("Include correlation engine metadata")
        self.include_engine_metadata.setChecked(True)
        self.include_engine_metadata.setToolTip("Include engine type, version, and execution parameters")
        system_layout.addWidget(self.include_engine_metadata)
        
        self.include_case_metadata = QCheckBox("Include case metadata")
        self.include_case_metadata.setChecked(False)
        self.include_case_metadata.setToolTip("Include case information and investigation context")
        system_layout.addWidget(self.include_case_metadata)
        
        system_group.setLayout(system_layout)
        layout.addWidget(system_group)
        
        layout.addStretch()
        
        return widget
    
    def _create_preview_tab(self) -> QWidget:
        """Create export preview tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Preview controls
        controls_layout = QHBoxLayout()
        
        preview_label = QLabel("Export Preview:")
        preview_label.setFont(QFont("Arial", 10, QFont.Bold))
        controls_layout.addWidget(preview_label)
        
        controls_layout.addStretch()
        
        refresh_button = QPushButton("Refresh Preview")
        refresh_button.clicked.connect(self._update_preview)
        controls_layout.addWidget(refresh_button)
        
        layout.addLayout(controls_layout)
        
        # Preview content
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setFont(QFont("Consolas", 9))
        layout.addWidget(self.preview_text)
        
        # Statistics
        stats_layout = QHBoxLayout()
        
        self.stats_label = QLabel("Statistics will appear here...")
        self.stats_label.setStyleSheet("color: #666; font-style: italic;")
        stats_layout.addWidget(self.stats_label)
        
        stats_layout.addStretch()
        
        layout.addLayout(stats_layout)
        
        return widget
    
    def _connect_option_signals(self):
        """Connect option change signals to preview update."""
        self.format_combo.currentTextChanged.connect(self._update_preview)
        
        for checkbox in self.tab_checkboxes.values():
            checkbox.toggled.connect(self._update_preview)
        
        self.include_feather_records.toggled.connect(self._update_preview)
        self.include_semantic_mappings.toggled.connect(self._update_preview)
        self.include_scoring_config.toggled.connect(self._update_preview)
        
        self._update_preview()
    
    def _browse_output_path(self):
        """Browse for output file path."""
        format_text = self.format_combo.currentText()
        
        if "JSON" in format_text:
            file_filter = "JSON Files (*.json);;All Files (*)"
            default_ext = ".json"
        elif "CSV" in format_text:
            file_filter = "CSV Files (*.csv);;All Files (*)"
            default_ext = ".csv"
        elif "XML" in format_text:
            file_filter = "XML Files (*.xml);;All Files (*)"
            default_ext = ".xml"
        elif "Archive" in format_text:
            file_filter = "ZIP Archives (*.zip);;All Files (*)"
            default_ext = ".zip"
        else:
            file_filter = "All Files (*)"
            default_ext = ""
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"correlation_results_{timestamp}{default_ext}"
        
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Export Results",
            default_filename,
            file_filter
        )
        
        if filepath:
            self.output_path_edit.setText(filepath)
    
    def _update_preview(self):
        """Update the export preview."""
        try:
            selected_tabs = []
            for tab_id, checkbox in self.tab_checkboxes.items():
                if checkbox.isChecked():
                    selected_tabs.append(tab_id)
            
            if not selected_tabs:
                self.preview_text.setPlainText("No tabs selected for export.")
                self.stats_label.setText("No data to export.")
                return
            
            format_text = self.format_combo.currentText()
            
            if "JSON" in format_text:
                preview = self._generate_json_preview(selected_tabs)
            elif "CSV" in format_text:
                preview = self._generate_csv_preview(selected_tabs)
            elif "XML" in format_text:
                preview = self._generate_xml_preview(selected_tabs)
            elif "Archive" in format_text:
                preview = self._generate_archive_preview(selected_tabs)
            else:
                preview = "Preview not available for this format."
            
            self.preview_text.setPlainText(preview)
            
            total_matches = sum(len(self.tab_states[tab_id].get('matches', [])) for tab_id in selected_tabs)
            total_tabs = len(selected_tabs)
            
            self.stats_label.setText(f"Exporting {total_matches:,} matches from {total_tabs} tab(s)")
            
        except Exception as e:
            self.preview_text.setPlainText(f"Preview generation error: {str(e)}")
            self.stats_label.setText("Error generating preview")
    
    def _generate_json_preview(self, selected_tabs: List[str]) -> str:
        """Generate JSON export preview."""
        preview_data = {
            "export_metadata": {
                "timestamp": datetime.now().isoformat(),
                "format": "json",
                "version": "1.0",
                "tabs_exported": len(selected_tabs)
            }
        }
        
        if self.include_semantic_mappings.isChecked():
            preview_data["semantic_mappings"] = {
                "enabled": True,
                "mappings_count": "...",
                "coverage_statistics": "..."
            }
        
        if self.include_scoring_config.isChecked():
            preview_data["scoring_configuration"] = {
                "enabled": True,
                "scoring_type": "weighted",
                "interpretation_thresholds": "..."
            }
        
        preview_data["tabs"] = {}
        for tab_id in selected_tabs[:2]:
            tab_state = self.tab_states[tab_id]
            preview_data["tabs"][tab_id] = {
                "wing_name": tab_state.get('wing_name', 'Unknown'),
                "matches_count": len(tab_state.get('matches', [])),
                "matches": "[Match data would appear here...]"
            }
        
        if len(selected_tabs) > 2:
            preview_data["tabs"]["..."] = f"({len(selected_tabs) - 2} more tabs)"
        
        return json.dumps(preview_data, indent=2)[:1000] + "\n\n... (truncated for preview)"
    
    def _generate_csv_preview(self, selected_tabs: List[str]) -> str:
        """Generate CSV export preview."""
        headers = ["Tab_ID", "Wing_Name", "Match_ID", "Timestamp", "Score"]
        
        if self.include_semantic_mappings.isChecked():
            headers.extend(["Semantic_Fields_Mapped", "Semantic_Coverage"])
        
        if self.include_scoring_config.isChecked():
            headers.extend(["Weighted_Score", "Score_Interpretation"])
        
        preview_lines = [",".join(headers)]
        
        for tab_id in selected_tabs[:2]:
            tab_state = self.tab_states[tab_id]
            wing_name = tab_state.get('wing_name', 'Unknown')
            
            for i in range(min(3, len(tab_state.get('matches', [])))):
                row = [
                    tab_id[:8],
                    wing_name,
                    f"match_{i+1}",
                    "2024-01-03T10:30:00",
                    "0.75"
                ]
                
                if self.include_semantic_mappings.isChecked():
                    row.extend(["5", "83.3%"])
                
                if self.include_scoring_config.isChecked():
                    row.extend(["0.82", "Probable Match"])
                
                preview_lines.append(",".join(row))
        
        if len(selected_tabs) > 2:
            preview_lines.append("... (more tabs and matches)")
        
        return "\n".join(preview_lines)
    
    def _generate_xml_preview(self, selected_tabs: List[str]) -> str:
        """Generate XML export preview."""
        xml_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<correlation_results>',
            '  <export_metadata>',
            f'    <timestamp>{datetime.now().isoformat()}</timestamp>',
            '    <format>xml</format>',
            f'    <tabs_exported>{len(selected_tabs)}</tabs_exported>',
            '  </export_metadata>'
        ]
        
        if self.include_semantic_mappings.isChecked():
            xml_lines.extend([
                '  <semantic_mappings>',
                '    <enabled>true</enabled>',
                '    <mappings_count>...</mappings_count>',
                '  </semantic_mappings>'
            ])
        
        xml_lines.extend([
            '  <tabs>',
            '    <!-- Tab data would appear here -->',
            '    <tab id="..." wing_name="..." matches_count="...">',
            '      <matches>',
            '        <!-- Match data with semantic and scoring info -->',
            '      </matches>',
            '    </tab>',
            '  </tabs>',
            '</correlation_results>'
        ])
        
        return "\n".join(xml_lines)
    
    def _generate_archive_preview(self, selected_tabs: List[str]) -> str:
        """Generate archive export preview."""
        preview_lines = [
            "Archive Contents:",
            "",
            "📁 correlation_results.zip",
            "  📄 export_metadata.json",
            "  📄 semantic_mappings.json",
            "  📄 scoring_configuration.json",
            "  📁 tabs/",
        ]
        
        for tab_id in selected_tabs[:3]:
            tab_state = self.tab_states[tab_id]
            wing_name = tab_state.get('wing_name', 'Unknown')
            preview_lines.append(f"    📄 {wing_name}_{tab_id[:8]}.json")
        
        if len(selected_tabs) > 3:
            preview_lines.append(f"    📄 ... ({len(selected_tabs) - 3} more tab files)")
        
        preview_lines.extend([
            "  📄 summary_statistics.json",
            "",
            "Each tab file contains:",
            "- Match data with feather records",
            "- Applied semantic mappings",
            "- Scoring breakdown and interpretation",
            "- Tab-specific metadata and state"
        ])
        
        return "\n".join(preview_lines)
    
    def get_export_config(self) -> Dict[str, Any]:
        """Get the export configuration."""
        selected_tabs = {}
        for tab_id, checkbox in self.tab_checkboxes.items():
            if checkbox.isChecked():
                selected_tabs[tab_id] = self.tab_states[tab_id]
        
        format_text = self.format_combo.currentText()
        if "JSON" in format_text:
            export_format = "json"
        elif "CSV" in format_text:
            export_format = "csv"
        elif "XML" in format_text:
            export_format = "xml"
        elif "Archive" in format_text:
            export_format = "archive"
        else:
            export_format = "json"
        
        options = {
            'include_feather_records': self.include_feather_records.isChecked(),
            'include_raw_values': self.include_raw_values.isChecked(),
            'include_timestamps': self.include_timestamps.isChecked(),
            'include_current_filters': self.include_current_filters.isChecked(),
            'include_semantic_mappings': self.include_semantic_mappings.isChecked(),
            'include_semantic_statistics': self.include_semantic_statistics.isChecked(),
            'include_unmapped_fields': self.include_unmapped_fields.isChecked(),
            'include_scoring_config': self.include_scoring_config.isChecked(),
            'include_scoring_breakdown': self.include_scoring_breakdown.isChecked(),
            'include_score_interpretation': self.include_score_interpretation.isChecked(),
            'include_export_metadata': self.include_export_metadata.isChecked(),
            'include_engine_metadata': self.include_engine_metadata.isChecked(),
            'include_case_metadata': self.include_case_metadata.isChecked(),
            'compress': self.compress_checkbox.isChecked(),
            'score_threshold': float(self.score_threshold_edit.text()) if self.score_threshold_checkbox.isChecked() else None
        }
        
        return {
            'tab_states': selected_tabs,
            'output_path': self.output_path_edit.text(),
            'format': export_format,
            'options': options
        }


class ResultsExporter:
    """
    Results exporter with semantic mapping and scoring metadata support.
    
    Supports multiple export formats (JSON, CSV, XML, Archive) with comprehensive
    metadata about semantic mappings and weighted scoring.
    """
    
    def __init__(self):
        """Initialize the results exporter."""
        self.export_version = "1.0"
    
    def export_to_json(self, tab_states: Dict[str, Any], output_path: str, options: Dict[str, Any]) -> tuple[bool, str]:
        """
        Export results to JSON format with full metadata.
        
        Args:
            tab_states: Dictionary of tab states to export
            output_path: Output file path
            options: Export options
            
        Returns:
            Tuple of (success, message)
        """
        try:
            export_data = self._build_export_data(tab_states, options)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False, default=str)
            
            return True, f"Successfully exported to JSON: {output_path}"
            
        except Exception as e:
            return False, f"JSON export failed: {str(e)}"
    
    def export_to_csv(self, tab_states: Dict[str, Any], output_path: str, options: Dict[str, Any]) -> tuple[bool, str]:
        """
        Export results to CSV format with metadata columns.
        
        Args:
            tab_states: Dictionary of tab states to export
            output_path: Output file path
            options: Export options
            
        Returns:
            Tuple of (success, message)
        """
        try:
            headers = [
                'Tab_ID', 'Wing_Name', 'Match_ID', 'Timestamp', 'Score',
                'Feather_Count', 'Time_Spread_Seconds', 'Application', 'File_Path'
            ]
            
            if options.get('include_semantic_mappings', False):
                headers.extend([
                    'Semantic_Fields_Mapped', 'Semantic_Coverage_Percent',
                    'Semantic_Categories', 'Semantic_Confidence_Avg'
                ])
            
            if options.get('include_scoring_config', False):
                headers.extend([
                    'Weighted_Score', 'Score_Interpretation', 'Scoring_Breakdown',
                    'Matched_Feathers', 'Total_Feathers'
                ])
            
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                
                for tab_id, tab_state in tab_states.items():
                    wing_name = tab_state.get('wing_name', 'Unknown')
                    matches = tab_state.get('matches', [])
                    
                    for match in matches:
                        if options.get('score_threshold') is not None:
                            if match.get('match_score', 0) < options['score_threshold']:
                                continue
                        
                        row = [
                            tab_id,
                            wing_name,
                            match.get('match_id', ''),
                            match.get('timestamp', ''),
                            match.get('match_score', 0),
                            match.get('feather_count', 0),
                            match.get('time_spread_seconds', 0),
                            match.get('matched_application', ''),
                            match.get('matched_file_path', '')
                        ]
                        
                        if options.get('include_semantic_mappings', False):
                            semantic_info = self._extract_semantic_info(match, tab_state)
                            row.extend([
                                semantic_info.get('fields_mapped', 0),
                                semantic_info.get('coverage_percent', 0),
                                ';'.join(semantic_info.get('categories', [])),
                                semantic_info.get('avg_confidence', 0)
                            ])
                        
                        if options.get('include_scoring_config', False):
                            scoring_info = self._extract_scoring_info(match)
                            row.extend([
                                scoring_info.get('weighted_score', ''),
                                scoring_info.get('interpretation', ''),
                                scoring_info.get('breakdown_summary', ''),
                                scoring_info.get('matched_feathers', 0),
                                scoring_info.get('total_feathers', 0)
                            ])
                        
                        writer.writerow(row)
            
            return True, f"Successfully exported to CSV: {output_path}"
            
        except Exception as e:
            return False, f"CSV export failed: {str(e)}"
    
    def export_to_xml(self, tab_states: Dict[str, Any], output_path: str, options: Dict[str, Any]) -> tuple[bool, str]:
        """
        Export results to XML format with structured metadata.
        
        Args:
            tab_states: Dictionary of tab states to export
            output_path: Output file path
            options: Export options
            
        Returns:
            Tuple of (success, message)
        """
        try:
            root = ET.Element('correlation_results')
            
            if options.get('include_export_metadata', True):
                metadata_elem = ET.SubElement(root, 'export_metadata')
                ET.SubElement(metadata_elem, 'timestamp').text = datetime.now().isoformat()
                ET.SubElement(metadata_elem, 'version').text = self.export_version
                ET.SubElement(metadata_elem, 'format').text = 'xml'
                ET.SubElement(metadata_elem, 'tabs_exported').text = str(len(tab_states))
            
            if options.get('include_semantic_mappings', False):
                semantic_elem = ET.SubElement(root, 'semantic_mappings_metadata')
                ET.SubElement(semantic_elem, 'enabled').text = 'true'
            
            if options.get('include_scoring_config', False):
                scoring_elem = ET.SubElement(root, 'scoring_configuration_metadata')
                ET.SubElement(scoring_elem, 'enabled').text = 'true'
            
            tabs_elem = ET.SubElement(root, 'tabs')
            
            for tab_id, tab_state in tab_states.items():
                tab_elem = ET.SubElement(tabs_elem, 'tab')
                tab_elem.set('id', tab_id)
                tab_elem.set('wing_name', tab_state.get('wing_name', 'Unknown'))
                
                matches_elem = ET.SubElement(tab_elem, 'matches')
                matches = tab_state.get('matches', [])
                
                for match in matches:
                    if options.get('score_threshold') is not None:
                        if match.get('match_score', 0) < options['score_threshold']:
                            continue
                    
                    match_elem = ET.SubElement(matches_elem, 'match')
                    match_elem.set('id', match.get('match_id', ''))
                    
                    ET.SubElement(match_elem, 'timestamp').text = match.get('timestamp', '')
                    ET.SubElement(match_elem, 'score').text = str(match.get('match_score', 0))
                    ET.SubElement(match_elem, 'feather_count').text = str(match.get('feather_count', 0))
                    
                    if options.get('include_semantic_mappings', False):
                        semantic_elem = ET.SubElement(match_elem, 'semantic_information')
                        semantic_info = self._extract_semantic_info(match, tab_state)
                        
                        for key, value in semantic_info.items():
                            elem = ET.SubElement(semantic_elem, key)
                            elem.text = str(value)
                    
                    if options.get('include_scoring_config', False):
                        scoring_elem = ET.SubElement(match_elem, 'scoring_information')
                        scoring_info = self._extract_scoring_info(match)
                        
                        for key, value in scoring_info.items():
                            elem = ET.SubElement(scoring_elem, key)
                            elem.text = str(value)
            
            tree = ET.ElementTree(root)
            ET.indent(tree, space="  ", level=0)
            tree.write(output_path, encoding='utf-8', xml_declaration=True)
            
            return True, f"Successfully exported to XML: {output_path}"
            
        except Exception as e:
            return False, f"XML export failed: {str(e)}"
    
    def export_to_archive(self, tab_states: Dict[str, Any], output_path: str, options: Dict[str, Any]) -> tuple[bool, str]:
        """
        Export results to ZIP archive with multiple formats and comprehensive metadata.
        
        Args:
            tab_states: Dictionary of tab states to export
            output_path: Output file path
            options: Export options
            
        Returns:
            Tuple of (success, message)
        """
        try:
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_path = Path(temp_dir)
                    
                    json_path = temp_path / "correlation_results.json"
                    success, message = self.export_to_json(tab_states, str(json_path), options)
                    if success:
                        zipf.write(json_path, "correlation_results.json")
                    
                    csv_path = temp_path / "correlation_results.csv"
                    success, message = self.export_to_csv(tab_states, str(csv_path), options)
                    if success:
                        zipf.write(csv_path, "correlation_results.csv")
                    
                    if options.get('include_export_metadata', True):
                        metadata = {
                            'export_timestamp': datetime.now().isoformat(),
                            'export_version': self.export_version,
                            'tabs_exported': len(tab_states),
                            'export_options': options
                        }
                        
                        metadata_path = temp_path / "export_metadata.json"
                        with open(metadata_path, 'w') as f:
                            json.dump(metadata, f, indent=2)
                        zipf.write(metadata_path, "export_metadata.json")
                    
                    if options.get('include_semantic_mappings', False):
                        semantic_config = self._extract_semantic_configuration(tab_states)
                        
                        semantic_path = temp_path / "semantic_mappings.json"
                        with open(semantic_path, 'w') as f:
                            json.dump(semantic_config, f, indent=2)
                        zipf.write(semantic_path, "semantic_mappings.json")
                    
                    if options.get('include_scoring_config', False):
                        scoring_config = self._extract_scoring_configuration(tab_states)
                        
                        scoring_path = temp_path / "scoring_configuration.json"
                        with open(scoring_path, 'w') as f:
                            json.dump(scoring_config, f, indent=2)
                        zipf.write(scoring_path, "scoring_configuration.json")
                    
                    tabs_dir = temp_path / "tabs"
                    tabs_dir.mkdir()
                    
                    for tab_id, tab_state in tab_states.items():
                        wing_name = tab_state.get('wing_name', 'Unknown')
                        tab_filename = f"{wing_name}_{tab_id[:8]}.json"
                        
                        tab_data = {
                            'tab_id': tab_id,
                            'wing_name': wing_name,
                            'tab_state': tab_state,
                            'export_timestamp': datetime.now().isoformat()
                        }
                        
                        tab_path = tabs_dir / tab_filename
                        with open(tab_path, 'w') as f:
                            json.dump(tab_data, f, indent=2, default=str)
                        
                        zipf.write(tab_path, f"tabs/{tab_filename}")
                    
                    summary_stats = self._generate_summary_statistics(tab_states)
                    
                    summary_path = temp_path / "summary_statistics.json"
                    with open(summary_path, 'w') as f:
                        json.dump(summary_stats, f, indent=2)
                    zipf.write(summary_path, "summary_statistics.json")
            
            return True, f"Successfully exported to archive: {output_path}"
            
        except Exception as e:
            return False, f"Archive export failed: {str(e)}"
    
    def _build_export_data(self, tab_states: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, Any]:
        """Build comprehensive export data structure."""
        export_data = {}
        
        if options.get('include_export_metadata', True):
            export_data['export_metadata'] = {
                'timestamp': datetime.now().isoformat(),
                'version': self.export_version,
                'format': 'json',
                'tabs_exported': len(tab_states),
                'options_used': options
            }
        
        if options.get('include_semantic_mappings', False):
            export_data['semantic_mappings'] = self._extract_semantic_configuration(tab_states)
        
        if options.get('include_scoring_config', False):
            export_data['scoring_configuration'] = self._extract_scoring_configuration(tab_states)
        
        export_data['tabs'] = {}
        
        for tab_id, tab_state in tab_states.items():
            tab_data = {
                'wing_name': tab_state.get('wing_name', 'Unknown'),
                'matches': []
            }
            
            if options.get('include_export_metadata', True):
                tab_data['metadata'] = {
                    'created_timestamp': tab_state.get('created_timestamp'),
                    'last_accessed': tab_state.get('last_accessed'),
                    'filter_state': tab_state.get('filter_state', {}),
                    'semantic_mappings_count': len(tab_state.get('semantic_mappings', {})),
                    'scoring_configuration_present': bool(tab_state.get('scoring_configuration'))
                }
            
            matches = tab_state.get('matches', [])
            for match in matches:
                if options.get('score_threshold') is not None:
                    if match.get('match_score', 0) < options['score_threshold']:
                        continue
                
                match_data = {
                    'match_id': match.get('match_id', ''),
                    'timestamp': match.get('timestamp', ''),
                    'match_score': match.get('match_score', 0),
                    'feather_count': match.get('feather_count', 0),
                    'time_spread_seconds': match.get('time_spread_seconds', 0),
                    'matched_application': match.get('matched_application'),
                    'matched_file_path': match.get('matched_file_path')
                }
                
                if options.get('include_feather_records', True):
                    match_data['feather_records'] = match.get('feather_records', {})
                
                if options.get('include_semantic_mappings', False):
                    match_data['semantic_information'] = self._extract_semantic_info(match, tab_state)
                
                if options.get('include_scoring_config', False):
                    match_data['scoring_information'] = self._extract_scoring_info(match)
                
                tab_data['matches'].append(match_data)
            
            export_data['tabs'][tab_id] = tab_data
        
        export_data['summary_statistics'] = self._generate_summary_statistics(tab_states)
        
        return export_data
    
    def _extract_semantic_info(self, match: Dict[str, Any], tab_state: Dict[str, Any]) -> Dict[str, Any]:
        """Extract semantic mapping information for a match."""
        semantic_mappings = tab_state.get('semantic_mappings', {})
        
        if not semantic_mappings:
            return {
                'fields_mapped': 0,
                'coverage_percent': 0,
                'categories': [],
                'avg_confidence': 0
            }
        
        feather_records = match.get('feather_records', {})
        total_fields = 0
        mapped_fields = 0
        categories = set()
        confidences = []
        
        for feather_id, record in feather_records.items():
            if feather_id in semantic_mappings:
                feather_mappings = semantic_mappings[feather_id]
                
                for field_name, field_value in record.items():
                    if field_name.startswith('_'):
                        continue
                    
                    total_fields += 1
                    
                    if field_name in feather_mappings:
                        mapped_fields += 1
                        mapping_info = feather_mappings[field_name]
                        
                        category = mapping_info.get('category', 'unknown')
                        categories.add(category)
                        
                        confidence = mapping_info.get('confidence', 0.0)
                        confidences.append(confidence)
        
        coverage_percent = (mapped_fields / total_fields * 100) if total_fields > 0 else 0
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0
        
        return {
            'fields_mapped': mapped_fields,
            'total_fields': total_fields,
            'coverage_percent': round(coverage_percent, 1),
            'categories': list(categories),
            'avg_confidence': round(avg_confidence, 3)
        }
    
    def _extract_scoring_info(self, match: Dict[str, Any]) -> Dict[str, Any]:
        """Extract scoring information for a match."""
        weighted_score = match.get('weighted_score')
        
        if not weighted_score or not isinstance(weighted_score, dict):
            return {
                'weighted_score': None,
                'interpretation': None,
                'breakdown_summary': None,
                'matched_feathers': 0,
                'total_feathers': 0
            }
        
        breakdown = weighted_score.get('breakdown', {})
        matched_feathers = sum(1 for data in breakdown.values() if data.get('matched', False))
        total_feathers = len(breakdown)
        
        breakdown_summary = []
        for feather_id, data in breakdown.items():
            if data.get('matched', False):
                contribution = data.get('contribution', 0)
                breakdown_summary.append(f"{feather_id}:{contribution:.3f}")
        
        return {
            'weighted_score': weighted_score.get('score'),
            'interpretation': weighted_score.get('interpretation'),
            'breakdown_summary': ';'.join(breakdown_summary),
            'matched_feathers': matched_feathers,
            'total_feathers': total_feathers
        }
    
    def _extract_semantic_configuration(self, tab_states: Dict[str, Any]) -> Dict[str, Any]:
        """Extract semantic mapping configuration from tab states."""
        all_mappings = {}
        mapping_stats = {
            'total_mappings': 0,
            'categories': set(),
            'sources': set(),
            'avg_confidence': 0
        }
        
        confidences = []
        
        for tab_state in tab_states.values():
            semantic_mappings = tab_state.get('semantic_mappings', {})
            
            for feather_id, feather_mappings in semantic_mappings.items():
                if feather_id not in all_mappings:
                    all_mappings[feather_id] = {}
                
                for field_name, mapping_info in feather_mappings.items():
                    all_mappings[feather_id][field_name] = mapping_info
                    mapping_stats['total_mappings'] += 1
                    
                    category = mapping_info.get('category', 'unknown')
                    mapping_stats['categories'].add(category)
                    
                    source = mapping_info.get('mapping_source', 'unknown')
                    mapping_stats['sources'].add(source)
                    
                    confidence = mapping_info.get('confidence', 0.0)
                    confidences.append(confidence)
        
        mapping_stats['categories'] = list(mapping_stats['categories'])
        mapping_stats['sources'] = list(mapping_stats['sources'])
        mapping_stats['avg_confidence'] = sum(confidences) / len(confidences) if confidences else 0
        
        return {
            'mappings': all_mappings,
            'statistics': mapping_stats
        }
    
    def _extract_scoring_configuration(self, tab_states: Dict[str, Any]) -> Dict[str, Any]:
        """Extract scoring configuration from tab states."""
        scoring_configs = {}
        
        for tab_id, tab_state in tab_states.items():
            scoring_config = tab_state.get('scoring_configuration', {})
            if scoring_config:
                scoring_configs[tab_id] = scoring_config
        
        merged_config = {}
        if scoring_configs:
            first_config = next(iter(scoring_configs.values()))
            merged_config = first_config.copy()
        
        return {
            'configurations': scoring_configs,
            'merged_configuration': merged_config
        }
    
    def _generate_summary_statistics(self, tab_states: Dict[str, Any]) -> Dict[str, Any]:
        """Generate summary statistics for the export."""
        total_matches = 0
        total_tabs = len(tab_states)
        all_scores = []
        semantic_tabs = 0
        scoring_tabs = 0
        
        for tab_state in tab_states.values():
            matches = tab_state.get('matches', [])
            total_matches += len(matches)
            
            for match in matches:
                score = match.get('match_score', 0)
                all_scores.append(score)
            
            if tab_state.get('semantic_mappings'):
                semantic_tabs += 1
            
            if tab_state.get('scoring_configuration'):
                scoring_tabs += 1
        
        avg_score = sum(all_scores) / len(all_scores) if all_scores else 0
        
        return {
            'total_matches': total_matches,
            'total_tabs': total_tabs,
            'average_score': round(avg_score, 3),
            'tabs_with_semantic_mappings': semantic_tabs,
            'tabs_with_scoring_configuration': scoring_tabs,
            'semantic_coverage_percent': round((semantic_tabs / total_tabs * 100), 1) if total_tabs > 0 else 0,
            'scoring_coverage_percent': round((scoring_tabs / total_tabs * 100), 1) if total_tabs > 0 else 0
        }


# Backward compatibility alias
EnhancedResultsExporter = ResultsExporter


def show_export_dialog(tab_states: Dict[str, Any], parent=None) -> Optional[Dict[str, Any]]:
    """
    Show export options dialog and return export configuration.
    
    Args:
        tab_states: Dictionary of tab states to export
        parent: Parent widget
        
    Returns:
        Export configuration dictionary or None if cancelled
    """
    dialog = ExportOptionsDialog(tab_states, parent)
    
    if dialog.exec_() == QDialog.Accepted:
        return dialog.get_export_config()
    
    return None


def export_results_with_progress(export_config: Dict[str, Any], parent=None) -> tuple[bool, str]:
    """
    Export results with progress dialog.
    
    Args:
        export_config: Export configuration
        parent: Parent widget
        
    Returns:
        Tuple of (success, message)
    """
    progress = QProgressDialog("Preparing export...", "Cancel", 0, 100, parent)
    progress.setWindowTitle("Exporting Results")
    progress.setWindowModality(Qt.WindowModal)
    progress.setMinimumDuration(0)
    
    # Apply Crow Eye styling
    from .ui_styling import CorrelationEngineStyles
    CorrelationEngineStyles.apply_progress_dialog_style(progress)
    progress.show()
    
    worker = ExportWorker(export_config)
    
    worker.progress_updated.connect(lambda value, status: (
        progress.setValue(value),
        progress.setLabelText(status)
    ))
    
    result = [False, ""]
    
    def on_export_completed(filepath, success, message):
        result[0] = success
        result[1] = message
        progress.close()
    
    worker.export_completed.connect(on_export_completed)
    
    worker.start()
    worker.wait()
    
    return result[0], result[1]
