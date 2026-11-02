"""
Settings -> User Behavior: an on/off switch for every behaviour rule.

One saved setting behind two screens: this page and the Rules view of the
User Behavior window both edit ``uba_disabled_rules`` in global_config.json
(uba/engine/rule_switches.py). A rule that is off is not looked for in any
case; the coverage page lists it as "Turned off in Settings", never as
"nothing found", and Eye's query_user_behavior names it as turned off.

The page follows the dialog's Save / Cancel: switches change nothing until
Save, and Save applies only the switches flipped here, onto the setting as it
is then - so a rule switched in the User Behavior window while this dialog was
open is not put back.

Colour has one meaning each: green = on (looked for), slate = off. Severity
chips use the User Behavior window's own palette (react-uba
src/styles/tokens.js SEVERITY_STYLE), so a severity looks the same in both
places; the switches are never red, because turning a rule off is a choice,
not an alarm.
"""

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt

from styles import CrowEyeStyles
from ui.app_theme import (keep_style, set_role, set_severity, set_status, set_variant,
                          STATUS_COLORS)

_SEVERITIES = ("routine", "notable", "suspicious", "critical")

_ON = QtGui.QColor(STATUS_COLORS["ok"])
_ON_TRACK = QtGui.QColor(74, 222, 128, 60)
_OFF_TRACK = QtGui.QColor("#1E293B")
_OFF_KNOB = QtGui.QColor("#94A3B8")
_EDGE = QtGui.QColor(255, 255, 255, 36)
# Violet marks an analyst's own rule and nothing else - the same chip as the
# User Behavior window's "Your rule" badge (react-uba app.css .rule-badge)
# beside the same violet user_rule icon.
_USER_RULE_CHIP = ("QLabel { color: #A78BFA; background: rgba(139, 92, 246, 0.16); "
                   "border-radius: 9px; padding: 2px 10px; font-weight: 700; font-size: 11px; }")


