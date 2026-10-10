"""The website's look for whole windows: one stylesheet, set once.

The loading / parse dialog (ui/Loading_dialog.py) was the first surface in the
site's look - Barlow Semi Condensed and JetBrains Mono, the slate card, the
indigo -> cyan strip, pill buttons, quiet tables. Its pieces lived privately in
that module; they live here now, and Settings, Eye AI's Advanced settings,
Database Search and Saved Searches take the same look through
``apply_site_theme(dialog)``.

Why one sheet: those windows set a separate ``setStyleSheet`` on almost every
widget (title, label, input, button, table...). Qt polishes each of those on
its own, and every one hard-coded the old neon palette. ``apply_site_theme``
sets ONE sheet on the window, clears the per-widget ones (keeping the few
marked ``keepStyle``), and turns what they said into a role - a title, a muted
hint, a primary / ghost / danger button, a card - that the sheet styles.

No translucent window and no glow: these are large, resizable windows with
long tables, and a translucent top-level makes Qt repaint everything under any
change. Ghassan's choice (2026-10-09): the native frame, the card look inside.

Capitals and letter spacing go through QFont (``font()`` below): Qt
stylesheets ignore text-transform and letter-spacing. The Eye's own name is
never uppercased - give its title ``role="brand"``.
"""
import re

from PyQt5 import QtCore, QtGui, QtWidgets

# The site's tokens (crow-eye.com style.css), as in styles.Colors.SITE_*.
BG = "#0A0C10"          # window well
CARD = "#0F172A"        # cards, rails
CARD_2 = "#131C31"      # a card inside a card, hover rows
LINE = "rgba(255, 255, 255, 0.08)"
LINE_2 = "rgba(255, 255, 255, 0.14)"
INDIGO = "#6366F1"
INDIGO_HOVER = "#818CF8"
CYAN = "#22D3EE"
ROSE = "#F43F5E"
TEXT = "#F8FAFC"
BODY = "#E2E8F0"
MUTED = "#94A3B8"
LAVENDER = "#A5B4FC"


# Meaning colours, one place: status text, item foregrounds, chart series.
STATUS_COLORS = {
    "ok": "#4ADE80", "warn": "#FBBF24", "bad": "#FDA4AF", "info": "#22D3EE",
    "accent": "#A5B4FC", "neutral": "#94A3B8",
}
# Scores: high / medium / low / none (the engines' 0.7 and 0.4 cut-offs).
SCORE_COLORS = {"high": "#4ADE80", "medium": "#FBBF24", "low": "#FDA4AF", "none": "#64748B"}
# Chart series: the site's indigo / cyan family first, then distinct but calm.
CHART_PALETTE = ("#6366F1", "#22D3EE", "#A78BFA", "#2DD4BF", "#FBBF24", "#F472B6",
                 "#38BDF8", "#A3E635", "#FB923C", "#94A3B8", "#818CF8", "#34D399")


def score_kind(score):
    """'high' / 'medium' / 'low' / 'none' for a 0..1 score."""
    try:
        v = float(score)
    except (TypeError, ValueError):
        return "none"
    if v >= 0.7:
        return "high"
    if v >= 0.4:
        return "medium"
    return "low" if v > 0 else "none"


def severity_kind(severity):
    """critical / high -> bad, medium -> warn, low / info -> ok."""
    s = str(severity or "").strip().lower()
    if s in ("critical", "high"):
        return "bad"
    if s == "medium":
        return "warn"
    if s in ("low", "info", "informational"):
        return "ok"
    return "neutral"


def chart_color(key, order=None):
    """A stable colour per series key (a feather keeps its colour in every
    chart), from CHART_PALETTE. ``order`` - the full key list - assigns
    colours by sorted name, so two charts sorted differently still agree."""
    keys = sorted(order) if order else None
    if keys and key in keys:
        return CHART_PALETTE[keys.index(key) % len(CHART_PALETTE)]
    import zlib
    return CHART_PALETTE[zlib.crc32(str(key).encode("utf-8")) % len(CHART_PALETTE)]


def families():
    """(interface family, monospace family): Barlow Semi Condensed and
    JetBrains Mono when they registered, else Segoe UI / Consolas."""
    try:
        from ui.app_fonts import ui_family, mono_family
        return ui_family(), mono_family()
    except Exception:
        return "Segoe UI", "Consolas"


def font(family, px, weight=QtGui.QFont.Normal, upper=False, spacing=100.0):
    """A QFont in pixels. ``family`` is a family name, or "ui" / "mono"."""
    if family in ("ui", "mono"):
        family = families()[0 if family == "ui" else 1]
    f = QtGui.QFont(family)
    f.setPixelSize(int(px))
    f.setWeight(weight)
    if upper:
        f.setCapitalization(QtGui.QFont.AllUppercase)
    if spacing != 100.0:
        f.setLetterSpacing(QtGui.QFont.PercentageSpacing, spacing)
    return f


class Card(QtWidgets.QFrame):
    """A card: background and hairline from the stylesheet, plus the site's
    3 px indigo -> cyan strip along the top edge, clipped to the corners."""

    RADIUS = 20.0
    grip = None                       # a resize grip kept in the corner, if any

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.grip is not None:
            self.grip.move(self.width() - self.grip.width() - 6,
                           self.height() - self.grip.height() - 6)
            self.grip.raise_()

    def paintEvent(self, event):
        super().paintEvent(event)
        if event.rect().top() > 3:    # the strip is not in the damaged area
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(r, self.RADIUS, self.RADIUS)
        p.setClipPath(clip)
        g = QtGui.QLinearGradient(r.left(), 0, r.right(), 0)
        g.setColorAt(0.0, QtGui.QColor(INDIGO))
        g.setColorAt(1.0, QtGui.QColor(CYAN))
        p.fillRect(QtCore.QRectF(r.left(), r.top(), r.width(), 3.0), g)
        p.end()


