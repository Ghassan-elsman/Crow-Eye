"""Centralized style definitions for the Crow Eye application."""

from PyQt5.QtCore import Qt

# Unified Color Palette
class Colors:
    # Modern Dark Dashboard Base Colors
    BG_PRIMARY = "#0F172A"      # Main background
    BG_PANELS = "#1E293B"       # Panel background
    BG_TABLES = "#0B1220"       # Dark slate for tables
    BG_CARDS = "#1E293B"        # Card backgrounds
    
    # Text Colors
    TEXT_PRIMARY = "#E2E8F0"    # Primary text
    TEXT_SECONDARY = "#94A3B8"  # Secondary text
    TEXT_MUTED = "#64748B"      # Muted text
    
    # Accent Colors
    ACCENT_BLUE = "#3B82F6"     # Primary accent blue
    ACCENT_CYAN = "#00FFFF"     # Neon cyan for cyberpunk accents
    ACCENT_PURPLE = "#8B5CF6"   # Subtle purple for secondary highlights
    
    # Status Colors
    SUCCESS = "#10B981"         # Success green
    WARNING = "#F59E0B"         # Warning amber
    ERROR = "#EF4444"           # Error red
    
    # Border Colors
    BORDER_SUBTLE = "#334155"   # Subtle borders
    BORDER_ACCENT = "#475569"   # Accent borders
    
    # Cyberpunk Glow Effects
    GLOW_CYAN = "rgba(0, 255, 255, 0.3)"     # Neon cyan glow
    GLOW_BLUE = "rgba(59, 130, 246, 0.3)"    # Blue glow
    GLOW_PURPLE = "rgba(139, 92, 246, 0.3)"  # Purple glow