class RuleSwitch(QtWidgets.QAbstractButton):
    """A two-state switch: a track and a knob, painted (not a QSS checkbox,
    which cannot draw one). Checkable, so keyboard and accessibility work as
    for any button: Space toggles it, and it reports its checked state."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(40, 22)

    def sizeHint(self):
        return QtCore.QSize(40, 22)

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        on = self.isChecked()
        rect = QtCore.QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QtGui.QPen(_ON if on else _EDGE, 1))
        p.setBrush(_ON_TRACK if on else _OFF_TRACK)
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        d = self.height() - 6
        x = self.width() - d - 3 if on else 3
        p.setPen(Qt.NoPen)
        knob = QtGui.QColor(_ON if on else _OFF_KNOB)
        if not self.isEnabled():
            knob.setAlpha(110)
        p.setBrush(knob)
        p.drawEllipse(QtCore.QRectF(x, 3, d, d))
        if self.hasFocus():
            p.setPen(QtGui.QPen(QtGui.QColor("#818CF8"), 1, Qt.DotLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.end()


class UserBehaviorSettingsPage(QtWidgets.QScrollArea):
    """The page itself. ``apply()`` is called from SettingsDialog.save_settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._switches = {}          # rule_id -> RuleSwitch
        self._rows = {}              # rule_id -> (row widget, search text)
        self._groups = []            # (group box, [rule ids])
        self._initial_off = set()
        self._error = ""
        self._build()

    # ------------------------------------------------------------------ #
    def _build(self):
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(16)

        header = QtWidgets.QLabel("User Behavior")
        set_role(header, "title")
        layout.addWidget(header)

        blurb = QtWidgets.QLabel(
            "Every behaviour rule User Behavior looks for. Turn a rule off and it "
            "is not looked for in any case: the User Behavior window lists it as "
            "\"Turned off in Settings\" rather than \"nothing found\", and Eye says "
            "so too, because a rule that did not run is no evidence that the "
            "behaviour did not happen.\n\n"
            "The same switches are in the User Behavior window, under Rules. A "
            "change takes effect the next time a case is analysed - the stored "
            "analysis of each case is rebuilt when the switches differ from the "
            "ones it was built with.")
        blurb.setWordWrap(True)
        set_role(blurb, "muted")
        layout.addWidget(blurb)

        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(10)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search rules")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(240)
        self.search.textChanged.connect(self._filter)
        bar.addWidget(self.search, 1)
        self.count_label = QtWidgets.QLabel("")
        bar.addWidget(self.count_label)
        self.all_on_btn = QtWidgets.QPushButton("Turn all on")
        self.all_on_btn.setCursor(Qt.PointingHandCursor)
        set_variant(self.all_on_btn, "ghost")
        self.all_on_btn.clicked.connect(self._turn_all_on)
        bar.addWidget(self.all_on_btn)
        layout.addLayout(bar)

        try:
            from uba.engine import rule_switches
            rows = rule_switches.switch_rows()
            self._initial_off = rule_switches.disabled_rule_ids()
        except Exception as e:                 # the rules file failed to load
            rows = []
            self._error = str(e)
            note = QtWidgets.QLabel("The behaviour rules could not be loaded: %s" % e)
            note.setWordWrap(True)
            set_role(note, "note")
            set_status(note, "warn")
            layout.addWidget(note)

        by_class = {}
        for row in rows:
            by_class.setdefault(row["class_label"], []).append(row)
        for label, members in by_class.items():
            box = QtWidgets.QGroupBox("%s (%d)" % (label, len(members)))
            box_layout = QtWidgets.QVBoxLayout(box)
            box_layout.setContentsMargins(14, 18, 14, 10)
            box_layout.setSpacing(2)
            for row in members:
                box_layout.addWidget(self._rule_row(row))
            layout.addWidget(box)
            self._groups.append((box, [r["rule_id"] for r in members]))

        layout.addStretch()
        self.setWidget(panel)
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._update_count()

    def _rule_row(self, rule):
        row = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(4, 6, 4, 6)
        h.setSpacing(12)

        switch = RuleSwitch()
        switch.setChecked(bool(rule["enabled"]))
        switch.setToolTip("On: looked for in every case. Off: not looked for.")
        switch.setAccessibleName(rule["title"])
        switch.toggled.connect(lambda _on, rid=rule["rule_id"]: self._on_toggled(rid))
        h.addWidget(switch, 0, Qt.AlignVCenter)

        # The same drawing the User Behavior window shows for this behaviour
        # (uba/icons/activity, exported from react-uba's activityIcons.js).
        icon_name = "user_rule" if rule.get("user_rule") else rule.get("activity", "")
        icon = CrowEyeStyles.resource_icon("uba", "icons", "activity", f"{icon_name}.svg")
        if icon is not None:
            glyph = QtWidgets.QLabel()
            glyph.setPixmap(icon.pixmap(22, 22))
            glyph.setFixedSize(24, 24)
            h.addWidget(glyph, 0, Qt.AlignVCenter)

        text = QtWidgets.QVBoxLayout()
        text.setSpacing(1)
        title = QtWidgets.QLabel(rule["title"])
        set_role(title, "label")
        text.addWidget(title)
        rid = QtWidgets.QLabel(rule["rule_id"])
        set_role(rid, "mono")
        text.addWidget(rid)
        if rule.get("invalid"):
            # A rule of yours that fails validation is listed, never hidden,
            # with the reason it does not run.
            why = QtWidgets.QLabel("Not valid, so not run: " + " ".join(rule["invalid"]))
            why.setWordWrap(True)
            set_status(why, "warn")
            text.addWidget(why)
        h.addLayout(text, 1)

        if rule.get("user_rule"):
            badge = QtWidgets.QLabel("Your rule")
            badge.setToolTip("A behaviour rule you created (%s rule), saved for every case."
                             % ("table" if rule.get("user_kind") == "table" else "derived"))
            keep_style(badge)
            badge.setStyleSheet(_USER_RULE_CHIP)
            h.addWidget(badge, 0, Qt.AlignVCenter)

        sev = QtWidgets.QLabel(str(rule["severity"]).capitalize())
        sev.setMinimumWidth(78)
        sev.setAlignment(Qt.AlignCenter)
        set_severity(sev, rule["severity"] if rule["severity"] in _SEVERITIES else "routine")
        h.addWidget(sev, 0, Qt.AlignVCenter)

        self._switches[rule["rule_id"]] = switch
        self._rows[rule["rule_id"]] = (
            row, title, " ".join([rule["title"], rule["rule_id"], rule.get("activity", ""),
                                  rule.get("class_label", "")]).lower())
        self._style_row(rule["rule_id"])
        return row

    # ------------------------------------------------------------------ #
    def _style_row(self, rule_id):
        _row, title, _text = self._rows[rule_id]
        on = self._switches[rule_id].isChecked()
        # Off rows read quieter (slate text, same size); the switch already
        # says which. Colour through the theme's status property, never a
        # per-widget sheet or font, which a later theme pass would undo.
        set_status(title, None if on else "neutral")

    def _on_toggled(self, rule_id):
        self._style_row(rule_id)
        self._update_count()

    def _turn_all_on(self):
        for switch in self._switches.values():
            if not switch.isChecked():
                switch.setChecked(True)

    def _filter(self, text):
        needle = (text or "").strip().lower()
        shown = set()
        for rule_id, (row, _title, hay) in self._rows.items():
            match = not needle or needle in hay
            row.setVisible(match)
            if match:
                shown.add(rule_id)
        for box, ids in self._groups:
            box.setVisible(any(r in shown for r in ids))

    def _update_count(self):
        total = len(self._switches)
        off = sum(1 for s in self._switches.values() if not s.isChecked())
        if off:
            self.count_label.setText("%d of %d rules off" % (off, total))
            set_status(self.count_label, "accent")
        else:
            self.count_label.setText("All %d rules on" % total)
            set_status(self.count_label, "neutral")
        self.all_on_btn.setEnabled(off > 0)

    # ------------------------------------------------------------------ #
    def changes(self):
        """{rule_id: on} for every switch flipped since the page opened."""
        out = {}
        for rule_id, switch in self._switches.items():
            was_on = rule_id not in self._initial_off
            if switch.isChecked() != was_on:
                out[rule_id] = switch.isChecked()
        return out

    def apply(self):
        """Save the flipped switches onto the setting as it is now. True when
        there was nothing to save or the save worked."""
        changed = self.changes()
        if not changed:
            return True
        from uba.engine import rule_switches
        off = rule_switches.disabled_rule_ids()
        for rule_id, on in changed.items():
            if on:
                off.discard(rule_id)
            else:
                off.add(rule_id)
        saved = rule_switches.set_disabled_rules(off)
        if saved:
            self._initial_off = set(off)
        return saved
