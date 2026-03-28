"""
Styling definitions for the Offline Artifact Importer GUI.

This module provides consistent styling for the GUI, including colors, fonts,
spacing, and widget styles. It integrates with Crow-eye styles when available
and provides fallback styling otherwise.

Author: Crow-eye Forensics
License: MIT
"""

# ============================================================================
# Color Palette (Task 14.5)
# ============================================================================

class AppColors:
    """Application color palette"""
    
    # Background colors
    BG_PRIMARY = "#0F172A"  # Dark blue-gray
    BG_SECONDARY = "#1E293B"  # Lighter blue-gray
    BG_PANELS = "#1E293B"  # Panel background
    BG_HOVER = "#334155"  # Hover state
    
    # Text colors
    TEXT_PRIMARY = "#E2E8F0"  # Light gray
    TEXT_SECONDARY = "#94A3B8"  # Medium gray
    TEXT_DISABLED = "#64748B"  # Disabled text
    
    # Accent colors
    ACCENT_BLUE = "#3B82F6"  # Primary accent
    ACCENT_GREEN = "#10B981"  # Success
    ACCENT_RED = "#EF4444"  # Error
    ACCENT_YELLOW = "#F59E0B"  # Warning
    ACCENT_PURPLE = "#8B5CF6"  # Info
    
    # Border colors
    BORDER_DEFAULT = "#334155"
    BORDER_FOCUS = "#3B82F6"
    BORDER_ERROR = "#EF4444"

# ============================================================================
# Font Definitions
# ============================================================================

class AppFonts:
    """Application font definitions"""
    
    # Font families
    FAMILY_DEFAULT = "Segoe UI, Arial, sans-serif"
    FAMILY_MONOSPACE = "Consolas, Courier New, monospace"
    
    # Font sizes
    SIZE_SMALL = "10pt"
    SIZE_NORMAL = "11pt"
    SIZE_LARGE = "12pt"
    SIZE_HEADING = "14pt"
    SIZE_TITLE = "16pt"
    
    # Font weights
    WEIGHT_NORMAL = "normal"
    WEIGHT_BOLD = "bold"

# ============================================================================
# Spacing Definitions
# ============================================================================

class AppSpacing:
    """Application spacing definitions"""
    
    # Padding
    PADDING_SMALL = "4px"
    PADDING_NORMAL = "8px"
    PADDING_LARGE = "12px"
    PADDING_XLARGE = "16px"
    
    # Margins
    MARGIN_SMALL = "4px"
    MARGIN_NORMAL = "8px"
    MARGIN_LARGE = "12px"
    MARGIN_XLARGE = "16px"
    
    # Spacing between elements
    SPACING_SMALL = 4
    SPACING_NORMAL = 8
    SPACING_LARGE = 12
    SPACING_XLARGE = 16

# ============================================================================
# Widget Styles
# ============================================================================

def get_button_style() -> str:
    """Get QPushButton stylesheet"""
    return f"""
        QPushButton {{
            background-color: {AppColors.ACCENT_BLUE};
            color: {AppColors.TEXT_PRIMARY};
            border: none;
            border-radius: 4px;
            padding: {AppSpacing.PADDING_NORMAL};
            font-family: {AppFonts.FAMILY_DEFAULT};
            font-size: {AppFonts.SIZE_NORMAL};
            font-weight: {AppFonts.WEIGHT_BOLD};
        }}
        QPushButton:hover {{
            background-color: #2563EB;
        }}
        QPushButton:pressed {{
            background-color: #1D4ED8;
        }}
        QPushButton:disabled {{
            background-color: {AppColors.BG_HOVER};
            color: {AppColors.TEXT_DISABLED};
        }}
    """

def get_label_style() -> str:
    """Get QLabel stylesheet"""
    return f"""
        QLabel {{
            color: {AppColors.TEXT_PRIMARY};
            font-family: {AppFonts.FAMILY_DEFAULT};
            font-size: {AppFonts.SIZE_NORMAL};
            padding: {AppSpacing.PADDING_SMALL};
        }}
    """

def get_lineedit_style() -> str:
    """Get QLineEdit stylesheet"""
    return f"""
        QLineEdit {{
            background-color: {AppColors.BG_SECONDARY};
            color: {AppColors.TEXT_PRIMARY};
            border: 1px solid {AppColors.BORDER_DEFAULT};
            border-radius: 4px;
            padding: {AppSpacing.PADDING_NORMAL};
            font-family: {AppFonts.FAMILY_DEFAULT};
            font-size: {AppFonts.SIZE_NORMAL};
        }}
        QLineEdit:focus {{
            border: 1px solid {AppColors.BORDER_FOCUS};
        }}
        QLineEdit:disabled {{
            background-color: {AppColors.BG_HOVER};
            color: {AppColors.TEXT_DISABLED};
        }}
    """

