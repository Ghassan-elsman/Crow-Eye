from PyQt5 import QtWidgets, QtCore, QtGui
from typing import Optional, Dict, Any, List, Union, Callable
from pathlib import Path
import logging

class ComponentFactory:
    """
    Factory for creating consistent UI components with standardized styling.
    """
    
    def __init__(self, styles: Optional[Dict[str, str]] = None):
        """
        Initialize the component factory with optional styles.
        
        Args:
            styles: Dictionary of style names to CSS styles
        """
        self.styles = styles or {}
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def create_button(self, 
                     text: str = "", 
                     style_name: str = "default",
                     tooltip: str = "",
                     icon: Optional[Union[str, QtGui.QIcon]] = None,
                     on_click: Optional[Callable] = None) -> QtWidgets.QPushButton:
        """
        Create a styled push button.
        
        Args:
            text: Button text
            style_name: Name of the style to apply
            tooltip: Tooltip text
            icon: Optional icon (path or QIcon)
            on_click: Click event handler
            
        Returns:
            Configured QPushButton
        """
        button = QtWidgets.QPushButton(text)
        
        # Apply style if available
        if style_name in self.styles:
            button.setStyleSheet(self.styles[style_name])
            
        # Set tooltip if provided
        if tooltip:
            button.setToolTip(tooltip)
            
        # Set icon if provided
        if icon:
            if isinstance(icon, str):
                icon = QtGui.QIcon(icon)
            button.setIcon(icon)
            
        # Connect click handler if provided
        if on_click:
            button.clicked.connect(on_click)
            
        return button
    
    def create_table(self, 
                    headers: List[str],
                    style_name: str = "default",
                    selection_behavior: str = "selectRows",
                    selection_mode: str = "extended",
                    sort_enabled: bool = True) -> QtWidgets.QTableWidget:
        """
        Create a configured table widget with consistent styling.
        
        Args:
            headers: List of column headers
            style_name: Name of the style to apply (default style will be used if not found)
            selection_behavior: Selection behavior ('selectRows' or 'selectItems')
            selection_mode: Selection mode ('single', 'extended', etc.)
            sort_enabled: Whether to enable sorting
            
        Returns:
            Configured QTableWidget with applied styles
        """
        table = QtWidgets.QTableWidget()
        
        # Configure table properties
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(sort_enabled)
        
        # Set selection behavior
        selection_behavior_enum = getattr(
            QtCore.Qt.SelectionBehavior, 
            f"Select{selection_behavior.capitalize()}",
            QtCore.Qt.SelectionBehavior.SelectRows
        )
        table.setSelectionBehavior(selection_behavior_enum)
        
        # Set selection mode
        selection_mode_enum = getattr(
            QtCore.QItemSelectionModel, 
            selection_mode.upper(),
            QtCore.QItemSelectionModel.ExtendedSelection
        )
        table.setSelectionMode(selection_mode_enum)
        
        # Apply style from styles if available, otherwise use default
        style = self.styles.get(style_name, "")
        if style:
            table.setStyleSheet(style)
        
        # Configure header with enhanced settings
        header = table.horizontalHeader()
        if header:
            # Header properties
            header.setStretchLastSection(True)
            header.setDefaultAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            header.setHighlightSections(True)
            header.setSectionsClickable(True)
            header.setSectionsMovable(True)
            header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
            header.setSortIndicatorShown(True)
            
            # Force header style update
            header.setAttribute(QtCore.Qt.WA_StyledBackground, True)
            if style:
                header.setStyleSheet(style)
            
            # Force style refresh
            header.style().unpolish(header)
            header.style().polish(header)
            header.update()
        
        # Configure viewport
        viewport = table.viewport()
        if viewport:
            viewport.setAttribute(QtCore.Qt.WA_StyledBackground, True)
            if style:
                viewport.setStyleSheet('')
            viewport.update()
        
        # Force table style update
        table.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        table.style().unpolish(table)
        table.style().polish(table)
        table.update()
        
        return table
    
    def create_label(self, 
                    text: str = "",
                    style_name: str = "default",
                    alignment: str = "left",
                    word_wrap: bool = False) -> QtWidgets.QLabel:
        """
        Create a styled label.
        
        Args:
            text: Label text
            style_name: Name of the style to apply
            alignment: Text alignment ('left', 'center', 'right')
            word_wrap: Whether to enable word wrap
            
        Returns:
            Configured QLabel
        """
        label = QtWidgets.QLabel(text)
        
        # Set alignment
        align_flag = getattr(
            QtCore.Qt.AlignmentFlag, 
            f"Align{alignment.capitalize()}",
            QtCore.Qt.AlignmentFlag.AlignLeft
        )
        label.setAlignment(align_flag | QtCore.Qt.AlignmentFlag.AlignVCenter)
        
        # Set word wrap
        label.setWordWrap(word_wrap)
        
        # Apply style if available
        if style_name in self.styles:
            label.setStyleSheet(self.styles[style_name])
            
        return label
    
    def create_progress_dialog(self, 
                             title: str = "Processing",
                             label_text: str = "Please wait...",
                             minimum: int = 0,
                             maximum: int = 0,
                             parent: Optional[QtWidgets.QWidget] = None) -> QtWidgets.QProgressDialog:
        """
        Create a progress dialog.
        
        Args:
            title: Dialog title
            label_text: Text to display
            minimum: Minimum progress value
            maximum: Maximum progress value
            parent: Parent widget
            
        Returns:
            Configured QProgressDialog
        """
        dialog = QtWidgets.QProgressDialog(label_text, "Cancel", minimum, maximum, parent)
        dialog.setWindowTitle(title)
        dialog.setWindowModality(QtCore.Qt.WindowModal)
        dialog.setMinimumDuration(0)
        
        # Apply default style if available
        if 'progress_dialog' in self.styles:
            dialog.setStyleSheet(self.styles['progress_dialog'])
            
        return dialog
    
    def create_message_box(self,
                         title: str = "Message",
                         text: str = "",
                         icon: str = "information",
                         buttons: str = "ok",
                         parent: Optional[QtWidgets.QWidget] = None) -> QtWidgets.QMessageBox:
        """
        Create a message box.
        
        Args:
            title: Window title
            text: Message text
            icon: Icon type ('information', 'warning', 'critical', 'question')
            buttons: Buttons to show ('ok', 'yesno', 'yesnocancel', etc.)
            parent: Parent widget
            
        Returns:
            Configured QMessageBox
        """
        msg_box = QtWidgets.QMessageBox(parent)
        msg_box.setWindowTitle(title)
        msg_box.setText(text)
        
        # Set icon
        icon_type = getattr(
            QtWidgets.QMessageBox.Icon,
            f"{icon.capitalize()}",
            QtWidgets.QMessageBox.Icon.Information
        )
        msg_box.setIcon(icon_type)
        
        # Set buttons
        button_types = {
            'ok': QtWidgets.QMessageBox.StandardButton.Ok,
            'yesno': QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            'yesnocancel': QtWidgets.QMessageBox.StandardButton.Yes | 
                          QtWidgets.QMessageBox.StandardButton.No | 
                          QtWidgets.QMessageBox.StandardButton.Cancel,
            'savecancel': QtWidgets.QMessageBox.StandardButton.Save | 
                         QtWidgets.QMessageBox.StandardButton.Cancel,
        }
        
        standard_buttons = button_types.get(buttons.lower(), QtWidgets.QMessageBox.StandardButton.Ok)
        msg_box.setStandardButtons(standard_buttons)
        
        # Apply style if available
        if 'message_box' in self.styles:
            msg_box.setStyleSheet(self.styles['message_box'])
            
        return msg_box
