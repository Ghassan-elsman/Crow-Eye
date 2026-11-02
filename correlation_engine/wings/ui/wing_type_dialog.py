"""
What kind of Wing? The first step of creating one.

A Wing runs on exactly one engine, chosen by its category, and most of the
Wing Creator's form follows from it: Time and Identity Wings name Feathers and
a time window, a Behaviour Wing names UBA behaviour steps and no Feathers, and
only Identity carries advanced rules. Choosing the type first lets the Creator
open with only the sections that type uses, instead of a long form whose
meaning changes when a combo box at its top is set.

Three cards, one per type: the Wing and engine icon pair, the name, what the
type finds, what it needs, and the engine that runs it. A click picks a card,
a double-click or Enter creates; the Creator's header keeps a chip that opens
this dialog again to change the type.
"""

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

try:
    from ui import app_theme as _theme
except Exception:
    _theme = None

from ...config.wing_config import (
    WING_CATEGORY_BEHAVIOUR, WING_CATEGORY_IDENTITY, WING_CATEGORY_TIME,
)

# key -> (name, what it finds, what it needs, engine, colour). The colours are
# the engine icons' own (crow_eye_icons engine_time / engine_identity /
# engine_behaviour), so a card and the icon on it agree.
TYPES = (
    (WING_CATEGORY_TIME, "Time Wing",
     "Traces from different artifacts that fall inside one time window: what happened "
     "together, at the same moment.",
     "Two or more Feathers. Plain match rules.",
     "Time-Window engine", "#4ADE80"),
    (WING_CATEGORY_IDENTITY, "Identity Wing",
     "Everything recorded about one program, file or account across the artifacts, "
     "grouped around each time it was seen.",
     "Two or more Feathers. Also absence, sequence and threshold rules.",
     "Identity engine", "#60A5FA"),
    (WING_CATEGORY_BEHAVIOUR, "Behaviour Wing",
     "A person's behaviour from User Behavior: steps in order or in any order, within "
     "a time range, with an alert when they all happen.",
     "The case's User Behavior analysis. No Feathers.",
     "Behavioural engine", "#A78BFA"),
)

CARD_QSS = """
QFrame#wingTypeCard { background: #111A2C; border: 1px solid #24324A; border-radius: 14px; }
QFrame#wingTypeCard[hover="true"] { border: 1px solid %(c)s; background: #142036; }
QFrame#wingTypeCard[checked="true"] { border: 2px solid %(c)s; background: %(tint)s; }
QFrame#wingTypeCard:disabled { border-color: #1E293B; background: #0D1422; }
QFrame#wingTypeCard QLabel { background: transparent; border: none; }
"""


def _tint(colour, alpha=0.12):
    c = QColor(colour)
    return "rgba(%d, %d, %d, %.2f)" % (c.red(), c.green(), c.blue(), alpha)


