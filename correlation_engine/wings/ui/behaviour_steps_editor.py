"""
Behaviour step editor - what the Wing Creator shows for a Behaviour Wing.

A Behaviour Wing names no Feathers (config/wing_config.py, BEHAVIOUR_FIELDS):
it is a set of behaviour steps one person performs, in order or in any order,
within a time range. This editor writes exactly what the Behavioural engine
reads (engine/behavioural_engine.py, _compile_step and _steps_rule):

  a step   rule_id (one id, or a list: any of them) or activity, label,
           min_count, min_severity, actor (person / machine / any), conditions
  the Wing ordered, within_minutes, max_gap_minutes (ordered only),
           subject {scope, accounts / sids / groups, include_service_accounts},
           alert {severity, technique_id [...], tactic [...]}

What it has no widget for is kept: each step, the subject and the alert start
from the dict that was loaded, so a Wing saved unchanged keeps its fields.

The behaviours offered are UBA's built-in rules (uba/config/behavior_rules.json),
the analyst's own (uba_user_rules.json) and the activities they record, grouped
by behaviour class, each with its activity icon (uba/icons/activity). A rule
turned off in Settings is still offered, marked: the Wing saves, and that step
is "not evaluable" when it runs.
"""

import copy
import os
from typing import Dict, List, Optional

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFrame,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ...config.wing_config import (
    ALERT_SEVERITIES, BEHAVIOUR_EVENT_FIELDS, BEHAVIOUR_FIELDS, STEP_ACTORS,
    SUBJECT_SCOPES, UBA_SEVERITIES,
)

try:
    from ui import app_theme as _theme
except Exception:                               # pragma: no cover - stripped host
    _theme = None

try:
    # The Wing condition language's row editor (field / test / value / not),
    # the one the Behaviour Rule Creator uses for its conditions.
    from uba.ui.behaviour_rule_dialog import ConditionTable
except Exception:                               # pragma: no cover - stripped host
    ConditionTable = None


def _look(widget, role=None, status=None, variant=None):
    """A role / meaning colour / button variant through the window sheet."""
    if _theme is None:
        return widget
    if role:
        _theme.set_role(widget, role)
    if status:
        _theme.set_status(widget, status)
    if variant:
        _theme.set_variant(widget, variant)
    return widget


# The editor's own rules, added to the window sheet by whoever hosts it (the
# Wing Creator's _WINGS_EXTRA, the picker's own sheet): the step well, the
# dense condition rows and the violet "Your rule" chip - violet marks an
# analyst's rule and nothing else (ui/uba_rules_settings.py, react-uba
# .rule-badge, the user_rule icon).
EDITOR_QSS = """
QFrame#behaviourStep { background: #0A0C10; border: 3px solid #1F2532;
    border-radius: 10px; }
QFrame#behaviourStep QLabel { background: transparent; }
QTableWidget QComboBox, QTableWidget QLineEdit { padding: 0 6px; border-radius: 6px;
    font-size: 12px; min-height: 0; }
QTableWidget QComboBox::drop-down { width: 16px; }
QPushButton[cell="true"] { padding: 0; min-height: 0; border-radius: 6px; }
QPushButton[compact="true"] { padding: 3px 12px; min-height: 0; font-size: 12px; border-radius: 8px; }
QLabel[chip="user_rule"], QFrame#behaviourStep QLabel[chip="user_rule"] { color: #A78BFA; background: rgba(139, 92, 246, 0.16);
    border-radius: 9px; padding: 2px 10px; font-weight: 700; font-size: 11px; }
"""

_WARN = QColor("#FBBF24")
_MUTED = QColor("#94A3B8")

ACTOR_TEXT = {
    "person": ("The person",
               "Only events recorded for the person being evaluated."),
    "machine": ("No person recorded",
                "Events Windows records no account for (a service installed, a program "
                "run known from Prefetch, a USB device plugged in), matched on the case "
                "as a whole."),
    "any": ("Either",
            "The person's own events and events with no person recorded."),
}
assert tuple(ACTOR_TEXT) == STEP_ACTORS

SCOPE_TEXT = {
    "everyone": "Everyone",
    "accounts": "These accounts",
    "sids": "These SIDs",
    "groups": "Members of these local groups",
}
assert tuple(SCOPE_TEXT) == SUBJECT_SCOPES

UNITS = (("minutes", 1), ("hours", 60), ("days", 1440))

# Detail keys the shipped Behaviour Wings condition on; any details.<name>
# can be typed.
_DETAIL_FIELDS = ("details.folder", "details.file_types", "details.rename_chain",
                  "details.executable")
CONDITION_FIELDS = list(BEHAVIOUR_EVENT_FIELDS) + list(_DETAIL_FIELDS)

_NUMERIC_OPS = ("greater_than", "less_than", "greater_equal", "less_equal")


# --------------------------------------------------------------- catalog --
def activity_icon(name):
    """The User Behavior window's drawing for an activity (or user_rule)."""
    try:
        from styles import CrowEyeStyles
        return CrowEyeStyles.resource_icon("uba", "icons", "activity", f"{name}.svg")
    except Exception:
        return None


def load_catalog() -> Dict:
    """Every behaviour a step can name, read now: the rules (built-in and the
    analyst's, as the Settings switch list draws them - rule_switches.
    switch_rows) and the activities they record.

    {'rules': {id: row}, 'rule_order': [ids], 'activities': {name: entry},
     'activity_order': [names], 'problem': text or ''}. A row carries
    title, activity, class_label, severity, enabled, user_rule, invalid.
    """
    try:
        from uba.engine import rule_switches
        rows = rule_switches.switch_rows()
        class_order = list(rule_switches.CLASS_ORDER)
    except Exception as e:
        return {"rules": {}, "rule_order": [], "activities": {}, "activity_order": [],
                "problem": f"The behaviour rules could not be read ({e})."}
    rules = {r["rule_id"]: r for r in rows}
    activities: Dict[str, Dict] = {}
    for r in rows:
        name = r.get("activity") or ""
        if not name:
            continue
        entry = activities.setdefault(name, {
            "activity": name, "behavior_class": r.get("behavior_class", ""),
            "class_label": r.get("class_label", ""), "rule_ids": [], "enabled": False})
        entry["rule_ids"].append(r["rule_id"])
        if r.get("enabled") and not r.get("invalid"):
            entry["enabled"] = True

    def act_key(name):
        cls = activities[name]["behavior_class"]
        return (class_order.index(cls) if cls in class_order else len(class_order), name)
    return {"rules": rules, "rule_order": [r["rule_id"] for r in rows],
            "activities": activities, "activity_order": sorted(activities, key=act_key),
            "problem": ""}


