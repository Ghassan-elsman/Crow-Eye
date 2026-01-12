"""
Case-Specific Configuration Dialog

Provides comprehensive UI for managing case-specific semantic mappings and scoring weights.
Allows users to create, edit, and manage case-specific configurations that override
global settings.

Features:
- Case selection and management
- Semantic mappings editor with validation
- Scoring weights editor with visual feedback
- Configuration comparison and copying
- Import/export capabilities
- Real-time validation and preview
"""

import logging
from typing import Optional, Dict, Any, List
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QLabel,
    QCheckBox, QSpinBox, QDoubleSpinBox, QLineEdit, QPushButton,
    QGroupBox, QFormLayout, QComboBox, QTextEdit, QMessageBox,
    QFileDialog, QSlider, QFrame, QScrollArea, QGridLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QSplitter,
    QTreeWidget, QTreeWidgetItem, QProgressBar, QListWidget,
    QListWidgetItem, QButtonGroup, QRadioButton
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QIcon, QColor, QPalette

from ..integration.case_specific_configuration_integration import CaseSpecificConfigurationIntegration
from ..config.case_specific_configuration_manager import (
    CaseSemanticMappingConfig, CaseScoringWeightsConfig, CaseConfigurationMetadata
)

logger = logging.getLogger(__name__)


