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
    SCORE_CONFIRMED = "#4CAF50"      # Green - High confidence
    SCORE_PROBABLE = "#FF9800"       # Orange - Medium confidence
    SCORE_WEAK = "#F44336"           # Red - Low confidence
    SCORE_INSUFFICIENT = "#9E9E9E"   # Gray - Insufficient evidence
    SCORE_DEFAULT = "#2196F3"        # Blue - Default/Unknown
    
    # Background colors for score highlights
    SCORE_CONFIRMED_BG = "#C8E6C9"   # Light green
    SCORE_PROBABLE_BG = "#FFE0B2"    # Light orange
    SCORE_WEAK_BG = "#FFCDD2"        # Light red
    SCORE_INSUFFICIENT_BG = "#F5F5F5"  # Light gray
    
    # Match status colors
    MATCHED_COLOR = "#4CAF50"        # Green
    MATCHED_BG = "#E8F5E9"           # Very light green
    UNMATCHED_COLOR = "#9E9E9E"      # Gray
    UNMATCHED_BG = "#FAFAFA"         # Very light gray
    
    # ============================================================================
    # COLOR PALETTE - General UI
    # ============================================================================
    
    # Base colors (matching Crow-Eye theme)
    BG_PRIMARY = "#0F172A"           # Main background
    BG_PANELS = "#1E293B"            # Panel background
    BG_CARDS = "#1E293B"             # Card backgrounds
    BG_HOVER = "#263449"             # Hover state
    
    # Text colors
    TEXT_PRIMARY = "#E2E8F0"         # Primary text
    TEXT_SECONDARY = "#94A3B8"       # Secondary text
    TEXT_MUTED = "#64748B"           # Muted text
    TEXT_ACCENT = "#00FFFF"          # Accent text (cyan)
    
    # Border colors
    BORDER_SUBTLE = "#334155"        # Subtle borders
    BORDER_ACCENT = "#475569"        # Accent borders
    BORDER_FOCUS = "#3B82F6"         # Focus state
    BORDER_HOVER = "#00FFFF"         # Hover state (cyan)
    
    # Button colors
    BTN_PRIMARY = "#3B82F6"          # Primary button
    BTN_PRIMARY_HOVER = "#2563EB"    # Primary hover
    BTN_SUCCESS = "#10B981"          # Success button
    BTN_SUCCESS_HOVER = "#059669"    # Success hover
    BTN_DANGER = "#EF4444"           # Danger button
    BTN_DANGER_HOVER = "#DC2626"     # Danger hover
    BTN_SECONDARY = "#64748B"        # Secondary button
    BTN_SECONDARY_HOVER = "#475569"  # Secondary hover
    
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
            background-color: {BG_PRIMARY};
            border: 2px solid {TEXT_ACCENT};
            border-radius: 8px;
        }}
        QProgressDialog QLabel {{
            color: {TEXT_PRIMARY};
            font-size: 10pt;
            padding: 8px;
        }}
        QProgressBar {{
            background-color: {BG_PANELS};
            border: 1px solid {BORDER_SUBTLE};
            border-radius: 4px;
            text-align: center;
            color: {TEXT_PRIMARY};
            font-size: 9pt;
            font-weight: bold;
            min-height: 20px;
        }}
        QProgressBar::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #00FFFF, stop:0.5 #10B981, stop:1 #00FFFF);
            border-radius: 3px;
        }}
        QPushButton {{
            background-color: {BG_PANELS};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_ACCENT};
            border-radius: 4px;
            padding: 6px 16px;
            font-size: 9pt;
            min-width: 70px;
        }}
        QPushButton:hover {{
            background-color: {BG_HOVER};
            border-color: {TEXT_ACCENT};
            color: {TEXT_ACCENT};
        }}
        QPushButton:pressed {{
            background-color: {BG_PRIMARY};
        }}
    """
    
    @staticmethod
    def apply_progress_dialog_style(dialog):
        """Apply Crow Eye styling to a QProgressDialog."""
        dialog.setStyleSheet(CorrelationEngineStyles.PROGRESS_DIALOG_STYLE)
        dialog.setMinimumWidth(350)
        dialog.setMinimumHeight(120)
    
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
            text-transform: uppercase;
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
