"""
UI Styling Module for Correlation Engine Components

This module provides consistent styling, icons, and color coding for all
correlation engine UI components, ensuring a polished and professional appearance.
"""

from PyQt5.QtWidgets import (
    QWidget, QPushButton, QTableWidget, QHeaderView, QGroupBox,
    QLabel, QLineEdit, QTextEdit, QComboBox, QCheckBox, QSpinBox,
    QDoubleSpinBox, QTabWidget, QDialog, QFrame
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QFont


class CorrelationEngineStyles:
    """
    Centralized styling for Correlation Engine components.
    
    Provides consistent colors, fonts, and styling across all correlation
    engine UI components including scoring displays, wing selection, results
    viewing, and semantic mapping dialogs.
    """
    
    # ============================================================================
    # COLOR PALETTE - Score Interpretations
    # ============================================================================
    
    # Score interpretation colors (semantic color coding)
    SCORE_CONFIRMED = "#4CAF50" # Green - High confidence
    SCORE_PROBABLE = "#FF9800" # Orange - Medium confidence
    SCORE_WEAK = "#F44336" # Red - Low confidence
    SCORE_INSUFFICIENT = "#9E9E9E" # Gray - Insufficient evidence
    SCORE_DEFAULT = "#2196F3" # Blue - Default/Unknown
    
    # Background colors for score highlights
    SCORE_CONFIRMED_BG = "#C8E6C9" # Light green
    SCORE_PROBABLE_BG = "#FFE0B2" # Light orange
    SCORE_WEAK_BG = "#FFCDD2" # Light red
    SCORE_INSUFFICIENT_BG = "#F5F5F5" # Light gray
    
    # Match status colors
    MATCHED_COLOR = "#4CAF50" # Green
    MATCHED_BG = "#E8F5E9" # Very light green
    UNMATCHED_COLOR = "#9E9E9E" # Gray
    UNMATCHED_BG = "#FAFAFA" # Very light gray
    
    # ============================================================================
    # COLOR PALETTE - General UI
    # ============================================================================
    
    # Base colors (matching Crow-Eye theme)
    BG_PRIMARY = "#0F172A" # Main background
    BG_PANELS = "#1E293B" # Panel background
    BG_CARDS = "#1E293B" # Card backgrounds
    BG_HOVER = "#263449" # Hover state
    
    # Text colors
    TEXT_PRIMARY = "#E2E8F0" # Primary text
    TEXT_SECONDARY = "#94A3B8" # Secondary text
    TEXT_MUTED = "#64748B" # Muted text
    TEXT_ACCENT = "#00FFFF" # Accent text (cyan)
    
    # Border colors
    BORDER_SUBTLE = "#334155" # Subtle borders
    BORDER_ACCENT = "#475569" # Accent borders
    BORDER_FOCUS = "#3B82F6" # Focus state
    BORDER_HOVER = "#00FFFF" # Hover state (cyan)
    
    # Button colors
    BTN_PRIMARY = "#3B82F6" # Primary button
    BTN_PRIMARY_HOVER = "#2563EB" # Primary hover
    BTN_SUCCESS = "#10B981" # Success button
    BTN_SUCCESS_HOVER = "#059669" # Success hover
    BTN_DANGER = "#EF4444" # Danger button
    BTN_DANGER_HOVER = "#DC2626" # Danger hover
    BTN_SECONDARY = "#64748B" # Secondary button
    BTN_SECONDARY_HOVER = "#475569" # Secondary hover
    
    # ============================================================================
    # ICON DEFINITIONS
    # ============================================================================
    
    @staticmethod
    def create_icon(icon_type: str, size: int = 16, color: str = None) -> QIcon:
        """
        Create a simple icon programmatically.
        
        Args:
            icon_type: Type of icon ('check', 'cross', 'info', 'warning', 'error', 
                      'add', 'remove', 'edit', 'save', 'load', 'execute', 'settings')
            size: Icon size in pixels
            color: Icon color (hex string)
            
        Returns:
            QIcon object
        """
        if color is None:
            color = CorrelationEngineStyles.TEXT_PRIMARY
        
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        pen_color = QColor(color)
        painter.setPen(pen_color)
        painter.setBrush(pen_color)
        
        # Draw different icon types
        if icon_type == 'check':
            # Checkmark
            painter.setPen(QColor(color))
            painter.drawLine(size//4, size//2, size//2, size*3//4)
            painter.drawLine(size//2, size*3//4, size*3//4, size//4)
        
        elif icon_type == 'cross':
            # X mark
            painter.drawLine(size//4, size//4, size*3//4, size*3//4)
            painter.drawLine(size*3//4, size//4, size//4, size*3//4)
        
        elif icon_type == 'info':
            # Info circle
            painter.drawEllipse(2, 2, size-4, size-4)
            painter.drawText(0, 0, size, size, Qt.AlignCenter, 'i')
        
        elif icon_type == 'warning':
            # Warning triangle
            from PyQt5.QtCore import QPoint
            from PyQt5.QtGui import QPolygon
            points = QPolygon([
                QPoint(size//2, size//4),
                QPoint(size//4, size*3//4),
                QPoint(size*3//4, size*3//4)
            ])
            painter.drawPolygon(points)
            painter.drawText(0, 0, size, size, Qt.AlignCenter, '!')
        
        elif icon_type == 'error':
            # Error circle with X
            painter.drawEllipse(2, 2, size-4, size-4)
            painter.drawLine(size//3, size//3, size*2//3, size*2//3)
            painter.drawLine(size*2//3, size//3, size//3, size*2//3)
        
        elif icon_type == 'add':
            # Plus sign
            painter.drawLine(size//2, size//4, size//2, size*3//4)
            painter.drawLine(size//4, size//2, size*3//4, size//2)
        
        elif icon_type == 'remove':
            # Minus sign
            painter.drawLine(size//4, size//2, size*3//4, size//2)
        
        elif icon_type == 'edit':
            # Pencil
            painter.drawLine(size//4, size*3//4, size*3//4, size//4)
            painter.drawRect(size//4-2, size*3//4-2, 4, 4)
        
        elif icon_type == 'save':
            # Floppy disk
            painter.drawRect(size//4, size//4, size//2, size//2)
            painter.drawLine(size//2, size//4, size//2, size*3//4)
        
        elif icon_type == 'load':
            # Folder
            painter.drawRect(size//4, size//3, size//2, size//2)
            painter.drawLine(size//4, size//3, size//3, size//4)
        
        elif icon_type == 'execute':
            # Play button
            from PyQt5.QtCore import QPoint
            from PyQt5.QtGui import QPolygon
            points = QPolygon([
                QPoint(size//3, size//4),
                QPoint(size//3, size*3//4),
                QPoint(size*2//3, size//2)
            ])
            painter.drawPolygon(points)
        
        elif icon_type == 'settings':
            # Gear
            painter.drawEllipse(size//3, size//3, size//3, size//3)
            for i in range(8):
                angle = i * 45
                painter.save()
                painter.translate(size//2, size//2)
                painter.rotate(angle)
                painter.drawRect(-2, -size//2, 4, size//6)
                painter.restore()
        
        painter.end()
        
        return QIcon(pixmap)
    
    # ============================================================================
    # BUTTON STYLES
    # ============================================================================
    
    PRIMARY_BUTTON_STYLE = f"""
        QPushButton {{
            background-color: {BTN_PRIMARY};
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 600;
            font-size: 11px;
            font-family: 'Segoe UI', sans-serif;
        }}
        QPushButton:hover {{
            background-color: {BTN_PRIMARY_HOVER};
            border: 1px solid {BORDER_HOVER};
        }}
        QPushButton:pressed {{
            background-color: #1D4ED8;
        }}
        QPushButton:disabled {{
            background-color: {BTN_SECONDARY};
            color: {TEXT_MUTED};
        }}
    """
    
    SUCCESS_BUTTON_STYLE = f"""
        QPushButton {{
            background-color: {BTN_SUCCESS};
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 600;
            font-size: 11px;
            font-family: 'Segoe UI', sans-serif;
        }}
        QPushButton:hover {{
            background-color: {BTN_SUCCESS_HOVER};
            border: 1px solid {BORDER_HOVER};
        }}
        QPushButton:pressed {{
            background-color: #047857;
        }}
        QPushButton:disabled {{
            background-color: {BTN_SECONDARY};
            color: {TEXT_MUTED};
        }}
    """
    
    DANGER_BUTTON_STYLE = f"""
        QPushButton {{
            background-color: {BTN_DANGER};
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 600;
            font-size: 11px;
            font-family: 'Segoe UI', sans-serif;
        }}
        QPushButton:hover {{
            background-color: {BTN_DANGER_HOVER};
            border: 1px solid {BORDER_HOVER};
        }}
        QPushButton:pressed {{
            background-color: #B91C1C;
        }}
        QPushButton:disabled {{
            background-color: {BTN_SECONDARY};
            color: {TEXT_MUTED};
        }}
    """
    
    SECONDARY_BUTTON_STYLE = f"""
        QPushButton {{
            background-color: {BTN_SECONDARY};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_SUBTLE};
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 600;
            font-size: 11px;
            font-family: 'Segoe UI', sans-serif;
        }}
        QPushButton:hover {{
            background-color: {BTN_SECONDARY_HOVER};
            border: 1px solid {BORDER_HOVER};
        }}
        QPushButton:pressed {{
            background-color: #334155;
        }}
        QPushButton:disabled {{
            background-color: #475569;
            color: {TEXT_MUTED};
        }}
    """
    
    # ============================================================================
    # TABLE STYLES
    # ============================================================================
    
    # ============================================================================
    # PROGRESS DIALOG STYLE
    # ============================================================================
    
    PROGRESS_DIALOG_STYLE = f"""
        QProgressDialog {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #1E3A5F, stop:0.5 {BG_PRIMARY}, stop:1 #0F1419);
            border: 2px solid {TEXT_ACCENT};
            border-radius: 12px;
            padding: 16px;
        }}
        
        QProgressDialog QLabel {{
            color: #FFFFFF;
            font-size: 11pt;
            font-weight: 600;
            font-family: 'Segoe UI', 'Roboto', sans-serif;
            padding: 12px 16px;
            background: transparent;
        }}
        
        QProgressBar {{
            background-color: {BG_PANELS};
            border: 2px solid {BORDER_ACCENT};
            border-radius: 8px;
            text-align: center;
            color: #FFFFFF;
            font-size: 11pt;
            font-weight: 700;
            font-family: 'Segoe UI', 'Roboto', sans-serif;
            min-height: 28px;
            max-height: 28px;
            margin: 8px 16px;
        }}
        
        QProgressBar::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #00D9FF, stop:0.15 #00FFFF, stop:0.3 #10B981, 
                stop:0.5 #00FFFF, stop:0.7 #10B981, stop:0.85 #00FFFF, stop:1 #00D9FF);
            border-radius: 6px;
            margin: 1px;
        }}
        
        QPushButton {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {BG_HOVER}, stop:1 {BG_PANELS});
            color: #FFFFFF;
            border: 1px solid {BORDER_ACCENT};
            border-radius: 6px;
            padding: 8px 20px;
            font-size: 10pt;
            font-weight: 600;
            font-family: 'Segoe UI', 'Roboto', sans-serif;
            min-width: 80px;
            margin: 8px;
        }}
        
        QPushButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #2A4A6F, stop:1 {BG_HOVER});
            border: 2px solid {TEXT_ACCENT};
            color: {TEXT_ACCENT};
        }}
        
        QPushButton:pressed {{
            background: {BG_PRIMARY};
            border: 2px solid #00B8D4;
            color: #00B8D4;
        }}
        
        QPushButton:focus {{
            outline: none;
            border: 2px solid {TEXT_ACCENT};
        }}
    """
    
    @staticmethod
    def apply_progress_dialog_style(dialog):
        """
        Apply enhanced Crow Eye styling to a QProgressDialog.
        
        Features:
        - Modern gradient background
        - Enhanced progress bar with animated gradient
        - Improved typography and spacing
        - Better button styling with hover effects
        """
        dialog.setStyleSheet(CorrelationEngineStyles.PROGRESS_DIALOG_STYLE)
        dialog.setMinimumWidth(450)
        dialog.setMinimumHeight(150)
        
        # Set window flags for better appearance
        from PyQt5.QtCore import Qt
        dialog.setWindowFlags(
            Qt.Dialog | 
            Qt.CustomizeWindowHint | 
            Qt.WindowTitleHint |
            Qt.WindowCloseButtonHint
        )
    
    TABLE_STYLE = f"""
        QTableWidget {{
            background-color: {BG_PRIMARY};
            border: 1px solid {BORDER_SUBTLE};
            border-radius: 8px;
            gridline-color: {BORDER_SUBTLE};
            selection-background-color: {BTN_SUCCESS};
            selection-color: #FFFFFF;
            alternate-background-color: {BG_PANELS};
            color: {TEXT_PRIMARY};
            font-size: 11px;
            font-family: 'Segoe UI', sans-serif;
        }}
        
        QTableWidget::item {{
            padding: 4px 8px;
            border-bottom: 1px solid {BORDER_SUBTLE};
        }}
        
        QTableWidget::item:selected {{
            background-color: {BTN_SUCCESS};
            color: #FFFFFF;
            font-weight: bold;
        }}
        
        QTableWidget::item:hover {{
            background-color: {BG_HOVER};
            color: {TEXT_ACCENT};
        }}
        
        QHeaderView::section {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 {BTN_PRIMARY}, stop:1 {BTN_PRIMARY_HOVER});
            color: #FFFFFF;
            padding: 6px 8px;
            border: none;
            border-right: 1px solid {BORDER_SUBTLE};
            font-weight: 600;
            font-size: 11px;
            font-family: 'Segoe UI', sans-serif;
        }}
        
        QHeaderView::section:hover {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 #60A5FA, stop:1 {BTN_PRIMARY});
            border-bottom: 2px solid {BORDER_HOVER};
        }}
    """
    
    # ============================================================================
    # GROUP BOX STYLES
    # ============================================================================
    
    GROUP_BOX_STYLE = f"""
        QGroupBox {{
            background-color: {BG_PANELS};
            border: 1px solid {BORDER_SUBTLE};
            border-radius: 8px;
            margin-top: 12px;
            padding-top: 12px;
            font-weight: 600;
            font-size: 11px;
            font-family: 'Segoe UI', sans-serif;
            color: {TEXT_PRIMARY};
        }}
        
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 4px 8px;
            background-color: {BG_PRIMARY};
            color: {TEXT_ACCENT};
            border: 1px solid {BORDER_SUBTLE};
            border-radius: 4px;
            font-weight: bold;
        }}
    """
    
    # ============================================================================
    # INPUT FIELD STYLES
    # ============================================================================
    
    INPUT_STYLE = f"""
        QLineEdit, QTextEdit, QComboBox {{
            background-color: {BG_PANELS};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_SUBTLE};
            border-radius: 4px;
            padding: 6px 8px;
            font-size: 11px;
            font-family: 'Segoe UI', sans-serif;
        }}
        
        QLineEdit:hover, QTextEdit:hover, QComboBox:hover {{
            background-color: {BG_HOVER};
            border-color: {BORDER_ACCENT};
        }}
        
        QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
            border: 2px solid {BORDER_FOCUS};
            background-color: {BG_HOVER};
        }}
        
        QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled {{
            background-color: #475569;
            color: {TEXT_MUTED};
            border-color: {BORDER_SUBTLE};
        }}
    """
    
    # ============================================================================
    # DIALOG STYLES
    # ============================================================================
    
    DIALOG_STYLE = f"""
        QDialog {{
            background-color: {BG_PRIMARY};
            color: {TEXT_PRIMARY};
            border: 2px solid {BORDER_SUBTLE};
            border-radius: 10px;
        }}

        QDialog QLabel {{
            color: {TEXT_PRIMARY};
            font-family: 'Segoe UI', sans-serif;
        }}
    """

    # ============================================================================
    # TAB WIDGET STYLES — mirrored from crow_eye_styles.qss so detail
    # dialogs render identical tab chrome to the main window.
    # ============================================================================

    TAB_WIDGET_STYLE = f"""
        QTabWidget::pane {{
            border: 1px solid {BORDER_SUBTLE};
            border-radius: 8px;
            background: {BG_PANELS};
            margin: 0px;
            padding: 0px;
        }}

        QTabBar::tab {{
            background: {BG_PANELS};
            color: {TEXT_SECONDARY};
            border: 1px solid {BORDER_SUBTLE};
            border-bottom: none;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            padding: 10px 22px;
            margin: 0px 3px 0px 3px;
            min-width: 110px;
            font-weight: 600;
            font-size: 11px;
        }}

        QTabBar::tab:selected {{
            background-color: #0B1220;
            color: {TEXT_ACCENT};
            border-bottom: 2px solid {TEXT_ACCENT};
            font-weight: bold;
        }}

        QTabBar::tab:hover:!selected {{
            background-color: {BORDER_SUBTLE};
            color: #FFFFFF;
        }}
    """

    # ============================================================================
    # TREE WIDGET STYLES
    # ============================================================================

    TREE_WIDGET_STYLE = f"""
        QTreeWidget {{
            background-color: {BG_PRIMARY};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_SUBTLE};
            border-radius: 8px;
            font-family: 'Segoe UI', sans-serif;
            font-size: 11px;
            alternate-background-color: {BG_PANELS};
            outline: 0;
        }}

        QTreeWidget::item {{
            padding: 4px 6px;
            border-bottom: 1px solid {BORDER_SUBTLE};
            color: {TEXT_PRIMARY};
        }}

        QTreeWidget::item:selected {{
            background-color: {BTN_SUCCESS};
            color: #FFFFFF;
            font-weight: bold;
        }}

        QTreeWidget::item:hover {{
            background-color: {BG_HOVER};
            color: {TEXT_ACCENT};
        }}

        QTreeWidget::branch:has-children:!has-siblings:closed,
        QTreeWidget::branch:closed:has-children:has-siblings {{
            border-image: none;
        }}

        QTreeWidget::branch:open:has-children:!has-siblings,
        QTreeWidget::branch:open:has-children:has-siblings {{
            border-image: none;
        }}

        QHeaderView::section {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {BTN_PRIMARY}, stop:1 {BTN_PRIMARY_HOVER});
            color: #FFFFFF;
            padding: 6px 8px;
            border: none;
            border-right: 1px solid {BORDER_SUBTLE};
            font-weight: 600;
            font-size: 11px;
        }}
    """

    # ============================================================================
    # SCROLL AREA STYLES
    # ============================================================================

    SCROLL_AREA_STYLE = f"""
        QScrollArea {{
            background-color: {BG_PRIMARY};
            border: none;
        }}

        QScrollArea > QWidget > QWidget {{
            background-color: {BG_PRIMARY};
            color: {TEXT_PRIMARY};
        }}

        QScrollBar:vertical {{
            background-color: {BG_PANELS};
            width: 12px;
            border: 1px solid {BORDER_SUBTLE};
            border-radius: 6px;
            margin: 0px;
        }}

        QScrollBar::handle:vertical {{
            background-color: {TEXT_ACCENT};
            min-height: 28px;
            border-radius: 5px;
        }}

        QScrollBar::handle:vertical:hover {{
            background-color: #22D3EE;
        }}

        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{
            background: none;
            height: 0px;
        }}

        QScrollBar:horizontal {{
            background-color: {BG_PANELS};
            height: 12px;
            border: 1px solid {BORDER_SUBTLE};
            border-radius: 6px;
        }}

        QScrollBar::handle:horizontal {{
            background-color: {TEXT_ACCENT};
            min-width: 28px;
            border-radius: 5px;
        }}

        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {{
            background: none;
            width: 0px;
        }}
    """

    # ============================================================================
    # TEXT EDIT / READ-ONLY HTML PANE STYLES
    # ============================================================================

    TEXT_EDIT_STYLE = f"""
        QTextEdit, QPlainTextEdit {{
            background-color: #0B1220;
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_SUBTLE};
            border-radius: 5px;
            padding: 8px;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 11px;
            selection-background-color: {BTN_PRIMARY};
            selection-color: #FFFFFF;
        }}

        QTextEdit:focus, QPlainTextEdit:focus {{
            border: 1px solid {BORDER_HOVER};
        }}
    """

    # ============================================================================
    # HEADING / TITLE LABEL STYLES (h2 / h3 used inside detail dialogs)
    # ============================================================================

    HEADING_LABEL_STYLE = f"""
        QLabel {{
            color: {TEXT_PRIMARY};
            font-family: 'Segoe UI', sans-serif;
            background-color: transparent;
        }}
    """

    # ============================================================================
    # CATCH-ALL DETAIL-DIALOG QSS — covers every widget class an evidence
    # detail view could contain (buttons, checkboxes, spinboxes, splitters,
    # list widgets, frames, header views). Applied at dialog scope so
    # cascading reaches deeply nested children Qt's class iteration would
    # otherwise miss (e.g. a QPushButton inside a tab inside a tab).
    # ============================================================================

    DETAIL_DIALOG_QSS = f"""
        /* Push buttons — primary blue default with hover */
        QPushButton {{
            background-color: {BTN_PRIMARY};
            color: #FFFFFF;
            border: none;
            border-radius: 6px;
            padding: 8px 18px;
            font-weight: 600;
            font-size: 11px;
            font-family: 'Segoe UI', sans-serif;
            min-width: 80px;
            min-height: 22px;
        }}
        QPushButton:hover {{ background-color: #60A5FA; }}
        QPushButton:pressed {{ background-color: {BTN_PRIMARY_HOVER}; }}
        QPushButton:disabled {{ background-color: {BTN_SECONDARY}; color: {TEXT_SECONDARY}; }}

        /* Note: Close/Cancel→slate and Export/Save/Copy→emerald variants
           are dispatched programmatically in apply_evidence_detail_styling
           because Qt's QSS attribute selectors only support exact-match
           [text="…"] — CSS3 prefix matching [text^="…"] is not supported
           by Qt's stylesheet engine and silently no-ops. */

        /* Checkboxes + radio buttons */
        QCheckBox, QRadioButton {{
            color: {TEXT_PRIMARY};
            spacing: 8px;
            background-color: transparent;
        }}
        QCheckBox::indicator, QRadioButton::indicator {{
            width: 16px;
            height: 16px;
            border: 2px solid {BORDER_SUBTLE};
            border-radius: 3px;
            background-color: #0B1220;
        }}
        QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
            border-color: {BORDER_HOVER};
        }}
        QCheckBox::indicator:checked {{
            background-color: {TEXT_ACCENT};
            border-color: {TEXT_ACCENT};
        }}
        QRadioButton::indicator {{ border-radius: 8px; }}
        QRadioButton::indicator:checked {{
            background-color: {TEXT_ACCENT};
            border-color: {TEXT_ACCENT};
        }}

        /* Spin boxes */
        QSpinBox, QDoubleSpinBox {{
            background-color: {BG_PANELS};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_SUBTLE};
            border-radius: 4px;
            padding: 4px 6px;
            selection-background-color: {BTN_PRIMARY};
            selection-color: #FFFFFF;
        }}
        QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {BORDER_FOCUS}; }}

        /* Splitters */
        QSplitter::handle {{
            background-color: {BORDER_SUBTLE};
        }}
        QSplitter::handle:hover {{
            background-color: {TEXT_ACCENT};
        }}

        /* Frames that opt-in by object name. (Avoiding a blanket
           QFrame rule because QGroupBox / QLineEdit / many composite
           widgets inherit from QFrame internally and would inherit
           "border: none" through the cascade.) */
        QFrame#noFrame {{
            background-color: transparent;
            border: none;
        }}

        /* List widgets (used in some legacy detail sub-tabs) */
        QListWidget {{
            background-color: {BG_PANELS};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_SUBTLE};
            border-radius: 4px;
            padding: 4px;
            font-family: 'Segoe UI', sans-serif;
            font-size: 11px;
        }}
        QListWidget::item {{
            padding: 6px;
            border-radius: 3px;
        }}
        QListWidget::item:hover {{
            background-color: {BG_HOVER};
            color: {TEXT_ACCENT};
        }}
        QListWidget::item:selected {{
            background-color: {BTN_PRIMARY};
            color: #FFFFFF;
        }}

        /* QHeaderView baseline — TABLE_STYLE / TREE_WIDGET_STYLE already
           cover the in-table variants; this catches standalone ones. */
        QHeaderView::section {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {BTN_PRIMARY}, stop:1 {BTN_PRIMARY_HOVER});
            color: #FFFFFF;
            padding: 6px 8px;
            border: none;
            border-right: 1px solid {BORDER_SUBTLE};
            font-weight: 600;
        }}

        /* Tool tips */
        QToolTip {{
            background-color: {BG_PRIMARY};
            color: {TEXT_PRIMARY};
            border: 1px solid {TEXT_ACCENT};
            padding: 4px 6px;
        }}

        /* Date / time edits */
        QDateTimeEdit, QDateEdit, QTimeEdit {{
            background-color: {BG_PANELS};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_SUBTLE};
            border-radius: 4px;
            padding: 4px 6px;
        }}
        QDateTimeEdit:focus, QDateEdit:focus, QTimeEdit:focus {{
            border-color: {BORDER_FOCUS};
        }}
        QDateTimeEdit::drop-down,
        QDateEdit::drop-down,
        QTimeEdit::drop-down,
        QComboBox::drop-down {{
            border: none;
        }}

        /* Context menus that pop out of tables / trees */
        QMenu {{
            background-color: {BG_PANELS};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_SUBTLE};
            border-radius: 6px;
            padding: 4px;
        }}
        QMenu::item {{
            padding: 6px 18px;
            border-radius: 4px;
        }}
        QMenu::item:selected {{
            background-color: {BTN_PRIMARY};
            color: #FFFFFF;
        }}
        QMenu::separator {{
            height: 1px;
            background-color: {BORDER_SUBTLE};
            margin: 4px 6px;
        }}

        /* Progress bars (used by some embedded heatmap / chart panes) */
        QProgressBar {{
            background-color: {BG_PANELS};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_SUBTLE};
            border-radius: 4px;
            text-align: center;
        }}
        QProgressBar::chunk {{
            background-color: {TEXT_ACCENT};
            border-radius: 3px;
        }}
    """

    # ============================================================================
    # UTILITY METHODS
    # ============================================================================
    
    @staticmethod
    def apply_button_style(button: QPushButton, style_type: str = 'primary'):
        """
        Apply consistent button styling.
        
        Args:
            button: QPushButton to style
            style_type: 'primary', 'success', 'danger', or 'secondary'
        """
        styles = {
            'primary': CorrelationEngineStyles.PRIMARY_BUTTON_STYLE,
            'success': CorrelationEngineStyles.SUCCESS_BUTTON_STYLE,
            'danger': CorrelationEngineStyles.DANGER_BUTTON_STYLE,
            'secondary': CorrelationEngineStyles.SECONDARY_BUTTON_STYLE
        }
        
        button.setStyleSheet(styles.get(style_type, styles['primary']))
        button.setCursor(Qt.PointingHandCursor)
    
    @staticmethod
    def apply_table_style(table: QTableWidget):
        """
        Apply consistent table styling with improved layout.
        
        Args:
            table: QTableWidget to style
        """
        table.setStyleSheet(CorrelationEngineStyles.TABLE_STYLE)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        
        # Configure header
        header = table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setStretchLastSection(True)
        header.setSectionsClickable(True)
        header.setHighlightSections(True)
    
    @staticmethod
    def apply_group_box_style(group_box: QGroupBox):
        """
        Apply consistent group box styling.
        
        Args:
            group_box: QGroupBox to style
        """
        group_box.setStyleSheet(CorrelationEngineStyles.GROUP_BOX_STYLE)
    
    @staticmethod
    def apply_input_style(widget):
        """
        Apply consistent input field styling.
        
        Args:
            widget: QLineEdit, QTextEdit, or QComboBox to style
        """
        widget.setStyleSheet(CorrelationEngineStyles.INPUT_STYLE)
    
    @staticmethod
    def apply_dialog_style(dialog: QDialog):
        """
        Apply consistent dialog styling.

        Args:
            dialog: QDialog to style
        """
        dialog.setStyleSheet(CorrelationEngineStyles.DIALOG_STYLE)

    # ------------------------------------------------------------------ #
    # Detail-dialog widget styles (added in the GUI-polish pass).
    # ------------------------------------------------------------------ #

    @staticmethod
    def apply_tab_style(tab_widget):
        """Apply the Crow-Eye tab chrome to a ``QTabWidget``."""
        tab_widget.setStyleSheet(CorrelationEngineStyles.TAB_WIDGET_STYLE)

    @staticmethod
    def apply_tree_style(tree_widget):
        """Apply the Crow-Eye tree chrome (alt-rows, hover, headers)."""
        tree_widget.setStyleSheet(CorrelationEngineStyles.TREE_WIDGET_STYLE)
        try:
            tree_widget.setAlternatingRowColors(True)
        except Exception:
            pass

    @staticmethod
    def apply_scroll_style(scroll_area):
        """Apply the slate background + cyan scrollbars to a ``QScrollArea``."""
        scroll_area.setStyleSheet(CorrelationEngineStyles.SCROLL_AREA_STYLE)

    @staticmethod
    def apply_text_edit_style(text_edit):
        """Apply the read-only HTML / monospace text-edit chrome."""
        text_edit.setStyleSheet(CorrelationEngineStyles.TEXT_EDIT_STYLE)

    @staticmethod
    def apply_evidence_detail_styling(dialog: QDialog) -> None:
        """One-shot: style every widget inside a Correlation Engine detail dialog.

        Walks ``dialog.findChildren(...)`` and applies the right
        per-widget stylesheet (Qt's cascade isn't reliable across
        every widget type, especially nested QTabWidgets). Idempotent —
        safe to call from a constructor and from re-render paths.

        Used by ``MatchDetailDialog``, ``AnchorDetailDialog``,
        ``IdentityDetailDialog``, ``TimeWindowDetailDialog``, etc., so
        every popup the analyst opens carries the unified slate / cyan /
        emerald look instead of falling back to default Qt chrome.
        """
        # Lazy imports keep ui_styling.py importable without PyQt at
        # module load (e.g. on the headless test harness).
        from PyQt5.QtWidgets import (
            QTabWidget, QTreeWidget, QTableWidget, QGroupBox,
            QScrollArea, QTextEdit, QPlainTextEdit, QLineEdit, QComboBox,
            QPushButton,
        )

        # Dialog frame + label baseline + catch-all widget chrome
        # (push buttons, checkboxes, spinboxes, splitters, list widgets,
        # tool tips, standalone header views, frames). Applied at the
        # dialog level so every nested child cascades into the theme.
        dialog.setStyleSheet(
            CorrelationEngineStyles.DIALOG_STYLE
            + CorrelationEngineStyles.HEADING_LABEL_STYLE
            + CorrelationEngineStyles.DETAIL_DIALOG_QSS
        )

        # Tab containers — common in IdentityDetailDialog +
        # TimeWindowDetailDialog content sections.
        for tw in dialog.findChildren(QTabWidget):
            CorrelationEngineStyles.apply_tab_style(tw)

        # Tables (matched feathers, evidence list, etc.).
        # Apply only the *visual* chrome — stylesheet, alt-rows, header
        # stretch. Selection mode / edit triggers / vertical-header
        # visibility are owned by each table's creator so an analyst
        # who set up multi-row select on a specific table keeps it.
        for tbl in dialog.findChildren(QTableWidget):
            tbl.setStyleSheet(CorrelationEngineStyles.TABLE_STYLE)
            tbl.setAlternatingRowColors(True)
            header = tbl.horizontalHeader()
            if header is not None:
                header.setStretchLastSection(True)
                header.setHighlightSections(True)

        # Trees (raw record viewer)
        for tree in dialog.findChildren(QTreeWidget):
            CorrelationEngineStyles.apply_tree_style(tree)

        # Group boxes (section wrappers)
        for gb in dialog.findChildren(QGroupBox):
            CorrelationEngineStyles.apply_group_box_style(gb)

        # Scroll areas + scrollbars
        for sa in dialog.findChildren(QScrollArea):
            CorrelationEngineStyles.apply_scroll_style(sa)

        # Read-only HTML / monospace panes (metadata blocks)
        for te in dialog.findChildren(QTextEdit):
            CorrelationEngineStyles.apply_text_edit_style(te)
        for pe in dialog.findChildren(QPlainTextEdit):
            CorrelationEngineStyles.apply_text_edit_style(pe)

        # Inline inputs (rare in detail dialogs but possible — e.g.
        # an in-line filter on a tab).
        for inp in dialog.findChildren(QLineEdit):
            CorrelationEngineStyles.apply_input_style(inp)
        for combo in dialog.findChildren(QComboBox):
            CorrelationEngineStyles.apply_input_style(combo)

        # Push buttons — dispatch by text. Qt QSS attribute selectors
        # don't support CSS3 prefix matching ([text^="…"]) and exact
        # matching breaks the moment a label gains an ellipsis or
        # mnemonic, so we route it through Python and call
        # apply_button_style with the correct variant. The dialog-level
        # QPushButton {…} rule covers everything else (primary blue).
        for btn in dialog.findChildren(QPushButton):
            label = (btn.text() or "").lstrip("&").strip().lower()
            if not label:
                continue
            if label.startswith(("close", "cancel", "dismiss")):
                CorrelationEngineStyles.apply_button_style(btn, "secondary")
            elif label.startswith(("export", "save", "copy")):
                CorrelationEngineStyles.apply_button_style(btn, "success")

    @staticmethod
    def get_score_color(interpretation: str) -> str:
        """
        Get color for score interpretation.
        
        Args:
            interpretation: Score interpretation string
            
        Returns:
            Hex color string
        """
        interpretation_lower = interpretation.lower()
        
        if 'confirmed' in interpretation_lower:
            return CorrelationEngineStyles.SCORE_CONFIRMED
        elif 'probable' in interpretation_lower or 'likely' in interpretation_lower:
            return CorrelationEngineStyles.SCORE_PROBABLE
        elif 'weak' in interpretation_lower:
            return CorrelationEngineStyles.SCORE_WEAK
        elif 'insufficient' in interpretation_lower:
            return CorrelationEngineStyles.SCORE_INSUFFICIENT
        else:
            return CorrelationEngineStyles.SCORE_DEFAULT
    
    @staticmethod
    def get_score_background_color(interpretation: str) -> str:
        """
        Get background color for score interpretation.
        
        Args:
            interpretation: Score interpretation string
            
        Returns:
            Hex color string
        """
        interpretation_lower = interpretation.lower()
        
        if 'confirmed' in interpretation_lower:
            return CorrelationEngineStyles.SCORE_CONFIRMED_BG
        elif 'probable' in interpretation_lower or 'likely' in interpretation_lower:
            return CorrelationEngineStyles.SCORE_PROBABLE_BG
        elif 'weak' in interpretation_lower:
            return CorrelationEngineStyles.SCORE_WEAK_BG
        elif 'insufficient' in interpretation_lower:
            return CorrelationEngineStyles.SCORE_INSUFFICIENT_BG
        else:
            return CorrelationEngineStyles.SCORE_INSUFFICIENT_BG
    
    @staticmethod
    def create_styled_label(text: str, style_type: str = 'primary') -> QLabel:
        """
        Create a styled label.
        
        Args:
            text: Label text
            style_type: 'primary', 'secondary', 'accent', or 'muted'
            
        Returns:
            Styled QLabel
        """
        label = QLabel(text)
        
        colors = {
            'primary': CorrelationEngineStyles.TEXT_PRIMARY,
            'secondary': CorrelationEngineStyles.TEXT_SECONDARY,
            'accent': CorrelationEngineStyles.TEXT_ACCENT,
            'muted': CorrelationEngineStyles.TEXT_MUTED
        }
        
        color = colors.get(style_type, colors['primary'])
        label.setStyleSheet(f"color: {color}; font-family: 'Segoe UI', sans-serif;")
        
        return label
    
    @staticmethod
    def add_button_icon(button: QPushButton, icon_type: str, color: str = None):
        """
        Add an icon to a button.
        
        Args:
            button: QPushButton to add icon to
            icon_type: Type of icon
            color: Icon color (optional)
        """
        icon = CorrelationEngineStyles.create_icon(icon_type, 16, color)
        button.setIcon(icon)
        button.setIconSize(QSize(16, 16))
