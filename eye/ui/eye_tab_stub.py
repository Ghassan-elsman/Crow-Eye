"""
EYE Tab Stub for Context Window Settings Integration.

This module provides a stub implementation of the EYE Tab that demonstrates
the integration pattern for the Context Window Settings Dialog. The full
EYE Tab implementation will be completed in Task 17.

This stub shows:
- How to add a "Context Settings" button to the chat toolbar
- How to open the ContextWindowSettingsDialog
- How to call ContextManager.update_context_config() after saving
- How to display success messages

"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QMessageBox, QToolBar
)
from PyQt5.QtCore import Qt
from typing import Optional

from eye.services.context_manager import ContextManager
from eye.services.context_window_config_manager import ContextWindowConfigManager
from eye.ui.settings_dialog import ContextWindowSettingsDialog


class EYETabStub(QWidget):
    """
    Stub implementation of EYE Tab for demonstrating Context Settings integration.
    
    This is a placeholder implementation that shows the integration pattern
    for the Context Window Settings Dialog. The full EYE Tab with chat interface,
    report builder, and QWebChannel bridge will be implemented in Task 17.
    
    Integration Pattern:
    1. Add "Context Settings" button to chat toolbar
    2. Open ContextWindowSettingsDialog when clicked
    3. After dialog saves, call ContextManager.update_context_config()
    4. Display success message to user
    
    """
    
    def __init__(
        self,
        context_manager: ContextManager,
        config_manager: Optional[ContextWindowConfigManager] = None,
        parent=None
    ):
        """
        Initialize EYE Tab stub.
        
        Args:
            context_manager: ContextManager instance for configuration updates
            config_manager: Optional ContextWindowConfigManager (creates default if None)
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.context_manager = context_manager
        self.config_manager = config_manager or ContextWindowConfigManager()
        
        self._init_ui()
    
    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Create toolbar
        toolbar = self._create_toolbar()
        layout.addWidget(toolbar)
        
        # Placeholder content area
        content_area = QWidget()
        content_layout = QVBoxLayout(content_area)
        content_layout.setAlignment(Qt.AlignCenter)
        
        placeholder_label = QLabel(
            "EYE Tab Stub\n\n"
            "This is a placeholder implementation demonstrating\n"
            "Context Window Settings Dialog integration.\n\n"
            "Click 'Context Settings' in the toolbar above to test the integration.\n\n"
            "Full EYE Tab implementation (Task 17) will include:\n"
            "- Chat Interface (React SPA)\n"
            "- Report Builder Panel\n"
            "- QWebChannel Bridge\n"
            "- Interactive Data Viewer"
        )
        placeholder_label.setAlignment(Qt.AlignCenter)
        placeholder_label.setStyleSheet("""
            QLabel {
                color: #9CA3AF;
                font-size: 12pt;
                padding: 40px;
                background: #1E293B;
                border-radius: 8px;
            }
        """)
        
        content_layout.addWidget(placeholder_label)
        layout.addWidget(content_area, 1)
        
        # Apply styling
        self.setStyleSheet("""
            QWidget {
                background-color: #0B1220;
            }
        """)
    
    def _create_toolbar(self) -> QToolBar:
        """
        Create chat toolbar with Context Settings button.
        
        Returns:
            QToolBar with Context Settings button
        """
        toolbar = QToolBar("Chat Toolbar")
        toolbar.setMovable(False)
        toolbar.setStyleSheet("""
            QToolBar {
                background-color: #1E293B;
                border-bottom: 1px solid #334155;
                padding: 4px;
                spacing: 8px;
            }
            QPushButton {
                background-color: #334155;
                color: #E5E7EB;
                border: 1px solid #475569;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 10pt;
            }
            QPushButton:hover {
                background-color: #475569;
                border: 1px solid #00FFFF;
            }
            QPushButton:pressed {
                background-color: #1E293B;
            }
        """)
        
        # Add Context Settings button
        context_settings_button = QPushButton("⚙️ Context Settings")
        context_settings_button.setToolTip("Configure context window and token budget settings")
        context_settings_button.clicked.connect(self._on_context_settings_clicked)
        toolbar.addWidget(context_settings_button)
        
        # Add spacer
        spacer = QWidget()
        from PyQt5.QtWidgets import QSizePolicy
        spacer.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Preferred
        )
        toolbar.addWidget(spacer)
        
        # Add placeholder buttons for future implementation
        clear_history_button = QPushButton("🗑️ Clear History")
        clear_history_button.setToolTip("Clear conversation history (placeholder)")
        clear_history_button.setEnabled(False)
        toolbar.addWidget(clear_history_button)
        
        export_button = QPushButton("📥 Export")
        export_button.setToolTip("Export conversation or report (placeholder)")
        export_button.setEnabled(False)
        toolbar.addWidget(export_button)
        
        return toolbar
    
    def _on_context_settings_clicked(self):
        """
        Handle Context Settings button click.
        
        This method demonstrates the integration pattern:
        1. Get current backend from context manager
        2. Open ContextWindowSettingsDialog
        3. If dialog accepted (saved), get new configuration
        4. Call ContextManager.update_context_config() to apply changes
        5. Display success message
        
        """
        # Get current backend from context manager
        current_backend = self.context_manager.model_router.config.get("backend", "ollama")
        
        # Open settings dialog
        dialog = ContextWindowSettingsDialog(
            config_manager=self.config_manager,
            current_backend=current_backend,
            parent=self
        )
        
        # Execute dialog and check result
        result = dialog.exec_()
        
        if result == ContextWindowSettingsDialog.Accepted:
            # Dialog was saved, apply new configuration
            try:
                # Get updated configuration from config manager
                new_config = self.config_manager.get_config_for_backend(current_backend)
                
                # Apply configuration to context manager
                self.context_manager.update_context_config(new_config)
                
                # Display success message
                QMessageBox.information(
                    self,
                    "Configuration Updated",
                    "Context window configuration has been updated successfully.\n\n"
                    f"Max Total Tokens: {new_config['max_total_tokens']:,}\n"
                    f"Conversation History Budget: {new_config['token_budget']['conversation_history']:,}\n"
                    f"Sliding Window Size: {new_config['history_management']['sliding_window_size']}\n\n"
                    "Changes are now active."
                )
                
            except Exception as e:
                # Display error message
                QMessageBox.critical(
                    self,
                    "Configuration Error",
                    f"Failed to apply configuration:\n\n{str(e)}"
                )
        else:
            # Dialog was cancelled, no action needed
            pass
    
    def get_context_stats(self) -> dict:
        """
        Get current context statistics from ContextManager.
        
        This method can be used by the UI to display context usage information.
        
        Returns:
            Dictionary with context statistics:
                - total_messages: Number of messages in history
                - total_tokens: Total tokens used
                - budget_remaining: Tokens remaining in budget
                - truncation_count: Number of truncations
                - max_total_tokens: Maximum context window size
        """
        return self.context_manager.get_context_stats()
