"""
Behaviour Rule Creator - one editor for the analyst's own behaviour rules.

Two kinds, both written in the Wing condition language and saved globally in
``uba_user_rules.json`` (uba/engine/user_rules.py):

* **From a table** - a parsed artifact table of the open case, conditions on
  its columns, and where the time, the person and the program are.
* **From a behaviour** - a filter over behaviours User Behavior already finds
  (built-in or your own), emitted as its own behaviour with its own title and
  severity, carrying the base behaviour's evidence.

"Test on this case" runs the rule against the open case before it is saved
and shows the first events it would produce, with the count. A rule that
names a column the case's table does not have is refused with the reason.

Two doors open it, through ``open_behaviour_rule_creator()``:
- the User Behavior window (Rules view, "New behaviour rule"), via UBABridge;
- the Wing Creator's behavioural mode ("New behaviour..."), wired in Phase 4.

The opener is busy-guarded like every Crow-Eye opener (``@gated``): while
parsing or loading runs it says so and offers "Open when ready".
"""

import logging
import os
from typing import List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt

from uba.engine import user_rules
from uba.engine.extractors import declarative
from uba.engine.rule_loader import (ACTOR_MODES, AGGREGATIONS, TIME_BASES,
                                    load_rules, validate_user_rule)

logger = logging.getLogger(__name__)

try:
    from ui import app_theme as _theme
except Exception:                               # pragma: no cover - stripped host
    _theme = None

FEATURE = "the Behaviour Rule Creator"

OPERATORS = [("is", "equals"), ("contains", "contains"), ("matches regex", "regex"),
             ("is not", "not_equals"), (">", "greater_than"), ("<", "less_than"),
             ("≥", "greater_equal"), ("≤", "less_equal"),
             ("has any value", "wildcard")]
CLASSES = [("User", "user"), ("Application", "application"),
           ("System program", "system_app"), ("System", "system")]
SEVERITIES = [("Routine", "routine"), ("Notable", "notable"),
              ("Suspicious", "suspicious"), ("Critical", "critical")]
TIME_BASIS_ITEMS = [("Exact time", "exact"),
                    ("At or before (a last-write time)", "at_or_before")]
ACTOR_ITEMS = [("From a SID column", "sid"), ("From a user-name column", "username"),
               ("The profile the row belongs to (owner column, or the only profile)",
                "hive_owner"),
               ("Nobody - leave it unattributed", "none")]
AGG_ITEMS = [("One event per matching row", "none"),
             ("One event per person per day", "per_actor_day"),
             ("One event per burst (rows close in time)", "burst")]
assert [v for _l, v in TIME_BASIS_ITEMS] == list(TIME_BASES)
assert [v for _l, v in ACTOR_ITEMS] == list(ACTOR_MODES)
assert [v for _l, v in AGG_ITEMS] == list(AGGREGATIONS)

NO_COLUMN = "(none)"

# The editor's own rules on top of the site sheet: dense condition rows, the
# group well, and the violet "Your rule" chip - the colour that marks an
# analyst's rule everywhere (react-uba .rule-badge, the user_rule icon).
_EXTRA_QSS = """
QTableWidget QComboBox, QTableWidget QLineEdit { padding: 0 6px; border-radius: 6px;
    font-size: 12px; min-height: 0; }
QTableWidget QComboBox::drop-down { width: 16px; }
QPushButton[cell="true"] { padding: 0; min-height: 0; border-radius: 6px; }
QPushButton[compact="true"] { padding: 3px 12px; min-height: 0; font-size: 12px; border-radius: 8px; }
QFrame#ruleGroup { background: #0A0C10; border: 3px solid #1F2532;
    border-radius: 10px; }
QLabel[chip="user_rule"] { color: #A78BFA; background: rgba(139, 92, 246, 0.16);
    border-radius: 9px; padding: 2px 10px; font-weight: 700; font-size: 11px; }
QLabel#placeholders { color: #94A3B8; font-size: 12px; }
"""


def _role(w, role):
    if _theme is not None:
        _theme.set_role(w, role)
    return w


def _variant(w, variant, compact=False, cell=False):
    if compact:
        w.setProperty("compact", True)
    if cell:
        w.setProperty("cell", True)
    if _theme is not None:
        _theme.set_variant(w, variant)
    return w


def _status(w, kind):
    if _theme is not None:
        _theme.set_status(w, kind)
    return w


def _activity_icon(name):
    try:
        from styles import CrowEyeStyles
        return CrowEyeStyles.resource_icon("uba", "icons", "activity", "%s.svg" % name)
    except Exception:
        return None