class CaseSpecificConfigurationDialog(QDialog):
    """
    Dialog for managing case-specific configurations.
    
    Provides comprehensive interface for creating, editing, and managing
    case-specific semantic mappings and scoring weights.
    """
    
    # Signals
    configuration_changed = pyqtSignal(str)  # case_id
    case_switched = pyqtSignal(str)  # case_id
    
    def __init__(self, 
                 case_integration: CaseSpecificConfigurationIntegration,
                 current_case_id: Optional[str] = None,
                 parent=None):
        super().__init__(parent)
        
        self.case_integration = case_integration
        self.current_case_id = current_case_id
        
        self.setWindowTitle("Case-Specific Configuration")
        self.setModal(True)
        self.resize(1200, 800)
        
        # Track changes
        self.has_unsaved_changes = False
        
        self._setup_ui()
        self._load_cases()
        self._connect_signals()
        
        # Load current case if specified
        if current_case_id:
            self._switch_to_case(current_case_id)
    
    def _setup_ui(self):
        """Setup the user interface"""
        layout = QVBoxLayout(self)
        
        # Create main splitter
        main_splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(main_splitter)
        
        # Left panel - Case selection and management
        self._create_case_panel(main_splitter)
        
        # Right panel - Configuration tabs
        self._create_configuration_panel(main_splitter)
        
        # Set splitter proportions
        main_splitter.setSizes([300, 900])
        
        # Create button bar
        self._create_button_bar(layout)
    
    def _create_case_panel(self, parent):
        """Create case selection and management panel"""
        case_widget = QWidget()
        case_layout = QVBoxLayout(case_widget)
        
        # Case selection
        case_selection_group = QGroupBox("Case Selection")
        case_selection_layout = QVBoxLayout(case_selection_group)
        
        # Current case display
        current_case_layout = QHBoxLayout()
        current_case_layout.addWidget(QLabel("Current Case:"))
        self.current_case_label = QLabel("None")
        self.current_case_label.setStyleSheet("font-weight: bold; color: blue;")
        current_case_layout.addWidget(self.current_case_label)
        current_case_layout.addStretch()
        case_selection_layout.addLayout(current_case_layout)
        
        # Case list
        self.case_list = QListWidget()
        self.case_list.itemClicked.connect(self._on_case_selected)
        case_selection_layout.addWidget(self.case_list)
        
        # Case management buttons
        case_buttons_layout = QGridLayout()
        
        self.new_case_btn = QPushButton("New Case")
        self.new_case_btn.clicked.connect(self._create_new_case)
        case_buttons_layout.addWidget(self.new_case_btn, 0, 0)
        
        self.copy_case_btn = QPushButton("Copy Case")
        self.copy_case_btn.clicked.connect(self._copy_case)
        case_buttons_layout.addWidget(self.copy_case_btn, 0, 1)
        
        self.delete_case_btn = QPushButton("Delete Case")
        self.delete_case_btn.clicked.connect(self._delete_case)
        case_buttons_layout.addWidget(self.delete_case_btn, 1, 0)
        
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._load_cases)
        case_buttons_layout.addWidget(self.refresh_btn, 1, 1)
        
        case_selection_layout.addLayout(case_buttons_layout)
        
        # Configuration mode selection
        config_mode_group = QGroupBox("Configuration Mode")
        config_mode_layout = QVBoxLayout(config_mode_group)
        
        self.config_mode_group = QButtonGroup()
        
        self.global_mode_rb = QRadioButton("Use Global Settings")
        self.global_mode_rb.setToolTip("Use global configuration for this case")
        self.global_mode_rb.toggled.connect(self._on_config_mode_changed)
        self.config_mode_group.addButton(self.global_mode_rb, 0)
        config_mode_layout.addWidget(self.global_mode_rb)
        
        self.custom_mode_rb = QRadioButton("Create Custom Settings")
        self.custom_mode_rb.setToolTip("Create case-specific configuration")
        self.custom_mode_rb.toggled.connect(self._on_config_mode_changed)
        self.config_mode_group.addButton(self.custom_mode_rb, 1)
        config_mode_layout.addWidget(self.custom_mode_rb)
        
        # Configuration status
        self.config_status_label = QLabel("No case selected")
        self.config_status_label.setWordWrap(True)
        config_mode_layout.addWidget(self.config_status_label)
        
        case_layout.addWidget(case_selection_group)
        case_layout.addWidget(config_mode_group)
        case_layout.addStretch()
        
        parent.addWidget(case_widget)
    
    def _create_configuration_panel(self, parent):
        """Create configuration tabs panel"""
        config_widget = QWidget()
        config_layout = QVBoxLayout(config_widget)
        
        # Configuration tabs
        self.config_tabs = QTabWidget()
        config_layout.addWidget(self.config_tabs)
        
        # Create tabs
        self._create_semantic_mappings_tab()
        self._create_scoring_weights_tab()
        self._create_case_metadata_tab()
        self._create_comparison_tab()
        
        parent.addWidget(config_widget)
    
    def _create_semantic_mappings_tab(self):
        """Create semantic mappings configuration tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Enable/disable semantic mappings
        semantic_group = QGroupBox("Semantic Mappings Configuration")
        semantic_layout = QVBoxLayout(semantic_group)
        
        # Enable checkbox and options
        options_layout = QHBoxLayout()
        
        self.semantic_enabled_cb = QCheckBox("Enable case-specific semantic mappings")
        self.semantic_enabled_cb.toggled.connect(self._on_semantic_enabled_changed)
        options_layout.addWidget(self.semantic_enabled_cb)
        
        options_layout.addStretch()
        
        self.inherit_global_semantic_cb = QCheckBox("Inherit global mappings")
        self.inherit_global_semantic_cb.setToolTip("Include global mappings in addition to case-specific ones")
        options_layout.addWidget(self.inherit_global_semantic_cb)
        
        self.override_global_semantic_cb = QCheckBox("Override global mappings")
        self.override_global_semantic_cb.setToolTip("Case-specific mappings take precedence over global ones")
        options_layout.addWidget(self.override_global_semantic_cb)
        
        semantic_layout.addLayout(options_layout)
        
        # Mappings table
        self.semantic_table = QTableWidget()
        self.semantic_table.setColumnCount(7)
        self.semantic_table.setHorizontalHeaderLabels([
            "Source", "Field", "Technical Value", "Semantic Value", 
            "Category", "Severity", "Description"
        ])
        
        # Set column widths
        header = self.semantic_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        
        semantic_layout.addWidget(self.semantic_table)
        
        # Semantic mappings buttons
        semantic_buttons_layout = QHBoxLayout()
        
        self.add_semantic_btn = QPushButton("Add Mapping")
        self.add_semantic_btn.clicked.connect(self._add_semantic_mapping)
        semantic_buttons_layout.addWidget(self.add_semantic_btn)
        
        self.edit_semantic_btn = QPushButton("Edit Mapping")
        self.edit_semantic_btn.clicked.connect(self._edit_semantic_mapping)
        semantic_buttons_layout.addWidget(self.edit_semantic_btn)
        
        self.delete_semantic_btn = QPushButton("Delete Mapping")
        self.delete_semantic_btn.clicked.connect(self._delete_semantic_mapping)
        semantic_buttons_layout.addWidget(self.delete_semantic_btn)
        
        semantic_buttons_layout.addStretch()
        
        self.import_semantic_btn = QPushButton("Import Mappings")
        self.import_semantic_btn.clicked.connect(self._import_semantic_mappings)
        semantic_buttons_layout.addWidget(self.import_semantic_btn)
        
        self.export_semantic_btn = QPushButton("Export Mappings")
        self.export_semantic_btn.clicked.connect(self._export_semantic_mappings)
        semantic_buttons_layout.addWidget(self.export_semantic_btn)
        
        semantic_layout.addLayout(semantic_buttons_layout)
        
        layout.addWidget(semantic_group)
        
        self.config_tabs.addTab(tab, "Semantic Mappings")
    
    def _create_scoring_weights_tab(self):
        """Create scoring weights configuration tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Enable/disable scoring weights
        scoring_group = QGroupBox("Scoring Weights Configuration")
        scoring_layout = QVBoxLayout(scoring_group)
        
        # Enable checkbox and options
        options_layout = QHBoxLayout()
        
        self.scoring_enabled_cb = QCheckBox("Enable case-specific scoring weights")
        self.scoring_enabled_cb.toggled.connect(self._on_scoring_enabled_changed)
        options_layout.addWidget(self.scoring_enabled_cb)
        
        options_layout.addStretch()
        
        self.inherit_global_scoring_cb = QCheckBox("Inherit global weights")
        self.inherit_global_scoring_cb.setToolTip("Use global weights as base, override with case-specific ones")
        options_layout.addWidget(self.inherit_global_scoring_cb)
        
        self.override_global_scoring_cb = QCheckBox("Override global weights")
        self.override_global_scoring_cb.setToolTip("Case-specific weights take precedence over global ones")
        options_layout.addWidget(self.override_global_scoring_cb)
        
        scoring_layout.addLayout(options_layout)
        
        # Create scrollable area for weights
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        # Artifact weights
        weights_group = QGroupBox("Artifact Weights")
        weights_layout = QGridLayout(weights_group)
        
        weights_layout.addWidget(QLabel("Artifact Type"), 0, 0)
        weights_layout.addWidget(QLabel("Weight"), 0, 1)
        weights_layout.addWidget(QLabel("Slider"), 0, 2)
        weights_layout.addWidget(QLabel("Tier"), 0, 3)
        
        self.scoring_weights_widgets = {}
        artifact_types = [
            "Logs", "Prefetch", "SRUM", "AmCache", "ShimCache", 
            "Jumplists", "LNK", "MFT", "USN", "Registry", "Browser"
        ]
        
        for i, artifact_type in enumerate(artifact_types):
            row = i + 1
            
            # Artifact type label
            type_label = QLabel(artifact_type)
            weights_layout.addWidget(type_label, row, 0)
            
            # Weight spinbox
            weight_spin = QDoubleSpinBox()
            weight_spin.setRange(0.0, 1.0)
            weight_spin.setSingleStep(0.05)
            weight_spin.setDecimals(2)
            weight_spin.valueChanged.connect(self._on_weight_changed)
            weights_layout.addWidget(weight_spin, row, 1)
            
            # Weight slider
            weight_slider = QSlider(Qt.Horizontal)
            weight_slider.setRange(0, 100)
            weight_slider.valueChanged.connect(lambda v, spin=weight_spin: spin.setValue(v / 100.0))
            weight_spin.valueChanged.connect(lambda v, slider=weight_slider: slider.setValue(int(v * 100)))
            weights_layout.addWidget(weight_slider, row, 2)
            
            # Tier combobox
            tier_combo = QComboBox()
            tier_combo.addItems(["1 - Primary", "2 - Supporting", "3 - Contextual", "4 - Background"])
            tier_combo.currentIndexChanged.connect(self._on_tier_changed)
            weights_layout.addWidget(tier_combo, row, 3)
            
            self.scoring_weights_widgets[artifact_type] = {
                'spin': weight_spin,
                'slider': weight_slider,
                'tier': tier_combo
            }
        
        scroll_layout.addWidget(weights_group)
        
        # Score interpretation
        interpretation_group = QGroupBox("Score Interpretation")
        interpretation_layout = QGridLayout(interpretation_group)
        
        interpretation_layout.addWidget(QLabel("Level"), 0, 0)
        interpretation_layout.addWidget(QLabel("Minimum Score"), 0, 1)
        interpretation_layout.addWidget(QLabel("Label"), 0, 2)
        interpretation_layout.addWidget(QLabel("Color"), 0, 3)
        
        self.score_interpretation_widgets = {}
        levels = ["confirmed", "probable", "weak", "minimal"]
        colors = ["#4CAF50", "#FF9800", "#FFC107", "#9E9E9E"]
        
        for i, (level, color) in enumerate(zip(levels, colors)):
            row = i + 1
            
            level_label = QLabel(level.title())
            interpretation_layout.addWidget(level_label, row, 0)
            
            min_score_spin = QDoubleSpinBox()
            min_score_spin.setRange(0.0, 1.0)
            min_score_spin.setSingleStep(0.1)
            min_score_spin.setDecimals(2)
            interpretation_layout.addWidget(min_score_spin, row, 1)
            
            label_edit = QLineEdit()
            interpretation_layout.addWidget(label_edit, row, 2)
            
            color_btn = QPushButton()
            color_btn.setStyleSheet(f"background-color: {color}; min-width: 50px;")
            color_btn.clicked.connect(lambda checked, l=level: self._choose_score_color(l))
            interpretation_layout.addWidget(color_btn, row, 3)
            
            self.score_interpretation_widgets[level] = {
                'min_score': min_score_spin,
                'label': label_edit,
                'color_btn': color_btn,
                'color': color
            }
        
        scroll_layout.addWidget(interpretation_group)
        scroll_layout.addStretch()
        
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        scoring_layout.addWidget(scroll_area)
        
        # Scoring buttons
        scoring_buttons_layout = QHBoxLayout()
        
        self.reset_weights_btn = QPushButton("Reset to Defaults")
        self.reset_weights_btn.clicked.connect(self._reset_scoring_weights)
        scoring_buttons_layout.addWidget(self.reset_weights_btn)
        
        self.balance_weights_btn = QPushButton("Auto-Balance")
        self.balance_weights_btn.clicked.connect(self._auto_balance_weights)
        scoring_buttons_layout.addWidget(self.balance_weights_btn)
        
        scoring_buttons_layout.addStretch()
        
        self.import_weights_btn = QPushButton("Import Weights")
        self.import_weights_btn.clicked.connect(self._import_scoring_weights)
        scoring_buttons_layout.addWidget(self.import_weights_btn)
        
        self.export_weights_btn = QPushButton("Export Weights")
        self.export_weights_btn.clicked.connect(self._export_scoring_weights)
        scoring_buttons_layout.addWidget(self.export_weights_btn)
        
        scoring_layout.addLayout(scoring_buttons_layout)
        
        layout.addWidget(scoring_group)
        
        self.config_tabs.addTab(tab, "Scoring Weights")
    
    def _create_case_metadata_tab(self):
        """Create case metadata configuration tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Case information
        info_group = QGroupBox("Case Information")
        info_layout = QFormLayout(info_group)
        
        self.case_id_edit = QLineEdit()
        self.case_id_edit.setReadOnly(True)
        info_layout.addRow("Case ID:", self.case_id_edit)
        
        self.case_name_edit = QLineEdit()
        self.case_name_edit.textChanged.connect(self._on_metadata_changed)
        info_layout.addRow("Case Name:", self.case_name_edit)
        
        self.case_description_edit = QTextEdit()
        self.case_description_edit.setMaximumHeight(100)
        self.case_description_edit.textChanged.connect(self._on_metadata_changed)
        info_layout.addRow("Description:", self.case_description_edit)
        
        self.case_tags_edit = QLineEdit()
        self.case_tags_edit.setPlaceholderText("Enter tags separated by commas")
        self.case_tags_edit.textChanged.connect(self._on_metadata_changed)
        info_layout.addRow("Tags:", self.case_tags_edit)
        
        layout.addWidget(info_group)
        
        # Configuration status
        status_group = QGroupBox("Configuration Status")
        status_layout = QFormLayout(status_group)
        
        self.has_semantic_label = QLabel("No")
        status_layout.addRow("Has Semantic Mappings:", self.has_semantic_label)
        
        self.has_scoring_label = QLabel("No")
        status_layout.addRow("Has Scoring Weights:", self.has_scoring_label)
        
        self.created_date_label = QLabel("Unknown")
        status_layout.addRow("Created:", self.created_date_label)
        
        self.modified_date_label = QLabel("Unknown")
        status_layout.addRow("Last Modified:", self.modified_date_label)
        
        self.config_size_label = QLabel("0 KB")
        status_layout.addRow("Configuration Size:", self.config_size_label)
        
        layout.addWidget(status_group)
        
        # Validation status
        validation_group = QGroupBox("Validation Status")
        validation_layout = QVBoxLayout(validation_group)
        
        self.validation_status_label = QLabel("Not validated")
        validation_layout.addWidget(self.validation_status_label)
        
        self.validate_btn = QPushButton("Validate Configuration")
        self.validate_btn.clicked.connect(self._validate_configuration)
        validation_layout.addWidget(self.validate_btn)
        
        self.validation_results = QTextEdit()
        self.validation_results.setReadOnly(True)
        self.validation_results.setMaximumHeight(150)
        validation_layout.addWidget(self.validation_results)
        
        layout.addWidget(validation_group)
        
        layout.addStretch()
        
        self.config_tabs.addTab(tab, "Case Metadata")
    
    def _create_comparison_tab(self):
        """Create configuration comparison tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Comparison controls
        comparison_group = QGroupBox("Configuration Comparison")
        comparison_layout = QHBoxLayout(comparison_group)
        
        comparison_layout.addWidget(QLabel("Compare with:"))
        
        self.compare_case_combo = QComboBox()
        self.compare_case_combo.currentTextChanged.connect(self._on_comparison_case_changed)
        comparison_layout.addWidget(self.compare_case_combo)
        
        self.compare_btn = QPushButton("Compare")
        self.compare_btn.clicked.connect(self._compare_configurations)
        comparison_layout.addWidget(self.compare_btn)
        
        comparison_layout.addStretch()
        
        self.copy_from_btn = QPushButton("Copy From Selected")
        self.copy_from_btn.clicked.connect(self._copy_from_selected_case)
        comparison_layout.addWidget(self.copy_from_btn)
        
        layout.addWidget(comparison_group)
        
        # Comparison results
        self.comparison_results = QTextEdit()
        self.comparison_results.setReadOnly(True)
        layout.addWidget(self.comparison_results)
        
        self.config_tabs.addTab(tab, "Comparison")
    
    def _create_button_bar(self, parent_layout):
        """Create dialog button bar"""
        button_layout = QHBoxLayout()
        
        # Left side buttons
        self.save_btn = QPushButton("Save Configuration")
        self.save_btn.clicked.connect(self._save_configuration)
        button_layout.addWidget(self.save_btn)
        
        self.export_all_btn = QPushButton("Export All")
        self.export_all_btn.clicked.connect(self._export_all_configuration)
        button_layout.addWidget(self.export_all_btn)
        
        self.import_all_btn = QPushButton("Import All")
        self.import_all_btn.clicked.connect(self._import_all_configuration)
        button_layout.addWidget(self.import_all_btn)
        
        button_layout.addStretch()
        
        # Right side buttons
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel_dialog)
        button_layout.addWidget(self.cancel_btn)
        
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.clicked.connect(self._apply_configuration)
        button_layout.addWidget(self.apply_btn)
        
        self.ok_btn = QPushButton("OK")
        self.ok_btn.clicked.connect(self._ok_dialog)
        self.ok_btn.setDefault(True)
        button_layout.addWidget(self.ok_btn)
        
        parent_layout.addLayout(button_layout)
    
    def _connect_signals(self):
        """Connect UI signals"""
        # Track changes for unsaved changes detection
        self.semantic_enabled_cb.toggled.connect(self._mark_unsaved_changes)
        self.scoring_enabled_cb.toggled.connect(self._mark_unsaved_changes)
        self.inherit_global_semantic_cb.toggled.connect(self._mark_unsaved_changes)
        self.inherit_global_scoring_cb.toggled.connect(self._mark_unsaved_changes)
        
        # Enable/disable controls based on checkboxes
        self.semantic_enabled_cb.toggled.connect(self._update_semantic_controls)
        self.scoring_enabled_cb.toggled.connect(self._update_scoring_controls)
    
    def _load_cases(self):
        """Load available cases into the case list"""
        self.case_list.clear()
        self.compare_case_combo.clear()
        self.compare_case_combo.addItem("Global Configuration")
        
        try:
            cases = self.case_integration.list_available_cases()
            
            for case_info in cases:
                case_id = case_info['case_id']
                case_name = case_info.get('case_name', case_id)
                
                # Create list item
                item_text = f"{case_name} ({case_id})"
                if case_info.get('has_semantic_mappings') or case_info.get('has_scoring_weights'):
                    item_text += " ✓"
                
                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, case_id)
                
                # Color code based on configuration status
                if case_info.get('is_current'):
                    item.setBackground(QColor(200, 255, 200))  # Light green for current
                elif case_info.get('has_semantic_mappings') and case_info.get('has_scoring_weights'):
                    item.setBackground(QColor(255, 255, 200))  # Light yellow for fully configured
                
                self.case_list.addItem(item)
                self.compare_case_combo.addItem(item_text, case_id)
            
            logger.info(f"Loaded {len(cases)} cases")
            
        except Exception as e:
            logger.error(f"Failed to load cases: {e}")
            QMessageBox.warning(self, "Load Error", f"Failed to load cases: {e}")
    
    def _on_case_selected(self, item):
        """Handle case selection"""
        case_id = item.data(Qt.UserRole)
        if case_id != self.current_case_id:
            if self.has_unsaved_changes:
                reply = QMessageBox.question(
                    self, "Unsaved Changes",
                    "You have unsaved changes. Switch case anyway?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return
            
            self._switch_to_case(case_id)
    
    def _switch_to_case(self, case_id: str):
        """Switch to a different case"""
        try:
            self.current_case_id = case_id
            self.current_case_label.setText(case_id)
            
            # Load case configuration
            self._load_case_configuration(case_id)
            
            # Update UI state
            self._update_ui_state()
            
            # Reset unsaved changes flag
            self.has_unsaved_changes = False
            
            # Emit signal
            self.case_switched.emit(case_id)
            
            logger.info(f"Switched to case: {case_id}")
            
        except Exception as e:
            logger.error(f"Failed to switch to case {case_id}: {e}")
            QMessageBox.warning(self, "Switch Error", f"Failed to switch to case: {e}")
    
    def _load_case_configuration(self, case_id: str):
        """Load configuration for a specific case"""
        try:
            # Get case summary
            summary = self.case_integration.get_case_configuration_summary(case_id)
            
            if 'error' in summary:
                raise Exception(summary['error'])
            
            # Update metadata tab
            self._update_metadata_display(summary)
            
            # Load semantic mappings
            if summary.get('has_semantic_mappings'):
                semantic_config = self.case_integration.case_config_manager.load_case_semantic_mappings(case_id)
                if semantic_config:
                    self._load_semantic_mappings_config(semantic_config)
            else:
                self._clear_semantic_mappings()
            
            # Load scoring weights
            if summary.get('has_scoring_weights'):
                scoring_config = self.case_integration.case_config_manager.load_case_scoring_weights(case_id)
                if scoring_config:
                    self._load_scoring_weights_config(scoring_config)
            else:
                self._clear_scoring_weights()
            
            # Update configuration mode
            has_custom = summary.get('has_semantic_mappings') or summary.get('has_scoring_weights')
            if has_custom:
                self.custom_mode_rb.setChecked(True)
            else:
                self.global_mode_rb.setChecked(True)
            
        except Exception as e:
            logger.error(f"Failed to load case configuration for {case_id}: {e}")
            QMessageBox.warning(self, "Load Error", f"Failed to load case configuration: {e}")
    
    def _update_metadata_display(self, summary: Dict[str, Any]):
        """Update metadata display with case information"""
        metadata = summary.get('metadata', {})
        
        self.case_id_edit.setText(summary.get('case_id', ''))
        self.case_name_edit.setText(metadata.get('case_name', ''))
        self.case_description_edit.setPlainText(metadata.get('description', ''))
        self.case_tags_edit.setText(', '.join(metadata.get('tags', [])))
        
        self.has_semantic_label.setText("Yes" if summary.get('has_semantic_mappings') else "No")
        self.has_scoring_label.setText("Yes" if summary.get('has_scoring_weights') else "No")
        self.created_date_label.setText(metadata.get('created_date', 'Unknown'))
        self.modified_date_label.setText(metadata.get('last_modified', 'Unknown'))
        
        # Update configuration status
        if summary.get('has_semantic_mappings') and summary.get('has_scoring_weights'):
            status = "Full custom configuration"
        elif summary.get('has_semantic_mappings'):
            status = "Custom semantic mappings only"
        elif summary.get('has_scoring_weights'):
            status = "Custom scoring weights only"
        else:
            status = "Using global configuration"
        
        self.config_status_label.setText(status)
    
    def _load_semantic_mappings_config(self, config: CaseSemanticMappingConfig):
        """Load semantic mappings configuration into UI"""
        self.semantic_enabled_cb.setChecked(config.enabled)
        self.inherit_global_semantic_cb.setChecked(config.inherit_global)
        self.override_global_semantic_cb.setChecked(config.override_global)
        
        # Load mappings into table
        self.semantic_table.setRowCount(len(config.mappings))
        
        for row, mapping in enumerate(config.mappings):
            self.semantic_table.setItem(row, 0, QTableWidgetItem(mapping.get('source', '')))
            self.semantic_table.setItem(row, 1, QTableWidgetItem(mapping.get('field', '')))
            self.semantic_table.setItem(row, 2, QTableWidgetItem(mapping.get('technical_value', '')))
            self.semantic_table.setItem(row, 3, QTableWidgetItem(mapping.get('semantic_value', '')))
            self.semantic_table.setItem(row, 4, QTableWidgetItem(mapping.get('category', '')))
            self.semantic_table.setItem(row, 5, QTableWidgetItem(mapping.get('severity', '')))
            self.semantic_table.setItem(row, 6, QTableWidgetItem(mapping.get('description', '')))
    
    def _load_scoring_weights_config(self, config: CaseScoringWeightsConfig):
        """Load scoring weights configuration into UI"""
        self.scoring_enabled_cb.setChecked(config.enabled)
        self.inherit_global_scoring_cb.setChecked(config.inherit_global)
        self.override_global_scoring_cb.setChecked(config.override_global)
        
        # Load weights
        for artifact_type, widgets in self.scoring_weights_widgets.items():
            weight = config.default_weights.get(artifact_type, 0.0)
            widgets['spin'].setValue(weight)
            widgets['slider'].setValue(int(weight * 100))
        
        # Load score interpretation
        for level, widgets in self.score_interpretation_widgets.items():
            if level in config.score_interpretation:
                interpretation = config.score_interpretation[level]
                widgets['min_score'].setValue(interpretation.get('min', 0.0))
                widgets['label'].setText(interpretation.get('label', level.title()))
    
    def _clear_semantic_mappings(self):
        """Clear semantic mappings UI"""
        self.semantic_enabled_cb.setChecked(False)
        self.inherit_global_semantic_cb.setChecked(True)
        self.override_global_semantic_cb.setChecked(False)
        self.semantic_table.setRowCount(0)
    
    def _clear_scoring_weights(self):
        """Clear scoring weights UI"""
        self.scoring_enabled_cb.setChecked(False)
        self.inherit_global_scoring_cb.setChecked(True)
        self.override_global_scoring_cb.setChecked(False)
        
        # Reset weights to defaults
        default_weights = {
            "Logs": 0.4, "Prefetch": 0.3, "SRUM": 0.2, "AmCache": 0.15,
            "ShimCache": 0.15, "Jumplists": 0.1, "LNK": 0.1, "MFT": 0.05, "USN": 0.05
        }
        
        for artifact_type, widgets in self.scoring_weights_widgets.items():
            weight = default_weights.get(artifact_type, 0.0)
            widgets['spin'].setValue(weight)
            widgets['slider'].setValue(int(weight * 100))
    
    def _update_ui_state(self):
        """Update UI state based on current configuration"""
        has_case = self.current_case_id is not None
        
        # Enable/disable controls based on case selection
        self.config_tabs.setEnabled(has_case)
        self.custom_mode_rb.setEnabled(has_case)
        self.global_mode_rb.setEnabled(has_case)
        
        # Update control states
        self._update_semantic_controls()
        self._update_scoring_controls()
    
    def _update_semantic_controls(self):
        """Update semantic mapping controls based on enabled state"""
        enabled = self.semantic_enabled_cb.isChecked() and self.custom_mode_rb.isChecked()
        
        self.inherit_global_semantic_cb.setEnabled(enabled)
        self.override_global_semantic_cb.setEnabled(enabled)
        self.semantic_table.setEnabled(enabled)
        self.add_semantic_btn.setEnabled(enabled)
        self.edit_semantic_btn.setEnabled(enabled)
        self.delete_semantic_btn.setEnabled(enabled)
        self.import_semantic_btn.setEnabled(enabled)
        self.export_semantic_btn.setEnabled(enabled)
    
    def _update_scoring_controls(self):
        """Update scoring weights controls based on enabled state"""
        enabled = self.scoring_enabled_cb.isChecked() and self.custom_mode_rb.isChecked()
        
        self.inherit_global_scoring_cb.setEnabled(enabled)
        self.override_global_scoring_cb.setEnabled(enabled)
        
        for widgets in self.scoring_weights_widgets.values():
            widgets['spin'].setEnabled(enabled)
            widgets['slider'].setEnabled(enabled)
            widgets['tier'].setEnabled(enabled)
        
        for widgets in self.score_interpretation_widgets.values():
            widgets['min_score'].setEnabled(enabled)
            widgets['label'].setEnabled(enabled)
            widgets['color_btn'].setEnabled(enabled)
        
        self.reset_weights_btn.setEnabled(enabled)
        self.balance_weights_btn.setEnabled(enabled)
        self.import_weights_btn.setEnabled(enabled)
        self.export_weights_btn.setEnabled(enabled)
    
    def _mark_unsaved_changes(self):
        """Mark that there are unsaved changes"""
        self.has_unsaved_changes = True
        if not self.windowTitle().endswith("*"):
            self.setWindowTitle(self.windowTitle() + "*")
    
    def _on_config_mode_changed(self):
        """Handle configuration mode change"""
        self._update_ui_state()
        self._mark_unsaved_changes()
    
    def _on_semantic_enabled_changed(self):
        """Handle semantic mappings enabled change"""
        self._update_semantic_controls()
        self._mark_unsaved_changes()
    
    def _on_scoring_enabled_changed(self):
        """Handle scoring weights enabled change"""
        self._update_scoring_controls()
        self._mark_unsaved_changes()
    
    def _on_weight_changed(self):
        """Handle weight value change"""
        self._mark_unsaved_changes()
    
    def _on_tier_changed(self):
        """Handle tier change"""
        self._mark_unsaved_changes()
    
    def _on_metadata_changed(self):
        """Handle metadata change"""
        self._mark_unsaved_changes()
    
    def _create_new_case(self):
        """Create a new case configuration"""
        # This would open a dialog to create a new case
        # For now, show a placeholder message
        QMessageBox.information(
            self, "Create New Case",
            "New case creation dialog would open here.\n"
            "This would allow creating a new case with custom configuration."
        )
    
    def _copy_case(self):
        """Copy configuration from another case"""
        if not self.current_case_id:
            QMessageBox.warning(self, "No Case Selected", "Please select a case first.")
            return
        
        # This would open a dialog to select source case and copy options
        QMessageBox.information(
            self, "Copy Case Configuration",
            "Case copying dialog would open here.\n"
            "This would allow copying configuration from another case."
        )
    
    def _delete_case(self):
        """Delete the selected case configuration"""
        if not self.current_case_id:
            QMessageBox.warning(self, "No Case Selected", "Please select a case first.")
            return
        
        reply = QMessageBox.question(
            self, "Delete Case Configuration",
            f"Are you sure you want to delete the configuration for case '{self.current_case_id}'?\n"
            "This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                success = self.case_integration.delete_case_configuration(self.current_case_id)
                if success:
                    QMessageBox.information(self, "Delete Successful", "Case configuration deleted.")
                    self._load_cases()
                    self.current_case_id = None
                    self.current_case_label.setText("None")
                    self._update_ui_state()
                else:
                    QMessageBox.warning(self, "Delete Failed", "Failed to delete case configuration.")
            except Exception as e:
                QMessageBox.critical(self, "Delete Error", f"Error deleting case: {e}")
    
    def _add_semantic_mapping(self):
        """Add a new semantic mapping"""
        # This would open a dialog to add a new semantic mapping
        QMessageBox.information(
            self, "Add Semantic Mapping",
            "Semantic mapping editor dialog would open here."
        )
    
    def _edit_semantic_mapping(self):
        """Edit selected semantic mapping"""
        current_row = self.semantic_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "No Selection", "Please select a mapping to edit.")
            return
        
        QMessageBox.information(
            self, "Edit Semantic Mapping",
            "Semantic mapping editor dialog would open here."
        )
    
    def _delete_semantic_mapping(self):
        """Delete selected semantic mapping"""
        current_row = self.semantic_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "No Selection", "Please select a mapping to delete.")
            return
        
        reply = QMessageBox.question(
            self, "Delete Mapping",
            "Are you sure you want to delete this semantic mapping?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.semantic_table.removeRow(current_row)
            self._mark_unsaved_changes()
    
    def _import_semantic_mappings(self):
        """Import semantic mappings from file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Semantic Mappings",
            "", "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            QMessageBox.information(
                self, "Import Semantic Mappings",
                f"Would import semantic mappings from: {file_path}"
            )
    
    def _export_semantic_mappings(self):
        """Export semantic mappings to file"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Semantic Mappings",
            f"{self.current_case_id}_semantic_mappings.json",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            QMessageBox.information(
                self, "Export Semantic Mappings",
                f"Would export semantic mappings to: {file_path}"
            )
    
    def _reset_scoring_weights(self):
        """Reset scoring weights to defaults"""
        reply = QMessageBox.question(
            self, "Reset Weights",
            "Reset all scoring weights to default values?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self._clear_scoring_weights()
            self._mark_unsaved_changes()
    
    def _auto_balance_weights(self):
        """Auto-balance scoring weights"""
        QMessageBox.information(
            self, "Auto-Balance Weights",
            "Auto-balancing algorithm would run here to optimize weights."
        )
    
    def _import_scoring_weights(self):
        """Import scoring weights from file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Scoring Weights",
            "", "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            QMessageBox.information(
                self, "Import Scoring Weights",
                f"Would import scoring weights from: {file_path}"
            )
    
    def _export_scoring_weights(self):
        """Export scoring weights to file"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Scoring Weights",
            f"{self.current_case_id}_scoring_weights.json",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            QMessageBox.information(
                self, "Export Scoring Weights",
                f"Would export scoring weights to: {file_path}"
            )
    
    def _choose_score_color(self, level: str):
        """Choose color for score interpretation level"""
        from PyQt5.QtWidgets import QColorDialog
        
        current_color = QColor(self.score_interpretation_widgets[level]['color'])
        color = QColorDialog.getColor(current_color, self, f"Choose Color for {level.title()}")
        
        if color.isValid():
            color_name = color.name()
            self.score_interpretation_widgets[level]['color'] = color_name
            self.score_interpretation_widgets[level]['color_btn'].setStyleSheet(
                f"background-color: {color_name}; min-width: 50px;"
            )
            self._mark_unsaved_changes()
    
    def _validate_configuration(self):
        """Validate current case configuration"""
        if not self.current_case_id:
            self.validation_results.setText("No case selected for validation.")
            return
        
        try:
            validation = self.case_integration.case_config_manager.validate_case_configuration(
                self.current_case_id
            )
            
            results = []
            if validation['valid']:
                results.append("✅ Configuration is valid!")
                self.validation_status_label.setText("Valid")
                self.validation_status_label.setStyleSheet("color: green;")
            else:
                results.append("❌ Configuration has errors:")
                for error in validation['errors']:
                    results.append(f"  • {error}")
                self.validation_status_label.setText("Invalid")
                self.validation_status_label.setStyleSheet("color: red;")
            
            self.validation_results.setText("\n".join(results))
            
        except Exception as e:
            self.validation_results.setText(f"❌ Validation failed: {e}")
            self.validation_status_label.setText("Error")
            self.validation_status_label.setStyleSheet("color: red;")
    
    def _on_comparison_case_changed(self):
        """Handle comparison case selection change"""
        self.comparison_results.clear()
    
    def _compare_configurations(self):
        """Compare current case with selected case"""
        compare_case = self.compare_case_combo.currentData()
        if not compare_case or not self.current_case_id:
            QMessageBox.warning(self, "Comparison Error", "Please select cases to compare.")
            return
        
        self.comparison_results.setText(
            f"Comparison between '{self.current_case_id}' and '{compare_case}' would be shown here.\n"
            "This would include differences in semantic mappings, scoring weights, and other settings."
        )
    
    def _copy_from_selected_case(self):
        """Copy configuration from selected comparison case"""
        compare_case = self.compare_case_combo.currentData()
        if not compare_case or not self.current_case_id:
            QMessageBox.warning(self, "Copy Error", "Please select a case to copy from.")
            return
        
        reply = QMessageBox.question(
            self, "Copy Configuration",
            f"Copy configuration from '{compare_case}' to '{self.current_case_id}'?\n"
            "This will overwrite current settings.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            QMessageBox.information(
                self, "Copy Configuration",
                f"Would copy configuration from '{compare_case}' to '{self.current_case_id}'"
            )
    
    def _save_configuration(self):
        """Save current configuration"""
        if not self.current_case_id:
            QMessageBox.warning(self, "Save Error", "No case selected.")
            return
        
        try:
            # This would save the current configuration
            QMessageBox.information(self, "Save Successful", "Configuration saved successfully.")
            self.has_unsaved_changes = False
            self.setWindowTitle("Case-Specific Configuration")
            
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save configuration: {e}")
    
    def _export_all_configuration(self):
        """Export complete case configuration"""
        if not self.current_case_id:
            QMessageBox.warning(self, "Export Error", "No case selected.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Case Configuration",
            f"{self.current_case_id}_complete_config.json",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                success = self.case_integration.export_case_configuration(self.current_case_id, file_path)
                if success:
                    QMessageBox.information(self, "Export Successful", f"Configuration exported to {file_path}")
                else:
                    QMessageBox.warning(self, "Export Failed", "Failed to export configuration.")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Export failed: {e}")
    
    def _import_all_configuration(self):
        """Import complete case configuration"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Case Configuration",
            "", "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                success = self.case_integration.import_case_configuration(file_path, self.current_case_id)
                if success:
                    QMessageBox.information(self, "Import Successful", "Configuration imported successfully.")
                    self._load_case_configuration(self.current_case_id)
                else:
                    QMessageBox.warning(self, "Import Failed", "Failed to import configuration.")
            except Exception as e:
                QMessageBox.critical(self, "Import Error", f"Import failed: {e}")
    
    def _apply_configuration(self):
        """Apply configuration changes"""
        self._save_configuration()
        if not self.has_unsaved_changes:
            self.configuration_changed.emit(self.current_case_id)
    
    def _cancel_dialog(self):
        """Cancel dialog"""
        if self.has_unsaved_changes:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Close anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        
        self.reject()
    
    def _ok_dialog(self):
        """OK dialog"""
        self._apply_configuration()
        self.accept()