def as_list(value) -> List[str]:
    if value is None or value == "":
        return []
    return [str(v) for v in value] if isinstance(value, (list, tuple)) else [str(value)]


def step_notes(step: Dict, catalog: Dict) -> List[str]:
    """Why a step will not run as written, from what this machine's rules
    say now - the engine's _step_availability without a case (it adds the
    case's own: a rule unavailable or degraded for that case's data)."""
    if catalog.get("problem"):
        return []
    rules, acts = catalog["rules"], catalog["activities"]
    notes, usable = [], False
    for rid in as_list(step.get("rule_id")):
        row = rules.get(rid)
        if row is None:
            notes.append(f"There is no UBA rule '{rid}' (built-in or yours).")
        elif row.get("invalid"):
            notes.append(f"Your rule {rid} is not valid, so it does not run: "
                         + " ".join(row["invalid"]))
        elif not row.get("enabled"):
            notes.append(f"{row.get('title') or rid} ({rid}) is turned off in Settings.")
        else:
            usable = True
    for name in as_list(step.get("activity")):
        entry = acts.get(name)
        if entry is None:
            notes.append(f"No UBA rule records the activity '{name}'.")
        elif not entry["enabled"]:
            notes.append(f"Every rule that records '{name}' is turned off in Settings.")
        else:
            usable = True
    if not notes:
        return []
    if usable:
        return notes + ["The step runs on the others."]
    return notes + ["This step will be not evaluable until that changes."]


def _put(d: Dict, key, value):
    """Set ``key`` keeping its place when it is already there."""
    d[key] = value


def _number_out(value: float):
    """A whole number of minutes as an int (60, not 60.0)."""
    return int(value) if float(value).is_integer() else float(value)


def _split_list(text: str) -> List[str]:
    return [p.strip() for p in str(text or "").replace(";", ",").split(",") if p.strip()]


def find_artifacts_dir(case_directory: Optional[str]) -> Optional[str]:
    """The case's Target_Artifacts from what the Wing Creator was given (the
    case folder, or its Correlation folder), or None."""
    if not case_directory:
        return None
    d = os.path.abspath(case_directory)
    for _ in range(3):
        if os.path.basename(d).lower() == "target_artifacts" and os.path.isdir(d):
            return d
        cand = os.path.join(d, "Target_Artifacts")
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


