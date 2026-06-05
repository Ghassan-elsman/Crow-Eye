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

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QLabel


# Resolved once at import time so the path string is short + consistent.
_ICONS_DIR: Path = Path(__file__).parent / "icons"

# Canonical names. Keep in sync with the SVGs in _ICONS_DIR — the
# manifest test in tests/test_crow_eye_icons.py enforces the match.
ICON_NAMES = (
    # Status
    "success", "warning", "error", "info", "fail",
    # Action
    "add", "edit", "delete", "copy", "star",
    "refresh", "download", "save",
    # Navigation
    "prev", "next", "expand", "collapse", "up", "down",
    # Decoration
    "folder", "file", "chart", "search", "settings",
    "tip", "clock", "target", "link", "play", "stop", "close",
)


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
