"""The main window's side menu, laid out as a navigation list.

setupUi builds every side-menu button (and the rest of the window connects, renames, enables and
hides them by name), so this module does not create them: `apply(ui)` takes the existing buttons out
of the menu's layout and places them again -

  * the two main actions on top: Parse all Artifacts and Run Correlation, with Export and Dynamic
    Linking as two small buttons beside each other;
  * three sections, each collapsible, its state remembered: LIVE ANALYSIS (the parsers), TOOLS (the
    partition, file browser, shadow copy and acquisition windows), OFFLINE ANALYSIS;
  * every entry a flat row: its icon in its section's colour, its name, a bar in that colour on
    hover, and - for an artifact - a green dot once the open case holds what it parsed.

A row's colour says which family it belongs to, nothing else (one meaning per colour).
"""
import os

from PyQt5 import QtCore, QtGui, QtWidgets

try:
    from ui import app_theme as _theme
except Exception:                                         # pragma: no cover
    _theme = None

LIVE_C, TOOLS_C, OFFLINE_C = "#818CF8", "#22D3EE", "#A78BFA"
PARSED_C = "#4ADE80"

SECTIONS = (
    ("live", "Live analysis", LIVE_C, ("registrybutton", "lnkbutton", "Prefetchbutton", "ShimCacheButton",
                                       "AmcacheButton", "MFT_USN_CorrelateButton", "logbutton", "RecycleBinButton",
                                       "SRUMButton", "BrowserButton")),
    ("tools", "Tools", TOOLS_C, ("PartitionButton", "LiveFileBrowserButton", "ShadowCopiesButton",
                                 "LiveAppAcquisitionButton")),
    ("offline", "Offline analysis", OFFLINE_C, ("CrowClawButton", "OfflineImporterButton", "ImageParsingButton",
                                                "ParseOfflineArtifactsButton", "FileBrowserButton",
                                                "AppAcquisitionButton")),
)

# The databases each artifact's parser writes in a case's Target_Artifacts: any one of them present
# (and not empty) means the open case holds it.
PARSED_BY = {
    "registrybutton": ("registry_data.db",),
    "lnkbutton": ("LnkDB.db",),
    "Prefetchbutton": ("prefetch_data.db",),
    "ShimCacheButton": ("shimcache.db",),
    "AmcacheButton": ("amcache.db",),
    "MFT_USN_CorrelateButton": ("mft_usn_correlated_analysis.db", "mft_claw_analysis.db", "USN_journal.db"),
    "logbutton": ("Log_Claw.db",),
    "RecycleBinButton": ("recyclebin_analysis.db",),
    "SRUMButton": ("srum_data.db",),
    "BrowserButton": ("browser_analysis.db",),
    "PartitionButton": ("partition_data.db",),
    "ShadowCopiesButton": ("shadow_copies.db",),
}


def _rgba(colour, alpha):
    c = QtGui.QColor(colour)
    return "rgba(%d, %d, %d, %.2f)" % (c.red(), c.green(), c.blue(), alpha)


def _font(px, weight=QtGui.QFont.DemiBold, upper=False):
    if _theme is not None:
        try:
            return _theme.font("ui", px, weight, upper=upper, spacing=108 if upper else 100)
        except Exception:
            pass
    f = QtGui.QFont("Segoe UI", max(8, px - 4))
    f.setWeight(weight)
    if upper:
        f.setCapitalization(QtGui.QFont.AllUppercase)
    return f


# A raised button, not a flat row: a gradient lit from the top in the section's colour, a border in
# that colour, and a lighter top edge, so each entry reads as something to press. Hover brightens it;
# pressed inverts the gradient, the way a key goes down.
ROW_QSS = """
QPushButton {
    text-align: left; padding: 0px 30px 0px 11px; border-radius: 9px; color: #C9D3E3;
    border: 1px solid #1B2436; border-top: 1px solid #263149; border-left: 3px solid %(bar)s;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #161E30, stop:1 #10172A);
}
QPushButton:hover {
    color: #FFFFFF; border: 1px solid %(edge_hover)s; border-top: 1px solid %(lit_hover)s;
    border-left: 3px solid %(c)s;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 %(top_hover)s, stop:1 %(bottom_hover)s);
}
QPushButton:pressed {
    border-top: 1px solid #1B2436;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0C1220, stop:1 %(top_hover)s);
}
QPushButton:focus { outline: none; }
QPushButton:disabled {
    color: #56657C; border: 1px solid #172031; border-left: 3px solid #1E293B;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #131A29, stop:1 #0F1522);
}
"""