# ---------------------------------------------------------------- picker --
class BehaviourPickerDialog(QDialog):
    """Choose a step's behaviour: one or more UBA rules (any of them), or one
    or more activities. After ``exec_()``: ``kind`` ('rule_id' / 'activity')
    and ``selected`` (the ids, in catalog order)."""

    def __init__(self, parent=None, catalog=None, kind="rule_id", selected=(),
                 on_new_behaviour=None, step_name="this step"):
        super().__init__(parent)
        self.setWindowTitle("Choose the behaviour")
        self.setModal(True)
        self.resize(760, 640)
        self.catalog = catalog or load_catalog()
        self.kind = kind if kind in ("rule_id", "activity") else "rule_id"
        self.selected = list(selected or [])
        self._on_new = on_new_behaviour
        if _theme is not None:
            _theme.begin_theme(self, extra=EDITOR_QSS)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        title = QLabel(f"Behaviour for {step_name}")
        _look(title, role="section")
        lay.addWidget(title)
        help_text = QLabel("Tick one or more: the step matches an event of any of them. "
                           "A step names rules or activities, not both.")
        help_text.setWordWrap(True)
        _look(help_text, role="muted")
        lay.addWidget(help_text)

        mode = QHBoxLayout()
        self.rules_btn = QPushButton("UBA rules")
        self.acts_btn = QPushButton("Activities")
        self._mode_group = QButtonGroup(self)
        for b in (self.rules_btn, self.acts_btn):
            b.setCheckable(True)
            _look(b, variant="pill")
            self._mode_group.addButton(b)
            mode.addWidget(b)
        mode.addSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search behaviours, rule ids, activities...")
        self.search.textChanged.connect(self._filter)
        mode.addWidget(self.search, 1)
        lay.addLayout(mode)

        self.rule_tree = self._tree(["Behaviour", "Rule id", "", "In Settings"])
        self.act_tree = self._tree(["Activity", "Recorded by", "In Settings"])
        lay.addWidget(self.rule_tree, 1)
        lay.addWidget(self.act_tree, 1)

        if self.catalog.get("problem"):
            note = QLabel(self.catalog["problem"])
            note.setWordWrap(True)
            _look(note, role="note", status="warn")
            lay.addWidget(note)

        buttons = QHBoxLayout()
        self.new_btn = QPushButton("New behaviour...")
        self.new_btn.setToolTip("Create a behaviour rule of your own (the Behaviour Rule "
                                "Creator); it is listed here once saved.")
        _look(self.new_btn, variant="ghost")
        self.new_btn.setVisible(self._on_new is not None)
        self.new_btn.clicked.connect(self._new_behaviour)
        buttons.addWidget(self.new_btn)
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        _look(cancel, variant="ghost")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.ok_btn = QPushButton("Use these")
        _look(self.ok_btn, variant="primary")
        self.ok_btn.clicked.connect(self._accept)
        buttons.addWidget(self.ok_btn)
        lay.addLayout(buttons)

        self.rules_btn.toggled.connect(lambda on: on and self._set_mode("rule_id"))
        self.acts_btn.toggled.connect(lambda on: on and self._set_mode("activity"))
        self._fill()
        (self.rules_btn if self.kind == "rule_id" else self.acts_btn).setChecked(True)
        self._set_mode(self.kind)
        if _theme is not None:
            _theme.apply_theme(self, extra=EDITOR_QSS)

    def _tree(self, headers):
        tree = QTreeWidget()
        tree.setColumnCount(len(headers))
        tree.setHeaderLabels(headers)
        tree.setRootIsDecorated(True)
        tree.setUniformRowHeights(True)
        tree.setIconSize(QSize(20, 20))
        head = tree.header()
        head.setStretchLastSection(False)
        head.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, len(headers)):
            head.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        if headers[2] == "":
            # the "Your rule" chip's column: an item widget is not measured
            head.setSectionResizeMode(2, QHeaderView.Fixed)
            head.resizeSection(2, 92)
        tree.itemChanged.connect(lambda _i, _c: self._count())
        return tree

    # ------------------------------------------------------------ fill --
    def _fill(self):
        cat = self.catalog
        chosen = set(self.selected)
        for tree in (self.rule_tree, self.act_tree):
            tree.blockSignals(True)
            tree.clear()
        groups: Dict[str, QTreeWidgetItem] = {}

        def group(tree, label, key):
            k = (id(tree), label)
            if k not in groups:
                g = QTreeWidgetItem(tree, [label or "Other"])
                g.setFlags(Qt.ItemIsEnabled)
                f = g.font(0)
                f.setBold(True)
                g.setFont(0, f)
                g.setFirstColumnSpanned(True)
                groups[k] = g
            return groups[k]

        for rid in cat["rule_order"]:
            row = cat["rules"][rid]
            g = group(self.rule_tree, row.get("class_label"), rid)
            item = QTreeWidgetItem(g, [row.get("title") or rid, rid, "", ""])
            item.setData(0, Qt.UserRole, rid)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            item.setCheckState(0, Qt.Checked if (self.kind == "rule_id" and rid in chosen)
                               else Qt.Unchecked)
            icon = activity_icon("user_rule" if row.get("user_rule") else row.get("activity", ""))
            if icon is not None:
                item.setIcon(0, icon)
            item.setForeground(1, _MUTED)
            tip = row.get("how") or ""
            item.setToolTip(0, f"{rid} - activity {row.get('activity', '')}"
                               + (f"\n\n{tip}" if tip else ""))
            if row.get("invalid"):
                item.setText(3, "not valid, so not run")
                item.setForeground(3, _WARN)
                item.setToolTip(3, " ".join(row["invalid"]))
            elif not row.get("enabled"):
                item.setText(3, "turned off in Settings")
                item.setForeground(3, _WARN)
                item.setForeground(0, _MUTED)
                item.setToolTip(3, "The Wing can still be saved; this step is not "
                                   "evaluable until the rule is turned on in Settings.")
            if row.get("user_rule"):
                chip = QLabel("Your rule")
                chip.setProperty("chip", "user_rule")
                chip.setToolTip("A behaviour rule you created, saved for every case.")
                chip.setAlignment(Qt.AlignCenter)
                self.rule_tree.setItemWidget(item, 2, chip)

        for name in cat["activity_order"]:
            entry = cat["activities"][name]
            g = group(self.act_tree, entry.get("class_label"), name)
            n = len(entry["rule_ids"])
            item = QTreeWidgetItem(g, [name, f"{n} rule{'s' if n != 1 else ''}", ""])
            item.setData(0, Qt.UserRole, name)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            item.setCheckState(0, Qt.Checked if (self.kind == "activity" and name in chosen)
                               else Qt.Unchecked)
            icon = activity_icon(name)
            if icon is not None:
                item.setIcon(0, icon)
            item.setForeground(1, _MUTED)
            item.setToolTip(1, ", ".join(entry["rule_ids"]))
            item.setToolTip(0, f"Any rule that records '{name}': {', '.join(entry['rule_ids'])}")
            if not entry["enabled"]:
                item.setText(2, "all its rules turned off in Settings")
                item.setForeground(2, _WARN)
                item.setForeground(0, _MUTED)

        for tree in (self.rule_tree, self.act_tree):
            tree.expandAll()
            tree.blockSignals(False)
        self._filter(self.search.text())
        self._count()

    def _set_mode(self, kind):
        self.kind = kind
        self.rule_tree.setVisible(kind == "rule_id")
        self.act_tree.setVisible(kind == "activity")
        self._count()

    def _filter(self, text):
        needle = str(text or "").strip().lower()
        for tree in (self.rule_tree, self.act_tree):
            for gi in range(tree.topLevelItemCount()):
                g = tree.topLevelItem(gi)
                shown = 0
                for ci in range(g.childCount()):
                    c = g.child(ci)
                    hay = " ".join(c.text(k) for k in range(tree.columnCount())).lower()
                    hit = not needle or needle in hay
                    c.setHidden(not hit)
                    shown += hit
                g.setHidden(shown == 0)

    def _items(self, tree):
        for gi in range(tree.topLevelItemCount()):
            g = tree.topLevelItem(gi)
            for ci in range(g.childCount()):
                yield g.child(ci)

    def checked(self, kind=None) -> List[str]:
        tree = self.rule_tree if (kind or self.kind) == "rule_id" else self.act_tree
        return [c.data(0, Qt.UserRole) for c in self._items(tree)
                if c.checkState(0) == Qt.Checked]

    def _count(self):
        n = len(self.checked())
        self.ok_btn.setEnabled(n > 0)
        self.ok_btn.setText("Use these" if n != 1 else "Use this")

    def item_for(self, ident, kind="rule_id"):
        tree = self.rule_tree if kind == "rule_id" else self.act_tree
        return next((c for c in self._items(tree) if c.data(0, Qt.UserRole) == ident), None)

    def _new_behaviour(self):
        new_id = self._on_new() if self._on_new else None
        if not new_id:
            return
        keep = self.checked("rule_id") if self.kind == "rule_id" else []
        self.catalog = load_catalog()
        self.selected, self.kind = keep + [new_id], "rule_id"
        self._fill()
        self.rules_btn.setChecked(True)
        item = self.item_for(new_id)
        if item is not None:
            self.rule_tree.scrollToItem(item)
            self.rule_tree.setCurrentItem(item)
        if _theme is not None:
            _theme.apply_theme(self, root=self.rule_tree, extra=EDITOR_QSS)

    def _accept(self):
        self.selected = self.checked()
        if self.selected:
            self.accept()


