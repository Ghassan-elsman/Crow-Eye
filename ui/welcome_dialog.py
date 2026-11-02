"""The welcome an investigator sees the first time Crow-Eye starts.

Three steps to a first result, a way to the User Guide on crow-eye.com, and a
send-off. Shown once (the global setting ``welcome_shown``), never on a
relaunch into a case (elevation or update) and never under tests; Help ->
Welcome... opens it again.
"""
import os

from PyQt5 import QtCore, QtGui, QtWidgets

USER_GUIDE_URL = "https://crow-eye.com/user-guide"
SETTING = "welcome_shown"

STEPS = (
    ("Create a case",
     "Every investigation lives in a case: one folder for the evidence, the parsed artifacts, "
     "the logs and the chain of custody."),
    ("Parse all Artifacts",
     "Parse this machine in one click, or bring evidence in from a forensic image, a collected "
     "folder or third-party output from the Offline Analysis tools."),
    ("Read what it found",
     "The artifact tables, the Timeline, User Behavior and Correlation each tell part of the "
     "story, and the Eye answers questions about the case."),
)

QSS = """
QDialog#WelcomeDialog { background: #0A0C10; }
QLabel#WelcomeKicker { color: #22D3EE; letter-spacing: 1px; }
QLabel#WelcomeTitle { color: #F8FAFC; }
QLabel#WelcomeLead, QLabel#WelcomeStepText { color: #CBD5E1; }
QLabel#WelcomeStepTitle { color: #F8FAFC; }
QLabel#WelcomeStepNum {
    color: #0A0C10; background: #22C55E; border-radius: 13px;
    min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px;
}
QFrame#WelcomeStep { background: #0F172A; border: 1px solid #1E293B; border-radius: 12px; }
QLabel#WelcomeHunt { color: #4ADE80; }
QCheckBox { color: #94A3B8; }
QPushButton#WelcomeGuide {
    border: 1px solid #4ADE80; border-top: 1px solid #A7F3D0; border-radius: 11px;
    color: #FFFFFF; padding: 9px 18px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #15803D, stop:0.5 #16A34A, stop:1 #059669);
}
QPushButton#WelcomeGuide:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #16A34A, stop:0.5 #22C55E, stop:1 #10B981);
}
QPushButton#WelcomeStart {
    border: 1px solid #334155; border-radius: 11px; color: #E2E8F0; padding: 9px 22px;
    background: #111827;
}
QPushButton#WelcomeStart:hover { border-color: #6366F1; color: #FFFFFF; }
"""


def _font(px, weight=QtGui.QFont.Normal, family="ui", upper=False):
    try:
        from ui import app_theme
        return app_theme.font(family, px, weight, upper=upper)
    except Exception:
        f = QtGui.QFont("Segoe UI", max(8, px - 4))
        f.setWeight(weight)
        return f


def _logo_path():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("CrowEye_rounded.png", "CrowEye.png", "Crow-Eye.png"):
        path = os.path.join(here, "GUI Resources", name)
        if os.path.isfile(path):
            return path
    return None


