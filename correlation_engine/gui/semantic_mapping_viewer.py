"""
Semantic Mapping Viewer

Viewer for displaying and managing semantic mappings.
Shows built-in, global, and wing-specific mappings with coverage statistics.
Enhanced with correlation result integration, tooltips, and filtering options.

Implements Task 13: Create Semantic Mapping Viewer
Enhanced for Task 7.3: Create semantic mapping display components
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QTableWidget, QTableWidgetItem, QLabel, QPushButton,
    QTextEdit, QGroupBox, QComboBox, QMessageBox, QHeaderView,
    QCheckBox, QLineEdit, QSplitter, QFrame, QScrollArea
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPixmap, QPainter
from typing import List, Dict, Optional, Any, Tuple

from correlation_engine.config.semantic_mapping import SemanticMappingManager, SemanticMapping


class SemanticInfoDisplayWidget(QWidget):
    """
    Widget for displaying semantic information in correlation results.
    
    Shows semantic mappings for individual records with tooltips and filtering.
    """
    
    def __init__(self, parent=None):
        """
        Initialize semantic info display widget.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.semantic_data = {}
        self.current_record = {}
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the semantic info display UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header
        header_layout = QHBoxLayout()
        
        title_label = QLabel("Semantic Information")
        title_label.setFont(QFont("Arial", 10, QFont.Bold))
        header_layout.addWidget(title_label)
        
        # Filter controls
        self.show_mapped_only = QCheckBox("Show mapped fields only")
        self.show_mapped_only.setChecked(False)
        self.show_mapped_only.stateChanged.connect(self.refresh_display)
        header_layout.addWidget(self.show_mapped_only)
        
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        # Semantic info table
        self.semantic_table = QTableWidget()
        self.semantic_table.setColumnCount(5)
        self.semantic_table.setHorizontalHeaderLabels([
            "Field", "Raw Value", "Semantic Value", "Category", "Confidence"
        ])
        
        # Configure table
        self.semantic_table.setAlternatingRowColors(True)
        self.semantic_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.semantic_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.semantic_table.verticalHeader().setVisible(False)
        
        # Set column resize modes
        header = self.semantic_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Field
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Raw Value
        header.setSectionResizeMode(2, QHeaderView.Stretch)  # Semantic Value
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Category
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Confidence
        
        # Enable tooltips
        self.semantic_table.setMouseTracking(True)
        self.semantic_table.cellEntered.connect(self._show_field_tooltip)
        
        layout.addWidget(self.semantic_table)
        
        # Summary section
        self.summary_label = QLabel("No semantic information available")
        self.summary_label.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(self.summary_label)
    
    def display_semantic_info(self, record: Dict[str, Any], semantic_data: Dict[str, Any]):
        """
        Display semantic information for a correlation record.
        
        Args:
            record: Correlation record data
            semantic_data: Semantic mapping information
        """
        self.current_record = record
        self.semantic_data = semantic_data
        self.refresh_display()
    
    def refresh_display(self):
        """Refresh the semantic information display."""
        self.semantic_table.setRowCount(0)
        
        if not self.semantic_data or '_semantic_mappings' not in self.semantic_data:
            self.summary_label.setText("No semantic mappings available for this record")
            return
        
        semantic_mappings = self.semantic_data['_semantic_mappings']
        show_mapped_only = self.show_mapped_only.isChecked()
        
        # Count statistics
        total_fields = 0
        mapped_fields = 0
        
        # Process all fields in the record
        for field_name, field_value in self.current_record.items():
            if field_name.startswith('_'):  # Skip internal fields
                continue
            
            total_fields += 1
            has_mapping = field_name in semantic_mappings
            
            if has_mapping:
                mapped_fields += 1
            
            # Skip unmapped fields if filter is enabled
            if show_mapped_only and not has_mapping:
                continue
            
            # Add row to table
            row = self.semantic_table.rowCount()
            self.semantic_table.insertRow(row)
            
            # Field name
            field_item = QTableWidgetItem(field_name)
            if has_mapping:
                field_item.setFont(QFont("Arial", 9, QFont.Bold))
                field_item.setForeground(QColor("#2196F3"))  # Blue for mapped fields
            else:
                field_item.setForeground(QColor("#666"))  # Gray for unmapped fields
            
            self.semantic_table.setItem(row, 0, field_item)
            
            # Raw value
            raw_value_item = QTableWidgetItem(str(field_value))
            self.semantic_table.setItem(row, 1, raw_value_item)
            
            if has_mapping:
                mapping_info = semantic_mappings[field_name]
                
                # Semantic value
                semantic_value = mapping_info.get('semantic_value', str(field_value))
                semantic_item = QTableWidgetItem(semantic_value)
                semantic_item.setFont(QFont("Arial", 9, QFont.Bold))
                semantic_item.setForeground(QColor("#4CAF50"))  # Green for semantic values
                self.semantic_table.setItem(row, 2, semantic_item)
                
                # Category
                category = mapping_info.get('category', 'N/A')
                category_item = QTableWidgetItem(category)
                self._apply_category_color(category_item, category)
                self.semantic_table.setItem(row, 3, category_item)
                
                # Confidence
                confidence = mapping_info.get('confidence', 0.0)
                confidence_item = QTableWidgetItem(f"{confidence:.2f}")
                confidence_item.setTextAlignment(Qt.AlignCenter)
                self._apply_confidence_color(confidence_item, confidence)
                self.semantic_table.setItem(row, 4, confidence_item)
                
                # Set tooltips
                tooltip = self._generate_field_tooltip(field_name, field_value, mapping_info)
                for col in range(5):
                    item = self.semantic_table.item(row, col)
                    if item:
                        item.setToolTip(tooltip)
            
            else:
                # No mapping available
                no_mapping_item = QTableWidgetItem("(no mapping)")
                no_mapping_item.setForeground(QColor("#999"))
                no_mapping_item.setFont(QFont("Arial", 9, QFont.Italic))
                self.semantic_table.setItem(row, 2, no_mapping_item)
                
                self.semantic_table.setItem(row, 3, QTableWidgetItem("-"))
                self.semantic_table.setItem(row, 4, QTableWidgetItem("-"))
                
                # Tooltip for unmapped field
                tooltip = f"Field: {field_name}\nRaw Value: {field_value}\nNo semantic mapping available"
                for col in range(5):
                    item = self.semantic_table.item(row, col)
                    if item:
                        item.setToolTip(tooltip)
        
        # Update summary
        if total_fields > 0:
            mapping_percentage = (mapped_fields / total_fields) * 100
            self.summary_label.setText(
                f"Semantic coverage: {mapped_fields}/{total_fields} fields mapped ({mapping_percentage:.1f}%)"
            )
        else:
            self.summary_label.setText("No fields found in record")
        
        self.semantic_table.resizeRowsToContents()
    
    def _apply_category_color(self, item: QTableWidgetItem, category: str):
        """Apply color coding based on semantic category."""
        category_colors = {
            'security': '#F44336',      # Red
            'system': '#FF9800',        # Orange  
            'application': '#4CAF50',   # Green
            'network': '#2196F3',       # Blue
            'file': '#9C27B0',          # Purple
            'process': '#FF5722',       # Deep Orange
            'user': '#795548',          # Brown
            'time': '#607D8B',          # Blue Gray
            'unknown': '#9E9E9E'        # Gray
        }
        
        color = category_colors.get(category.lower(), '#9E9E9E')
        item.setForeground(QColor(color))
    
    def _apply_confidence_color(self, item: QTableWidgetItem, confidence: float):
        """Apply color coding based on confidence level."""
        if confidence >= 0.8:
            item.setForeground(QColor("#4CAF50"))  # Green - High confidence
        elif confidence >= 0.6:
            item.setForeground(QColor("#FF9800"))  # Orange - Medium confidence
        elif confidence >= 0.4:
            item.setForeground(QColor("#FF5722"))  # Deep Orange - Low confidence
        else:
            item.setForeground(QColor("#F44336"))  # Red - Very low confidence
    
    def _generate_field_tooltip(self, field_name: str, field_value: Any, mapping_info: Dict[str, Any]) -> str:
        """Generate detailed tooltip for a mapped field."""
        tooltip_lines = [
            f"Field: {field_name}",
            f"Raw Value: {field_value}",
            f"Semantic Value: {mapping_info.get('semantic_value', 'N/A')}",
            "",
            f"Category: {mapping_info.get('category', 'N/A')}",
            f"Confidence: {mapping_info.get('confidence', 0.0):.2f}",
            f"Severity: {mapping_info.get('severity', 'N/A')}",
            f"Source: {mapping_info.get('mapping_source', 'N/A')}"
        ]
        
        description = mapping_info.get('description', '')
        if description:
            tooltip_lines.extend(["", f"Description: {description}"])
        
        return "\n".join(tooltip_lines)
    
    def _show_field_tooltip(self, row: int, column: int):
        """Show tooltip when mouse enters a cell."""
        item = self.semantic_table.item(row, column)
        if item and item.toolTip():
            # Tooltip is already set, Qt handles display
            pass
    
    def clear(self):
        """Clear all displayed semantic information."""
        self.semantic_table.setRowCount(0)
        self.semantic_data = {}
        self.current_record = {}
        self.summary_label.setText("No semantic information available")