# ------------------------------------------------------------- one step --
class StepCard(QFrame):
    """One behaviour step: what it is, how many, whose, extra conditions."""

    changed = pyqtSignal()
    move_requested = pyqtSignal(object, int)      # (card, -1 up / +1 down)
    remove_requested = pyqtSignal(object)
    choose_requested = pyqtSignal(object)

    def __init__(self, step: Optional[Dict] = None, catalog: Optional[Dict] = None, parent=None):
        super().__init__(parent)
        self.setObjectName("behaviourStep")
        self._orig = copy.deepcopy(step) if isinstance(step, dict) else {}
        self.catalog = catalog or {"rules": {}, "activities": {}, "problem": ""}
        if self._orig.get("activity") not in (None, "", []):
            self._kind, self._value = "activity", copy.deepcopy(self._orig["activity"])
        else:
            self._kind, self._value = "rule_id", copy.deepcopy(self._orig.get("rule_id"))
        self._loading = True

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(7)

        head = QHBoxLayout()
        self.number_label = QLabel("STEP 1")
        _look(self.number_label, role="caption")
        self.number_label.setMinimumWidth(60)
        head.addWidget(self.number_label)
        self.label_edit = QLineEdit(str(self._orig.get("label") or ""))
        self.label_edit.setPlaceholderText("What happens in this step (shown in hits; optional)")
        self.label_edit.textChanged.connect(self._emit)
        head.addWidget(self.label_edit, 1)
        from ...gui.crow_eye_icons import CrowEyeIcons
        self.up_btn = QPushButton()
        self.up_btn.setIcon(CrowEyeIcons.up())
        self.up_btn.setToolTip("Move this step up")
        self.down_btn = QPushButton()
        self.down_btn.setIcon(CrowEyeIcons.down())
        self.down_btn.setToolTip("Move this step down")
        self.remove_btn = QPushButton("Remove step")
        for b, v in ((self.up_btn, "ghost"), (self.down_btn, "ghost"), (self.remove_btn, "danger")):
            _look(b, variant=v)
            head.addWidget(b)
        self.up_btn.clicked.connect(lambda: self.move_requested.emit(self, -1))
        self.down_btn.clicked.connect(lambda: self.move_requested.emit(self, 1))
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        lay.addLayout(head)

        what = QHBoxLayout()
        what_label = QLabel("Behaviour:")
        what_label.setMinimumWidth(110)
        what.addWidget(what_label)
        self.what_box = QHBoxLayout()
        self.what_box.setSpacing(6)
        what.addLayout(self.what_box)
        what.addStretch()
        self.choose_btn = QPushButton("Choose...")
        _look(self.choose_btn, variant="ghost")
        self.choose_btn.clicked.connect(lambda: self.choose_requested.emit(self))
        what.addWidget(self.choose_btn)
        lay.addLayout(what)

        self.state_note = QLabel("")
        self.state_note.setWordWrap(True)
        _look(self.state_note, role="note", status="warn")
        lay.addWidget(self.state_note)

        who = QHBoxLayout()
        who_label = QLabel("Done by:")
        who_label.setMinimumWidth(110)
        who.addWidget(who_label)
        self.actor_combo = QComboBox()
        for key in STEP_ACTORS:
            self.actor_combo.addItem(ACTOR_TEXT[key][0], key)
        actor = self._orig.get("actor", "person") or "person"
        idx = self.actor_combo.findData(actor)
        self.actor_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.actor_combo.currentIndexChanged.connect(self._actor_changed)
        who.addWidget(self.actor_combo)
        self.actor_help = QLabel("")
        self.actor_help.setWordWrap(True)
        _look(self.actor_help, role="muted")
        who.addWidget(self.actor_help, 1)
        lay.addLayout(who)

        count = QHBoxLayout()
        count_label = QLabel("At least:")
        count_label.setMinimumWidth(110)
        count.addWidget(count_label)
        self.min_count_spin = QSpinBox()
        self.min_count_spin.setRange(1, 1000000)
        mc = self._orig.get("min_count", 1)
        self.min_count_spin.setValue(mc if isinstance(mc, int) and not isinstance(mc, bool)
                                     and mc >= 1 else 1)
        self._count_suffix()
        self.min_count_spin.setToolTip("Counted as UBA counts each event: a burst of files "
                                       "or an hour of sign-ins counts as many.")
        self.min_count_spin.valueChanged.connect(self._count_suffix)
        self.min_count_spin.valueChanged.connect(self._emit)
        count.addWidget(self.min_count_spin)
        count.addSpacing(18)
        count.addWidget(QLabel("Severity at least:"))
        self.min_sev_combo = QComboBox()
        self.min_sev_combo.addItem("Any severity", None)
        for sev in UBA_SEVERITIES:
            self.min_sev_combo.addItem(sev.capitalize(), sev)
        idx = self.min_sev_combo.findData(self._orig.get("min_severity"))
        self.min_sev_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.min_sev_combo.currentIndexChanged.connect(self._emit)
        count.addWidget(self.min_sev_combo)
        count.addStretch()
        lay.addLayout(count)

        cond_head = QHBoxLayout()
        cond_label = QLabel("Extra conditions:")
        cond_label.setMinimumWidth(110)
        cond_head.addWidget(cond_label)
        cond_help = QLabel("on the behaviour event's fields; details.<name> reads one of its details")
        _look(cond_help, role="muted")
        cond_head.addWidget(cond_help, 1)
        self.add_cond_btn = QPushButton("+ Condition")
        _look(self.add_cond_btn, variant="ghost")
        cond_head.addWidget(self.add_cond_btn)
        lay.addLayout(cond_head)

        self._orig_conditions = [c for c in (self._orig.get("conditions") or [])
                                 if isinstance(c, dict)]
        if ConditionTable is not None:
            self.conditions = ConditionTable(CONDITION_FIELDS)
            for cond in self._orig_conditions:
                self.conditions.add_row(cond)
            self.conditions.changed.connect(self._conditions_changed)
            self.add_cond_btn.clicked.connect(lambda: self.conditions.add_row())
            lay.addWidget(self.conditions)
        else:                                   # pragma: no cover - stripped host
            self.conditions = None
            self.add_cond_btn.setEnabled(False)
            ro = QLabel(", ".join(f"{c.get('field_name')} {c.get('operator', 'equals')} "
                                  f"{c.get('value')}" for c in self._orig_conditions)
                        or "None")
            _look(ro, role="mono")
            lay.addWidget(ro)

        self._actor_changed(emit=False)
        self._conditions_changed(emit=False)
        self.refresh_what()
        self._loading = False

    # ----------------------------------------------------------- state --
    def _emit(self, *_a):
        if not self._loading:
            self.changed.emit()

    def _actor_changed(self, *_a, emit=True):
        key = self.actor_combo.currentData() or "person"
        self.actor_help.setText(ACTOR_TEXT[key][1])
        if emit:
            self._emit()

    def _conditions_changed(self, emit=True):
        if self.conditions is not None:
            self.conditions.setVisible(self.conditions.table.rowCount() > 0)
        if emit:
            self._emit()

    def _count_suffix(self, *_a):
        self.min_count_spin.setSuffix(" event" if self.min_count_spin.value() == 1 else " events")

    def showEvent(self, event):
        super().showEvent(event)
        # The condition rows were measured before the theme gave the header
        # its height: fit them again, or the last row is cut off.
        if self.conditions is not None:
            self.conditions._fit()

    def set_number(self, index: int, count: int):
        self.number_label.setText(f"STEP {index + 1}")
        self.up_btn.setEnabled(index > 0)
        self.down_btn.setEnabled(index < count - 1)

    def selection(self):
        """(kind, ids) the step names now."""
        return self._kind, as_list(self._value)

    def set_selection(self, kind: str, ids: List[str]):
        """A new choice from the picker: one id is written as a string, more
        as a list (both are what the engine reads)."""
        ids = [str(i) for i in ids]
        if kind == self._kind and as_list(self._value) == ids:
            return
        self._kind = kind
        self._value = ids[0] if len(ids) == 1 else list(ids)
        self.refresh_what()
        self._emit()

    def set_catalog(self, catalog):
        self.catalog = catalog
        self.refresh_what()

    def refresh_what(self):
        while self.what_box.count():
            w = self.what_box.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        kind, ids = self.selection()
        if not ids:
            empty = QLabel("Nothing chosen yet")
            _look(empty, role="muted", status="warn")
            self.what_box.addWidget(empty)
        rules, acts = self.catalog.get("rules", {}), self.catalog.get("activities", {})
        for n, ident in enumerate(ids):
            if n:
                sep = QLabel("or")
                _look(sep, role="muted")
                self.what_box.addWidget(sep)
            if kind == "rule_id":
                row = rules.get(ident) or {}
                icon_name = "user_rule" if row.get("user_rule") else row.get("activity", "")
                text = f"{row.get('title') or ident}  ({ident})" if row else ident
            else:
                icon_name, text = ident, f"activity: {ident}"
                row = {}
            icon = activity_icon(icon_name) if icon_name else None
            if icon is not None:
                glyph = QLabel()
                glyph.setPixmap(icon.pixmap(20, 20))
                glyph.setFixedSize(22, 22)
                self.what_box.addWidget(glyph)
            lbl = QLabel(text)
            _look(lbl, role="label")
            if kind == "rule_id" and row and not row.get("enabled"):
                _look(lbl, status="neutral")
            self.what_box.addWidget(lbl)
            if row.get("user_rule"):
                chip = QLabel("Your rule")
                chip.setProperty("chip", "user_rule")
                self.what_box.addWidget(chip)
        notes = step_notes({kind: self._value}, self.catalog)
        self.state_note.setText(" ".join(notes))
        self.state_note.setVisible(bool(notes))

    # ------------------------------------------------------------ out --
    def _conditions_out(self) -> List[Dict]:
        if self.conditions is None:
            return copy.deepcopy(self._orig_conditions)
        out = []
        for i, cond in enumerate(self.conditions.conditions(feather_id="")):
            cond.pop("feather_id", None)
            orig = self._orig_conditions[i] if i < len(self._orig_conditions) else None
            if orig is not None and orig.get("field_name") == cond["field_name"] \
                    and orig.get("operator", "equals") == cond["operator"] \
                    and str(orig.get("value")) == str(cond["value"]) \
                    and bool(orig.get("negate")) == bool(cond.get("negate")):
                out.append(copy.deepcopy(orig))  # as loaded: a number stays a number
                continue
            if cond["operator"] in _NUMERIC_OPS:
                try:
                    cond["value"] = _number_out(float(cond["value"]))
                except (TypeError, ValueError):
                    pass
            out.append({k: cond[k] for k in ("field_name", "operator", "value", "negate")
                        if k in cond})
        return out

    def step(self) -> Dict:
        """The step as the engine reads it."""
        s = copy.deepcopy(self._orig)
        label = self.label_edit.text().strip()
        if label:
            _put(s, "label", label)
        else:
            s.pop("label", None)
        other = "activity" if self._kind == "rule_id" else "rule_id"
        s.pop(other, None)
        if as_list(self._value):
            _put(s, self._kind, copy.deepcopy(self._value))
        else:
            s.pop(self._kind, None)
        count = self.min_count_spin.value()
        if count != 1 or "min_count" in self._orig:
            _put(s, "min_count", count)
        sev = self.min_sev_combo.currentData()
        if sev:
            _put(s, "min_severity", sev)
        else:
            s.pop("min_severity", None)
        actor = self.actor_combo.currentData() or "person"
        if actor != "person" or "actor" in self._orig:
            _put(s, "actor", actor)
        conds = self._conditions_out()
        if conds or self._orig.get("conditions") == []:
            _put(s, "conditions", conds)
        else:
            s.pop("conditions", None)
        return s