class WelcomeDialog(QtWidgets.QDialog):
    """Welcome to the Crow-Eye Forensics Engine."""

    def __init__(self, parent=None, show_again=False):
        super().__init__(parent)
        self.setObjectName("WelcomeDialog")
        self.setWindowTitle("Welcome to Crow-Eye")
        self.setModal(True)
        self.setStyleSheet(QSS)
        self.setMinimumWidth(720)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(34, 30, 34, 26)
        outer.setSpacing(16)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(18)
        logo = _logo_path()
        if logo:
            mark = QtWidgets.QLabel()
            pix = QtGui.QPixmap(logo)
            if not pix.isNull():
                mark.setPixmap(pix.scaled(72, 72, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
                head.addWidget(mark, 0, QtCore.Qt.AlignTop)
        titles = QtWidgets.QVBoxLayout()
        titles.setSpacing(4)
        kicker = QtWidgets.QLabel("WELCOME, INVESTIGATOR")
        kicker.setObjectName("WelcomeKicker")
        kicker.setFont(_font(12, QtGui.QFont.Bold))
        title = QtWidgets.QLabel("Welcome to the Crow-Eye Forensics Engine")
        title.setObjectName("WelcomeTitle")
        title.setFont(_font(26, QtGui.QFont.Bold, "display"))
        title.setWordWrap(True)
        lead = QtWidgets.QLabel("Crow-Eye reads a Windows machine's artifacts, links them to the people "
                                "and programs behind them, and keeps a chain of custody for every step. "
                                "Three steps to your first result:")
        lead.setObjectName("WelcomeLead")
        lead.setFont(_font(15))
        lead.setWordWrap(True)
        titles.addWidget(kicker)
        titles.addWidget(title)
        titles.addWidget(lead)
        head.addLayout(titles, 1)
        outer.addLayout(head)

        for i, (name, text) in enumerate(STEPS, 1):
            card = QtWidgets.QFrame()
            card.setObjectName("WelcomeStep")
            row = QtWidgets.QHBoxLayout(card)
            row.setContentsMargins(16, 12, 16, 12)
            row.setSpacing(14)
            num = QtWidgets.QLabel(str(i))
            num.setObjectName("WelcomeStepNum")
            num.setAlignment(QtCore.Qt.AlignCenter)
            num.setFont(_font(14, QtGui.QFont.Bold))
            col = QtWidgets.QVBoxLayout()
            col.setSpacing(2)
            t = QtWidgets.QLabel(name)
            t.setObjectName("WelcomeStepTitle")
            t.setFont(_font(16, QtGui.QFont.Bold))
            d = QtWidgets.QLabel(text)
            d.setObjectName("WelcomeStepText")
            d.setFont(_font(14))
            d.setWordWrap(True)
            col.addWidget(t)
            col.addWidget(d)
            row.addWidget(num, 0, QtCore.Qt.AlignTop)
            row.addLayout(col, 1)
            outer.addWidget(card)

        guide_text = QtWidgets.QLabel("The User Guide on crow-eye.com walks through each of these, every "
                                      "tool in the side menu, and what each artifact proves.")
        guide_text.setObjectName("WelcomeLead")
        guide_text.setFont(_font(14))
        guide_text.setWordWrap(True)
        outer.addWidget(guide_text)

        hunt = QtWidgets.QLabel("Good hunting.")
        hunt.setObjectName("WelcomeHunt")
        hunt.setFont(_font(20, QtGui.QFont.Bold, "display"))
        outer.addWidget(hunt)

        foot = QtWidgets.QHBoxLayout()
        foot.setSpacing(10)
        self.again = QtWidgets.QCheckBox("Show this at start-up")
        self.again.setChecked(bool(show_again))
        self.again.setFont(_font(13))
        foot.addWidget(self.again)
        foot.addStretch(1)
        self.guide_button = QtWidgets.QPushButton("Open the User Guide")
        self.guide_button.setObjectName("WelcomeGuide")
        self.guide_button.setFont(_font(14, QtGui.QFont.Bold))
        self.guide_button.setCursor(QtCore.Qt.PointingHandCursor)
        self.guide_button.clicked.connect(self.open_guide)
        start = QtWidgets.QPushButton("Start")
        start.setObjectName("WelcomeStart")
        start.setFont(_font(14, QtGui.QFont.Bold))
        start.setCursor(QtCore.Qt.PointingHandCursor)
        start.setDefault(True)
        start.clicked.connect(self.accept)
        foot.addWidget(self.guide_button)
        foot.addWidget(start)
        outer.addLayout(foot)

    def open_guide(self):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(USER_GUIDE_URL))

    def done(self, result):
        _remember(not self.again.isChecked())
        super().done(result)


def _remember(shown):
    """``welcome_shown`` true: not shown at the next start."""
    try:
        from config.case_history_manager import write_global_setting
        write_global_setting(SETTING, bool(shown))
    except Exception:
        pass


def should_show(relaunched=False):
    """The first start only: not on a relaunch into a case (elevation, an update),
    not under tests (they would wait on a modal window) and not once seen."""
    if relaunched:
        return False
    if os.environ.get("CROWEYE_NO_SELF_ELEVATE") == "1" or os.environ.get("CROWEYE_NO_WELCOME") == "1":
        return False
    if os.environ.get("QT_QPA_PLATFORM", "").lower() in ("offscreen", "minimal"):
        return False
    try:
        from config.case_history_manager import read_global_setting
        return not bool(read_global_setting(SETTING, False))
    except Exception:
        return False


def show_welcome(parent=None, show_again=False):
    dlg = WelcomeDialog(parent, show_again=show_again)
    try:
        from styles import CrowEyeStyles as _CES
        _CES.give_window_a_taskbar_button(dlg)
    except Exception:
        pass
    return dlg.exec_()