class Grip(QtWidgets.QSizeGrip):
    """Resize handle drawn as six slate dots (the native grip is a grey hatch)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.setCursor(QtCore.Qt.SizeFDiagCursor)
        self.setToolTip("Drag to resize")

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(INDIGO if self.underMouse() else "#475569"))
        w, h = self.width(), self.height()
        for dx, dy in ((4, 12), (8, 8), (12, 4), (8, 12), (12, 8), (12, 12)):
            p.drawEllipse(QtCore.QPointF(w - 16 + dx, h - 16 + dy), 1.3, 1.3)
        p.end()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()


# --- glyphs ----------------------------------------------------------------------
# Spin-box arrows and the check mark. The CSS border-triangle trick draws a bar
# inside spin-box sub-controls, so these are tiny SVG files, written once per
# install to the temp folder (a frozen build has no writable program folder;
# Qt's stylesheet url() needs a real path or a compiled resource).
_GLYPHS = {
    "up": '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6" viewBox="0 0 10 6">'
          '<path d="M1 5 L5 1 L9 5" fill="none" stroke="%s" stroke-width="1.6" '
          'stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "down": '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6" viewBox="0 0 10 6">'
            '<path d="M1 1 L5 5 L9 1" fill="none" stroke="%s" stroke-width="1.6" '
            'stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "check": '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
             '<path d="M2.5 6.2 L5 8.6 L9.6 3.4" fill="none" stroke="%s" stroke-width="1.9" '
             'stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "right": '<svg xmlns="http://www.w3.org/2000/svg" width="6" height="10" viewBox="0 0 6 10">'
             '<path d="M1 1 L5 5 L1 9" fill="none" stroke="%s" stroke-width="1.6" '
             'stroke-linecap="round" stroke-linejoin="round"/></svg>',
}
_glyph_paths = {}


def glyph(name, colour):
    """Path (forward slashes) of a small SVG glyph in ``colour``."""
    key = (name, colour)
    if key in _glyph_paths:
        return _glyph_paths[key]
    import os
    import tempfile
    folder = os.path.join(tempfile.gettempdir(), "crow_eye_site_theme_1")
    path = os.path.join(folder, "%s_%s.svg" % (name, colour.strip("#")))
    want = _GLYPHS[name] % colour
    try:
        try:
            with open(path, "r", encoding="ascii") as fh:
                ok = fh.read() == want
        except (OSError, ValueError):
            ok = False
        if not ok:
            # Written whole or not at all: a half-written or emptied file
            # (crash, antivirus, two Crow-Eyes at once) was kept for good and
            # every arrow and check mark rendered blank.
            os.makedirs(folder, exist_ok=True)
            tmp = "%s.%d.tmp" % (path, os.getpid())
            with open(tmp, "w", encoding="ascii") as fh:
                fh.write(want)
            os.replace(tmp, path)
    except OSError:
        path = ""
    _glyph_paths[key] = path.replace("\\", "/")
    return _glyph_paths[key]


def _img(name, colour):
    p = glyph(name, colour)
    return 'image: url("%s");' % p if p else "image: none;"


# --- the sheet -------------------------------------------------------------------
_QSS_CACHE = {}


def site_qss():
    ui, mono = families()
    if (ui, mono) in _QSS_CACHE:
        return _QSS_CACHE[(ui, mono)]
    _QSS_CACHE[(ui, mono)] = _build_qss(ui, mono)
    return _QSS_CACHE[(ui, mono)]


def _build_qss(ui, mono):
    return """
QDialog, QWidget#siteWindow { background-color: %(BG)s; color: %(BODY)s; }
QWidget { font-family: '%(ui)s'; font-size: 13px; color: %(BODY)s; }
QHeaderView, QHeaderView QWidget { font-size: 11px; font-weight: 700; }
QWidget#siteRail { background-color: %(CARD)s; border-right: 1px solid %(LINE)s; }
QStackedWidget, QStackedWidget > QWidget, QScrollArea, QScrollArea > QWidget,
QScrollArea > QWidget > QWidget,
QTabWidget > QStackedWidget > QWidget { background-color: transparent; }
QScrollArea { border: none; }
QSplitter::handle { background: transparent; }