def _row_qss(colour):
    """ROW_QSS filled for one section colour."""
    # At rest only a slim bar in the section's colour says which family a row is in; on hover the
    # colour comes up through the edge and the surface. Solid colours: at 3 px a translucent edge
    # shows brighter seams where Qt draws a corner over a side.
    return ROW_QSS % {
        "c": colour, "bar": _mix(colour, "#10172A", 0.55),
        "edge_hover": _mix(colour, "#10172A", 0.45), "lit_hover": _mix(colour, "#10172A", 0.70),
        "top_hover": _mix(colour, "#161E30", 0.22), "bottom_hover": _mix(colour, "#10172A", 0.10)}


def _mix(colour, base, amount):
    """`amount` of `colour` over the opaque `base`, as #RRGGBB (QSS gradients want solid stops)."""
    a, b = QtGui.QColor(colour), QtGui.QColor(base)
    mixed = [round(b.red() + (a.red() - b.red()) * amount), round(b.green() + (a.green() - b.green()) * amount),
             round(b.blue() + (a.blue() - b.blue()) * amount)]
    return "#%02X%02X%02X" % tuple(mixed)

# Parse all Artifacts: the one action every case starts with, in the green of the
# "parsed" dots - the colour that means "this case holds it". Green, not red: red
# means urgent and nothing else.
PRIMARY_QSS = """
QPushButton {
    border: 1px solid #4ADE80; border-top: 1px solid #A7F3D0; border-bottom: 1px solid #065F46;
    border-radius: 13px; color: #FFFFFF; padding: 8px 14px; text-align: center;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #15803D, stop:0.5 #16A34A, stop:1 #059669);
}
QPushButton:hover {
    border-color: #BBF7D0;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #16A34A, stop:0.5 #22C55E, stop:1 #10B981);
}
QPushButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #166534, stop:0.5 #15803D, stop:1 #047857);
}
QPushButton:disabled { background: #172033; border: 1px solid #1E293B; color: #56657C; }
"""
PRIMARY_GLOW, PRIMARY_INK = "#22C55E", "#F0FDF4"
SECONDARY_GLOW, SECONDARY_INK = "#A78BFA", "#EDE9FE"

SECONDARY_QSS = """
QPushButton {
    border: 1px solid #6D4BD8; border-top: 1px solid #9C7BF2; border-radius: 12px;
    color: #EDE9FE; padding: 7px 14px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2A1F4D, stop:1 #1A1533);
}
QPushButton:hover {
    border-color: #A78BFA; color: #FFFFFF;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3A2A6A, stop:1 #221A42);
}
QPushButton:pressed { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1A1533, stop:1 #2A1F4D); }
QPushButton:disabled { border-color: #1E293B; color: #56657C; background: #131A29; }
"""

SMALL_QSS = """
QPushButton {
    border: 1px solid #222D44; border-top: 1px solid #2D3A57; border-radius: 9px;
    color: #C9D3E3; padding: 5px 8px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #161E30, stop:1 #10172A);
}
QPushButton:hover {
    border-color: #3D5A80; color: #FFFFFF;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1B2A42, stop:1 #121B2E);
}
QPushButton:pressed { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0C1220, stop:1 #1B2A42); }
"""

HEADER_QSS = """
QToolButton {
    color: #7D8BA4; background: transparent; border: none; border-bottom: 1px solid #1B2436;
    padding: 14px 2px 7px 2px; text-align: left;
}
QToolButton:hover { color: #C7D2FE; border-bottom-color: #2E3B57; }
"""

FRAME_QSS = """
QFrame#side_fram {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0D1322, stop:1 #090E1A);
    border: none; border-right: 1px solid #182134;
}
"""


