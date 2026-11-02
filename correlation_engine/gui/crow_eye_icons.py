"""Crow-Eye-styled icon set — loads from gui/icons/*.svg.

Use these instead of QStyle.standardIcon throughout the app so the visual
identity stays consistent (dark + cyan accent, status colors per role).
Each call returns a cached QIcon; loading is one-shot per process.

Usage:
    from correlation_engine.gui.crow_eye_icons import CrowEyeIcons
    btn.setIcon(CrowEyeIcons.add())
    tree_item.setIcon(0, CrowEyeIcons.warning())

The SVGs are authored by `icons/_generate_icons.py`; re-run that script
if you want to tweak the shapes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from PyQt5.QtCore import QRect, QSize, Qt
from PyQt5.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PyQt5.QtWidgets import QLabel, QTableWidgetItem


# Resolved once at import time so the path string is short + consistent.
_ICONS_DIR: Path = Path(__file__).parent / "icons"

# Canonical names. Keep in sync with the SVGs in _ICONS_DIR — the
# manifest test in tests/test_crow_eye_icons.py enforces the match.
ICON_NAMES = (
    # Status
    "success", "warning", "error", "info", "fail",
    # Action
    "add", "edit", "delete", "copy", "star",
    "refresh", "download", "save", "history",
    # Navigation
    "prev", "next", "expand", "collapse", "up", "down",
    # Decoration
    "folder", "file", "chart", "search", "settings",
    "tip", "clock", "target", "link", "play", "stop", "close", "subarrow",
    "upload", "hourglass", "lock", "disk", "calendar", "text", "crow", "clipboard", "package",
    # Badges
    "bolt", "tag",
    # Result-tree hierarchy levels
    "identity", "sub_identity", "anchor", "evidence",
    # Tree relation guides + expand-state indicators (used via QSS url())
    "branch_vline", "branch_more", "branch_end", "branch_closed", "branch_open",
    # Behaviour Results view: tab, person -> Behaviour Wing -> hit
    "behaviour", "person", "behaviour_wing", "hit_ordered", "hit_any",
    # The correlation engines (a Wing = the brand's Wing art + its engine's icon)
    "engine_time", "engine_identity", "engine_behaviour",
)

# Raster brand artwork, deliberately NOT in ICON_NAMES. These are the Feather /
# Wing illustrations shared with the website, not authored UI glyphs, and they
# cannot be expressed as SVG. ICON_NAMES is manifest-tested against icons/*.svg
# in both directions, so listing them there would fail that test; they get their
# own tuple and their own coverage instead. Since 2026-10-30 (Ghassan: "the
# Feather and wings should be drawn like that exactly", the User Guide's
# Feathers / Wings cards) they are how the app marks every Wing and Feather.
RASTER_ICON_NAMES = ("feather", "wing")

# Each brand art ships at 128 px (<name>.png) and 256 px (<name>@2x.png), the
# site's icon-<name>.png pair byte for byte, plus exact-size copies for rich
# text (<name>-<px>.png and its @2x; icons/_scale_brand_art.py renders them
# from the SVG master, icons/brand/<name>-small.svg, the same way the 128 /
# 256 px files were made). A QLabel's rich text scales an <img> with no smoothing, so
# icon_label_html must be handed a file of the size it draws.
BRAND_ART_RICH_TEXT_SIZES = (14, 16, 24)


def brand_art_files(name: str):
    """Every file of the brand art ``name`` ("wing" / "feather") that ships,
    smallest first: the exact rich-text sizes and their @2x, then the 128 px
    art and its 256 px @2x."""
    paths = []
    for px in BRAND_ART_RICH_TEXT_SIZES:
        paths += [_ICONS_DIR / f"{name}-{px}.png", _ICONS_DIR / f"{name}-{px}@2x.png"]
    paths += [_ICONS_DIR / f"{name}.png", _ICONS_DIR / f"{name}@2x.png"]
    return [p for p in paths if p.exists()]


class CrowEyeIcons:
    """QIcon factories for the Crow-Eye SVG asset set.

    Each accessor lazily loads its .svg the first time it's called and
    caches the resulting QIcon on the class. The cache lives for the
    process lifetime — Qt safely shares QIcon across widgets."""

    _CACHE: Dict[str, QIcon] = {}

    @classmethod
    def _load(cls, name: str) -> QIcon:
        cached = cls._CACHE.get(name)
        if cached is not None:
            return cached
        path = _ICONS_DIR / f"{name}.svg"
        # A missing SVG yields an empty QIcon rather than raising — callers
        # that setIcon a null QIcon just don't show the icon (Qt no-op).
        icon = QIcon(str(path)) if path.exists() else QIcon()
        cls._CACHE[name] = icon
        return icon

    @classmethod
    def _load_raster(cls, name: str) -> QIcon:
        """Same contract as _load, for the .png brand artwork.

        Every size that ships (the 128 / 256 px art and the exact rich-text
        sizes) is added with its own pixel size, so Qt draws the closest one
        and only ever scales down from a size above it: crisp in a 16 px row,
        a 24 px title and a window icon alike."""
        key = f"raster:{name}"
        cached = cls._CACHE.get(key)
        if cached is not None:
            return cached
        icon = QIcon()
        for path in brand_art_files(name):
            side = QPixmap(str(path)).width()
            if side > 0:
                icon.addFile(str(path), QSize(side, side))
        cls._CACHE[key] = icon
        return icon

    # ── Brand artwork (raster): a Wing and a Feather ─────────
    # The art the User Guide draws: an indigo layered wing, a cyan quill
    # (redrawn 2026-10-30; masters in icons/brand/). Every
    # Wing and Feather marker in the app is one of these; a row naming one
    # Wing shows wing_icon() (the Wing beside its engine) instead.
    @classmethod
    def feather(cls) -> QIcon: return cls._load_raster("feather")

    @classmethod
    def wing(cls) -> QIcon: return cls._load_raster("wing")

    # ── Status ───────────────────────────────────────────────
    @classmethod
    def success(cls) -> QIcon: return cls._load("success")
    @classmethod
    def warning(cls) -> QIcon: return cls._load("warning")
    @classmethod
    def error(cls) -> QIcon: return cls._load("error")
    @classmethod
    def info(cls) -> QIcon: return cls._load("info")
    @classmethod
    def fail(cls) -> QIcon: return cls._load("fail")

    # ── Action ───────────────────────────────────────────────
    @classmethod
    def add(cls) -> QIcon: return cls._load("add")
    @classmethod
    def edit(cls) -> QIcon: return cls._load("edit")
    @classmethod
    def delete(cls) -> QIcon: return cls._load("delete")
    @classmethod
    def copy(cls) -> QIcon: return cls._load("copy")
    @classmethod
    def star(cls) -> QIcon: return cls._load("star")
    @classmethod
    def refresh(cls) -> QIcon: return cls._load("refresh")
    @classmethod
    def download(cls) -> QIcon: return cls._load("download")
    @classmethod
    def save(cls) -> QIcon: return cls._load("save")
    @classmethod
    def history(cls) -> QIcon: return cls._load("history") # load previous/last results

    # ── Navigation ───────────────────────────────────────────
    @classmethod
    def prev(cls) -> QIcon: return cls._load("prev")
    @classmethod
    def next(cls) -> QIcon: return cls._load("next")
    @classmethod
    def expand(cls) -> QIcon: return cls._load("expand")
    @classmethod
    def collapse(cls) -> QIcon: return cls._load("collapse")
    @classmethod
    def up(cls) -> QIcon: return cls._load("up")
    @classmethod
    def down(cls) -> QIcon: return cls._load("down")

    # ── Decoration ───────────────────────────────────────────
    @classmethod
    def folder(cls) -> QIcon: return cls._load("folder")
    @classmethod
    def file(cls) -> QIcon: return cls._load("file")
    @classmethod
    def chart(cls) -> QIcon: return cls._load("chart")
    @classmethod
    def search(cls) -> QIcon: return cls._load("search")
    @classmethod
    def settings(cls) -> QIcon: return cls._load("settings")
    @classmethod
    def tip(cls) -> QIcon: return cls._load("tip")
    @classmethod
    def clock(cls) -> QIcon: return cls._load("clock")
    @classmethod
    def target(cls) -> QIcon: return cls._load("target")
    @classmethod
    def link(cls) -> QIcon: return cls._load("link")
    @classmethod
    def play(cls) -> QIcon: return cls._load("play")
    @classmethod
    def stop(cls) -> QIcon: return cls._load("stop")
    @classmethod
    def close(cls) -> QIcon: return cls._load("close")
    @classmethod
    def subarrow(cls) -> QIcon: return cls._load("subarrow") # ↳ corner arrow, subordinate metric

    # ── Badges ───────────────────────────────────────────────
    @classmethod
    def bolt(cls) -> QIcon: return cls._load("bolt") # advanced wing / Identity engine only
    @classmethod
    def tag(cls) -> QIcon: return cls._load("tag") # semantic annotation marker

    # ── Result-tree hierarchy levels ─────────────────────────
    # Identity (WHO/WHAT acted) → Sub-identity (WHICH variant) →
    # Anchor (WHEN evidence co-occurred) → Evidence (WHAT proves it)
    @classmethod
    def identity(cls) -> QIcon: return cls._load("identity") # fingerprint, blue
    @classmethod
    def sub_identity(cls) -> QIcon: return cls._load("sub_identity") # branch to variant node, orange
    @classmethod
    def anchor(cls) -> QIcon: return cls._load("anchor") # pin moored to a timeline node, amber
    @classmethod
    def evidence(cls) -> QIcon: return cls._load("evidence") # record + magnifier, green

    # ── Tree relation guides + expand indicators ─────────────
    # Primarily consumed via icon_path() in QTreeWidget::branch QSS rules;
    # QIcon factories provided for manifest consistency.
    @classmethod
    def branch_vline(cls) -> QIcon: return cls._load("branch_vline")
    @classmethod
    def branch_more(cls) -> QIcon: return cls._load("branch_more")
    @classmethod
    def branch_end(cls) -> QIcon: return cls._load("branch_end")
    @classmethod
    def branch_closed(cls) -> QIcon: return cls._load("branch_closed")
    @classmethod
    def branch_open(cls) -> QIcon: return cls._load("branch_open")

    # ── Additional decoration (emoji→icon sweep, 2026-07-18) ─────
    @classmethod
    def upload(cls) -> QIcon: return cls._load("upload")
    @classmethod
    def hourglass(cls) -> QIcon: return cls._load("hourglass")
    @classmethod
    def lock(cls) -> QIcon: return cls._load("lock")
    @classmethod
    def disk(cls) -> QIcon: return cls._load("disk")
    @classmethod
    def calendar(cls) -> QIcon: return cls._load("calendar")
    @classmethod
    def text(cls) -> QIcon: return cls._load("text")
    @classmethod
    def crow(cls) -> QIcon: return cls._load("crow")  # Crow-Eye brand mark
    @classmethod
    def clipboard(cls) -> QIcon: return cls._load("clipboard")
    @classmethod
    def package(cls) -> QIcon: return cls._load("package")

    # ── Behaviour Results view (behaviour_results_view.py) ───
    # Tab = "Activity pulse"; tree levels person -> Behaviour Wing -> hit. The
    # two hit icons are grey (UBA "routine") and tinted to the hit's severity
    # by the view, so one SVG serves every severity.
    @classmethod
    def behaviour(cls) -> QIcon: return cls._load("behaviour") # head over a pulse line, sky
    @classmethod
    def person(cls) -> QIcon: return cls._load("person") # a person by SID, blue
    @classmethod
    def behaviour_wing(cls) -> QIcon: return cls._load("behaviour_wing") # a Behaviour Wing, sky
    @classmethod
    def hit_ordered(cls) -> QIcon: return cls._load("hit_ordered") # bracket + arrowed dots
    @classmethod
    def hit_any(cls) -> QIcon: return cls._load("hit_any") # bracket + loose dots

    # ── Correlation engines ──────────────────────────────────
    # Each draws how its engine groups evidence; see _generate_icons.py.
    @classmethod
    def engine_time(cls) -> QIcon: return cls._load("engine_time") # clock in a window + records, green
    @classmethod
    def engine_identity(cls) -> QIcon: return cls._load("engine_identity") # records into one identity, blue
    @classmethod
    def engine_behaviour(cls) -> QIcon: return cls._load("engine_behaviour") # a person, steps in order, violet

    @classmethod
    def icon_path(cls, name: str) -> str:
        """Posix-style absolute path of an icon SVG, for QSS url() usage
        (e.g. QTreeWidget::branch guide lines and expand indicators)."""
        return (_ICONS_DIR / f"{name}.svg").as_posix()


# ── Engines and Wings ─────────────────────────────────────────
# A Wing is shown as two icons side by side: the Wing art, then the icon of
# the engine that runs it. They are painted into ONE QIcon by _PairIconEngine,
# so every setIcon() call site stays a one-liner; the view showing them must
# be given pair_icon_size(), or Qt shrinks the pair to fit a square.

_ENGINE_ICON_NAMES = {
    "time_window_scanning": "engine_time",
    "identity_based": "engine_identity",
    "behavioural": "engine_behaviour",
}

# The gap between the two icons, as a fraction of their height.
_PAIR_GAP = 0.25

_PAIR_ENGINES = []


def pair_icon_size(height: int = 16) -> QSize:
    """The icon size a view needs to show a Wing's icon pair at ``height``."""
    return QSize(round(height * (2 + _PAIR_GAP)), height)


