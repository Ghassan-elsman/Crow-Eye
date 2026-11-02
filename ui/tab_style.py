"""The main window's tabs, in two levels that read as two levels.

setupUi styles every tab widget with the same UNIFIED_TAB_STYLE, applied up to three times each, so
the artifact tabs (Registry, Prefetch, ...) and the tables under them (Registry's 40 sub-tabs) look
alike and the eye has nothing to tell them apart by. `apply(ui)` runs once after setupUi and gives:

  * the MAIN tabs a folder look: quiet labels on the bar, the chosen one joined to the page below
    it (the page's own colour, no border between them) under a cyan top line;
  * every SUB-TAB widget inside them a pill look: smaller, borderless, the chosen one filled indigo.

Weights come from QFont, never from QSS: a `font-weight` in a tab's QSS is laid out after the tab's
width is measured, which clipped labels (ui/app_theme.py notes the same). Labels are never elided
- a tab that does not fit scrolls the bar - and a disabled tab's label stays readable (the old rule
painted its text and its background the same grey).
"""
from PyQt5 import QtCore, QtGui, QtWidgets

try:
    from ui import app_theme as _theme
except Exception:                                         # pragma: no cover
    _theme = None

# Ghassan, 2026-10-31: "get back the old tabs button style". The tabs keep setupUi's own
# UNIFIED_TAB_STYLE; only the label fix stays (names never elided, a full bar scrolls). Set
# False to bring the folder / pill look below back.
OLD_LOOK = True

PANE = "#0E131C"
LINE = "#24324A"

MAIN_QSS = """
QTabWidget::pane { border: 1px solid %(line)s; border-radius: 10px; border-top-left-radius: 0px;
    background: %(pane)s; top: -1px; }
QTabBar { background: transparent; }
QTabBar::tab { background: transparent; color: #94A3B8; border: 1px solid transparent; border-bottom: none;
    border-top-left-radius: 8px; border-top-right-radius: 8px; padding: 8px 16px; margin-right: 2px; }
QTabBar::tab:hover:!selected { background: rgba(148, 163, 184, 0.10); color: #E2E8F0; }
QTabBar::tab:selected { background: %(pane)s; color: #F8FAFC; border: 1px solid %(line)s;
    border-top: 2px solid #22D3EE; border-bottom: 1px solid %(pane)s; }
QTabBar::tab:disabled { color: #475569; background: transparent; }
QTabBar::scroller { width: 52px; }
QTabBar QToolButton { background: #1E293B; border: 1px solid #334155; border-radius: 6px; margin: 3px 1px; min-width: 22px; }
QTabBar QToolButton:hover { background: #334155; border-color: #22D3EE; }
""" % {"pane": PANE, "line": LINE}

SUB_QSS = """
QTabWidget::pane { border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 8px; background: #0B1220; top: 0px; }
QTabBar { background: transparent; }
QTabBar::tab { background: transparent; color: #94A3B8; border: 1px solid transparent; border-radius: 12px;
    padding: 4px 12px; margin: 6px 4px 6px 0px; }
QTabBar::tab:hover:!selected { border-color: rgba(255, 255, 255, 0.16); color: #E2E8F0; }
QTabBar::tab:selected { background: rgba(99, 102, 241, 0.20); border-color: #6366F1; color: #E0E7FF; }
QTabBar::tab:disabled { color: #475569; }
QTabBar::scroller { width: 52px; }
QTabBar QToolButton { background: #1E293B; border: 1px solid #334155; border-radius: 6px; margin: 3px 1px; min-width: 22px; }
QTabBar QToolButton:hover { background: #334155; border-color: #6366F1; }
"""


def _font(px, weight):
    if _theme is not None:
        try:
            return _theme.font("ui", px, weight)
        except Exception:
            pass
    f = QtGui.QFont("Segoe UI", max(8, px - 4))
    f.setWeight(weight)
    return f


def _style(widget, qss, px, weight):
    bar = widget.tabBar()
    if OLD_LOOK:
        bar.setElideMode(QtCore.Qt.ElideNone)
        bar.setUsesScrollButtons(True)
        return
    widget.setStyleSheet(qss)
    bar.setFont(_font(px, weight))
    bar.setElideMode(QtCore.Qt.ElideNone)
    bar.setUsesScrollButtons(True)
    bar.setExpanding(False)
    bar.setDrawBase(False)
    widget.setDocumentMode(False)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def sub_tab_widgets(main):
    """Every QTabWidget inside the main tab widget's pages, at any depth."""
    out = []
    for i in range(main.count()):
        page = main.widget(i)
        if page is not None:
            out.extend(page.findChildren(QtWidgets.QTabWidget))
    return out


def apply(ui):
    """Restyle the main tabs and every sub-tab widget once (after setupUi). Sub-tab widgets made
    later (the MFT and LNK detail tabs) take SUB_QSS through `style_sub` at their creation."""
    main = getattr(ui, "main_tab", None)
    if main is None:
        return 0
    _style(main, MAIN_QSS, 13, QtGui.QFont.DemiBold)
    main.setIconSize(QtCore.QSize(18, 18))
    subs = sub_tab_widgets(main)
    for widget in subs:
        style_sub(widget)
    return 1 + len(subs)


def style_sub(widget):
    """One sub-tab widget in the pill look."""
    _style(widget, SUB_QSS, 12, QtGui.QFont.Medium)