# --------------------------------------------------------------------------
class ConditionTable(QtWidgets.QWidget):
    """Rows of field / test / value / not - the Wing condition language's
    SemanticCondition, one per row."""

    changed = QtCore.pyqtSignal()

    def __init__(self, fields=(), parent=None):
        super().__init__(parent)
        self._fields = list(fields)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Field", "Test", "Value", "Not", ""])
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        head.setSectionResizeMode(1, QtWidgets.QHeaderView.Fixed)
        head.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        head.setSectionResizeMode(3, QtWidgets.QHeaderView.Fixed)
        head.setSectionResizeMode(4, QtWidgets.QHeaderView.Fixed)
        head.resizeSection(1, 140)
        head.resizeSection(3, 46)
        head.resizeSection(4, 34)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setMinimumHeight(74)
        lay.addWidget(self.table)
        self._rows = []
        self._fit()

    def _fit(self):
        rows = max(1, self.table.rowCount())
        height = self.table.horizontalHeader().height() + rows * 32 + 6
        self.table.setFixedHeight(max(74, min(height, 32 * 8 + 40)))

    def set_fields(self, fields):
        self._fields = list(fields)
        for row in self._rows:
            combo = row["field"]
            text = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(self._fields)
            combo.setCurrentText(text)
            combo.blockSignals(False)

    def add_row(self, cond=None):
        cond = cond or {}
        r = self.table.rowCount()
        self.table.insertRow(r)
        field = QtWidgets.QComboBox()
        field.setEditable(True)
        field.addItems(self._fields)
        field.setCurrentText(str(cond.get("field_name", self._fields[0] if self._fields else "")))
        field.currentTextChanged.connect(self.changed.emit)
        op = QtWidgets.QComboBox()
        for label, name in OPERATORS:
            op.addItem(label, name)
        idx = op.findData(cond.get("operator", "contains" if not cond else "equals"))
        op.setCurrentIndex(idx if idx >= 0 else 0)
        value = QtWidgets.QLineEdit(str(cond.get("value", "")) if cond.get("value") != "*" else "")
        value.setPlaceholderText("value")
        value.textChanged.connect(self.changed.emit)
        neg = QtWidgets.QCheckBox()
        neg.setToolTip("Not: the row matches when this test does NOT hold")
        neg.setChecked(bool(cond.get("negate")))
        neg_wrap = QtWidgets.QWidget()
        nl = QtWidgets.QHBoxLayout(neg_wrap)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setAlignment(Qt.AlignCenter)
        nl.addWidget(neg)
        remove = QtWidgets.QPushButton("×")
        remove.setToolTip("Remove this condition")
        remove.setFixedSize(26, 24)
        _variant(remove, "danger", cell=True)
        row = {"field": field, "op": op, "value": value, "neg": neg, "remove": remove}
        remove.clicked.connect(lambda _=False, rw=row: self._remove(rw))
        op.currentIndexChanged.connect(lambda _i, rw=row: self._op_changed(rw))
        for col, w in enumerate((field, op, value, neg_wrap, remove)):
            self.table.setCellWidget(r, col, w)
        self._rows.append(row)
        self._op_changed(row)
        self._fit()
        self.changed.emit()
        return row

    def _op_changed(self, row):
        wildcard = row["op"].currentData() == "wildcard"
        row["value"].setEnabled(not wildcard)
        if wildcard:
            row["value"].setPlaceholderText("any value")
        else:
            row["value"].setPlaceholderText("value")
        self.changed.emit()

    def _remove(self, row):
        if row not in self._rows:
            return
        i = self._rows.index(row)
        self._rows.pop(i)
        self.table.removeRow(i)
        self._fit()
        self.changed.emit()

    def clear(self):
        while self._rows:
            self._remove(self._rows[-1])

    def conditions(self, feather_id) -> List[dict]:
        out = []
        for row in self._rows:
            field = row["field"].currentText().strip()
            if not field:
                continue
            op = row["op"].currentData() or "equals"
            value = "*" if op == "wildcard" else row["value"].text()
            cond = {"feather_id": feather_id, "field_name": field,
                    "value": value, "operator": op}
            if row["neg"].isChecked():
                cond["negate"] = True
            out.append(cond)
        return out


class ConditionGroup(QtWidgets.QFrame):
    """A nested group with its own ALL / ANY (condition_groups)."""

    removed = QtCore.pyqtSignal(object)

    def __init__(self, fields, group=None, parent=None):
        super().__init__(parent)
        self.setObjectName("ruleGroup")
        group = group or {}
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(6)
        head = QtWidgets.QHBoxLayout()
        head.addWidget(QtWidgets.QLabel("Group - match"))
        self.logic = QtWidgets.QComboBox()
        self.logic.addItem("all of these", "AND")
        self.logic.addItem("any of these", "OR")
        self.logic.setCurrentIndex(1 if str(group.get("logic_operator", "AND")).upper() == "OR" else 0)
        head.addWidget(self.logic)
        head.addStretch()
        add = QtWidgets.QPushButton("+ Condition")
        _variant(add, "ghost", compact=True)
        head.addWidget(add)
        rm = QtWidgets.QPushButton("Remove group")
        _variant(rm, "danger", compact=True)
        head.addWidget(rm)
        lay.addLayout(head)
        self.table = ConditionTable(fields)
        lay.addWidget(self.table)
        add.clicked.connect(lambda: self.table.add_row())
        rm.clicked.connect(lambda: self.removed.emit(self))
        for cond in group.get("conditions") or []:
            self.table.add_row(cond)
        if not group.get("conditions"):
            self.table.add_row()

    def to_dict(self, feather_id):
        return {"logic_operator": self.logic.currentData(),
                "conditions": self.table.conditions(feather_id)}


class _PreviewWorker(QtCore.QThread):
    """Runs a table rule's preview off the GUI thread, on a pool of its own
    (DbPool connections belong to the thread that opened them)."""

    done = QtCore.pyqtSignal(dict)

    def __init__(self, artifacts_dir, rule, parent=None):
        super().__init__(parent)
        self.artifacts_dir, self.rule = artifacts_dir, rule

    def run(self):
        try:
            result = declarative.preview_table_rule(self.artifacts_dir, self.rule)
        except Exception as e:                  # pragma: no cover - reported, not raised
            logger.exception("UBA: rule preview failed")
            result = {"ok": False, "problems": ["The test failed: %s" % e], "events": [], "count": 0}
        self.done.emit(result)