class _PairIconEngine(QIconEngine):
    """Two square icons in one QIcon: ``left``, a gap, then ``right``.

    ``right`` may be None (a Wing with no category yet): its slot stays empty,
    so the row's text still lines up with the Wings that have one. Disabled and
    other modes are passed through to both icons, so a greyed row greys both."""

    def __init__(self, left: QIcon, right: Optional[QIcon]):
        super().__init__()
        self._left = left
        self._right = right

    def _side(self, size: QSize) -> int:
        return max(1, min(size.height(), int(size.width() / (2 + _PAIR_GAP))))

    def actualSize(self, size, mode, state):
        side = self._side(size)
        return QSize(round(side * (2 + _PAIR_GAP)), side)

    def paint(self, painter, rect, mode, state):
        side = self._side(rect.size())
        y = rect.top() + (rect.height() - side) // 2
        self._left.paint(painter, QRect(rect.left(), y, side, side), Qt.AlignCenter, mode, state)
        if self._right is not None:
            x = rect.left() + side + round(side * _PAIR_GAP)
            self._right.paint(painter, QRect(x, y, side, side), Qt.AlignCenter, mode, state)

    def pixmap(self, size, mode, state):
        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pixmap

    def clone(self):
        # Qt owns the clone, but the Python object behind it must outlive every
        # QIcon using it: keep it referenced from the original.
        copy = _PairIconEngine(self._left, self._right)
        self._clones = getattr(self, "_clones", []) + [copy]
        return copy


