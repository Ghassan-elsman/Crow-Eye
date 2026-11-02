"""The top bar in three groups at one height.

setupUi builds the bar from nine unrelated stylesheets: two 42 px icon buttons with 3 px teal
outlines, two flat blue case buttons, a case label in a serif with its own 3 px outline, and four
tool buttons each in a different loud gradient (one of them red, which in this app means urgent)
inside a framed box, with Eye AI's icon at 60 px. `apply(ui)` runs once after setupUi and restyles
those same widgets, without moving any of them:

  * left: the sidebar toggle and Settings as one segmented icon pair;
  * centre: the case as a chip with a status dot (cyan when a case is open), its folder as the
    tooltip;
  * right: Create case and Open case as one raised pair, then Database Search, Timeline, User
    Behavior and Eye AI in one shared raised style, each told apart by its own accent on the
    lower edge and its icon, all at 18 px.

Everything sits on 36 px. The frame takes the side menu's dark gradient and a hairline below.
Weights come from QFont (a QSS font-weight is measured after the width and clips labels).
"""
import html
import os

from PyQt5 import QtCore, QtGui, QtWidgets

try:
    from ui import app_theme as _theme
except Exception:                                         # pragma: no cover
    _theme = None
try:
    from ui.side_menu import _mix, _rgba
except Exception:                                         # pragma: no cover
    def _mix(colour, base, amount):
        a, b = QtGui.QColor(colour), QtGui.QColor(base)
        return "#%02X%02X%02X" % tuple(round(y + (x - y) * amount) for x, y in
                                       ((a.red(), b.red()), (a.green(), b.green()), (a.blue(), b.blue())))

    def _rgba(colour, alpha):
        c = QtGui.QColor(colour)
        return "rgba(%d, %d, %d, %.2f)" % (c.red(), c.green(), c.blue(), alpha)

HEIGHT = 38

FRAME_QSS = """
QFrame#top_frame {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #111A2B, stop:1 #0B111E);
    border: none; border-bottom: 1px solid #1B2539;
}
QFrame#search_frame { background: transparent; border: none; padding: 0px; margin: 0px; }
"""

# Raised, like the side menu's rows: a gradient, a hairline edge and a lit top edge.
# %(left)s / %(right)s round only the outer corners of a joined pair.
RAISED_QSS = """
QPushButton {
    color: #D2DBE8; padding: 0px %(pad)dpx; min-height: %(h)dpx; max-height: %(h)dpx;
    border: 1px solid #212C42; border-top: 1px solid #2D3A56; border-bottom: %(under)s;
    border-top-left-radius: %(left)dpx; border-bottom-left-radius: %(left)dpx;
    border-top-right-radius: %(right)dpx; border-bottom-right-radius: %(right)dpx;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #161F31, stop:1 #10172A);
}
QPushButton:hover {
    color: #FFFFFF; border-color: %(hover)s; border-bottom: %(under_hover)s;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 %(top_hover)s, stop:1 #121A2C);
}
QPushButton:pressed, QPushButton:checked {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0C1220, stop:1 %(top_hover)s);
    border-color: %(hover)s;
}
QPushButton:disabled { color: #56657C; }
"""