QLabel { background: transparent; border: none; padding: 0; color: %(BODY)s; }
QLabel:disabled, QLabel[role]:disabled { color: #64748B; }
QLabel[role="title"], QLabel[role="brand"] { color: %(TEXT)s; font-size: 24px; font-weight: 800; }
QLabel[role="section"] { color: %(LAVENDER)s; font-size: 14px; font-weight: 700; }
QLabel[role="subtitle"] { color: %(LAVENDER)s; font-size: 15px; font-weight: 600; }
QLabel[role="label"] { color: %(BODY)s; font-size: 14px; font-weight: 600; }
QLabel[role="muted"] { color: %(MUTED)s; font-size: 12px; }
QLabel[role="mono"] { color: %(MUTED)s; font-family: '%(mono)s'; font-size: 12px; }
QLabel[role="note"] { color: %(CYAN)s; background: rgba(34, 211, 238, 0.06);
    border: 1px solid rgba(34, 211, 238, 0.18); border-radius: 8px; padding: 6px 10px; }

QFrame[card="true"], QGroupBox {
    background-color: %(CARD)s; border: 1px solid %(LINE)s; border-radius: 14px; }
QFrame[card="true"] QLabel, QGroupBox QLabel { background: transparent; }
QGroupBox { margin-top: 20px; padding: 14px 14px 12px 14px; font-weight: 700; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 4px;
    padding: 0 4px; color: %(MUTED)s; font-size: 11px; font-weight: 700; }
QGroupBox::indicator { width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid %(LINE_2)s; background: %(BG)s; }
QGroupBox::indicator:checked { background: %(INDIGO)s; border-color: %(INDIGO)s; }
QFrame[frameShape="4"], QFrame[frameShape="5"] { color: %(LINE)s; background: %(LINE)s; border: none; }

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QDateEdit, QTimeEdit,
QTextEdit, QPlainTextEdit {
    background-color: %(BG)s; color: %(TEXT)s; border: 1px solid %(LINE_2)s;
    border-radius: 10px; padding: 7px 10px; selection-background-color: rgba(99, 102, 241, 0.45); }
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QDateTimeEdit:hover {
    border-color: rgba(129, 140, 248, 0.45); }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateTimeEdit:focus,
QTextEdit:focus, QPlainTextEdit:focus { border: 1px solid %(INDIGO)s; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QDateTimeEdit:disabled, QTextEdit:disabled { color: #64748B; background-color: rgba(15, 23, 42, 0.6);
    border-color: %(LINE)s; }
QLineEdit[field="large"] { font-size: 15px; padding: 9px 14px; border-radius: 12px; }
QComboBox::drop-down, QDateTimeEdit::drop-down { border: none; width: 26px; }
QComboBox::down-arrow, QDateTimeEdit::down-arrow { %(IMG_DOWN)s width: 10px; height: 6px; margin-right: 8px; }
QComboBox::down-arrow:hover, QDateTimeEdit::down-arrow:hover { %(IMG_DOWN_HOT)s }
QComboBox QAbstractItemView { background: %(CARD)s; color: %(BODY)s; border: 1px solid %(LINE_2)s;
    selection-background-color: rgba(99, 102, 241, 0.30); outline: 0; }
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {
    border: none; width: 22px; background: transparent; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { %(IMG_UP)s width: 10px; height: 6px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { %(IMG_DOWN)s width: 10px; height: 6px; }
QSpinBox::up-arrow:hover, QDoubleSpinBox::up-arrow:hover { %(IMG_UP_HOT)s }
QSpinBox::down-arrow:hover, QDoubleSpinBox::down-arrow:hover { %(IMG_DOWN_HOT)s }

QCheckBox, QRadioButton { background: transparent; color: %(BODY)s; spacing: 9px; }
QCheckBox::indicator, QRadioButton::indicator { width: 18px; height: 18px;
    border: 1px solid %(LINE_2)s; background: %(BG)s; }
QCheckBox::indicator { border-radius: 6px; }
QRadioButton::indicator { border-radius: 10px; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: %(INDIGO_HOVER)s; }
QCheckBox::indicator:checked { background: %(INDIGO)s; border-color: %(INDIGO)s; %(IMG_CHECK)s }
QCheckBox::indicator:checked:hover { background: %(INDIGO_HOVER)s; border-color: %(INDIGO_HOVER)s; }
QRadioButton::indicator:checked {
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 #FFFFFF, stop:0.35 #FFFFFF, stop:0.45 %(INDIGO)s, stop:1 %(INDIGO)s);
    border-color: %(INDIGO)s; }
QCheckBox::indicator:disabled { background: rgba(15, 23, 42, 0.6); border-color: %(LINE)s; }
QCheckBox:disabled, QRadioButton:disabled { color: #64748B; }
QCheckBox[variant="pill"] { color: %(MUTED)s; background: transparent;
    border: 1px solid rgba(255, 255, 255, 0.10); border-radius: 13px; padding: 4px 13px; }
QCheckBox[variant="pill"]::indicator { width: 0; height: 0; border: none; }
QCheckBox[variant="pill"]:hover { color: %(TEXT)s; border-color: %(INDIGO)s; }
QCheckBox[variant="pill"]:checked { color: %(LAVENDER)s; border-color: %(INDIGO)s;
    background: rgba(99, 102, 241, 0.16); }

QPushButton { background: rgba(99, 102, 241, 0.10); color: %(LAVENDER)s;
    border: 1px solid rgba(99, 102, 241, 0.45); border-radius: 15px; padding: 6px 18px;
    font-weight: 700; min-height: 18px; }
QPushButton:hover { background: rgba(99, 102, 241, 0.22); color: %(TEXT)s; border-color: %(INDIGO_HOVER)s; }
QPushButton:pressed { background: rgba(99, 102, 241, 0.32); }
QPushButton:disabled { color: #475569; background: transparent; border-color: %(LINE)s; }
QPushButton:checked { background: rgba(99, 102, 241, 0.22); color: %(TEXT)s; border-color: %(INDIGO)s; }
QPushButton[variant="primary"] { color: #FFFFFF; border: none;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 %(INDIGO)s, stop:1 #4F46E5); }
QPushButton[variant="primary"]:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 %(INDIGO_HOVER)s, stop:1 %(CYAN)s); }
QPushButton[variant="primary"]:pressed { background: #4F46E5; }
QPushButton[variant="primary"]:disabled { background: rgba(99, 102, 241, 0.18); color: #64748B; }
QPushButton[variant="ghost"] { background: transparent; color: %(MUTED)s; border: 1px solid %(LINE_2)s; }
QPushButton[variant="ghost"]:hover { color: %(TEXT)s; background: rgba(255, 255, 255, 0.06);
    border-color: rgba(255, 255, 255, 0.28); }
QPushButton[variant="danger"] { background: transparent; color: %(MUTED)s; border: 1px solid %(LINE_2)s; }
QPushButton[variant="danger"]:hover { color: #FFFFFF; background: %(ROSE)s; border-color: %(ROSE)s; }
QPushButton[variant="danger"]:pressed { background: #E11D48; border-color: #E11D48; }
QPushButton[variant="danger"]:disabled { color: #FDA4AF; background: rgba(244, 63, 94, 0.08);
    border-color: rgba(244, 63, 94, 0.35); }
QPushButton[variant="warning"] { background: transparent; color: #FBBF24;
    border: 1px solid rgba(251, 191, 36, 0.55); }
QPushButton[variant="warning"]:hover { color: #0A0C10; background: #FBBF24; border-color: #FBBF24; }
QPushButton[variant="warning"]:disabled { color: rgba(251, 191, 36, 0.75); background: rgba(251, 191, 36, 0.08);
    border-color: rgba(251, 191, 36, 0.35); }
QLabel[status="ok"] { color: #4ADE80; }
QLabel[status="warn"] { color: #FBBF24; }
QLabel[status="bad"] { color: #FDA4AF; }
QLabel[status="info"] { color: #22D3EE; }
QLabel[status="accent"] { color: #A5B4FC; }
QLabel[status="neutral"] { color: %(MUTED)s; }
QLabel[status="ok"][role="note"] { color: #4ADE80; background: rgba(74, 222, 128, 0.07);
    border: 1px solid rgba(74, 222, 128, 0.25); }
QLabel[status="warn"][role="note"] { color: #FBBF24; background: rgba(251, 191, 36, 0.07);
    border: 1px solid rgba(251, 191, 36, 0.28); }
QLabel[status="bad"][role="note"] { color: #FDA4AF; background: rgba(244, 63, 94, 0.07);
    border: 1px solid rgba(244, 63, 94, 0.30); }
QFrame[status="ok"] { border: 1px solid rgba(74, 222, 128, 0.45); }
QFrame[status="warn"] { border: 1px solid rgba(251, 191, 36, 0.45); }
QFrame[status="bad"] { border: 1px solid rgba(244, 63, 94, 0.45); }
QLineEdit[status="ok"] { border: 1px solid rgba(74, 222, 128, 0.55); color: #4ADE80; }
QLineEdit[status="warn"] { border: 1px solid rgba(251, 191, 36, 0.55); color: #FBBF24; }
QLabel[status] { border: none; }
QPushButton[dense="true"] { padding: 5px 11px; }
QLabel[role="caption"] { color: %(LAVENDER)s; font-size: 12px; font-weight: 700; }
QLabel[role="readout"], QLabel[role="readout"][status] { background: rgba(30, 41, 59, 0.55);
    border: 1px solid %(LINE)s; border-radius: 8px; padding: 5px 10px; }
QLabel[role="readout"] { color: %(BODY)s; }
QLabel[mono="true"] { font-family: '%(mono)s'; }
QLabel[rule="true"], QLabel[rule="true"][status] { border-bottom: 1px solid rgba(99, 102, 241, 0.45);
    padding-bottom: 5px; }
QLabel[bold="true"] { font-weight: 700; }
QCheckBox[status="ok"] { color: #4ADE80; }
QCheckBox[status="warn"] { color: #FBBF24; }
QCheckBox[status="bad"] { color: #FDA4AF; }
QCheckBox[status="info"] { color: #22D3EE; }
QPushButton[variant="pill"] { background: transparent; color: %(MUTED)s; font-weight: 600;
    border: 1px solid rgba(255, 255, 255, 0.10); border-radius: 13px; padding: 3px 13px; }
QPushButton[variant="pill"]:hover { color: %(TEXT)s; border-color: %(INDIGO)s; }
QPushButton[variant="pill"]:checked { color: %(LAVENDER)s; border-color: %(INDIGO)s;
    background: rgba(99, 102, 241, 0.16); }
QPushButton[variant="nav"] { background: transparent; color: %(MUTED)s; border: none;
    border-left: 3px solid transparent; border-radius: 0; text-align: left;
    padding: 10px 16px; font-size: 14px; font-weight: 600; }
QPushButton[variant="nav"]:hover { color: %(TEXT)s; background: rgba(255, 255, 255, 0.04); }
QPushButton[variant="nav"][active="true"] { color: %(TEXT)s; background: rgba(99, 102, 241, 0.14);
    border-left: 3px solid %(CYAN)s; }
QToolButton { background: transparent; color: %(MUTED)s; border: none; border-radius: 8px; padding: 4px; }
QToolButton:hover { color: %(TEXT)s; background: rgba(255, 255, 255, 0.06); }

QTabWidget::pane { border: 1px solid %(LINE)s; border-radius: 14px; background: %(CARD)s; top: -1px; }
QTabBar { background: transparent; }
QTabBar::tab { background: transparent; border: 1px solid transparent;
    border-radius: 13px; padding: 6px 16px; margin: 0 4px 8px 0; }
QTabBar::tab:hover { border-color: rgba(255, 255, 255, 0.12); }
QTabBar::tab:selected { background: rgba(99, 102, 241, 0.16); border-color: %(INDIGO)s; }

QTableView, QTreeView, QListView, QTableWidget, QTreeWidget, QListWidget {
    background-color: rgba(10, 12, 16, 0.55); alternate-background-color: rgba(255, 255, 255, 0.02);
    color: %(BODY)s; border: 1px solid %(LINE)s; border-radius: 12px; outline: 0;
    gridline-color: rgba(255, 255, 255, 0.04);
    selection-background-color: rgba(99, 102, 241, 0.28); selection-color: %(TEXT)s; }
QTableView::item, QTreeView::item, QListView::item { padding: 4px 6px; border: none;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04); }
QTableView::item:hover, QTreeView::item:hover, QListView::item:hover { background: rgba(99, 102, 241, 0.08); }
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {
    background: rgba(99, 102, 241, 0.28); color: %(TEXT)s; }
QHeaderView { background: transparent; border: none; }
QHeaderView::section { background: transparent; color: %(MUTED)s; border: none;
    border-bottom: 1px solid %(LINE)s; padding: 8px 8px 6px 8px; }
QHeaderView::section:hover { color: %(TEXT)s; }
QTableCornerButton::section { background: transparent; border: none; }

QProgressBar { border: none; border-radius: 7px; background-color: #1E293B; color: %(TEXT)s;
    text-align: center; font-weight: 700; min-height: 14px; }
QProgressBar[variant="slim"] { color: transparent; border-radius: 5px; min-height: 10px; max-height: 10px; }
QProgressBar::chunk { border-radius: 7px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 %(INDIGO)s, stop:1 %(CYAN)s); }
QStatusBar { background: transparent; color: %(MUTED)s; border-top: 1px solid %(LINE)s; }
QStatusBar QLabel { color: %(MUTED)s; }
QToolTip { background: %(CARD)s; color: %(BODY)s; border: 1px solid %(LINE_2)s; border-radius: 8px;
    padding: 6px 8px; }
QCalendarWidget QWidget { background: %(CARD)s; color: %(BODY)s; }
QCalendarWidget QAbstractItemView:enabled { selection-background-color: %(INDIGO)s; }
QMenuBar { background: %(CARD)s; color: %(BODY)s; border-bottom: 1px solid %(LINE)s; padding: 2px 6px; }
QMenuBar::item { background: transparent; padding: 5px 11px; margin: 2px 1px;
    border-radius: 7px; }
QMenuBar::item:selected { background: rgba(99, 102, 241, 0.18); color: %(TEXT)s; }
QMenuBar::item:pressed { background: rgba(99, 102, 241, 0.30); color: %(TEXT)s; }
QMenuBar::item:disabled { color: #475569; }
QMenu { background: %(CARD)s; color: %(BODY)s; border: 1px solid %(LINE_2)s; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 6px 18px; border-radius: 6px; }
QMenu::item:selected { background: rgba(99, 102, 241, 0.25); color: %(TEXT)s; }
QMenu::item:disabled { color: #475569; background: transparent; }
QMenu::separator { height: 1px; background: %(LINE_2)s; margin: 5px 10px; }
QMenu::indicator { width: 14px; height: 14px; border-radius: 4px; border: 1px solid %(LINE_2)s;
    margin-left: 4px; }
QMenu::indicator:checked { background: %(INDIGO)s; border-color: %(INDIGO)s; %(IMG_CHECK)s }
QMenu::right-arrow { %(IMG_RIGHT)s width: 6px; height: 10px; margin-right: 6px; }
""" % dict(BG=BG, CARD=CARD, LINE=LINE, LINE_2=LINE_2, INDIGO=INDIGO, INDIGO_HOVER=INDIGO_HOVER,
           CYAN=CYAN, ROSE=ROSE, TEXT=TEXT, BODY=BODY, MUTED=MUTED, LAVENDER=LAVENDER,
           ui=ui, mono=mono, IMG_UP=_img("up", MUTED), IMG_DOWN=_img("down", MUTED),
           IMG_UP_HOT=_img("up", CYAN), IMG_DOWN_HOT=_img("down", CYAN),
           IMG_CHECK=_img("check", "#FFFFFF"), IMG_RIGHT=_img("right", MUTED)) + _scrollbars()


def _scrollbars():
    try:
        from styles import CrowEyeStyles
        return CrowEyeStyles.SCROLLBAR_STYLE
    except Exception:
        return ""


# --- roles -------------------------------------------------------------------------
def set_role(widget, role):
    """A label's role: title / brand / section / subtitle / label / muted / mono / note.
    Titles are uppercased through QFont (QSS cannot); the brand never is."""
    widget.setProperty("role", role)
    if role == "title":
        widget.setFont(font("ui", 24, QtGui.QFont.ExtraBold, upper=True, spacing=104))
    elif role == "brand":
        widget.setFont(font("ui", 24, QtGui.QFont.ExtraBold, spacing=102))
    elif role == "section":
        widget.setFont(font("ui", 14, QtGui.QFont.Bold, upper=True, spacing=106))
    elif role == "caption":
        widget.setFont(font("ui", 12, QtGui.QFont.Bold, upper=True, spacing=106))
    _repolish(widget)
    return widget


def set_variant(widget, variant):
    """A button's variant: primary / ghost / danger / warning / pill / nav."""
    widget.setProperty("variant", variant)
    if variant in _BUTTON_FONT_VARIANTS:
        widget.setFont(button_font(widget.property("dense") is True))
    _repolish(widget)
    return widget


# Variants that take the site's button font (bold, uppercase, tracked).
_BUTTON_FONT_VARIANTS = ("primary", "ghost", "danger", "warning")


def button_font(dense=False):
    """The site's button font; ``dense`` for a crowded tool row (12px)."""
    if dense:
        return font("ui", 12, QtGui.QFont.Bold, upper=True, spacing=103)
    return font("ui", 13, QtGui.QFont.Bold, upper=True, spacing=106)


def set_dense(button, on=True):
    """A button in a crowded tool row: smaller font and padding, same role."""
    button.setProperty("dense", bool(on))
    if button.property("variant") in _BUTTON_FONT_VARIANTS or button.property("variant") is None:
        button.setFont(button_font(bool(on)))
    _repolish(button)
    return button


# The loading dialog's log-toolbar pills: one accent per level.
LEVEL_PILLS = {
    "ALL": (LAVENDER, INDIGO, "rgba(99, 102, 241, 0.16)"),
    "WARNING": ("#FBBF24", "#FBBF24", "rgba(251, 191, 36, 0.12)"),
    "ERROR": ("#FDA4AF", ROSE, "rgba(244, 63, 94, 0.14)"),
}


def level_pill(button, level):
    """A checkable log-level pill in the loading dialog's colours."""
    text, edge, fill = LEVEL_PILLS.get(level, LEVEL_PILLS["ALL"])
    button.setStyleSheet(
        "QPushButton { background: transparent; color: %s; border: 1px solid rgba(255,255,255,0.10);"
        " border-radius: 12px; padding: 3px 13px; font-weight: 600; min-height: 18px; }"
        " QPushButton:hover { color: %s; border-color: %s; }"
        " QPushButton:checked { color: %s; border-color: %s; background: %s; }"
        % (MUTED, TEXT, edge, text, edge, fill))
    button.setFont(font("ui", 12, QtGui.QFont.DemiBold))
    return keep_style(button)


def log_view_sheet():
    """A log viewer's well, as the loading dialog's (mono, #0A0C10)."""
    return ("QPlainTextEdit, QTextEdit { background-color: %s; color: %s; border: 1px solid %s;"
            " border-radius: 12px; padding: 8px; font-family: '%s'; font-size: 12px;"
            " selection-background-color: rgba(99, 102, 241, 0.45); }" % (BG, BODY, LINE, families()[1])
            + _scrollbars())


def set_card(frame, on=True):
    frame.setProperty("card", bool(on))
    _repolish(frame)
    return frame


def keep_style(widget, tree=False):
    """Leave this widget's own stylesheet alone (log views, warning banners,
    status pills). ``tree``: its children too - a container whose one
    objectName-keyed sheet styles everything inside it."""
    widget.setProperty("keepStyle", True)
    if tree:
        widget.setProperty("keepTree", True)
    return widget


def restyle(widget, variant=None, **props):
    """Change a themed widget's state (variant, active, ...) at run time.
    Use this instead of swapping per-widget sheets, which undoes the theme."""
    if variant is not None:
        widget.setProperty("variant", variant)
    for k, v in props.items():
        widget.setProperty(k, v)
    if variant in _BUTTON_FONT_VARIANTS:
        widget.setFont(button_font(widget.property("dense") is True))
    _repolish(widget)
    return widget


def set_status(widget, kind):
    """Colour a label / frame / line edit by meaning (ok, warn, bad, info,
    accent, neutral) through the window sheet: no per-widget sheet, so a
    later theme pass never undoes it. Use it again to change the state."""
    widget.setProperty("status", kind or None)
    if widget.styleSheet() and not widget.property("keepStyle"):
        widget.setStyleSheet("")
    _repolish(widget)
    return widget


def _in_kept_tree(w, stop):
    p = w.parentWidget()
    while p is not None and p is not stop:
        if p.property("keepTree"):
            return True
        p = p.parentWidget()
    return False


def _repolish(w):
    st = w.style()
    st.unpolish(w)
    st.polish(w)


# What a per-widget sheet said, read back into a role, so a window's hundreds of
# inline strings need no edits one by one. Explicit roles always win.
_SIZE = re.compile(r"font-size\s*:\s*(\d+(?:\.\d+)?)")
_WEIGHT = re.compile(r"font-weight\s*:\s*(\d+|bold)")
_MUTED = ("#94a3b8", "#64748b", "#9ca3af", "#6b7280", "#a0aec0", "#cbd5e1", "#888", "#aaa", "#8b949e")
_DANGER = ("#ef4444", "#dc2626", "#b91c1c", "#f43f5e", "#e11d48", "#f87171")
_PRIMARY = ("#10b981", "#059669", "#22c55e", "#16a34a", "#34d399")
_GHOST = ("#64748b", "#475569", "#6b7280", "#4b5563", "#334155", "#263449", "#1e293b", "transparent")
_WARNING = ("#f59e0b", "#d97706", "#ff9800", "#ffaa00", "#fbbf24", "#ff9900")
# Text colours read back into a status (the label keeps its meaning).
_STATUS_HUES = (
    ("ok", ("#4caf50", "#10b981", "#22c55e", "#4ade80", "#00ff00", "#00ff7f", "#34d399", "#059669", "#16a34a")),
    ("bad", ("#f44336", "#ef4444", "#f87171", "#ff0000", "#dc2626", "#fda4af", "#ff4444")),
    ("warn", ("#ff9800", "#f59e0b", "#fbbf24", "#ff9900", "#ffaa00", "#d97706", "#ffc107", "#ffa500")),
    ("accent", ("#9c27b0", "#a855f7", "#8b5cf6", "#c084fc", "#a5b4fc")),
    ("info", ("#00ffff", "#00d9ff", "#22d3ee", "#06b6d4", "#2196f3", "#3b82f6", "#60a5fa", "#00bfff")),
)


_MONO = ("consolas", "courier", "monospace", "cascadia", "jetbrains mono")


def _base_rule(sheet):
    """The widget's own declarations: a bare declaration list, or the first
    block whose selector has no pseudo-state. A ':disabled { color: ... }'
    block says nothing about the normal look (it made every Eye AI checkbox
    label "muted")."""
    s = sheet.lower()
    if "{" not in s:
        return s
    for selector, body in re.findall(r"([^{}]*)\{([^}]*)\}", s):
        if ":" not in selector:
            return body
    return ""


def _solid_background(s):
    m = re.search(r"background(?:-color)?\s*:\s*([^;]+)", s)
    if not m:
        return False
    v = m.group(1).strip()
    return not (v.startswith("transparent") or v.replace(" ", "").startswith("rgba(0,0,0,0)"))


def _infer_status(sheet):
    s = _base_rule(sheet)
    m = re.search(r"(?<![-\w])color\s*:\s*(#[0-9a-f]{3,8}|[a-z]+)", s)
    if not m:
        return None
    c = m.group(1)
    for kind, hues in _STATUS_HUES:
        if c in hues:
            return kind
    return None


def _infer_label_props(sheet):
    """(role, props) for what a label's old sheet meant.

    Sizes are read as written (a pt value as its number, the round-16 tuning
    every window was approved with). Bold is weight 600 or more. A sheet with
    a solid background and a border / padding was a boxed read-out; one with a
    bottom border was an underlined heading; a monospace family stays mono."""
    s = _base_rule(sheet)
    m = _SIZE.search(s)
    size = float(m.group(1)) if m else 0
    w = _WEIGHT.search(s)
    bold = bool(w) and (w.group(1) == "bold" or int(w.group(1)) >= 600)
    muted = any(c in s for c in _MUTED)
    props = {}
    if any(f in s for f in _MONO):
        props["mono"] = True
    if size >= 18:
        role = "title"
    elif _solid_background(s) and ("border" in s or "padding" in s):
        role = "readout"
        if muted:
            props["status"] = "neutral"
    elif "border-bottom" in s and bold:
        role, props["rule"] = "section", True
    elif bold and size >= 14 and ("#00ffff" in s or "#22d3ee" in s or "#a5b4fc" in s or "#60a5fa" in s):
        role = "section"
    elif "italic" in s or muted:
        role = "muted"
    elif bold and size and size <= 12:
        role = "caption"
    elif size and size <= 12:
        role = "muted"
    elif bold:
        role = "label"
    else:
        role = "mono" if props.pop("mono", None) else None
    if bold and role == "muted":
        props["bold"] = True
    return role, props


def _infer_label(sheet):
    return _infer_label_props(sheet)[0]


def _infer_button(sheet):
    head = _base_rule(sheet) or sheet.lower().split("hover")[0]
    if any(c in head for c in _DANGER):
        return "danger"
    if any(c in head for c in _PRIMARY):
        return "primary"
    if "background-color: transparent" in head or "background: transparent" in head:
        return "ghost"
    if any(c in head for c in _WARNING):
        return "warning"
    if any(c in head for c in _GHOST[:8]):
        return "ghost"
    return None


def _infer_frame(sheet):
    s = sheet.lower()
    if "border-left" in s:            # a severity stripe means something
        return False
    return ("background" in s and "border-radius" in s) or ("border:" in s and "background" in s)


def apply_site_theme(window, *, clear_inline=True, root=None, extra=""):
    """The site look on ``window``: one sheet, the site fonts, roles for what
    the cleared per-widget sheets said. Idempotent; cheap to call again after
    a page is rebuilt (pass that page as ``root`` to only walk it)."""
    ui, _mono = families()
    header_font = font(ui, 11, QtGui.QFont.Bold, upper=True, spacing=108)
    tab_font = font(ui, 13, QtGui.QFont.Bold)
    if root is None:
        # A window that already carries a sheet (Crow-Claw's MAIN_WINDOW):
        # drop it first. Children cleared under the old sheet otherwise keep
        # a style object tied to it and never take the new one.
        if window.styleSheet() and not _has_site_sheet(window, extra):
            window.setStyleSheet("")
        # The font BEFORE the sheet: polishing under a sheet fixes each
        # child's font, and a window font set afterwards never reaches them.
        window.setFont(font("ui", 13))
        window.setProperty("siteTheme", True)
    fonted = []
    for w in (root or window).findChildren(QtWidgets.QWidget):
        if isinstance(w, QtWidgets.QHeaderView):
            # It paints on its viewport, whose font a sheet's polish fixed:
            # set both, or the header keeps the old font.
            w.setFont(header_font)
            w.viewport().setFont(header_font)
            fonted.append(w)
        elif isinstance(w, QtWidgets.QTabBar):
            # Bold through QFont, so the tab is measured with the font it is
            # drawn in (a QSS font-weight on ::tab clipped the labels).
            w.setFont(tab_font)
            fonted.append(w)
        if not clear_inline or w.property("keepStyle") or _in_kept_tree(w, root or window):
            continue
        sheet = w.styleSheet()
        if not sheet:
            continue
        if isinstance(w, QtWidgets.QLabel) and w.property("role") is None:
            role, props = _infer_label_props(sheet)
            if role == "title" and w.text().strip().lower().startswith("eye"):
                role = "brand"
            status = props.pop("status", None)
            if status is None and role not in ("title", "brand"):
                status = _infer_status(sheet)
            if status == "info" and role in ("section", "label", "caption"):
                status = None                   # a cyan heading is a heading
            for k, v in props.items():
                w.setProperty(k, v)
            if role:
                set_role(w, role)
            if status and w.property("status") is None:
                w.setProperty("status", status)
        elif isinstance(w, QtWidgets.QCheckBox) and w.property("status") is None:
            status = _infer_status(sheet)
            if status in ("ok", "warn", "bad"):
                w.setProperty("status", status)
        elif isinstance(w, QtWidgets.QPushButton) and w.property("variant") is None:
            v = _infer_button(sheet)
            if v:
                set_variant(w, v)
        elif type(w) is QtWidgets.QFrame and w.property("card") is None and _infer_frame(sheet):
            set_card(w)
        w.setStyleSheet("")
    if root is None and not _has_site_sheet(window, extra):
        _set_site_sheet(window, extra)
        # Setting the sheet re-polished every child and reset the fonts given
        # before it: a header was then MEASURED in the sheet's font and PAINTED
        # (on its viewport) in the uppercase one, so ResizeToContents columns
        # clipped their titles ("XECUTION II"); a button's variant font and a
        # title's role font fell back to plain 13px. Give them back.
        for w in fonted:
            if isinstance(w, QtWidgets.QHeaderView):
                w.setFont(header_font)
                w.viewport().setFont(header_font)
            else:
                w.setFont(tab_font)
        _refont_roles(window)
    _one_button_family(root or window)
    return window


def _one_button_family(root):
    """Every text button in a themed window in the site's button font: the
    variant buttons had it and the plain ones beside them did not ("DELETE
    SELECTED" next to "Add Mapping"). A width cap grows to the label in that
    font, so nothing is clipped."""
    f, f_dense = button_font(), button_font(dense=True)
    for b in root.findChildren(QtWidgets.QPushButton):
        v = b.property("variant")
        if v in ("pill", "nav") or b.property("keepStyle") or not (b.text() or "").strip():
            continue
        dense = b.property("dense") is True
        if v is None:
            b.setFont(f_dense if dense else f)
        cap = b.maximumWidth()
        if cap < 16777215:
            m = QtGui.QFontMetrics(f_dense if dense else f)
            need = m.horizontalAdvance(b.text().replace("&", "").upper()) + (30 if dense else 44)
            if not b.icon().isNull():
                need += b.iconSize().width() + 6
            if need > cap:
                b.setMaximumWidth(need)


def _refont_roles(root):
    """The fonts set_variant / set_role give, set again (after a sheet change)."""
    for b in root.findChildren(QtWidgets.QPushButton):
        if b.property("variant") in _BUTTON_FONT_VARIANTS:
            b.setFont(button_font(b.property("dense") is True))
    for lbl in root.findChildren(QtWidgets.QLabel):
        if lbl.property("role") in ("title", "brand", "section", "caption"):
            set_role(lbl, lbl.property("role"))


def _full_sheet(extra=""):
    """The site sheet plus a window's own rules (one sheet, set once)."""
    return site_qss() + ("\n" + extra if extra else "")


def _set_site_sheet(window, extra=""):
    window.setStyleSheet(_full_sheet(extra))
    window._site_sheet_set = _full_sheet(extra)


def _has_site_sheet(window, extra=""):
    """Whether this exact site sheet is on ``window`` - remembered, not read
    back: styles.install_scrollbar_policy rewrites every sheet's scroll-bar
    rules on the way in, so styleSheet() never equals what was set, and the
    window was cleared and re-polished (0.37 s on a 400-field row)."""
    return getattr(window, "_site_sheet_set", None) == _full_sheet(extra) and bool(window.styleSheet())


def scrollable_tabs(tabs):
    """Put each page of ``tabs`` in a frameless scroll area, so a page taller
    than the window scrolls instead of squeezing its rows together."""
    for i in range(tabs.count()):
        page = tabs.widget(i)
        if isinstance(page, QtWidgets.QScrollArea):
            continue
        text, icon, tip = tabs.tabText(i), tabs.tabIcon(i), tabs.tabToolTip(i)
        area = QtWidgets.QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QtWidgets.QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        tabs.removeTab(i)
        area.setWidget(page)
        tabs.insertTab(i, area, icon, text)
        tabs.setTabToolTip(i, tip)
    tabs.setCurrentIndex(0)
    return tabs


def begin_site_theme(window, extra=""):
    """Put the site font and sheet on ``window`` BEFORE its children exist.

    For windows that set a sheet at the top of their constructor (Crow-Claw,
    the Offline Importer and Forensic Images set MAIN_WINDOW): replacing a
    window's sheet after its children were polished under the old one left
    them in the old fonts and colours (Qt does not re-resolve them). Call
    this instead of that first setStyleSheet, then apply_site_theme() at
    the end of the constructor for the roles."""
    window.setFont(font("ui", 13))
    window.setProperty("siteTheme", True)
    _set_site_sheet(window, extra)
    return window


def themed_message_box(parent, icon, title, text, buttons=QtWidgets.QMessageBox.Ok):
    """A QMessageBox in the site look (the static helpers take the old one)."""
    box = QtWidgets.QMessageBox(icon, title, text, buttons, parent)
    box.setStyleSheet(site_qss())
    box.setFont(font("ui", 13))
    return box.exec_()
