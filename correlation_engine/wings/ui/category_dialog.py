"""
Wing category picker.

Each Wing has one category, and the category decides the one engine that runs
it. Wings saved before categories existed have none; the Wing Creator asks for
it with this dialog when such a Wing is opened, before it is edited, because
an uncategorised Wing does not run at all.
"""

from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QButtonGroup, QDialog, QDialogButtonBox, QLabel, QPushButton, QRadioButton,
    QVBoxLayout,
)

try:
    from ui import app_theme as _theme
except Exception:
    _theme = None

from ...config.wing_config import (
    WING_CATEGORY_BEHAVIOUR, WING_CATEGORY_IDENTITY, WING_CATEGORY_TIME,
)

CATEGORY_CHOICES = (
    (WING_CATEGORY_TIME, "Time Wing",
     "Runs on the Time-Window engine: traces from different artifacts that fall "
     "inside one time window. Plain match rules only."),
    (WING_CATEGORY_IDENTITY, "Identity Wing",
     "Runs on the Identity engine: everything recorded about one program or file. "
     "Supports absence, sequence and threshold rules."),
    (WING_CATEGORY_BEHAVIOUR, "Behaviour Wing",
     "Runs on the Behavioural engine over UBA's behaviour events, per person. "
     "Names no Feathers: its steps are UBA behaviours, in order or not, within a time range."),
)


class WingCategoryDialog(QDialog):
    """Modal: choose Time, Identity or Behaviour for one Wing."""

    def __init__(self, wing_name: str, has_advanced_rules: bool = False,
                 current: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose the Wing's category")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._choice = None
        if _theme is not None:
            _theme.begin_theme(self)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        title = QLabel(f"“{wing_name or 'This Wing'}” has no category")
        if _theme is not None:
            _theme.set_role(title, "section")
        layout.addWidget(title)
        intro = QLabel("A Wing runs on exactly one engine, chosen by its category. "
                       "Until it has one it is listed under “Needs a category” "
                       "and does not run.")
        intro.setWordWrap(True)
        if _theme is not None:
            _theme.set_role(intro, "muted")
        layout.addWidget(intro)

        from ...gui.crow_eye_icons import pair_icon_size, wing_icon
        self._group = QButtonGroup(self)
        self._buttons = {}
        for key, label, help_text in CATEGORY_CHOICES:
            radio = QRadioButton(label)
            radio.setIcon(wing_icon(key))  # the wing, then the engine that runs it
            radio.setIconSize(pair_icon_size(16))
            radio.setProperty("category", key)
            self._group.addButton(radio)
            self._buttons[key] = radio
            layout.addWidget(radio)
            note = QLabel(help_text)
            note.setWordWrap(True)
            note.setContentsMargins(26, 0, 0, 4)
            if _theme is not None:
                _theme.set_role(note, "muted")
            layout.addWidget(note)

        if has_advanced_rules:
            self._buttons[WING_CATEGORY_TIME].setEnabled(False)
            self._buttons[WING_CATEGORY_TIME].setToolTip(
                "This Wing has advanced rules, which the Time-Window engine cannot evaluate.")
            warn = QLabel("This Wing has advanced rules (absence, sequence, threshold, nested "
                          "or cross-feather), so it cannot be a Time Wing.")
            warn.setWordWrap(True)
            if _theme is not None:
                _theme.set_role(warn, "note")
                _theme.set_status(warn, "warn")
            layout.addWidget(warn)

        suggested = current or (WING_CATEGORY_IDENTITY if has_advanced_rules else None)
        if suggested in self._buttons and self._buttons[suggested].isEnabled():
            self._buttons[suggested].setChecked(True)

        box = QDialogButtonBox()
        self._ok = QPushButton("Use this category")
        cancel = QPushButton("Not now")
        if _theme is not None:
            _theme.set_variant(self._ok, "primary")
            _theme.set_variant(cancel, "ghost")
        box.addButton(self._ok, QDialogButtonBox.AcceptRole)
        box.addButton(cancel, QDialogButtonBox.RejectRole)
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self._group.buttonToggled.connect(lambda *_a: self._sync())
        self._sync()
        if _theme is not None:
            _theme.apply_theme(self)

    def _sync(self):
        self._ok.setEnabled(self._group.checkedButton() is not None)

    def _accept(self):
        button = self._group.checkedButton()
        if button is None:
            return
        self._choice = button.property("category")
        self.accept()

    def choice(self) -> Optional[str]:
        return self._choice


def ask_wing_category(parent, wing_name: str, has_advanced_rules: bool = False) -> Optional[str]:
    """The category the analyst chose, or None if they put it off."""
    dialog = WingCategoryDialog(wing_name, has_advanced_rules, parent=parent)
    if dialog.exec_() == QDialog.Accepted:
        return dialog.choice()
    return None