CHIP_QSS = """
QLabel {
    color: #E2E8F0; background: #0A101C; padding: 0px 18px; min-height: %(h)dpx; max-height: %(h)dpx;
    border: 1px solid #1E2940; border-top: 1px solid #0A0F1A; border-radius: %(r)dpx;
}
QLabel[caseOpen="true"] { border-color: #155E75; }
""" % {"h": HEIGHT - 2, "r": HEIGHT // 2}

# The tools stand in one dock: a glass capsule, the buttons inside it borderless, each told apart by
# its icon's hue and a tint of that hue on hover. Eye AI closes the dock as the flagship.
DOCK_QSS = """
QFrame#search_frame {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #141C2E, stop:1 #0E1524);
    border: 1px solid #1E2940; border-top: 1px solid #2A3754; border-radius: 12px;
    padding: 0px; margin: 0px;
}
"""

DOCK_BUTTON_QSS = """
QPushButton {
    color: #FFFFFF; border: 1px solid %(edge)s; border-top: 1px solid %(lit)s; border-radius: 9px;
    padding: 0px 12px; min-height: %(h)dpx; max-height: %(h)dpx;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 %(top)s, stop:1 %(bottom)s);
}
QPushButton:hover {
    border-color: %(edge_hover)s;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 %(top_hover)s, stop:1 %(bottom_hover)s);
}
QPushButton:pressed { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 %(bottom)s, stop:1 %(top)s); }
QPushButton:disabled { color: #56657C; background: #131A29; border-color: #1E293B; }
"""

EYE_QSS = """
QPushButton {
    color: #FFFFFF; border: 1px solid #7C83F7; border-top: 1px solid #A5ABFF; border-radius: 9px;
    padding: 0px 14px; min-height: %(h)dpx; max-height: %(h)dpx;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #4F46E5, stop:1 #0891B2);
}
QPushButton:hover {
    border-color: #C7CBFF;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6366F1, stop:1 #06B6D4);
}
QPushButton:pressed { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #4338CA, stop:1 #0E7490); }
"""

# Create case leads the pair: the first thing a session does.
CREATE_QSS = """
QPushButton {
    color: #FFFFFF; padding: 0px 14px; min-height: %(h)dpx; max-height: %(h)dpx;
    border: 1px solid #4B4FC9; border-top: 1px solid #6E73EE; border-right: none;
    border-top-left-radius: 9px; border-bottom-left-radius: 9px;
    border-top-right-radius: 0px; border-bottom-right-radius: 0px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3B3FA8, stop:1 #2A2D7C);
}
QPushButton:hover {
    border-color: #818CF8;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4A4FC4, stop:1 #33378F);
}
QPushButton:pressed { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #24276C, stop:1 #3B3FA8); }
"""


class _Hairline(QtCore.QObject):
    """A fading indigo-cyan line along the bar's bottom edge, kept to the bar's width."""

    def __init__(self, frame):
        super().__init__(frame)
        self.frame = frame
        self.line = QtWidgets.QFrame(frame)
        self.line.setObjectName("brandLine")
        self.line.setStyleSheet(
            "QFrame#brandLine { border: none; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            "stop:0 rgba(99, 102, 241, 0), stop:0.25 #6366F1, stop:0.6 #22D3EE, stop:1 rgba(34, 211, 238, 0)); }")
        self.line.setProperty("keepStyle", True)
        self.line.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        frame.installEventFilter(self)
        self._place()

    def _place(self):
        self.line.setGeometry(0, self.frame.height() - 1, self.frame.width(), 1)
        self.line.raise_()

    def eventFilter(self, obj, event):
        if event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Show):
            self._place()
        return False


def _separator(parent):
    sep = QtWidgets.QFrame(parent)
    sep.setFixedSize(1, HEIGHT - 16)
    sep.setStyleSheet("background: #232F48; border: none;")
    sep.setProperty("keepStyle", True)
    return sep


# Each tool's accent: its own hue, none of them red (red means urgent here).
TOOLS = (("search_button", "#22D3EE"), ("timeline_search_button", "#8B5CF6"),
         ("uba_button", "#BEF264"), ("eye_assistant_button", "#60A5FA"))
# The website's own colour for UBA (crow-eye.com --lime, its "User Behavior Analytics" tag).
UBA_LIME = "#BEF264"

# Two-tone gradients from the site's palette only (--cyan #22D3EE, --indigo #6366F1, --lime
# #BEF264, and the violet the app pairs with indigo), in deep shades - no glow, nothing bright
# (Ghassan, 2026-10-31: "don't use neon"). No rose (urgent only), no amber (not ours).
# Each tool: (gradient from, gradient to, lit edge, text, icon colour or None).
NEON = {
    "search_button": ("#0E7490", "#3730A3", "#22D3EE", "#FFFFFF", "#A5F3FC"),
    "timeline_search_button": ("#4338CA", "#6D28D9", "#818CF8", "#FFFFFF", "#DDD6FE"),
    "uba_button": ("#E11D48", "#BE123C", "#FB7185", "#FFFFFF", "#FFFFFF"),
    "eye_assistant_button": ("#4F46E5", "#0E7490", "#818CF8", "#FFFFFF", None),
}

NEON_QSS = """
QPushButton {
    color: %(text)s; border: 1px solid %(edge)s; border-top: 1px solid %(lit)s; border-radius: 9px;
    padding: 0px 13px; min-height: %(h)dpx; max-height: %(h)dpx;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 %(a)s, stop:1 %(b)s);
}
QPushButton:hover {
    border-color: %(lit)s;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 %(a_hover)s, stop:1 %(b_hover)s);
}
QPushButton:pressed { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 %(b)s, stop:1 %(a)s); }
QPushButton:disabled { color: #56657C; background: #131A29; border-color: #1E293B; }
"""


def _neon(button, name, height):
    a, b, lit, text, icon = NEON[name]
    button.setStyleSheet(NEON_QSS % {
        "h": height, "a": a, "b": b, "lit": lit, "text": text, "edge": _mix(b, "#0B111E", 0.55),
        # _mix(colour, base, amount) keeps `amount` of colour: (a, "#FFFFFF", 0.12) was 88% WHITE,
        # white text on a near-white fill (Ghassan, 2026-11-01: "so bright that I cannot read").
        # The hover deepens the button a little instead; the lit edge says it is hovered.
        "a_hover": _mix(a, "#0B111E", 0.82), "b_hover": _mix(b, "#0B111E", 0.82)})
    if icon:
        _tint_icon(button, icon)


def _tint_icon(button, colour):
    """The button's icon painted in one colour (a monochrome SVG drawn in the site's hue)."""
    icon = button.icon()
    sizes = icon.availableSizes()
    if icon.isNull() or not sizes:
        return
    src = icon.pixmap(max(sizes, key=lambda z: z.width()))
    out = QtGui.QPixmap(src.size())
    out.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(out)
    painter.drawPixmap(0, 0, src)
    painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), QtGui.QColor(colour))
    painter.end()
    button.setIcon(QtGui.QIcon(out))


