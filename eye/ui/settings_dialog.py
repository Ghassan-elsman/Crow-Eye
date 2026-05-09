"""
Context Window Settings Dialog for EYE AI Forensic Assistant.

This module provides a settings dialog for configuring context window management
and token budgets. The dialog uses tabs to organize different configuration sections
and integrates with ContextWindowConfigManager for loading/saving settings.

"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QWidget, QSpinBox, QCheckBox, QComboBox,
    QGroupBox, QFormLayout, QMessageBox, QStatusBar
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPalette, QColor
from typing import Dict, Any


class ContextWindowSettingsDialog(QDialog):
    """
    Settings dialog for context window configuration.
    
    Provides tabbed interface for:
    - Backend Selection: Choose backend and apply presets
    - Token Budget: Configure token allocation across components
    - History Management: Configure conversation history truncation
    
    """
    
    def __init__(self, config_manager, current_backend: str, parent=None):
        """
        Initialize settings dialog.
        
        Args:
            config_manager: ContextWindowConfigManager instance
            current_backend: Currently configured backend name
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.config_manager = config_manager
        self.current_backend = current_backend
        self.config = config_manager.get_config_for_backend(current_backend)
        self.presets = config_manager.get_available_presets()
        
        # Track if configuration has been modified
        self.modified = False
        
        self._init_ui()
        self._apply_styling()
        self._load_current_config()
    
    def _init_ui(self):
        """Initialize the user interface components."""
        self.setWindowTitle("Context Window Settings")
        self.setMinimumSize(700, 600)
        self.resize(800, 650)
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)
        
        # Title
        title = QLabel("Context Window Configuration")
        title.setStyleSheet(
            "font-size: 16pt; font-weight: bold; color: #00FFFF; background: transparent;"
        )
        main_layout.addWidget(title)
        
        # Tab widget
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, 1)
        
        # Create tabs
        self._create_backend_tab()
        self._create_token_budget_tab()
        self._create_history_management_tab()
        
        # Status bar
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet("""
            QStatusBar {
                background-color: #1E293B;
                color: #E5E7EB;
                border-top: 1px solid #334155;
                padding: 4px;
            }
        """)
        main_layout.addWidget(self.status_bar)
        
        # Button layout
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        
        button_layout.addStretch()
        
        self.reset_button = QPushButton("Reset to Preset")
        self.reset_button.setFixedHeight(40)
        self.reset_button.setMinimumWidth(140)
        self.reset_button.clicked.connect(self._on_reset_to_preset)
        button_layout.addWidget(self.reset_button)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFixedHeight(40)
        self.cancel_button.setMinimumWidth(120)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        self.save_button = QPushButton("Save")
        self.save_button.setFixedHeight(40)
        self.save_button.setMinimumWidth(120)
        self.save_button.clicked.connect(self._on_save)
        button_layout.addWidget(self.save_button)
        
        main_layout.addLayout(button_layout)
    
    def _apply_styling(self):
        """Apply comprehensive dark theme styling."""
        # Set palette
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor("#0B1220"))
        palette.setColor(QPalette.WindowText, QColor("#E5E7EB"))
        palette.setColor(QPalette.Base, QColor("#1E293B"))
        palette.setColor(QPalette.Text, QColor("#F8FAFC"))
        self.setPalette(palette)
        
        # Dialog stylesheet
        dialog_style = """
            QDialog {
                background-color: #0B1220;
                color: #E5E7EB;
            }
            QWidget {
                background-color: #0B1220;
                color: #E5E7EB;
            }
            QLabel {
                color: #E5E7EB;
                font-size: 10pt;
                background: transparent;
            }
            QTabWidget::pane {
                border: 1px solid #334155;
                background: #111827;
                border-radius: 4px;
            }
            QTabBar::tab {
                background: #1E293B;
                color: #9CA3AF;
                padding: 10px 20px;
                border: 1px solid #334155;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #111827;
                color: #00FFFF;
                border-bottom: 2px solid #00FFFF;
            }
            QTabBar::tab:hover {
                background: #334155;
                color: #E5E7EB;
            }
            QSpinBox, QComboBox {
                background: #1E293B;
                border: 1px solid #334155;
                padding: 6px;
                color: #F8FAFC;
                font-size: 10pt;
                border-radius: 4px;
                min-width: 150px;
            }
            QSpinBox:focus, QComboBox:focus {
                border: 2px solid #00FFFF;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background: #334155;
                border: none;
                width: 16px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background: #475569;
            }
            QComboBox::drop-down {
                border: none;
                background: #334155;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid #9CA3AF;
                margin-right: 6px;
            }
            QCheckBox {
                color: #E5E7EB;
                font-size: 10pt;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #6B7280;
                border-radius: 3px;
                background: #1E293B;
            }
            QCheckBox::indicator:checked {
                background: #00FFFF;
                border: 2px solid #00FFFF;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #00FFFF;
            }
            QGroupBox {
                border: 2px solid #334155;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 12px;
                background: #111827;
                font-weight: bold;
                color: #00FFFF;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 4px 8px;
                background: #111827;
                color: #00FFFF;
            }
            QPushButton {
                background-color: #1E293B;
                color: #E5E7EB;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 10pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #334155;
                border: 1px solid #00FFFF;
            }
            QPushButton:pressed {
                background-color: #475569;
            }
        """
        
        self.setStyleSheet(dialog_style)
        
        # Button-specific styles
        self.save_button.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 10pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
            QPushButton:pressed {
                background-color: #047857;
            }
        """)
        
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #6B7280;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 10pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4B5563;
            }
            QPushButton:pressed {
                background-color: #374151;
            }
        """)
        
        self.reset_button.setStyleSheet("""
            QPushButton {
                background-color: #F59E0B;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 10pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #D97706;
            }
            QPushButton:pressed {
                background-color: #B45309;
            }
        """)
    
    def _create_backend_tab(self):
        """Create Backend Selection tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Backend selection group
        backend_group = QGroupBox("Backend Selection")
        backend_layout = QFormLayout()
        backend_layout.setSpacing(12)
        backend_layout.setLabelAlignment(Qt.AlignRight)
        
        # Backend dropdown
        backend_label = QLabel("Backend:")
        backend_label.setStyleSheet("font-weight: bold; color: #E5E7EB;")
        
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(sorted(self.presets.keys()))
        self.backend_combo.setCurrentText(self.current_backend)
        self.backend_combo.currentTextChanged.connect(self._on_backend_changed)
        
        backend_layout.addRow(backend_label, self.backend_combo)
        
        # Current preset display
        preset_label = QLabel("Current Preset:")
        preset_label.setStyleSheet("font-weight: bold; color: #E5E7EB;")
        
        self.preset_display = QLabel(self.current_backend)
        self.preset_display.setStyleSheet("color: #00FFFF; font-weight: bold;")
        
        backend_layout.addRow(preset_label, self.preset_display)
        
        backend_group.setLayout(backend_layout)
        layout.addWidget(backend_group)
        
        # Apply preset button
        apply_preset_layout = QHBoxLayout()
        apply_preset_layout.addStretch()
        
        self.apply_preset_button = QPushButton("Apply Preset")
        self.apply_preset_button.setFixedHeight(36)
        self.apply_preset_button.setMinimumWidth(140)
        self.apply_preset_button.clicked.connect(self._on_apply_preset)
        self.apply_preset_button.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 10pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
            QPushButton:pressed {
                background-color: #1D4ED8;
            }
        """)
        
        apply_preset_layout.addWidget(self.apply_preset_button)
        layout.addLayout(apply_preset_layout)
        
        # Info text
        info_text = QLabel(
            "Select a backend to view its default preset configuration. "
            "Click 'Apply Preset' to load the default settings for the selected backend."
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet("color: #9CA3AF; font-size: 9pt; background: transparent;")
        layout.addWidget(info_text)
        
        layout.addStretch()
        
        self.tabs.addTab(tab, "Backend Selection")
    
    def _create_token_budget_tab(self):
        """Create Token Budget tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Max total tokens
        max_tokens_group = QGroupBox("Context Window Size")
        max_tokens_layout = QFormLayout()
        max_tokens_layout.setSpacing(12)
        max_tokens_layout.setLabelAlignment(Qt.AlignRight)
        
        max_tokens_label = QLabel("Max Total Tokens:")
        max_tokens_label.setStyleSheet("font-weight: bold; color: #E5E7EB;")
        
        self.max_tokens_spinbox = QSpinBox()
        self.max_tokens_spinbox.setRange(1000, 200000)
        self.max_tokens_spinbox.setSingleStep(1000)
        self.max_tokens_spinbox.valueChanged.connect(self._on_config_changed)
        
        max_tokens_layout.addRow(max_tokens_label, self.max_tokens_spinbox)
        max_tokens_group.setLayout(max_tokens_layout)
        layout.addWidget(max_tokens_group)
        
        # Token budget components
        budget_group = QGroupBox("Token Budget Allocation")
        budget_layout = QFormLayout()
        budget_layout.setSpacing(12)
        budget_layout.setLabelAlignment(Qt.AlignRight)
        
        # Create spinboxes for each budget component
        self.budget_spinboxes = {}
        
        budget_components = [
            ("system_prompt", "System Prompt:"),
            ("rag_context", "RAG Context:"),
            ("conversation_history", "Conversation History:"),
            ("tool_definitions", "Tool Definitions:"),
            ("response_buffer", "Response Buffer:")
        ]
        
        for key, label_text in budget_components:
            label = QLabel(label_text)
            label.setStyleSheet("font-weight: bold; color: #E5E7EB;")
            
            spinbox = QSpinBox()
            spinbox.setRange(0, 100000)
            spinbox.setSingleStep(100)
            spinbox.valueChanged.connect(self._on_budget_changed)
            
            self.budget_spinboxes[key] = spinbox
            budget_layout.addRow(label, spinbox)
        
        budget_group.setLayout(budget_layout)
        layout.addWidget(budget_group)
        
        # Budget summary
        summary_group = QGroupBox("Budget Summary")
        summary_layout = QVBoxLayout()
        summary_layout.setSpacing(8)
        
        self.budget_sum_label = QLabel("Total Allocated: 0 tokens")
        self.budget_sum_label.setStyleSheet("font-weight: bold; color: #E5E7EB; background: transparent;")
        summary_layout.addWidget(self.budget_sum_label)
        
        self.budget_remaining_label = QLabel("Remaining: 0 tokens")
        self.budget_remaining_label.setStyleSheet("font-weight: bold; color: #10B981; background: transparent;")
        summary_layout.addWidget(self.budget_remaining_label)
        
        self.budget_warning_label = QLabel("")
        self.budget_warning_label.setStyleSheet(
            "font-weight: bold; color: #F59E0B; background: transparent;"
        )
        self.budget_warning_label.setWordWrap(True)
        summary_layout.addWidget(self.budget_warning_label)
        
        summary_group.setLayout(summary_layout)
        layout.addWidget(summary_group)
        
        layout.addStretch()
        
        self.tabs.addTab(tab, "Token Budget")
    
    def _create_history_management_tab(self):
        """Create History Management tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Sliding window configuration
        window_group = QGroupBox("Sliding Window Configuration")
        window_layout = QFormLayout()
        window_layout.setSpacing(12)
        window_layout.setLabelAlignment(Qt.AlignRight)
        
        window_label = QLabel("Sliding Window Size:")
        window_label.setStyleSheet("font-weight: bold; color: #E5E7EB;")
        
        self.window_size_spinbox = QSpinBox()
        self.window_size_spinbox.setRange(1, 100)
        self.window_size_spinbox.setSingleStep(1)
        self.window_size_spinbox.valueChanged.connect(self._on_config_changed)
        
        window_layout.addRow(window_label, self.window_size_spinbox)
        
        window_info = QLabel(
            "Number of recent messages to preserve when truncating conversation history."
        )
        window_info.setWordWrap(True)
        window_info.setStyleSheet("color: #9CA3AF; font-size: 9pt; background: transparent;")
        window_layout.addRow("", window_info)
        
        window_group.setLayout(window_layout)
        layout.addWidget(window_group)
        
        # Preservation options
        preserve_group = QGroupBox("Message Preservation")
        preserve_layout = QVBoxLayout()
        preserve_layout.setSpacing(12)
        
        self.preserve_first_checkbox = QCheckBox("Preserve First Message")
        self.preserve_first_checkbox.stateChanged.connect(self._on_config_changed)
        preserve_layout.addWidget(self.preserve_first_checkbox)
        
        first_info = QLabel(
            "Always keep the first message (context-setting) even when truncating."
        )
        first_info.setWordWrap(True)
        first_info.setStyleSheet("color: #9CA3AF; font-size: 9pt; background: transparent; margin-left: 26px;")
        preserve_layout.addWidget(first_info)
        
        self.preserve_tool_checkbox = QCheckBox("Preserve Tool Messages")
        self.preserve_tool_checkbox.stateChanged.connect(self._on_config_changed)
        preserve_layout.addWidget(self.preserve_tool_checkbox)
        
        tool_info = QLabel(
            "Keep messages containing tool calls and results to maintain conversation coherence."
        )
        tool_info.setWordWrap(True)
        tool_info.setStyleSheet("color: #9CA3AF; font-size: 9pt; background: transparent; margin-left: 26px;")
        preserve_layout.addWidget(tool_info)
        
        preserve_group.setLayout(preserve_layout)
        layout.addWidget(preserve_group)
        
        # Truncation strategy
        strategy_group = QGroupBox("Truncation Strategy")
        strategy_layout = QFormLayout()
        strategy_layout.setSpacing(12)
        strategy_layout.setLabelAlignment(Qt.AlignRight)
        
        strategy_label = QLabel("Strategy:")
        strategy_label.setStyleSheet("font-weight: bold; color: #E5E7EB;")
        
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(["sliding_window", "summarization", "none"])
        self.strategy_combo.currentTextChanged.connect(self._on_config_changed)
        
        strategy_layout.addRow(strategy_label, self.strategy_combo)
        
        strategy_info = QLabel(
            "sliding_window: Remove oldest messages\n"
            "summarization: Summarize old messages (future feature)\n"
            "none: No automatic truncation"
        )
        strategy_info.setWordWrap(True)
        strategy_info.setStyleSheet("color: #9CA3AF; font-size: 9pt; background: transparent;")
        strategy_layout.addRow("", strategy_info)
        
        strategy_group.setLayout(strategy_layout)
        layout.addWidget(strategy_group)
        
        layout.addStretch()
        
        self.tabs.addTab(tab, "History Management")
    
    def _load_current_config(self):
        """Load current configuration into UI widgets."""
        # Max total tokens
        self.max_tokens_spinbox.setValue(self.config["max_total_tokens"])
        
        # Token budget
        budget = self.config["token_budget"]
        for key, spinbox in self.budget_spinboxes.items():
            spinbox.setValue(budget[key])
        
        # History management
        history = self.config["history_management"]
        self.window_size_spinbox.setValue(history["sliding_window_size"])
        self.preserve_first_checkbox.setChecked(history["preserve_first_message"])
        self.preserve_tool_checkbox.setChecked(history["preserve_tool_messages"])
        self.strategy_combo.setCurrentText(history["truncation_strategy"])
        
        # Update budget summary
        self._update_budget_summary()
        
        # Reset modified flag
        self.modified = False
    
    def _on_backend_changed(self, backend: str):
        """Handle backend selection change."""
        self.preset_display.setText(backend)
    
    def _on_apply_preset(self):
        """Apply preset for selected backend."""
        selected_backend = self.backend_combo.currentText()
        
        reply = QMessageBox.question(
            self,
            "Apply Preset",
            f"Apply default preset for {selected_backend}?\n\n"
            "This will replace your current configuration with the preset values.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Load preset configuration
            preset_config = self.config_manager._get_preset_for_backend(selected_backend)
            self.config = preset_config
            self.current_backend = selected_backend
            
            # Reload UI
            self._load_current_config()
            
            self.status_bar.showMessage(f"Applied preset for {selected_backend}", 3000)
            self.modified = True
    
    def _on_config_changed(self):
        """Handle configuration change."""
        self.modified = True
        self._update_budget_summary()
    
    def _on_budget_changed(self):
        """Handle budget component change."""
        self.modified = True
        self._update_budget_summary()
    
    def _update_budget_summary(self):
        """Update budget summary display."""
        # Calculate budget sum
        budget_sum = sum(spinbox.value() for spinbox in self.budget_spinboxes.values())
        max_tokens = self.max_tokens_spinbox.value()
        remaining = max_tokens - budget_sum
        
        # Update labels
        self.budget_sum_label.setText(f"Total Allocated: {budget_sum:,} tokens")
        self.budget_remaining_label.setText(f"Remaining: {remaining:,} tokens")
        
        # Show warning if sum exceeds max
        if budget_sum > max_tokens:
            self.budget_warning_label.setText(
                f"⚠️ Warning: Budget sum ({budget_sum:,}) exceeds max total tokens ({max_tokens:,})"
            )
            self.budget_remaining_label.setStyleSheet("font-weight: bold; color: #EF4444; background: transparent;")
        else:
            self.budget_warning_label.setText("")
            self.budget_remaining_label.setStyleSheet("font-weight: bold; color: #10B981; background: transparent;")
    
    def _validate_config(self) -> bool:
        """
        Validate current configuration.
        
        Returns:
            True if valid, False otherwise
        """
        # Get current values
        max_tokens = self.max_tokens_spinbox.value()
        budget_sum = sum(spinbox.value() for spinbox in self.budget_spinboxes.values())
        
        # Check budget sum
        if budget_sum > max_tokens:
            self.status_bar.showMessage(
                f"Error: Budget sum ({budget_sum:,}) exceeds max total tokens ({max_tokens:,})",
                5000
            )
            return False
        
        # Check window size
        window_size = self.window_size_spinbox.value()
        if window_size <= 0:
            self.status_bar.showMessage("Error: Sliding window size must be positive", 5000)
            return False
        
        return True
    
    def _get_current_config(self) -> Dict[str, Any]:
        """
        Get current configuration from UI widgets.
        
        Returns:
            Configuration dictionary
        """
        return {
            "max_total_tokens": self.max_tokens_spinbox.value(),
            "token_budget": {
                key: spinbox.value()
                for key, spinbox in self.budget_spinboxes.items()
            },
            "history_management": {
                "sliding_window_size": self.window_size_spinbox.value(),
                "preserve_first_message": self.preserve_first_checkbox.isChecked(),
                "preserve_tool_messages": self.preserve_tool_checkbox.isChecked(),
                "truncation_strategy": self.strategy_combo.currentText()
            }
        }
    
    def _on_reset_to_preset(self):
        """Reset configuration to default preset for current backend."""
        reply = QMessageBox.question(
            self,
            "Reset to Preset",
            f"Reset configuration to default preset for {self.current_backend}?\n\n"
            "This will discard any unsaved changes.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Reload preset configuration
            self.config = self.config_manager._get_preset_for_backend(self.current_backend)
            self._load_current_config()
            
            self.status_bar.showMessage(f"Reset to preset for {self.current_backend}", 3000)
            self.modified = True
    
    def _on_save(self):
        """Save configuration."""
        # Validate configuration
        if not self._validate_config():
            return
        
        try:
            # Get current configuration
            config = self._get_current_config()
            
            # Save using config manager
            self.config_manager.save_config(config)
            
            # Show success message
            QMessageBox.information(
                self,
                "Configuration Saved",
                "Context window configuration has been saved successfully.\n\n"
                "Changes will take effect immediately."
            )
            
            # Accept dialog
            self.accept()
            
        except ValueError as e:
            # Validation error
            self.status_bar.showMessage(f"Validation error: {str(e)}", 5000)
            QMessageBox.warning(
                self,
                "Validation Error",
                f"Configuration validation failed:\n\n{str(e)}"
            )
        except Exception as e:
            # Save error
            self.status_bar.showMessage(f"Save error: {str(e)}", 5000)
            QMessageBox.critical(
                self,
                "Save Error",
                f"Failed to save configuration:\n\n{str(e)}"
            )
