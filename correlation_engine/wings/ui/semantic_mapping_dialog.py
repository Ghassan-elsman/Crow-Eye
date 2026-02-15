"""
Semantic Mapping Dialog - Ultra Compact Version
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QDialogButtonBox, QFormLayout, QGroupBox, QMessageBox, 
    QComboBox, QRadioButton, QButtonGroup, QTableWidget, 
    QPushButton, QHeaderView, QWidget, QScrollArea, QFrame
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPalette, QColor, QFont
from ...config.semantic_mapping import SemanticCondition, SemanticRule
import uuid


class SemanticMappingDialog(QDialog):
    def __init__(self, parent=None, mapping=None, scope='global', wing_id=None, 
                 available_feathers=None, mode='simple'):
        super().__init__(parent)
        
        # Set window flags to ensure independent styling
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        
        self.mapping = mapping or {}
        self.scope = scope
        self.wing_id = wing_id
        self.available_feathers = available_feathers or []
        self.mode = mode
        if self.mapping and self.mapping.get('conditions'):
            self.mode = 'advanced'
        
        self.init_ui()
        self.load_mapping()
    
    def init_ui(self):
        self.setWindowTitle("Semantic Mapping")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)
        
        # Mode + Scope in single compact bar
        mode_frame = QFrame()
        mode_frame.setStyleSheet("QFrame { background-color: #1E293B; border: 1px solid #334155; border-radius: 6px; }")
        mode_frame.setFixedHeight(42)
        mode_layout = QHBoxLayout(mode_frame)
        mode_layout.setSpacing(16)
        mode_layout.setContentsMargins(14, 0, 14, 0)
        
        mode_label = QLabel("Mode:")
        mode_label.setStyleSheet("font-size: 11pt; font-weight: bold; color: #00FFFF; background: transparent;")
        mode_layout.addWidget(mode_label)
        
        self.mode_group = QButtonGroup()
        self.simple_radio = QRadioButton("Simple")
        self.simple_radio.setChecked(self.mode == 'simple')
        self.simple_radio.toggled.connect(self._mode_changed)
        self.simple_radio.setStyleSheet("font-size: 11pt; font-weight: bold; color: #F8FAFC; background: transparent;")
        self.mode_group.addButton(self.simple_radio)
        mode_layout.addWidget(self.simple_radio)
        
        self.adv_radio = QRadioButton("Advanced")
        self.adv_radio.setChecked(self.mode == 'advanced')
        self.adv_radio.setStyleSheet("font-size: 11pt; font-weight: bold; color: #F8FAFC; background: transparent;")
        self.mode_group.addButton(self.adv_radio)
        mode_layout.addWidget(self.adv_radio)
        
        # Scope in same bar
        if not self.mapping:
            sep = QLabel("|")
            sep.setStyleSheet("color: #475569; font-size: 14pt; background: transparent;")
            mode_layout.addWidget(sep)
            
            scope_label = QLabel("Scope:")
            scope_label.setStyleSheet("font-size: 11pt; font-weight: bold; color: #3B82F6; background: transparent;")
            mode_layout.addWidget(scope_label)
            
            self.scope_group = QButtonGroup()
            self.global_radio = QRadioButton("Global")
            self.global_radio.setChecked(self.scope == 'global')
            self.global_radio.setStyleSheet("font-size: 11pt; font-weight: bold; color: #F8FAFC; background: transparent;")
            self.scope_group.addButton(self.global_radio)
            mode_layout.addWidget(self.global_radio)
            
            self.wing_radio = QRadioButton("Wing")
            self.wing_radio.setEnabled(self.wing_id is not None)
            self.wing_radio.setStyleSheet("font-size: 11pt; font-weight: bold; color: #F8FAFC; background: transparent;")
            self.scope_group.addButton(self.wing_radio)
            mode_layout.addWidget(self.wing_radio)
        
        mode_layout.addStretch()
        layout.addWidget(mode_frame)
        
        # Simple mode form - professional with visible text
        self.simple_grp = QGroupBox("Simple Mapping")
        self.simple_grp.setStyleSheet("""
            QGroupBox { 
                font-size: 11pt; font-weight: bold; color: #00FFFF; 
                border: 2px solid #00FFFF; border-radius: 6px; 
                padding-top: 18px; margin-top: 6px; background: #111827;
            } 
            QGroupBox::title { background: #111827; padding: 2px 8px; }
        """)
        sf = QFormLayout()
        sf.setSpacing(12)
        sf.setContentsMargins(16, 24, 16, 16)
        sf.setLabelAlignment(Qt.AlignRight)
        
        # Style for form labels
        label_style = "font-size: 10pt; font-weight: bold; color: #E5E7EB;"
        input_style = "background: #1E293B; color: #F8FAFC; border: 1px solid #334155; border-radius: 4px; padding: 4px;"
        
        src_label = QLabel("Source:")
        src_label.setStyleSheet(label_style)
        self.src = QComboBox()
        self.src.setEditable(True)
        self.src.setStyleSheet(input_style)
        self.src.addItems(["SecurityLogs", "Prefetch", "ShimCache", "AmCache", "Registry", "SRUM", "MFT", "LNK", "USN", "ShellBags"])
        self.src.setFixedHeight(32)
        sf.addRow(src_label, self.src)
        
        fld_label = QLabel("Field:")
        fld_label.setStyleSheet(label_style)
        self.fld = QComboBox()
        self.fld.setEditable(True)
        self.fld.setStyleSheet(input_style)
        self.fld.addItems(["EventID", "Status", "Code", "Type", "Value", "path", "executable_name", "user"])
        self.fld.setFixedHeight(32)
        sf.addRow(fld_label, self.fld)
        
        tech_label = QLabel("Value:")
        tech_label.setStyleSheet(label_style)
        self.tech = QLineEdit()
        self.tech.setPlaceholderText("e.g., 4624, chrome.exe")
        self.tech.setStyleSheet(input_style)
        self.tech.setFixedHeight(32)
        sf.addRow(tech_label, self.tech)
        
        sem_label = QLabel("Semantic:")
        sem_label.setStyleSheet(label_style)
        self.sem = QLineEdit()
        self.sem.setPlaceholderText("e.g., User Login, Browser Activity")
        self.sem.setFixedHeight(32)
        self.sem.setStyleSheet("border: 2px solid #00FFFF; background: #1E293B; color: #F8FAFC; border-radius: 4px; padding: 4px;")
        sf.addRow(sem_label, self.sem)
        
        desc_label = QLabel("Description:")
        desc_label.setStyleSheet(label_style)
        self.desc = QLineEdit()
        self.desc.setPlaceholderText("Optional description")
        self.desc.setStyleSheet(input_style)
        self.desc.setFixedHeight(32)
        sf.addRow(desc_label, self.desc)
        
        self.simple_grp.setLayout(sf)
        layout.addWidget(self.simple_grp)
        
        # Advanced mode - scrollable with dark theme
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: #0B1220; border: none; }")
        
        self.adv_widget = QWidget()
        self.adv_widget.setStyleSheet("background: #0B1220;")
        av = QVBoxLayout(self.adv_widget)
        av.setSpacing(10)
        av.setContentsMargins(0, 0, 0, 0)
        
        # Rule output - professional styling
        rg = QGroupBox("Rule Output")
        rg.setStyleSheet("""
            QGroupBox { 
                font-size: 11pt; font-weight: bold; color: #00FFFF; 
                border: 2px solid #00FFFF; border-radius: 6px; 
                padding-top: 18px; margin-top: 6px; background: #111827;
            } 
            QGroupBox::title { background: #111827; padding: 2px 8px; }
        """)
        rf = QVBoxLayout()
        rf.setSpacing(10)
        rf.setContentsMargins(14, 22, 14, 14)
        
        # Row 1: Name and Semantic
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        adv_input_style = "background: #1E293B; color: #F8FAFC; border: 1px solid #334155; border-radius: 4px; padding: 4px;"
        name_lbl = QLabel("Name:")
        name_lbl.setStyleSheet("font-size: 10pt; font-weight: bold; color: #E5E7EB;")
        row1.addWidget(name_lbl)
        self.rname = QLineEdit()
        self.rname.setPlaceholderText("Rule name")
        self.rname.setFixedHeight(32)
        self.rname.setStyleSheet(adv_input_style)
        self.rname.textChanged.connect(self._preview)
        row1.addWidget(self.rname, 1)
        sem_lbl = QLabel("Semantic:")
        sem_lbl.setStyleSheet("font-size: 10pt; font-weight: bold; color: #E5E7EB;")
        row1.addWidget(sem_lbl)
        self.rsem = QLineEdit()
        self.rsem.setPlaceholderText("Output value")
        self.rsem.setFixedHeight(32)
        self.rsem.setStyleSheet("border: 2px solid #00FFFF; background: #1E293B; color: #F8FAFC; border-radius: 4px; padding: 4px;")
        self.rsem.textChanged.connect(self._preview)
        row1.addWidget(self.rsem, 1)
        rf.addLayout(row1)
        
        # Row 2: Category, Severity, Description
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        adv_combo_style = "background: #1E293B; color: #F8FAFC; border: 1px solid #334155; border-radius: 4px; padding: 4px;"
        cat_lbl = QLabel("Category:")
        cat_lbl.setStyleSheet("font-size: 10pt; font-weight: bold; color: #E5E7EB;")
        row2.addWidget(cat_lbl)
        self.cat = QComboBox()
        self.cat.setEditable(True)
        self.cat.setStyleSheet(adv_combo_style)
        self.cat.addItems(["", "authentication", "process_execution", "file_access", "user_activity"])
        self.cat.setFixedHeight(30)
        self.cat.setFixedWidth(150)
        row2.addWidget(self.cat)
        sev_lbl = QLabel("Severity:")
        sev_lbl.setStyleSheet("font-size: 10pt; font-weight: bold; color: #E5E7EB;")
        row2.addWidget(sev_lbl)
        self.sev = QComboBox()
        self.sev.setStyleSheet(adv_combo_style)
        self.sev.addItems(["info", "low", "medium", "high", "critical"])
        self.sev.setFixedHeight(30)
        self.sev.setFixedWidth(100)
        row2.addWidget(self.sev)
        desc_lbl = QLabel("Description:")
        desc_lbl.setStyleSheet("font-size: 10pt; font-weight: bold; color: #E5E7EB;")
        row2.addWidget(desc_lbl)
        self.rdesc = QLineEdit()
        self.rdesc.setPlaceholderText("Optional")
        self.rdesc.setStyleSheet(adv_input_style)
        self.rdesc.setFixedHeight(30)
        row2.addWidget(self.rdesc, 1)
        rf.addLayout(row2)
        
        rg.setLayout(rf)
        av.addWidget(rg)
        
        # Conditions table - COMPACT professional styling
        cg = QGroupBox("Conditions")
        cg.setStyleSheet("""
            QGroupBox { 
                font-size: 10pt; font-weight: bold; color: #3B82F6; 
                border: 2px solid #3B82F6; border-radius: 6px; 
                padding-top: 14px; margin-top: 4px; background: #111827;
            } 
            QGroupBox::title { background: #111827; padding: 2px 6px; }
        """)
        cl = QVBoxLayout()
        cl.setSpacing(4)
        cl.setContentsMargins(8, 18, 8, 8)
        
        self.tbl = QTableWidget()
        self.tbl.setColumnCount(5)
        self.tbl.setHorizontalHeaderLabels(["Feather", "Field", "Op", "Value", ""])
        self.tbl.setStyleSheet("""
            QTableWidget { background: #0F172A; border: 1px solid #334155; color: #F8FAFC; font-size: 9pt; gridline-color: #334155; }
            QTableWidget::item { padding: 2px; color: #F8FAFC; }
            QHeaderView::section { background: #1E293B; color: #00FFFF; padding: 3px; border: none; border-bottom: 1px solid #00FFFF; font-size: 9pt; font-weight: bold; }
        """)
        header = self.tbl.horizontalHeader()
        header.setMinimumSectionSize(14)  # Allow very small columns
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        # Set fixed column widths AFTER resize mode
        header.resizeSection(2, 40)  # Op column - compact
        header.resizeSection(4, 26)  # Delete button column - fits 20x20 button
        self.tbl.setMinimumHeight(100)
        self.tbl.setMaximumHeight(150)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.verticalHeader().setDefaultSectionSize(24)  # Compact row height
        cl.addWidget(self.tbl)
        
        # Add button row - visible
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        ab = QPushButton("+ Add")
        ab.setFixedSize(70, 26)
        ab.setStyleSheet("background: #10B981; color: white; border: none; border-radius: 4px; font-weight: bold; font-size: 10pt;")
        ab.clicked.connect(self._add_cond)
        btn_row.addWidget(ab)
        tip = QLabel("* = wildcard")
        tip.setStyleSheet("color: #94A3B8; font-size: 8pt; background: transparent;")
        btn_row.addWidget(tip)
        btn_row.addStretch()
        cl.addLayout(btn_row)
        cg.setLayout(cl)
        av.addWidget(cg)
        
        # Logic + Preview row - professional styling
        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        
        # Logic section
        lg = QGroupBox("Logic")
        lg.setStyleSheet("""
            QGroupBox { 
                font-size: 11pt; font-weight: bold; color: #F59E0B; 
                border: 2px solid #F59E0B; border-radius: 6px; 
                padding-top: 18px; margin-top: 6px; background: #111827;
            } 
            QGroupBox::title { background: #111827; padding: 2px 8px; }
        """)
        ll = QHBoxLayout()
        ll.setContentsMargins(14, 22, 14, 14)
        self.logic = QComboBox()
        self.logic.addItems(["AND", "OR"])
        self.logic.setFixedHeight(30)
        self.logic.setFixedWidth(80)
        self.logic.currentIndexChanged.connect(self._preview)
        ll.addWidget(self.logic)
        self.lind = QLabel("All match")
        self.lind.setStyleSheet("font-size: 8pt; color: #F59E0B;")
        self.logic.currentIndexChanged.connect(lambda: self.lind.setText("All match" if self.logic.currentIndex()==0 else "Any match"))
        ll.addWidget(self.lind)
        lg.setLayout(ll)
        lg.setFixedWidth(180)
        bottom.addWidget(lg)
        
        # Preview section
        pg = QGroupBox("Preview")
        pg.setStyleSheet("""
            QGroupBox { 
                font-size: 11pt; font-weight: bold; color: #8B5CF6; 
                border: 2px solid #8B5CF6; border-radius: 6px; 
                padding-top: 18px; margin-top: 6px; background: #111827;
            } 
            QGroupBox::title { background: #111827; padding: 2px 8px; }
        """)
        pl = QVBoxLayout()
        pl.setContentsMargins(14, 22, 14, 14)
        self.prev = QLabel()
        self.prev.setWordWrap(True)
        self.prev.setMinimumHeight(28)
        self.prev.setStyleSheet("background: #0F172A; border: 1px solid #334155; padding: 8px; color: #00FFFF; font-family: Consolas; font-size: 10pt; border-radius: 4px;")
        pl.addWidget(self.prev)
        pg.setLayout(pl)
        bottom.addWidget(pg, 1)
        
        av.addLayout(bottom)
        
        self.scroll.setWidget(self.adv_widget)
        layout.addWidget(self.scroll, 1)
        
        # Dialog buttons - professional styling
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.setStyleSheet("""
            QPushButton {
                min-width: 100px;
                min-height: 36px;
                font-size: 11pt;
                font-weight: bold;
                border-radius: 6px;
            }
        """)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)
        
        self._style()
        self._mode_changed()
        self.update()
    
    def _style(self):
        """Apply comprehensive dark theme styling to the dialog"""
        try:
            # Force clear any inherited styles
            self.setStyleSheet("")
            
            # Set palette for backup styling
            palette = QPalette()
            palette.setColor(QPalette.Window, QColor("#0B1220"))
            palette.setColor(QPalette.WindowText, QColor("#E5E7EB"))
            palette.setColor(QPalette.Base, QColor("#1E293B"))
            palette.setColor(QPalette.AlternateBase, QColor("#111827"))
            palette.setColor(QPalette.Text, QColor("#F8FAFC"))
            palette.setColor(QPalette.Button, QColor("#3B82F6"))
            palette.setColor(QPalette.ButtonText, QColor("white"))
            palette.setColor(QPalette.Highlight, QColor("#00FFFF"))
            palette.setColor(QPalette.HighlightedText, QColor("#0B1220"))
            self.setPalette(palette)
            
            # Main dialog stylesheet - comprehensive dark theme
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
                QGroupBox {
                    background-color: #111827;
                    border: 2px solid #1E3A5F;
                    border-radius: 6px;
                    color: #00FFFF;
                    font-weight: bold;
                    padding: 6px;
                    padding-top: 18px;
                    margin-top: 6px;
                    font-size: 11pt;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 2px 6px;
                    background: #111827;
                    color: #00FFFF;
                }
                QLineEdit {
                    background-color: #1E293B;
                    border: 1px solid #334155;
                    border-radius: 4px;
                    padding: 6px;
                    color: #F8FAFC;
                    font-size: 10pt;
                    min-height: 24px;
                }
                QLineEdit:focus {
                    border-color: #00FFFF;
                    border-width: 2px;
                }
                QLineEdit::placeholder {
                    color: #64748B;
                }
                QComboBox {
                    background-color: #1E293B;
                    border: 1px solid #334155;
                    border-radius: 4px;
                    padding: 6px;
                    color: #F8FAFC;
                    font-size: 10pt;
                    min-height: 24px;
                }
                QComboBox:focus {
                    border-color: #00FFFF;
                }
                QComboBox:editable {
                    background-color: #1E293B;
                    color: #F8FAFC;
                }
                QComboBox QLineEdit {
                    background-color: #1E293B;
                    color: #F8FAFC;
                    border: none;
                    padding: 4px;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 20px;
                    background: #334155;
                    border-top-right-radius: 4px;
                    border-bottom-right-radius: 4px;
                }
                QComboBox::down-arrow {
                    border-left: 5px solid transparent;
                    border-right: 5px solid transparent;
                    border-top: 6px solid #00FFFF;
                    margin-right: 5px;
                }
                QComboBox QAbstractItemView {
                    background-color: #1E293B;
                    color: #F8FAFC;
                    selection-background-color: #3B82F6;
                    selection-color: white;
                    border: 1px solid #334155;
                }
                QComboBox QAbstractItemView::item {
                    color: #F8FAFC;
                    padding: 6px;
                }
                QComboBox QAbstractItemView::item:selected {
                    background-color: #3B82F6;
                    color: white;
                }
                QComboBox QAbstractItemView QScrollBar:vertical {
                    background-color: #1E293B;
                    width: 12px;
                    border-radius: 6px;
                    margin: 2px;
                }
                QComboBox QAbstractItemView QScrollBar::handle:vertical {
                    background-color: #475569;
                    border-radius: 5px;
                    min-height: 20px;
                }
                QComboBox QAbstractItemView QScrollBar::handle:vertical:hover {
                    background-color: #00FFFF;
                }
                QComboBox QAbstractItemView QScrollBar::add-line:vertical,
                QComboBox QAbstractItemView QScrollBar::sub-line:vertical {
                    height: 0px;
                }
                QComboBox QAbstractItemView QScrollBar::add-page:vertical,
                QComboBox QAbstractItemView QScrollBar::sub-page:vertical {
                    background-color: #1E293B;
                }
                QRadioButton {
                    color: #F8FAFC;
                    font-size: 11pt;
                    font-weight: bold;
                    spacing: 8px;
                    background: transparent;
                }
                QRadioButton:checked {
                    color: #00FFFF;
                    font-weight: bold;
                }
                QRadioButton::indicator {
                    width: 18px;
                    height: 18px;
                    border-radius: 9px;
                    border: 2px solid #64748B;
                    background-color: #1E293B;
                }
                QRadioButton::indicator:checked {
                    background-color: #00FFFF;
                    border-color: #00FFFF;
                }
                QRadioButton::indicator:hover {
                    border-color: #00FFFF;
                }
                QPushButton {
                    background-color: #3B82F6;
                    color: white;
                    border: none;
                    border-radius: 5px;
                    padding: 8px 16px;
                    font-size: 10pt;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #2563EB;
                }
                QPushButton:pressed {
                    background-color: #1E40AF;
                }
                QPushButton:disabled {
                    background-color: #475569;
                    color: #94A3B8;
                }
                QDialogButtonBox QPushButton {
                    min-width: 100px;
                    min-height: 36px;
                    background-color: #3B82F6;
                    color: white;
                }
                QDialogButtonBox QPushButton:hover {
                    background-color: #2563EB;
                }
                QLabel {
                    color: #E5E7EB;
                    font-size: 10pt;
                    background: transparent;
                }
                QScrollArea {
                    background-color: #0B1220;
                    border: none;
                }
                QScrollBar:vertical {
                    background-color: #1E293B;
                    width: 14px;
                    border-radius: 7px;
                }
                QScrollBar::handle:vertical {
                    background-color: #475569;
                    border-radius: 7px;
                    min-height: 24px;
                }
                QScrollBar::handle:vertical:hover {
                    background-color: #64748B;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px;
                }
                QTableWidget {
                    background-color: #0F172A;
                    border: 1px solid #334155;
                    color: #F8FAFC;
                    font-size: 10pt;
                    gridline-color: #334155;
                }
                QTableWidget::item {
                    padding: 6px;
                    border: none;
                    color: #F8FAFC;
                }
                QTableWidget::item:selected {
                    background-color: #3B82F6;
                    color: white;
                }
                QHeaderView::section {
                    background-color: #1E293B;
                    color: #00FFFF;
                    padding: 8px;
                    border: none;
                    border-bottom: 2px solid #00FFFF;
                    font-size: 10pt;
                    font-weight: bold;
                }
                QTableCornerButton::section {
                    background-color: #1E293B;
                    border: none;
                }
                QFrame {
                    background-color: transparent;
                    color: #E5E7EB;
                }
            """
            
            self.setStyleSheet(dialog_style)
                
        except Exception as e:
            # Fallback to basic styling if advanced styling fails
            print(f"Warning: Failed to apply advanced styling: {e}")
            self.setStyleSheet("QDialog { background-color: #1E1E1E; color: white; }")
    
    def showEvent(self, event):
        """Override showEvent to ensure styling is applied when dialog is shown"""
        super().showEvent(event)
        # Reapply styling when dialog is shown
        self._style()
        # Force update
        self.update()
    
    def _mode_changed(self):
        adv = self.adv_radio.isChecked()
        self.simple_grp.setVisible(not adv)
        self.scroll.setVisible(adv)
        self.mode = 'advanced' if adv else 'simple'
        if adv: self._preview()
    
    def _add_cond(self):
        r = self.tbl.rowCount()
        self.tbl.insertRow(r)
        
        # COMPACT cell widget styling - smaller fonts, less padding
        combo_style = """
            QComboBox { 
                font-size: 9pt; padding: 2px; background: #1E293B; 
                border: 1px solid #334155; color: #F8FAFC; border-radius: 2px; 
                min-height: 20px; max-height: 20px;
            }
            QComboBox:editable { background: #1E293B; color: #F8FAFC; }
            QComboBox QLineEdit { background: #1E293B; color: #F8FAFC; border: none; font-size: 9pt; }
            QComboBox QAbstractItemView { background: #1E293B; color: #F8FAFC; border: 1px solid #334155; font-size: 9pt; }
            QComboBox QAbstractItemView::item { color: #F8FAFC; padding: 2px; }
            QComboBox QAbstractItemView::item:selected { background: #3B82F6; color: white; }
            QComboBox QAbstractItemView QScrollBar:vertical { background: #1E293B; width: 8px; }
            QComboBox QAbstractItemView QScrollBar::handle:vertical { background: #475569; border-radius: 3px; min-height: 16px; }
            QComboBox QAbstractItemView QScrollBar::handle:vertical:hover { background: #00FFFF; }
            QComboBox QAbstractItemView QScrollBar::add-line:vertical, QComboBox QAbstractItemView QScrollBar::sub-line:vertical { height: 0; }
            QComboBox QAbstractItemView QScrollBar::add-page:vertical, QComboBox QAbstractItemView QScrollBar::sub-page:vertical { background: #1E293B; }
        """
        
        f = QComboBox()
        f.setEditable(True)
        f.setStyleSheet(combo_style)
        f.setFixedHeight(22)
        # Complete Crow-Eye feather list
        default_feathers = [
            # Identity-level (for identity-based semantic mapping)
            "_identity",
            # Execution artifacts
            "Prefetch", "ShimCache", "AmCache", "AmCache_App", "AmCache_File", "AmCache_Shortcut",
            # User activity artifacts  
            "UserAssist", "RecentDocs", "OpenSaveMRU", "LastSaveMRU", "ShellBags", "TypedPaths",
            # Link files
            "LNK", "JumpLists", "AutomaticJumplist", "CustomJumplist",
            # System resources
            "SRUM", "SRUM_App", "SRUM_Network",
            # File system
            "MFT", "USN", "MFT_USN",
            # Registry
            "Registry", "BAM", "AppCompatFlags",
            # Event logs
            "Logs", "SecurityLogs", "SystemLogs", "ApplicationLogs", "PowerShellLogs",
            # Browser artifacts
            "BrowserHistory", "Downloads", "Cookies", "TypedURLs", "Cache",
            # Other
            "RecycleBin", "Startup", "Services", "TaskScheduler", "NetworkConnections"
        ]
        f.addItems(self.available_feathers if self.available_feathers else default_feathers)
        f.currentTextChanged.connect(self._preview)
        self.tbl.setCellWidget(r, 0, f)
        
        fd = QComboBox()
        fd.setEditable(True)
        fd.setStyleSheet(combo_style)
        fd.setFixedHeight(22)
        fd.addItems(["identity_value", "identity_type", "path", "name", "executable_name", "EventID", "user", "timestamp", "source", "destination", "hash", "size", "command_line"])
        fd.currentTextChanged.connect(self._preview)
        self.tbl.setCellWidget(r, 1, fd)
        
        o = QComboBox()
        o.setStyleSheet(combo_style)
        o.setFixedHeight(22)
        o.addItems(["=", "~", "*"])
        o.currentIndexChanged.connect(self._preview)
        self.tbl.setCellWidget(r, 2, o)
        
        v = QLineEdit()
        v.setStyleSheet("font-size: 9pt; padding: 2px; min-height: 18px; max-height: 20px; background: #1E293B; border: 1px solid #334155; color: #F8FAFC; border-radius: 2px;")
        v.setFixedHeight(22)
        v.textChanged.connect(self._preview)
        self.tbl.setCellWidget(r, 3, v)
        
        # Delete button - visible red X
        x = QPushButton("✕")
        x.setStyleSheet("background: #EF4444; color: white; border: none; font-size: 10pt; font-weight: bold; border-radius: 3px; padding: 0px;")
        x.setFixedSize(20, 20)
        x.clicked.connect(lambda: self._rm_cond(r))
        self.tbl.setCellWidget(r, 4, x)
        self._preview()
    
    def _rm_cond(self, r):
        s = self.sender()
        for i in range(self.tbl.rowCount()):
            if self.tbl.cellWidget(i, 4) == s:
                self.tbl.removeRow(i)
                break
        self._preview()
    
    def _preview(self):
        if self.mode != 'advanced': return
        n = self.rname.text() or "[Name]"
        s = self.rsem.text() or "[Semantic]"
        l = "AND" if self.logic.currentIndex() == 0 else "OR"
        c = []
        for i in range(self.tbl.rowCount()):
            f = self.tbl.cellWidget(i, 0)
            fd = self.tbl.cellWidget(i, 1)
            o = self.tbl.cellWidget(i, 2)
            v = self.tbl.cellWidget(i, 3)
            if f and fd:
                c.append(f"{f.currentText()}.{fd.currentText()}{o.currentText() if o else '='}{v.text() if v else '*'}")
        self.prev.setText(f"IF {f' {l} '.join(c)} → {s}" if c else f"'{n}' → {s}")
    
    def load_mapping(self):
        if not self.mapping: return
        self.src.setCurrentText(self.mapping.get('source', ''))
        self.fld.setCurrentText(self.mapping.get('field', ''))
        self.tech.setText(self.mapping.get('technical_value', ''))
        self.sem.setText(self.mapping.get('semantic_value', ''))
        self.desc.setText(self.mapping.get('description', ''))
        
        self.rname.setText(self.mapping.get('name', ''))
        self.rsem.setText(self.mapping.get('semantic_value', ''))
        self.rdesc.setText(self.mapping.get('description', ''))
        self.cat.setCurrentText(self.mapping.get('category', ''))
        idx = self.sev.findText(self.mapping.get('severity', 'info'))
        if idx >= 0: self.sev.setCurrentIndex(idx)
        self.logic.setCurrentIndex(0 if self.mapping.get('logic_operator', 'AND') == 'AND' else 1)
        
        for cd in self.mapping.get('conditions', []):
            self._add_cond()
            r = self.tbl.rowCount() - 1
            if self.tbl.cellWidget(r, 0): self.tbl.cellWidget(r, 0).setCurrentText(cd.get('feather_id', ''))
            if self.tbl.cellWidget(r, 1): self.tbl.cellWidget(r, 1).setCurrentText(cd.get('field_name', ''))
            if self.tbl.cellWidget(r, 2):
                om = {'equals': '=', 'contains': '~', 'wildcard': '*', 'regex': '~'}
                self.tbl.cellWidget(r, 2).setCurrentText(om.get(cd.get('operator', 'equals'), '='))
            if self.tbl.cellWidget(r, 3): self.tbl.cellWidget(r, 3).setText(cd.get('value', ''))
        self._preview()
    
    def _accept(self):
        if self.mode == 'advanced':
            if not self.rname.text().strip():
                QMessageBox.warning(self, "Error", "Name required")
                return
            if not self.rsem.text().strip():
                QMessageBox.warning(self, "Error", "Semantic required")
                return
            if self.tbl.rowCount() == 0:
                QMessageBox.warning(self, "Error", "Add condition")
                return
        else:
            if not self.src.currentText().strip() or not self.fld.currentText().strip() or not self.tech.text().strip() or not self.sem.text().strip():
                QMessageBox.warning(self, "Error", "Fill all fields")
                return
        self.accept()
    
    def get_mapping(self):
        sc = self.mapping.get('scope', 'global') if self.mapping else ('wing' if hasattr(self, 'wing_radio') and self.wing_radio.isChecked() else 'global')
        
        if self.mode == 'advanced':
            conds = []
            for i in range(self.tbl.rowCount()):
                f = self.tbl.cellWidget(i, 0)
                fd = self.tbl.cellWidget(i, 1)
                o = self.tbl.cellWidget(i, 2)
                v = self.tbl.cellWidget(i, 3)
                if f and fd:
                    om = {'=': 'equals', '~': 'contains', '*': 'wildcard'}
                    conds.append({'feather_id': f.currentText(), 'field_name': fd.currentText(), 'value': v.text() if v else '*', 'operator': om.get(o.currentText() if o else '=', 'equals')})
            logic_op = "AND" if self.logic.currentIndex() == 0 else "OR"
            return {'rule_id': self.mapping.get('rule_id', str(uuid.uuid4())), 'name': self.rname.text(), 'semantic_value': self.rsem.text(), 'description': self.rdesc.text(), 'conditions': conds, 'logic_operator': logic_op, 'scope': sc, 'category': self.cat.currentText(), 'severity': self.sev.currentText(), 'confidence': 1.0, 'mode': 'advanced'}
        return {'source': self.src.currentText(), 'field': self.fld.currentText(), 'technical_value': self.tech.text(), 'semantic_value': self.sem.text(), 'description': self.desc.text(), 'scope': sc, 'mode': 'simple'}
    
    def get_rule(self):
        d = self.get_mapping()
        if d.get('mode') != 'advanced': return None
        return SemanticRule(rule_id=d['rule_id'], name=d['name'], semantic_value=d['semantic_value'], description=d['description'], conditions=[SemanticCondition(feather_id=c['feather_id'], field_name=c['field_name'], value=c['value'], operator=c['operator']) for c in d['conditions']], logic_operator=d['logic_operator'], scope=d['scope'], category=d['category'], severity=d['severity'], confidence=d['confidence'])
    
    def get_rule_data(self):
        return self.get_mapping()