# ------------------------------------------------------------- editor --
def _unit_for(minutes) -> int:
    """The largest unit (in minutes) the span is a whole number of."""
    try:
        m = float(minutes)
    except (TypeError, ValueError):
        return 1
    for _name, factor in reversed(UNITS):
        if m and factor > 1 and (m / factor).is_integer():
            return factor
    return 1


class _Span(QWidget):
    """A number with a unit (minutes / hours / days), read in minutes."""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(0, 1000000)
        self.spin.setDecimals(0)
        self.spin.setMinimumWidth(90)
        self.unit = QComboBox()
        for name, factor in UNITS:
            self.unit.addItem(name, factor)
        lay.addWidget(self.spin)
        lay.addWidget(self.unit)
        self.spin.valueChanged.connect(lambda _v: self.changed.emit())
        self.unit.currentIndexChanged.connect(lambda _i: self.changed.emit())

    def set_minutes(self, minutes):
        factor = _unit_for(minutes)
        amount = float(minutes) / factor if minutes is not None else 0.0
        blocked = (self.spin.blockSignals(True), self.unit.blockSignals(True))
        self.spin.setDecimals(0 if float(amount).is_integer() else 2)
        self.spin.setValue(amount)
        self.unit.setCurrentIndex(max(0, self.unit.findData(factor)))
        self.spin.blockSignals(blocked[0])
        self.unit.blockSignals(blocked[1])

    def minutes(self):
        return _number_out(self.spin.value() * (self.unit.currentData() or 1))