# --------------------------------------------------------------------------
class BehaviourRuleDialog(QtWidgets.QDialog):
    """The editor. After ``exec_()``: ``saved_rule`` (the rule as stored),
    ``deleted_id``, and ``rerun_requested`` (the analyst asked to analyse
    again now)."""

    def __init__(self, parent=None, artifacts_dir=None, rule=None, kind=None,
                 store=None, offer_rerun=True):
        super().__init__(parent)
        self.artifacts_dir = artifacts_dir if artifacts_dir and os.path.isdir(artifacts_dir) else None
        self.store = store
        self.offer_rerun = offer_rerun
        self.original = dict(rule) if rule else None
        self.saved_rule = None
        self.deleted_id = None
        self.rerun_requested = False
        self._id_edited = bool(rule)
        self._worker = None
        self._columns_cache = {}
        self._builtin = load_rules()
        self._builtin_ids = {r["id"] for r in self._builtin["rules"]}
        self._user, _problems = user_rules.load_user_rules(self._builtin_ids)
        self._groups: List[ConditionGroup] = []

        self.setWindowTitle("Behaviour Rule Creator")
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint |
                            Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        icon = _activity_icon("user_rule")
        if icon is not None:
            self.setWindowIcon(icon)
        if _theme is not None:
            _theme.begin_theme(self, extra=_EXTRA_QSS)
        self.resize(1060, 900)
        self.setMinimumSize(860, 620)
        self._build()
        self._load(self.original, kind or (self.original or {}).get("kind") or user_rules.KIND_TABLE)
        if _theme is not None:
            _theme.apply_theme(self, extra=_EXTRA_QSS)

    # ------------------------------------------------------------------ build
    def _card(self, title, help_text=None):
        frame = QtWidgets.QFrame()
        if _theme is not None:
            _theme.set_card(frame)
        lay = QtWidgets.QVBoxLayout(frame)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(10)
        head = QtWidgets.QLabel(title)
        _role(head, "section")
        lay.addWidget(head)
        if help_text:
            hint = QtWidgets.QLabel(help_text)
            hint.setWordWrap(True)
            _role(hint, "muted")
            lay.addWidget(hint)
        return frame, lay

    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(12)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(12)
        icon = _activity_icon("user_rule")
        if icon is not None:
            glyph = QtWidgets.QLabel()
            glyph.setPixmap(icon.pixmap(36, 36))
            glyph.setFixedSize(40, 40)
            head.addWidget(glyph, 0, Qt.AlignVCenter)
        title = QtWidgets.QLabel("Behaviour Rule Creator")
        _role(title, "title")
        head.addWidget(title, 0, Qt.AlignVCenter)
        chip = QtWidgets.QLabel("Your rule")
        chip.setProperty("chip", "user_rule")
        head.addWidget(chip, 0, Qt.AlignVCenter)
        head.addStretch()
        root.addLayout(head)

        blurb = QtWidgets.QLabel(
            "A behaviour of your own for User Behavior: it is looked for in every case, "
            "appears in the Activity Story and the coverage page with the \"Your rule\" "
            "icon, can be turned off like any rule, and Eye sees its events. Rules are "
            "saved for all cases, never inside one.")
        blurb.setWordWrap(True)
        _role(blurb, "muted")
        root.addWidget(blurb)

        kinds = QtWidgets.QHBoxLayout()
        kinds.setSpacing(8)
        self.kind_group = QtWidgets.QButtonGroup(self)
        self.kind_group.setExclusive(True)
        self.kind_table = QtWidgets.QPushButton("From a table")
        self.kind_derived = QtWidgets.QPushButton("From a behaviour")
        for b, tip in ((self.kind_table, "Rows of a parsed artifact table that meet your conditions"),
                       (self.kind_derived, "Behaviours User Behavior already finds, narrowed by your conditions")):
            b.setCheckable(True)
            b.setToolTip(tip)
            _variant(b, "pill")
            self.kind_group.addButton(b)
            kinds.addWidget(b)
        kinds.addStretch()
        self.case_label = QtWidgets.QLabel()
        _role(self.case_label, "muted")
        kinds.addWidget(self.case_label)
        root.addLayout(kinds)
        self.kind_table.clicked.connect(lambda: self._set_kind(user_rules.KIND_TABLE))
        self.kind_derived.clicked.connect(lambda: self._set_kind(user_rules.KIND_DERIVED))

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QtWidgets.QWidget()
        self.body = QtWidgets.QVBoxLayout(body)
        self.body.setContentsMargins(0, 0, 8, 0)
        self.body.setSpacing(14)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self._build_identity()
        self._build_source()
        self._build_conditions()
        self._build_columns()
        self._build_test()
        self.body.addStretch()
        # Filled once every card exists: a table choice fills the column map
        # and the condition fields.
        self._fill_dbs()
        self._fill_bases()

        foot = QtWidgets.QHBoxLayout()
        foot.setSpacing(8)
        self.import_btn = QtWidgets.QPushButton("Import…")
        self.export_btn = QtWidgets.QPushButton("Export…")
        self.delete_btn = QtWidgets.QPushButton("Delete rule")
        for b, v in ((self.import_btn, "ghost"), (self.export_btn, "ghost"),
                     (self.delete_btn, "danger")):
            _variant(b, v)
            foot.addWidget(b)
        foot.addStretch()
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.save_btn = QtWidgets.QPushButton("Save rule")
        _variant(self.cancel_btn, "ghost")
        _variant(self.save_btn, "primary")
        foot.addWidget(self.cancel_btn)
        foot.addWidget(self.save_btn)
        root.addLayout(foot)
        self.import_btn.clicked.connect(self._import)
        self.export_btn.clicked.connect(self._export)
        self.delete_btn.clicked.connect(self._delete)
        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn.clicked.connect(self._save)

    def _build_identity(self):
        card, lay = self._card("Rule")
        form = QtWidgets.QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.title_edit = QtWidgets.QLineEdit()
        self.title_edit.setPlaceholderText("What the behaviour is, e.g. Mimikatz ran")
        self.title_edit.textChanged.connect(self._title_changed)
        form.addRow("Title", self.title_edit)
        self.id_edit = QtWidgets.QLineEdit()
        self.id_edit.setPlaceholderText("user_...")
        self.id_edit.textEdited.connect(lambda _t: setattr(self, "_id_edited", True))
        form.addRow("Rule id", self.id_edit)

        row = QtWidgets.QHBoxLayout()
        self.activity_combo = QtWidgets.QComboBox()
        self.activity_combo.setIconSize(QtCore.QSize(18, 18))
        for act in user_rules.builtin_activities():
            icon = _activity_icon(act)
            label = act.replace("_", " ")
            if icon is not None:
                self.activity_combo.addItem(icon, label, act)
            else:
                self.activity_combo.addItem(label, act)
        self.activity_combo.setToolTip(
            "The activity family the event belongs to (its filter and label in the "
            "window). Events of your rules are drawn with the \"Your rule\" icon.")
        row.addWidget(self.activity_combo, 2)
        row.addSpacing(14)
        self.class_combo = QtWidgets.QComboBox()
        for label, value in CLASSES:
            self.class_combo.addItem(label, value)
        row.addWidget(QtWidgets.QLabel("Class"))
        row.addSpacing(6)
        row.addWidget(self.class_combo, 1)
        form.addRow("Activity", row)

        sev_row = QtWidgets.QHBoxLayout()
        self.severity_combo = QtWidgets.QComboBox()
        for label, value in SEVERITIES:
            self.severity_combo.addItem(label, value)
        self.severity_combo.setCurrentIndex(1)
        self.severity_chip = QtWidgets.QLabel()
        self.severity_chip.setAlignment(Qt.AlignCenter)
        self.severity_chip.setMinimumWidth(90)
        self.severity_combo.currentIndexChanged.connect(self._severity_changed)
        sev_row.addWidget(self.severity_combo, 1)
        sev_row.addWidget(self.severity_chip)
        sev_row.addStretch(2)
        form.addRow("Severity", sev_row)

        self.desc_edit = QtWidgets.QLineEdit()
        form.addRow("Sentence", self.desc_edit)
        lay.addLayout(form)
        self.placeholders = QtWidgets.QLabel()
        self.placeholders.setObjectName("placeholders")
        self.placeholders.setWordWrap(True)
        lay.addWidget(self.placeholders)
        self.body.addWidget(card)
        self._severity_changed()

    def _build_source(self):
        card, lay = self._card("Source")
        self.source_stack = QtWidgets.QStackedWidget()
        # Table page.
        page = QtWidgets.QWidget()
        pl = QtWidgets.QHBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        self.db_combo = QtWidgets.QComboBox()
        self.table_combo = QtWidgets.QComboBox()
        self.rows_label = QtWidgets.QLabel()
        _role(self.rows_label, "muted")
        pl.addWidget(QtWidgets.QLabel("Database"))
        pl.addWidget(self.db_combo, 2)
        pl.addWidget(QtWidgets.QLabel("Table"))
        pl.addWidget(self.table_combo, 2)
        pl.addWidget(self.rows_label, 1)
        self.source_stack.addWidget(page)
        # Derived page.
        page2 = QtWidgets.QWidget()
        dl = QtWidgets.QVBoxLayout(page2)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(8)
        hint = QtWidgets.QLabel("Tick the behaviours this rule narrows. Its events carry "
                                "the base behaviour's evidence.")
        _role(hint, "muted")
        dl.addWidget(hint)
        self.base_search = QtWidgets.QLineEdit()
        self.base_search.setPlaceholderText("Search behaviours")
        self.base_search.setClearButtonEnabled(True)
        self.base_search.textChanged.connect(self._filter_bases)
        dl.addWidget(self.base_search)
        self.base_list = QtWidgets.QListWidget()
        self.base_list.setIconSize(QtCore.QSize(18, 18))
        self.base_list.setMinimumHeight(170)
        self.base_list.setMaximumHeight(220)
        self.base_list.itemChanged.connect(lambda _i: self._refresh_fields())
        dl.addWidget(self.base_list)
        self.source_stack.addWidget(page2)
        lay.addWidget(self.source_stack)
        self.body.addWidget(card)

        self.db_combo.currentIndexChanged.connect(self._db_changed)
        self.table_combo.currentIndexChanged.connect(self._table_changed)

    def _build_conditions(self):
        card, lay = self._card(
            "Conditions",
            "Written in the Wing condition language: each test reads one field. Tests are "
            "not case-sensitive. A group has its own all / any.")
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Match"))
        self.logic_combo = QtWidgets.QComboBox()
        self.logic_combo.addItem("all of the tests and groups", "AND")
        self.logic_combo.addItem("any of the tests and groups", "OR")
        top.addWidget(self.logic_combo)
        top.addStretch()
        add = QtWidgets.QPushButton("+ Condition")
        _variant(add, "primary", compact=True)
        add_group = QtWidgets.QPushButton("+ Group")
        _variant(add_group, "ghost", compact=True)
        top.addWidget(add)
        top.addWidget(add_group)
        lay.addLayout(top)
        self.cond_table = ConditionTable()
        lay.addWidget(self.cond_table)
        self.groups_box = QtWidgets.QVBoxLayout()
        self.groups_box.setSpacing(8)
        lay.addLayout(self.groups_box)
        add.clicked.connect(lambda: self.cond_table.add_row())
        add_group.clicked.connect(lambda: self._add_group())
        self.body.addWidget(card)

    def _build_columns(self):
        card, lay = self._card(
            "Columns",
            "Where the row says when, who and which program. The person goes through "
            "the same attribution ladder as the built-in rules, so a SID is recorded "
            "only when the evidence binds the row to one profile.")
        self.columns_card = card
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        self.time_combo = QtWidgets.QComboBox()
        self.basis_combo = QtWidgets.QComboBox()
        for label, value in TIME_BASIS_ITEMS:
            self.basis_combo.addItem(label, value)
        self.actor_mode = QtWidgets.QComboBox()
        for label, value in ACTOR_ITEMS:
            self.actor_mode.addItem(label, value)
        self.actor_col = QtWidgets.QComboBox()
        self.app_combo = QtWidgets.QComboBox()
        self.agg_combo = QtWidgets.QComboBox()
        for label, value in AGG_ITEMS:
            self.agg_combo.addItem(label, value)
        self.gap_spin = QtWidgets.QSpinBox()
        self.gap_spin.setRange(1, 24 * 60)
        self.gap_spin.setValue(10)
        self.gap_spin.setSuffix(" min gap")
        grid.addWidget(QtWidgets.QLabel("Time"), 0, 0)
        grid.addWidget(self.time_combo, 0, 1)
        grid.addWidget(self.basis_combo, 0, 2)
        grid.addWidget(QtWidgets.QLabel("Person"), 1, 0)
        grid.addWidget(self.actor_mode, 1, 1)
        grid.addWidget(self.actor_col, 1, 2)
        grid.addWidget(QtWidgets.QLabel("Program"), 2, 0)
        grid.addWidget(self.app_combo, 2, 1)
        grid.addWidget(QtWidgets.QLabel("Events"), 3, 0)
        grid.addWidget(self.agg_combo, 3, 1)
        grid.addWidget(self.gap_spin, 3, 2)
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(2, 2)
        lay.addLayout(grid)
        self.actor_mode.currentIndexChanged.connect(self._actor_mode_changed)
        self.agg_combo.currentIndexChanged.connect(self._agg_changed)
        self.body.addWidget(card)
        self._actor_mode_changed()
        self._agg_changed()

    def _build_test(self):
        card, lay = self._card("Test on this case")
        row = QtWidgets.QHBoxLayout()
        self.test_btn = QtWidgets.QPushButton("Test on this case")
        _variant(self.test_btn, "primary")
        row.addWidget(self.test_btn)
        self.test_status = QtWidgets.QLabel("Run the rule against the open case before saving it.")
        self.test_status.setWordWrap(True)
        _role(self.test_status, "muted")
        row.addWidget(self.test_status, 1)
        lay.addLayout(row)
        self.test_table = QtWidgets.QTableWidget(0, 5)
        self.test_table.setHorizontalHeaderLabels(["Time (UTC)", "Person", "SID", "What", "Evidence"])
        head = self.test_table.horizontalHeader()
        for col, mode in ((0, QtWidgets.QHeaderView.ResizeToContents),
                          (1, QtWidgets.QHeaderView.ResizeToContents),
                          (2, QtWidgets.QHeaderView.Interactive),
                          (3, QtWidgets.QHeaderView.Stretch),
                          (4, QtWidgets.QHeaderView.ResizeToContents)):
            head.setSectionResizeMode(col, mode)
        head.resizeSection(2, 150)
        self.test_table.verticalHeader().setVisible(False)
        self.test_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.test_table.setWordWrap(False)
        self.test_table.setMinimumHeight(170)
        self.test_table.setVisible(False)
        lay.addWidget(self.test_table)
        self.test_btn.clicked.connect(self._test)
        self.body.addWidget(card)

    # --------------------------------------------------------------- sources
    def _fill_dbs(self):
        self.db_combo.blockSignals(True)
        self.db_combo.clear()
        if not self.artifacts_dir:
            self.case_label.setText("No case open - tables cannot be listed or tested")
            _status(self.case_label, "warn")
        else:
            case = os.path.basename(os.path.dirname(os.path.abspath(self.artifacts_dir)))
            self.case_label.setText("Case: %s" % case)
            from uba.utils.db_access import discover_databases
            for entry in discover_databases(self.artifacts_dir):
                label = entry["name"] if not entry["logical"] else "%s  —  %s" % (
                    entry["name"], entry["rel"])
                self.db_combo.addItem(label, entry)
        self.db_combo.blockSignals(False)
        self._db_changed()

    def _open(self, db_entry):
        from uba.utils.db_access import open_ro
        return open_ro(db_entry["path"])

    def _db_changed(self):
        self.table_combo.blockSignals(True)
        self.table_combo.clear()
        entry = self.db_combo.currentData()
        if entry:
            try:
                conn = self._open(entry)
                try:
                    names = [r[0] for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name NOT LIKE 'sqlite_%' ORDER BY name COLLATE NOCASE")]
                finally:
                    conn.close()
                self.table_combo.addItems(names)
            except Exception as e:
                logger.warning("UBA: cannot list tables of %s: %s", entry.get("path"), e)
        self.table_combo.blockSignals(False)
        self._table_changed()

    def _columns(self) -> List[str]:
        entry = self.db_combo.currentData()
        table = self.table_combo.currentText()
        if not entry or not table:
            return []
        key = (entry["path"], table)
        if key not in self._columns_cache:
            cols, count = [], None
            try:
                conn = self._open(entry)
                try:
                    cols = [r[1] for r in conn.execute('PRAGMA table_info("%s")'
                                                       % table.replace('"', '""'))]
                    count = conn.execute('SELECT COUNT(*) FROM "%s"'
                                         % table.replace('"', '""')).fetchone()[0]
                finally:
                    conn.close()
            except Exception as e:
                logger.warning("UBA: cannot read columns of %s: %s", table, e)
            self._columns_cache[key] = (cols, count)
        return self._columns_cache[key][0]

    def _table_changed(self):
        cols = self._columns()
        entry = self.db_combo.currentData()
        count = None
        if entry and self.table_combo.currentText():
            count = self._columns_cache.get((entry["path"], self.table_combo.currentText()),
                                            ([], None))[1]
        self.rows_label.setText("" if count is None else "{:,} rows, {} columns".format(
            count, len(cols)))
        for combo, blank in ((self.time_combo, "(no time - timeless events)"),
                             (self.actor_col, NO_COLUMN), (self.app_combo, NO_COLUMN)):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(blank, "")
            for c in cols:
                combo.addItem(c, c)
            i = combo.findData(current)
            combo.setCurrentIndex(i if i >= 0 else 0)
            combo.blockSignals(False)
        self._guess_columns(cols)
        self._refresh_fields()

    def _guess_columns(self, cols):
        """First guesses for an empty column map - the analyst checks them."""
        low = {c.lower(): c for c in cols}
        if not self.time_combo.currentData():
            for name in ("last_executed", "last_execution", "eventtimestamputc", "timestamp",
                         "last_written", "last_run_time", "visit_time", "start_time",
                         "time_created", "modified", "created_on"):
                if name in low:
                    self.time_combo.setCurrentIndex(self.time_combo.findData(low[name]))
                    break
        if not self.app_combo.currentData():
            for name in ("executable_name", "process_path", "program_path", "app_name",
                         "path", "image_path", "filename", "name"):
                if name in low:
                    self.app_combo.setCurrentIndex(self.app_combo.findData(low[name]))
                    break
        if not self.actor_col.currentData():
            for name in ("sid", "user_sid", "usersid", "user", "user_name", "username"):
                if name in low:
                    self.actor_col.setCurrentIndex(self.actor_col.findData(low[name]))
                    mode = "sid" if "sid" in name else "username"
                    if name == "user_name":
                        mode = "hive_owner"
                    self.actor_mode.setCurrentIndex(self.actor_mode.findData(mode))
                    break

    def _fill_bases(self):
        self.base_list.blockSignals(True)
        self.base_list.clear()
        rules = list(self._builtin["rules"]) + [user_rules.to_rule_meta(r) for r in self._user]
        for rule in sorted(rules, key=lambda r: (not r.get("user_rule"), r.get("title", "").lower())):
            if self.original and rule.get("id") == self.original.get("id"):
                continue
            icon = _activity_icon("user_rule" if rule.get("user_rule") else rule.get("activity"))
            item = QtWidgets.QListWidgetItem("%s   ·  %s" % (rule.get("title"), rule["id"]))
            if icon is not None:
                item.setIcon(icon)
            item.setData(Qt.UserRole, rule["id"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.base_list.addItem(item)
        self.base_list.blockSignals(False)

    def _filter_bases(self, text):
        needle = (text or "").strip().lower()
        for i in range(self.base_list.count()):
            item = self.base_list.item(i)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def _checked_bases(self) -> List[str]:
        out = []
        for i in range(self.base_list.count()):
            item = self.base_list.item(i)
            if item.checkState() == Qt.Checked:
                out.append(item.data(Qt.UserRole))
        return out

    def _derived_fields(self) -> List[str]:
        """Event fields, then the details keys the chosen behaviours carry in
        the analysis at hand (so 'details.executable' is offered for Prefetch)."""
        fields = list(declarative.EVENT_FIELDS)
        store = self._store()
        bases = self._checked_bases()
        if store is not None and bases:
            import json as _json
            keys = []
            try:
                marks = ",".join("?" for _ in bases)
                for (details,) in store.conn.execute(
                        "SELECT details_json FROM events WHERE rule_id IN (%s) LIMIT 400"
                        % marks, bases):
                    for k in (_json.loads(details or "{}") or {}):
                        if k not in keys:
                            keys.append(k)
            except Exception:
                keys = []
            fields = ["details.%s" % k for k in keys] + fields
        return fields

    def _refresh_fields(self):
        kind = self._kind()
        fields = self._columns() if kind == user_rules.KIND_TABLE else self._derived_fields()
        self.cond_table.set_fields(fields)
        for group in self._groups:
            group.table.set_fields(fields)
        if kind == user_rules.KIND_TABLE:
            self.placeholders.setText(
                "In the sentence: {actor} {app} {time} {table} {count}, or any column in braces, "
                "e.g. {actor} ran {executable_name}")
        else:
            self.placeholders.setText(
                "In the sentence: {description} (the base behaviour's own sentence), {actor} "
                "{app} {time}, or any event field / details.<key> in braces")

    # ----------------------------------------------------------------- state
    def _kind(self):
        return user_rules.KIND_DERIVED if self.kind_derived.isChecked() else user_rules.KIND_TABLE

    def _set_kind(self, kind):
        (self.kind_derived if kind == user_rules.KIND_DERIVED else self.kind_table).setChecked(True)
        derived = kind == user_rules.KIND_DERIVED
        self.source_stack.setCurrentIndex(1 if derived else 0)
        # A stack is as tall as its tallest page; let the hidden one shrink.
        for i in range(self.source_stack.count()):
            page = self.source_stack.widget(i)
            policy = (QtWidgets.QSizePolicy.Preferred if i == self.source_stack.currentIndex()
                      else QtWidgets.QSizePolicy.Ignored)
            page.setSizePolicy(QtWidgets.QSizePolicy.Preferred, policy)
        self.source_stack.adjustSize()
        self.columns_card.setVisible(not derived)
        self.desc_edit.setPlaceholderText(
            "{description}" if derived else "{actor} ran {executable_name}")
        self._refresh_fields()

    def _title_changed(self, text):
        if self._id_edited:
            return
        taken = set(self._builtin_ids) | {r.get("id") for r in self._user}
        self.id_edit.setText(user_rules.suggest_id(text, taken) if text.strip() else "")

    def _severity_changed(self):
        sev = self.severity_combo.currentData() or "notable"
        self.severity_chip.setText(self.severity_combo.currentText())
        if _theme is not None:
            _theme.set_severity(self.severity_chip, sev)

    def _actor_mode_changed(self):
        mode = self.actor_mode.currentData()
        self.actor_col.setEnabled(mode in ("sid", "username", "hive_owner"))
        self.actor_col.setToolTip({
            "sid": "The column holding a SID (S-1-5-21-...)",
            "username": "The column holding an account name",
            "hive_owner": "Optional: a column naming the owner (user name, SID, or a path "
                          "under \\Users\\<name>\\). Empty: the only profile on a "
                          "one-profile machine, otherwise nobody.",
        }.get(mode, "Not used"))

    def _agg_changed(self):
        self.gap_spin.setEnabled(self.agg_combo.currentData() == "burst")

    def _add_group(self, group=None):
        fields = (self._columns() if self._kind() == user_rules.KIND_TABLE
                  else self._derived_fields())
        frame = ConditionGroup(fields, group)
        frame.removed.connect(self._remove_group)
        self.groups_box.addWidget(frame)
        self._groups.append(frame)
        if _theme is not None:
            _theme.apply_theme(self, root=frame, extra=_EXTRA_QSS)
        return frame

    def _remove_group(self, frame):
        if frame in self._groups:
            self._groups.remove(frame)
        frame.setParent(None)
        frame.deleteLater()

    def _store(self):
        """The analysis a derived rule filters: the window's own, else the
        case's stored one (<case>/UBA/uba_events.db), whatever its age."""
        if self.store is None and self.artifacts_dir:
            try:
                from uba.engine.persisted_store import PersistedStore
                store, meta = PersistedStore(self.artifacts_dir).load()
                self.store = store
                self._store_built = (meta or {}).get("built_at_utc")
            except Exception as e:
                logger.debug("UBA: no stored analysis for the rule editor: %s", e)
        return self.store

    # ------------------------------------------------------------- load/save
    def _load(self, rule, kind):
        rule = rule or {}
        self.cond_table.clear()
        for group in list(self._groups):
            self._remove_group(group)
        self._set_kind(kind)
        self.title_edit.setText(rule.get("title", ""))
        if rule.get("id"):
            self.id_edit.setText(rule["id"])
        i = self.activity_combo.findData(rule.get("activity") or "execution")
        self.activity_combo.setCurrentIndex(i if i >= 0 else 0)
        i = self.class_combo.findData(rule.get("behavior_class") or "user")
        self.class_combo.setCurrentIndex(max(0, i))
        i = self.severity_combo.findData(rule.get("severity") or "notable")
        self.severity_combo.setCurrentIndex(max(0, i))
        self.desc_edit.setText(rule.get("description", ""))
        self.delete_btn.setVisible(bool(self.original))
        if kind == user_rules.KIND_TABLE and rule.get("source"):
            source = rule["source"]
            for idx in range(self.db_combo.count()):
                if (self.db_combo.itemData(idx) or {}).get("name") == source.get("db"):
                    self.db_combo.setCurrentIndex(idx)
                    break
            t = self.table_combo.findText(source.get("table", ""))
            if t >= 0:
                self.table_combo.setCurrentIndex(t)
            cols = rule.get("columns") or {}
            for combo, value in ((self.time_combo, cols.get("time")),
                                 (self.app_combo, cols.get("app")),
                                 (self.actor_col, (cols.get("actor") or {}).get("column"))):
                j = combo.findData(value or "")
                combo.setCurrentIndex(j if j >= 0 else 0)
            j = self.basis_combo.findData(cols.get("time_basis", "exact"))
            self.basis_combo.setCurrentIndex(max(0, j))
            j = self.actor_mode.findData((cols.get("actor") or {}).get("mode", "none"))
            self.actor_mode.setCurrentIndex(max(0, j))
            agg = rule.get("aggregation") or {}
            j = self.agg_combo.findData(agg.get("mode", "none"))
            self.agg_combo.setCurrentIndex(max(0, j))
            if agg.get("gap_minutes"):
                self.gap_spin.setValue(int(float(agg["gap_minutes"])))
        if kind == user_rules.KIND_DERIVED:
            wanted = set((rule.get("base") or {}).get("rule_ids") or [])
            first = None
            for idx in range(self.base_list.count()):
                item = self.base_list.item(idx)
                if item.data(Qt.UserRole) in wanted:
                    item.setCheckState(Qt.Checked)
                    first = first or item
            if first is not None:
                self.base_list.scrollToItem(first, QtWidgets.QAbstractItemView.PositionAtTop)
        self._refresh_fields()
        i = self.logic_combo.findData(str(rule.get("logic_operator", "AND")).upper())
        self.logic_combo.setCurrentIndex(max(0, i))
        for cond in rule.get("conditions") or []:
            self.cond_table.add_row(cond)
        if not rule.get("conditions") and not rule.get("condition_groups"):
            self.cond_table.add_row()
        for group in rule.get("condition_groups") or []:
            self._add_group(group)

    def build_rule(self) -> dict:
        """The rule as the form says now (not yet validated or saved)."""
        kind = self._kind()
        rule = {
            "id": self.id_edit.text().strip(),
            "kind": kind,
            "title": self.title_edit.text().strip(),
            "activity": self.activity_combo.currentData(),
            "behavior_class": self.class_combo.currentData(),
            "severity": self.severity_combo.currentData(),
            "description": self.desc_edit.text().strip(),
            "logic_operator": self.logic_combo.currentData(),
        }
        if kind == user_rules.KIND_TABLE:
            entry = self.db_combo.currentData() or {}
            table = self.table_combo.currentText()
            feather = table or "row"
            rule["source"] = {"db": entry.get("name", ""), "table": table}
            mode = self.actor_mode.currentData()
            rule["columns"] = {
                "time": self.time_combo.currentData() or "",
                "time_basis": self.basis_combo.currentData(),
                "actor": {"mode": mode,
                          "column": (self.actor_col.currentData() or "") if mode != "none" else ""},
                "app": self.app_combo.currentData() or "",
            }
            agg = {"mode": self.agg_combo.currentData()}
            if agg["mode"] == "burst":
                agg["gap_minutes"] = self.gap_spin.value()
            rule["aggregation"] = agg
        else:
            feather = user_rules.DERIVED_FEATHER
            rule["base"] = {"rule_ids": self._checked_bases(), "activities": []}
        rule["conditions"] = self.cond_table.conditions(feather)
        rule["condition_groups"] = [g.to_dict(feather) for g in self._groups]
        if self.original:
            for key in ("author", "created_utc", "version"):
                if key in self.original:
                    rule[key] = self.original[key]
            if self.original.get("id") and self.original["id"] != rule["id"]:
                rule["previous_id"] = self.original["id"]
        return rule

    def problems(self, rule) -> List[str]:
        """Everything that stops ``rule`` being saved, the case's own checks
        included (a column the open case's table lacks is refused here)."""
        found = validate_user_rule(rule, self._builtin_ids)
        others = {r.get("id") for r in self._user
                  if not self.original or r.get("id") != self.original.get("id")}
        if rule.get("id") in others:
            found.append("Another rule of yours already uses the id '%s'." % rule["id"])
        if rule["kind"] == user_rules.KIND_TABLE and self.artifacts_dir and not found:
            from uba.utils.db_access import DbPool
            pool = DbPool(self.artifacts_dir)
            try:
                found.extend(declarative.check_table_rule(pool, rule))
            finally:
                pool.close()
        if rule["kind"] == user_rules.KIND_DERIVED:
            found.extend(declarative.check_derived_rule(rule))
        return found

    def _warn(self, title, text):
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning, title, text,
                                    QtWidgets.QMessageBox.Ok, self)
        if _theme is not None:
            box.setStyleSheet(_theme.theme_qss())
        box.exec_()

    def _ask(self, title, text):
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question, title, text,
                                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, self)
        if _theme is not None:
            box.setStyleSheet(_theme.theme_qss())
        return box.exec_() == QtWidgets.QMessageBox.Yes

    def _save(self):
        rule = self.build_rule()
        found = self.problems(rule)
        if found:
            self._warn("The rule cannot be saved", "\n".join("• " + p for p in found))
            return
        ok, problems, stored = user_rules.save_rule(rule, self._builtin_ids)
        if not ok:
            self._warn("The rule cannot be saved", "\n".join("• " + p for p in problems))
            return
        self.saved_rule = stored
        if self.offer_rerun:
            self.rerun_requested = self._ask(
                "Rule saved",
                "'%s' is saved for every case.\n\nAnalyse this case again now so the rule is "
                "applied? Until then the window shows the analysis built without it."
                % stored["title"])
        self.accept()

    def _delete(self):
        if not self.original:
            return
        if not self._ask("Delete rule", "Delete your rule '%s' from every case?"
                         % self.original.get("title", self.original.get("id"))):
            return
        if user_rules.delete_rule(self.original["id"]):
            self.deleted_id = self.original["id"]
            if self.offer_rerun:
                self.rerun_requested = self._ask(
                    "Rule deleted", "Analyse this case again now, without the rule?")
            self.accept()

    def _export(self):
        path, _f = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export your behaviour rules", "uba_user_rules_export.json", "JSON (*.json)")
        if not path:
            return
        try:
            n = user_rules.export_rules(path)
        except OSError as e:
            self._warn("Export failed", str(e))
            return
        self.test_status.setText("Exported %d rule%s to %s" % (n, "" if n == 1 else "s", path))
        _status(self.test_status, "ok")

    def _import(self):
        path, _f = QtWidgets.QFileDialog.getOpenFileName(
            self, "Import behaviour rules", "", "JSON (*.json)")
        if not path:
            return
        added, skipped = user_rules.import_rules(path, self._builtin_ids)
        text = "Imported %d rule%s." % (len(added), "" if len(added) == 1 else "s")
        if skipped:
            text += "\n\nSkipped:\n" + "\n".join("• %s: %s" % s for s in skipped[:20])
        self._warn("Import", text) if skipped else self._ask_ok("Import", text)
        self._user, _p = user_rules.load_user_rules(self._builtin_ids)
        self._fill_bases()
        if added:
            self.saved_rule = self.saved_rule or {"imported": added}

    def _ask_ok(self, title, text):
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information, title, text,
                                    QtWidgets.QMessageBox.Ok, self)
        if _theme is not None:
            box.setStyleSheet(_theme.theme_qss())
        box.exec_()

    # ------------------------------------------------------------------ test
    def _test(self):
        rule = self.build_rule()
        if not rule["id"]:
            rule["id"] = "user_preview"
        if not rule["title"]:
            rule["title"] = "(untitled)"
        found = [p for p in validate_user_rule(rule, self._builtin_ids)]
        if found:
            self._show_result({"ok": False, "problems": found, "events": [], "count": 0})
            return
        if rule["kind"] == user_rules.KIND_TABLE:
            if not self.artifacts_dir:
                self._show_result({"ok": False, "events": [], "count": 0,
                                   "problems": ["Open a case to test a rule on it."]})
                return
            self.test_btn.setEnabled(False)
            self.test_status.setText("Testing on this case…")
            _status(self.test_status, "info")
            self._worker = _PreviewWorker(self.artifacts_dir, rule, self)
            self._worker.done.connect(self._show_result)
            self._worker.start()
        else:
            QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                result = declarative.preview_derived_rule(self._store(), rule)
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
            self._show_result(result)

    def _show_result(self, result):
        self.test_btn.setEnabled(True)
        if not result.get("ok"):
            self.test_status.setText("Not run on this case: " + " ".join(result.get("problems") or []))
            _status(self.test_status, "warn")
            self.test_table.setVisible(False)
            return
        count = result.get("count", 0)
        rows = result.get("matched_rows", count)
        more = " or more (the test stops at 5,000)" if result.get("capped") else ""
        unit = "behaviour" if self._kind() == user_rules.KIND_DERIVED else "row"
        if count:
            text = "{:,}{} event{} from {:,} matching {}{}".format(
                count, more, "" if count == 1 else "s", rows, unit, "" if rows == 1 else "s")
            if count > len(result.get("events") or []):
                text += " - the first %d are shown" % len(result["events"])
            _status(self.test_status, "ok")
        else:
            text = ("Nothing matched in this case. That is a result, not an error - "
                    "check the conditions against a row you expect to match.")
            _status(self.test_status, "neutral")
        self.test_status.setText(text)
        events = result.get("events") or []
        self.test_table.setRowCount(len(events))
        for r, ev in enumerate(events):
            person = ev.get("actor_name") or "Unattributed"
            values = [ev.get("ts_start") or "(no time)", person, ev.get("actor_sid") or "",
                      ev.get("description") or "", ev.get("evidence") or ""]
            for c, v in enumerate(values):
                item = QtWidgets.QTableWidgetItem(str(v))
                if c == 1 and ev.get("actor_basis"):
                    item.setToolTip(ev["actor_basis"])
                if c == 3:
                    item.setToolTip(str(v))
                self.test_table.setItem(r, c, item)
        self.test_table.setVisible(bool(events))

    def done(self, result):
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(5000)
        super().done(result)