def get_combobox_style() -> str:
    """Get QComboBox stylesheet"""
    return f"""
        QComboBox {{
            background-color: {AppColors.BG_SECONDARY};
            color: {AppColors.TEXT_PRIMARY};
            border: 1px solid {AppColors.BORDER_DEFAULT};
            border-radius: 4px;
            padding: {AppSpacing.PADDING_NORMAL};
            font-family: {AppFonts.FAMILY_DEFAULT};
            font-size: {AppFonts.SIZE_NORMAL};
        }}
        QComboBox:hover {{
            border: 1px solid {AppColors.BORDER_FOCUS};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        QComboBox::down-arrow {{
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 5px solid {AppColors.TEXT_PRIMARY};
        }}
        QComboBox QAbstractItemView {{
            background-color: {AppColors.BG_SECONDARY};
            color: {AppColors.TEXT_PRIMARY};
            selection-background-color: {AppColors.ACCENT_BLUE};
            border: 1px solid {AppColors.BORDER_DEFAULT};
        }}
    """

def get_checkbox_style() -> str:
    """Get QCheckBox stylesheet"""
    return f"""
        QCheckBox {{
            color: {AppColors.TEXT_PRIMARY};
            font-family: {AppFonts.FAMILY_DEFAULT};
            font-size: {AppFonts.SIZE_NORMAL};
            spacing: {AppSpacing.SPACING_NORMAL}px;
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border: 1px solid {AppColors.BORDER_DEFAULT};
            border-radius: 3px;
            background-color: {AppColors.BG_SECONDARY};
        }}
        QCheckBox::indicator:checked {{
            background-color: {AppColors.ACCENT_BLUE};
            border: 1px solid {AppColors.ACCENT_BLUE};
        }}
        QCheckBox::indicator:hover {{
            border: 1px solid {AppColors.BORDER_FOCUS};
        }}
    """

def get_progressbar_style() -> str:
    """Get QProgressBar stylesheet"""
    return f"""
        QProgressBar {{
            background-color: {AppColors.BG_SECONDARY};
            border: 1px solid {AppColors.BORDER_DEFAULT};
            border-radius: 4px;
            text-align: center;
            color: {AppColors.TEXT_PRIMARY};
            font-family: {AppFonts.FAMILY_DEFAULT};
            font-size: {AppFonts.SIZE_NORMAL};
            font-weight: {AppFonts.WEIGHT_BOLD};
        }}
        QProgressBar::chunk {{
            background-color: {AppColors.ACCENT_BLUE};
            border-radius: 3px;
        }}
    """

def get_table_style() -> str:
    """Get QTableWidget stylesheet"""
    return f"""
        QTableWidget {{
            background-color: {AppColors.BG_SECONDARY};
            color: {AppColors.TEXT_PRIMARY};
            gridline-color: {AppColors.BORDER_DEFAULT};
            border: 1px solid {AppColors.BORDER_DEFAULT};
            font-family: {AppFonts.FAMILY_DEFAULT};
            font-size: {AppFonts.SIZE_NORMAL};
        }}
        QTableWidget::item {{
            padding: {AppSpacing.PADDING_NORMAL};
        }}
        QTableWidget::item:selected {{
            background-color: {AppColors.ACCENT_BLUE};
            color: {AppColors.TEXT_PRIMARY};
        }}
        QHeaderView::section {{
            background-color: {AppColors.BG_HOVER};
            color: {AppColors.TEXT_PRIMARY};
            padding: {AppSpacing.PADDING_NORMAL};
            border: 1px solid {AppColors.BORDER_DEFAULT};
            font-weight: {AppFonts.WEIGHT_BOLD};
        }}
        QHeaderView::section:hover {{
            background-color: {AppColors.ACCENT_BLUE};
        }}
    """

def get_panel_style() -> str:
    """Get QFrame panel stylesheet"""
    return f"""
        QFrame {{
            background-color: {AppColors.BG_PANELS};
            border: 1px solid {AppColors.BORDER_DEFAULT};
            border-radius: 4px;
            padding: {AppSpacing.PADDING_LARGE};
        }}
    """

# ============================================================================
# Complete Application Stylesheet
# ============================================================================

def get_application_stylesheet() -> str:
    """Get complete application stylesheet"""
    return f"""
        /* Main Window */
        QMainWindow {{
            background-color: {AppColors.BG_PRIMARY};
        }}
        
        /* Buttons */
        {get_button_style()}
        
        /* Labels */
        {get_label_style()}
        
        /* Line Edits */
        {get_lineedit_style()}
        
        /* Combo Boxes */
        {get_combobox_style()}
        
        /* Checkboxes */
        {get_checkbox_style()}
        
        /* Progress Bars */
        {get_progressbar_style()}
        
        /* Tables */
        {get_table_style()}
        
        /* Panels */
        {get_panel_style()}
        
        /* Scroll Bars */
        QScrollBar:vertical {{
            background-color: {AppColors.BG_SECONDARY};
            width: 12px;
            border: none;
        }}
        QScrollBar::handle:vertical {{
            background-color: {AppColors.BG_HOVER};
            border-radius: 6px;
            min-height: 20px;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: {AppColors.ACCENT_BLUE};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        
        /* Tool Tips */
        QToolTip {{
            background-color: {AppColors.BG_SECONDARY};
            color: {AppColors.TEXT_PRIMARY};
            border: 1px solid {AppColors.BORDER_DEFAULT};
            padding: {AppSpacing.PADDING_NORMAL};
            font-family: {AppFonts.FAMILY_DEFAULT};
            font-size: {AppFonts.SIZE_NORMAL};
        }}
    """
