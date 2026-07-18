"""Centralized style definitions for the Crow Eye application."""

from PyQt5.QtCore import Qt

# Unified Color Palette
class Colors:
    # Modern Dark Dashboard Base Colors
    BG_PRIMARY = "#0F172A" # Main background
    BG_PANELS = "#1E293B" # Panel background
    BG_TABLES = "#0B1220" # Dark slate for tables
    BG_CARDS = "#1E293B" # Card backgrounds
    
    # Text Colors
    TEXT_PRIMARY = "#E2E8F0" # Primary text
    TEXT_SECONDARY = "#94A3B8" # Secondary text
    TEXT_MUTED = "#64748B" # Muted text
    
    # Accent Colors
    ACCENT_BLUE = "#3B82F6" # Primary accent blue
    ACCENT_CYAN = "#00FFFF" # Neon cyan for cyberpunk accents
    ACCENT_PURPLE = "#8B5CF6" # Subtle purple for secondary highlights
    
    # Status Colors
    SUCCESS = "#10B981" # Success green
    WARNING = "#F59E0B" # Warning amber
    ERROR = "#EF4444" # Error red
    
    # Border Colors
    BORDER_SUBTLE = "#334155" # Subtle borders
    BORDER_ACCENT = "#475569" # Accent borders

class CrowEyeStyles:
    """Centralized style definitions for the Crow Eye application."""

    # Marker so the global popup stylesheet is appended to the app stylesheet at most
    # once (idempotent), even if apply_global_dark_theme is called more than once.
    _GLOBAL_THEME_MARKER = "/* CROWEYE_GLOBAL_POPUP_THEME */"

    # Type-selector-only stylesheet for the popup/dialog widgets that otherwise fall
    # back to Qt's default black text (unreadable on our dark chrome). Deliberately
    # scoped to message/input dialogs, menus and tooltips — general QDialog/QLabel
    # defaults are handled by the dark QPalette below (which any explicit per-widget
    # QSS still overrides, so already-styled dialogs are unaffected).
    POPUP_STYLESHEET = f"""
{_GLOBAL_THEME_MARKER}
QMessageBox, QInputDialog {{
    background-color: {Colors.BG_TABLES};
    color: {Colors.TEXT_PRIMARY};
}}
QMessageBox QLabel, QInputDialog QLabel {{
    color: {Colors.TEXT_PRIMARY};
    background: transparent;
    font-size: 10pt;
}}
QMessageBox QPushButton, QInputDialog QPushButton {{
    background-color: {Colors.BG_PANELS};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER_SUBTLE};
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 10pt;
    font-weight: bold;
    min-width: 80px;
    min-height: 28px;
}}
QMessageBox QPushButton:hover, QInputDialog QPushButton:hover {{
    background-color: {Colors.BORDER_SUBTLE};
    border: 1px solid {Colors.ACCENT_CYAN};
}}
QMessageBox QPushButton:pressed, QInputDialog QPushButton:pressed {{
    background-color: {Colors.BORDER_ACCENT};
}}
QInputDialog QLineEdit, QInputDialog QComboBox, QInputDialog QSpinBox,
QInputDialog QDoubleSpinBox, QMessageBox QTextEdit {{
    background-color: {Colors.BG_PANELS};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER_SUBTLE};
    border-radius: 4px;
    padding: 4px;
}}
QMenu {{
    background-color: {Colors.BG_PANELS};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER_SUBTLE};
}}
QMenu::item:selected {{
    background-color: {Colors.ACCENT_BLUE};
    color: #FFFFFF;
}}
QToolTip {{
    background-color: {Colors.BG_PANELS};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER_SUBTLE};
}}
"""

    @staticmethod
    def apply_global_dark_theme(app):
        """Apply the app-wide dark theme once, right after the QApplication is created.

        Fixes the "black text on a dark background / unstyled black-by-default" problem
        in popups and dialogs that don't set their own colors. Two parts:

        1. A dark QPalette — makes the DEFAULT text of any unstyled widget (QLabel,
           QLineEdit, QComboBox, custom QDialogs, native color/font/input dialogs) light
           on dark. A palette is a fallback that any explicit per-widget QSS overrides,
           so already-styled dialogs are not regressed.
        2. A type-selector-only popup stylesheet (POPUP_STYLESHEET), appended once, for
           the static-method popups (QMessageBox/QInputDialog) + menus/tooltips that
           Qt's native style may render with a light chrome regardless of the palette.

        Safe to call once; guarded so a theming error never blocks startup.
        """
        from PyQt5.QtGui import QPalette, QColor

        c = Colors
        pal = QPalette()
        pal.setColor(QPalette.Window, QColor(c.BG_PRIMARY))
        pal.setColor(QPalette.WindowText, QColor(c.TEXT_PRIMARY))
        pal.setColor(QPalette.Base, QColor(c.BG_TABLES))
        pal.setColor(QPalette.AlternateBase, QColor(c.BG_PANELS))
        pal.setColor(QPalette.Text, QColor(c.TEXT_PRIMARY))
        pal.setColor(QPalette.Button, QColor(c.BG_PANELS))
        pal.setColor(QPalette.ButtonText, QColor(c.TEXT_PRIMARY))
        pal.setColor(QPalette.BrightText, QColor("#FFFFFF"))
        pal.setColor(QPalette.ToolTipBase, QColor(c.BG_PANELS))
        pal.setColor(QPalette.ToolTipText, QColor(c.TEXT_PRIMARY))
        pal.setColor(QPalette.Highlight, QColor(c.ACCENT_BLUE))
        pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
        pal.setColor(QPalette.Link, QColor(c.ACCENT_CYAN))
        pal.setColor(QPalette.LinkVisited, QColor(c.ACCENT_PURPLE))
        # PlaceholderText role only exists on Qt >= 5.12 — guard for safety.
        try:
            pal.setColor(QPalette.PlaceholderText, QColor(c.TEXT_MUTED))
        except AttributeError:
            pass
        # Disabled group so greyed-out text stays legible on dark.
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            pal.setColor(QPalette.Disabled, role, QColor(c.TEXT_MUTED))
        app.setPalette(pal)

        # Append the popup stylesheet once (don't clobber existing app QSS).
        existing = app.styleSheet() or ""
        if CrowEyeStyles._GLOBAL_THEME_MARKER not in existing:
            app.setStyleSheet((existing + "\n" + CrowEyeStyles.POPUP_STYLESHEET).strip())

    @staticmethod
    def apply_table_styles(table_widget):
        """Apply consistent table styles to a QTableWidget.

        Args:
            table_widget: The QTableWidget to style
        """
        # Lazy-import so styles.py keeps a minimal import surface for callers
        # that don't actually touch widgets (tests / tooling).
        from PyQt5.QtWidgets import QHeaderView

        # Use QTableView selectors so the rules match BOTH the classic
        # QTableWidget tables AND the QTableView-based VirtualTableWidget.
        # `QTableWidget::item` would not style a QTableView (QTableView is its
        # parent class), but `QTableView::item` matches QTableWidget too
        # (it's a subclass) — so this is identical for the old tables and fixes
        # the virtual tables' cell/selection/background/scrollbar styling.
        style = CrowEyeStyles.UNIFIED_TABLE_STYLE.replace("QTableWidget", "QTableView")

        # Reset any existing styles
        table_widget.setStyleSheet('')

        # Apply the complete table style
        table_widget.setStyleSheet(style)

        # Configure header
        header = table_widget.horizontalHeader()
        if header:
            header.setStyleSheet(style)
            # Auto-fit each section to whichever is wider: header label or
            # cell content. Prevents column titles from getting truncated
            # to "Run Tim…" or similar. The last section still stretches
            # to fill any remaining horizontal space.
            header.setSectionResizeMode(QHeaderView.ResizeToContents)
            header.setStretchLastSection(True)
            header.setDefaultSectionSize(200)
            header.setMinimumSectionSize(80)
            header.setSectionsClickable(True)
            header.setHighlightSections(True)
            header.setSortIndicatorShown(True)
            header.setAttribute(Qt.WA_StyledBackground, True)

            # Force style update
            header.style().unpolish(header)
            header.style().polish(header)
            header.update()

        # Configure vertical header
        vertical = table_widget.verticalHeader()
        if vertical:
            vertical.setDefaultSectionSize(30)
            vertical.setMinimumSectionSize(24)
            vertical.setAttribute(Qt.WA_StyledBackground, True)
            vertical.style().unpolish(vertical)
            vertical.style().polish(vertical)
            vertical.update()

        # Force table style update
        table_widget.setAttribute(Qt.WA_StyledBackground, True)
        table_widget.style().unpolish(table_widget)
        table_widget.style().polish(table_widget)
        table_widget.update()

    @staticmethod
    def apply_tab_styles(tab_widget, style_name=None):
        # All tab styles now use UNIFIED_TAB_STYLE
        tab_widget.setStyleSheet(CrowEyeStyles.UNIFIED_TAB_STYLE)

        # Stretch tabs to fill any horizontal space available in the bar.
        # When the bar has more room than the tabs need, each tab grows
        # equally; when it doesn't, they fall back to their min-width and
        # Qt re-enables the scroll buttons automatically.
        try:
            bar = tab_widget.tabBar()
            if bar is not None:
                bar.setExpanding(True)
                bar.setUsesScrollButtons(True)
                # Don't elide tab text unless we genuinely run out of room.
                from PyQt5.QtCore import Qt as _Qt
                bar.setElideMode(_Qt.ElideNone)
        except Exception:
            # Some QTabBar subclasses don't expose these; degrade silently.
            pass

        # Force a style refresh to ensure styles are applied immediately
        tab_widget.style().unpolish(tab_widget)
        tab_widget.style().polish(tab_widget)
        tab_widget.update()

    @staticmethod
    def apply_tree_styles(tree_widget):
        """Apply UNIFIED_TREE_STYLE to a QTreeView / QTreeWidget."""
        tree_widget.setStyleSheet(CrowEyeStyles.UNIFIED_TREE_STYLE)
        tree_widget.setAlternatingRowColors(True)
        tree_widget.style().unpolish(tree_widget)
        tree_widget.style().polish(tree_widget)
        tree_widget.update()

    @staticmethod
    def apply_slider_styles(slider):
        """Apply UNIFIED_SLIDER_STYLE to a QSlider (horizontal or vertical)."""
        slider.setStyleSheet(CrowEyeStyles.UNIFIED_SLIDER_STYLE)
        slider.style().unpolish(slider)
        slider.style().polish(slider)
        slider.update()

    @staticmethod
    def apply_scrollarea_styles(area):
        """Apply UNIFIED_SCROLLAREA_STYLE to a QScrollArea, transparent viewport."""
        area.setStyleSheet(CrowEyeStyles.UNIFIED_SCROLLAREA_STYLE)
        # Force the viewport widget itself to be transparent — PyQt5 will
        # otherwise paint an opaque background on the inner widget.
        try:
            area.viewport().setAutoFillBackground(False)
        except Exception:
            pass
        area.style().unpolish(area)
        area.style().polish(area)
        area.update()

    @staticmethod
    def apply_dialog_styles(dialog):
        """Apply DIALOG_STYLE to a QDialog and propagate the table / tree /
        slider / scroll-area helpers to any child of those types so the
        dialog inherits the unified look without per-call wiring.

        Safe to call multiple times. Silently no-ops on import failures so
        styling never blocks dialog construction.
        """
        try:
            dialog.setStyleSheet(CrowEyeStyles.DIALOG_STYLE)
        except Exception:
            return # don't break dialog construction on a styling hiccup

        # Lazy-import the widget classes so styles.py keeps a minimal import
        # surface for non-GUI consumers.
        try:
            from PyQt5.QtWidgets import (
                QTableWidget, QTableView, QTreeWidget, QTreeView,
                QSlider, QScrollArea,
            )
        except Exception:
            return

        try:
            for t in dialog.findChildren(QTableWidget):
                CrowEyeStyles.apply_table_styles(t)
            for t in dialog.findChildren(QTableView):
                # QTableView (not QTableWidget) — apply the same QSS via setStyleSheet
                t.setStyleSheet(CrowEyeStyles.UNIFIED_TABLE_STYLE)
            for t in dialog.findChildren(QTreeWidget):
                CrowEyeStyles.apply_tree_styles(t)
            for t in dialog.findChildren(QTreeView):
                t.setStyleSheet(CrowEyeStyles.UNIFIED_TREE_STYLE)
            for s in dialog.findChildren(QSlider):
                CrowEyeStyles.apply_slider_styles(s)
            for a in dialog.findChildren(QScrollArea):
                CrowEyeStyles.apply_scrollarea_styles(a)
        except Exception:
            # findChildren can fail mid-construction; degrade gracefully.
            pass


    # ============================================================================
    # STYLE CONSTANTS - Using Colors class values for consistency
    # ============================================================================
    
    # Dynamic Linking Window Main Container Style
    DYNAMIC_LINKING_WINDOW_STYLE = f"""
        QDialog {{
            background-color: {Colors.BG_PRIMARY};
            color: {Colors.TEXT_PRIMARY};
        }}
        QLabel {{
            color: {Colors.TEXT_PRIMARY};
            font-family: 'Segoe UI', sans-serif;
        }}
        QFrame {{
            background-color: {Colors.BG_PANELS};
            border: 1px solid {Colors.BORDER_SUBTLE};
            border-radius: 8px;
        }}
        QTextEdit, QLineEdit, QComboBox {{
            background-color: {Colors.BG_TABLES};
            color: {Colors.TEXT_PRIMARY};
            border: 1px solid {Colors.BORDER_SUBTLE};
            border-radius: 4px;
            padding: 5px;
        }}
        QTextEdit:focus, QLineEdit:focus, QComboBox:focus {{
            border: 1px solid {Colors.ACCENT_CYAN};
        }}
        QProgressBar {{
            background-color: {Colors.BG_TABLES};
            border: 1px solid {Colors.BORDER_SUBTLE};
            border-radius: 5px;
            text-align: center;
            color: {Colors.TEXT_PRIMARY};
        }}
        QProgressBar::chunk {{
            background-color: {Colors.ACCENT_CYAN};
            border-radius: 4px;
        }}
    """

    # Additional UI-specific colors
    PANEL_OVERLAY = "rgba(11, 18, 32, 0.9)" # Semi-transparent overlay

    # Semantic hover tokens (replace previous neon-cyan over-use)
    HOVER_TINT = "rgba(148, 163, 184, 0.08)" # subtle slate — default hover for non-primary widgets
    HOVER_BLUE = "rgba(59, 130, 246, 0.15)" # brand-blue hover for primary CTAs
    
    # ============================================================================

    # Modern Flat Button Style with Cyberpunk Accents
    BUTTON_STYLE = """
        QPushButton {
            background-color: #3B82F6;
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 6px 12px;
            font-weight: 600;
            font-size: 11px;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
            min-width: 80px;
        }
        
        QPushButton:hover {
            background-color: #60A5FA;
        }
        
        QPushButton:pressed {
            background-color: #1E40AF;
        }
        
        QPushButton:disabled {
            background-color: #64748B;
            color: #94A3B8;
        }
    """
    
    # Modern Flat Green Button with Cyberpunk Glow
    GREEN_BUTTON = """
        QPushButton {
            background-color: #22C55E;
            color: #FFFFFF;
            border: none;
            border-radius: 4px;
            padding: 4px 10px;
            font-weight: 600;
            font-size: 11px;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
            min-width: 80px;
            max-height: 28px;
        }
        QPushButton:hover {
            background-color: #4ADE80;
            border: 1px solid rgba(148, 163, 184, 0.28);
        }
        QPushButton:pressed {
            background-color: #16A34A;
            border: 1px solid rgba(0, 255, 255, 0.3);
        }
        QPushButton:disabled {
            background-color: #64748B;
            color: #94A3B8;
        }
    """
    
    # Case Button Style - Smaller buttons for top bar
    CASE_BUTTON = """
        QPushButton {
            background-color: #2563EB;
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 600;
            font-size: 12px;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
            min-width: 100px;
            max-height: 32px;
        }
        QPushButton:hover {
            background-color: #3B82F6;
            border: 1px solid rgba(148, 163, 184, 0.28);
        }
        QPushButton:pressed {
            background-color: #1D4ED8;
        }
        QPushButton:disabled {
            background-color: #64748B;
            color: #94A3B8;
        }
    """
    
    # Modern Flat Search Button
    SEARCH_BUTTON_STYLE = """
        QPushButton {
            background-color: #3B82F6;
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 6px 16px;
            font-weight: 600;
            font-size: 11px;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
        }
        QPushButton:hover {
            background-color: #60A5FA;
            /* Qt doesn't support box-shadow, using border instead */
            border: 1px solid rgba(148, 163, 184, 0.28);
        }
        QPushButton:pressed {
            background-color: #1E40AF;
            /* Qt doesn't support box-shadow, using border instead */
            border: 1px solid rgba(0, 255, 255, 0.3);
        }
        QPushButton:disabled {
            background-color: #64748B;
        }
    """
    
    # Checkbox Style with Cyberpunk Accents
    CHECKBOX_STYLE = """
        QCheckBox {
            color: #E2E8F0;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
            font-size: 13px;
            spacing: 8px;
            padding: 4px;
        }
        
        QCheckBox::indicator {
            width: 18px;
            height: 18px;
            border-radius: 4px;
            border: 1px solid #475569;
            background-color: #1E293B;
        }
        
        QCheckBox::indicator:unchecked:hover {
            border: 1px solid rgba(148, 163, 184, 0.28);
        }
        
        QCheckBox::indicator:checked {
            background-color: #3B82F6;
            border: 1px solid #3B82F6;
            image: url(:/Icons/icons/check.svg);
        }
        
        QCheckBox::indicator:checked:hover {
            background-color: #60A5FA;
            border: 1px solid #00FFFF;
        }
        
        QCheckBox:disabled {
            color: #64748B;
        }
        
        QCheckBox::indicator:disabled {
            background-color: #334155;
            border: 1px solid #475569;
        }
    """

    # Modern Flat Clear Button
    CLEAR_BUTTON_STYLE = """
        QPushButton {
            background-color: #64748B;
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 6px 16px;
            font-weight: 600;
            font-size: 11px;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
        }
        QPushButton:hover {
            background-color: #94A3B8;
            /* Qt doesn't support box-shadow, using border instead */
            border: 1px solid rgba(148, 163, 184, 0.28);
        }
        QPushButton:pressed {
            background-color: #334155;
            /* Qt doesn't support box-shadow, using border instead */
            border: 1px solid rgba(0, 255, 255, 0.3);
        }
        QPushButton:disabled {
            background-color: #475569;
            color: #94A3B8;
        }
    """

    # Modern Flat Red Button with Cyberpunk Glow
    RED_BUTTON = """
        QPushButton {
            background-color: #EF4444;
            color: #FFFFFF;
            border: none;
            border-radius: 8px;
            padding: 12px 24px;
            font-weight: 600;
            font-size: 13px;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
        }
        QPushButton:hover {
            background-color: #F87171;
        }
        QPushButton:pressed {
            background-color: #B91C1C;
        }
        QPushButton:disabled {
            background-color: #64748B;
            color: #94A3B8;
        }
    """
    
    # Modern Flat Orange Button with Cyberpunk Glow
    ORANGE_BUTTON = """
        QPushButton {
            background-color: #FF5F1F;
            color: #FFFFFF;
            border: none;
            border-radius: 8px;
            padding: 10px 20px;
            font-weight: 600;
            font-size: 12px;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
        }
        QPushButton:hover {
            background-color: #FF8C42;
            border: 1px solid rgba(255, 255, 255, 0.4);
        }
        QPushButton:pressed {
            background-color: #E64A19;
            border: 1px solid rgba(255, 255, 255, 0.3);
        }
        QPushButton:disabled {
            background-color: #64748B;
            color: #94A3B8;
        }
    """
    
    # Dialog Style with Cyberpunk Theme
    DIALOG_STYLE = """
        QDialog {
            background-color: #0F172A;
            color: #E2E8F0;
            border: 2px solid #334155;
            border-radius: 10px;
        }
    """
    
    # Group Box Style with Cyberpunk Theme
    GROUP_BOX = """
        QGroupBox {
            background-color: #1E293B;
            color: #E2E8F0;
            border: 1px solid #334155;
            border-radius: 6px;
            margin-top: 10px;
            font-weight: 600;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 2px 5px;
            background-color: #0F172A;
            color: #00FFFF;
            border: 1px solid #334155;
            border-radius: 3px;
        }
    """
    
    # Message Box Style with Enhanced Cyberpunk Theme - Larger Size for Better Visibility
    MESSAGE_BOX_STYLE = """
        QMessageBox {
            background-color: #0F172A;
            color: #E2E8F0;
            border: 3px solid #334155;
            border-radius: 15px;
            min-width: 550px;
            min-height: 300px;
            padding: 30px;
            /* Qt doesn't support box-shadow, using border instead */
            border: 3px solid rgba(0, 255, 255, 0.4);
        }
        QMessageBox QLabel {
            color: #E2E8F0;
            font-size: 18px;
            font-weight: 600;
            font-family: 'Segoe UI', sans-serif;
            margin-bottom: 20px;
            padding: 15px;
            border-left: 4px solid #00FFFF;
            background-color: rgba(0, 255, 255, 0.08);
            line-height: 1.4;
        }
        QMessageBox QPushButton {
            background-color: #3B82F6;
            color: #FFFFFF;
            border: 2px solid rgba(0, 255, 255, 0.3);
            border-radius: 10px;
            padding: 15px 30px;
            font-weight: 600;
            font-size: 16px;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
            min-width: 120px;
            min-height: 45px;
            margin: 15px;
        }
        QMessageBox QPushButton:hover {
            background-color: #60A5FA;
            border: 2px solid rgba(148, 163, 184, 0.28);
            /* Qt doesn't support box-shadow, using border instead */
            border: 3px solid rgba(148, 163, 184, 0.28);
        }
        QMessageBox QPushButton:pressed {
            background-color: #1E40AF;
            border: 2px solid #00FFFF;
        }
        QMessageBox QPushButton:focus {
            outline: none;
            border: 3px solid #00FFFF;
        }
    """

    # ============================================================================
    # UNIFIED TAB WIDGET STYLES
    # ============================================================================
    
    # Unified Tab Style — aligned with the dark-navy table palette.
    # ------------------------------------------------------------------
    # pane bg #0e131c (slight lift over canvas #07090e)
    # pane border #2a3a55 (matches the lifted header band)
    # tab inactive #11151c (matches row body — neutral)
    # tab hover #1a2236 (matches the header band)
    # tab selected #1a2236 + 2px emerald underline (ties to the
    # new translucent-emerald row selection)
    # tab border #2a3a55 (visible separator between tabs)
    # ------------------------------------------------------------------
    UNIFIED_TAB_STYLE = """
        QTabWidget::pane {
            border: 1px solid #2a3a55;
            border-radius: 8px;
            background: #0e131c;
            margin: 0px;
            padding: 0px;
            top: -1px; /* overlap the selected tab's bottom edge cleanly */
        }
        QTabBar::tab {
            background: #1E293B;
            color: #94A3B8;
            border: 1px solid #334155;
            border-bottom: none;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            padding: 6px 14px;
            margin: 0px 3px 0px 3px;
            min-width: 130px;
            min-height: 18px;
            /* No max-width — paired with QTabBar.setExpanding(True) so tabs
               grow to fill spare horizontal room in the bar. */
        }
        QTabBar::tab {
            font-weight: 600;
            font-family: 'Segoe UI', sans-serif;
            font-size: 11px;
            qproperty-wordWrap: false;
            padding-top: 6px;
            padding-bottom: 6px;
        }
        QTabBar::tab:selected {
            background-color: #0B1220;
            color: #00FFFF;
            border-bottom: 2px solid #00FFFF;
            font-weight: bold;
        }
        QTabBar::tab:hover:!selected {
            background-color: #334155;
            color: #FFFFFF;
        }
        QTabBar::tab:disabled {
            color: #64748B;
            background-color: #64748B;
        }
        QTabBar::scroller {
            width: 24px;
        }
        QTabBar QToolButton {
            background-color: #1E293B;
            border: 1px solid #334155;
            border-radius: 3px;
        }
        QTabBar QToolButton:hover {
            background-color: #334155;
            border: 1px solid rgba(148, 163, 184, 0.28);
        }
    """

    # Case Dialog Styles - Enhanced Cyberpunk Theme
    CASE_DIALOG_STYLE = """
        QDialog {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 #020617, stop:0.5 #0B1220, stop:1 #020617);
            border: 2px solid #00FFFF;
            border-radius: 16px;
        }
        
        QFrame {
            background-color: transparent;
            border: none;
        }
        
        QFrame[frameShape="4"] { /* HLine */
            background-color: #00FFFF;
            color: #00FFFF;
            border: 1px solid rgba(0, 255, 255, 0.3);
            margin: 15px 0;
            border-radius: 2px;
        }
        
        QLabel {
            color: #E2E8F0;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
        }
        
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 #2563EB, stop:1 #1E40AF);
            color: #FFFFFF;
            border: none;
            border-radius: 8px;
            padding: 10px 20px;
            font-weight: 700;
            font-size: 13px;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
            min-width: 100px;
        }
        
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 #3B82F6, stop:1 #2563EB);
            border: 2px solid rgba(148, 163, 184, 0.28);
        }
        
        QPushButton:pressed {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 #1D4ED8, stop:1 #1E40AF);
            border: 2px solid #00FF7F;
        }
        
        QPushButton:disabled {
            background: #334155;
            color: #64748B;
            border: 1px solid #475569;
        }
    """
    
    DIALOG_TITLE = """
        QLabel {
            color: #00FFFF;
            font-size: 28px;
            font-weight: 800;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
            padding: 15px 0;
            background: transparent;
            border: none;
            margin: 0;
        }
    """
    
    DIALOG_DESCRIPTION = """
        QLabel {
            color: #94A3B8;
            font-size: 14px;
            font-weight: normal;
            font-family: 'Segoe UI', sans-serif;
            line-height: 1.4;
        }
    """
    
    OPTION_CARD_STYLE = """
        QWidget#option_card {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                stop:0 #0F172A, stop:0.3 #1E293B, stop:0.7 #1E293B, stop:1 #0F172A);
            border: 2px solid #334155;
            border-radius: 15px;
            padding: 0px;
            margin: 8px 0;
            min-height: 80px;
        }
        
        QWidget#option_card:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                stop:0 #1E293B, stop:0.2 #2D3748, stop:0.5 #334155, stop:0.8 #2D3748, stop:1 #1E293B);
            border: 3px solid rgba(148, 163, 184, 0.28);
            margin: 6px 0;
        }
        
        QWidget#option_card:selected {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                stop:0 #1F2937, stop:0.3 #374151, stop:0.7 #374151, stop:1 #1F2937);
            border: 3px solid #00FF7F;
            margin: 6px 0;
        }
        
        /* Enhanced icon styling within cards */
        QLabel[objectName^="icon"] {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                stop:0 rgba(0, 255, 255, 0.05), stop:1 rgba(0, 255, 255, 0.15));
            border: 1px solid rgba(0, 255, 255, 0.3);
            padding: 8px;
            border-radius: 10px;
            margin: 5px;
        }
        
        QLabel[objectName^="icon"]:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                stop:0 rgba(59, 130, 246, 0.15), stop:1 rgba(59, 130, 246, 0.25));
            border: 2px solid rgba(148, 163, 184, 0.28);
        }
        
        /* Enhanced text styling within cards */
        QWidget#option_card QLabel {
            color: #E2E8F0;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
            font-weight: 600;
            background: transparent;
            border: none;
            padding: 2px;
        }
        
        QWidget#option_card QLabel[objectName="title"] {
            color: #00FFFF;
            font-size: 16px;
            font-weight: bold;
        }
        
        QWidget#option_card QLabel[objectName="description"] {
            color: #94A3B8;
            font-size: 13px;
            font-weight: normal;
            line-height: 1.3;
        }
    """
    
    LABEL_STYLE = """
        QLabel {
            color: #E2E8F0;
            font-size: 14px;
            font-weight: 600;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
        }
        
        QLabel:hover {
            color: #FFFFFF;
        }
    """
    

    

    

    # Input Field Style
    INPUT_FIELD = """
        QLineEdit, QTextEdit, QPlainTextEdit {
            background-color: #1E293B;
            color: #F1F5F9;
            border: 1px solid #334155;
            border-radius: 4px;
            padding: 4px 8px;
            selection-background-color: #3B82F6;
            selection-color: #FFFFFF;
            font-size: 11px;
        }
        
        QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover {
            background-color: #263449;
            border-color: #475569;
        }
        
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
            border: 1px solid #3B82F6;
            background-color: #263449;
        }
        
        QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {
            background-color: #475569;
            color: #94A3B8;
            border-color: #334155;
        }
        
        /* Placeholder text styling */
        QLineEdit[placeholderText], QTextEdit[placeholderText] {
            color: #94A3B8;
        }
    """
    
    # Modern Date/Time Edit Style
    DATETIME_STYLE = """
        QDateTimeEdit {
            background-color: #1E293B;
            color: #F1F5F9;
            border: 1px solid #334155;
            border-radius: 4px;
            padding: 4px 8px;
            font-size: 11px;
            font-family: 'Segoe UI', sans-serif;
        }
        
        QDateTimeEdit:hover {
            background-color: #263449;
            border-color: #475569;
        }
        
        QDateTimeEdit:focus {
            border: 1px solid #3B82F6;
            background-color: #263449;
        }
        
        QDateTimeEdit::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 20px;
            border-left-width: 1px;
            border-left-color: #334155;
            border-left-style: solid;
            border-top-right-radius: 4px;
            border-bottom-right-radius: 4px;
            background-color: #0F172A;
        }
        
        QDateTimeEdit::drop-down:hover {
            background-color: #334155;
        }
        
        QDateTimeEdit::down-arrow {
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid #00FFFF;
            width: 0;
            height: 0;
            margin-top: 2px;
            margin-right: 2px;
        }
        
        QDateTimeEdit:disabled {
            background-color: #475569;
            color: #94A3B8;
            border-color: #334155;
        }
    """
    
    # Modern Calendar Widget Style - Dark Theme
    CALENDAR_STYLE = """
        /* Main calendar widget background */
        QCalendarWidget {
            background-color: #0F172A;
            color: #E2E8F0;
            border: 1px solid #334155;
            border-radius: 6px;
        }
        
        /* All child widgets default */
        QCalendarWidget QWidget {
            background-color: #0F172A;
            color: #E2E8F0;
            font-family: 'Segoe UI', sans-serif;
            font-size: 11px;
        }
        
        /* Navigation bar (top section with month/year) */
        QCalendarWidget QWidget#qt_calendar_navigationbar {
            background-color: #1E293B;
            border-bottom: 1px solid #334155;
            min-height: 32px;
        }
        
        /* Month/Year buttons and labels */
        QCalendarWidget QToolButton {
            color: #00FFFF;
            background-color: #1E293B;
            border: none;
            border-radius: 4px;
            margin: 2px;
            padding: 4px 8px;
            font-weight: bold;
            font-size: 12px;
        }
        
        QCalendarWidget QToolButton:hover {
            background-color: #3B82F6;
            color: #FFFFFF;
        }
        
        QCalendarWidget QToolButton:pressed {
            background-color: #1E40AF;
        }
        
        /* Previous/Next month buttons */
        QCalendarWidget QToolButton#qt_calendar_prevmonth,
        QCalendarWidget QToolButton#qt_calendar_nextmonth {
            background-color: transparent;
            color: #10B981;
            font-size: 16px;
            font-weight: bold;
            min-width: 28px;
        }
        
        QCalendarWidget QToolButton#qt_calendar_prevmonth:hover,
        QCalendarWidget QToolButton#qt_calendar_nextmonth:hover {
            background-color: #334155;
            color: #E2E8F0;
        }
        
        /* Month button dropdown */
        QCalendarWidget QToolButton::menu-indicator {
            image: none;
        }
        
        /* Month/Year dropdown menus */
        QCalendarWidget QMenu {
            background-color: #1E293B;
            color: #E2E8F0;
            border: 1px solid #334155;
            border-radius: 4px;
        }
        
        QCalendarWidget QMenu::item {
            padding: 6px 20px;
        }
        
        QCalendarWidget QMenu::item:selected {
            background-color: #3B82F6;
            color: #FFFFFF;
        }
        
        /* Year spinbox */
        QCalendarWidget QSpinBox {
            background-color: #1E293B;
            color: #00FFFF;
            border: 1px solid #334155;
            border-radius: 4px;
            margin: 2px;
            padding: 2px 4px;
            font-weight: bold;
        }
        
        QCalendarWidget QSpinBox::up-button,
        QCalendarWidget QSpinBox::down-button {
            background-color: #334155;
            border: none;
            width: 16px;
        }
        
        QCalendarWidget QSpinBox::up-button:hover,
        QCalendarWidget QSpinBox::down-button:hover {
            background-color: #3B82F6;
        }
        
        /* Calendar table view (days grid) */
        QCalendarWidget QTableView {
            background-color: #0F172A;
            alternate-background-color: #0F172A;
            selection-background-color: #3B82F6;
            selection-color: #FFFFFF;
            outline: none;
            border: none;
        }
        
        /* Day cells */
        QCalendarWidget QAbstractItemView:enabled {
            background-color: #0F172A;
            color: #E2E8F0;
            selection-background-color: #3B82F6;
            selection-color: #FFFFFF;
            font-size: 11px;
        }
        
        QCalendarWidget QAbstractItemView:disabled {
            color: #64748B;
        }
        
        /* Weekday header row (Sun, Mon, Tue, etc.) */
        QCalendarWidget QHeaderView {
            background-color: #1E293B;
        }
        
        QCalendarWidget QHeaderView::section {
            background-color: #1E293B;
            color: #00FFFF;
            font-weight: bold;
            font-size: 10px;
            border: none;
            padding: 4px;
        }
        
        /* Weekend days (Saturday/Sunday) in header */
        QCalendarWidget QHeaderView::section:first,
        QCalendarWidget QHeaderView::section:last {
            color: #EF4444;
        }
    """
    

    
    # Unified Modern Table Style — Dark navy/charcoal canvas with subtle slate rows
    # ------------------------------------------------------------------
    # canvas #07090e (near-black, hint of navy — app/page background)
    # row #11151c (slightly lighter dark slate — main row body)
    # row-alt #141923 (very subtle stripe, ~+1.5% lightness)
    # header #161b24 (slight elevation over rows)
    # border #1f2530 (quiet outline)
    # grid #1a1f29 (dimmer than border — keeps grid readable but soft)
    # text #e6edf3 (clean light)
    # muted #94a3b8 (row-number header, secondary text)
    # accent #58a6ff (sort marker, scrollbar pressed)
    # select #1f6feb (active selection — GH blue family)
    # ------------------------------------------------------------------
    UNIFIED_TABLE_STYLE = """
        /* Horizontal (column) header — distinct lifted slate so the header
           row reads as a separate band from the data rows. Border colour
           is also stepped up so the header outline visibly separates from
           the table border. */
        QHeaderView::section {
            background-color: #1a2236;
            color: #f3f7fb;
            padding: 8px 14px;
            border: none;
            border-right: 1px solid #2a3a55;
            border-bottom: 2px solid #2a3a55;
            font-weight: 600;
            font-size: 12px;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
        }
        QHeaderView::section:first {
            border-top-left-radius: 6px;
        }
        QHeaderView::section:last {
            border-top-right-radius: 6px;
            border-right: none;
        }
        QHeaderView::section:hover {
            background-color: #243054;
            color: #ffffff;
        }
        QHeaderView::section:checked {
            background-color: #1f2a47;
            color: #58a6ff;
            border-bottom: 2px solid #58a6ff; /* marks the active sort column */
        }

        /* Vertical (row-number) header */
        QHeaderView::section:vertical {
            background-color: #07090e;
            color: #94a3b8;
            padding: 8px 10px;
            border: none;
            border-right: 1px solid #1f2530;
            border-bottom: 1px solid #141923;
            font-weight: 500;
            font-size: 12px;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
            min-width: 32px;
        }
        QHeaderView::section:vertical:hover {
            background-color: #11151c;
            color: #e6edf3;
        }

        /* Table core — near-black canvas; rows paint slightly lighter via ::item */
        QTableWidget {
            background-color: #07090e;
            border: 1px solid #1f2530;
            border-radius: 8px;
            gridline-color: #1a1f29;
            outline: 0;
            selection-background-color: rgba(16, 185, 129, 0.32); /* translucent emerald */
            selection-color: #ecfdf5;
            alternate-background-color: #141923; /* subtle stripe */
            color: #e6edf3;
            show-decoration-selected: 1;
            font-size: 13px;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
        }

        /* Table cells — base row tone slightly lighter than the canvas */
        QTableWidget::item {
            background-color: #11151c;
            padding: 8px 14px;
            font-size: 13px;
            font-weight: 400;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
            color: #e6edf3;
            border: none;
        }
        QTableWidget::item:alternate {
            background-color: #141923;
            color: #e6edf3;
        }
        /* Selected row — translucent emerald, weight bump, no border/padding shift */
        QTableWidget::item:selected {
            background-color: rgba(16, 185, 129, 0.28);
            color: #ecfdf5;
            font-weight: 600;
        }
        QTableWidget::item:selected:active {
            background-color: rgba(16, 185, 129, 0.45);
            color: #ffffff;
        }
        /* Hover: very gentle slate tint */
        QTableWidget::item:hover {
            background-color: rgba(148, 163, 184, 0.07);
        }
        QTableWidget::item:selected:hover {
            background-color: rgba(16, 185, 129, 0.55);
            color: #ffffff;
        }

        /* Corner button (top-left, between the two headers) — matches header band */
        QTableCornerButton::section {
            background-color: #1a2236;
            border: none;
            border-right: 1px solid #2a3a55;
            border-bottom: 2px solid #2a3a55;
            border-top-left-radius: 8px;
        }
        QTableCornerButton::section:hover {
            background-color: #243054;
        }

        /* Scrollbars — match canvas */
        QScrollBar:vertical {
            border: none;
            background: #07090e;
            width: 12px;
            margin: 0;
            border-radius: 6px;
        }
        QScrollBar::handle:vertical {
            background: #1f2530;
            min-height: 36px;
            border-radius: 6px;
            margin: 2px;
        }
        QScrollBar::handle:vertical:hover {
            background: #2a3140;
        }
        QScrollBar::handle:vertical:pressed {
            background: #58a6ff;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
            background: none;
        }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
            background: none;
        }

        QScrollBar:horizontal {
            border: none;
            background: #07090e;
            height: 12px;
            margin: 0;
            border-radius: 6px;
        }
        QScrollBar::handle:horizontal {
            background: #1f2530;
            min-width: 36px;
            border-radius: 6px;
            margin: 2px;
        }
        QScrollBar::handle:horizontal:hover {
            background: #2a3140;
        }
        QScrollBar::handle:horizontal:pressed {
            background: #58a6ff;
        }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            width: 0px;
            background: none;
        }
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
            background: none;
        }
    """

    # ========================================================================
    # GEP-style "missing-widget" coverage — Trees / Frames / Sliders / Scroll
    # areas. Same tone as UNIFIED_TABLE_STYLE: slate base, no per-cell border
    # doubling, no layout-shift on selection / hover, system-stack fonts,
    # cyan reserved for :focus or semantic-active states only.
    # ========================================================================

    UNIFIED_TREE_STYLE = """
        QTreeView, QTreeWidget {
            background-color: #0B1220;
            border: 1px solid #334155;
            border-radius: 8px;
            color: #E2E8F0;
            font-size: 13px;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
            outline: 0;
            selection-background-color: #10B981;
            selection-color: #FFFFFF;
            alternate-background-color: #131C2E;
            show-decoration-selected: 1;
        }
        QTreeView::item, QTreeWidget::item {
            padding: 6px 10px;
            border: none;
        }
        QTreeView::item:alternate, QTreeWidget::item:alternate {
            background-color: #131C2E;
        }
        QTreeView::item:hover, QTreeWidget::item:hover {
            background-color: rgba(148, 163, 184, 0.08);
        }
        QTreeView::item:selected, QTreeWidget::item:selected {
            background-color: #059669;
            color: #FFFFFF;
            font-weight: 600;
        }
        QTreeView::item:selected:active, QTreeWidget::item:selected:active {
            background-color: #10B981;
        }
        QTreeView::item:selected:hover, QTreeWidget::item:selected:hover {
            background-color: #047857;
            color: #FFFFFF;
        }
        QTreeView::branch:has-siblings:!adjoins-item {
            border-image: none;
            background: transparent;
        }
        QTreeView::branch:has-siblings:adjoins-item {
            border-image: none;
            background: transparent;
        }
        QTreeView::branch:!has-children:!has-siblings:adjoins-item {
            border-image: none;
            background: transparent;
        }
        /* Expand / collapse markers — slate triangles, no neon */
        QTreeView::branch:has-children:!has-siblings:closed,
        QTreeView::branch:closed:has-children:has-siblings {
            border-image: none;
            image: none;
            background: transparent;
        }
        QTreeView::branch:open:has-children:!has-siblings,
        QTreeView::branch:open:has-children:has-siblings {
            border-image: none;
            image: none;
            background: transparent;
        }
        /* Inherit the same slate scrollbar used in tables */
        QTreeView QScrollBar:vertical, QTreeWidget QScrollBar:vertical {
            border: none;
            background: #0B1220;
            width: 12px;
            margin: 0;
            border-radius: 6px;
        }
        QTreeView QScrollBar::handle:vertical, QTreeWidget QScrollBar::handle:vertical {
            background: #334155;
            min-height: 36px;
            border-radius: 6px;
            margin: 2px;
        }
        QTreeView QScrollBar::handle:vertical:hover, QTreeWidget QScrollBar::handle:vertical:hover {
            background: #475569;
        }
    """

    UNIFIED_FRAME_STYLE = """
        /* Default non-line QFrame inherits the panel slate so unstyled frames
         * don't show OS-default white. */
        QFrame {
            background-color: transparent;
            color: #E2E8F0;
        }
        /* HLine / VLine — frameShape 4 = HLine, 5 = VLine. 1 px slate rule. */
        QFrame[frameShape="4"] {
            color: #334155;
            background-color: #334155;
            max-height: 1px;
            border: none;
        }
        QFrame[frameShape="5"] {
            color: #334155;
            background-color: #334155;
            max-width: 1px;
            border: none;
        }
        /* Box-style frames (StyledPanel, Box) get a subtle slate border */
        QFrame[frameShape="6"], QFrame[frameShape="2"] {
            border: 1px solid #334155;
            border-radius: 6px;
        }
    """

    UNIFIED_SLIDER_STYLE = """
        QSlider::groove:horizontal {
            background: #1E293B;
            height: 4px;
            border-radius: 2px;
        }
        QSlider::sub-page:horizontal {
            background: #3B82F6;
            border-radius: 2px;
        }
        QSlider::add-page:horizontal {
            background: #1E293B;
            border-radius: 2px;
        }
        QSlider::handle:horizontal {
            background: #3B82F6;
            border: 2px solid #1E40AF;
            width: 14px;
            height: 14px;
            margin: -6px 0;
            border-radius: 8px;
        }
        QSlider::handle:horizontal:hover {
            background: #60A5FA;
            border-color: #3B82F6;
        }
        QSlider::handle:horizontal:pressed {
            background: #1E40AF;
        }
        QSlider::groove:vertical {
            background: #1E293B;
            width: 4px;
            border-radius: 2px;
        }
        QSlider::sub-page:vertical {
            background: #1E293B;
            border-radius: 2px;
        }
        QSlider::add-page:vertical {
            background: #3B82F6;
            border-radius: 2px;
        }
        QSlider::handle:vertical {
            background: #3B82F6;
            border: 2px solid #1E40AF;
            width: 14px;
            height: 14px;
            margin: 0 -6px;
            border-radius: 8px;
        }
        QSlider::handle:vertical:hover {
            background: #60A5FA;
            border-color: #3B82F6;
        }
        QSlider::handle:vertical:pressed {
            background: #1E40AF;
        }
        /* Tick marks (visible only when tickPosition is set) */
        QSlider::tick-mark {
            background: #475569;
            width: 1px;
            height: 1px;
        }
    """

    UNIFIED_SCROLLAREA_STYLE = """
        QScrollArea {
            background-color: transparent;
            border: 1px solid #334155;
            border-radius: 8px;
        }
        /* The intermediate viewport / contents widgets must be transparent so
         * the parent panel's colour shows through; without this PyQt5 draws
         * an opaque grey rectangle inside scroll areas. */
        QScrollArea > QWidget > QWidget {
            background-color: transparent;
        }
        /* Match the table scrollbar so a panel containing tables + scroll
         * areas reads as one visual surface. */
        QScrollArea QScrollBar:vertical {
            border: none;
            background: #0B1220;
            width: 12px;
            margin: 0;
            border-radius: 6px;
        }
        QScrollArea QScrollBar::handle:vertical {
            background: #334155;
            min-height: 36px;
            border-radius: 6px;
            margin: 2px;
        }
        QScrollArea QScrollBar::handle:vertical:hover {
            background: #475569;
        }
        QScrollArea QScrollBar:horizontal {
            border: none;
            background: #0B1220;
            height: 12px;
            margin: 0;
            border-radius: 6px;
        }
        QScrollArea QScrollBar::handle:horizontal {
            background: #334155;
            min-width: 36px;
            border-radius: 6px;
            margin: 2px;
        }
        QScrollArea QScrollBar::handle:horizontal:hover {
            background: #475569;
        }
    """

    # Scrollbar Style - Enhanced Cyberpunk Theme
    SCROLLBAR_STYLE = """
        QScrollBar:vertical {
            border: none;
            background: #0B1220;
            width: 12px;
            margin: 0;
            border-radius: 6px;
        }
        
        QScrollBar::handle:vertical {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #334155, stop:1 #1E293B);
            min-height: 30px;
            border-radius: 6px;
            margin: 1px;
            border: 1px solid rgba(0, 255, 255, 0.2);
        }
        
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
            background: none;
        }
        
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
            background: none;
        }
        
        QScrollBar::handle:vertical:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #475569, stop:1 #334155);
            border: 1px solid rgba(148, 163, 184, 0.28);
        }
        
        QScrollBar::handle:vertical:pressed {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1E293B, stop:1 #0F172A);
            border: 1px solid #00FFFF;
        }
        
        QScrollBar:horizontal {
            border: none;
            background: #0B1220;
            height: 12px;
            margin: 0;
            border-radius: 6px;
        }
        
        QScrollBar::handle:horizontal {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #334155, stop:1 #1E293B);
            min-width: 30px;
            border-radius: 6px;
            margin: 1px;
            border: 1px solid rgba(0, 255, 255, 0.2);
        }
        
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            width: 0px;
            background: none;
        }
        
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
            background: none;
        }
        
        QScrollBar::handle:horizontal:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #475569, stop:1 #334155);
            border: 1px solid rgba(148, 163, 184, 0.28);
        }
        
        QScrollBar::handle:horizontal:pressed {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1E293B, stop:1 #0F172A);
            border: 1px solid #00FFFF;
        }
    """

    # Modern Main Window Style
    MAIN_WINDOW = """
        QMainWindow {
            background-color: #0F172A;
            color: #E2E8F0;
            font-family: 'Segoe UI', sans-serif;
            font-size: 13px;
        }
        
        QMainWindow::title {
            background-color: #1E293B;
            color: #E2E8F0;
            font-weight: 600;
        }
    """
        

    # Modern Table Container Frame
    TABLE_WIDGET = """
        QFrame#info_frame {
            background-color: #0B1220;
            border: 1px solid #334155;
            border-radius: 8px;
        }
    """



    # Enhanced Cyberpunk Tab Style with Neon Glow - Redirects to UNIFIED_TAB_STYLE
    CYBERPUNK_TAB_STYLE = UNIFIED_TAB_STYLE

    # Modern Main Tab Widget Style - Redirects to UNIFIED_TAB_STYLE
    MAIN_TAB_WIDGET = UNIFIED_TAB_STYLE

    # Container shell for tab pages, table panels, and the main info_frame.
    # Aligned with the new dark-navy palette so tables, tabs, and their
    # wrapping panels read as one coherent surface.
    # panel bg #0e131c (slight lift over canvas #07090e)
    # panel border #2a3a55 (matches the lifted header band)
    #
    # The QFrame border + radius rule is scoped to StyledPanel frames
    # (frameShape == 6) so nested QFrames with other shapes don't pick
    # up a double border.
    TAB_BACKGROUND = """
        QWidget {
            background-color: #0e131c;
            color: #e6edf3;
        }
        QFrame[frameShape="6"] {
            background-color: #0e131c;
            color: #e6edf3;
            border: 1px solid #2a3a55;
            border-radius: 10px;
        }
    """
    
    # Live Analysis Label Style
    LIVE_ANALYSIS_LABEL = """
        QLabel {
            /* Text Styling */
            color: #00FF00; /* Neon green */
            font-family: 'Arial Black', sans-serif;
            font-size: 14px;
            font-weight: bold;
            
            /* Background */
            background-color: rgba(0, 20, 0, 0.7); /* Dark green with transparency */
            border: 1px solid #00FF00;
            border-radius: 4px;
            padding: 8px 16px;
        }
    """
    
    # Success Button Style
    SUCCESS_BUTTON = """
        QPushButton {
            background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                      stop: 0 #10B981, stop: 1 #059669);
            border: 1px solid #34D399;
            border-radius: 8px;
            color: white;
            font-weight: bold;
            padding: 10px 20px;
            font-size: 13px;
            font-family: 'Segoe UI', sans-serif;
        }
        
        QPushButton:hover {
            background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                      stop: 0 #34D399, stop: 1 #10B981);
            border: 1px solid rgba(148, 163, 184, 0.28);
        }
        
        QPushButton:pressed {
            background: #047857;
            border: 1px solid #00FFFF;
        }
        
        QPushButton:disabled {
            background: #1F2937;
            border-color: #475569;
            color: #94A3B8;
        }
    """
    
    # Loading Progress Style - Note: User requested not to change progress bars
    LOADING_PROGRESS = """
        QProgressBar {
            border: 2px solid #00ffff;
            border-radius: 8px;
            background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                                      stop: 0 #0B1220, stop: 1 #1E293B);
            text-align: center;
            color: #00ffff;
            font-weight: bold;
            font-family: 'Segoe UI', sans-serif;
        }
        
        QProgressBar::chunk {
            background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                                      stop: 0 #00ffff, stop: 1 #00bcd4);
            border-radius: 5px;
            margin: 1px;
        }
        
        QProgressBar::chunk:disabled {
            background: #666666;
        }
    """
    
    # Logo Label Style
    LOGO_LABEL = """
        QLabel {
            color: #00ffff;
            font-size: 24px;
            font-weight: bold;
            font-family: 'Arial Black', sans-serif;
            padding: 10px;
        }
    """
    
    # Title Label Style
    TITLE_LABEL = """
        QLabel {
            color: #00ffff;
            font-size: 24px;
            font-weight: bold;
            padding: 10px;
            margin-bottom: 10px;
            font-family: 'Segoe UI', sans-serif;
        }
    """
    
    
    # ============================================================================
    # UNIFIED LOADING DIALOG STYLES
    # ============================================================================
    
    # Primary loading dialog style
    LOADING_DIALOG = """
        QDialog {
            background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                                      stop: 0 rgba(10, 25, 41, 0.95),
                                      stop: 0.5 rgba(26, 35, 50, 0.95),
                                      stop: 1 rgba(10, 25, 41, 0.95));
            border: 3px solid #00ffff;
            border-radius: 15px;
            color: #00ffff;
        }
    """
    
    # Loading Title Style
    LOADING_TITLE = """
        QLabel {
            color: #00ffff;
            font-size: 24px;
            font-weight: bold;
            padding: 10px;
            font-family: 'Segoe UI', sans-serif;
        }
    """
    
    # Loading Status Style
    LOADING_STATUS = """
        QLabel {
            color: #b0bec5;
            font-size: 14px;
            padding: 5px;
            font-family: 'Segoe UI', sans-serif;
        }
    """
    
    # Loading Log Style
    LOADING_LOG = """
        QTextEdit {
            background-color: #0a1929;
            color: #b0bec5;
            border: 1px solid #00ffff;
            border-radius: 5px;
            padding: 5px;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 12px;
        }
        
        QScrollBar:vertical {
            border: none;
            background: #0a1929;
            width: 10px;
            margin: 0;
        }
        
        QScrollBar::handle:vertical {
            background: #00ffff;
            min-height: 20px;
            border-radius: 5px;
        }
    """

    # Fullscreen overlay backdrop (loading screen)
    OVERLAY_BACKDROP = """
        QWidget {
            background-color: rgba(0, 0, 0, 180);
            border: 2px solid #00ffff;
        }
    """

    # Loading container within overlay
    OVERLAY_CONTAINER = """
        QWidget {
            background-color: rgba(10, 15, 30, 220);
            border: 2px solid #00ffff;
            border-radius: 10px;
        }
    """

    # Overlay title label style
    OVERLAY_TITLE = """
        QLabel {
            color: #00ffff;
            font-size: 24px;
            font-weight: bold;
            font-family: 'Consolas', monospace;
            padding: 10px;
            background-color: rgba(0, 30, 60, 150);
            border: 1px solid #00ffff;
            border-radius: 5px;
        }
    """

    # Overlay status label
    OVERLAY_STATUS = """
        QLabel {
            color: #00ffff;
            font-size: 16px;
            font-family: 'Consolas', monospace;
            margin: 10px;
        }
    """

    # Overlay progress bar
    OVERLAY_PROGRESS = """
        QProgressBar {
            border: 2px solid #00ffff;
            border-radius: 8px;
            background-color: rgba(0, 30, 60, 150);
            height: 25px;
            text-align: center;
            color: #ffffff;
            font-weight: bold;
        }
        QProgressBar::chunk {
            background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                                      stop: 0 #00ffff, stop: 0.5 #0099cc, stop: 1 #00ffff);
            border-radius: 6px;
            margin: 2px;
        }
    """

    # Overlay log display
    OVERLAY_LOG = """
        QTextEdit {
            background-color: rgba(0, 10, 20, 200);
            color: #00ff00;
            font-family: 'Consolas', monospace;
            font-size: 12px;
            border: 1px solid #00ffff;
            border-radius: 5px;
            padding: 10px;
        }
    """

    # Modern Top Frame Style with Enhanced Look
    TOP_FRAME = """
        QFrame#top_frame {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                                      stop:0 #1E293B, stop:1 #0F172A);
            border-bottom: 1px solid #3B82F6;
            padding: 4px;
        }
    """

    # Main hamburger/menu button in top frame
    MAIN_MENU_BUTTON = """
        QPushButton {
            background-color: rgba(15,23,42,0.8);
            border: 1px solid rgba(0,255,255,0.3);
            padding: 0px;
            border-radius: 8px;
            max-width: 42px;
            max-height: 42px;
            icon-size: 42px;
        }
        QPushButton:hover {
            background-color: rgba(30,41,59,0.9);
            border-color: rgba(148, 163, 184, 0.28);
        }
        QPushButton:pressed {
            background-color: rgba(15,23,42,1.0);
            border-color: rgba(0,255,255,0.8);
        }
        QPushButton:checked {
            background-color: rgba(30,41,59,0.9);
            border-color: rgba(0,255,255,0.8);
            border-width: 2px;
        }
    """

    # Main title label in top frame
    MAIN_LABEL = """
        QLabel {
            color: #00FFFF;
            font-size: 16px;
            font-weight: bold;
            text-align: center;
            padding: 4px 10px;
            background-color: rgba(15,23,42,0.7);
            border-radius: 6px;
            border: 1px solid rgba(0,255,255,0.4);
            max-width: 300px;
        }
        QLabel:hover {
            background-color: rgba(15,23,42,0.8);
            border: 1px solid rgba(148, 163, 184, 0.28);
            color: #E2E8F0;
            /* Qt doesn't support text-shadow, using brighter color instead */
            color: #80FFFF;
        }
    """

    # Modern Main Content Frame
    MAIN_FRAME = """
        QFrame#Main_frame {
            background-color: #0F172A;
        }
    """

    # Modern Sidebar Frame with Blue Effect
    SIDEBAR_FRAME = """
        QFrame#side_fram {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                                      stop:0 #0F172A, stop:1 #1E293B);
            border-right: 1px solid #3B82F6;
            padding: 8px;
        }
    """

    # Search bar container in the top frame
    SEARCH_FRAME = """
        QFrame#search_frame {
            background-color: rgba(255,255,255,0.04);
            border: 2px solid rgba(59,130,246,0.3);
            border-radius: 8px;
            padding: 6px 10px;
            margin: 6px 10px;
            /* box-shadow removed - not supported in Qt stylesheets */
        }
    """

    # Search label in search bar
    SEARCH_LABEL = """
        QLabel#search_label {
            color: #D1D5DB; /* gray-300 */
            font-weight: 600;
            padding: 0 10px;
            margin-right: 4px;
        }
    """

    # General label style for form labels
    LABEL_STYLE = """
        QLabel {
            color: #E2E8F0;
            font-weight: 600;
            font-size: 13px;
            padding: 4px 8px;
            margin: 2px 4px;
        }
    """

    # Search input field
    SEARCH_INPUT = """
        QLineEdit#search_input {
            background: transparent;
            border: none;
            color: #F9FAFB;
            padding: 8px 12px;
            margin: 4px;
            min-width: 150px;
            max-width: 180px;
            selection-background-color: #2563EB;
            selection-color: #FFFFFF;
        }
        QLineEdit#search_input:focus {
            outline: none;
            border: none;
        }
    """

    # ============================================================================
    # BUTTON STYLES - ACTIVELY USED
    # ============================================================================
    # Modern Flat Sidebar Buttons with Cyberpunk Accents
    SIDEBAR_BUTTON = """
        QPushButton {
            background-color: #1E293B;
            color: #E2E8F0;
            border: none;
            border-radius: 8px;
            text-align: left;
            padding: 14px 20px;
            font-weight: 600;
            font-size: 13px;
            font-family: 'Segoe UI', sans-serif;
            margin: 2px 8px;
            min-width: 120px;
        }
        QPushButton:hover {
            background-color: #334155;
            color: #FFFFFF;
        }
        QPushButton:pressed {
            background-color: #475569;
        }
        QPushButton:checked {
            background-color: #3B82F6;
            color: #FFFFFF;
            border-left: 4px solid #00FFFF;
            font-weight: bold;
        }
        QPushButton:disabled {
            background-color: #64748B;
            color: #94A3B8;
        }
    """
    


    # Modern Navigation Buttons for Search Results
    NAVIGATION_BUTTON = """
        QPushButton {
            background-color: #64748B;
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 10px 18px;
            font-weight: 600;
            font-size: 13px;
            font-family: 'Segoe UI', sans-serif;
        }
        QPushButton:hover {
            background-color: #94A3B8;
        }
        QPushButton:pressed {
            background-color: #334155;
        }
        QPushButton:disabled {
            background-color: #475569;
            color: #94A3B8;
        }
    """

    # Filter Button Style - Cyberpunk themed filter button
    FILTER_BUTTON = """
        QPushButton {
            background-color: #8B5CF6;
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 600;
            font-size: 12px;
            font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
            min-width: 80px;
        }
        QPushButton:hover {
            background-color: #A78BFA;
            border: 1px solid rgba(148, 163, 184, 0.28);
        }
        QPushButton:pressed {
            background-color: #6D28D9;
        }
        QPushButton:disabled {
            background-color: #475569;
            color: #94A3B8;
        }
    """

    # Export Button Style (Green)
    EXPORT_BUTTON = """
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                                      stop:0 #10B981, stop:1 #059669);
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 10px 20px;
            font-weight: 600;
            font-size: 11px;
            font-family: 'Segoe UI', sans-serif;
            min-width: 120px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                                      stop:0 #34D399, stop:1 #10B981);
            border: 1px solid rgba(148, 163, 184, 0.28);
        }
        QPushButton:pressed {
            background: #047857;
        }
    """

    # Dynamic Linking Button Style (Cyan/Teal - Intelligence & Mapping)
    DYNAMIC_LINK_BUTTON = """
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                      stop:0 #0891B2, stop:1 #0E7490);
            color: #FFFFFF;
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 6px;
            padding: 8px 15px;
            font-weight: 600;
            font-size: 11px;
            font-family: 'Segoe UI', sans-serif;
            min-width: 120px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                      stop:0 #22D3EE, stop:1 #0891B2);
            border: 1px solid rgba(148, 163, 184, 0.28);
        }
        QPushButton:pressed {
            background: #155E75;
        }
    """

    # Correlation Button Style (Purple/Violet - Analysis & Data Science)
    CORRELATION_BUTTON = """
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                                      stop:0 #9333EA, stop:0.5 #7C3AED, stop:1 #9333EA);
            color: #FFFFFF;
            border: 3px solid #6B21A8;
            border-radius: 10px;
            padding: 12px 25px;
            font-weight: bold;
            font-size: 12px;
            font-family: 'Segoe UI', sans-serif;
            min-width: 140px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                                      stop:0 #A855F7, stop:0.5 #9333EA, stop:1 #A855F7);
            border: 3px solid #7C3AED;
            /* Removed transform: scale(1.02) - not supported by Qt */
        }
        QPushButton:pressed {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                                      stop:0 #6B21A8, stop:0.5 #581C87, stop:1 #6B21A8);
            border: 3px solid #581C87;
            padding-top: 14px;
            padding-bottom: 10px;
        }
        QPushButton:disabled {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                                      stop:0 #4B5563, stop:0.5 #374151, stop:1 #4B5563);
            color: #9CA3AF;
            border: 3px solid #374151;
        }
    """

    # Visualization Button Style (Cyan/Indigo)
    VISUALIZATION_BUTTON = """
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                                      stop:0 #06B6D4, stop:1 #3B82F6);
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 10px 20px;
            font-weight: 600;
            font-size: 13px;
            font-family: 'Segoe UI', sans-serif;
            min-width: 120px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                                      stop:0 #22D3EE, stop:1 #60A5FA);
            border: 1px solid #FFFFFF;
        }
        QPushButton:pressed {
            background: #0E7490;
        }
    """

    # Main Search Button Style (Orange/Gold)
    SEARCH_BUTTON_MAIN = """
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                                      stop:0 #F59E0B, stop:1 #EA580C);
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 10px 20px;
            font-weight: 600;
            font-size: 13px;
            font-family: 'Segoe UI', sans-serif;
            min-width: 120px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                                      stop:0 #FBBF24, stop:1 #F97316);
            border: 1px solid #FFFFFF;
        }
        QPushButton:pressed {
            background: #B45309;
        }
    """

    # EYE AI Assistant Button Style (Dark Blue)
    EYE_BUTTON = """
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                                      stop:0 #1E3A8A, stop:1 #1E40AF);
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 10px 20px;
            font-weight: 600;
            font-size: 13px;
            font-family: 'Segoe UI', sans-serif;
            min-width: 120px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                                      stop:0 #2563EB, stop:1 #3B82F6);
            border: 1px solid #FFFFFF;
        }
        QPushButton:pressed {
            background: #1E3A8A;
        }
    """

    # User Behavior Analytics Button Style (Sentinel crimson)
    UBA_BUTTON = """
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                      stop:0 #B4233A, stop:1 #FF3B56);
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 10px 20px;
            font-weight: 600;
            font-size: 13px;
            font-family: 'Segoe UI', sans-serif;
            min-width: 120px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                      stop:0 #D12A45, stop:1 #FF5069);
            border: 1px solid #FFFFFF;
        }
        QPushButton:pressed {
            background: #8E1A2C;
        }
    """

    # Parser Button Style (Primary Blue - Standardized with Dark Gradients)
    PARSER_BUTTON = """
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #2563EB, stop:1 #1E40AF);
            color: #FFFFFF;
            border: none;
            border-right: 10px solid #1E3A8A;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 600;
            font-size: 12px;
            font-family: 'Segoe UI', sans-serif;
            text-align: left;
            padding-left: 15px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #1E40AF, stop:1 #1D4ED8);
            border-left: 3px solid rgba(148, 163, 184, 0.28);
            border-right: 10px solid #0F172A;
        }
        QPushButton:pressed {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #1D4ED8, stop:1 #1E3A8A);
            border-left: 3px solid #00FFFF;
            border-right: 10px solid #0B1220;
        }
        QPushButton:disabled {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #64748B, stop:1 #475569);
            color: #94A3B8;
            border-right: 10px solid #334155;
        }
    """



    # ============================================================================
    # SPECIALIZED BUTTONS - ACTIVELY USED
    # ============================================================================

    # Modern Info Button
    INFO_BUTTON = """
        QPushButton {
            background-color: #3B82F6;
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 10px 18px;
            font-weight: 600;
            font-size: 13px;
            font-family: 'Segoe UI', sans-serif;
        }
        QPushButton:hover {
            background-color: #60A5FA;
            border: 1px solid rgba(148, 163, 184, 0.28); /* Replaced box-shadow with border for Qt compatibility */
        }
        QPushButton:pressed {
            background-color: #1E40AF;
            border: 1px solid rgba(0, 255, 255, 0.3); /* Replaced box-shadow with border for Qt compatibility */
        }
        QPushButton:disabled {
            background-color: #64748B;
            color: #94A3B8;
        }
    """



    # Enhanced Cyberpunk Parse All Button
    PARSE_ALL_BUTTON = """
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                                      stop:0 #8B5CF6, stop:0.5 #6D28D9, stop:1 #3B82F6);
            color: #FFFFFF;
            border: 2px solid #00FFFF;
            border-radius: 8px;
            padding: 14px 28px;
            font-weight: 700;
            font-size: 13px;
            font-family: 'Segoe UI', sans-serif;
            /* Removed box-shadow for Qt compatibility */
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                                      stop:0 #A78BFA, stop:0.5 #8B5CF6, stop:1 #60A5FA);
            border: 3px solid rgba(148, 163, 184, 0.28); /* Enhanced border to replace box-shadow effect */
        }
        QPushButton:pressed {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                                      stop:0 #7C3AED, stop:0.5 #4C1D95, stop:1 #1E40AF);
            border: 2px solid #80FFFF; /* Changed border color to replace box-shadow effect */
        }
        QPushButton:disabled {
            background-color: #64748B;
            color: #94A3B8;
            border: 2px solid #475569;
        }
    """

    # DateTime Edit style for time pickers
    DATE_TIME_EDIT = """
        QDateTimeEdit {
            background-color: #1E293B;
            color: #E2E8F0;
            border: 1px solid #334155;
            border-radius: 4px;
            padding: 6px 8px;
            font-size: 12px;
            font-family: 'Segoe UI', sans-serif;
            selection-background-color: #3B82F6;
        }
        QDateTimeEdit:hover {
            border: 1px solid #475569;
        }
        QDateTimeEdit:focus {
            border: 2px solid #00FFFF;
            background-color: #0F172A;
        }
    """

    # Primary button style for important actions
    PRIMARY_BUTTON = """
        QPushButton {
            background-color: #3B82F6;
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 10px 20px;
            font-weight: 600;
            font-size: 13px;
            font-family: 'Segoe UI', sans-serif;
            min-width: 100px;
        }
        QPushButton:hover {
            background-color: #60A5FA;
            border: 1px solid rgba(148, 163, 184, 0.28);
        }
        QPushButton:pressed {
            background-color: #1E40AF;
        }
        QPushButton:disabled {
            background-color: #64748B;
            color: #94A3B8;
        }
    """

    # Secondary button style for less important actions
    SECONDARY_BUTTON = """
        QPushButton {
            background-color: #64748B;
            color: #FFFFFF;
            border: 1px solid #475569;
            border-radius: 6px;
            padding: 10px 20px;
            font-weight: 600;
            font-size: 13px;
            font-family: 'Segoe UI', sans-serif;
            min-width: 100px;
        }
        QPushButton:hover {
            background-color: #94A3B8;
            border: 1px solid rgba(148, 163, 184, 0.28);
        }
        QPushButton:pressed {
            background-color: #334155;
        }
        QPushButton:disabled {
            background-color: #475569;
            color: #94A3B8;
        }
    """

    # ============================================================================
    # DARK CYBERPUNK LOADING DIALOG STYLES
    # ============================================================================

    # Loading dialog backdrop
    LOADING_DIALOG_BACKDROP = """
        QFrame {
            background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                                      stop: 0 rgba(10, 25, 41, 0.95),
                                      stop: 0.5 rgba(26, 35, 50, 0.95),
                                      stop: 1 rgba(10, 25, 41, 0.95));
            border: 3px solid #00ffff;
            border-radius: 15px;
        }
    """

    # Loading dialog main title
    LOADING_DIALOG_TITLE = """
        QLabel {
            color: #00ffff;
            font-size: 32px;
            font-weight: bold;
            font-family: 'Consolas', 'Courier New', monospace;
            padding: 5px 20px 5px 20px;
            background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                                      stop: 0 rgba(0, 255, 255, 0.15),
                                      stop: 0.5 rgba(0, 255, 255, 0.25),
                                      stop: 1 rgba(0, 255, 255, 0.15));
            border: 2px solid #00ffff;
            border-radius: 10px;
        }
    """

    # Loading dialog icon/logo — 3px gradient cyan border, flush to the icon
    # (no padding). The outer halo glow is applied in code via QGraphicsDropShadowEffect.
    LOADING_DIALOG_ICON = """
        QLabel {
            background-color: rgba(0, 255, 255, 0.05);
            border: 4px solid qlineargradient(
                x1: 0, y1: 0, x2: 1, y2: 1,
                stop: 0 #00ffff,
                stop: 0.3 #00bcff,
                stop: 0.7 #00ffaa,
                stop: 1 #00ffff);
            border-radius: 16px;
            padding: 8px;
        }
    """

    # Loading dialog progress bar
    LOADING_DIALOG_PROGRESS = """
        QProgressBar {
            border: 2px solid #00ffff;
            border-radius: 8px;
            text-align: center;
            font-family: 'Consolas', 'Courier New', monospace;
            font-weight: 900;
            font-size: 14px;
            /* Qt doesn't support text-shadow, using contrasting color and font styling instead */
            color: #ffffff;
            /* Removed text-shadow: 0 0 5px #00ffff, 0 0 10px #00ffff; */
            font-weight: 900;
            background-color: rgba(10, 25, 41, 0.8);
            min-height: 30px;
        }
        QProgressBar::chunk {
            background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                                      stop: 0 #00ffff, stop: 0.5 #0099cc, stop: 1 #00ffff);
            border-radius: 6px;
            margin: 2px;
        }
    """

    # Loading dialog step indicator
    LOADING_DIALOG_STEP = """
        QLabel {
            color: #00ffff;
            font-size: 16px;
            font-family: 'Consolas', 'Courier New', monospace;
            font-weight: bold;
            padding: 15px;
            text-align: center;
            background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                      stop: 0 rgba(0, 255, 255, 0.15),
                                      stop: 1 rgba(0, 255, 255, 0.05));
            border: 2px solid #00ffff;
            border-radius: 8px;
            margin: 5px;
        }
    """

    # Loading dialog log header
    LOADING_DIALOG_LOG_HEADER = """
        QLabel {
            color: #00ff00;
            font-size: 14px;
            font-weight: bold;
            font-family: 'Consolas', 'Courier New', monospace;
            padding: 8px;
            border-bottom: 2px solid #00ff00;
            margin-bottom: 5px;
            background: rgba(0, 255, 0, 0.1);
            border-radius: 6px 6px 0 0;
        }
    """

    # Loading dialog log display
    LOADING_DIALOG_LOG_DISPLAY = """
        QTextEdit {
            background-color: rgba(0, 10, 20, 0.9);
            color: #00ff00;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 11px;
            border: 2px solid #00ffff;
            border-radius: 8px;
            padding: 10px;
            line-height: 1.4;
        }
        QScrollBar:vertical {
            border: none;
            background: rgba(0, 0, 0, 0.3);
            width: 12px;
            margin: 0;
            border-radius: 6px;
        }
        QScrollBar::handle:vertical {
            background: #00ffff;
            min-height: 20px;
            border-radius: 6px;
            margin: 2px;
        }
        QScrollBar::handle:vertical:hover {
            background: #00ff00;
        }
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {
            height: 0px;
            background: none;
            border: none;
        }
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {
            background: rgba(0, 0, 0, 0.2);
            border-radius: 6px;
        }
        QScrollBar:horizontal {
            border: none;
            background: rgba(0, 0, 0, 0.3);
            height: 12px;
            margin: 0;
            border-radius: 6px;
        }
        QScrollBar::handle:horizontal {
            background: #00ffff;
            min-width: 20px;
            border-radius: 6px;
            margin: 2px;
        }
        QScrollBar::handle:horizontal:hover {
            background: #00ff00;
        }
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {
            width: 0px;
            background: none;
            border: none;
        }
        QScrollBar::add-page:horizontal,
        QScrollBar::sub-page:horizontal {
            background: rgba(0, 0, 0, 0.2);
            border-radius: 6px;
        }
    """

    # Loading dialog status label
    LOADING_DIALOG_STATUS = """
        QLabel {
            color: #ffff00;
            font-size: 14px;
            font-family: 'Consolas', 'Courier New', monospace;
            font-weight: bold;
            padding: 12px;
            background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                      stop: 0 rgba(255, 255, 0, 0.2),
                                      stop: 1 rgba(255, 255, 0, 0.1));
            border: 2px solid #ffff00;
            border-radius: 8px;
        }
    """


    # Enhanced Tab Button Style — REDIRECT to UNIFIED_TAB_STYLE (was duplicate block)
    TAB_BUTTON_STYLE = UNIFIED_TAB_STYLE

    # Sub Tab Widget Style - Redirects to UNIFIED_TAB_STYLE
    SUB_TAB_WIDGET = UNIFIED_TAB_STYLE

    # Top Tab Button Style — REDIRECT to UNIFIED_TAB_STYLE (was duplicate block)
    TOP_TAB_BUTTON_STYLE = UNIFIED_TAB_STYLE


    # ------------------------------------------------------------------
    # CROWCLAW_* — shared constants for Artifacts_Collectors/crow_claw GUI.
    # All use the unified slate / brand-blue / emerald palette; cyan is
    # reserved for :checked / :focus only (same rule as UNIFIED_TABLE_STYLE).
    # ------------------------------------------------------------------

    CROWCLAW_SECTION_HEADER = (
        f"color: {Colors.ACCENT_BLUE}; "
        f"font-weight: 700; "
        f"font-size: 11px; "
    )

    CROWCLAW_LABEL_KEY = (
        f"color: {Colors.TEXT_SECONDARY}; "
        f"font-weight: 600; "
    )

    CROWCLAW_LABEL_PATH = (
        f"color: {Colors.SUCCESS}; "
        f"font-weight: 600; "
        f"background-color: transparent; "
    )

    CROWCLAW_STATUS_PILL_OK = (
        f"color: {Colors.SUCCESS}; font-weight: bold; padding: 5px; "
        f"background-color: {Colors.BG_PANELS}; "
        f"border: 1px solid {Colors.SUCCESS}; border-radius: 4px;"
    )

    CROWCLAW_STATUS_PILL_WARN = (
        f"color: {Colors.WARNING}; font-weight: bold; padding: 5px; "
        f"background-color: {Colors.BG_PANELS}; "
        f"border: 1px solid {Colors.WARNING}; border-radius: 4px;"
    )

    CROWCLAW_STATUS_PILL_ERROR = (
        f"color: {Colors.ERROR}; font-weight: bold; padding: 5px; "
        f"background-color: {Colors.BG_PANELS}; "
        f"border: 1px solid {Colors.ERROR}; border-radius: 4px;"
    )

    CROWCLAW_LOG_AREA = (
        f"QTextEdit {{ "
        f"background-color: {Colors.BG_TABLES}; "
        f"color: {Colors.TEXT_PRIMARY}; "
        f"border: 1px solid {Colors.BORDER_SUBTLE}; "
        f"border-radius: 6px; "
        f"padding: 10px; "
        f"font-family: Consolas, 'Cascadia Mono', monospace; "
        f"font-size: 10pt; "
        f"selection-background-color: {Colors.SUCCESS}; "
        f"selection-color: {Colors.BG_PRIMARY}; "
        f"}}"
    )

    CROWCLAW_TOOLBAR_BUTTON = (
        f"QPushButton {{ "
        f"background-color: {Colors.BG_PANELS}; "
        f"color: {Colors.TEXT_PRIMARY}; "
        f"border: 1px solid {Colors.BORDER_SUBTLE}; "
        f"border-radius: 4px; "
        f"padding: 8px 14px; "
        f"font-weight: 600; "
        f"font-size: 11px; "
        f"}} "
        f"QPushButton:hover {{ "
        f"background-color: {Colors.BORDER_SUBTLE}; "
        f"border-color: {Colors.ACCENT_BLUE}; "
        f"}} "
        f"QPushButton:pressed {{ "
        f"background-color: {Colors.ACCENT_BLUE}; "
        f"color: {Colors.BG_PRIMARY}; "
        f"}} "
        f"QPushButton:focus {{ "
        f"border: 1px solid {Colors.ACCENT_CYAN}; "
        f"}}"
    )

    CROWCLAW_PRIMARY_BUTTON = (
        f"QPushButton {{ "
        f"background-color: {Colors.SUCCESS}; "
        f"color: {Colors.BG_PRIMARY}; "
        f"font-size: 14px; font-weight: 800; "
        f"border: none; "
        f"border-radius: 6px; "
        f"padding: 10px 18px; "
        f"}} "
        f"QPushButton:hover {{ "
        f"background-color: #34D399; "
        f"}} "
        f"QPushButton:pressed {{ "
        f"background-color: #059669; "
        f"color: {Colors.TEXT_PRIMARY}; "
        f"}} "
        f"QPushButton:focus {{ "
        f"outline: 2px solid {Colors.ACCENT_CYAN}; "
        f"outline-offset: 2px; "
        f"}}"
    )

    CROWCLAW_STEP_BUTTON_ACTIVE = (
        f"background-color: {Colors.ACCENT_BLUE}; "
        f"color: {Colors.TEXT_PRIMARY}; "
        f"border: 1px solid {Colors.ACCENT_BLUE}; "
        f"border-radius: 4px; padding: 10px; "
        f"text-align: left; font-weight: 700;"
    )

    CROWCLAW_STEP_BUTTON_INACTIVE = (
        f"background-color: {Colors.BG_PANELS}; "
        f"color: {Colors.TEXT_PRIMARY}; "
        f"border: 1px solid {Colors.BORDER_SUBTLE}; "
        f"border-radius: 4px; padding: 10px; "
        f"text-align: left; font-weight: 600;"
    )

    CROWCLAW_PROGRESS_BAR = (
        f"QProgressBar {{ "
        f"background-color: {Colors.BG_PANELS}; "
        f"border: 1px solid {Colors.BORDER_SUBTLE}; "
        f"border-radius: 6px; "
        f"text-align: center; "
        f"color: {Colors.TEXT_PRIMARY}; "
        f"font-weight: 600; "
        f"font-size: 12px; "
        f"padding: 2px; "
        f"}} "
        f"QProgressBar::chunk {{ "
        f"background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
        f"stop:0 {Colors.ACCENT_BLUE}, stop:1 {Colors.SUCCESS}); "
        f"border-radius: 4px; "
        f"}}"
    )