# --------------------------------------------------------------------------
def _main_window_of(widget):
    w = widget
    while w is not None:
        if hasattr(w, "_feature_gate"):
            return w
        w = w.parent() if hasattr(w, "parent") else None
    return None


def open_behaviour_rule_creator(parent=None, artifacts_dir=None, rule_id=None,
                                kind=None, store=None, offer_rerun=True):
    """The one opener both doors call. Returns None when it could not open
    (Crow-Eye busy), else {"saved": rule or None, "deleted": id or None,
    "rerun": bool}.

    Busy-guarded as @gated openers are: through the main window's feature
    gate when one is reachable from ``parent`` (busy dialog with "Open when
    ready"), else ui.busy_guard directly. ``rule_id`` opens that rule of
    yours for editing; ``kind`` ('table' / 'derived') picks the page of a new
    rule. ``store`` lets a derived rule be tested against the analysis on
    screen."""
    main = _main_window_of(parent)
    retry = lambda: open_behaviour_rule_creator(parent, artifacts_dir, rule_id, kind,
                                                store, offer_rerun)
    if main is not None:
        try:
            if not main._feature_gate(FEATURE, needs=None, kind="view", retry=retry):
                return None
        except Exception:
            logger.debug("UBA: feature gate unavailable", exc_info=True)
    else:
        try:
            from ui import busy_guard
            if busy_guard.is_busy():
                reason, _elapsed = busy_guard.current()
                box = QtWidgets.QMessageBox(
                    QtWidgets.QMessageBox.Information, "Crow-Eye is busy",
                    "Crow-Eye is still working: %s.\n\nThe Behaviour Rule Creator will be "
                    "available when it has finished." % (reason or "working"),
                    QtWidgets.QMessageBox.Ok, parent)
                box.exec_()
                return None
        except ImportError:
            pass

    rule = None
    if rule_id:
        loaded, _problems = user_rules.load_user_rules()
        rule = next((r for r in loaded if r.get("id") == rule_id), None)
        if rule is not None:
            rule = {k: v for k, v in rule.items() if not k.startswith("_")}
    dialog = BehaviourRuleDialog(parent, artifacts_dir=artifacts_dir, rule=rule, kind=kind,
                                 store=store, offer_rerun=offer_rerun)
    try:
        from styles import CrowEyeStyles as _CES
        _CES.give_window_a_taskbar_button(dialog)
    except Exception:
        pass
    dialog.exec_()
    return {"saved": dialog.saved_rule, "deleted": dialog.deleted_id,
            "rerun": bool(dialog.rerun_requested)}