class Semanget):
    """
    Pane
    """
    
    # Signachange
    filter_changdict)
    
    def __init__(self, parent=None):
        """
        Initialize semantic filter panel.
        
        As:

"
        super().__init__(parent)
       t()
        self.available_severities = set()
       )
    
    def setup_ui(self):
        """Setup the filter panel UI."
    ut(self)
        layout.setContentsMargins(5, 5)
        
        # Title
        )
        titleold))
        layout.addWidget(title_label)
        
        # Category filter
        category_group = QGroupBox("Categ")
        category_layout = QVBoxLayout(cat)
        
    mboBox()
        self.category_fs")
        self.category_filter.currentText
        category_layout.addWidget(r)
        
        up)
        
        # Severity filter
        severity_group = QGroupBox("Severity")
        severity_layout = QVBoxLayout_group)
        
        self.severity_filx()
        self.severity_filter.addItem("All Severi")
        self.severity_filter.currentTextChanged.conne)
        
        
        layout.addWidget(severity_group)
        
        # Confidence filter
        dence")
        confidence_layout = QVBoxLayout(e_group)
        
        confidence_filterut()
        confidence_filter_layout.addWidget(QLa
        
        ox()
        self.confidence_filter.addItems([""])
        self.confidence_filter.setCurrentText("0.0")
        self.confidence_filter.currentTextChanged.connect(self._emit_filter_chang
        confidence_filter_layout.addWidget(self.confide
        
        confidence_layout.addLayout(confut)
        
        
        # Mapping status filter
        status_group = QGroupBox("Mapping Status")
        
        
        self.show_mapped = QCheckBox("Show mapped fields")
        
        self.show_mapped.stateChanged.connec)
        status_layout.addWidget(self.show_mapped)
        
        self.show_unmapped = QCheckBox("Show unmapped fields")
        self.show_unmapped.setChecked(True)
        
        status_layout.addWidget(self.show_unmapped)
        
        
        
        # Search filter
        search_group = QGroupBox("Search")
        )
        
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Search in field names or ...")
        self.search_field.textChanged.connect(sel
        rch_field)
        
        layout.addWidget(search_group)
        
        # Reset button
        rs")
        reset_button.clicked.connect(s)
        
        
        layout.addStretch()
    
    def 
        """
        Get current filter criteria.
        
        Returns:
        iteria
        """
        {
            'category',
            'severity': self.severity_filter.curren
            'min_confidence': float(self.confidence_filtt()),
            'show_mapped': self.show_mked(),
        ,
            'search_text': e
    
    
    def res
        """Reset all filters to default values."""
        es")
        self.es")
        self.confidence_filter.setCurrentText("0.0")
        selue)
        self.show_unmappedue)
        self.search_field.clear()
    
    def _emit_filter_change(self):
        """Emit filter change signal with current criteria."""
        self.filter_changed.emit(self.get_filter_criteria())


