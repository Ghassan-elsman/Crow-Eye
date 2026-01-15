"""
Wings Creator Main Window
Main GUI for creating and editing Wings.
"""

import os
import json
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QSpinBox,
    QFileDialog, QMessageBox, QScrollArea, QGroupBox,
    QMenuBar, QMenu, QAction, QStatusBar, QDialog, QDialogButtonBox,
    QInputDialog, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QCheckBox, QDoubleSpinBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from ...gui.ui_styling import CorrelationEngineStyles


from ..core.wing_model import Wing, FeatherSpec, CorrelationRules
from ..core.artifact_detector import ArtifactDetector
from ..core.wing_validator import WingValidator
from .feather_widget import FeatherWidget
from .json_viewer import JsonViewerDialog
from .anchor_priority_widget import AnchorPriorityWidget

# Import config system
try:
    from ...config import ConfigManager, WingConfig
    from ...config.wing_config import WingFeatherReference
    CONFIG_AVAILABLE = True
except ImportError:
    CONFIG_AVAILABLE = False
    print("Warning: Config system not available")


class WingsCreatorWindow(QMainWindow):
    """Main window for Wings Creator"""
    
    def __init__(self):
        super().__init__()
        self.wing = Wing()
        self.feather_widgets = []
        self.current_config = None  # Store current wing config
        self.config_manager = ConfigManager() if CONFIG_AVAILABLE else None
        self.case_directory = None  # Store case directory for feather path resolution
        self.init_ui()
        self.load_stylesheet()
    
    def set_case_directory(self, case_directory: str):
        """Set the case directory for feather path resolution"""
        self.case_directory = case_directory
        print(f"[Wings Creator] Case directory set: {case_directory}")
    
    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("Crow-Eye Wings Creator")
        self.setGeometry(100, 100, 1400, 900)
        
        # Create central widget with scroll area
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Create header
        header_layout = self.create_header()
        main_layout.addLayout(header_layout)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.North)
        
        # Create tabs
        self.create_basic_tab()
        self.create_scoring_tab()
        self.create_semantic_mappings_tab()
        
        main_layout.addWidget(self.tab_widget)
        
        # Create menu bar
        self.create_menu_bar()
        
        # Create status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready to create a new Wing")
    
    def create_header(self):
        """Create header with title and action buttons"""
        header_layout = QHBoxLayout()
        
        # Title
        title_label = QLabel("WINGS CREATOR")
        title_font = QFont("Consolas", 12, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignLeft)
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        # Action buttons
        self.view_json_btn = QPushButton("View JSON")
        self.view_json_btn.clicked.connect(self.view_json)
        header_layout.addWidget(self.view_json_btn)
        
        self.save_btn = QPushButton("Save Wing")
        CorrelationEngineStyles.add_button_icon(self.save_btn, "save", "#FFFFFF")
        self.save_btn.clicked.connect(self.save_wing)
        header_layout.addWidget(self.save_btn)
        
        self.test_btn = QPushButton("Test Wing")
        CorrelationEngineStyles.add_button_icon(self.test_btn, "execute", "#FFFFFF")
        self.test_btn.clicked.connect(self.test_wing)
        header_layout.addWidget(self.test_btn)
        
        return header_layout
    
    def create_basic_tab(self):
        """Create the basic configuration tab"""
        # Create scroll area for form
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        form_widget = QWidget()
        form_layout = QVBoxLayout(form_widget)
        form_layout.setSpacing(10)
        
        # Wing basic info
        form_layout.addWidget(self.create_basic_info_section())
        
        # Feathers section
        form_layout.addWidget(self.create_feathers_section())
        
        # Correlation rules section
        form_layout.addWidget(self.create_correlation_rules_section())
        
        # Wing logic section
        form_layout.addWidget(self.create_wing_logic_section())
        
        form_layout.addStretch()
        
        scroll.setWidget(form_widget)
        self.tab_widget.addTab(scroll, "Basic Configuration")
    
    def create_scoring_tab(self):
        """Create the scoring configuration tab"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        form_widget = QWidget()
        form_layout = QVBoxLayout(form_widget)
        form_layout.setSpacing(10)
        
        # Weighted scoring section
        form_layout.addWidget(self.create_weighted_scoring_section())
        
        # Score interpretation section
        form_layout.addWidget(self.create_score_interpretation_section())
        
        form_layout.addStretch()
        
        scroll.setWidget(form_widget)
        self.tab_widget.addTab(scroll, "Scoring")
    
    def create_basic_info_section(self):
        """Create basic wing information section"""
        group = QGroupBox("Wing Information")
        layout = QVBoxLayout()
        
        # Wing Name
        name_layout = QHBoxLayout()
        name_label = QLabel("Wing Name:")
        name_label.setMinimumWidth(120)
        self.wing_name_input = QLineEdit()
        self.wing_name_input.setPlaceholderText("Enter wing name...")
        self.wing_name_input.textChanged.connect(self.on_wing_name_changed)
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.wing_name_input)
        layout.addLayout(name_layout)
        
        # Wing ID (read-only)
        id_layout = QHBoxLayout()
        id_label = QLabel("Wing ID:")
        id_label.setMinimumWidth(120)
        self.wing_id_label = QLabel(self.wing.wing_id)
        self.wing_id_label.setStyleSheet("color: #00d9ff; font-family: 'Consolas'; font-size: 8pt;")
        id_layout.addWidget(id_label)
        id_layout.addWidget(self.wing_id_label)
        id_layout.addStretch()
        layout.addLayout(id_layout)
        
        # Description
        desc_label = QLabel("Description:")
        layout.addWidget(desc_label)
        self.description_input = QTextEdit()
        self.description_input.setPlaceholderText("Describe what this wing does...")
        self.description_input.setMaximumHeight(60)
        self.description_input.textChanged.connect(self.on_description_changed)
        layout.addWidget(self.description_input)
        
        # Author
        author_layout = QHBoxLayout()
        author_label = QLabel("Author:")
        author_label.setMinimumWidth(120)
        self.author_input = QLineEdit()
        self.author_input.setPlaceholderText("Your name...")
        self.author_input.textChanged.connect(self.on_author_changed)
        author_layout.addWidget(author_label)
        author_layout.addWidget(self.author_input)
        layout.addLayout(author_layout)
        
        group.setLayout(layout)
        return group
    
    def create_feathers_section(self):
        """Create feathers configuration section"""
        group = QGroupBox("Feather Selection (Minimum 1 Required)")
        layout = QVBoxLayout()
        
        # Container for feather widgets
        self.feathers_container = QVBoxLayout()
        layout.addLayout(self.feathers_container)
        
        # Add feather button
        add_btn = QPushButton("+ Add Feather")
        add_btn.clicked.connect(self.add_feather)
        layout.addWidget(add_btn)
        
        group.setLayout(layout)
        return group
    
    def create_correlation_rules_section(self):
        """Create correlation rules section"""
        group = QGroupBox("Correlation Settings")
        layout = QVBoxLayout()
        
        # Target Application Filter (Wing-level)
        filter_label = QLabel("Target Application (applies to ALL feathers):")
        filter_label.setStyleSheet("font-weight: bold; color: #00d9ff;")
        layout.addWidget(filter_label)
        
        filter_help = QLabel(
            "Specify which application/file to correlate across all artifacts. "
            "Leave empty or use '*' to correlate all applications."
        )
        filter_help.setWordWrap(True)
        filter_help.setStyleSheet("color: #888; font-size: 8pt; margin-bottom: 5px;")
        layout.addWidget(filter_help)
        
        # Apply to selection
        apply_layout = QHBoxLayout()
        apply_label = QLabel("Apply to:")
        apply_label.setMinimumWidth(120)
        
        from PyQt5.QtWidgets import QRadioButton, QButtonGroup
        self.apply_group = QButtonGroup()
        
        self.apply_all_radio = QRadioButton("All Applications")
        self.apply_all_radio.setChecked(True)
        self.apply_all_radio.toggled.connect(self.on_apply_to_changed)
        self.apply_group.addButton(self.apply_all_radio)
        
        self.apply_specific_radio = QRadioButton("Specific Application")
        self.apply_specific_radio.toggled.connect(self.on_apply_to_changed)
        self.apply_group.addButton(self.apply_specific_radio)
        
        apply_layout.addWidget(apply_label)
        apply_layout.addWidget(self.apply_all_radio)
        apply_layout.addWidget(self.apply_specific_radio)
        apply_layout.addStretch()
        layout.addLayout(apply_layout)
        
        # Target application input
        app_layout = QHBoxLayout()
        app_label = QLabel("Application Name:")
        app_label.setMinimumWidth(120)
        self.target_app_input = QLineEdit()
        self.target_app_input.setPlaceholderText("e.g., chrome.exe, notepad.exe, powershell.exe")
        self.target_app_input.setEnabled(False)
        self.target_app_input.textChanged.connect(self.on_target_app_changed)
        app_layout.addWidget(app_label)
        app_layout.addWidget(self.target_app_input)
        layout.addLayout(app_layout)
        
        # Optional path filter
        path_layout = QHBoxLayout()
        path_label = QLabel("Path Filter (optional):")
        path_label.setMinimumWidth(120)
        self.target_path_input = QLineEdit()
        self.target_path_input.setPlaceholderText("e.g., C:\\Windows\\System32\\*")
        self.target_path_input.textChanged.connect(self.on_target_path_changed)
        path_layout.addWidget(path_label)
        path_layout.addWidget(self.target_path_input)
        layout.addLayout(path_layout)
        
        # Event ID filter (for Logs artifacts) - initially hidden
        self.event_id_widget = QWidget()
        event_layout = QHBoxLayout(self.event_id_widget)
        event_layout.setContentsMargins(0, 0, 0, 0)
        event_label = QLabel("Event ID (for Logs):")
        event_label.setMinimumWidth(120)
        self.target_event_input = QLineEdit()
        self.target_event_input.setPlaceholderText("e.g., 4688, 4624, or 4688,4624,4625 for multiple")
        self.target_event_input.textChanged.connect(self.on_target_event_changed)
        event_help = QLabel("(comma-separated)")
        event_help.setStyleSheet("color: #888; font-size: 8pt;")
        event_layout.addWidget(event_label)
        event_layout.addWidget(self.target_event_input)
        event_layout.addWidget(event_help)
        layout.addWidget(self.event_id_widget)
        self.event_id_widget.setVisible(False)  # Hidden by default
        
        # Separator
        from PyQt5.QtWidgets import QFrame
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)
        
        # Time window
        time_layout = QHBoxLayout()
        time_label = QLabel("Time Window:")
        time_label.setMinimumWidth(120)
        self.time_window_spin = QSpinBox()
        self.time_window_spin.setMinimum(1)
        self.time_window_spin.setMaximum(1440)
        self.time_window_spin.setValue(180)  # Default: 3 hours for better correlation accuracy
        self.time_window_spin.setSuffix(" minutes")
        self.time_window_spin.valueChanged.connect(self.on_time_window_changed)
        time_help = QLabel("(±tolerance for matching)")
        time_layout.addWidget(time_label)
        time_layout.addWidget(self.time_window_spin)
        time_layout.addWidget(time_help)
        time_layout.addStretch()
        layout.addLayout(time_layout)
        
        # Anchor priority
        priority_label = QLabel("Anchor Priority (drag to reorder):")
        layout.addWidget(priority_label)
        
        self.anchor_priority_widget = AnchorPriorityWidget()
        self.anchor_priority_widget.priority_changed.connect(self.on_anchor_priority_changed)
        layout.addWidget(self.anchor_priority_widget)
        
        group.setLayout(layout)
        return group
    
    def create_wing_logic_section(self):
        """Create wing logic section"""
        group = QGroupBox("Wing Logic")
        layout = QVBoxLayout()
        
        # Proves
        proves_layout = QHBoxLayout()
        proves_label = QLabel("This Wing proves:")
        proves_label.setMinimumWidth(120)
        self.proves_input = QLineEdit()
        self.proves_input.setPlaceholderText("What does this wing prove?")
        self.proves_input.textChanged.connect(self.on_proves_changed)
        proves_layout.addWidget(proves_label)
        proves_layout.addWidget(self.proves_input)
        layout.addLayout(proves_layout)
        
        # Minimum matches
        matches_layout = QHBoxLayout()
        matches_label = QLabel("Minimum matches required:")
        matches_label.setMinimumWidth(120)
        self.min_matches_spin = QSpinBox()
        self.min_matches_spin.setMinimum(1)
        self.min_matches_spin.setMaximum(10)
        self.min_matches_spin.setValue(1)
        self.min_matches_spin.setSuffix(" feathers")
        self.min_matches_spin.valueChanged.connect(self.on_min_matches_changed)
        matches_layout.addWidget(matches_label)
        matches_layout.addWidget(self.min_matches_spin)
        matches_layout.addStretch()
        layout.addLayout(matches_layout)
        
        group.setLayout(layout)
        return group
    
    def create_weighted_scoring_section(self):
        """Create weighted scoring configuration section"""
        group = QGroupBox("Weighted Scoring Configuration")
        layout = QVBoxLayout()
        
        # Enable weighted scoring checkbox
        self.enable_weighted_scoring_cb = QCheckBox("Enable Weighted Scoring")
        self.enable_weighted_scoring_cb.setStyleSheet("font-weight: bold; color: #00d9ff;")
        self.enable_weighted_scoring_cb.stateChanged.connect(self.on_weighted_scoring_toggled)
        layout.addWidget(self.enable_weighted_scoring_cb)
        
        # Help text
        help_text = QLabel(
            "Weighted scoring calculates match confidence based on the forensic strength of each Feather. "
            "Assign weights (0.0-1.0) to each Feather based on its evidential value."
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #888; font-size: 9pt; margin-bottom: 10px;")
        layout.addWidget(help_text)
        
        # Feather weights table
        table_label = QLabel("Feather Weights:")
        table_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(table_label)
        
        self.weights_table = QTableWidget()
        self.weights_table.setColumnCount(5)
        self.weights_table.setHorizontalHeaderLabels([
            "Feather", "Weight (0.0-1.0)", "Tier", "Tier Name", "Artifact Type"
        ])
        self.weights_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.weights_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.weights_table.setMinimumHeight(200)
        self.weights_table.setEnabled(False)  # Disabled until weighted scoring is enabled
        self.weights_table.itemChanged.connect(self.on_weight_changed)
        layout.addWidget(self.weights_table)
        
        # Total weight display
        total_layout = QHBoxLayout()
        total_label = QLabel("Total Weight:")
        total_label.setStyleSheet("font-weight: bold;")
        self.total_weight_label = QLabel("0.00")
        self.total_weight_label.setStyleSheet("color: #00d9ff; font-size: 11pt; font-weight: bold;")
        total_layout.addWidget(total_label)
        total_layout.addWidget(self.total_weight_label)
        total_layout.addStretch()
        layout.addLayout(total_layout)
        
        # Warning label
        self.weight_warning_label = QLabel("")
        self.weight_warning_label.setStyleSheet("color: #ff6b6b; font-weight: bold;")
        self.weight_warning_label.setVisible(False)
        layout.addWidget(self.weight_warning_label)
        
        group.setLayout(layout)
        return group
    
    def create_score_interpretation_section(self):
        """Create score interpretation thresholds section"""
        group = QGroupBox("Score Interpretation Thresholds")
        layout = QVBoxLayout()
        
        # Help text
        help_text = QLabel(
            "Define how match scores should be interpreted. Scores are calculated as the sum of weights "
            "from matched Feathers. Set minimum thresholds for each interpretation level."
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #888; font-size: 9pt; margin-bottom: 10px;")
        layout.addWidget(help_text)
        
        # Interpretation table
        self.interpretation_table = QTableWidget()
        self.interpretation_table.setColumnCount(3)
        self.interpretation_table.setHorizontalHeaderLabels([
            "Level", "Label", "Minimum Score"
        ])
        self.interpretation_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.interpretation_table.setMinimumHeight(150)
        self.interpretation_table.setEnabled(False)  # Disabled until weighted scoring is enabled
        self.interpretation_table.itemChanged.connect(self.on_interpretation_changed)
        
        # Add default interpretation levels
        self.interpretation_levels = [
            {"level": "confirmed", "label": "Confirmed Evidence", "min": 0.70},
            {"level": "probable", "label": "Probable Match", "min": 0.40},
            {"level": "weak", "label": "Weak / Partial Evidence", "min": 0.20},
            {"level": "insufficient", "label": "Insufficient Evidence", "min": 0.0}
        ]
        
        layout.addWidget(self.interpretation_table)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.add_level_btn = QPushButton("+ Add Level")
        self.add_level_btn.clicked.connect(self.add_interpretation_level)
        self.add_level_btn.setEnabled(False)
        self.add_level_btn.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
            QPushButton:disabled {
                background-color: #374151;
                color: #6B7280;
            }
        """)
        
        self.remove_level_btn = QPushButton("− Remove Level")
        self.remove_level_btn.clicked.connect(self.remove_interpretation_level)
        self.remove_level_btn.setEnabled(False)
        self.remove_level_btn.setStyleSheet("""
            QPushButton {
                background-color: #EF4444;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #DC2626;
            }
            QPushButton:disabled {
                background-color: #374151;
                color: #6B7280;
            }
        """)
        
        self.reset_levels_btn = QPushButton("↺ Reset to Defaults")
        self.reset_levels_btn.clicked.connect(self.reset_interpretation_levels)
        self.reset_levels_btn.setEnabled(False)
        self.reset_levels_btn.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
            QPushButton:disabled {
                background-color: #374151;
                color: #6B7280;
            }
        """)
        
        button_layout.addWidget(self.add_level_btn)
        button_layout.addWidget(self.remove_level_btn)
        button_layout.addWidget(self.reset_levels_btn)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        
        group.setLayout(layout)
        return group
    
    def create_semantic_mappings_tab(self):
        """Create the semantic mappings configuration tab"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        form_widget = QWidget()
        form_layout = QVBoxLayout(form_widget)
        form_layout.setSpacing(10)
        
        # Semantic mappings section (basic)
        form_layout.addWidget(self.create_semantic_mappings_section())
        
        # Advanced semantic rules section
        form_layout.addWidget(self.create_advanced_semantic_rules_section())
        
        form_layout.addStretch()
        
        scroll.setWidget(form_widget)
        self.tab_widget.addTab(scroll, "Semantic Mappings")
    
    def create_semantic_mappings_section(self):
        """Create semantic mappings configuration section"""
        group = QGroupBox("Wing-Specific Semantic Mappings")
        layout = QVBoxLayout()
        
        # Help text
        help_text = QLabel(
            "Define semantic mappings specific to this Wing. These mappings will override global mappings "
            "when displaying correlation results for this Wing. Use semantic mappings to translate technical "
            "values (like Event IDs) into human-readable meanings."
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #888; font-size: 9pt; margin-bottom: 10px;")
        layout.addWidget(help_text)
        
        # Semantic mappings table
        table_label = QLabel("Semantic Mappings:")
        table_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(table_label)
        
        self.semantic_mappings_table = QTableWidget()
        self.semantic_mappings_table.setColumnCount(5)
        self.semantic_mappings_table.setHorizontalHeaderLabels([
            "Source", "Field", "Technical Value", "Semantic Value", "Description"
        ])
        self.semantic_mappings_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.semantic_mappings_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.semantic_mappings_table.setMinimumHeight(300)
        self.semantic_mappings_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.semantic_mappings_table)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.load_global_mappings_btn = QPushButton("📥 Load Global Mappings")
        self.load_global_mappings_btn.setToolTip("Load semantic mappings from global configuration")
        self.load_global_mappings_btn.clicked.connect(self.load_global_semantic_mappings)
        self.load_global_mappings_btn.setStyleSheet("background-color: #10B981;")
        
        self.add_mapping_btn = QPushButton("Add Mapping")
        self.add_mapping_btn.clicked.connect(self.add_semantic_mapping)
        
        self.edit_mapping_btn = QPushButton("Edit Mapping")
        self.edit_mapping_btn.clicked.connect(self.edit_semantic_mapping)
        
        self.delete_mapping_btn = QPushButton("Delete Mapping")
        self.delete_mapping_btn.clicked.connect(self.delete_semantic_mapping)
        
        button_layout.addWidget(self.load_global_mappings_btn)
        button_layout.addWidget(self.add_mapping_btn)
        button_layout.addWidget(self.edit_mapping_btn)
        button_layout.addWidget(self.delete_mapping_btn)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        
        # Info label
        info_label = QLabel(
            "💡 Tip: Wing-specific mappings take priority over global mappings. "
            "Global semantic mappings are automatically loaded. "
            "You can add Wing-specific mappings or edit existing ones."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #00d9ff; font-size: 8pt; margin-top: 10px;")
        layout.addWidget(info_label)
        
        # Initialize wing_semantic_mappings list and load global mappings by default
        self.wing_semantic_mappings = []
        self.load_global_semantic_mappings_silently()
        
        group.setLayout(layout)
        return group
    
    def create_advanced_semantic_rules_section(self):
        """Create advanced semantic rules configuration section with AND/OR logic and wildcards"""
        from PyQt5.QtWidgets import QListWidget, QListWidgetItem
        
        group = QGroupBox("Advanced Semantic Rules")
        layout = QVBoxLayout()
        
        # Help text
        help_text = QLabel(
            "Define advanced semantic rules with multi-value conditions, AND/OR logic, and wildcard (*) support. "
            "These rules allow complex matching patterns for identity-level semantic classification."
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #888; font-size: 9pt; margin-bottom: 10px;")
        layout.addWidget(help_text)
        
        # Semantic rules list
        rules_label = QLabel("Wing Semantic Rules:")
        rules_label.setStyleSheet("font-weight: bold; color: #00d9ff;")
        layout.addWidget(rules_label)
        
        self.semantic_rules_list = QListWidget()
        self.semantic_rules_list.setMaximumHeight(150)
        self.semantic_rules_list.setToolTip("Wing-specific semantic rules with AND/OR logic and wildcard support")
        self.semantic_rules_list.itemSelectionChanged.connect(self._on_semantic_rule_selection_changed)
        self.semantic_rules_list.itemDoubleClicked.connect(self._edit_semantic_rule)
        layout.addWidget(self.semantic_rules_list)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.add_semantic_rule_btn = QPushButton("+ Add Rule")
        self.add_semantic_rule_btn.clicked.connect(self._add_semantic_rule)
        self.add_semantic_rule_btn.setToolTip("Add a new advanced semantic rule")
        button_layout.addWidget(self.add_semantic_rule_btn)
        
        self.edit_semantic_rule_btn = QPushButton("Edit")
        self.edit_semantic_rule_btn.clicked.connect(self._edit_semantic_rule)
        self.edit_semantic_rule_btn.setEnabled(False)
        self.edit_semantic_rule_btn.setToolTip("Edit the selected semantic rule")
        button_layout.addWidget(self.edit_semantic_rule_btn)
        
        self.remove_semantic_rule_btn = QPushButton("Remove")
        self.remove_semantic_rule_btn.clicked.connect(self._remove_semantic_rule)
        self.remove_semantic_rule_btn.setEnabled(False)
        self.remove_semantic_rule_btn.setToolTip("Remove the selected semantic rule")
        button_layout.addWidget(self.remove_semantic_rule_btn)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        # Info label
        info_label = QLabel(
            "💡 Advanced rules support: AND/OR logic operators, wildcard (*) matching, "
            "and multi-value conditions. Wing rules take priority over global rules."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #00d9ff; font-size: 8pt; margin-top: 10px;")
        layout.addWidget(info_label)
        
        # Initialize wing_semantic_rules list
        self.wing_semantic_rules = []
        
        group.setLayout(layout)
        return group
    
    def _on_semantic_rule_selection_changed(self):
        """Handle semantic rule selection change"""
        has_selection = self.semantic_rules_list.currentItem() is not None
        self.edit_semantic_rule_btn.setEnabled(has_selection)
        self.remove_semantic_rule_btn.setEnabled(has_selection)
    
    def _add_semantic_rule(self):
        """Add a new advanced semantic rule to the wing"""
        try:
            from .semantic_mapping_dialog import SemanticMappingDialog
            from PyQt5.QtWidgets import QListWidgetItem
            
            # Get available feathers from the wing
            available_feathers = []
            for feather in self.wing.feathers:
                available_feathers.append(feather.feather_id)
            
            # Open the semantic mapping dialog in advanced mode
            dialog = SemanticMappingDialog(
                parent=self,
                mapping=None,
                scope='wing',
                wing_id=self.wing.wing_id,
                available_feathers=available_feathers,
                mode='advanced'
            )
            
            if dialog.exec_():
                rule_data = dialog.get_rule_data()
                if rule_data:
                    # Add to list
                    rule_name = rule_data.get('name', 'Unnamed Rule')
                    semantic_value = rule_data.get('semantic_value', '')
                    item = QListWidgetItem(f"{rule_name} → {semantic_value}")
                    item.setData(Qt.UserRole, rule_data)
                    item.setToolTip(self._format_rule_tooltip(rule_data))
                    self.semantic_rules_list.addItem(item)
                    
                    # Update wing semantic rules
                    self._update_wing_semantic_rules()
                    
        except ImportError as e:
            QMessageBox.warning(
                self,
                "Import Error",
                f"Could not import SemanticMappingDialog: {e}\n\nPlease ensure the semantic mapping module is available."
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to add semantic rule: {e}"
            )
    
    def _edit_semantic_rule(self):
        """Edit the selected semantic rule"""
        current_item = self.semantic_rules_list.currentItem()
        if not current_item:
            return
        
        try:
            from .semantic_mapping_dialog import SemanticMappingDialog
            
            rule_data = current_item.data(Qt.UserRole)
            
            # Get available feathers from the wing
            available_feathers = []
            for feather in self.wing.feathers:
                available_feathers.append(feather.feather_id)
            
            # Open the semantic mapping dialog with existing rule
            dialog = SemanticMappingDialog(
                parent=self,
                mapping=rule_data,
                scope='wing',
                wing_id=self.wing.wing_id,
                available_feathers=available_feathers,
                mode='advanced'
            )
            
            if dialog.exec_():
                updated_rule = dialog.get_rule_data()
                if updated_rule:
                    # Update list item
                    rule_name = updated_rule.get('name', 'Unnamed Rule')
                    semantic_value = updated_rule.get('semantic_value', '')
                    current_item.setText(f"{rule_name} → {semantic_value}")
                    current_item.setData(Qt.UserRole, updated_rule)
                    current_item.setToolTip(self._format_rule_tooltip(updated_rule))
                    
                    # Update wing semantic rules
                    self._update_wing_semantic_rules()
                    
        except ImportError as e:
            QMessageBox.warning(
                self,
                "Import Error",
                f"Could not import SemanticMappingDialog: {e}"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to edit semantic rule: {e}"
            )
    
    def _remove_semantic_rule(self):
        """Remove the selected semantic rule"""
        current_item = self.semantic_rules_list.currentItem()
        if current_item:
            self.semantic_rules_list.takeItem(self.semantic_rules_list.row(current_item))
            self._update_wing_semantic_rules()
    
    def _format_rule_tooltip(self, rule_data: dict) -> str:
        """Format a tooltip for a semantic rule"""
        lines = [
            f"Name: {rule_data.get('name', 'Unnamed')}",
            f"Semantic Value: {rule_data.get('semantic_value', '')}",
            f"Logic: {rule_data.get('logic_operator', 'AND')}",
            f"Conditions: {len(rule_data.get('conditions', []))}"
        ]
        
        conditions = rule_data.get('conditions', [])
        if conditions:
            lines.append("")
            lines.append("Conditions:")
            for cond in conditions[:3]:  # Show first 3 conditions
                feather = cond.get('feather_id', '')
                field = cond.get('field_name', '')
                op = cond.get('operator', 'equals')
                value = cond.get('value', '')
                lines.append(f"  • {feather}.{field} {op} '{value}'")
            if len(conditions) > 3:
                lines.append(f"  ... and {len(conditions) - 3} more")
        
        return "\n".join(lines)
    
    def _update_wing_semantic_rules(self):
        """Update the wing's semantic_rules from the list widget"""
        rules = []
        for i in range(self.semantic_rules_list.count()):
            item = self.semantic_rules_list.item(i)
            rule_data = item.data(Qt.UserRole)
            if rule_data:
                rules.append(rule_data)
        
        self.wing_semantic_rules = rules
        self.wing.semantic_rules = rules
    
    def _load_semantic_rules_to_ui(self):
        """Load semantic rules from wing to UI"""
        from PyQt5.QtWidgets import QListWidgetItem
        
        self.semantic_rules_list.clear()
        self.wing_semantic_rules = self.wing.semantic_rules if hasattr(self.wing, 'semantic_rules') else []
        
        print(f"[Wing Creator] _load_semantic_rules_to_ui: Loading {len(self.wing_semantic_rules)} semantic rules")
        
        for rule_data in self.wing_semantic_rules:
            rule_name = rule_data.get('name', 'Unnamed Rule')
            semantic_value = rule_data.get('semantic_value', '')
            logic_op = rule_data.get('logic_operator', 'AND')
            print(f"[Wing Creator]   - Rule: {rule_name} ({logic_op}) → {semantic_value}")
            item = QListWidgetItem(f"{rule_name} → {semantic_value}")
            item.setData(Qt.UserRole, rule_data)
            item.setToolTip(self._format_rule_tooltip(rule_data))
            self.semantic_rules_list.addItem(item)
    
    def _load_scoring_to_ui(self):
        """Load weighted scoring configuration from wing to UI"""
        # Load weighted scoring enabled state
        use_weighted_scoring = getattr(self.wing, 'use_weighted_scoring', True)
        self.enable_weighted_scoring_cb.setChecked(use_weighted_scoring)
        
        # Load feather weights from feathers - use update_weights_table which handles this properly
        if use_weighted_scoring:
            self.weights_table.setEnabled(True)
            self.interpretation_table.setEnabled(True)
            self.add_level_btn.setEnabled(True)
            self.remove_level_btn.setEnabled(True)
            self.reset_levels_btn.setEnabled(True)
            self.update_weights_table()
        else:
            self.weights_table.setEnabled(False)
            self.interpretation_table.setEnabled(False)
            self.add_level_btn.setEnabled(False)
            self.remove_level_btn.setEnabled(False)
            self.reset_levels_btn.setEnabled(False)
        
        # Load score interpretation thresholds
        scoring = getattr(self.wing, 'scoring', {})
        if scoring and 'score_interpretation' in scoring:
            self.interpretation_levels = []
            for level_key, level_data in scoring['score_interpretation'].items():
                self.interpretation_levels.append({
                    'level': level_key,
                    'label': level_data.get('label', level_key),
                    'min': level_data.get('min', 0.0)
                })
            # Sort by min score descending for proper display
            self.interpretation_levels.sort(key=lambda x: x['min'], reverse=True)
            self.update_interpretation_table()
        else:
            # Load default interpretation levels
            self.interpretation_levels = [
                {'level': 'confirmed', 'label': 'Confirmed Evidence', 'min': 0.70},
                {'level': 'probable', 'label': 'Probable Match', 'min': 0.40},
                {'level': 'weak', 'label': 'Weak / Partial Evidence', 'min': 0.20},
                {'level': 'insufficient', 'label': 'Insufficient Evidence', 'min': 0.0}
            ]
            self.update_interpretation_table()

    def create_menu_bar(self):
        """Create menu bar"""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("File")
        
        new_action = QAction("New Wing", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self.new_wing)
        file_menu.addAction(new_action)
        
        open_action = QAction("Open Wing", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_wing)
        file_menu.addAction(open_action)
        
        save_action = QAction("Save Wing", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_wing)
        file_menu.addAction(save_action)
        
        save_as_action = QAction("Save Wing As...", self)
        save_as_action.setShortcut("Ctrl+Shift+S")
        save_as_action.triggered.connect(self.save_wing_as)
        file_menu.addAction(save_as_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Config menu
        if CONFIG_AVAILABLE:
            config_menu = menubar.addMenu("Config")
            
            save_config_action = QAction("Save as Configuration...", self)
            save_config_action.triggered.connect(self.save_wing_config)
            config_menu.addAction(save_config_action)
            
            load_config_action = QAction("Load Configuration...", self)
            load_config_action.triggered.connect(self.load_wing_config)
            config_menu.addAction(load_config_action)
            
            config_menu.addSeparator()
            
            list_configs_action = QAction("List Configurations", self)
            list_configs_action.triggered.connect(self.list_wing_configs)
            config_menu.addAction(list_configs_action)
        
        # Help menu
        help_menu = menubar.addMenu("Help")
        
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def load_stylesheet(self):
        """Load Wings Creator dark theme stylesheet"""
        style_path = os.path.join(
            os.path.dirname(__file__),
            "wings_styles.qss"
        )
        try:
            with open(style_path, 'r') as f:
                stylesheet = f.read()
                self.setStyleSheet(stylesheet)
        except FileNotFoundError:
            print(f"Warning: Stylesheet not found at {style_path}")
            # Fallback to basic dark theme with proper table header styling
            self.setStyleSheet("""
                QMainWindow, QWidget {
                    background-color: #0B1220;
                    color: #E5E7EB;
                }
                QGroupBox {
                    background-color: #1a1f2e;
                    border: 2px solid #334155;
                    border-radius: 8px;
                    color: #00d9ff;
                    font-weight: bold;
                    padding-top: 15px;
                    margin-top: 10px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    subcontrol-position: top left;
                    padding: 5px 10px;
                    color: #00d9ff;
                }
                QPushButton {
                    background-color: #3B82F6;
                    color: white;
                    border-radius: 6px;
                    padding: 10px 20px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #2563EB;
                }
                QPushButton:pressed {
                    background-color: #1E40AF;
                }
                QTableWidget {
                    background-color: #1a1f2e;
                    alternate-background-color: #151a27;
                    gridline-color: #334155;
                    border: 1px solid #334155;
                    border-radius: 4px;
                }
                QTableWidget::item {
                    padding: 5px;
                    color: #E5E7EB;
                }
                QTableWidget::item:selected {
                    background-color: #3B82F6;
                    color: white;
                }
                QHeaderView::section {
                    background-color: #1E293B;
                    color: #00d9ff;
                    padding: 8px;
                    border: 1px solid #334155;
                    font-weight: bold;
                    font-size: 9pt;
                }
                QHeaderView::section:horizontal {
                    border-top: none;
                }
                QHeaderView::section:vertical {
                    border-left: none;
                }
                QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox {
                    background-color: #1a1f2e;
                    border: 1px solid #334155;
                    border-radius: 4px;
                    padding: 5px;
                    color: #E5E7EB;
                }
                QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                    border: 1px solid #3B82F6;
                }
                QCheckBox {
                    color: #E5E7EB;
                    spacing: 5px;
                }
                QCheckBox::indicator {
                    width: 18px;
                    height: 18px;
                    border: 2px solid #334155;
                    border-radius: 3px;
                    background-color: #1a1f2e;
                }
                QCheckBox::indicator:checked {
                    background-color: #3B82F6;
                    border-color: #3B82F6;
                }
                QTabWidget::pane {
                    border: 1px solid #334155;
                    background-color: #0B1220;
                    border-radius: 4px;
                }
                QTabBar::tab {
                    background-color: #1a1f2e;
                    color: #94A3B8;
                    padding: 10px 20px;
                    margin-right: 2px;
                    border-top-left-radius: 4px;
                    border-top-right-radius: 4px;
                }
                QTabBar::tab:selected {
                    background-color: #3B82F6;
                    color: white;
                }
                QTabBar::tab:hover:!selected {
                    background-color: #2563EB;
                    color: white;
                }
            """)
    
    # Event handlers
    def on_wing_name_changed(self, text):
        """Handle wing name change"""
        self.wing.wing_name = text
        self.update_status()
    
    def on_description_changed(self):
        """Handle description change"""
        self.wing.description = self.description_input.toPlainText()
    
    def on_author_changed(self, text):
        """Handle author change"""
        self.wing.author = text
    
    def on_proves_changed(self, text):
        """Handle proves change"""
        self.wing.proves = text
    
    def on_time_window_changed(self, value):
        """Handle time window change"""
        self.wing.correlation_rules.time_window_minutes = value
    
    def on_min_matches_changed(self, value):
        """Handle minimum matches change"""
        self.wing.correlation_rules.minimum_matches = value
    
    def on_anchor_priority_changed(self, priority):
        """Handle anchor priority change"""
        self.wing.correlation_rules.anchor_priority = priority
    
    def on_apply_to_changed(self):
        """Handle apply to radio button change"""
        if self.apply_specific_radio.isChecked():
            self.wing.correlation_rules.apply_to = "specific"
            self.target_app_input.setEnabled(True)
        else:
            self.wing.correlation_rules.apply_to = "all"
            self.target_app_input.setEnabled(False)
            self.target_app_input.clear()
    
    def on_target_app_changed(self, text):
        """Handle target application change"""
        self.wing.correlation_rules.target_application = text
    
    def on_target_path_changed(self, text):
        """Handle target path change"""
        self.wing.correlation_rules.target_file_path = text
    
    def on_target_event_changed(self, text):
        """Handle target event ID change"""
        self.wing.correlation_rules.target_event_id = text
    
    def update_event_id_visibility(self):
        """Show/hide Event ID field based on whether Logs feather exists"""
        has_logs = False
        
        for feather_widget in self.feather_widgets:
            feather_spec = feather_widget.get_feather_spec()
            if feather_spec.artifact_type == "Logs":
                has_logs = True
                break
        
        self.event_id_widget.setVisible(has_logs)
    
    def add_feather(self):
        """Add a new feather widget"""
        feather_widget = FeatherWidget(len(self.feather_widgets) + 1)
        feather_widget.feather_changed.connect(self.on_feather_changed)
        feather_widget.remove_requested.connect(self.remove_feather)
        
        self.feather_widgets.append(feather_widget)
        self.feathers_container.addWidget(feather_widget)
        
        self.update_status()
        self.update_event_id_visibility()
    
    def remove_feather(self, widget):
        """Remove a feather widget"""
        if widget in self.feather_widgets:
            self.feather_widgets.remove(widget)
            self.feathers_container.removeWidget(widget)
            widget.deleteLater()
            
            # Renumber remaining feathers
            for i, fw in enumerate(self.feather_widgets, 1):
                fw.set_feather_number(i)
            
            self.update_status()
            self.update_event_id_visibility()
    
    def on_feather_changed(self):
        """Handle feather configuration change"""
        # Update wing feathers from widgets
        self.wing.feathers = [fw.get_feather_spec() for fw in self.feather_widgets]
        self.update_status()
        self.update_event_id_visibility()
        
        # Update weights table if weighted scoring is enabled
        if self.enable_weighted_scoring_cb.isChecked():
            self.update_weights_table()
    
    def on_weighted_scoring_toggled(self, state):
        """Handle weighted scoring checkbox toggle"""
        enabled = state == Qt.Checked
        self.weights_table.setEnabled(enabled)
        self.interpretation_table.setEnabled(enabled)
        self.add_level_btn.setEnabled(enabled)
        self.remove_level_btn.setEnabled(enabled)
        self.reset_levels_btn.setEnabled(enabled)
        
        if enabled:
            self.update_weights_table()
            self.update_interpretation_table()
        else:
            # Clear tables when disabled
            self.weights_table.setRowCount(0)
            self.interpretation_table.setRowCount(0)
    
    def update_weights_table(self):
        """Update the weights table with current feathers"""
        self.weights_table.blockSignals(True)  # Prevent triggering itemChanged
        
        self.weights_table.setRowCount(len(self.feather_widgets))
        
        # Default weights based on artifact type forensic strength
        default_weights = {
            'MFT': 0.25,
            'Prefetch': 0.20,
            'ShimCache': 0.15,
            'AmCache': 0.15,
            'Registry': 0.10,
            'Logs': 0.10,
            'LNK': 0.05,
            'Jumplists': 0.05,
            'RecycleBin': 0.05,
            'SRUM': 0.10
        }
        
        for i, feather_widget in enumerate(self.feather_widgets):
            feather_spec = feather_widget.get_feather_spec()
            
            # Feather name (read-only)
            name_item = QTableWidgetItem(feather_spec.feather_id or f"Feather {i+1}")
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.weights_table.setItem(i, 0, name_item)
            
            # Get default weight if not set
            if not hasattr(feather_spec, 'weight') or feather_spec.weight == 0.0:
                feather_spec.weight = default_weights.get(feather_spec.artifact_type, 0.10)
            
            # Weight (editable with spin box)
            weight_spin = QDoubleSpinBox()
            weight_spin.setRange(0.0, 1.0)
            weight_spin.setSingleStep(0.05)
            weight_spin.setDecimals(2)
            weight_spin.setValue(feather_spec.weight)
            weight_spin.valueChanged.connect(lambda v, row=i: self.on_weight_spin_changed(row, v))
            self.weights_table.setCellWidget(i, 1, weight_spin)
            
            # Tier (editable)
            tier_spin = QSpinBox()
            tier_spin.setRange(0, 10)
            tier_spin.setValue(getattr(feather_spec, 'tier', 0))
            tier_spin.valueChanged.connect(lambda v, row=i: self.on_tier_changed(row, v))
            self.weights_table.setCellWidget(i, 2, tier_spin)
            
            # Tier name (editable)
            tier_name_item = QTableWidgetItem(getattr(feather_spec, 'tier_name', ''))
            self.weights_table.setItem(i, 3, tier_name_item)
            
            # Artifact type (read-only)
            artifact_item = QTableWidgetItem(feather_spec.artifact_type)
            artifact_item.setFlags(artifact_item.flags() & ~Qt.ItemIsEditable)
            self.weights_table.setItem(i, 4, artifact_item)
        
        self.weights_table.blockSignals(False)
        self.update_total_weight()
    
    def on_weight_spin_changed(self, row, value):
        """Handle weight spin box change"""
        if row < len(self.feather_widgets):
            feather_spec = self.feather_widgets[row].get_feather_spec()
            feather_spec.weight = value
            self.update_total_weight()
    
    def on_tier_changed(self, row, value):
        """Handle tier change"""
        if row < len(self.feather_widgets):
            feather_spec = self.feather_widgets[row].get_feather_spec()
            feather_spec.tier = value
    
    def on_weight_changed(self, item):
        """Handle weight table item change (for tier name)"""
        if item.column() == 3:  # Tier name column
            row = item.row()
            if row < len(self.feather_widgets):
                feather_spec = self.feather_widgets[row].get_feather_spec()
                feather_spec.tier_name = item.text()
    
    def update_total_weight(self):
        """Update the total weight display"""
        total = 0.0
        for i in range(self.weights_table.rowCount()):
            weight_widget = self.weights_table.cellWidget(i, 1)
            if weight_widget:
                total += weight_widget.value()
        
        self.total_weight_label.setText(f"{total:.2f}")
        
        # Update total weight label color based on value
        if total > 1.0:
            self.total_weight_label.setStyleSheet("color: #F59E0B; font-size: 11pt; font-weight: bold;")  # Amber
        elif total >= 0.8:
            self.total_weight_label.setStyleSheet("color: #10B981; font-size: 11pt; font-weight: bold;")  # Green
        else:
            self.total_weight_label.setStyleSheet("color: #00d9ff; font-size: 11pt; font-weight: bold;")  # Cyan
        
        # Show informative message based on total weight
        if total > 1.0:
            self.weight_warning_label.setText(
                f"ℹ️ Total weight ({total:.2f}) exceeds 1.0 - Scores will be normalized. "
                "This is valid for relative scoring where feather importance is compared."
            )
            self.weight_warning_label.setStyleSheet("color: #F59E0B; font-weight: bold; font-size: 9pt;")  # Amber
            self.weight_warning_label.show()
        elif total < 0.5:
            self.weight_warning_label.setText(
                f"💡 Tip: Total weight ({total:.2f}) is low. Consider increasing weights for more meaningful scores."
            )
            self.weight_warning_label.setStyleSheet("color: #60A5FA; font-weight: bold; font-size: 9pt;")  # Blue
            self.weight_warning_label.show()
        else:
            self.weight_warning_label.hide()
    
    def update_interpretation_table(self):
        """Update the interpretation table with current levels"""
        self.interpretation_table.blockSignals(True)
        
        self.interpretation_table.setRowCount(len(self.interpretation_levels))
        
        for i, level in enumerate(self.interpretation_levels):
            # Level (read-only)
            level_item = QTableWidgetItem(level['level'])
            level_item.setFlags(level_item.flags() & ~Qt.ItemIsEditable)
            self.interpretation_table.setItem(i, 0, level_item)
            
            # Label (editable)
            label_item = QTableWidgetItem(level['label'])
            self.interpretation_table.setItem(i, 1, label_item)
            
            # Minimum score (editable with spin box)
            min_spin = QDoubleSpinBox()
            min_spin.setRange(0.0, 1.0)
            min_spin.setSingleStep(0.05)
            min_spin.setDecimals(2)
            min_spin.setValue(level['min'])
            min_spin.valueChanged.connect(lambda v, row=i: self.on_min_score_changed(row, v))
            self.interpretation_table.setCellWidget(i, 2, min_spin)
        
        self.interpretation_table.blockSignals(False)
    
    def on_interpretation_changed(self, item):
        """Handle interpretation table item change"""
        if item.column() == 1:  # Label column
            row = item.row()
            if row < len(self.interpretation_levels):
                self.interpretation_levels[row]['label'] = item.text()
    
    def on_min_score_changed(self, row, value):
        """Handle minimum score change"""
        if row < len(self.interpretation_levels):
            self.interpretation_levels[row]['min'] = value
    
    def add_interpretation_level(self):
        """Add a new interpretation level"""
        level_name, ok = QInputDialog.getText(
            self, "Add Interpretation Level",
            "Enter level name (e.g., 'high', 'medium', 'low'):"
        )
        
        if ok and level_name:
            new_level = {
                "level": level_name.lower().replace(' ', '_'),
                "label": level_name,
                "min": 0.5
            }
            self.interpretation_levels.append(new_level)
            self.update_interpretation_table()
    
    def remove_interpretation_level(self):
        """Remove selected interpretation level"""
        current_row = self.interpretation_table.currentRow()
        if current_row >= 0 and current_row < len(self.interpretation_levels):
            reply = QMessageBox.question(
                self, "Remove Level",
                f"Remove interpretation level '{self.interpretation_levels[current_row]['label']}'?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.interpretation_levels.pop(current_row)
                self.update_interpretation_table()
    
    def reset_interpretation_levels(self):
        """Reset interpretation levels to defaults"""
        reply = QMessageBox.question(
            self, "Reset to Defaults",
            "Reset interpretation levels to default values?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.interpretation_levels = [
                {"level": "confirmed", "label": "Confirmed Evidence", "min": 0.70},
                {"level": "probable", "label": "Probable Match", "min": 0.40},
                {"level": "weak", "label": "Weak / Partial Evidence", "min": 0.20},
                {"level": "insufficient", "label": "Insufficient Evidence", "min": 0.0}
            ]
            self.update_interpretation_table()
    
    def add_semantic_mapping(self):
        """Add a new semantic mapping"""
        from .semantic_mapping_dialog import SemanticMappingDialog
        
        # Pass wing_id to enable wing-specific scope selection
        dialog = SemanticMappingDialog(
            parent=self,
            mapping=None,
            scope='wing',  # Default to wing scope when opened from Wings Creator
            wing_id=self.wing.wing_id
        )
        if dialog.exec_() == QDialog.Accepted:
            mapping = dialog.get_mapping()
            self.wing_semantic_mappings.append(mapping)
            self.update_semantic_mappings_table()
    
    def edit_semantic_mapping(self):
        """Edit selected semantic mapping"""
        current_row = self.semantic_mappings_table.currentRow()
        if current_row < 0 or current_row >= len(self.wing_semantic_mappings):
            QMessageBox.warning(
                self, "No Selection",
                "Please select a semantic mapping to edit."
            )
            return
        
        from .semantic_mapping_dialog import SemanticMappingDialog
        
        mapping = self.wing_semantic_mappings[current_row]
        # Pass wing_id to enable wing-specific scope selection
        dialog = SemanticMappingDialog(
            parent=self,
            mapping=mapping,
            scope=mapping.get('scope', 'wing'),
            wing_id=self.wing.wing_id
        )
        if dialog.exec_() == QDialog.Accepted:
            updated_mapping = dialog.get_mapping()
            self.wing_semantic_mappings[current_row] = updated_mapping
            self.update_semantic_mappings_table()
    
    def delete_semantic_mapping(self):
        """Delete selected semantic mapping"""
        current_row = self.semantic_mappings_table.currentRow()
        if current_row < 0 or current_row >= len(self.wing_semantic_mappings):
            QMessageBox.warning(
                self, "No Selection",
                "Please select a semantic mapping to delete."
            )
            return
        
        mapping = self.wing_semantic_mappings[current_row]
        reply = QMessageBox.question(
            self, "Delete Mapping",
            f"Delete semantic mapping for {mapping['source']}.{mapping['field']} = {mapping['technical_value']}?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.wing_semantic_mappings.pop(current_row)
            self.update_semantic_mappings_table()
    
    def load_global_mappings(self):
        """Load global semantic mappings"""
        try:
            from ...config.semantic_mapping import SemanticMappingManager
            
            # Create semantic mapping manager
            semantic_manager = SemanticMappingManager()
            
            # Get all global mappings
            global_mappings = semantic_manager.get_all_mappings(scope="global")
            
            if not global_mappings:
                QMessageBox.information(
                    self, "No Global Mappings",
                    "No global semantic mappings found."
                )
                return
            
            # Ask user if they want to replace or merge
            reply = QMessageBox.question(
                self, "Load Global Mappings",
                f"Found {len(global_mappings)} global semantic mappings.\n\n"
                "Do you want to:\n"
                "• Yes: Replace all Wing-specific mappings\n"
                "• No: Merge with existing Wing-specific mappings",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )
            
            if reply == QMessageBox.Cancel:
                return
            
            if reply == QMessageBox.Yes:
                # Replace all mappings
                self.wing_semantic_mappings = []
            
            # Add global mappings
            for mapping in global_mappings:
                mapping_dict = {
                    'source': mapping.source,
                    'field': mapping.field,
                    'technical_value': mapping.technical_value,
                    'semantic_value': mapping.semantic_value,
                    'description': mapping.description
                }
                
                # Check if mapping already exists (avoid duplicates when merging)
                exists = any(
                    m['source'] == mapping_dict['source'] and
                    m['field'] == mapping_dict['field'] and
                    m['technical_value'] == mapping_dict['technical_value']
                    for m in self.wing_semantic_mappings
                )
                
                if not exists:
                    self.wing_semantic_mappings.append(mapping_dict)
            
            self.update_semantic_mappings_table()
            
            QMessageBox.information(
                self, "Mappings Loaded",
                f"Successfully loaded {len(global_mappings)} global semantic mappings."
            )
            
        except Exception as e:
            QMessageBox.critical(
                self, "Load Error",
                f"Failed to load global mappings:\n{str(e)}"
            )
    
    def load_global_semantic_mappings(self):
        """Load global semantic mappings with user feedback"""
        try:
            from ...config.semantic_mapping import SemanticMappingManager
            
            # Create semantic mapping manager
            semantic_manager = SemanticMappingManager()
            
            # Get all global mappings
            global_mappings = semantic_manager.get_all_mappings(scope="global")
            
            if not global_mappings:
                QMessageBox.information(
                    self,
                    "No Global Mappings",
                    "No global semantic mappings found.\n\n"
                    "You can create global mappings in the Semantic Mapping configuration."
                )
                return
            
            # Ask user if they want to replace or merge
            existing_count = len(self.wing_semantic_mappings)
            if existing_count > 0:
                reply = QMessageBox.question(
                    self,
                    "Load Global Mappings",
                    f"Found {len(global_mappings)} global mappings.\n"
                    f"You currently have {existing_count} mappings.\n\n"
                    "Do you want to:\n"
                    "• Yes - Replace all existing mappings\n"
                    "• No - Merge (add new, keep existing)",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
                )
                
                if reply == QMessageBox.Cancel:
                    return
                elif reply == QMessageBox.Yes:
                    # Replace all
                    self.wing_semantic_mappings = []
            
            # Add global mappings
            added_count = 0
            skipped_count = 0
            
            for mapping in global_mappings:
                mapping_dict = {
                    'source': mapping.source,
                    'field': mapping.field,
                    'technical_value': mapping.technical_value,
                    'semantic_value': mapping.semantic_value,
                    'description': mapping.description
                }
                
                # Check if mapping already exists (for merge mode)
                exists = False
                for existing in self.wing_semantic_mappings:
                    if (existing.get('source') == mapping_dict['source'] and
                        existing.get('field') == mapping_dict['field'] and
                        existing.get('technical_value') == mapping_dict['technical_value']):
                        exists = True
                        skipped_count += 1
                        break
                
                if not exists:
                    self.wing_semantic_mappings.append(mapping_dict)
                    added_count += 1
            
            self.update_semantic_mappings_table()
            
            # Show result
            message = f"✓ Loaded {added_count} global semantic mappings."
            if skipped_count > 0:
                message += f"\n⊘ Skipped {skipped_count} duplicate mappings."
            
            QMessageBox.information(self, "Global Mappings Loaded", message)
            self.status_bar.showMessage(f"Loaded {added_count} global semantic mappings")
            
        except Exception as e:
            QMessageBox.warning(
                self,
                "Load Error",
                f"Failed to load global semantic mappings:\n{str(e)}"
            )
    
    def load_global_semantic_mappings_silently(self):
        """Load global semantic mappings silently on initialization"""
        try:
            from ...config.semantic_mapping import SemanticMappingManager
            
            # Create semantic mapping manager
            semantic_manager = SemanticMappingManager()
            
            # Get all global mappings
            global_mappings = semantic_manager.get_all_mappings(scope="global")
            
            if not global_mappings:
                return
            
            # Add global mappings
            for mapping in global_mappings:
                mapping_dict = {
                    'source': mapping.source,
                    'field': mapping.field,
                    'technical_value': mapping.technical_value,
                    'semantic_value': mapping.semantic_value,
                    'description': mapping.description
                }
                self.wing_semantic_mappings.append(mapping_dict)
            
            self.update_semantic_mappings_table()
            
        except Exception as e:
            # Silently fail - don't show error on initialization
            print(f"Note: Could not load global semantic mappings: {e}")
    
    def update_semantic_mappings_table(self):
        """Update the semantic mappings table"""
        self.semantic_mappings_table.blockSignals(True)
        
        self.semantic_mappings_table.setRowCount(len(self.wing_semantic_mappings))
        
        for i, mapping in enumerate(self.wing_semantic_mappings):
            # Source (read-only)
            source_item = QTableWidgetItem(mapping.get('source', ''))
            source_item.setFlags(source_item.flags() & ~Qt.ItemIsEditable)
            self.semantic_mappings_table.setItem(i, 0, source_item)
            
            # Field (read-only)
            field_item = QTableWidgetItem(mapping.get('field', ''))
            field_item.setFlags(field_item.flags() & ~Qt.ItemIsEditable)
            self.semantic_mappings_table.setItem(i, 1, field_item)
            
            # Technical Value (read-only)
            tech_item = QTableWidgetItem(mapping.get('technical_value', ''))
            tech_item.setFlags(tech_item.flags() & ~Qt.ItemIsEditable)
            self.semantic_mappings_table.setItem(i, 2, tech_item)
            
            # Semantic Value (read-only)
            semantic_item = QTableWidgetItem(mapping.get('semantic_value', ''))
            semantic_item.setFlags(semantic_item.flags() & ~Qt.ItemIsEditable)
            self.semantic_mappings_table.setItem(i, 3, semantic_item)
            
            # Description (read-only)
            desc_item = QTableWidgetItem(mapping.get('description', ''))
            desc_item.setFlags(desc_item.flags() & ~Qt.ItemIsEditable)
            self.semantic_mappings_table.setItem(i, 4, desc_item)
        
        self.semantic_mappings_table.blockSignals(False)
    
    def update_status(self):
        """Update status bar"""
        feather_count = len(self.feather_widgets)
        if self.wing.wing_name:
            self.status_bar.showMessage(
                f"Wing: {self.wing.wing_name} | Feathers: {feather_count}"
            )
        else:
            self.status_bar.showMessage(f"Feathers: {feather_count}")
    
    def view_json(self):
        """Show JSON viewer dialog"""
        dialog = JsonViewerDialog(self.wing, self)
        dialog.exec_()
    
    def save_wing(self):
        """Save wing to file"""
        # Validate wing
        is_valid, errors = WingValidator.validate_wing(self.wing)
        
        if not is_valid:
            error_msg = "Cannot save wing. Please fix the following errors:\n\n"
            error_msg += "\n".join(f"• {error}" for error in errors)
            QMessageBox.warning(self, "Validation Errors", error_msg)
            return
        
        # Get save path
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Wing",
            f"{self.wing.wing_name}.json" if self.wing.wing_name else "wing.json",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                # Update wing with semantic mappings and rules before saving
                self.wing.semantic_mappings = self.wing_semantic_mappings
                self.wing.semantic_rules = self.wing_semantic_rules if hasattr(self, 'wing_semantic_rules') else []
                
                self.wing.save_to_file(file_path)
                
                # Auto-save wing configuration after saving wing
                self._auto_save_wing_config()
                
                QMessageBox.information(
                    self,
                    "Success",
                    f"Wing saved successfully to:\n{file_path}"
                )
                self.status_bar.showMessage(f"Wing saved: {file_path}")
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Save Error",
                    f"Failed to save wing:\n{str(e)}"
                )
    
    def save_wing_as(self):
        """Save wing as new file"""
        self.save_wing()
    
    def open_wing(self):
        """Open wing from file"""
        print("[Wing Creator] open_wing called")
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Wing",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            print(f"[Wing Creator] Selected file: {file_path}")
            try:
                # Try to load as Wing first
                try:
                    print("[Wing Creator] Attempting to load as Wing format...")
                    self.wing = Wing.load_from_file(file_path)
                    print(f"[Wing Creator] Loaded as Wing format successfully")
                    print(f"[Wing Creator] Wing has {len(self.wing.feathers)} feathers")
                except Exception as wing_error:
                    print(f"[Wing Creator] Failed to load as Wing format: {wing_error}")
                    # If that fails, try loading as WingConfig (default wings format)
                    try:
                        print("[Wing Creator] Attempting to load as WingConfig format...")
                        from ...config.wing_config import WingConfig
                        wing_config = WingConfig.load_from_file(file_path)
                        print(f"[Wing Creator] Loaded as WingConfig successfully")
                        print(f"[Wing Creator] WingConfig has {len(wing_config.feathers)} feathers")
                        # Convert WingConfig to Wing
                        self.wing = self._convert_wing_config_to_wing(wing_config)
                        print(f"[Wing Creator] Converted to Wing with {len(self.wing.feathers)} feathers")
                    except Exception as config_error:
                        print(f"[Wing Creator] Failed to load as WingConfig format: {config_error}")
                        # If both fail, raise the original error
                        raise wing_error
                
                print("[Wing Creator] Calling load_wing_to_ui...")
                self.load_wing_to_ui()
                self.status_bar.showMessage(f"Wing loaded: {file_path}")
                print("[Wing Creator] Wing loaded successfully")
            except Exception as e:
                import traceback
                error_msg = f"Failed to load wing:\n{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
                print(f"[Wing Creator] ERROR: {error_msg}")
                QMessageBox.critical(
                    self,
                    "Load Error",
                    error_msg
                )
    
    def _convert_wing_config_to_wing(self, wing_config) -> Wing:
        """
        Convert WingConfig (pipeline format) to Wing (creator format).
        This is needed for loading default wings which are stored in WingConfig format.
        """
        from ..core.wing_model import Wing, FeatherSpec, CorrelationRules
        
        print(f"[Wing Creator] Converting WingConfig to Wing")
        print(f"[Wing Creator] Wing name: {wing_config.wing_name}")
        print(f"[Wing Creator] Number of feathers in config: {len(wing_config.feathers)}")
        
        # Convert feathers from WingConfig format to Wing format
        feathers = []
        for i, feather in enumerate(wing_config.feathers):
            print(f"[Wing Creator] Converting feather {i+1}: {feather.feather_id}")
            print(f"[Wing Creator]   - artifact_type: {feather.artifact_type}")
            print(f"[Wing Creator]   - feather_database_path: {feather.feather_database_path}")
            
            # Create FeatherSpec directly instead of using from_dict
            # This preserves the full database path
            feather_spec = FeatherSpec(
                feather_id=feather.feather_id,
                database_filename=feather.feather_database_path,  # Keep full path
                artifact_type=feather.artifact_type,
                detection_confidence='high',  # Default for config-based feathers
                manually_overridden=True,  # Config-based feathers are manually configured
                detection_method='metadata',
                feather_config_name=getattr(feather, 'feather_config_name', None),
                weight=getattr(feather, 'weight', 0.0),
                tier=getattr(feather, 'tier', 0),
                tier_name=getattr(feather, 'tier_name', '')
            )
            
            feathers.append(feather_spec)
            print(f"[Wing Creator]   - Created FeatherSpec with database_filename: {feather_spec.database_filename}")
        
        print(f"[Wing Creator] Converted {len(feathers)} feathers")
        
        # Create correlation rules
        correlation_rules = CorrelationRules(
            time_window_minutes=wing_config.time_window_minutes,
            minimum_matches=wing_config.minimum_matches,
            target_application=wing_config.target_application or "",
            target_file_path=wing_config.target_file_path or "",
            target_event_id=wing_config.target_event_id or "",
            apply_to=wing_config.apply_to,
            anchor_priority=wing_config.anchor_priority
        )
        
        # Get semantic rules from WingConfig
        semantic_rules = getattr(wing_config, 'semantic_rules', [])
        print(f"[Wing Creator] Semantic rules from config: {len(semantic_rules)}")
        
        # Get weighted scoring configuration from WingConfig
        use_weighted_scoring = getattr(wing_config, 'use_weighted_scoring', True)
        scoring = getattr(wing_config, 'scoring', {
            'enabled': True,
            'score_interpretation': {
                'confirmed': {'min': 0.8, 'label': 'Confirmed Execution'},
                'probable': {'min': 0.5, 'label': 'Probable Match'},
                'weak': {'min': 0.2, 'label': 'Weak Evidence'},
                'minimal': {'min': 0.0, 'label': 'Minimal Evidence'}
            }
        })
        print(f"[Wing Creator] Use weighted scoring: {use_weighted_scoring}")
        
        # Create Wing object with all fields including semantic rules and scoring
        wing = Wing(
            wing_id=wing_config.wing_id,
            wing_name=wing_config.wing_name,
            version=wing_config.version,
            author=wing_config.author,
            created_date=wing_config.created_date,
            description=wing_config.description,
            proves=wing_config.proves,
            feathers=feathers,
            correlation_rules=correlation_rules,
            semantic_rules=semantic_rules,
            use_weighted_scoring=use_weighted_scoring,
            scoring=scoring
        )
        
        print(f"[Wing Creator] Created Wing with {len(wing.feathers)} feathers")
        print(f"[Wing Creator] Wing has {len(wing.semantic_rules)} semantic rules")
        print(f"[Wing Creator] Wing use_weighted_scoring: {wing.use_weighted_scoring}")
        
        return wing
    
    def load_wing_to_ui(self):
        """Load wing data into UI"""
        print(f"[Wing Creator] load_wing_to_ui called")
        print(f"[Wing Creator] Wing name: {self.wing.wing_name}")
        print(f"[Wing Creator] Number of feathers in wing: {len(self.wing.feathers)}")
        
        # Load basic info
        self.wing_name_input.setText(self.wing.wing_name)
        self.wing_id_label.setText(self.wing.wing_id)
        self.description_input.setPlainText(self.wing.description)
        self.author_input.setText(self.wing.author)
        self.proves_input.setText(self.wing.proves)
        
        # Load correlation rules
        self.time_window_spin.setValue(self.wing.correlation_rules.time_window_minutes)
        self.min_matches_spin.setValue(self.wing.correlation_rules.minimum_matches)
        self.anchor_priority_widget.set_priority(self.wing.correlation_rules.anchor_priority)
        
        # Load filter settings
        if self.wing.correlation_rules.apply_to == "specific":
            self.apply_specific_radio.setChecked(True)
            self.target_app_input.setEnabled(True)
        else:
            self.apply_all_radio.setChecked(True)
            self.target_app_input.setEnabled(False)
        
        self.target_app_input.setText(self.wing.correlation_rules.target_application)
        self.target_path_input.setText(self.wing.correlation_rules.target_file_path)
        self.target_event_input.setText(self.wing.correlation_rules.target_event_id)
        
        # Load feathers
        # Clear existing feather widgets
        for widget in self.feather_widgets:
            self.feathers_container.removeWidget(widget)
            widget.deleteLater()
        self.feather_widgets.clear()
        
        print(f"[Wing Creator] Creating {len(self.wing.feathers)} feather widgets")
        
        # Add feather widgets
        for i, feather in enumerate(self.wing.feathers):
            print(f"[Wing Creator] Creating widget for feather {i+1}: {feather.feather_id}")
            print(f"[Wing Creator]   - database_filename: {feather.database_filename}")
            print(f"[Wing Creator]   - artifact_type: {feather.artifact_type}")
            
            feather_widget = FeatherWidget(len(self.feather_widgets) + 1)
            # Set case directory if available
            if self.case_directory:
                feather_widget.set_case_directory(self.case_directory)
            feather_widget.set_feather_spec(feather)
            feather_widget.feather_changed.connect(self.on_feather_changed)
            feather_widget.remove_requested.connect(self.remove_feather)
            
            self.feather_widgets.append(feather_widget)
            self.feathers_container.addWidget(feather_widget)
            feather_widget.show()  # Explicitly show the widget
            print(f"[Wing Creator]   - Widget added and shown")
        
        print(f"[Wing Creator] Created {len(self.feather_widgets)} feather widgets")
        
        # Force UI update to ensure widgets are visible
        self.feathers_container.update()
        if hasattr(self, 'scroll_area'):
            self.scroll_area.update()
        
        # Update Event ID visibility
        self.update_event_id_visibility()
        
        # Load semantic mappings
        self.wing_semantic_mappings = self.wing.semantic_mappings if hasattr(self.wing, 'semantic_mappings') else []
        self.update_semantic_mappings_table()
        
        # Load advanced semantic rules
        self._load_semantic_rules_to_ui()
        
        # Load weighted scoring configuration
        self._load_scoring_to_ui()
    
    def new_wing(self):
        """Create new wing"""
        reply = QMessageBox.question(
            self,
            "New Wing",
            "Create a new wing? Any unsaved changes will be lost.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.wing = Wing()
            self.wing_semantic_mappings = []
            self.wing_semantic_rules = []
            self.load_wing_to_ui()
            self.status_bar.showMessage("New wing created")
    
    def test_wing(self):
        """Test wing configuration"""
        is_valid, errors = WingValidator.validate_wing(self.wing)
        
        if is_valid:
            QMessageBox.information(
                self,
                "Validation Success",
                "Wing configuration is valid and ready to use!"
            )
        else:
            error_msg = "Wing has the following validation errors:\n\n"
            error_msg += "\n".join(f"• {error}" for error in errors)
            QMessageBox.warning(self, "Validation Errors", error_msg)
    
    def show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            "About Wings Creator",
            "Crow-Eye Wings Creator v0.1.0\n\n"
            "Visual tool for creating forensic correlation rules (Wings).\n"
            "Part of the Correlation Engine system."
        )

    # Configuration Methods
    
    def save_wing_config(self):
        """Save current wing as a configuration"""
        if not CONFIG_AVAILABLE:
            QMessageBox.warning(self, "Not Available", "Configuration system not available")
            return
        
        # Validate wing first
        is_valid, errors = WingValidator.validate_wing(self.wing)
        if not is_valid:
            reply = QMessageBox.question(
                self, "Validation Errors",
                f"Wing has validation errors:\n\n" + "\n".join(errors[:5]) + "\n\nSave anyway?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
        
        # Get config name from user
        config_name, ok = QInputDialog.getText(
            self, "Save Configuration",
            "Enter configuration name:",
            QLineEdit.Normal,
            self.wing.wing_name.lower().replace(' ', '_') if self.wing.wing_name else "wing_config"
        )
        
        if not ok or not config_name:
            return
        
        try:
            # Create wing config with feather references
            feather_refs = []
            for feather_widget in self.feather_widgets:
                feather_spec = feather_widget.get_feather_spec()
                feather_refs.append(
                    WingFeatherReference(
                        feather_config_name="",  # Can be linked later
                        feather_database_path=feather_spec.database_filename,
                        artifact_type=feather_spec.artifact_type,
                        feather_id=feather_spec.feather_id,
                        weight=getattr(feather_spec, 'weight', 0.0),
                        tier=getattr(feather_spec, 'tier', 0),
                        tier_name=getattr(feather_spec, 'tier_name', '')
                    )
                )
            
            # Build scoring configuration
            scoring_config = {}
            if self.enable_weighted_scoring_cb.isChecked():
                score_interpretation = {}
                for level in self.interpretation_levels:
                    score_interpretation[level['level']] = {
                        'min': level['min'],
                        'label': level['label']
                    }
                scoring_config = {
                    'enabled': True,
                    'score_interpretation': score_interpretation
                }
            
            config = WingConfig(
                config_name=config_name,
                wing_name=self.wing.wing_name,
                wing_id=self.wing.wing_id,
                description=self.wing.description,
                proves=self.wing.proves,
                author=self.wing.author,
                feathers=feather_refs,
                time_window_minutes=self.wing.correlation_rules.time_window_minutes,
                minimum_matches=self.wing.correlation_rules.minimum_matches,
                target_application=self.wing.correlation_rules.target_application,
                target_file_path=self.wing.correlation_rules.target_file_path,
                target_event_id=self.wing.correlation_rules.target_event_id,
                apply_to=self.wing.correlation_rules.apply_to,
                anchor_priority=self.wing.correlation_rules.anchor_priority,
                use_weighted_scoring=self.enable_weighted_scoring_cb.isChecked(),
                scoring=scoring_config
            )
            
            # Save configuration
            saved_path = self.config_manager.save_wing_config(config)
            
            QMessageBox.information(
                self, "Configuration Saved",
                f"Wing configuration saved successfully:\n{saved_path}\n\n"
                f"You can reuse this wing in other cases by loading this configuration."
            )
            
            self.current_config = config
            self.status_bar.showMessage(f"Configuration saved: {config_name}")
            
        except Exception as e:
            QMessageBox.critical(
                self, "Save Error",
                f"Failed to save configuration:\n{str(e)}"
            )
    
    def _auto_save_wing_config(self):
        """Automatically save wing configuration after saving wing"""
        if not CONFIG_AVAILABLE or not self.config_manager:
            return
        
        try:
            # Generate config name from wing name
            config_name = self.wing.wing_name.replace(' ', '_').lower() if self.wing.wing_name else "wing_config"
            
            # Create wing config with feather references
            feather_refs = []
            for feather_widget in self.feather_widgets:
                feather_spec = feather_widget.get_feather_spec()
                feather_refs.append(
                    WingFeatherReference(
                        feather_config_name="",
                        feather_database_path=feather_spec.database_filename,
                        artifact_type=feather_spec.artifact_type,
                        feather_id=feather_spec.feather_id,
                        weight=getattr(feather_spec, 'weight', 0.0),
                        tier=getattr(feather_spec, 'tier', 0),
                        tier_name=getattr(feather_spec, 'tier_name', '')
                    )
                )
            
            # Build scoring configuration
            scoring_config = {}
            if self.enable_weighted_scoring_cb.isChecked():
                score_interpretation = {}
                for level in self.interpretation_levels:
                    score_interpretation[level['level']] = {
                        'min': level['min'],
                        'label': level['label']
                    }
                scoring_config = {
                    'enabled': True,
                    'score_interpretation': score_interpretation
                }
            
            config = WingConfig(
                config_name=config_name,
                wing_name=self.wing.wing_name,
                wing_id=self.wing.wing_id,
                description=self.wing.description,
                proves=self.wing.proves,
                author=self.wing.author,
                feathers=feather_refs,
                time_window_minutes=self.wing.correlation_rules.time_window_minutes,
                minimum_matches=self.wing.correlation_rules.minimum_matches,
                target_application=self.wing.correlation_rules.target_application,
                target_file_path=self.wing.correlation_rules.target_file_path,
                target_event_id=self.wing.correlation_rules.target_event_id,
                apply_to=self.wing.correlation_rules.apply_to,
                anchor_priority=self.wing.correlation_rules.anchor_priority,
                use_weighted_scoring=self.enable_weighted_scoring_cb.isChecked(),
                scoring=scoring_config
            )
            
            # Save configuration silently
            saved_path = self.config_manager.save_wing_config(config)
            self.current_config = config
            self.status_bar.showMessage(f"✓ Config auto-saved: {config_name}")
            
        except Exception as e:
            # Don't show error to user, just log it
            print(f"Auto-save wing config failed: {e}")
    
    def _wing_feather_ref_to_feather_spec(self, feather_ref, case_directory=None):
        """
        Convert WingFeatherReference to FeatherSpec.
        
        Args:
            feather_ref: WingFeatherReference from wing config
            case_directory: Optional case directory for path resolution
            
        Returns:
            FeatherSpec object ready for FeatherWidget
        """
        from ..core.wing_model import FeatherSpec
        
        # Create FeatherSpec with proper field mapping
        feather_spec = FeatherSpec(
            feather_id=feather_ref.feather_id,
            database_filename=feather_ref.feather_database_path,
            artifact_type=feather_ref.artifact_type,
            detection_confidence="high",  # Default for loaded configs
            manually_overridden=False
        )
        
        # Add weighted scoring fields if present
        if hasattr(feather_ref, 'weight'):
            feather_spec.weight = feather_ref.weight
        if hasattr(feather_ref, 'tier'):
            feather_spec.tier = feather_ref.tier
        if hasattr(feather_ref, 'tier_name'):
            feather_spec.tier_name = feather_ref.tier_name
        
        # Store feather_config_name for path resolution
        if hasattr(feather_ref, 'feather_config_name'):
            feather_spec.feather_config_name = feather_ref.feather_config_name
        
        return feather_spec
    
    def load_wing_config(self):
        """Load a wing configuration"""
        if not CONFIG_AVAILABLE:
            QMessageBox.warning(self, "Not Available", "Configuration system not available")
            return
        
        try:
            # Get list of available configs
            configs = self.config_manager.list_wing_configs()
            
            if not configs:
                QMessageBox.information(
                    self, "No Configurations",
                    "No saved wing configurations found.\n\n"
                    "Create a wing and save its configuration first."
                )
                return
            
            # Let user select a config
            config_name, ok = QInputDialog.getItem(
                self, "Load Configuration",
                "Select wing configuration to load:",
                configs, 0, False
            )
            
            if not ok or not config_name:
                return
            
            # Load the configuration
            config = self.config_manager.load_wing_config(config_name)
            
            # Apply configuration to UI
            self.wing_name_input.setText(config.wing_name)
            self.wing_id_label.setText(config.wing_id)
            self.description_input.setPlainText(config.description)
            self.author_input.setText(config.author)
            self.proves_input.setText(config.proves)
            
            # Load correlation rules
            self.time_window_spin.setValue(config.time_window_minutes)
            self.min_matches_spin.setValue(config.minimum_matches)
            self.target_app_input.setText(config.target_application)
            self.target_path_input.setText(config.target_file_path)
            self.target_event_input.setText(config.target_event_id)
            
            if config.apply_to == "specific":
                self.apply_specific_radio.setChecked(True)
            else:
                self.apply_all_radio.setChecked(True)
            
            # Load weighted scoring configuration
            self.enable_weighted_scoring_cb.setChecked(config.use_weighted_scoring)
            if config.use_weighted_scoring and config.scoring:
                # Load interpretation levels
                if 'score_interpretation' in config.scoring:
                    self.interpretation_levels = []
                    for level_key, level_data in config.scoring['score_interpretation'].items():
                        self.interpretation_levels.append({
                            'level': level_key,
                            'label': level_data.get('label', level_key),
                            'min': level_data.get('min', 0.0)
                        })
                    self.update_interpretation_table()
            
            # Load feathers with proper conversion and error handling
            # Clear existing feather widgets
            for widget in self.feather_widgets:
                self.feathers_container.removeWidget(widget)
                widget.deleteLater()
            self.feather_widgets.clear()
            
            # Track loading results
            loaded_count = 0
            failed_feathers = []
            
            # Add feather widgets from config
            for i, feather_ref in enumerate(config.feathers):
                try:
                    # Convert WingFeatherReference to FeatherSpec
                    feather_spec = self._wing_feather_ref_to_feather_spec(
                        feather_ref,
                        self.case_directory
                    )
                    
                    # Create feather widget
                    feather_widget = FeatherWidget(len(self.feather_widgets) + 1)
                    
                    # Set case directory if available
                    if self.case_directory:
                        feather_widget.set_case_directory(self.case_directory)
                    
                    # Set feather spec (this will resolve paths and populate UI)
                    feather_widget.set_feather_spec(feather_spec)
                    
                    # Connect signals
                    feather_widget.feather_changed.connect(self.on_feather_changed)
                    feather_widget.remove_requested.connect(self.remove_feather)
                    
                    # Add to container
                    self.feather_widgets.append(feather_widget)
                    self.feathers_container.addWidget(feather_widget)
                    
                    loaded_count += 1
                    print(f"[Wings Creator] Loaded feather {i+1}: {feather_ref.feather_id}")
                    
                except Exception as e:
                    feather_id = getattr(feather_ref, 'feather_id', f'feather_{i+1}')
                    error_msg = str(e)
                    failed_feathers.append((feather_id, error_msg))
                    print(f"[Wings Creator] Failed to load feather {feather_id}: {error_msg}")
            
            # Update weights table if weighted scoring is enabled
            if config.use_weighted_scoring and loaded_count > 0:
                self.update_weights_table()
            
            # Show configuration details with loading results
            if failed_feathers:
                # Partial load - show warning
                failed_list = "\n".join([f"  • {fid}: {err}" for fid, err in failed_feathers])
                details = (
                    f"Configuration: {config.config_name}\n"
                    f"Wing: {config.wing_name}\n"
                    f"Feathers Loaded: {loaded_count}/{len(config.feathers)}\n"
                    f"Target: {config.target_application or 'All applications'}\n"
                    f"Weighted Scoring: {'Enabled' if config.use_weighted_scoring else 'Disabled'}\n\n"
                    f"⚠ Warning: Some feathers failed to load:\n{failed_list}\n\n"
                    f"You may need to manually select the feather database files."
                )
                QMessageBox.warning(
                    self, "Configuration Partially Loaded",
                    details
                )
            else:
                # Full success
                details = (
                    f"Configuration: {config.config_name}\n"
                    f"Wing: {config.wing_name}\n"
                    f"Feathers: {loaded_count} loaded successfully\n"
                    f"Target: {config.target_application or 'All applications'}\n"
                    f"Weighted Scoring: {'Enabled' if config.use_weighted_scoring else 'Disabled'}\n"
                    f"Created: {config.created_date}\n\n"
                    f"✓ All feathers loaded successfully!"
                )
                QMessageBox.information(
                    self, "Configuration Loaded",
                    details
                )
            
            self.current_config = config
            self.status_bar.showMessage(f"Configuration loaded: {config_name}")
            
        except Exception as e:
            QMessageBox.critical(
                self, "Load Error",
                f"Failed to load configuration:\n{str(e)}"
            )
    
    def list_wing_configs(self):
        """List all available wing configurations"""
        if not CONFIG_AVAILABLE:
            QMessageBox.warning(self, "Not Available", "Configuration system not available")
            return
        
        try:
            configs = self.config_manager.list_wing_configs()
            
            if not configs:
                QMessageBox.information(
                    self, "No Configurations",
                    "No saved wing configurations found."
                )
                return
            
            # Build list of configs with details
            config_list = []
            for config_name in configs:
                try:
                    info = self.config_manager.get_config_info("wing", config_name)
                    config_list.append(
                        f"• {config_name}\n"
                        f"  Wing: {info.get('wing_name', 'Unknown')}\n"
                        f"  Feathers: {info.get('feathers', 0)}\n"
                        f"  Proves: {info.get('proves', 'N/A')}\n"
                    )
                except:
                    config_list.append(f"• {config_name}\n")
            
            message = "Available Wing Configurations:\n\n" + "\n".join(config_list)
            
            QMessageBox.information(
                self, "Wing Configurations",
                message
            )
            
        except Exception as e:
            QMessageBox.critical(
                self, "Error",
                f"Failed to list configurations:\n{str(e)}"
            )