def raised(accent=None, left=8, right=8, pad=14):
    hover = accent or "#22D3EE"
    return RAISED_QSS % {
        "pad": pad, "h": HEIGHT - 2, "left": left, "right": right,
        # The accent is a thin line under the button at rest and the whole edge on hover - solid
        # colours, so the 2 px line has no seams where Qt joins it to the corners.
        "under": "2px solid %s" % _mix(accent, "#10172A", 0.55) if accent else "1px solid #0A0F1A",
        "under_hover": "2px solid %s" % accent if accent else "1px solid %s" % hover,
        "hover": _mix(hover, "#10172A", 0.50), "top_hover": _mix(hover, "#161F31", 0.18)}


def _font(px, weight):
    if _theme is not None:
        try:
            return _theme.font("ui", px, weight)
        except Exception:
            pass
    f = QtGui.QFont("Segoe UI", max(8, px - 4))
    f.setWeight(weight)
    return f


def _fix(button, width=None):
    button.setMinimumHeight(HEIGHT)
    button.setMaximumHeight(HEIGHT)
    if width is not None:
        button.setMinimumWidth(width)
        button.setMaximumWidth(width)
    else:
        button.setMinimumWidth(0)
        button.setMaximumWidth(16777215)
    button.setSizePolicy(QtWidgets.QSizePolicy.Preferred if width is None else QtWidgets.QSizePolicy.Fixed,
                         QtWidgets.QSizePolicy.Fixed)