class SemanticMappingViewer(QDialog):
    """
    Viewer for semantic mappingstion.
    Enhanced with correlation result integrationg.
    
    Implements Task 13: Semantic Mapping Viewer
    Enhanents
    """
    
    def __init__(self, mapping_managone):
        """
        Initialize semantic mapping viewer.
        
        Args:
            mapping_manager: SemanticMappingManager instance
            parent: Paget
        """
        t)
        self.mapping_manager = mnager
        self.setup_ui()
        self.load_data()
    
    def setup_ui(self):
        ""
        self.setWindowTitle("Semantic Mapping 
        self.setMinimumSize(1200, 800)  # Increased size for nes
        
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("<h2>Semantic Mapping V</h2>")
    get(title)
        
        # Section
        stats_group = QGroupBox("Covics")
        ut()
        self.statEdit()
        self.stats_text.setReadOnly(True)
        sel100)
        stats_la)
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        # Filter section
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter by Artifact:"))
        s()
    "All")
        self.artifact_filter
        filter_layout.addWidget(self.artifact_filter)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)
        
        # Tabs for different mapping sources
        self.tabs = QTabWidget()
        
    Mappings
        self.all_tab = self._creatle()
        self.tabs.addTab(self.all_tab, "All Mappings")
        
pings
able()
       
        
    gs
        self.global_tab = self._create_mapping_
       al")
    
        # Tab 4: Wing Mappings
        sel
        self.tabs.addTab(self.wing_tab, "Wic")
        
        # Tablicts
        self.conflicts_tab = self._create_conflicts_tab()
        self.tabs.addTab(self.connflicts")
        
        # Tab 6: Correlation Resew)
        self.correlation_tab = self._create_cob()
        self.tabs.addTaResults")
        
    s)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        refresh_btn = QPushButton(
        
        button_)
        
        close_btn = QPushButton")
        t)
        button_layout.addWid
        
        layout.addLayout(button_layo
    
    def _create_mapping_table(self) -> QT
        """Create a table widget for displayi"
        table = QTableWidget()
        table.setColumnCount(7)
        table.setHorizontalHeaderLabe
        ng", 
            "Category", nce"
        ])
        table.horizontalHeader().setStretchLastSection(True)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWitRows)
        table.setMouseTracking(True)
        table.cellEntered.connect(lambda row, col: sel))
        
        return table
    
    def _create_correlation_results_tab(selfet:
        """Create tab for displas."""
        et()
        layout = QVBoxLayout(idget)
        
        # Instructions
        )
        info_label.setStyleSheet("0px;")
        layout.addWidget(info_label)
        
        
        self.semantic_info_widge)
        layout.addWidget(self.semantic_info_widget)
        
        
    
    def _create_conflicts_tab(self) -> QWidget:
        """Create conflicts detection tab with enhanced ""
        
        layout = QVBoxLayot)
        
        info_label = QLabel("Conflicts occur when multipllue.")
        bel)
        
        ()
        self.conf4)
        self.conflicts_table.setHoriz
            "Field", "Value", "Cons"
        ])
        self.conflicts_table.horizontalHeadeon(True)
        layout.addWidget(self.conflicts_table)
        
        idget
    
    def _show_mapping_tooltip(self, table: QTa
        """Show detailed tooltip for mappi"
        lumn)
        if not item:
    
        
        # Get mapping data for this row
        field_item = table.ite
        value_item = table.itemrow, 2)
        meaning_item = table.item(row, 3)
        category_item = table.item(row, 4)
        confidence_item = table.item(row, 6)
        
        if all([field_item, value_item, meaning_item, categoitem]):
            tooltip = (
                f"Field: {field_item.text()}\n"
                f"Tet()}\n"
    \n"
                f"Category: {category_item.text
                f"Confidence: {confidence_ite\n\n"
                f"Click fo..."
            )
        
    
    def load_data(self):
        "
        self._load_statistics()
        self._load_artifact_filter()
        self._load_all_mappings()
        self._load_builtin_mappings()
        segs()
        self._load_wing_mappings()
        self._detect_conflicts()
    
    def _load_statist
    "
        all_mappings = s
        
        # Count mappings by source
        builtin_count = sum(1 for m in")
        global_count = sum(1 for ")
        wing_count = sum(1 for m in a)
        
        # Count artifacts and catered
        artifacts = set(m.artifa
    gory)
        
        stats_html = f"""
<b>Total Mappings:</b> {len(all_ma}<br>
<b>Built-in:</b> {builtin_count} | <b>Global:</b> {global_count}
<b>Artifacts Covered:</b> {len(artifacts)}<br>
<b>Categories:</b> {len(categories)}<br>
        """
        self.stats_text.setHtml(stats_html)
    
    def self):
        """Load artifact types in
        artifacts = set(m.artifact_type for m in self._get_all_mappings() if m.artifact_type)
        
        current = self.art()
        self.artifact_filter.clear()
        
        self.artifact_fil)
        
        # Restore selection
        index = self.artifact_filter.findText(
        if index >= 0:
           ex)
    
    
        """Get all mappings from man"
        all_mappings = []
        
        
        for mappings_list in self.mapping_manager.gl
            all_mappings.extend(mappst)
        
        # Get from artifact mappings
        .values():
            all_mappings.ex
        
        return all_mapgs
    
    
        """Load all mappings into table."""
        self._populate_table(self.all_tab, s
    
    def lf):
        """Load built-in mappings."""
        mappings = [m for m in self._get_all_mappings() if m.mapping_source
        self._populate_table(self.builtin_tab,
    
    def _load_global_mappings(self):
        """Load global mappings."""
        mappings = [m for m in self._get_all_mal"]
        s)
    
    
        """Load wing-specific map
        mappings = [m for m in self._get_al"]
        self._populate_table(self.wing_tab, mappings)
    
    def _populate_table(self, table: ):
        """Populate table with mappin"
        # Apply artifact filter
        artifact_filter = self.artifact_filter.currentTet()
    "All":
            mappings = [m for m in m
        
        table.setRowCount(len(mappings))
        
    s):
            table.setItem(i, 0, QT)
            table.setItem(i, 1, QTableWidgeld))
            table.setItem(i, 2, QTableWidgetItem(mapping.technical_value))
            table.setItem(i, 3, QTableWidgetItem(mappe))
    
            
            # Severity with color
            severity_item = QTa)
            if mapping.severity == "critical":
                severity_item.setFor))
            elif mapping.severity == "high":
        , 0))
            elif mapping.severity == "me
        ))
            table.setItem(i, 5, severity_item)
            
            table.setItem(i, 6, QTableWidgetItem(f"{mapping.conf
    
    def _detect_conflicts(self):
        """Detect and display mapping conflicts with resolution suggestions."""
        # Grue
        mapping_groups: Dict[Tupl{}
        
        for mapping in self._get_all_mappings(
            key = (mapping.field, mapping.technical_value)
            if key not in mapping_groups:
                mapping_groups[key] = []
            mapping_groups[key].append(mapping
        
        # Find conflicts (multiple different m/value)
        conf
        for (field, value), mappings in mapping_groups.items():
    s)
            if len(meanings) > 1:
                conflicts.append((field, value, mapgs))
        
        # Populate conflicts table
        ts))
        
        for i, (field, value, mappings) in enumerate(conflicts):
            self.conflicts_table.setItem(ield))
            self.conflicts_table.setIteme))
            
        gs))
            self.conflicts_table.setItem(i, 2, QTableWidgetItem(meanings))
            
            sources = ", ".join(set(m.mapping_source for m in m)
            self.conflicts_table.setItem(i, 3, QTableWidgetItees))
    
    def apply_filter(self):
        abs."""
        self._load_all_mappings()
        self._load_builtin_mappings()
        s()
        self._load_wing_mappings()

# A
dditional components for Task 7.3: Create semantic mapping display components

class SemanticInfoDisplayWidget(QWidget):
    """
    Widget for displaying semantic information in correlation results.
    
    Shows semantic mappings for individual records with tooltips and filtering.
    """
    
    def __init__(self, parent=None):
        """
        Initialize semantic info display widget.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.semantic_data = {}
        self.current_record = {}
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the semantic info display UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header
        header_layout = QHBoxLayout()
        
        title_label = QLabel("Semantic Information")
        title_label.setFont(QFont("Arial", 10, QFont.Bold))
        header_layout.addWidget(title_label)
        
        # Filter controls
        self.show_mapped_only = QCheckBox("Show mapped fields only")
        self.show_mapped_only.setChecked(False)
        self.show_mapped_only.stateChanged.connect(self.refresh_display)
        header_layout.addWidget(self.show_mapped_only)
        
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        # Semantic info table
        self.semantic_table = QTableWidget()
        self.semantic_table.setColumnCount(5)
        self.semantic_table.setHorizontalHeaderLabels([
            "Field", "Raw Value", "Semantic Value", "Category", "Confidence"
        ])
        
        # Configure table
        self.semantic_table.setAlternatingRowColors(True)
        self.semantic_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.semantic_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.semantic_table.verticalHeader().setVisible(False)
        
        # Set column resize modes
        header = self.semantic_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Field
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Raw Value
        header.setSectionResizeMode(2, QHeaderView.Stretch)  # Semantic Value
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Category
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Confidence
        
        # Enable tooltips
        self.semantic_table.setMouseTracking(True)
        self.semantic_table.cellEntered.connect(self._show_field_tooltip)
        
        layout.addWidget(self.semantic_table)
        
        # Summary section
        self.summary_label = QLabel("No semantic information available")
        self.summary_label.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(self.summary_label)
    
    def display_semantic_info(self, record: Dict[str, Any], semantic_data: Dict[str, Any]):
        """
        Display semantic information for a correlation record.
        
        Args:
            record: Correlation record data
            semantic_data: Semantic mapping information
        """
        self.current_record = record
        self.semantic_data = semantic_data
        self.refresh_display()
    
    def refresh_display(self):
        """Refresh the semantic information display."""
        self.semantic_table.setRowCount(0)
        
        if not self.semantic_data or '_semantic_mappings' not in self.semantic_data:
            self.summary_label.setText("No semantic mappings available for this record")
            return
        
        semantic_mappings = self.semantic_data['_semantic_mappings']
        show_mapped_only = self.show_mapped_only.isChecked()
        
        # Count statistics
        total_fields = 0
        mapped_fields = 0
        
        # Process all fields in the record
        for field_name, field_value in self.current_record.items():
            if field_name.startswith('_'):  # Skip internal fields
                continue
            
            total_fields += 1
            has_mapping = field_name in semantic_mappings
            
            if has_mapping:
                mapped_fields += 1
            
            # Skip unmapped fields if filter is enabled
            if show_mapped_only and not has_mapping:
                continue
            
            # Add row to table
            row = self.semantic_table.rowCount()
            self.semantic_table.insertRow(row)
            
            # Field name
            field_item = QTableWidgetItem(field_name)
            if has_mapping:
                field_item.setFont(QFont("Arial", 9, QFont.Bold))
                field_item.setForeground(QColor("#2196F3"))  # Blue for mapped fields
            else:
                field_item.setForeground(QColor("#666"))  # Gray for unmapped fields
            
            self.semantic_table.setItem(row, 0, field_item)
            
            # Raw value
            raw_value_item = QTableWidgetItem(str(field_value))
            self.semantic_table.setItem(row, 1, raw_value_item)
            
            if has_mapping:
                mapping_info = semantic_mappings[field_name]
                
                # Semantic value
                semantic_value = mapping_info.get('semantic_value', str(field_value))
                semantic_item = QTableWidgetItem(semantic_value)
                semantic_item.setFont(QFont("Arial", 9, QFont.Bold))
                semantic_item.setForeground(QColor("#4CAF50"))  # Green for semantic values
                self.semantic_table.setItem(row, 2, semantic_item)
                
                # Category
                category = mapping_info.get('category', 'N/A')
                category_item = QTableWidgetItem(category)
                self._apply_category_color(category_item, category)
                self.semantic_table.setItem(row, 3, category_item)
                
                # Confidence
                confidence = mapping_info.get('confidence', 0.0)
                confidence_item = QTableWidgetItem(f"{confidence:.2f}")
                confidence_item.setTextAlignment(Qt.AlignCenter)
                self._apply_confidence_color(confidence_item, confidence)
                self.semantic_table.setItem(row, 4, confidence_item)
                
                # Set tooltips
                tooltip = self._generate_field_tooltip(field_name, field_value, mapping_info)
                for col in range(5):
                    item = self.semantic_table.item(row, col)
                    if item:
                        item.setToolTip(tooltip)
            
            else:
                # No mapping available
                no_mapping_item = QTableWidgetItem("(no mapping)")
                no_mapping_item.setForeground(QColor("#999"))
                no_mapping_item.setFont(QFont("Arial", 9, QFont.Italic))
                self.semantic_table.setItem(row, 2, no_mapping_item)
                
                self.semantic_table.setItem(row, 3, QTableWidgetItem("-"))
                self.semantic_table.setItem(row, 4, QTableWidgetItem("-"))
                
                # Tooltip for unmapped field
                tooltip = f"Field: {field_name}\nRaw Value: {field_value}\nNo semantic mapping available"
                for col in range(5):
                    item = self.semantic_table.item(row, col)
                    if item:
                        item.setToolTip(tooltip)
        
        # Update summary
        if total_fields > 0:
            mapping_percentage = (mapped_fields / total_fields) * 100
            self.summary_label.setText(
                f"Semantic coverage: {mapped_fields}/{total_fields} fields mapped ({mapping_percentage:.1f}%)"
            )
        else:
            self.summary_label.setText("No fields found in record")
        
        self.semantic_table.resizeRowsToContents()
    
    def _apply_category_color(self, item: QTableWidgetItem, category: str):
        """Apply color coding based on semantic category."""
        category_colors = {
            'security': '#F44336',      # Red
            'system': '#FF9800',        # Orange  
            'application': '#4CAF50',   # Green
            'network': '#2196F3',       # Blue
            'file': '#9C27B0',          # Purple
            'process': '#FF5722',       # Deep Orange
            'user': '#795548',          # Brown
            'time': '#607D8B',          # Blue Gray
            'unknown': '#9E9E9E'        # Gray
        }
        
        color = category_colors.get(category.lower(), '#9E9E9E')
        item.setForeground(QColor(color))
    
    def _apply_confidence_color(self, item: QTableWidgetItem, confidence: float):
        """Apply color coding based on confidence level."""
        if confidence >= 0.8:
            item.setForeground(QColor("#4CAF50"))  # Green - High confidence
        elif confidence >= 0.6:
            item.setForeground(QColor("#FF9800"))  # Orange - Medium confidence
        elif confidence >= 0.4:
            item.setForeground(QColor("#FF5722"))  # Deep Orange - Low confidence
        else:
            item.setForeground(QColor("#F44336"))  # Red - Very low confidence
    
    def _generate_field_tooltip(self, field_name: str, field_value: Any, mapping_info: Dict[str, Any]) -> str:
        """Generate detailed tooltip for a mapped field."""
        tooltip_lines = [
            f"Field: {field_name}",
            f"Raw Value: {field_value}",
            f"Semantic Value: {mapping_info.get('semantic_value', 'N/A')}",
            "",
            f"Category: {mapping_info.get('category', 'N/A')}",
            f"Confidence: {mapping_info.get('confidence', 0.0):.2f}",
            f"Severity: {mapping_info.get('severity', 'N/A')}",
            f"Source: {mapping_info.get('mapping_source', 'N/A')}"
        ]
        
        description = mapping_info.get('description', '')
        if description:
            tooltip_lines.extend(["", f"Description: {description}"])
        
        return "\n".join(tooltip_lines)
    
    def _show_field_tooltip(self, row: int, column: int):
        """Show tooltip when mouse enters a cell."""
        item = self.semantic_table.item(row, column)
        if item and item.toolTip():
            # Tooltip is already set, Qt handles display
            pass
    
    def clear(self):
        """Clear all displayed semantic information."""
        self.semantic_table.setRowCount(0)
        self.semantic_data = {}
        self.current_record = {}
        self.summary_label.setText("No semantic information available")


class SemanticFilterPanel(QWidget):
    """
    Panel for filtering correlation results based on semantic information.
    """
    
    # Signal emitted when filter criteria change
    filter_changed = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        """
        Initialize semantic filter panel.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.available_categories = set()
        self.available_severities = set()
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the filter panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Title
        title_label = QLabel("Semantic Filters")
        title_label.setFont(QFont("Arial", 10, QFont.Bold))
        layout.addWidget(title_label)
        
        # Category filter
        category_group = QGroupBox("Categories")
        category_layout = QVBoxLayout(category_group)
        
        self.category_filter = QComboBox()
        self.category_filter.addItem("All Categories")
        self.category_filter.currentTextChanged.connect(self._emit_filter_change)
        category_layout.addWidget(self.category_filter)
        
        layout.addWidget(category_group)
        
        # Severity filter
        severity_group = QGroupBox("Severity")
        severity_layout = QVBoxLayout(severity_group)
        
        self.severity_filter = QComboBox()
        self.severity_filter.addItem("All Severities")
        self.severity_filter.currentTextChanged.connect(self._emit_filter_change)
        severity_layout.addWidget(self.severity_filter)
        
        layout.addWidget(severity_group)
        
        # Confidence filter
        confidence_group = QGroupBox("Confidence")
        confidence_layout = QVBoxLayout(confidence_group)
        
        confidence_filter_layout = QHBoxLayout()
        confidence_filter_layout.addWidget(QLabel("Minimum:"))
        
        self.confidence_filter = QComboBox()
        self.confidence_filter.addItems(["0.0", "0.2", "0.4", "0.6", "0.8"])
        self.confidence_filter.setCurrentText("0.0")
        self.confidence_filter.currentTextChanged.connect(self._emit_filter_change)
        confidence_filter_layout.addWidget(self.confidence_filter)
        
        confidence_layout.addLayout(confidence_filter_layout)
        layout.addWidget(confidence_group)
        
        # Mapping status filter
        status_group = QGroupBox("Mapping Status")
        status_layout = QVBoxLayout(status_group)
        
        self.show_mapped = QCheckBox("Show mapped fields")
        self.show_mapped.setChecked(True)
        self.show_mapped.stateChanged.connect(self._emit_filter_change)
        status_layout.addWidget(self.show_mapped)
        
        self.show_unmapped = QCheckBox("Show unmapped fields")
        self.show_unmapped.setChecked(True)
        self.show_unmapped.stateChanged.connect(self._emit_filter_change)
        status_layout.addWidget(self.show_unmapped)
        
        layout.addWidget(status_group)
        
        # Search filter
        search_group = QGroupBox("Search")
        search_layout = QVBoxLayout(search_group)
        
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Search in field names or values...")
        self.search_field.textChanged.connect(self._emit_filter_change)
        search_layout.addWidget(self.search_field)
        
        layout.addWidget(search_group)
        
        # Reset button
        reset_button = QPushButton("Reset Filters")
        reset_button.clicked.connect(self.reset_filters)
        layout.addWidget(reset_button)
        
        layout.addStretch()
    
    def get_filter_criteria(self) -> Dict[str, Any]:
        """
        Get current filter criteria.
        
        Returns:
            Dictionary with filter criteria
        """
        return {
            'category': self.category_filter.currentText() if self.category_filter.currentText() != "All Categories" else None,
            'severity': self.severity_filter.currentText() if self.severity_filter.currentText() != "All Severities" else None,
            'min_confidence': float(self.confidence_filter.currentText()),
            'show_mapped': self.show_mapped.isChecked(),
            'show_unmapped': self.show_unmapped.isChecked(),
            'search_text': self.search_field.text().strip() if self.search_field.text().strip() else None
        }
    
    def reset_filters(self):
        """Reset all filters to default values."""
        self.category_filter.setCurrentText("All Categories")
        self.severity_filter.setCurrentText("All Severities")
        self.confidence_filter.setCurrentText("0.0")
        self.show_mapped.setChecked(True)
        self.show_unmapped.setChecked(True)
        self.search_field.clear()
    
    def _emit_filter_change(self):
        """Emit filter change signal with current criteria."""
        self.filter_changed.emit(self.get_filter_criteria())