class _Dot(QtCore.QObject):
    """Keeps a row's parsed dot at the row's right edge as the row is resized."""

    def __init__(self, button, dot):
        super().__init__(button)
        self.button, self.dot = button, dot
        button.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Show):
            self.dot.move(self.button.width() - 20, (self.button.height() - self.dot.height()) // 2)
        return False


class _Pulse(QtCore.QObject):
    """A button that breathes: a soft glow in its colour and an icon in motion.

    One QVariantAnimation drives both. The glow is a drop shadow whose blur and
    strength rise and fall; the icon steps through frames rendered once
    (artifact_icons.animation_frames), so a tick only swaps a ready icon.
    `set_running(False)` stops it and leaves the still icon and a faint glow:
    the menu stops when the button is disabled, when Crow-Eye is busy, and
    while the window is hidden or minimised, so it costs nothing then.
    """

    def __init__(self, button, drawing, ink, glow, period_ms, blur=(8.0, 22.0), alpha=(60, 170)):
        super().__init__(button)
        self.button = button
        self.glow = QtGui.QColor(glow)
        self.blur, self.alpha = blur, alpha
        self.frames = []
        self.still = None
        try:
            from ui.artifact_icons import animation_frames, artifact_icon
            self.frames = animation_frames(drawing, ink)
            self.still = artifact_icon(drawing, ink)
        except Exception:                                   # pragma: no cover
            pass
        if self.still is not None:
            button.setIcon(self.still)
            button.setIconSize(QtCore.QSize(22, 22))
        self.effect = QtWidgets.QGraphicsDropShadowEffect(button)
        self.effect.setOffset(0, 0)
        button.setGraphicsEffect(self.effect)
        self._last = -1
        self.anim = QtCore.QVariantAnimation(self)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setDuration(int(period_ms))
        self.anim.setLoopCount(-1)
        self.anim.valueChanged.connect(self._tick)
        self._rest()

    def _rest(self):
        c = QtGui.QColor(self.glow)
        c.setAlpha(self.alpha[0])
        self.effect.setBlurRadius(self.blur[0])
        self.effect.setColor(c)

    def _tick(self, value):
        import math
        s = 0.5 - 0.5 * math.cos(2 * math.pi * float(value))   # 0 -> 1 -> 0, eased
        c = QtGui.QColor(self.glow)
        c.setAlpha(int(self.alpha[0] + (self.alpha[1] - self.alpha[0]) * s))
        self.effect.setColor(c)
        self.effect.setBlurRadius(self.blur[0] + (self.blur[1] - self.blur[0]) * s)
        if self.frames:
            i = int(float(value) * len(self.frames)) % len(self.frames)
            if i != self._last:
                self._last = i
                self.button.setIcon(self.frames[i])

    def set_running(self, on):
        running = self.anim.state() == QtCore.QAbstractAnimation.Running
        if on and not running:
            self.anim.start()
        elif not on and running:
            self.anim.stop()
            self._last = -1
            if self.still is not None:
                self.button.setIcon(self.still)
            self._rest()


class SideMenu(QtCore.QObject):
    """The re-laid side menu; kept on the ui object as `ui.side_menu`."""

    def __init__(self, ui):
        super().__init__(ui.side_fram)
        self.ui = ui
        self.dots = {}
        self.headers = {}
        self.bodies = {}
        self.settings = QtCore.QSettings("CrowEye", "SideMenu")
        self._build()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        QtCore.QTimer.singleShot(0, self.refresh)
        # The main actions move only while they can be pressed and someone can see
        # them: not while Crow-Eye is busy, not while the window is hidden or
        # minimised, not while the button is disabled.
        self._busy = False
        self._window = None
        try:
            from ui import busy_guard
            busy_guard.add_listener(self._on_busy)
        except Exception:                                   # pragma: no cover
            pass
        for p in getattr(self, "pulses", []):
            p.button.installEventFilter(self)
        QtCore.QTimer.singleShot(0, self._update_pulses)

    def _on_busy(self, busy):
        self._busy = bool(busy)
        self._update_pulses()

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind in (QtCore.QEvent.EnabledChange, QtCore.QEvent.WindowStateChange,
                    QtCore.QEvent.Show, QtCore.QEvent.Hide):
            QtCore.QTimer.singleShot(0, self._update_pulses)
        return False

    def _update_pulses(self):
        try:
            win = self.ui.side_fram.window()
        except Exception:
            win = None
        if win is not None and win is not self._window:
            self._window = win
            win.installEventFilter(self)
        visible = win is not None and win.isVisible() and not win.isMinimized()
        for p in getattr(self, "pulses", []):
            try:
                p.set_running(visible and not self._busy and p.button.isEnabled()
                              and p.button.isVisible())
            except RuntimeError:                            # a deleted widget
                pass

    # ---- layout ---------------------------------------------------------------------------------
    def _take_all(self):
        lay = self.ui.verticalLayout_3
        taken = []
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(self.ui.side_inner)
                taken.append(w)
        return taken

    def _build(self):
        ui = self.ui
        lay = ui.verticalLayout_3
        taken = self._take_all()
        names = ["parse_all", "correlation_button", "export_json_CSV", "dynamic_linking_button"]
        names += [n for _k, _t, _c, ns in SECTIONS for n in ns]
        # By the widgets themselves, never by object name: a button's attribute and its Qt object name
        # differ (Export is `export_json_CSV` on the ui object and "loadData" to Qt), and matching names
        # moved Export into Tools.
        placed = set(id(getattr(ui, n)) for n in names if getattr(ui, n, None) is not None)
        # A side button added to setupUi but not to SECTIONS still gets a row (in Tools) rather than
        # being left loose on top of the menu.
        extra = [w for w in taken if isinstance(w, QtWidgets.QPushButton) and id(w) not in placed]
        lay.setContentsMargins(10, 10, 10, 12)
        lay.setSpacing(2)
        ui.side_fram.setStyleSheet(FRAME_QSS)
        for old in ("Live_analysis", "Offline_analysis"):
            label = getattr(ui, old, None)
            if label is not None:
                label.hide()

        # the main actions: Parse all Artifacts first and largest, set off from the
        # top of the menu, breathing in green; Run Correlation under it in violet.
        top = QtWidgets.QVBoxLayout()
        top.setSpacing(12)
        top.setContentsMargins(4, 16, 4, 8)
        self.pulses = []
        for name, qss, height, px, drawing, ink, glow, period, blur, alpha in (
                ("parse_all", PRIMARY_QSS, 52, 15, "parse_all", PRIMARY_INK, PRIMARY_GLOW, 2400,
                 (8.0, 24.0), (70, 190)),
                ("correlation_button", SECONDARY_QSS, 42, 14, "correlate", SECONDARY_INK, SECONDARY_GLOW,
                 3200, (5.0, 15.0), (40, 120))):
            b = getattr(ui, name, None)
            if b is None:
                continue
            b.setStyleSheet(qss)
            b.setMinimumHeight(height)
            b.setMaximumHeight(height)
            b.setFont(_font(px, QtGui.QFont.Bold))
            b.setCursor(QtCore.Qt.PointingHandCursor)
            try:
                self.pulses.append(_Pulse(b, drawing, ink, glow, period, blur, alpha))
            except Exception:                               # pragma: no cover
                pass
            top.addWidget(b)
        small = QtWidgets.QHBoxLayout()
        small.setSpacing(6)
        for name, short, tip in (("export_json_CSV", "Export", "Export the case's tables as CSV, JSON or an HTML report - it runs in the background"),
                                 ("dynamic_linking_button", "Linking", "Dynamic Linking: map identifiers across "
                                                                       "the case's tables")):
            b = getattr(ui, name, None)
            if b is None:
                continue
            b.setStyleSheet(SMALL_QSS)
            b.setText(short)
            b.setToolTip(tip)
            b.setMinimumHeight(32)
            b.setMaximumHeight(32)
            b.setFont(_font(12))
            b.setCursor(QtCore.Qt.PointingHandCursor)
            small.addWidget(b, 1)
        top.addLayout(small)
        lay.addLayout(top)

        # the sections
        for key, title, colour, names in SECTIONS:
            buttons = [getattr(ui, n) for n in names if getattr(ui, n, None) is not None]
            if key == "tools":
                buttons += extra
            header = QtWidgets.QToolButton()
            header.setCheckable(True)
            header.setStyleSheet(HEADER_QSS)
            header.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
            header.setFont(_font(11, QtGui.QFont.Bold, upper=True))
            header.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            header.setCursor(QtCore.Qt.PointingHandCursor)
            header.setText(title)
            header.setToolTip("Show or hide the %s entries" % title.lower())
            body = QtWidgets.QWidget()
            bv = QtWidgets.QVBoxLayout(body)
            bv.setContentsMargins(0, 6, 0, 4)
            bv.setSpacing(5)
            for b in buttons:
                self._row(b, colour)
                bv.addWidget(b)
            lay.addWidget(header)
            lay.addWidget(body)
            self.headers[key], self.bodies[key] = header, body
            open_ = self.settings.value("open/" + key, True, type=bool)
            header.setChecked(open_)
            self._set_open(key, open_)
            header.toggled.connect(lambda on, k=key: self._set_open(k, on))
        lay.addStretch(1)

    def _row(self, b, colour):
        b.setCheckable(False)
        b.setStyleSheet(_row_qss(colour))
        b.setFont(_font(13))
        b.setMinimumHeight(37)
        b.setMaximumHeight(37)
        # Every row as wide as the actions above it: setupUi gave some of them a width of their own.
        b.setMinimumWidth(0)
        b.setMaximumWidth(16777215)
        b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        b.setCursor(QtCore.Qt.PointingHandCursor)
        try:
            from ui.artifact_icons import MAIN_BUTTONS, artifact_icon
            icon = artifact_icon(MAIN_BUTTONS.get(b.objectName()) or "", colour)
            if icon is not None:
                b.setIcon(icon)
                b.setIconSize(QtCore.QSize(18, 18))
        except Exception:
            pass
        if b.objectName() in PARSED_BY:
            dot = QtWidgets.QLabel(b)
            dot.setFixedSize(8, 8)
            dot.setStyleSheet("background: %s; border-radius: 4px;" % PARSED_C)
            dot.hide()
            self.dots[b.objectName()] = dot
            _Dot(b, dot)

    def _set_open(self, key, on):
        self.bodies[key].setVisible(on)
        header = self.headers[key]
        header.setArrowType(QtCore.Qt.DownArrow if on else QtCore.Qt.RightArrow)
        self.settings.setValue("open/" + key, bool(on))

    # ---- what the open case holds -----------------------------------------------------------------
    def _artifacts_dir(self):
        paths = getattr(self.ui, "case_paths", None) or {}
        d = paths.get("artifacts_dir")
        if not d and paths.get("case_root"):
            d = os.path.join(paths["case_root"], "Target_Artifacts")
        return d if d and os.path.isdir(d) else None

    def refresh(self):
        """The green dots: an artifact whose database the open case holds."""
        d = self._artifacts_dir()
        for name, dot in self.dots.items():
            found = None
            if d:
                for db in PARSED_BY[name]:
                    path = os.path.join(d, db)
                    try:
                        st = os.stat(path)
                    except OSError:
                        continue
                    if st.st_size > 8192:
                        found = (db, st.st_size)
                        break
            button = dot.parent()
            if found:
                dot.show()
                dot.setToolTip("Parsed in this case: %s (%.1f MB)" % (found[0], found[1] / 1048576.0))
                base = button.property("baseTip")
                if base is None:
                    base = button.toolTip() or ""
                    button.setProperty("baseTip", base)
                button.setToolTip((base + "\n" if base else "") + "Parsed in this case (%s)" % found[0])
            else:
                dot.hide()
                base = button.property("baseTip")
                if base is not None:
                    button.setToolTip(base)


def apply(ui):
    """Lay the side menu out as a navigation list (once, after setupUi and retranslateUi)."""
    if getattr(ui, "side_menu", None) is not None or not hasattr(ui, "verticalLayout_3"):
        return getattr(ui, "side_menu", None)
    ui.side_menu = SideMenu(ui)
    return ui.side_menu
