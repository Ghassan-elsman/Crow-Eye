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
from PyQt5.QtGui import QFont
from ...config.semantic_mapping import SemanticCondition, SemanticRule
import uuid

# The site look (ui/site_theme.py); standalone it keeps Qt's own style.
try:
    from ui import site_theme as _site
except Exception:
    _site = None


def _role(widget, role):
    if _site is not None:
        _site.set_role(widget, role)


def _status(widget, kind):
    if _site is not None:
        _site.set_status(widget, kind)


def _variant(widget, variant, compact=False, cell=False):
    """A button's role. ``compact``: a fixed-size row button (+ Add);
    ``cell``: the icon-only remove button inside a condition row."""
    if compact:
        widget.setProperty("compact", True)
    if cell:
        widget.setProperty("cell", True)
    if _site is not None:
        _site.set_variant(widget, variant)


def _dialog_extra():
    """The dialog's own rules on top of the site sheet: the condition tables
    are dense (22px rows of combos / edits), the preview is a mono well, and
    the semantic-output fields keep their cyan edge."""
    if _site is None:
        return ""
    mono = _site.families()[1]
    return """
QTableWidget QComboBox, QTableWidget QLineEdit { padding: 0 4px; border-radius: 6px;
    font-size: 12px; min-height: 0; }
QTableWidget QComboBox::drop-down { width: 14px; }
QTableWidget QComboBox::down-arrow { margin-right: 3px; }
QPushButton[compact="true"] { padding: 2px 10px; min-height: 0; font-size: 12px; border-radius: 7px; }
QPushButton[cell="true"] { padding: 0; min-height: 0; border-radius: 6px; }
QLineEdit[emphasis="true"] { border: 1px solid rgba(34, 211, 238, 0.60); }
QLineEdit[emphasis="true"]:focus { border: 1px solid %(CYAN)s; }
QLabel#rulePreview { background: %(BG)s; color: %(CYAN)s; border: 1px solid %(LINE)s;
    border-radius: 10px; padding: 8px; font-family: '%(mono)s'; font-size: 12px; }
QFrame#conditionGroup { background: %(BG)s; border: 1px solid %(LINE)s; border-radius: 10px; }
QFrame#modeBar { background: %(CARD)s; border: 1px solid %(LINE)s; border-radius: 12px; }
""" % dict(BG=_site.BG, CARD=_site.CARD, LINE=_site.LINE, CYAN=_site.CYAN, mono=mono)


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

        if _site is not None:
            _site.begin_site_theme(self, extra=_dialog_extra())
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
        mode_frame.setObjectName("modeBar")
        mode_frame.setFixedHeight(42)
        mode_layout = QHBoxLayout(mode_frame)
        mode_layout.setSpacing(16)
        mode_layout.setContentsMargins(14, 0, 14, 0)
        
        mode_label = QLabel("Mode:")
        _role(mode_label, "section")
        mode_layout.addWidget(mode_label)
        
        self.mode_group = QButtonGroup()
        self.simple_radio = QRadioButton("Simple")
        self.simple_radio.setChecked(self.mode == 'simple')
        self.simple_radio.toggled.connect(self._mode_changed)
        self.simple_radio.setFont(QFont(self.simple_radio.font().family(), -1, QFont.Bold))
        self.mode_group.addButton(self.simple_radio)
        mode_layout.addWidget(self.simple_radio)
        
        self.adv_radio = QRadioButton("Advanced")
        self.adv_radio.setChecked(self.mode == 'advanced')
        self.adv_radio.setFont(QFont(self.adv_radio.font().family(), -1, QFont.Bold))
        self.mode_group.addButton(self.adv_radio)
        mode_layout.addWidget(self.adv_radio)
        
        # Scope in same bar
        if not self.mapping:
            sep = QLabel("|")
            _role(sep, "muted")
            mode_layout.addWidget(sep)
            
            scope_label = QLabel("Scope:")
            _role(scope_label, "section")
            mode_layout.addWidget(scope_label)
            
            self.scope_group = QButtonGroup()
            self.global_radio = QRadioButton("Global")
            self.global_radio.setChecked(self.scope == 'global')
            self.global_radio.setFont(QFont(self.global_radio.font().family(), -1, QFont.Bold))
            self.scope_group.addButton(self.global_radio)
            mode_layout.addWidget(self.global_radio)
            
            self.wing_radio = QRadioButton("Wing")
            self.wing_radio.setEnabled(self.wing_id is not None)
            self.wing_radio.setFont(QFont(self.wing_radio.font().family(), -1, QFont.Bold))
            self.scope_group.addButton(self.wing_radio)
            mode_layout.addWidget(self.wing_radio)
        
        mode_layout.addStretch()
        layout.addWidget(mode_frame)
        
        # Simple mode form - professional with visible text
        self.simple_grp = QGroupBox("Simple Mapping")
        sf = QFormLayout()
        sf.setSpacing(12)
        sf.setContentsMargins(16, 24, 16, 16)
        sf.setLabelAlignment(Qt.AlignRight)
        
        
        src_label = QLabel("Source:")
        _role(src_label, "label")
        self.src = QComboBox()
        self.src.setEditable(True)
        self.src.addItems(["SecurityLogs", "Prefetch", "ShimCache", "AmCache", "Registry", "SRUM", "MFT", "LNK", "USN", "ShellBags"])
        self.src.setFixedHeight(32)
        sf.addRow(src_label, self.src)
        
        fld_label = QLabel("Field:")
        _role(fld_label, "label")
        self.fld = QComboBox()
        self.fld.setEditable(True)
        self.fld.addItems(["EventID", "Status", "Code", "Type", "Value", "path", "executable_name", "user"])
        self.fld.setFixedHeight(32)
        sf.addRow(fld_label, self.fld)
        
        tech_label = QLabel("Value:")
        _role(tech_label, "label")
        self.tech = QLineEdit()
        self.tech.setPlaceholderText("e.g., 4624, chrome.exe")
        self.tech.setFixedHeight(32)
        sf.addRow(tech_label, self.tech)
        
        sem_label = QLabel("Semantic:")
        _role(sem_label, "label")
        self.sem = QLineEdit()
        self.sem.setPlaceholderText("e.g., User Login, Browser Activity")
        self.sem.setFixedHeight(32)
        self.sem.setProperty("emphasis", True)
        sf.addRow(sem_label, self.sem)
        
        desc_label = QLabel("Description:")
        _role(desc_label, "label")
        self.desc = QLineEdit()
        self.desc.setPlaceholderText("Optional description")
        self.desc.setFixedHeight(32)
        sf.addRow(desc_label, self.desc)
        
        self.simple_grp.setLayout(sf)
        layout.addWidget(self.simple_grp)
        
        # Advanced mode - scrollable with dark theme
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        
        self.adv_widget = QWidget()
        av = QVBoxLayout(self.adv_widget)
        av.setSpacing(10)
        av.setContentsMargins(0, 0, 0, 0)
        
        # Rule output - professional styling
        rg = QGroupBox("Rule Output")
        rf = QVBoxLayout()
        rf.setSpacing(10)
        rf.setContentsMargins(14, 22, 14, 14)
        
        # Row 1: Name and Semantic
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        name_lbl = QLabel("Name:")
        _role(name_lbl, "label")
        row1.addWidget(name_lbl)
        self.rname = QLineEdit()
        self.rname.setPlaceholderText("Rule name")
        self.rname.setFixedHeight(32)
        self.rname.textChanged.connect(self._preview)
        row1.addWidget(self.rname, 1)
        sem_lbl = QLabel("Semantic:")
        _role(sem_lbl, "label")
        row1.addWidget(sem_lbl)
        self.rsem = QLineEdit()
        self.rsem.setPlaceholderText("Output value")
        self.rsem.setFixedHeight(32)
        self.rsem.setProperty("emphasis", True)
        self.rsem.textChanged.connect(self._preview)
        row1.addWidget(self.rsem, 1)
        rf.addLayout(row1)
        
        # Row 2: Category, Severity, Description
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        cat_lbl = QLabel("Category:")
        _role(cat_lbl, "label")
        row2.addWidget(cat_lbl)
        self.cat = QComboBox()
        self.cat.setEditable(True)
        self.cat.addItems(["", "authentication", "process_execution", "file_access", "user_activity"])
        self.cat.setFixedHeight(30)
        self.cat.setFixedWidth(150)
        row2.addWidget(self.cat)
        sev_lbl = QLabel("Severity:")
        _role(sev_lbl, "label")
        row2.addWidget(sev_lbl)
        self.sev = QComboBox()
        self.sev.addItems(["info", "low", "medium", "high", "critical"])
        self.sev.setFixedHeight(30)
        self.sev.setFixedWidth(100)
        row2.addWidget(self.sev)
        desc_lbl = QLabel("Description:")
        _role(desc_lbl, "label")
        row2.addWidget(desc_lbl)
        self.rdesc = QLineEdit()
        self.rdesc.setPlaceholderText("Optional")
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
        _variant(ab, "primary", compact=True)
        ab.clicked.connect(self._add_cond)
        btn_row.addWidget(ab)
        tip = QLabel("* = wildcard")
        _role(tip, "muted")
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
        ll = QHBoxLayout()
        ll.setContentsMargins(14, 22, 14, 14)
        self.logic = QComboBox()
        self.logic.addItems(["AND", "OR"])
        self.logic.setFixedHeight(30)
        self.logic.setFixedWidth(80)
        self.logic.currentIndexChanged.connect(self._preview)
        ll.addWidget(self.logic)
        self.lind = QLabel("All match")
        _role(self.lind, "muted")
        _status(self.lind, "warn")
        self.logic.currentIndexChanged.connect(lambda: self.lind.setText("All match" if self.logic.currentIndex()==0 else "Any match"))
        ll.addWidget(self.lind)
        lg.setLayout(ll)
        lg.setFixedWidth(180)
        self.logic_group = lg  # hidden for non-match rule types
        bottom.addWidget(lg)
        
        # Preview section
        pg = QGroupBox("Preview")
        pl = QVBoxLayout()
        pl.setContentsMargins(14, 22, 14, 14)
        self.prev = QLabel()
        self.prev.setWordWrap(True)
        self.prev.setMinimumHeight(28)
        self.prev.setObjectName("rulePreview")
        pl.addWidget(self.prev)
        pg.setLayout(pl)
        bottom.addWidget(pg, 1)
        
        av.addLayout(bottom)
        
        self.scroll.setWidget(self.adv_widget)
        layout.addWidget(self.scroll, 1)
        
        # Dialog buttons - professional styling
        # Buttons made (and given their role) BEFORE they join the box: a
        # button the box creates loses the site font when it is re-polished
        # under the app's style sheet, so OK / Cancel came out plain and
        # lower-case. Same text, same accepted / rejected.
        bb = QDialogButtonBox()
        ok_btn, cancel_btn = QPushButton("OK"), QPushButton("Cancel")
        _variant(ok_btn, "primary")
        _variant(cancel_btn, "ghost")
        bb.addButton(ok_btn, QDialogButtonBox.AcceptRole)
        bb.addButton(cancel_btn, QDialogButtonBox.RejectRole)
        ok_btn.setDefault(True)
        for b in bb.buttons():
            b.setMinimumSize(100, 36)           # as the box's own sheet had it
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)
        
        self._apply_site_look()
        self._mode_changed()
        if self.allow_advanced:
            self._rule_type_changed()
        self.update()
    
    def _apply_site_look(self):
        """The site look, once (ui/site_theme.py).

        This used to be _style(): a 230-line sheet in the old palette that
        showEvent wiped and set again on every show - each show re-polished
        the whole dialog, and the per-widget sheets fought it. The labels'
        own sheets become roles here; rows added later take the dialog
        sheet through their properties."""
        if _site is not None:
            _site.apply_site_theme(self, extra=_dialog_extra())

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

        f = QComboBox(); f.setEditable(True); f.setFixedHeight(22)
        f.addItems(self.available_feathers if self.available_feathers else self._DEFAULT_FEATHERS)
        f.currentTextChanged.connect(self._preview)
        tbl.setCellWidget(r, 0, f)

        fd = QComboBox(); fd.setEditable(True); fd.setFixedHeight(22)
        fd.addItems(self._DEFAULT_FIELDS)
        fd.currentTextChanged.connect(self._preview)
        tbl.setCellWidget(r, 1, fd)

        o = QComboBox(); o.setFixedHeight(22)
        for label, name in self.OP_ITEMS:
            if adv or name in self.OP_BASIC:
                o.addItem(label, name)
        o.currentIndexChanged.connect(self._preview)
        tbl.setCellWidget(r, 2, o)

        v = QLineEdit(); v.setFixedHeight(22)
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
            cmp.setFixedHeight(22)
            cmp.setToolTip("Cross-feather compare: feather.field (blank = compare to Value)")
            cmp.textChanged.connect(self._preview)
            tbl.setCellWidget(r, 5, cmp)
            del_col = 6

        from ...gui.crow_eye_icons import CrowEyeIcons
        x = QPushButton(); x.setIcon(CrowEyeIcons.delete()); x.setToolTip("Remove condition")
        _variant(x, "danger", cell=True)
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
        _variant(ab, "primary", compact=True)
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
        rt_lbl = QLabel("Rule Type:"); _role(rt_lbl, "label")
        top.addWidget(rt_lbl)
        self.rule_type_combo = QComboBox()
        self.rule_type_combo.addItems(self.RULE_TYPES)
        self.rule_type_combo.setFixedWidth(150)
        self.rule_type_combo.currentIndexChanged.connect(self._rule_type_changed)
        top.addWidget(self.rule_type_combo)
        top.addSpacing(14)
        tech_lbl = QLabel("ATT&CK IDs:"); _role(tech_lbl, "label")
        top.addWidget(tech_lbl)
        self.tech_ids = QLineEdit(); self.tech_ids.setPlaceholderText("e.g. T1070.004, T1562.001")
        self.tech_ids.setFixedHeight(28)
        top.addWidget(self.tech_ids, 1)
        tac_lbl = QLabel("Tactic:"); _role(tac_lbl, "label")
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
        _role(note, "note")                   # the site's amber notice
        _status(note, "warn")
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
        _variant(add_grp, "primary", compact=True)
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
        wl = QLabel("Within minutes (0 = whole window):"); _role(wl, "label")
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
        mcl = QLabel("Min count:"); _role(mcl, "label"); trow.addWidget(mcl)
        self.thr_min = QSpinBox(); self.thr_min.setRange(1, 1000000); self.thr_min.setValue(5)
        self.thr_min.setFixedWidth(80); trow.addWidget(self.thr_min)
        twl = QLabel("Within minutes:"); _role(twl, "label"); trow.addWidget(twl)
        self.thr_within = QSpinBox(); self.thr_within.setRange(0, 100000); self.thr_within.setValue(0)
        self.thr_within.setFixedWidth(90); trow.addWidget(self.thr_within)
        gbl = QLabel("Group by field:"); _role(gbl, "label"); trow.addWidget(gbl)
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
        sgl = QLabel("Max gap minutes between steps:"); _role(sgl, "label")
        srow.addWidget(sgl)
        self.seq_gap = QSpinBox(); self.seq_gap.setRange(0, 100000); self.seq_gap.setValue(30)
        self.seq_gap.setFixedWidth(90); srow.addWidget(self.seq_gap); srow.addStretch()
        sl.addLayout(srow)
        # Cross-feather join: the matching record of every step must share these
        # field values (e.g. same host/user) — a real correlation, not just
        # time-coincidence. Steps may each target a different feather.
        jrow = QHBoxLayout()
        jl = QLabel("Join on fields (same across steps):"); _role(jl, "label")
        jrow.addWidget(jl)
        self.seq_join = QLineEdit(); self.seq_join.setPlaceholderText("optional, e.g. host, user")
        self.seq_join.setFixedHeight(26); jrow.addWidget(self.seq_join, 1)
        sl.addLayout(jrow)
        self.seq_same_identity = QCheckBox("Restrict to the same identity")
        self.seq_same_identity.setToolTip(
            "Sequences are already evaluated within one correlated identity; this flag records "
            "that intent explicitly. Use 'Join on fields' for finer cross-feather binding.")
        sl.addWidget(self.seq_same_identity)
        self.sequence_group.setLayout(sl)
        av.addWidget(self.sequence_group)

    def _add_group(self, logic='AND', conditions=None):
        frame = QFrame()
        frame.setObjectName("conditionGroup")
        fl = QVBoxLayout(frame); fl.setContentsMargins(6, 6, 6, 6); fl.setSpacing(4)
        hdr = QHBoxLayout()
        lc = QComboBox(); lc.addItems(["AND", "OR"]); lc.setFixedWidth(70)
        lc.setCurrentText(logic if logic in ("AND", "OR") else "AND")
        hdr.addWidget(QLabel("Group logic:")); hdr.addWidget(lc); hdr.addStretch()
        rm = QPushButton("Remove group"); rm.setFixedHeight(22)
        _variant(rm, "danger", compact=True)
        hdr.addWidget(rm)
        fl.addLayout(hdr)
        tbl = self._make_cond_table(advanced=False)
        tbl.setMaximumHeight(110)
        fl.addWidget(tbl)
        ab = QPushButton("+ Add condition"); ab.setFixedHeight(22)
        _variant(ab, "primary", compact=True)
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