def engine_icon_name(engine_type) -> Optional[str]:
    """The icon name ("engine_time", ...) of a correlation engine, by type id
    (legacy names accepted), for rich text via icon_label_html. None when the
    type is unknown."""
    from ..engine import engine_registry
    try:
        type_id = engine_registry.normalize_engine_type(engine_type)
    except engine_registry.UnknownEngineError:
        return None
    return _ENGINE_ICON_NAMES.get(type_id)


def engine_icon(engine_type) -> QIcon:
    """The icon of a correlation engine, by type id (legacy names accepted).
    An unknown type gets an empty icon, which Qt simply does not draw."""
    name = engine_icon_name(engine_type)
    return CrowEyeIcons._load(name) if name else QIcon()


def wing_icon(wing_or_category) -> QIcon:
    """A Wing's icon pair: the Wing art, then its engine's icon.

    Takes a Wing (config object or dict) or a category ("time", "identity",
    "behaviour"). A Wing with no category gets the wing alone, in a pair-wide
    icon so it lines up with the rest."""
    from ..engine import engine_registry
    if isinstance(wing_or_category, str) or wing_or_category is None:
        category = wing_or_category
    else:
        category = engine_registry.wing_category_of(wing_or_category)
    spec = engine_registry.spec_for_category(category)
    key = f"pair:{spec.type_id if spec else 'none'}"
    cached = CrowEyeIcons._CACHE.get(key)
    if cached is None:
        right = engine_icon(spec.type_id) if spec else None
        engine = _PairIconEngine(CrowEyeIcons.wing(), right)
        _PAIR_ENGINES.append(engine)  # alive as long as the cached QIcon
        cached = QIcon(engine)
        CrowEyeIcons._CACHE[key] = cached
    return cached