class BehaviourStepsEditor(QWidget):
    """The Behaviour Wing's fields (BEHAVIOUR_FIELDS) as three sections:
    the steps, their order and time range, whom it watches and its alert."""

    changed = pyqtSignal()
    status_message = pyqtSignal(str)

    DEFAULT_WITHIN = 60

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cards: List[StepCard] = []
        self.artifacts_dir: Optional[str] = None
        self.catalog = load_catalog()
        self._subject: Dict = {}
        self._alert: Dict = {}
        self._loading = False
        from ...gui.crow_eye_icons import group_title_label

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        # -- steps
        steps_box = QGroupBox()
        sl = QVBoxLayout(steps_box)
        sl.addWidget(group_title_label("engine_behaviour", "Behaviour Steps"))
        intro = QLabel(
            "A Behaviour Wing names no Feathers. It is a set of behaviour steps one person "
            "performs, in order or in any order, within a time range: UBA's behaviours, "
            "evaluated by the Behavioural engine per person (SID).")
        intro.setWordWrap(True)
        _look(intro, role="muted")
        sl.addWidget(intro)
        if self.catalog.get("problem"):
            problem = QLabel(self.catalog["problem"])
            problem.setWordWrap(True)
            _look(problem, role="note", status="warn")
            sl.addWidget(problem)
        self.steps_layout = QVBoxLayout()
        self.steps_layout.setSpacing(8)
        sl.addLayout(self.steps_layout)
        self.empty_label = QLabel("No steps yet. Add one, then choose its behaviour.")
        _look(self.empty_label, role="muted")
        sl.addWidget(self.empty_label)
        row = QHBoxLayout()
        self.add_step_btn = QPushButton("+ Add Step")
        _look(self.add_step_btn, variant="primary")
        self.add_step_btn.clicked.connect(lambda: self.add_step())
        row.addWidget(self.add_step_btn)
        self.new_behaviour_btn = QPushButton("New behaviour...")
        _look(self.new_behaviour_btn, variant="ghost")
        self.new_behaviour_btn.clicked.connect(self.new_behaviour_step)
        row.addWidget(self.new_behaviour_btn)
        row.addStretch()
        sl.addLayout(row)
        outer.addWidget(steps_box)
        self.steps_box = steps_box

        # -- order and time range
        time_box = QGroupBox()
        tl = QVBoxLayout(time_box)
        tl.addWidget(group_title_label("clock", "Order and Time Range"))
        self.ordered_cb = QCheckBox("In order: each step happens after the one before")
        self.ordered_cb.setChecked(True)
        self.ordered_cb.toggled.connect(self._ordered_changed)
        tl.addWidget(self.ordered_cb)
        within_row = QHBoxLayout()
        within_label = QLabel("Within:")
        within_label.setMinimumWidth(110)
        within_row.addWidget(within_label)
        self.within = _Span()
        self.within.changed.connect(self._emit)
        within_row.addWidget(self.within)
        within_help = QLabel("the whole set fits in this span")
        _look(within_help, role="muted")
        within_row.addWidget(within_help)
        within_row.addStretch()
        tl.addLayout(within_row)
        gap_row = QHBoxLayout()
        self.gap_cb = QCheckBox("Max gap between steps:")
        self.gap_cb.setMinimumWidth(110)
        self.gap_cb.toggled.connect(self._gap_toggled)
        gap_row.addWidget(self.gap_cb)
        self.gap = _Span()
        self.gap.changed.connect(self._emit)
        gap_row.addWidget(self.gap)
        self.gap_help = QLabel("between one step and the next (steps in order only)")
        _look(self.gap_help, role="muted")
        gap_row.addWidget(self.gap_help)
        gap_row.addStretch()
        tl.addLayout(gap_row)
        outer.addWidget(time_box)
        self.time_box = time_box

        # -- subject and alert
        who_box = QGroupBox()
        wl = QVBoxLayout(who_box)
        wl.addWidget(group_title_label("target", "Whom It Watches and the Alert"))
        scope_row = QHBoxLayout()
        scope_label = QLabel("Watches:")
        scope_label.setMinimumWidth(110)
        scope_row.addWidget(scope_label)
        self.scope_combo = QComboBox()
        for key in SUBJECT_SCOPES:
            self.scope_combo.addItem(SCOPE_TEXT[key], key)
        self.scope_combo.currentIndexChanged.connect(self._scope_changed)
        scope_row.addWidget(self.scope_combo)
        self.scope_edit = QLineEdit()
        self.scope_edit.textChanged.connect(self._emit)
        scope_row.addWidget(self.scope_edit, 1)
        scope_row.addStretch()
        wl.addLayout(scope_row)
        self.service_cb = QCheckBox("Include service accounts (SYSTEM, LOCAL SERVICE, "
                                    "NETWORK SERVICE are evaluated as people too)")
        self.service_cb.toggled.connect(self._emit)
        wl.addWidget(self.service_cb)

        alert_row = QHBoxLayout()
        alert_label = QLabel("Alert severity:")
        alert_label.setMinimumWidth(110)
        alert_row.addWidget(alert_label)
        self.severity_combo = QComboBox()
        for sev in ALERT_SEVERITIES:
            self.severity_combo.addItem(sev.capitalize(), sev)
        self.severity_combo.currentIndexChanged.connect(self._emit)
        alert_row.addWidget(self.severity_combo)
        alert_row.addSpacing(18)
        alert_row.addWidget(QLabel("ATT&CK technique:"))
        self.technique_edit = QLineEdit()
        self.technique_edit.setPlaceholderText("e.g. T1070.001, T1078")
        self.technique_edit.textChanged.connect(self._emit)
        alert_row.addWidget(self.technique_edit, 1)
        alert_row.addSpacing(12)
        alert_row.addWidget(QLabel("Tactic:"))
        self.tactic_edit = QLineEdit()
        self.tactic_edit.setPlaceholderText("e.g. defense-evasion")
        self.tactic_edit.textChanged.connect(self._emit)
        alert_row.addWidget(self.tactic_edit, 1)
        wl.addLayout(alert_row)
        outer.addWidget(who_box)
        self.who_box = who_box

        self._update_new_behaviour_tip()
        self.set_behaviour({})

    # ------------------------------------------------------------ load --
    def set_artifacts_dir(self, artifacts_dir: Optional[str]):
        self.artifacts_dir = artifacts_dir if artifacts_dir and os.path.isdir(artifacts_dir) else None
        self._update_new_behaviour_tip()

    def _update_new_behaviour_tip(self):
        tip = ("Create a behaviour rule of your own in the Behaviour Rule Creator, then use "
               "it as a new step.")
        if not self.artifacts_dir:
            tip += (" No case is open here, so a rule from a table cannot be tested on one; "
                    "a rule from a behaviour can still be made.")
        self.new_behaviour_btn.setToolTip(tip)

    def set_behaviour(self, fields: Dict):
        """Show a Wing's behaviour fields (behaviour_fields_of)."""
        fields = fields or {}
        self._loading = True
        try:
            for card in list(self.cards):
                self._drop_card(card)
            for step in fields.get("steps") or []:
                self._add_card(step if isinstance(step, dict) else {})
            self.ordered_cb.setChecked(fields.get("ordered") is not False)
            within = fields.get("within_minutes")
            self.within.set_minutes(within if within not in (None, "") else self.DEFAULT_WITHIN)
            gap = fields.get("max_gap_minutes")
            self.gap_cb.setChecked(gap is not None)
            self.gap.set_minutes(gap if gap is not None else 30)
            self._subject = copy.deepcopy(fields.get("subject") or {})
            scope = self._subject.get("scope", "everyone") or "everyone"
            self.scope_combo.setCurrentIndex(max(0, self.scope_combo.findData(scope)))
            self.scope_edit.setText(", ".join(as_list(self._subject.get(scope)))
                                    if scope != "everyone" else "")
            self.service_cb.setChecked(bool(self._subject.get("include_service_accounts")))
            self._alert = copy.deepcopy(fields.get("alert") or {})
            sev = self._alert.get("severity") or "medium"
            self.severity_combo.setCurrentIndex(max(0, self.severity_combo.findData(sev)))
            self.technique_edit.setText(", ".join(as_list(self._alert.get("technique_id"))))
            self.tactic_edit.setText(", ".join(as_list(self._alert.get("tactic"))))
            self._renumber()
            self._ordered_changed(emit=False)
            self._scope_changed(emit=False)
        finally:
            self._loading = False

    # ------------------------------------------------------------- out --
    def steps(self) -> List[Dict]:
        return [c.step() for c in self.cards]

    def behaviour(self) -> Dict:
        """The Wing's behaviour fields as the engine reads them."""
        ordered = self.ordered_cb.isChecked()
        subject = copy.deepcopy(self._subject)
        scope = self.scope_combo.currentData() or "everyone"
        subject["scope"] = scope
        if scope != "everyone":
            subject[scope] = _split_list(self.scope_edit.text())
        if self.service_cb.isChecked() or "include_service_accounts" in self._subject \
                or not self._subject:
            subject["include_service_accounts"] = self.service_cb.isChecked()
        alert = copy.deepcopy(self._alert)
        alert["severity"] = self.severity_combo.currentData()
        for key, edit in (("technique_id", self.technique_edit), ("tactic", self.tactic_edit)):
            values = _split_list(edit.text())
            if values or key in self._alert:
                alert[key] = values
        out = {
            "steps": self.steps(),
            "ordered": ordered,
            "within_minutes": self.within.minutes(),
            "max_gap_minutes": self.gap.minutes() if (ordered and self.gap_cb.isChecked()) else None,
            "subject": subject,
            "alert": alert,
        }
        assert tuple(out) == BEHAVIOUR_FIELDS
        return out

    # ----------------------------------------------------------- steps --
    def _emit(self, *_a):
        if not self._loading:
            self.changed.emit()

    def _add_card(self, step: Dict) -> StepCard:
        card = StepCard(step, self.catalog)
        card.changed.connect(self._emit)
        card.move_requested.connect(self.move_step)
        card.remove_requested.connect(self.remove_step)
        card.choose_requested.connect(self.choose_behaviour)
        self.cards.append(card)
        self.steps_layout.addWidget(card)
        return card

    def _drop_card(self, card: StepCard):
        if card in self.cards:
            self.cards.remove(card)
        self.steps_layout.removeWidget(card)
        card.setParent(None)
        card.deleteLater()

    def _renumber(self):
        for i, card in enumerate(self.cards):
            card.set_number(i, len(self.cards))
        self.empty_label.setVisible(not self.cards)

    def _theme_part(self, widget):
        win = self.window()
        if _theme is not None and win is not None and win.property("siteTheme"):
            extra = getattr(win, "_theme_extra", None)
            _theme.apply_theme(win, root=widget, extra=extra if extra is not None else EDITOR_QSS)

    def add_step(self, step: Optional[Dict] = None, choose: bool = True) -> StepCard:
        """A new step at the end; with ``choose`` the picker opens for it."""
        card = self._add_card(dict(step or {}))
        self._renumber()
        self._theme_part(card)
        self._emit()
        if choose and not (step or {}).get("rule_id") and not (step or {}).get("activity"):
            self.choose_behaviour(card)
        return card

    def remove_step(self, card: StepCard):
        self._drop_card(card)
        self._renumber()
        self._emit()

    def move_step(self, card: StepCard, delta: int):
        i = self.cards.index(card)
        j = i + delta
        if not 0 <= j < len(self.cards):
            return
        self.cards[i], self.cards[j] = self.cards[j], self.cards[i]
        for c in self.cards:
            self.steps_layout.removeWidget(c)
        for c in self.cards:
            self.steps_layout.addWidget(c)
        self._renumber()
        self._emit()

    def picker_for(self, card: StepCard) -> BehaviourPickerDialog:
        kind, ids = card.selection()
        name = f"step {self.cards.index(card) + 1}" if card in self.cards else "this step"
        return BehaviourPickerDialog(self.window(), self.catalog, kind, ids,
                                     on_new_behaviour=self.create_behaviour, step_name=name)

    def choose_behaviour(self, card: StepCard):
        dlg = self.picker_for(card)
        if dlg.exec_() == QDialog.Accepted and dlg.selected:
            if dlg.catalog is not self.catalog:
                self.refresh_catalog(dlg.catalog)
            card.set_selection(dlg.kind, dlg.selected)
        elif dlg.catalog is not self.catalog:
            self.refresh_catalog(dlg.catalog)

    # ------------------------------------------------------ new behaviour --
    def refresh_catalog(self, catalog: Optional[Dict] = None):
        self.catalog = catalog or load_catalog()
        for card in self.cards:
            card.set_catalog(self.catalog)
            self._theme_part(card)

    def create_behaviour(self) -> Optional[str]:
        """Open the Behaviour Rule Creator (uba/ui/behaviour_rule_dialog.py).
        Returns the id of the rule saved there, or None."""
        try:
            from uba.ui.behaviour_rule_dialog import open_behaviour_rule_creator
        except Exception as e:
            QMessageBox.warning(self, "Behaviour Rule Creator",
                                f"The Behaviour Rule Creator could not be opened: {e}")
            return None
        result = open_behaviour_rule_creator(self.window(), self.artifacts_dir,
                                             rule_id=None, kind=None, store=None,
                                             offer_rerun=False)
        saved = (result or {}).get("saved") or {}
        new_id = saved.get("id") if isinstance(saved, dict) else None
        if new_id:
            self.refresh_catalog()
            self.status_message.emit(f"Behaviour rule saved: {new_id}")
        return new_id

    def new_behaviour_step(self):
        """New behaviour...: create a rule, then use it as a new step (or as
        the behaviour of the last step, when that has none yet)."""
        new_id = self.create_behaviour()
        if not new_id:
            return
        last = self.cards[-1] if self.cards else None
        if last is not None and not last.selection()[1]:
            last.set_selection("rule_id", [new_id])
        else:
            self.add_step({"rule_id": new_id}, choose=False)

    # ---------------------------------------------------------- toggles --
    def _ordered_changed(self, *_a, emit=True):
        ordered = self.ordered_cb.isChecked()
        self.gap_cb.setEnabled(ordered)
        self.gap.setEnabled(ordered and self.gap_cb.isChecked())
        self.gap_help.setText("between one step and the next" if ordered
                              else "applies only to steps in order")
        if emit:
            self._emit()

    def _gap_toggled(self, *_a):
        self.gap.setEnabled(self.ordered_cb.isChecked() and self.gap_cb.isChecked())
        self._emit()

    def _scope_changed(self, *_a, emit=True):
        scope = self.scope_combo.currentData() or "everyone"
        self.scope_edit.setVisible(scope != "everyone")
        placeholder = {"accounts": "user names, comma-separated (e.g. alice, CONTOSO\\bob)",
                       "sids": "SIDs, comma-separated (e.g. S-1-5-21-...-1001)",
                       "groups": "local group names, comma-separated (e.g. Administrators)"}
        self.scope_edit.setPlaceholderText(placeholder.get(scope, ""))
        if emit and not self._loading:
            # The list shown is the chosen scope's own.
            self._loading = True
            self.scope_edit.setText(", ".join(as_list(self._subject.get(scope)))
                                    if scope != "everyone" else "")
            self._loading = False
            self._emit()
