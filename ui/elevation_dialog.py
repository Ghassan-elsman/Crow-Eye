"""The pop-ups for parsing without Administrator rights (utils/elevation.py).

ElevationDialog("before", artifacts=[...])  asked before a live parse that needs
    rights: Restart as Administrator / Run anyway / Cancel.
ElevationDialog("after", outcomes=[...])    after a live parse whose artifacts
    were refused: Restart as Administrator / Open full report / Close. Shown in
    place of the Parse Status report, never as well.

``exec_()`` returns one of RESTART, RUN, REPORT, CANCEL.
"""
import html

from PyQt5 import QtCore, QtWidgets

from ui.parse_status_dialog import _finish_styling, _readable
from utils import elevation
from utils.parse_status import artifact_label

RESTART, RUN, REPORT, CANCEL = 11, 12, 13, 0

_AMBER = "#FBBF24"


class ElevationDialog(QtWidgets.QDialog):

    def __init__(self, mode, artifacts=None, outcomes=None, parent=None, can_restart=None):
        super().__init__(parent)
        self.mode = mode
        self.artifacts = list(artifacts or [])
        self.outcomes = list(outcomes or [])
        self.can_restart = elevation.can_relaunch() if can_restart is None else can_restart
        self.setWindowTitle("Crow-Eye - Administrator rights")
        self.setObjectName("ElevationDialog")
        self.resize(660, 0)
        self.setMinimumWidth(560)
        self._build()
        _finish_styling(self)
        _readable(self)
        self._style_primary()

    # --- layout ---------------------------------------------------------------
    def _build(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(12)
        icon = QtWidgets.QLabel()
        try:
            from correlation_engine.gui.crow_eye_icons import CrowEyeIcons
            icon.setPixmap(CrowEyeIcons.lock().pixmap(36, 36))
        except Exception:
            pass
        head.addWidget(icon, 0, QtCore.Qt.AlignTop)
        title = QtWidgets.QLabel(
            "This parse needs Administrator rights" if self.mode == "before"
            else "Windows refused access to some evidence")
        title.setObjectName("headingLabel")
        title.setWordWrap(True)
        title.setStyleSheet("QLabel { color: %s; font-size: 20px; font-weight: 800; }" % _AMBER)
        head.addWidget(title, 1)
        layout.addLayout(head)

        intro = QtWidgets.QLabel(self._intro())
        intro.setWordWrap(True)
        intro.setTextFormat(QtCore.Qt.RichText)
        intro.setStyleSheet("QLabel { color: #E2E8F0; font-size: 15px; }")
        layout.addWidget(intro)

        listing = QtWidgets.QLabel(self._listing())
        listing.setWordWrap(True)
        listing.setTextFormat(QtCore.Qt.RichText)
        listing.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        listing.setObjectName("elevationList")
        listing.setStyleSheet(
            "QLabel#elevationList { color: #F1F5F9; font-size: 14px; background: rgba(15,23,42,0.85);"
            " border: 1px solid #1E293B; border-left: 4px solid %s; border-radius: 8px;"
            " padding: 10px 14px; }" % _AMBER)
        layout.addWidget(listing)

        how = QtWidgets.QLabel(self._how())
        how.setWordWrap(True)
        how.setTextFormat(QtCore.Qt.RichText)
        how.setStyleSheet("QLabel { color: #CBD5E1; font-size: 13px; }")
        layout.addWidget(how)

        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(8)
        self.restart_btn = None
        if self.can_restart:
            self.restart_btn = QtWidgets.QPushButton("Restart as Administrator")
            self.restart_btn.setObjectName("restartButton")
            self.restart_btn.clicked.connect(lambda: self.done(RESTART))
            buttons.addWidget(self.restart_btn)
        buttons.addStretch(1)
        if self.mode == "before":
            run = QtWidgets.QPushButton("Run anyway")
            run.clicked.connect(lambda: self.done(RUN))
            buttons.addWidget(run)
            cancel = QtWidgets.QPushButton("Cancel")
            cancel.clicked.connect(lambda: self.done(CANCEL))
            buttons.addWidget(cancel)
        else:
            rep = QtWidgets.QPushButton("Open full report")
            rep.clicked.connect(lambda: self.done(REPORT))
            buttons.addWidget(rep)
            close = QtWidgets.QPushButton("Close")
            close.clicked.connect(lambda: self.done(CANCEL))
            buttons.addWidget(close)
        if self.restart_btn is not None:
            self.restart_btn.setDefault(True)
        layout.addLayout(buttons)

    def _intro(self):
        if self.mode == "before":
            return ("Crow-Eye is <b>not running as Administrator</b>. Windows protects the "
                    "evidence below, so without elevation it will be refused - the parse "
                    "would finish with those artifacts empty or incomplete.")
        return ("Crow-Eye is <b>not running as Administrator</b>, and Windows refused to let "
                "these artifacts be read. Their tables are empty or incomplete for that "
                "reason - not because the evidence is absent.")

    def _listing(self):
        rows = []
        if self.mode == "before":
            required, partial = elevation.admin_needs(self.artifacts)
            for a in required:
                verdict = "cannot be built" if a == "mft_usn_correlation" else "cannot be read"
                rows.append("<b>%s</b> &nbsp;<span style='color:%s;'>%s</span>"
                            "<br><span style='color:#94A3B8;'>%s</span>"
                            % (_e(artifact_label(a)), _AMBER, verdict,
                               _e(elevation.ADMIN_NEEDS[a][1])))
            for a in partial:
                rows.append("<b>%s</b> &nbsp;<span style='color:#38BDF8;'>only partly</span>"
                            "<br><span style='color:#94A3B8;'>%s</span>"
                            % (_e(artifact_label(a)), _e(elevation.ADMIN_NEEDS[a][1])))
        else:
            for o in self.outcomes:
                rows.append("<b>%s</b> &nbsp;<span style='color:%s;'>Access denied</span>"
                            "<br><span style='color:#94A3B8;'>%s</span>"
                            % (_e(o.label), _AMBER, _e(_short(o.message))))
        return "<br><br>".join(rows) or "(nothing listed)"

    def _how(self):
        if self.can_restart:
            text = ("<b>Restart as Administrator</b> reopens Crow-Eye elevated on this same "
                    "case; Windows asks for consent first. ")
            if self.mode == "before":
                text += "<b>Run anyway</b> parses what can be read without rights."
            else:
                text += "Then parse again."
            return text
        return ("Start Crow-Eye with Administrator (root) rights and parse again.")

    def _style_primary(self):
        if self.restart_btn is not None:
            self.restart_btn.setStyleSheet(
                "QPushButton { background: %s; color: #0B1220; border: none; border-radius: 6px;"
                " padding: 8px 16px; font-size: 14px; font-weight: 800; }"
                " QPushButton:hover { background: #FCD34D; }" % _AMBER)


def _e(text):
    return html.escape(str(text or ""), quote=False)


def _short(text, limit=220):
    # Python's error text quotes paths with repr(): C:\\Windows -> C:\Windows
    text = " ".join(str(text or "").replace("\\\\", "\\").split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def ask_before(parent, artifacts):
    """RESTART / RUN / CANCEL - RUN without asking when no question is needed."""
    if not elevation.precheck_needed(artifacts):
        return RUN
    return ElevationDialog("before", artifacts=artifacts, parent=parent).exec_()