def engine_wing_icon(engine_type) -> QIcon:
    """The icon pair of a Wing run by ``engine_type`` (the Wing art, then that
    engine's icon), for views that know the engine but not the Wing's category.
    An unknown engine gets the Wing alone, pair-wide."""
    from ..engine import engine_registry
    try:
        category = engine_registry.get_spec(engine_type).wing_category
    except Exception:
        category = None
    return wing_icon(category)


# Mapping from bracketed status tags used throughout the GUI to the
# matching Crow-Eye icon name. Lets `apply_status_to_label` accept either
# the short tag ("WARN") or the full icon name ("warning").
_TAG_TO_ICON_NAME: Dict[str, str] = {
    "OK": "success",
    "WARN": "warning",
    "ERROR": "error",
    "FAIL": "fail",
    "INFO": "info",
    "HINT": "tip",
    # Direct passthrough so callers can name the icon explicitly.
    "success": "success",
    "warning": "warning",
    "error": "error",
    "fail": "fail",
    "info": "info",
    "tip": "tip",
    "bolt": "bolt",
    "tag": "tag",
}


def status_label_html(severity: str, text: str, size_px: int = 14) -> str:
    """Build a rich-text HTML fragment combining a Crow-Eye icon with text.

    `severity` accepts either a tag ("WARN", "OK", "ERROR", "FAIL", "INFO",
    "HINT") or a direct icon name ("warning", "success", "error", ...).
    Unknown severities fall back to no icon — text only.

    Designed for QLabel widgets that previously used bracketed text tags
    like "[WARN] message"; replaces both the tag and the message with a
    single inline image + text pair so the label renders an icon plus
    the message text."""
    icon_name = _TAG_TO_ICON_NAME.get(severity)
    if icon_name is None:
        return text
    path = (_ICONS_DIR / f"{icon_name}.svg").as_posix()
    return f'<img src="{path}" width="{size_px}" height="{size_px}"> {text}'