class _Card(QFrame):
    """One type: a frame (the theme flattens a QPushButton's padding and
    height) picked by a click and chosen by a double-click. It keeps its own
    sheet: apply_theme clears inline sheets outside a keepTree."""

    picked = pyqtSignal(object)
    chosen = pyqtSignal(object)

    def __init__(self, key, colour):
        super().__init__()
        self.key = key
        self.setObjectName("wingTypeCard")
        self.setProperty("keepStyle", True)
        self.setProperty("keepTree", True)
        self.setProperty("checked", False)
        self.setProperty("hover", False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(CARD_QSS % {"c": colour, "tint": _tint(colour)})

    def _restyle(self):
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def isChecked(self):
        return bool(self.property("checked"))

    def setChecked(self, on):
        self.setProperty("checked", bool(on))
        self._restyle()

    def enterEvent(self, event):
        self.setProperty("hover", self.isEnabled())
        self._restyle()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setProperty("hover", False)
        self._restyle()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if self.isEnabled() and event.button() == Qt.LeftButton:
            self.picked.emit(self)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.isEnabled():
            self.picked.emit(self)
            self.chosen.emit(self)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and self.isEnabled():
            self.picked.emit(self)
            return
        super().keyPressEvent(event)


class WingTypeDialog(QDialog):
    """Modal: the three Wing types as cards; `choice()` is the picked key."""

    def __init__(self, parent=None, current: Optional[str] = None, has_advanced_rules: bool = False,
                 changing: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Change the Wing's type" if changing else "New Wing")
        self.setModal(True)
        self.setMinimumWidth(860)
        self._choice = None
        if _theme is not None:
            _theme.begin_theme(self)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(22, 20, 22, 18)
        title = QLabel("What kind of Wing?")
        if _theme is not None:
            _theme.set_role(title, "title")
        layout.addWidget(title)
        intro = QLabel("A Wing runs on one engine, and its type decides which. The Wing Creator "
                       "then shows only what that type uses." if not changing else
                       "Changing the type changes the engine that runs this Wing and the sections "
                       "the Creator shows. What you entered is kept.")
        intro.setWordWrap(True)
        if _theme is not None:
            _theme.set_role(intro, "muted")
        layout.addWidget(intro)

        from ...gui.crow_eye_icons import pair_icon_size, wing_icon
        row = QHBoxLayout()
        row.setSpacing(14)
        self._cards = {}
        for key, name, finds, needs, engine, colour in TYPES:
            card = _Card(key, colour)
            card.setMinimumSize(250, 250)
            card.picked.connect(self._pick)
            card.chosen.connect(lambda _c: self._accept())
            inner = QVBoxLayout(card)
            inner.setContentsMargins(18, 18, 18, 18)
            inner.setSpacing(10)
            icon = QLabel()
            icon.setPixmap(wing_icon(key).pixmap(pair_icon_size(30)))
            label = QLabel(name)
            label.setStyleSheet("font-size: 18px; font-weight: 600; color: %s;" % colour)
            what = QLabel(finds)
            what.setWordWrap(True)
            what.setStyleSheet("font-size: 13px; color: #E2E8F0;")
            need = QLabel("<b>Needs</b>&nbsp; " + needs)
            need.setWordWrap(True)
            need.setStyleSheet("font-size: 12px; color: #94A3B8;")
            run = QLabel("<b>Runs on</b>&nbsp; the " + engine)
            run.setStyleSheet("font-size: 12px; color: #94A3B8;")
            for w in (icon, label, what, need, run):
                # The card takes the click, whichever line was under the pointer.
                w.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                inner.addWidget(w)
            inner.addStretch(1)
            if key == WING_CATEGORY_TIME and has_advanced_rules:
                # Said on the card itself: a tooltip alone hides why it is greyed.
                card.setEnabled(False)
                label.setStyleSheet("font-size: 18px; font-weight: 600; color: #64748B;")
                why = QLabel("Not available: this Wing has advanced rules, which the "
                             "Time-Window engine cannot evaluate.")
                why.setWordWrap(True)
                why.setStyleSheet("font-size: 12px; color: #F59E0B;")
                inner.insertWidget(inner.count() - 1, why)
            self._cards[key] = card
            row.addWidget(card, 1)
        layout.addLayout(row)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        self._ok = QPushButton("Change type" if changing else "Create Wing")
        self._ok.setDefault(True)
        if _theme is not None:
            _theme.set_variant(self._ok, "primary")
            _theme.set_variant(cancel, "ghost")
        cancel.clicked.connect(self.reject)
        self._ok.clicked.connect(self._accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self._ok)
        layout.addLayout(buttons)

        if current in self._cards and self._cards[current].isEnabled():
            self._pick(self._cards[current])
            self._cards[current].setFocus()
        self._sync()
        if _theme is not None:
            _theme.apply_theme(self)

    def _checked(self):
        return next((c for c in self._cards.values() if c.isChecked()), None)

    def _sync(self):
        self._ok.setEnabled(self._checked() is not None)

    def _pick(self, card):
        for other in self._cards.values():
            other.setChecked(other is card)
        self._sync()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            focused = self.focusWidget()
            if focused in self._cards.values() and focused.isEnabled():
                self._pick(focused)
            self._accept()
            return
        super().keyPressEvent(event)

    def _accept(self):
        card = self._checked()
        if card is None:
            return
        self._choice = card.key
        self.accept()

    def choice(self) -> Optional[str]:
        return self._choice


def choose_wing_type(parent=None, current: Optional[str] = None, has_advanced_rules: bool = False,
                     changing: bool = False) -> Optional[str]:
    """The type picked, or None when cancelled."""
    dialog = WingTypeDialog(parent, current, has_advanced_rules, changing)
    if dialog.exec_() == QDialog.Accepted:
        return dialog.choice()
    return None
