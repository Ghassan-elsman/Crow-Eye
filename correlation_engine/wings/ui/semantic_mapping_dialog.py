"""
Semantic Mapping Dialog - Ultra Compact Version
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QDialogButtonBox, QFormLayout, QGroupBox, QMessageBox,
    QComboBox, QRadioButton, QButtonGroup, QTableWidget,
    QPushButton, QHeaderView, QWidget, QScrollArea, QFrame,
    QCheckBox, QSpinBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPalette, QColor, QFont
from ...config.semantic_mapping import SemanticCondition, SemanticRule
import uuid


class SemanticMappingDialog(QDialog):
    # Condition operator palette: (display label, canonical engine operator).
    # Stored as itemData so we never round-trip through fragile symbol maps.
    OP_ITEMS = [
        ("=", "equals"), ("contains", "contains"), ("regex", "regex"),
        ("≠", "not_equals"), (">", "greater_than"), ("<", "less_than"),
        ("≥", "greater_equal"), ("≤", "less_equal"), ("*", "wildcard"),
    ]
    # Basic authoring exposes only the original operators (+ regex); advanced
    # authoring exposes the full comparison/negation set.
    OP_BASIC = {"equals", "contains", "regex", "wildcard"}
    RULE_TYPES = ["match", "absence", "sequence", "threshold"]

    def __init__(self, parent=None, mapping=None, scope='global', wing_id=None,
                 available_feathers=None, mode='simple', allow_advanced=False):
        super().__init__(parent)

        # Set window flags to ensure independent styling
        self.setWindowFlags(self.windowFlags() | Qt.Window)

        self.mapping = mapping or {}
        self.scope = scope
        self.wing_id = wing_id
        self.available_feathers = available_feathers or []

        # Advanced rule authoring (rule_type/absence/sequence/threshold, nested
        # groups, cross-feather, negation, ATT&CK). Auto-enabled when editing a
        # mapping that already uses any advanced capability, so such rules stay
        # fully editable regardless of how the dialog was opened.
        mapping_advanced = self._mapping_is_advanced(self.mapping)
        self.allow_advanced = bool(allow_advanced) or mapping_advanced

        # A mapping with flat conditions OR any advanced capability (which may
        # have empty ``conditions`` — e.g. absence rules) opens in advanced mode.
        self.mode = mode
        if self.mapping and (self.mapping.get('conditions') or mapping_advanced):
            self.mode = 'advanced'

        self.init_ui()
        self.load_mapping()

    @staticmethod
    def _mapping_is_advanced(mapping) -> bool:
        """Detect whether a rule dict uses any Identity-engine-only capability."""
        if not isinstance(mapping, dict):
            return False
        if str(mapping.get('rule_type', 'match')).lower() != 'match':
            return True
        if mapping.get('condition_groups') or mapping.get('technique_id') or mapping.get('tactic'):
            return True
        for cond in mapping.get('conditions', []) or []:
            if isinstance(cond, dict) and (cond.get('negate') or cond.get('compare_to_feather')):
                return True
            if isinstance(cond, dict) and cond.get('operator') not in (None, 'equals', 'contains', 'regex', 'wildcard'):
                return True
        return False
    
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

        # Advanced: rule-type selector + ATT&CK + Identity-engine-only note.
        if self.allow_advanced:
            self._build_rule_type_bar(av)

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
        
        self.tbl = self._make_cond_table()
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
        self.match_group = cg  # hidden for non-match rule types

        # Advanced: nested condition groups + absence/threshold/sequence editors.
        if self.allow_advanced:
            self._build_spec_editors(av)

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
        self.logic_group = lg  # hidden for non-match rule types
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
        if self.allow_advanced:
            self._rule_type_changed()
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

    # ------------------------------------------------------------------
    # Reusable condition-table machinery (shared by match / absence /
    # threshold / sequence editors and nested groups)
    # ------------------------------------------------------------------
    _CELL_COMBO_STYLE = (
        "QComboBox { font-size: 9pt; padding: 2px; background: #1E293B; "
        "border: 1px solid #334155; color: #F8FAFC; border-radius: 2px; "
        "min-height: 20px; max-height: 20px; }"
        "QComboBox:editable { background: #1E293B; color: #F8FAFC; }"
        "QComboBox QLineEdit { background: #1E293B; color: #F8FAFC; border: none; font-size: 9pt; }"
        "QComboBox QAbstractItemView { background: #1E293B; color: #F8FAFC; border: 1px solid #334155; font-size: 9pt; }"
        "QComboBox QAbstractItemView::item { color: #F8FAFC; padding: 2px; }"
        "QComboBox QAbstractItemView::item:selected { background: #3B82F6; color: white; }"
    )
    _CELL_EDIT_STYLE = (
        "font-size: 9pt; padding: 2px; min-height: 18px; max-height: 20px; "
        "background: #1E293B; border: 1px solid #334155; color: #F8FAFC; border-radius: 2px;"
    )
    _DEFAULT_FEATHERS = [
        "_identity", "Prefetch", "ShimCache", "AmCache", "AmCache_App", "AmCache_File",
        "UserAssist", "RecentDocs", "ShellBags", "TypedPaths", "LNK", "JumpLists",
        "AutomaticJumplist", "SRUM", "SRUM_App", "SRUM_Network", "MFT", "USN", "MFT_USN",
        "Registry", "BAM", "Logs", "SecurityLogs", "SystemLogs", "ApplicationLogs",
        "PowerShellLogs", "BrowserHistory", "RecycleBin", "Startup", "Services",
        "TaskScheduler", "NetworkConnections",
    ]
    _DEFAULT_FIELDS = [
        "identity_value", "identity_type", "path", "name", "executable_name", "EventID",
        "user", "timestamp", "source", "destination", "hash", "size", "command_line",
        "reason", "si_created", "fn_created", "target_path",
    ]
    _TABLE_STYLE = (
        "QTableWidget { background: #0F172A; border: 1px solid #334155; color: #F8FAFC; font-size: 9pt; gridline-color: #334155; }"
        "QTableWidget::item { padding: 2px; color: #F8FAFC; }"
        "QHeaderView::section { background: #1E293B; color: #00FFFF; padding: 3px; border: none; border-bottom: 1px solid #00FFFF; font-size: 9pt; font-weight: bold; }"
    )

    def _make_cond_table(self, advanced=None):
        """Build a condition table. Advanced tables add Negate + Compare→ columns."""
        adv = self.allow_advanced if advanced is None else advanced
        tbl = QTableWidget()
        if adv:
            cols = ["Feather", "Field", "Op", "Value", "Neg", "Compare→ (feather.field)", ""]
        else:
            cols = ["Feather", "Field", "Op", "Value", ""]
        tbl.setColumnCount(len(cols))
        tbl.setHorizontalHeaderLabels(cols)
        tbl.setStyleSheet(self._TABLE_STYLE)
        h = tbl.horizontalHeader()
        h.setMinimumSectionSize(14)
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.Fixed)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        last = tbl.columnCount() - 1
        if adv:
            h.setSectionResizeMode(4, QHeaderView.Fixed)
            h.setSectionResizeMode(5, QHeaderView.Stretch)
            h.setSectionResizeMode(last, QHeaderView.Fixed)
            h.resizeSection(2, 78)
            h.resizeSection(4, 34)
        else:
            h.setSectionResizeMode(last, QHeaderView.Fixed)
            h.resizeSection(2, 42)
        h.resizeSection(last, 26)
        tbl.setMinimumHeight(90)
        tbl.setMaximumHeight(150)
        tbl.verticalHeader().setVisible(False)
        tbl.verticalHeader().setDefaultSectionSize(24)
        return tbl

    def _add_cond_row(self, tbl):
        r = tbl.rowCount()
        tbl.insertRow(r)
        adv = tbl.columnCount() >= 7

        f = QComboBox(); f.setEditable(True); f.setStyleSheet(self._CELL_COMBO_STYLE); f.setFixedHeight(22)
        f.addItems(self.available_feathers if self.available_feathers else self._DEFAULT_FEATHERS)
        f.currentTextChanged.connect(self._preview)
        tbl.setCellWidget(r, 0, f)

        fd = QComboBox(); fd.setEditable(True); fd.setStyleSheet(self._CELL_COMBO_STYLE); fd.setFixedHeight(22)
        fd.addItems(self._DEFAULT_FIELDS)
        fd.currentTextChanged.connect(self._preview)
        tbl.setCellWidget(r, 1, fd)

        o = QComboBox(); o.setStyleSheet(self._CELL_COMBO_STYLE); o.setFixedHeight(22)
        for label, name in self.OP_ITEMS:
            if adv or name in self.OP_BASIC:
                o.addItem(label, name)
        o.currentIndexChanged.connect(self._preview)
        tbl.setCellWidget(r, 2, o)

        v = QLineEdit(); v.setStyleSheet(self._CELL_EDIT_STYLE); v.setFixedHeight(22)
        v.textChanged.connect(self._preview)
        tbl.setCellWidget(r, 3, v)

        del_col = 4
        if adv:
            neg = QCheckBox(); neg.setToolTip("Negate — matches when this condition does NOT hold")
            neg.stateChanged.connect(self._preview)
            wrap = QWidget(); wl = QHBoxLayout(wrap); wl.setContentsMargins(0, 0, 0, 0)
            wl.setAlignment(Qt.AlignCenter); wl.addWidget(neg)
            tbl.setCellWidget(r, 4, wrap)
            cmp = QLineEdit(); cmp.setPlaceholderText("blank = literal value")
            cmp.setStyleSheet(self._CELL_EDIT_STYLE); cmp.setFixedHeight(22)
            cmp.setToolTip("Cross-feather compare: feather.field (blank = compare to Value)")
            cmp.textChanged.connect(self._preview)
            tbl.setCellWidget(r, 5, cmp)
            del_col = 6

        from ...gui.crow_eye_icons import CrowEyeIcons
        x = QPushButton(); x.setIcon(CrowEyeIcons.delete()); x.setToolTip("Remove condition")
        x.setStyleSheet("background: #EF4444; color: white; border: none; font-size: 10pt; font-weight: bold; border-radius: 3px; padding: 0px;")
        x.setFixedSize(20, 20)
        x.clicked.connect(lambda _=None, t=tbl, b=x: self._rm_cond_row(t, b))
        tbl.setCellWidget(r, del_col, x)
        self._preview()

    def _rm_cond_row(self, tbl, btn):
        last = tbl.columnCount() - 1
        for i in range(tbl.rowCount()):
            if tbl.cellWidget(i, last) is btn:
                tbl.removeRow(i)
                break
        self._preview()

    def _read_conds(self, tbl):
        """Read a condition table into a list of condition dicts."""
        adv = tbl.columnCount() >= 7
        out = []
        for i in range(tbl.rowCount()):
            f = tbl.cellWidget(i, 0); fd = tbl.cellWidget(i, 1)
            o = tbl.cellWidget(i, 2); v = tbl.cellWidget(i, 3)
            if not (f and fd):
                continue
            feather = f.currentText().strip()
            field = fd.currentText().strip()
            if not feather or not field:
                continue
            op = (o.currentData() if o and o.currentData() else 'equals')
            value = (v.text() if v else '')
            if op == 'wildcard' and not value:
                value = '*'
            cond = {'feather_id': feather, 'field_name': field, 'value': value, 'operator': op}
            if adv:
                negw = tbl.cellWidget(i, 4)
                neg = negw.findChild(QCheckBox) if negw else None
                if neg and neg.isChecked():
                    cond['negate'] = True
                cmp = tbl.cellWidget(i, 5)
                cmptext = cmp.text().strip() if cmp else ''
                if cmptext:
                    if '.' in cmptext:
                        cf, cff = cmptext.split('.', 1)
                    else:
                        cf, cff = feather, cmptext
                    cond['compare_to_feather'] = cf.strip()
                    cond['compare_to_field'] = cff.strip()
            out.append(cond)
        return out

    def _load_conds(self, tbl, conds):
        adv = tbl.columnCount() >= 7
        for cd in conds or []:
            self._add_cond_row(tbl)
            r = tbl.rowCount() - 1
            if tbl.cellWidget(r, 0): tbl.cellWidget(r, 0).setCurrentText(cd.get('feather_id', ''))
            if tbl.cellWidget(r, 1): tbl.cellWidget(r, 1).setCurrentText(cd.get('field_name', ''))
            o = tbl.cellWidget(r, 2)
            if o:
                idx = o.findData(cd.get('operator', 'equals'))
                o.setCurrentIndex(idx if idx >= 0 else 0)
            if tbl.cellWidget(r, 3): tbl.cellWidget(r, 3).setText(str(cd.get('value', '')))
            if adv:
                negw = tbl.cellWidget(r, 4)
                neg = negw.findChild(QCheckBox) if negw else None
                if neg: neg.setChecked(bool(cd.get('negate')))
                cmp = tbl.cellWidget(r, 5)
                if cmp and cd.get('compare_to_feather'):
                    cmp.setText(f"{cd.get('compare_to_feather')}.{cd.get('compare_to_field', '')}")

    def _cond_table_block(self, title, min_h=90):
        """A titled condition table + '+ Add' button. Returns (groupbox, table)."""
        box = QGroupBox(title)
        lay = QVBoxLayout(); lay.setSpacing(4); lay.setContentsMargins(8, 16, 8, 8)
        tbl = self._make_cond_table()
        tbl.setMinimumHeight(min_h)
        lay.addWidget(tbl)
        ab = QPushButton("+ Add"); ab.setFixedSize(70, 24)
        ab.setStyleSheet("background: #10B981; color: white; border: none; border-radius: 4px; font-weight: bold; font-size: 9pt;")
        ab.clicked.connect(lambda _=None, t=tbl: self._add_cond_row(t))
        row = QHBoxLayout(); row.addWidget(ab); row.addStretch(); lay.addLayout(row)
        box.setLayout(lay)
        return box, tbl

    # ------------------------------------------------------------------
    # Advanced rule-type + ATT&CK bar
    # ------------------------------------------------------------------
    def _build_rule_type_bar(self, av):
        bar = QGroupBox("Advanced Rule")
        lay = QVBoxLayout(); lay.setContentsMargins(12, 18, 12, 12); lay.setSpacing(8)

        top = QHBoxLayout(); top.setSpacing(10)
        rt_lbl = QLabel("Rule Type:"); rt_lbl.setStyleSheet("font-weight: bold; color: #E5E7EB;")
        top.addWidget(rt_lbl)
        self.rule_type_combo = QComboBox()
        self.rule_type_combo.addItems(self.RULE_TYPES)
        self.rule_type_combo.setFixedWidth(150)
        self.rule_type_combo.currentIndexChanged.connect(self._rule_type_changed)
        top.addWidget(self.rule_type_combo)
        top.addSpacing(14)
        tech_lbl = QLabel("ATT&CK IDs:"); tech_lbl.setStyleSheet("font-weight: bold; color: #E5E7EB;")
        top.addWidget(tech_lbl)
        self.tech_ids = QLineEdit(); self.tech_ids.setPlaceholderText("e.g. T1070.004, T1562.001")
        self.tech_ids.setFixedHeight(28)
        top.addWidget(self.tech_ids, 1)
        tac_lbl = QLabel("Tactic:"); tac_lbl.setStyleSheet("font-weight: bold; color: #E5E7EB;")
        top.addWidget(tac_lbl)
        self.tactics = QLineEdit(); self.tactics.setPlaceholderText("e.g. defense-evasion")
        self.tactics.setFixedHeight(28)
        top.addWidget(self.tactics, 1)
        lay.addLayout(top)

        from ...gui.crow_eye_icons import status_label_html
        note = QLabel()
        note.setTextFormat(Qt.RichText)
        note.setText(status_label_html(
            "bolt",
            "Advanced rules (absence / sequence / threshold / nested / cross-feather) "
            "run on the Identity-Based engine only. Running this wing on the Time-Window "
            "engine will prompt you to switch.",
            size_px=12,
        ))
        note.setWordWrap(True)
        note.setStyleSheet("color: #FBBF24; font-size: 9pt; background: transparent;")
        lay.addWidget(note)

        bar.setLayout(lay)
        av.addWidget(bar)

    # ------------------------------------------------------------------
    # Spec editors: nested groups + absence + threshold + sequence
    # ------------------------------------------------------------------
    def _build_spec_editors(self, av):
        # Nested condition groups (match rules only)
        self.groups_group = QGroupBox("Condition Groups  (optional nested (A AND B) OR (C AND D))")
        gl = QVBoxLayout(); gl.setContentsMargins(10, 16, 10, 10); gl.setSpacing(6)
        self.groups_layout = QVBoxLayout(); self.groups_layout.setSpacing(6)
        self.group_widgets = []  # list of (frame, logic_combo, table)
        gl.addLayout(self.groups_layout)
        add_grp = QPushButton("+ Add Group"); add_grp.setFixedHeight(24)
        add_grp.setStyleSheet("background: #6366F1; color: white; border: none; border-radius: 4px; font-weight: bold; font-size: 9pt;")
        add_grp.clicked.connect(lambda: self._add_group())
        gl.addWidget(add_grp, alignment=Qt.AlignLeft)
        self.groups_group.setLayout(gl)
        av.addWidget(self.groups_group)

        # Absence
        self.absence_group = QGroupBox("Absence Spec  (fire when expected present but required absent)")
        al = QVBoxLayout(); al.setContentsMargins(10, 16, 10, 10); al.setSpacing(6)
        exp_box, self.expect_tbl = self._cond_table_block("Expect Present")
        abs_box, self.absent_tbl = self._cond_table_block("Require Absent")
        al.addWidget(exp_box); al.addWidget(abs_box)
        wrow = QHBoxLayout()
        wl = QLabel("Within minutes (0 = whole window):"); wl.setStyleSheet("color: #E5E7EB;")
        wrow.addWidget(wl)
        self.abs_within = QSpinBox(); self.abs_within.setRange(0, 100000); self.abs_within.setValue(0)
        self.abs_within.setFixedWidth(90); wrow.addWidget(self.abs_within); wrow.addStretch()
        al.addLayout(wrow)
        self.absence_group.setLayout(al)
        av.addWidget(self.absence_group)

        # Threshold
        self.threshold_group = QGroupBox("Threshold Spec  (fire on >= N occurrences)")
        tl = QVBoxLayout(); tl.setContentsMargins(10, 16, 10, 10); tl.setSpacing(6)
        thr_box, self.thr_tbl = self._cond_table_block("Match Condition(s)")
        tl.addWidget(thr_box)
        trow = QHBoxLayout()
        mcl = QLabel("Min count:"); mcl.setStyleSheet("color: #E5E7EB;"); trow.addWidget(mcl)
        self.thr_min = QSpinBox(); self.thr_min.setRange(1, 1000000); self.thr_min.setValue(5)
        self.thr_min.setFixedWidth(80); trow.addWidget(self.thr_min)
        twl = QLabel("Within minutes:"); twl.setStyleSheet("color: #E5E7EB;"); trow.addWidget(twl)
        self.thr_within = QSpinBox(); self.thr_within.setRange(0, 100000); self.thr_within.setValue(0)
        self.thr_within.setFixedWidth(90); trow.addWidget(self.thr_within)
        gbl = QLabel("Group by field:"); gbl.setStyleSheet("color: #E5E7EB;"); trow.addWidget(gbl)
        self.thr_group_by = QLineEdit(); self.thr_group_by.setPlaceholderText("optional, e.g. user")
        self.thr_group_by.setFixedHeight(26); trow.addWidget(self.thr_group_by, 1)
        tl.addLayout(trow)
        self.threshold_group.setLayout(tl)
        av.addWidget(self.threshold_group)

        # Sequence
        self.sequence_group = QGroupBox("Sequence Spec  (ordered steps, top → bottom)")
        sl = QVBoxLayout(); sl.setContentsMargins(10, 16, 10, 10); sl.setSpacing(6)
        seq_box, self.seq_tbl = self._cond_table_block("Steps (in order)")
        sl.addWidget(seq_box)
        srow = QHBoxLayout()
        sgl = QLabel("Max gap minutes between steps:"); sgl.setStyleSheet("color: #E5E7EB;")
        srow.addWidget(sgl)
        self.seq_gap = QSpinBox(); self.seq_gap.setRange(0, 100000); self.seq_gap.setValue(30)
        self.seq_gap.setFixedWidth(90); srow.addWidget(self.seq_gap); srow.addStretch()
        sl.addLayout(srow)
        # Cross-feather join: the matching record of every step must share these
        # field values (e.g. same host/user) — a real correlation, not just
        # time-coincidence. Steps may each target a different feather.
        jrow = QHBoxLayout()
        jl = QLabel("Join on fields (same across steps):"); jl.setStyleSheet("color: #E5E7EB;")
        jrow.addWidget(jl)
        self.seq_join = QLineEdit(); self.seq_join.setPlaceholderText("optional, e.g. host, user")
        self.seq_join.setFixedHeight(26); jrow.addWidget(self.seq_join, 1)
        sl.addLayout(jrow)
        self.seq_same_identity = QCheckBox("Restrict to the same identity")
        self.seq_same_identity.setStyleSheet("color: #E5E7EB;")
        self.seq_same_identity.setToolTip(
            "Sequences are already evaluated within one correlated identity; this flag records "
            "that intent explicitly. Use 'Join on fields' for finer cross-feather binding.")
        sl.addWidget(self.seq_same_identity)
        self.sequence_group.setLayout(sl)
        av.addWidget(self.sequence_group)

    def _add_group(self, logic='AND', conditions=None):
        frame = QFrame()
        frame.setStyleSheet("QFrame { border: 1px solid #334155; border-radius: 4px; background: #0F172A; }")
        fl = QVBoxLayout(frame); fl.setContentsMargins(6, 6, 6, 6); fl.setSpacing(4)
        hdr = QHBoxLayout()
        lc = QComboBox(); lc.addItems(["AND", "OR"]); lc.setFixedWidth(70)
        lc.setCurrentText(logic if logic in ("AND", "OR") else "AND")
        hdr.addWidget(QLabel("Group logic:")); hdr.addWidget(lc); hdr.addStretch()
        rm = QPushButton("Remove group"); rm.setFixedHeight(22)
        rm.setStyleSheet("background: #EF4444; color: white; border: none; border-radius: 3px; font-size: 9pt; padding: 0 8px;")
        hdr.addWidget(rm)
        fl.addLayout(hdr)
        tbl = self._make_cond_table(advanced=False)
        tbl.setMaximumHeight(110)
        fl.addWidget(tbl)
        ab = QPushButton("+ Add condition"); ab.setFixedHeight(22)
        ab.setStyleSheet("background: #10B981; color: white; border: none; border-radius: 3px; font-size: 9pt; padding: 0 8px;")
        ab.clicked.connect(lambda _=None, t=tbl: self._add_cond_row(t))
        fl.addWidget(ab, alignment=Qt.AlignLeft)
        self.groups_layout.addWidget(frame)
        entry = (frame, lc, tbl)
        self.group_widgets.append(entry)
        rm.clicked.connect(lambda _=None, e=entry: self._remove_group(e))
        for cd in (conditions or []):
            self._load_conds(tbl, [cd])
        return entry

    def _remove_group(self, entry):
        frame, lc, tbl = entry
        if entry in self.group_widgets:
            self.group_widgets.remove(entry)
        frame.setParent(None)
        self._preview()

    def _rule_type_changed(self):
        if not hasattr(self, 'rule_type_combo'):
            return
        rt = self.rule_type_combo.currentText()
        is_match = (rt == 'match')
        if hasattr(self, 'match_group'): self.match_group.setVisible(is_match)
        if hasattr(self, 'logic_group'): self.logic_group.setVisible(is_match)
        if hasattr(self, 'groups_group'): self.groups_group.setVisible(is_match)
        self.absence_group.setVisible(rt == 'absence')
        self.threshold_group.setVisible(rt == 'threshold')
        self.sequence_group.setVisible(rt == 'sequence')
        self._preview()
    
    def _add_cond(self):
        """Add a row to the main match conditions table (+ Add button)."""
        self._add_cond_row(self.tbl)

    def _preview(self):
        if self.mode != 'advanced':
            return
        if not hasattr(self, 'prev'):
            return
        n = self.rname.text() or "[Name]"
        s = self.rsem.text() or "[Semantic]"
        rt = self.rule_type_combo.currentText() if hasattr(self, 'rule_type_combo') else 'match'
        if rt != 'match':
            self.prev.setText(f"[{rt}] '{n}' → {s}")
            return
        l = "AND" if self.logic.currentIndex() == 0 else "OR"
        c = []
        for i in range(self.tbl.rowCount()):
            f = self.tbl.cellWidget(i, 0)
            fd = self.tbl.cellWidget(i, 1)
            o = self.tbl.cellWidget(i, 2)
            v = self.tbl.cellWidget(i, 3)
            if f and fd:
                op = o.currentText() if o else '='
                neg = ''
                if self.tbl.columnCount() >= 7:
                    negw = self.tbl.cellWidget(i, 4)
                    chk = negw.findChild(QCheckBox) if negw else None
                    if chk and chk.isChecked():
                        neg = 'NOT '
                c.append(f"{neg}{f.currentText()}.{fd.currentText()}{op}{v.text() if v else '*'}")
        grp = len(self.group_widgets) if hasattr(self, 'group_widgets') else 0
        suffix = f"  (+{grp} group{'s' if grp != 1 else ''})" if grp else ""
        self.prev.setText(f"IF {f' {l} '.join(c)} → {s}{suffix}" if c else f"'{n}' → {s}")
    
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

        # Advanced fields (rule_type / ATT&CK / specs / nested groups)
        rule_type = str(self.mapping.get('rule_type', 'match')).lower()
        if hasattr(self, 'rule_type_combo'):
            i = self.rule_type_combo.findText(rule_type)
            self.rule_type_combo.setCurrentIndex(i if i >= 0 else 0)
            self.tech_ids.setText(', '.join(self.mapping.get('technique_id', []) or []))
            self.tactics.setText(', '.join(self.mapping.get('tactic', []) or []))

        # Flat match conditions
        self._load_conds(self.tbl, self.mapping.get('conditions', []))

        # Nested groups
        if hasattr(self, 'group_widgets'):
            for grp in self.mapping.get('condition_groups', []) or []:
                self._add_group(grp.get('logic_operator', 'AND'), grp.get('conditions', []))

        # Rule-type spec blocks
        if hasattr(self, 'rule_type_combo'):
            absence = self.mapping.get('absence') or {}
            if absence:
                self._load_conds(self.expect_tbl, absence.get('expect_present', []))
                self._load_conds(self.absent_tbl, absence.get('require_absent', []))
                self.abs_within.setValue(int(absence.get('within_minutes') or 0))
            threshold = self.mapping.get('threshold') or {}
            if threshold:
                thr_conds = threshold.get('conditions')
                if not thr_conds and threshold.get('condition'):
                    thr_conds = [threshold['condition']]
                self._load_conds(self.thr_tbl, thr_conds or [])
                self.thr_min.setValue(int(threshold.get('min_count') or 1))
                self.thr_within.setValue(int(threshold.get('within_minutes') or 0))
                self.thr_group_by.setText(threshold.get('group_by') or '')
            sequence = self.mapping.get('sequence') or {}
            if sequence:
                # Remember the original spec so grouped/multi-condition steps
                # (which the flat table can't represent) survive an unedited save.
                self._loaded_sequence = sequence
                self._load_conds(self.seq_tbl, self._flatten_seq_steps(sequence.get('steps', [])))
                self.seq_gap.setValue(int(sequence.get('max_gap_minutes') or 0))
                jf = sequence.get('join_fields') or []
                if isinstance(jf, str):
                    jf = [jf]
                self.seq_join.setText(', '.join(str(x) for x in jf))
                self.seq_same_identity.setChecked(bool(sequence.get('same_identity')))
            self._rule_type_changed()
        self._preview()
    
    def _read_groups(self):
        """Serialize nested condition groups into condition_groups dicts."""
        groups = []
        for frame, lc, tbl in getattr(self, 'group_widgets', []):
            conds = self._read_conds(tbl)
            if conds:
                groups.append({'logic_operator': lc.currentText(), 'conditions': conds})
        return groups

    def _current_rule_type(self):
        return self.rule_type_combo.currentText() if hasattr(self, 'rule_type_combo') else 'match'

    def _accept(self):
        if self.mode == 'advanced':
            if not self.rname.text().strip():
                QMessageBox.warning(self, "Error", "Name required")
                return
            if not self.rsem.text().strip():
                QMessageBox.warning(self, "Error", "Semantic required")
                return
            rt = self._current_rule_type()
            if rt == 'match':
                has_groups = bool(getattr(self, 'group_widgets', []))
                if self.tbl.rowCount() == 0 and not has_groups:
                    QMessageBox.warning(self, "Error", "Add at least one condition or group")
                    return
            elif rt == 'absence':
                if self.absent_tbl.rowCount() == 0:
                    QMessageBox.warning(self, "Error", "Absence rule needs at least one 'Require Absent' condition")
                    return
            elif rt == 'threshold':
                if self.thr_tbl.rowCount() == 0:
                    QMessageBox.warning(self, "Error", "Threshold rule needs a match condition")
                    return
            elif rt == 'sequence':
                if self.seq_tbl.rowCount() < 2:
                    QMessageBox.warning(self, "Error", "Sequence rule needs at least 2 steps")
                    return
        else:
            if not self.src.currentText().strip() or not self.fld.currentText().strip() or not self.tech.text().strip() or not self.sem.text().strip():
                QMessageBox.warning(self, "Error", "Fill all fields")
                return
        self.accept()

    def _split_tags(self, text):
        return [t.strip() for t in text.replace(';', ',').split(',') if t.strip()]

    @staticmethod
    def _flatten_seq_steps(steps):
        """Flatten sequence steps (each a flat condition or {conditions:[...]})
        into a single ordered list of condition dicts for the flat step table."""
        out = []
        for st in steps or []:
            if isinstance(st, dict) and 'conditions' in st:
                out.extend(st.get('conditions', []) or [])
            elif isinstance(st, dict):
                out.append(st)
        return out

    @staticmethod
    def _seq_sig(conds):
        """Order-preserving signature of a step list by core fields, so an
        unedited round-trip compares equal despite dict key ordering/extras."""
        return [
            (c.get('feather_id', ''), c.get('field_name', ''),
             c.get('operator', 'equals'), str(c.get('value', '')))
            for c in (conds or []) if isinstance(c, dict)
        ]

    def get_mapping(self):
        sc = self.mapping.get('scope', 'global') if self.mapping else ('wing' if hasattr(self, 'wing_radio') and self.wing_radio.isChecked() else 'global')

        if self.mode == 'advanced':
            rt = self._current_rule_type()
            # Preserve the rule's existing confidence (default rules ship
            # 0.85-0.95); only fall back to 1.0 for brand-new rules.
            confidence = self.mapping.get('confidence', 1.0) if self.mapping else 1.0
            rule = {
                'rule_id': self.mapping.get('rule_id', str(uuid.uuid4())),
                'name': self.rname.text(), 'semantic_value': self.rsem.text(),
                'description': self.rdesc.text(), 'scope': sc,
                'category': self.cat.currentText(), 'severity': self.sev.currentText(),
                'confidence': confidence, 'mode': 'advanced',
            }
            # ATT&CK tags (advanced only)
            if hasattr(self, 'tech_ids'):
                tids = self._split_tags(self.tech_ids.text())
                tacs = self._split_tags(self.tactics.text())
                if tids: rule['technique_id'] = tids
                if tacs: rule['tactic'] = tacs

            if rt == 'match':
                rule['conditions'] = self._read_conds(self.tbl)
                rule['logic_operator'] = "AND" if self.logic.currentIndex() == 0 else "OR"
                groups = self._read_groups()
                if groups:
                    rule['condition_groups'] = groups
            else:
                rule['rule_type'] = rt
                rule['conditions'] = []
                rule['logic_operator'] = "AND"
                if rt == 'absence':
                    spec = {
                        'expect_present': self._read_conds(self.expect_tbl),
                        'require_absent': self._read_conds(self.absent_tbl),
                    }
                    if self.abs_within.value() > 0:
                        spec['within_minutes'] = self.abs_within.value()
                    rule['absence'] = spec
                elif rt == 'threshold':
                    conds = self._read_conds(self.thr_tbl)
                    spec = {'min_count': self.thr_min.value()}
                    if len(conds) == 1:
                        spec['condition'] = conds[0]
                    else:
                        spec['conditions'] = conds
                    if self.thr_within.value() > 0:
                        spec['within_minutes'] = self.thr_within.value()
                    if self.thr_group_by.text().strip():
                        spec['group_by'] = self.thr_group_by.text().strip()
                    rule['threshold'] = spec
                elif rt == 'sequence':
                    table_steps = self._read_conds(self.seq_tbl)
                    # Preserve hand-authored {conditions:[...]} (multi-condition)
                    # steps on an unedited round-trip: the flat table can't
                    # represent them, so re-emit the original steps when they
                    # flatten to exactly the current table.
                    orig_steps = (getattr(self, '_loaded_sequence', None) or {}).get('steps')
                    if orig_steps and self._seq_sig(self._flatten_seq_steps(orig_steps)) == self._seq_sig(table_steps):
                        spec = {'steps': orig_steps}
                    else:
                        spec = {'steps': table_steps}
                    if self.seq_gap.value() > 0:
                        spec['max_gap_minutes'] = self.seq_gap.value()
                    join_fields = self._split_tags(self.seq_join.text())
                    if join_fields:
                        spec['join_fields'] = join_fields
                    if self.seq_same_identity.isChecked():
                        spec['same_identity'] = True
                    rule['sequence'] = spec
            return rule
        return {'source': self.src.currentText(), 'field': self.fld.currentText(), 'technical_value': self.tech.text(), 'semantic_value': self.sem.text(), 'description': self.desc.text(), 'scope': sc, 'mode': 'simple'}
    
    def get_rule(self):
        d = self.get_mapping()
        if d.get('mode') != 'advanced':
            return None
        # Delegate to the model so every advanced field (rule_type, specs,
        # condition_groups, negate/cross-feather, ATT&CK) is honoured.
        data = {k: v for k, v in d.items() if k != 'mode'}
        return SemanticRule.from_dict(data)
    
    def get_rule_data(self):
        return self.get_mapping()