def icon_label_html(name: str, text: str, size_px: int = 16) -> str:
    """Rich-text fragment pairing any Crow-Eye icon with `text`.

    Like `status_label_html` but takes a direct icon name rather than a
    severity tag, and resolves .svg or .png so the raster brand artwork
    (feather / wing) works as well as the authored glyph set. Used for
    QGroupBox headings, which have no icon API of their own. The brand art
    resolves to its exact-size file (wing-16.png, Qt taking wing-16@2x.png
    on a high-density screen): rich text scales an <img> with no smoothing.

    Returns bare text if no asset matches, so a caller never ends up with a
    broken-image box in the UI."""
    for path in (_ICONS_DIR / f"{name}.svg", _ICONS_DIR / f"{name}-{size_px}.png",
                 _ICONS_DIR / f"{name}.png"):
        if path.exists():
            return (f'<img src="{path.as_posix()}" width="{size_px}" '
                    f'height="{size_px}"> {text}')
    return text


def icon_table_item(icon: QIcon, text) -> QTableWidgetItem:
    """A table cell with ``icon`` before ``text``. How a column that names a
    Wing or a Feather marks each row: icon_table_item(CrowEyeIcons.feather(), name)."""
    item = QTableWidgetItem(str(text))
    item.setIcon(icon)
    return item


def group_title_label(name: str, text: str, size_px: int = 16) -> QLabel:
    """A QLabel styled as a group-box heading, with an icon before the text.

    QGroupBox has no setIcon, so the pattern is: clear the box's own title
    and insert this as the first row of its layout. Weight and size are set
    to match the title it replaces so the box still reads as a heading."""
    label = QLabel()
    label.setTextFormat(Qt.RichText)
    label.setText(icon_label_html(name, f"<b>{text}</b>", size_px=size_px))
    return label


def apply_status_to_label(
    label: QLabel,
    severity: str,
    text: str,
    size_px: int = 14,
) -> None:
    """Set `label` to a Crow-Eye icon plus `text` via QLabel rich-text.

    Equivalent to the old `label.setText("[WARN] text")` pattern but
    renders the icon as an inline image and leaves the message text
    icon-free. Sets the label's text format to RichText so the `<img>`
    tag is honored regardless of the default (most Qt builds auto-detect
    HTML, but being explicit prevents surprises)."""
    label.setTextFormat(Qt.RichText)
    label.setText(status_label_html(severity, text, size_px=size_px))
