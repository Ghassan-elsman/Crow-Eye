"""
Onboarding Wizard for EYE AI Forensic Assistant

This module provides a first-time setup wizard for configuring the LLM backend.
The wizard guides users through:
1. Welcome screen with capabilities overview
2. Integration type selection (Local CLI, Local API, Cloud API)
3. Dynamic credential input based on selected integration
4. Connectivity validation
5. Configuration save

"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QLineEdit, QGroupBox, QMessageBox, QTextEdit,
    QButtonGroup, QWidget, QStackedWidget, QFormLayout, QComboBox,
    QInputDialog
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPalette, QColor, QFont
import json
from pathlib import Path


class CloudAPIWarningDialog(QDialog):
    """
    Warning dialog for cloud API usage.
    
    Displays a security warning when users select Public Cloud APIs integration,
    informing them that case data will be transmitted over the internet and that
    organizational approval may be required.
    
    """
    
    def __init__(self, parent=None):
        """
        Initialize cloud API warning dialog.
        
        Args:
            parent: Parent widget (typically OnboardingWizard)
        """
        super().__init__(parent)
        self.setWindowTitle("Cloud API Security Warning")
        self.setMinimumWidth(500)
        
        # Apply dark theme styling
        self.setStyleSheet("""
            QDialog {
                background-color: #0B1220;
                color: #E5E7EB;
            }
            QLabel {
                color: #E5E7EB;
                background: transparent;
            }
            QPushButton {
                background-color: #1E293B;
                color: #E5E7EB;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 10pt;
                font-weight: bold;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: #334155;
                border: 1px solid #00FFFF;
            }
            QPushButton:pressed {
                background-color: #475569;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # Warning icon
        warning_icon = QLabel("⚠️")
        warning_icon.setStyleSheet("font-size: 48px; background: transparent;")
        warning_icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(warning_icon)
        
        # Warning text with bold formatting
        warning_text = QLabel(
            "<p style='text-align: center;'><b style='font-size: 14pt; color: #F59E0B;'>SECURITY WARNING</b></p>"
            "<p style='font-size: 11pt; line-height: 1.6;'>"
            "<b>Using Cloud APIs means transmitting sensitive case data over the internet.</b><br><br>"
            "Organizational approval may be required.<br><br>"
            "Ensure you have authorization before proceeding."
            "</p>"
        )
        warning_text.setWordWrap(True)
        warning_text.setTextFormat(Qt.RichText)
        warning_text.setStyleSheet("background: transparent;")
        layout.addWidget(warning_text)
        
        # Button layout
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        
        cancel_btn = QPushButton("Go Back")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #6B7280;
                color: white;
                border: none;
            }
            QPushButton:hover {
                background-color: #4B5563;
            }
            QPushButton:pressed {
                background-color: #374151;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        
        proceed_btn = QPushButton("I Understand, Proceed")
        proceed_btn.setStyleSheet("""
            QPushButton {
                background-color: #F59E0B;
                color: white;
                border: none;
            }
            QPushButton:hover {
                background-color: #D97706;
            }
            QPushButton:pressed {
                background-color: #B45309;
            }
        """)
        proceed_btn.clicked.connect(self.accept)
        
        button_layout.addStretch()
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(proceed_btn)
        
        layout.addLayout(button_layout)


class OnboardingWizard(QDialog):
    """
    Configuration wizard for first-time EYE setup.
    
    Multi-page wizard that guides users through LLM backend configuration:
    - Welcome screen explaining EYE capabilities
    - Integration type selection (Local CLI, Local API Server, Cloud API)
    - Dynamic credential input based on selected type
    - Connectivity validation using ModelRouter
    - Configuration save using ConfigManager and CredentialManager
    
    """
    
    configuration_complete = pyqtSignal(dict)  # Emits config on completion
    
    def __init__(self, config_manager, credential_manager, model_router, parent=None):
        """
        Initialize onboarding wizard.
        
        Args:
            config_manager: ConfigManager instance for saving configuration
            credential_manager: CredentialManager instance for storing API keys
            model_router: ModelRouter instance for connectivity validation
            parent: Parent widget (typically the main window)
        """
        super().__init__(parent)
        
        # Set window flags for independent styling
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        
        # Store service instances
        self.config_manager = config_manager
        self.credential_manager = credential_manager
        self.model_router = model_router
        
        # Configuration state
        self.config = {
            "integration_type": None,
            "backend": None,
            "model_name": "",
            "executable_path": "",
            "api_endpoint": "",
            "last_validated": None
        }
        
        # Load existing configuration if available
        try:
            existing_config = self.config_manager.load_config()
            if existing_config:
                self.config.update(existing_config)
                # Ensure integration_type is preserved even if it was inferred previously
                if "integration_type" in existing_config:
                    self.config["integration_type"] = existing_config["integration_type"]
        except Exception as e:
            # If config is invalid or fails to load, start fresh
            print(f"[Warning] Failed to load existing EYE config: {e}")
        
        # Current page index
        self.current_page = 0
        
        self._init_ui()
        self._apply_styling()
        self.show_welcome_screen()
    
    def _init_ui(self):
        """Initialize the user interface components."""
        self.setWindowTitle("EYE Assistant Setup Wizard")
        self.setMinimumSize(900, 700)
        self.resize(1000, 750)
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Stacked widget for pages
        self.pages = QStackedWidget()
        main_layout.addWidget(self.pages, 1)
        
        # Navigation buttons
        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(16, 12, 16, 16)
        nav_layout.setSpacing(12)
        
        self.diag_button = QPushButton("Diagnostics")
        self.diag_button.setFixedHeight(40)
        self.diag_button.setMinimumWidth(120)
        self.diag_button.setStyleSheet("""
            QPushButton {
                background-color: #4B5563;
                color: #E5E7EB;
                border: 1px solid #6B7280;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 10pt;
            }
            QPushButton:hover {
                background-color: #374151;
                border-color: #9CA3AF;
            }
        """)
        self.diag_button.clicked.connect(self._on_run_diagnostics)
        nav_layout.addWidget(self.diag_button)
        
        nav_layout.addStretch()
        
        self.back_button = QPushButton("Back")
        self.back_button.setFixedHeight(40)
        self.back_button.setMinimumWidth(120)
        self.back_button.setStyleSheet("""
            QPushButton {
                background-color: #6B7280;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 11pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4B5563;
            }
            QPushButton:pressed {
                background-color: #374151;
            }
            QPushButton:disabled {
                background-color: #374151;
                color: #9CA3AF;
            }
        """)
        self.back_button.clicked.connect(self._on_back)
        self.back_button.setEnabled(False)
        nav_layout.addWidget(self.back_button)
        
        self.next_button = QPushButton("Next")
        self.next_button.setFixedHeight(40)
        self.next_button.setMinimumWidth(120)
        self.next_button.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 11pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
            QPushButton:pressed {
                background-color: #047857;
            }
            QPushButton:disabled {
                background-color: #374151;
                color: #9CA3AF;
            }
        """)
        self.next_button.clicked.connect(self._on_next)
        nav_layout.addWidget(self.next_button)
        
        main_layout.addLayout(nav_layout)
    
    def _apply_styling(self):
        """Apply comprehensive dark theme styling to the wizard."""
        # Set palette for backup styling
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor("#0B1220"))
        palette.setColor(QPalette.WindowText, QColor("#E5E7EB"))
        palette.setColor(QPalette.Base, QColor("#1E293B"))
        palette.setColor(QPalette.Text, QColor("#F8FAFC"))
        self.setPalette(palette)
        
        # Main dialog stylesheet
        dialog_style = """
            QDialog {
                background-color: #0B1220;
                color: #E5E7EB;
                font-size: 10pt;
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
            QLineEdit {
                background: #1E293B;
                border: 1px solid #334155;
                padding: 8px;
                color: #F8FAFC;
                font-size: 10pt;
                border-radius: 4px;
            }
            QLineEdit:focus {
                border: 2px solid #00FFFF;
            }
            QRadioButton {
                color: #E5E7EB;
                font-size: 10pt;
                spacing: 8px;
            }
            QRadioButton::indicator {
                width: 18px;
                height: 18px;
            }
            QRadioButton::indicator:unchecked {
                border: 2px solid #6B7280;
                border-radius: 9px;
                background: #1E293B;
            }
            QRadioButton::indicator:checked {
                border: 2px solid #00FFFF;
                border-radius: 9px;
                background: #00FFFF;
            }
        """
        
        self.setStyleSheet(dialog_style)
    
    def show_welcome_screen(self):
        """
        Display welcome screen with capabilities overview.
        
        Shows EYE's key features and benefits to help users understand
        what they're configuring.
        
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 20)
        layout.setSpacing(20)
        
        # Title
        title = QLabel("Welcome to EYE AI Forensic Assistant")
        title.setStyleSheet(
            "font-size: 18pt; font-weight: bold; color: #00FFFF; background: transparent;"
        )
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # Subtitle
        subtitle = QLabel("Enhanced Yield Engine for Digital Forensic Investigations")
        subtitle.setStyleSheet(
            "font-size: 12pt; color: #9CA3AF; background: transparent;"
        )
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)
        
        layout.addSpacing(20)
        
        # Capabilities overview
        capabilities_text = """
<div style='color: #E5E7EB; font-size: 11pt; line-height: 1.6;'>
<p><b style='color: #00FFFF;'>EYE brings AI-powered analysis to your forensic investigations:</b></p>

<ul style='margin-left: 20px;'>
<li><b>Natural Language Querying:</b> Ask questions in plain English instead of writing complex SQL queries</li>
<li><b>Intelligent Analysis:</b> Get forensic insights and artifact interpretation from AI</li>
<li><b>Semantic Mapping:</b> Create rules to identify malicious patterns with AI assistance</li>
<li><b>Evidence Integrity:</b> Read-only database access ensures your evidence remains untouched</li>
<li><b>Flexible Deployment:</b> Works with local models (air-gapped) or cloud APIs</li>
<li><b>Human-in-the-Loop:</b> You maintain control with approval workflows for sensitive operations</li>
</ul>

<p style='margin-top: 20px;'><b style='color: #00FFFF;'>This wizard will help you configure your preferred AI backend.</b></p>
</div>
        """
        
        capabilities = QLabel(capabilities_text)
        capabilities.setWordWrap(True)
        capabilities.setTextFormat(Qt.RichText)
        capabilities.setStyleSheet("background: transparent;")
        layout.addWidget(capabilities)
        
        layout.addStretch()
        
        # Add page to stack
        self.pages.addWidget(page)
        self.pages.setCurrentWidget(page)
        
        # Update navigation
        self.back_button.setEnabled(False)
        self.next_button.setEnabled(True)
        self.next_button.setText("Next")
    
    def show_integration_selection(self):
        """
        Display integration type selection with three backend options.
        
        Presents three integration types:
        - Local/Offline CLI Agents (Ollama, LLaMA, Gemini CLI)
        - Local API Servers (LM Studio, vLLM)
        - Public Cloud APIs (OpenAI, Anthropic, Gemini)
        
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 20)
        layout.setSpacing(20)
        
        # Title
        title = QLabel("Select Integration Type")
        title.setStyleSheet(
            "font-size: 16pt; font-weight: bold; color: #00FFFF; background: transparent;"
        )
        layout.addWidget(title)
        
        # Description
        desc = QLabel(
            "Choose how EYE will connect to an AI model. Your choice depends on your "
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 10pt; color: #9CA3AF; background: transparent;")
        layout.addWidget(desc)
        
        layout.addSpacing(10)
        
        # Radio button group
        self.integration_group = QButtonGroup()
        
        # Option 1: Local CLI Agents
        cli_group = self._create_integration_option(
            "local_cli",
            "Local/Offline CLI Agents",
            "Run AI models locally using command-line tools. Perfect for air-gapped environments.",
            "Supports: Ollama, Local LLaMA, Gemini CLI"
        )
        layout.addWidget(cli_group)
        
        # Option 2: Local API Servers
        api_group = self._create_integration_option(
            "local_api",
            "Local API Servers",
            "Connect to AI models running on your local network via HTTP API.",
            "Supports: LM Studio, vLLM"
        )
        layout.addWidget(api_group)
        
        # Option 3: Cloud APIs
        cloud_group = self._create_integration_option(
            "cloud_api",
            "Public Cloud APIs",
            "Use cloud-based AI services. Requires internet connection and API keys.",
            "Supports: OpenAI, Anthropic, Google Gemini",
            warning="⚠️ Using Cloud APIs means transmitting case data over the internet. Organizational approval may be required."
        )
        layout.addWidget(cloud_group)
        
        layout.addStretch()
        
        # Add page to stack
        self.pages.addWidget(page)
        self.pages.setCurrentWidget(page)
        
        # Update navigation
        self.back_button.setEnabled(True)
        self.next_button.setEnabled(False)  # Enable when selection is made
        self.next_button.setText("Next")
    
    def _create_integration_option(self, value, title, description, supports, warning=None):
        """
        Create a styled integration option group box.
        
        Args:
            value: Integration type value (local_cli, local_api, cloud_api)
            title: Display title
            description: Description text
            supports: Supported backends text
            warning: Optional warning message
            
        Returns:
            QGroupBox containing the option
        """
        group = QGroupBox()
        group.setStyleSheet("""
            QGroupBox {
                border: 2px solid #334155;
                border-radius: 8px;
                padding-top: 10px;
                margin-top: 0px;
                background: #111827;
            }
            QGroupBox:hover {
                border: 2px solid #00FFFF;
            }
        """)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        
        # Radio button with title
        radio = QRadioButton(title)
        radio.setStyleSheet("font-size: 12pt; font-weight: bold; color: #00FFFF;")
        radio.toggled.connect(lambda checked: self._on_integration_selected(value) if checked else None)
        self.integration_group.addButton(radio)
        layout.addWidget(radio)
        
        # Description
        desc_label = QLabel(description)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("font-size: 10pt; color: #E5E7EB; background: transparent; margin-left: 26px;")
        layout.addWidget(desc_label)
        
        # Supports
        supports_label = QLabel(f"<i>{supports}</i>")
        supports_label.setStyleSheet("font-size: 9pt; color: #9CA3AF; background: transparent; margin-left: 26px;")
        layout.addWidget(supports_label)
        
        # Warning (if provided)
        if warning:
            warning_label = QLabel(warning)
            warning_label.setWordWrap(True)
            warning_label.setStyleSheet(
                "font-size: 9pt; font-weight: bold; color: #F59E0B; "
                "background: #1E1B16; padding: 8px; border-radius: 4px; margin-left: 26px; margin-top: 8px;"
            )
            layout.addWidget(warning_label)
        
        group.setLayout(layout)
        return group
    
    def _on_integration_selected(self, integration_type):
        """
        Handle integration type selection.
        
        Args:
            integration_type: Selected integration type (local_cli, local_api, cloud_api)
        """
        self.config["integration_type"] = integration_type
        self.next_button.setEnabled(True)
    
    def show_credential_input(self, integration_type):
        """
        Display dynamic credential input form based on selected integration type.
        
        Shows different input fields depending on the integration type:
        - Local CLI: executable path, model name
        - Local API: API endpoint, model name
        - Cloud API: backend selection, API key, model name
        
        Args:
            integration_type: The selected integration type (local_cli, local_api, cloud_api)
            
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 20)
        layout.setSpacing(20)
        
        # Title
        title = QLabel("Configure Backend")
        title.setStyleSheet(
            "font-size: 16pt; font-weight: bold; color: #00FFFF; background: transparent;"
        )
        layout.addWidget(title)
        
        # Form layout
        form_group = QGroupBox()
        form_group.setStyleSheet("""
            QGroupBox {
                border: 2px solid #334155;
                border-radius: 8px;
                padding-top: 20px;
                margin-top: 10px;
                background: #111827;
            }
        """)
        
        form_layout = QFormLayout()
        form_layout.setContentsMargins(20, 20, 20, 20)
        form_layout.setSpacing(16)
        form_layout.setLabelAlignment(Qt.AlignRight)
        
        # Store input widgets for validation
        self.input_widgets = {}
        
        if integration_type == "local_cli":
            # Local CLI configuration
            from eye.cli_agents.cli_profiles import list_supported_backends
            self._add_backend_selector(form_layout, list_supported_backends())
            self._add_text_input(form_layout, "executable_path", "Executable Path:", 
                                 placeholder="/usr/local/bin/ollama")
            self._add_text_input(form_layout, "model_name", "Model Name:", 
                                 placeholder="llama2")
            
        elif integration_type == "local_api":
            # Local API configuration
            self._add_backend_selector(form_layout, ["lm_studio", "vllm"])
            self._add_text_input(form_layout, "api_endpoint", "API Endpoint:", 
                                 placeholder="http://localhost:1234")
            self._add_text_input(form_layout, "model_name", "Model Name:", 
                                 placeholder="local-model")
            
        elif integration_type == "cloud_api":
            # Cloud API configuration
            self._add_backend_selector(form_layout, ["openai", "anthropic", "gemini"])
            self._add_text_input(form_layout, "api_key", "API Key:", 
                                 placeholder="sk-... or AIza...", password=True)
            self._add_text_input(form_layout, "model_name", "Model Name:", 
                                 placeholder="Click 'Detect Models' after entering API key")
        
        form_group.setLayout(form_layout)
        layout.addWidget(form_group)
        
        layout.addStretch()
        
        # Add page to stack
        self.pages.addWidget(page)
        self.pages.setCurrentWidget(page)
        
        # Update navigation
        self.back_button.setEnabled(True)
        self.next_button.setEnabled(True)
        self.next_button.setText("Validate & Save")
    
    def _add_backend_selector(self, form_layout, backends):
        """
        Add backend selection radio buttons to form.
        
        Args:
            form_layout: QFormLayout to add to
            backends: List of backend names
        """
        label = QLabel("Backend:")
        label.setStyleSheet("font-size: 10pt; font-weight: bold; color: #E5E7EB;")
        
        backend_widget = QWidget()
        backend_layout = QVBoxLayout(backend_widget)
        backend_layout.setContentsMargins(0, 0, 0, 0)
        backend_layout.setSpacing(8)
        
        self.backend_group = QButtonGroup()
        
        for backend in backends:
            radio = QRadioButton(backend.replace("_", " ").title())
            radio.toggled.connect(lambda checked, b=backend: self._on_backend_selected(b) if checked else None)
            self.backend_group.addButton(radio)
            backend_layout.addWidget(radio)
        
        # Select first by default
        self.backend_group.buttons()[0].setChecked(True)
        self.config["backend"] = backends[0]
        
        form_layout.addRow(label, backend_widget)
    
    def _on_backend_selected(self, backend):
        """
        Handle backend selection.
        
        Args:
            backend: Selected backend name
        """
        self.config["backend"] = backend
    
    def _add_text_input(self, form_layout, key, label_text, placeholder="", password=False):
        """
        Add text input field to form.
        
        Args:
            form_layout: QFormLayout to add to
            key: Configuration key
            label_text: Label text
            placeholder: Placeholder text
            password: Whether to use password mode
        """
        label = QLabel(label_text)
        label.setStyleSheet("font-size: 10pt; font-weight: bold; color: #E5E7EB;")
        
        input_field = QLineEdit()
        input_field.setPlaceholderText(placeholder)
        input_field.setMinimumWidth(300)
        if password:
            input_field.setEchoMode(QLineEdit.Password)
        
        input_field.textChanged.connect(lambda text: self._on_input_changed(key, text))
        
        # Set initial value if present in config
        if self.config.get(key):
            input_field.setText(self.config[key])
        
        self.input_widgets[key] = input_field
        form_layout.addRow(label, input_field)
        
        # Add "Detect Models" button for cloud API model name field
        if key == "model_name" and self.config.get("integration_type") == "cloud_api":
            detect_button = QPushButton("🔍 Detect Available Models")
            detect_button.setStyleSheet("""
                QPushButton {
                    background-color: #0EA5E9;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-size: 10pt;
                    margin-top: 8px;
                }
                QPushButton:hover {
                    background-color: #0284C7;
                }
                QPushButton:pressed {
                    background-color: #0369A1;
                }
            """)
            detect_button.clicked.connect(self._detect_models)
            form_layout.addRow("", detect_button)
    
    def _on_input_changed(self, key, value):
        """
        Handle input field changes.
        
        Args:
            key: Configuration key
            value: New value
        """
        self.config[key] = value
    
    def _detect_models(self):
        """
        Detect available models using the provided API key and ModelRouter.
        
        Queries the API to list available models based on the selected backend
        and displays them in a dialog for the user to select from.
        """
        backend = self.config.get("backend")
        
        # Get API key from input field
        api_key_widget = self.input_widgets.get("api_key", None)
        api_key = api_key_widget.text().strip() if api_key_widget else ""
        
        if not api_key:
            QMessageBox.warning(
                self,
                "API Key Required",
                f"Please enter your {backend.title()} API key first before detecting models."
            )
            return

        # Heuristic validation for API key format
        if backend == "openai" and not api_key.startswith("sk-"):
            QMessageBox.warning(self, "Invalid API Key Format", 
                               "OpenAI API keys usually start with 'sk-'.\n\nPlease check your key.")
            return
        elif backend == "gemini" and not api_key.startswith("AIza"):
            QMessageBox.warning(self, "Invalid API Key Format", 
                               "Gemini API keys usually start with 'AIza'.\n\nPlease check your key.")
            return
        elif backend == "anthropic" and not api_key.startswith("sk-ant-"):
            QMessageBox.warning(self, "Invalid API Key Format", 
                               "Anthropic API keys usually start with 'sk-ant-'.\n\nPlease check your key.")
            return

        try:
            # Temporarily store key for validation
            key_name = f"{backend}_api_key"
            self.credential_manager.store_credential(key_name, api_key)
            
            # Use ModelRouter to fetch models dynamically
            from eye.services.model_router import ModelRouter
            temp_router = ModelRouter(self.config, self.credential_manager)
            
            available_models = temp_router.backend.list_models()

            if not available_models:
                backend_title = backend.title()
                if "LM Studio" in backend_title or "Ollama" in backend_title:
                    help_text = (
                        f"No models were found for {backend_title}.\n\n"
                        "Please ensure:\n"
                        "1. The local server is running.\n"
                        "2. At least one model is loaded into memory (RAM/VRAM).\n"
                        "3. The API endpoint address is correct."
                    )
                else:
                    help_text = (
                        f"No supported models were found for {backend_title}.\n\n"
                        "Please check your API key and internet connection."
                    )

                QMessageBox.warning(self, "No Models Found", help_text)
                return

            
            self._show_model_selection_dialog(
                available_models,
                recommended=[], # No hardcoded recommendations
                title=f"Select {backend.replace('_', ' ').title()} Model"
            )
            
        except Exception as e:
            # Provide more detailed error information to help with troubleshooting
            error_details = str(e)
            if "401" in error_details or "Unauthorized" in error_details:
                error_msg = "Authentication failed (401). Please verify your API key is correct and active."
            elif "dns" in error_details.lower() or "connection" in error_details.lower():
                error_msg = "Network error. Please check your internet connection and DNS settings."
            else:
                error_msg = f"Failed to detect available models:\n\n{error_details}"

            QMessageBox.critical(
                self,
                "Detection Failed",
                f"{error_msg}\n\n"
                "Tip: Ensure you are using the correct key for the selected backend."
            )

    # Remove the old specific detection methods as they are now redundant
    def _detect_gemini_models(self): pass
    def _detect_openai_models(self): pass
    def _detect_anthropic_models(self): pass
    
    def _show_model_selection_dialog(self, models, recommended=None, title="Select Model", info_text=None):
        """
        Show a dialog to select from available models.
        
        Args:
            models: List of available model names
            recommended: List of recommended model names
            title: Dialog title
            info_text: Optional info text to display
        """
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QListWidget, QPushButton, QLabel
        
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumWidth(500)
        dialog.setMinimumHeight(400)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #0B1220;
                color: #E5E7EB;
            }
            QLabel {
                color: #E5E7EB;
                font-size: 10pt;
            }
            QListWidget {
                background-color: #1E293B;
                color: #E5E7EB;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 8px;
                font-size: 10pt;
            }
            QListWidget::item {
                padding: 8px;
                border-radius: 4px;
            }
            QListWidget::item:hover {
                background-color: #334155;
            }
            QListWidget::item:selected {
                background-color: #0EA5E9;
                color: white;
            }
            QPushButton {
                background-color: #10B981;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 10pt;
                font-weight: bold;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
            QPushButton:pressed {
                background-color: #047857;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Title
        title_label = QLabel(f"Found {len(models)} available models:")
        title_label.setStyleSheet("font-size: 12pt; font-weight: bold; color: #00FFFF;")
        layout.addWidget(title_label)
        
        # Info text
        if info_text:
            info_label = QLabel(info_text)
            info_label.setStyleSheet("font-size: 9pt; color: #9CA3AF; margin-bottom: 8px;")
            layout.addWidget(info_label)
        
        # Model list
        model_list = QListWidget()
        
        # Add recommended models first
        if recommended:
            for model in recommended:
                if model in models:
                    model_list.addItem(f"⭐ {model} (Recommended)")
                    models.remove(model)
        
        # Add remaining models
        for model in sorted(models):
            model_list.addItem(model)
        
        layout.addWidget(model_list)
        
        # Select button
        select_button = QPushButton("Select Model")
        select_button.clicked.connect(dialog.accept)
        layout.addWidget(select_button)
        
        # Show dialog
        if dialog.exec_() == QDialog.Accepted:
            selected_items = model_list.selectedItems()
            if selected_items:
                selected_model = selected_items[0].text()
                # Remove "⭐ " and " (Recommended)" if present
                selected_model = selected_model.replace("⭐ ", "").replace(" (Recommended)", "")
                
                # Update model name input field
                if "model_name" in self.input_widgets:
                    self.input_widgets["model_name"].setText(selected_model)
                    self.config["model_name"] = selected_model
                    
                    QMessageBox.information(
                        self,
                        "Model Selected",
                        f"Selected model: {selected_model}\n\n"
                        "You can now proceed to validate and save your configuration."
                    )
    
    def validate_connectivity(self):
        """
        Test connection to configured backend using ModelRouter.
        
        Attempts to validate connectivity to the configured LLM backend.
        Shows success or error message to the user.
        
        Returns:
            bool: True if connectivity validated successfully, False otherwise
            
        """
        try:
            # Store API key temporarily if provided (for cloud APIs)
            api_key = self.config.get("api_key")
            if api_key:
                key_name = f"{self.config['backend']}_api_key"
                self.credential_manager.store_credential(key_name, api_key)
            
            # Create temporary ModelRouter with current configuration
            from eye.services.model_router import ModelRouter
            temp_router = ModelRouter(self.config, self.credential_manager)
            
            # Test connectivity
            if temp_router.validate_connectivity():
                QMessageBox.information(
                    self,
                    "Connectivity Validated",
                    f"Successfully connected to {self.config['backend']}!\n\n"
                    "Your configuration will now be saved."
                )
                return True
            else:
                QMessageBox.warning(
                    self,
                    "Connectivity Failed",
                    f"Failed to connect to {self.config['backend']}.\n\n"
                    "Please check your configuration and try again.\n\n"
                    "Troubleshooting:\n"
                    "- Verify the executable path or API endpoint is correct\n"
                    "- Ensure the service is running\n"
                    "- Check your API key if using cloud services"
                )
                return False
                
        except Exception as e:
            QMessageBox.critical(
                self,
                "Validation Error",
                f"An error occurred during connectivity validation:\n\n{str(e)}\n\n"
                "Please check your configuration and try again."
            )
            return False
    
    def _on_run_diagnostics(self):
        """Perform system diagnostics and show results."""
        from eye.services.diagnostics import SystemDiagnostics
        from PyQt5.QtWidgets import QProgressDialog
        
        progress = QProgressDialog("Running System Integrity Check...", None, 0, 0, self)
        progress.setWindowTitle("Diagnostics")
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        
        try:
            diagnostics = SystemDiagnostics(self.config_manager, self.credential_manager)
            results = diagnostics.run_full_check()
            progress.close()
            self._show_diagnostics_results(results)
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Diagnostics Error", f"Failed to run diagnostics: {str(e)}")

    def _show_diagnostics_results(self, results):
        """Show diagnostic results in a styled dialog."""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QLabel
        
        dialog = QDialog(self)
        dialog.setWindowTitle("System Integrity Report")
        dialog.setMinimumSize(600, 500)
        dialog.setStyleSheet("background-color: #0B1220; color: #E5E7EB;")
        
        layout = QVBoxLayout(dialog)
        
        title = QLabel("EYE System Diagnostics")
        title.setStyleSheet("font-size: 14pt; font-weight: bold; color: #00FFFF; margin-bottom: 10px;")
        layout.addWidget(title)
        
        report = QTextEdit()
        report.setReadOnly(True)
        report.setStyleSheet("""
            QTextEdit {
                background-color: #1E293B;
                color: #E5E7EB;
                border: 1px solid #334155;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10pt;
                padding: 10px;
            }
        """)
        
        # Build the report text
        text = "<h2>INTEGRITY CHECK RESULTS</h2><hr>"
        
        # UI
        ui = results["ui"]
        color = "#10B981" if ui["status"] == "PASS" else "#EF4444"
        text += f"<p><b style='color:{color}'>[{ui['status']}] {ui['name']}</b><br>{ui['message']}</p>"
        
        # SDKs
        text += "<h3>Backend SDKs</h3><ul>"
        for sdk in results["sdks"]:
            color = "#10B981" if sdk["status"] == "PASS" else "#F59E0B"
            text += f"<li><span style='color:{color}'>{sdk['name']}</span>: {sdk['message']}</li>"
        text += "</ul>"
        
        # Config
        cfg = results["config"]
        color = "#10B981" if cfg["status"] == "PASS" else "#F59E0B"
        text += f"<h3>Configuration</h3><p><b style='color:{color}'>[{cfg['status']}]</b> {cfg['message']}</p>"
        
        # Env
        env = results["environment"]
        text += f"<h3>Environment</h3><p>Python: {env['python_version']}<br>Platform: {env['platform']}<br>CWD: {env['cwd']}</p>"
        
        report.setHtml(text)
        layout.addWidget(report)
        
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("background-color: #334155; color: white; padding: 8px; border-radius: 4px;")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        
        dialog.exec_()

    def save_configuration(self, config):
        """
        Save configuration using ConfigManager and CredentialManager.
        
        Saves non-sensitive settings to eye_config.json and stores
        API keys securely in OS-native credential storage.
        
        Args:
            config: Configuration dictionary to save
            
        """
        try:
            # Extract API key if present (for cloud APIs)
            api_key = config.pop("api_key", None)
            
            # Add timestamp
            from datetime import datetime
            config["last_validated"] = datetime.now().isoformat()
            
            # Save non-sensitive config to JSON
            self.config_manager.save_config(config)
            
            # Save API key to secure storage if provided
            if api_key:
                key_name = f"{config['backend']}_api_key"
                self.credential_manager.store_credential(key_name, api_key)
            
            # Emit completion signal
            self.configuration_complete.emit(config)
            
            # Show success message
            QMessageBox.information(
                self,
                "Configuration Saved",
                "Your EYE configuration has been saved successfully!\n\n"
                "You can now start using the AI assistant."
            )
            
            # Close wizard
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Save Error",
                f"Failed to save configuration:\n\n{str(e)}\n\n"
                "Please try again or contact support."
            )
    
    def _on_next(self):
        """Handle Next button click."""
        current_index = self.pages.currentIndex()
        
        if current_index == 0:
            # Welcome -> Integration Selection
            self.show_integration_selection()
            
        elif current_index == 1:
            # Integration Selection -> Credential Input
            if self.config["integration_type"]:
                # Show warning dialog for cloud API selection
                if self.config["integration_type"] == "cloud_api":
                    warning_dialog = CloudAPIWarningDialog(self)
                    if warning_dialog.exec_() == QDialog.Accepted:
                        # User acknowledged warning, proceed to credential input
                        self.show_credential_input(self.config["integration_type"])
                    # If rejected, stay on current page
                else:
                    # For local integrations, proceed directly
                    self.show_credential_input(self.config["integration_type"])
            
        elif current_index == 2:
            # Credential Input -> Validate & Save
            if self.validate_connectivity():
                self.save_configuration(self.config.copy())
    
    def _on_back(self):
        """Handle Back button click."""
        current_index = self.pages.currentIndex()
        
        if current_index > 0:
            self.pages.setCurrentIndex(current_index - 1)
            
            # Update navigation buttons
            if current_index - 1 == 0:
                self.back_button.setEnabled(False)
            
            self.next_button.setEnabled(True)
            self.next_button.setText("Next")
