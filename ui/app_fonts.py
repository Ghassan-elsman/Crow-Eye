"""The website's two typefaces, bundled so the app looks the same everywhere.

Barlow Semi Condensed (interface text and titles) and JetBrains Mono (paths,
times, logs) are what crow-eye.com uses. Neither ships with Windows, and a Qt
stylesheet uses only the FIRST family it names - a sheet that said
'JetBrains Mono' on a machine without it did not fall back to the next family
in the list, it fell back to Qt's default. So the fonts are registered from
``GUI Resources/fonts`` at start-up, and `ui_family()` / `mono_family()` hand
out a family that is really installed.

Both are under the SIL Open Font License 1.1; the licence files sit beside
the fonts.
"""

import logging
import os
import sys

logger = logging.getLogger(__name__)

FONT_FILES = (
    "BarlowSemiCondensed-Regular.ttf", "BarlowSemiCondensed-Medium.ttf",
    "BarlowSemiCondensed-SemiBold.ttf", "BarlowSemiCondensed-Bold.ttf",
    "BarlowSemiCondensed-ExtraBold.ttf",
    "JetBrainsMono-Regular.ttf", "JetBrainsMono-Bold.ttf",
)
UI_FAMILY = "Barlow Semi Condensed"
MONO_FAMILY = "JetBrains Mono"
UI_FALLBACK = "Segoe UI"
MONO_FALLBACK = "Consolas"

_loaded = None


def fonts_dir():
    """`GUI Resources/fonts`, in the source tree or the frozen bundle."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "GUI Resources", "fonts")


def load_app_fonts():
    """Register the bundled fonts once per process; returns the set of
    families that are available afterwards. Needs a QGuiApplication."""
    global _loaded
    if _loaded is not None:
        return _loaded
    from PyQt5.QtGui import QFontDatabase
    from PyQt5.QtWidgets import QApplication
    if QApplication.instance() is None:
        return set()
    families = set()
    folder = fonts_dir()
    for name in FONT_FILES:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            logger.warning("Bundled font missing: %s", path)
            continue
        font_id = QFontDatabase.addApplicationFont(path)
        if font_id < 0:
            logger.warning("Font could not be registered: %s", path)
            continue
        families.update(QFontDatabase.applicationFontFamilies(font_id))
    _loaded = families
    logger.info("Bundled fonts: %s", ", ".join(sorted(families)) or "none")
    return families


def _available(family):
    from PyQt5.QtGui import QFontDatabase
    load_app_fonts()
    return family in QFontDatabase().families()


def ui_family():
    """'Barlow Semi Condensed' when it loaded, otherwise 'Segoe UI'."""
    return UI_FAMILY if _available(UI_FAMILY) else UI_FALLBACK


def mono_family():
    """'JetBrains Mono' when it loaded, otherwise 'Consolas'."""
    return MONO_FAMILY if _available(MONO_FAMILY) else MONO_FALLBACK