def _trim_icon(button):
    """Eye AI's mark is a PNG that is mostly transparent margin; at a bar's icon size the
    mark itself came out a few pixels wide. Cut the margin away once."""
    icon = button.icon()
    sizes = icon.availableSizes()
    if icon.isNull() or not sizes:
        return
    image = icon.pixmap(max(sizes, key=lambda s: s.width())).toImage().convertToFormat(
        QtGui.QImage.Format_ARGB32)
    w, h = image.width(), image.height()
    xs = [x for x in range(0, w, 2) if any(QtGui.qAlpha(image.pixel(x, y)) > 24 for y in range(0, h, 2))]
    ys = [y for y in range(0, h, 2) if any(QtGui.qAlpha(image.pixel(x, y)) > 24 for x in range(0, w, 2))]
    if not xs or not ys:
        return
    side = max(xs[-1] - xs[0], ys[-1] - ys[0]) + 4
    cx, cy = (xs[0] + xs[-1]) // 2, (ys[0] + ys[-1]) // 2
    rect = QtCore.QRect(cx - side // 2, cy - side // 2, side, side).intersected(image.rect())
    button.setIcon(QtGui.QIcon(QtGui.QPixmap.fromImage(image.copy(rect))))


def _brand(parent):
    """The mark and the name, as an application shows whose it is: the rounded app tile and
    "Crow-Eye" over "Forensics Engine"."""
    box = QtWidgets.QWidget(parent)
    box.setObjectName("brand")
    box.setStyleSheet("QWidget#brand { background: transparent; }")
    row = QtWidgets.QHBoxLayout(box)
    row.setContentsMargins(4, 0, 12, 0)
    row.setSpacing(10)
    tile = QtWidgets.QLabel(box)
    try:
        from styles import CrowEyeStyles
        px = CrowEyeStyles.resource_pixmap("GUI Resources", "CrowEye_rounded.png")
    except Exception:
        px = None
    if px is not None and not px.isNull():
        ratio = parent.devicePixelRatioF() if hasattr(parent, "devicePixelRatioF") else 1.0
        size = int(28 * ratio)
        scaled = px.scaled(size, size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        scaled.setDevicePixelRatio(ratio)
        tile.setPixmap(scaled)
    tile.setFixedSize(28, 28)
    tile.setStyleSheet("background: transparent; border: none;")
    words = QtWidgets.QVBoxLayout()
    words.setContentsMargins(0, 0, 0, 0)
    words.setSpacing(0)
    name = QtWidgets.QLabel("Crow-Eye", box)
    name.setFont(_font(15, QtGui.QFont.Bold))
    name.setStyleSheet("color: #F1F5F9; background: transparent; border: none;")
    sub = QtWidgets.QLabel("Forensics Engine", box)
    sub.setFont(_font(11, QtGui.QFont.Medium))
    sub.setStyleSheet("color: #7D8BA4; background: transparent; border: none;")
    words.addWidget(name)
    words.addWidget(sub)
    row.addWidget(tile, 0, QtCore.Qt.AlignVCenter)
    row.addLayout(words)
    for w in (box, tile, name, sub):
        w.setProperty("keepStyle", True)
    box.setFixedHeight(HEIGHT)
    return box


def _case_chip(ui):
    """The case label as a chip: a dot, the case, its folder as the tooltip. The label's text is
    set in three places in Crow Eye.py ("Case: name" / "Case: None"); they keep calling setText."""
    label = ui.label
    plain_set = label.setText

    def set_text(text):
        text = str(text or "")
        name = text.split(":", 1)[1].strip() if ":" in text else ""
        is_open = bool(name) and name.lower() != "none"
        label.setProperty("caseOpen", is_open)
        dot = "#22D3EE" if is_open else "#475569"
        shown = html.escape(name) if is_open else "No case open"
        plain_set('<span style="color:%s;">&#9679;</span>&nbsp;&nbsp;<span style="color:#94A3B8;">Case</span>'
                  '&nbsp;&nbsp;<b>%s</b>' % (dot, shown))
        root = (getattr(ui, "case_paths", None) or {}).get("case_root")
        label.setToolTip(os.path.normpath(root) if is_open and root else
                         "Create or open a case to start" if not is_open else name)
        label.style().unpolish(label)
        label.style().polish(label)

    label.setTextFormat(QtCore.Qt.RichText)
    label.setStyleSheet(CHIP_QSS)
    label.setFont(_font(13, QtGui.QFont.Normal))
    label.setMaximumWidth(460)
    label.setMinimumHeight(HEIGHT)
    label.setMaximumHeight(HEIGHT)
    label.setText = set_text
    set_text(label.text())


def apply(ui):
    """Restyle the top bar once, after setupUi. Returns the number of widgets restyled."""
    frame = getattr(ui, "top_frame", None)
    if frame is None:
        return 0
    frame.setStyleSheet(FRAME_QSS)
    layout = getattr(ui, "horizontalLayout_3", None)
    if layout is not None:
        layout.setContentsMargins(14, 9, 14, 9)
        layout.setSpacing(10)
    ui.top_hairline = _Hairline(frame)
    left = getattr(ui, "left_section", None)
    if left is not None:
        left.setSpacing(0)
        # The gap setupUi left after the menu button goes; a pair is a pair.
        for i in reversed(range(left.count())):
            if left.itemAt(i).spacerItem() is not None:
                left.takeAt(i)
    done = 0
    pairs = ((getattr(ui, "main_menu", None), getattr(ui, "settings_button", None), True),
             (getattr(ui, "Creat_case", None), getattr(ui, "open_case_btn", None), False))
    for first, second, icons_only in pairs:
        if first is None or second is None:
            continue
        for button, (l, r) in ((first, (8, 0)), (second, (0, 8))):
            if button is getattr(ui, "Creat_case", None):
                button.setStyleSheet(CREATE_QSS % {"h": HEIGHT - 2})
            else:
                button.setStyleSheet(raised(left=l, right=r, pad=0 if icons_only else 14))
            button.setProperty("keepStyle", True)
            button.setFont(_font(13, QtGui.QFont.DemiBold))
            _fix(button, HEIGHT + 4 if icons_only else None)
            button.setIconSize(QtCore.QSize(20 if icons_only else 18, 20 if icons_only else 18))
            button.setCursor(QtCore.Qt.PointingHandCursor)
            done += 1
    if left is not None and getattr(ui, "settings_button", None) is not None:
        i = left.indexOf(ui.settings_button)
        if i >= 0:
            left.insertSpacing(i + 1, 14)
            ui.brand = _brand(frame)
            left.insertWidget(i + 2, ui.brand)
            divider = QtWidgets.QFrame(frame)
            divider.setFixedSize(1, HEIGHT - 12)
            divider.setStyleSheet("background: #1E2940; border: none;")
            divider.setProperty("keepStyle", True)
            left.insertWidget(i + 3, divider, 0, QtCore.Qt.AlignVCenter)
            left.insertSpacing(i + 4, 14)

    box = getattr(ui, "search_frame", None)
    if box is not None:
        box.setStyleSheet(DOCK_QSS)
        box.setProperty("keepStyle", True)
    search = getattr(ui, "horizontalLayout_search", None)
    if search is not None:
        search.setContentsMargins(6, 3, 6, 3)
        search.setSpacing(8)
    inner = HEIGHT - 8
    for k, (name, accent) in enumerate(TOOLS):
        button = getattr(ui, name, None)
        if button is None:
            continue
        if name == "eye_assistant_button":
            _trim_icon(button)
        _neon(button, name, inner)
        button.setProperty("keepStyle", True)
        button.setFont(_font(13, QtGui.QFont.DemiBold))
        button.setMinimumHeight(inner)
        button.setMaximumHeight(inner)
        button.setIconSize(QtCore.QSize(18, 18))
        button.setCursor(QtCore.Qt.PointingHandCursor)
        done += 1

    if getattr(ui, "label", None) is not None:
        _case_chip(ui)
        done += 1
    return done