class CrowEyeStyles:
    """Centralized style definitions for the Crow Eye application."""
    
    @staticmethod
    def apply_table_styles(table_widget):
        """Apply consistent table styles to a QTableWidget.
        
        Args:
            table_widget: The QTableWidget to style
        """
        # Reset any existing styles
        table_widget.setStyleSheet('')
        
        # Apply the complete table style
        table_widget.setStyleSheet(CrowEyeStyles.UNIFIED_TABLE_STYLE)
        
        # Configure header
        header = table_widget.horizontalHeader()
        if header:
            header.setStyleSheet(CrowEyeStyles.UNIFIED_TABLE_STYLE)
            header.setDefaultSectionSize(200)
            header.setMinimumSectionSize(100)
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
        
        # Force a style refresh to ensure styles are applied immediately
        tab_widget.style().unpolish(tab_widget)
        tab_widget.style().polish(tab_widget)
        tab_widget.update()
    
    
    # ============================================================================
    # STYLE CONSTANTS - Using Colors class values for consistency
    # ============================================================================
    
    # Additional UI-specific colors
    ACCENT_GLOW = "rgba(0, 255, 255, 0.3)"  # Neon cyan glow for hover effects
    ACCENT_GLOW_STRONG = "rgba(0, 255, 255, 0.5)"  # Stronger glow for active elements
    PANEL_OVERLAY = "rgba(11, 18, 32, 0.9)"  # Semi-transparent overlay
    
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
            font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
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
            font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            min-width: 80px;
            max-height: 28px;
        }
        QPushButton:hover {
            background-color: #4ADE80;
            border: 1px solid rgba(0, 255, 255, 0.4);
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
            font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            min-width: 100px;
            max-height: 32px;
        }
        QPushButton:hover {
            background-color: #3B82F6;
            border: 1px solid #00FFFF;
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
            font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        QPushButton:hover {
            background-color: #60A5FA;
            /* Qt doesn't support box-shadow, using border instead */
            border: 1px solid rgba(0, 255, 255, 0.4);
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
            font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
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
            border: 1px solid #00FFFF;
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
            font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        QPushButton:hover {
            background-color: #94A3B8;
            /* Qt doesn't support box-shadow, using border instead */
            border: 1px solid rgba(0, 255, 255, 0.4);
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
            font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
            text-transform: uppercase;
            letter-spacing: 0.5px;
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
            font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
            text-transform: uppercase;
            letter-spacing: 0.5px;
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
            font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
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
            letter-spacing: 0.5px;
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
            font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
            min-width: 120px;
            min-height: 45px;
            margin: 15px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        QMessageBox QPushButton:hover {
            background-color: #60A5FA;
            border: 2px solid #00FFFF;
            /* Qt doesn't support box-shadow, using border instead */
            border: 3px solid rgba(0, 255, 255, 0.5);
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
    
    # Modern Flat Tab Style with Cyberpunk Accents - Smaller Size
    UNIFIED_TAB_STYLE = """
        QTabWidget::pane {
            border: 1px solid #334155;
            border-radius: 8px;
            background: #1E293B;
            margin: 0px;
            padding: 0px;
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
            max-width: 220px;   
            min-height: 18px;
        }
        QTabBar::tab {
            font-weight: 600;
            font-family: 'Segoe UI', sans-serif;
            font-size: 11px;
            letter-spacing: 0.5px;
            text-transform: uppercase;
            qproperty-wordWrap: false;
            qproperty-textElideMode: 2;  /* 2 = ElideRight */
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
            border: 1px solid #00FFFF;
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
        
        QFrame[frameShape="4"] {  /* HLine */
            background-color: #00FFFF;
            color: #00FFFF;
            border: 1px solid rgba(0, 255, 255, 0.3);
            margin: 15px 0;
            border-radius: 2px;
        }
        
        QLabel {
            color: #E2E8F0;
            font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
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
            font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            min-width: 100px;
        }
        
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 #3B82F6, stop:1 #2563EB);
            border: 2px solid #00FFFF;
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
            font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
            text-transform: uppercase;
            letter-spacing: 2px;
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
            border: 3px solid #00FFFF;
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
                stop:0 rgba(0, 255, 255, 0.15), stop:1 rgba(0, 255, 255, 0.25));
            border: 2px solid rgba(0, 255, 255, 0.6);
        }
        
        /* Enhanced text styling within cards */
        QWidget#option_card QLabel {
            color: #E2E8F0;
            font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
            font-weight: 600;
            background: transparent;
            border: none;
            padding: 2px;
        }
        
        QWidget#option_card QLabel[objectName="title"] {
            color: #00FFFF;
            font-size: 16px;
            font-weight: bold;
            letter-spacing: 0.5px;
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
            font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
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
    
    # Modern Calendar Widget Style
    CALENDAR_STYLE = """
        QCalendarWidget QWidget {
            background-color: #0F172A;
            color: #E2E8F0;
            font-family: 'Segoe UI', sans-serif;
            font-size: 11px;
        }
        
        QCalendarWidget QToolButton {
            color: #FFFFFF;
            background-color: #1E293B;
            border: none;
            border-radius: 4px;
            margin: 2px;
            padding: 2px;
            font-weight: bold;
        }
        
        QCalendarWidget QToolButton:hover {
            background-color: #3B82F6;
        }
        
        QCalendarWidget QMenu {
            background-color: #1E293B;
            color: #E2E8F0;
            border: 1px solid #334155;
        }
        
        QCalendarWidget QSpinBox {
            background-color: #1E293B;
            color: #E2E8F0;
            border: 1px solid #334155;
            border-radius: 4px;
            margin: 2px;
        }
        
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
    """
    

    
    # Unified Modern Table Style with Dark Slate Background and Cyberpunk Elements - Smaller Headers
    UNIFIED_TABLE_STYLE = """
        QHeaderView::section {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2563EB, stop:1 #1E40AF);
            color: #FFFFFF;
            padding: 4px 8px;
            border: none;
            border-right: 1px solid #334155;
            font-weight: 600;
            font-size: 11px;
            font-family: 'Segoe UI', sans-serif;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        QHeaderView::section:first {
            border-top-left-radius: 6px;
        }
        QHeaderView::section:last {
            border-top-right-radius: 6px;
        }
        QHeaderView::section:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3B82F6, stop:1 #2563EB);
            color: #FFFFFF;
            border-bottom: 2px solid #00FFFF;
        }
        QHeaderView::section:checked {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1E40AF, stop:1 #1E3A8A);
            border-bottom: 2px solid #00FFFF;
        }

        /* Vertical header */
        QHeaderView::section:vertical {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0F172A, stop:1 #020617);
            color: #94A3B8;
            padding: 6px 8px;
            border: none;
            border-bottom: 1px solid #334155;
            font-weight: 600;
            font-size: 11px;
            font-family: 'Segoe UI', sans-serif;
            min-width: 30px;
            text-align: center;
        }
        QHeaderView::section:vertical:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #334155, stop:1 #1E293B);
            color: #E2E8F0;
            border-right: 2px solid rgba(0, 255, 255, 0.5);
        }

        /* Table core */
        QTableWidget {
            background-color: #0B1220;
            border: 1px solid #334155;
            border-radius: 8px;
            gridline-color: #334155;
            outline: 0;
            selection-background-color: #10B981;  /* emerald green */
            selection-color: #FFFFFF;
            alternate-background-color: #162032;   /* softer alt rows */
            color: #E2E8F0;
            show-decoration-selected: 1;
            font-size: 13px;
            font-family: 'Segoe UI', sans-serif;
        }

        /* Table cells - Enhanced for forensic readability */
        QTableWidget::item {
            padding: 2px 6px;
            border-bottom: 1px solid #334155;
            border-right: 1px solid #334155;
            font-size: 11px;
            font-weight: 600;
            font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
            color: #F8FAFC;
            letter-spacing: 0.2px;
        }
        QTableWidget::item:selected {
            background-color: #059669;  /* enhanced emerald green */
            color: #FFFFFF;
            font-weight: 800;
            border: 2px solid #10B981;
            border-radius: 3px;
            padding: 3px;
        }
        QTableWidget::item:hover {
            background-color: rgba(0, 255, 255, 0.15);
            color: #00FFFF;
            font-weight: 700;
        }
        QTableWidget::item:alternate {
            background-color: #1E293B;
            color: #F1F5F9;
        }

        /* Corner button */
        QTableCornerButton::section {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3B82F6, stop:1 #1E40AF);
            border: 1px solid #334155;
            border-top-left-radius: 8px;
        }
        QTableCornerButton::section:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #60A5FA, stop:1 #3B82F6);
            border: 1px solid #00FFFF;
        }
        
        /* Scrollbar styling - Enhanced Cyberpunk Theme */
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
            border: 1px solid #00FFFF;
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
            border: 1px solid #00FFFF;
        }
        
        QScrollBar::handle:horizontal:pressed {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1E293B, stop:1 #0F172A);
            border: 1px solid #00FFFF;
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
            border: 1px solid #00FFFF;
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
            border: 1px solid #00FFFF;
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

    # Modern Tab Background
    TAB_BACKGROUND = """
        QWidget {
            background-color: #0B1220;
            color: #E2E8F0;
        }
    """
    
    # Live Analysis Label Style
    LIVE_ANALYSIS_LABEL = """
        QLabel {
            /* Text Styling */
            color: #00FF00;                     /* Neon green */
            font-family: 'Arial Black', sans-serif;
            font-size: 14px;
            font-weight: bold;
            letter-spacing: 1px;
            text-transform: uppercase;
            
            /* Background */
            background-color: rgba(0, 20, 0, 0.7);  /* Dark green with transparency */
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
            text-transform: uppercase;
            letter-spacing: 0.8px;
            font-size: 13px;
            font-family: 'Segoe UI', sans-serif;
        }
        
        QPushButton:hover {
            background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                      stop: 0 #34D399, stop: 1 #10B981);
            border: 1px solid #00FFFF;
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
    
    # Step Container Style
    STEP_CONTAINER = """
        QFrame {
            background: rgba(0, 0, 0, 0.1);
            border: 1px solid rgba(0, 255, 255, 0.2);
            border-radius: 8px;
            padding: 10px;
            margin: 5px 0;
        }
    """
    
    # Step Number Style
    STEP_NUMBER = """
        QLabel {
            background-color: #1e88e5;
            color: white;
            border-radius: 17px;
            font-weight: bold;
            font-size: 16px;
            min-width: 30px;
            min-height: 30px;
            max-width: 30px;
            max-height: 30px;
            padding: 0;
            margin: 0;
        }
    """
    
    # Step Text Style
    STEP_TEXT = """
        color: #b0bec5;
        font-size: 14px;
        font-family: 'Segoe UI', sans-serif;
        padding-left: 12px;
    """
    
    # Progress Bar Style
    PROGRESS_BAR = """
        QProgressBar {
            border: 1px solid #00bcd4;
            border-radius: 5px;
            background: rgba(0, 0, 0, 0.3);
            text-align: center;
            height: 25px;
        }
        
        QProgressBar::chunk {
            background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                                      stop: 0 #00bcd4, stop: 1 #00838f);
            border-radius: 4px;
        }
    """
    
    # Status Label Style
    STATUS_LABEL = """
        QLabel {
            color: #b0bec5;
            font-size: 13px;
            font-style: italic;
            padding: 10px 0;
            min-height: 20px;
        }
    """
    
    # Active Step Number Style
    STEP_NUMBER_ACTIVE = """
        QLabel {
            background-color: #00bcd4;
            color: white;
            border-radius: 17px;
            font-weight: bold;
            font-size: 14px;
            min-width: 30px;
            min-height: 30px;
            max-width: 30px;
            max-height: 30px;
            padding: 0;
            margin: 0;
            border: 2px solid #00ffff;
        }
    """
    
    # Active Step Text Style
    STEP_TEXT_ACTIVE = """
        color: #00ffff;
        font-size: 14px;
        font-family: 'Segoe UI', sans-serif;
        padding-left: 15px;
        font-weight: bold;
    """
    
    # Active Step Container Style
    STEP_CONTAINER_ACTIVE = """
        QFrame {
            background: rgba(0, 188, 212, 0.1);
            border: 1px solid #00bcd4;
            border-radius: 8px;
            padding: 10px;
            margin: 5px 0;
        }
    """
    
    # Completed step styles (used when a step is finished successfully)
    STEP_NUMBER_COMPLETED = """
        QLabel {
            background-color: #00c853;
            color: white;
            border: 2px solid #00c853;
            border-radius: 17px;
            font-weight: bold;
            font-size: 14px;
        }
    """
    
    STEP_TEXT_COMPLETED = """
        color: #00c853;
        font-size: 14px;
        font-family: 'Segoe UI', sans-serif;
        padding-left: 15px;
        font-weight: bold;
    """
    
    STEP_CONTAINER_COMPLETED = """
        QFrame {
            background: rgba(0, 200, 83, 0.1);
            border: 1px solid rgba(0, 200, 83, 0.3);
            border-radius: 8px;
            margin: 2px;
            padding: 5px;
        }
    """
    
    # Success Status Label Style
    STATUS_LABEL_SUCCESS = """
        QLabel {
            color: #00c853;
            font-size: 13px;
            font-weight: bold;
            padding: 10px 0;
        }
    """
    
    # Error Status Label Style
    STATUS_LABEL_ERROR = """
        QLabel {
            color: #ff5252;
            font-size: 13px;
            font-weight: bold;
            padding: 10px 0;
        }
    """
    
    # Error Step Number Style
    STEP_NUMBER_ERROR = """
        QLabel {
            background-color: #ff5252;
            color: white;
            border-radius: 17px;
            font-weight: bold;
            font-size: 14px;
            min-width: 30px;
            min-height: 30px;
            max-width: 30px;
            max-height: 30px;
            padding: 0;
            margin: 0;
        }
    """
    
    # Error Step Text Style
    STEP_TEXT_ERROR = """
        color: #ff5252;
        font-size: 14px;
        font-family: 'Segoe UI', sans-serif;
        padding-left: 15px;
        font-weight: bold;
    """
    
    # Error Step Container Style
    STEP_CONTAINER_ERROR = """
        QFrame {
            background: rgba(255, 82, 82, 0.1);
            border: 1px solid #ff5252;
            border-radius: 8px;
            padding: 10px;
            margin: 5px 0;
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
            text-transform: uppercase;
            letter-spacing: 2px;
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
            border-color: rgba(0,255,255,0.6);
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
            letter-spacing: 0.8px;
            text-align: center;
            padding: 4px 10px;
            background-color: rgba(15,23,42,0.7);
            border-radius: 6px;
            border: 1px solid rgba(0,255,255,0.4);
            text-transform: uppercase;
            max-width: 300px;
        }
        QLabel:hover {
            background-color: rgba(15,23,42,0.8);
            border: 1px solid rgba(0,255,255,0.6);
            color: #00FFFF;
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
            letter-spacing: 0.5px;
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
            text-transform: uppercase;
            letter-spacing: 0.5px;
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
            font-family: 'BBH Sans Bogle', 'Segoe UI', sans-serif;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            min-width: 80px;
        }
        QPushButton:hover {
            background-color: #A78BFA;
            border: 1px solid rgba(0, 255, 255, 0.4);
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
            text-transform: uppercase;
            letter-spacing: 0.5px;
            min-width: 120px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                                      stop:0 #34D399, stop:1 #10B981);
            border: 1px solid #00FFFF;
        }
        QPushButton:pressed {
            background: #047857;
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
            text-transform: uppercase;
            letter-spacing: 0.5px;
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
            text-transform: uppercase;
            letter-spacing: 0.5px;
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

    # Parser Button Style (Primary Blue - Standardized)
    PARSER_BUTTON = """
        QPushButton {
            background-color: #3B82F6;
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 600;
            font-size: 12px;
            font-family: 'Segoe UI', sans-serif;
            text-align: left;
            padding-left: 15px;
        }
        QPushButton:hover {
            background-color: #2563EB;
            border-left: 3px solid #00FFFF;
        }
        QPushButton:pressed {
            background-color: #1D4ED8;
        }
        QPushButton:checked {
            background-color: #1E40AF;
            border-left: 3px solid #00FFFF;
        }
        QPushButton:disabled {
            background-color: #64748B;
            color: #94A3B8;
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
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        QPushButton:hover {
            background-color: #60A5FA;
            border: 1px solid rgba(0, 255, 255, 0.3); /* Replaced box-shadow with border for Qt compatibility */
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
            text-transform: uppercase;
            letter-spacing: 1px;
            /* Removed box-shadow for Qt compatibility */
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                                      stop:0 #A78BFA, stop:0.5 #8B5CF6, stop:1 #60A5FA);
            border: 3px solid #00FFFF; /* Enhanced border to replace box-shadow effect */
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
            text-transform: uppercase;
            letter-spacing: 0.5px;
            min-width: 100px;
        }
        QPushButton:hover {
            background-color: #60A5FA;
            border: 1px solid rgba(0, 255, 255, 0.4);
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
            text-transform: uppercase;
            letter-spacing: 0.5px;
            min-width: 100px;
        }
        QPushButton:hover {
            background-color: #94A3B8;
            border: 1px solid rgba(0, 255, 255, 0.3);
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
            text-transform: uppercase;
            letter-spacing: 3px;
            padding: 5px 20px 5px 20px;
            background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                                      stop: 0 rgba(0, 255, 255, 0.15),
                                      stop: 0.5 rgba(0, 255, 255, 0.25),
                                      stop: 1 rgba(0, 255, 255, 0.15));
            border: 2px solid #00ffff;
            border-radius: 10px;
        }
    """

    # Loading dialog icon/logo
    LOADING_DIALOG_ICON = """
        QLabel {
            background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                                      stop: 0 rgba(0, 255, 255, 0.2),
                                      stop: 0.5 rgba(0, 255, 255, 0.3),
                                      stop: 1 rgba(0, 255, 255, 0.1));
            border: 3px solid #00ffff;
            border-radius: 15px;
            padding: 15px;
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
            letter-spacing: 1px;
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


    # Enhanced Tab Button Style (alias for TOP_TAB_BUTTON_STYLE)
    TAB_BUTTON_STYLE = """
        QTabBar::tab {
            background-color: #1E293B;
            color: #E2E8F0;
            padding: 14px 28px;
            min-width: 140px;
            border: none;
            border-bottom: 3px solid transparent;
            margin-right: 8px;
            margin-bottom: 0;
            font-weight: 600;
            font-size: 13px;
            font-family: 'Segoe UI', sans-serif;
            text-transform: uppercase;
            letter-spacing: 0.8px;
        }
        
        QTabBar::tab:selected {
            background-color: #0B1220;
            color: #00FFFF;
            border-bottom: 3px solid #00FFFF;
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
    """

    # Sub Tab Widget Style - Redirects to UNIFIED_TAB_STYLE
    SUB_TAB_WIDGET = UNIFIED_TAB_STYLE

    # Modern Top Tab Button Style with Flat Design
    TOP_TAB_BUTTON_STYLE = """
        QTabBar::tab {
            background-color: #1E293B;
            color: #E2E8F0;
            padding: 14px 28px;
            min-width: 140px;
            border: none;
            border-bottom: 3px solid transparent;
            margin-right: 8px;
            margin-bottom: 0;
            font-weight: 600;
            font-size: 13px;
            font-family: 'Segoe UI', sans-serif;
            text-transform: uppercase;
            letter-spacing: 0.8px;
        }
        
        QTabBar::tab:selected {
            background-color: #0B1220;
            color: #00FFFF;
            border-bottom: 3px solid #00FFFF;
            font-weight: bold;
        }
        
        QTabBar::tab:hover:!selected {
            background-color: #334155;
            color: #FFFFFF;
        }
        
        QTabBar::tab:disabled {
            color: #64748B;
            background-color: #64748B;
            min-width: 120px;
            padding: 12px 20px;
        }

        QTabBar::scroller {
            width: 30px;
        }

        QTabBar QToolButton {
            background-color: #1E293B;
            border: 1px solid #334155;
            border-radius: 4px;
        }

        QTabBar QToolButton:hover {
            background-color: #334155;
            border: 1px solid #00FFFF;
        }
    """


