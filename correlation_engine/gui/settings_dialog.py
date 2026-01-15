"""
Settings Dialog

Provides configuration UI for enabling/disabling semantic mapping, weighted scoring,
and other integrated features in the Crow-Eye system.
"""

import logging
from typing import Optional, Dict, Any
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QLabel,
    QCheckBox, QSpinBox, QDoubleSpinBox, QLineEdit, QPushButton,
    QGroupBox, QFormLayout, QComboBox, QTextEdit, QMessageBox,
    QFileDialog, QSlider, QFrame, QScrollArea, QGridLayout
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QIcon

from ..config.integrated_configuration_manager import (
    IntegratedConfigurationManager, IntegratedConfiguration,
    SemanticMappingConfig, WeightedScoringConfig, ProgressTrackingConfig,
    EngineSelectionConfig, CaseSpecificConfig
)

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """
    Settings dialog for integrated configuration management.
    
    Provides UI for enabling/disabling and configuring:
    - Semantic mapping system
    - Weighted scoring system
    - Progress tracking system
    - Engine selection preferences
    - Case-specific configurations
    """
    
    # Signal emitted when configuration changes
    configuration_changed = pyqtSignal(object)  # IntegratedConfiguration
    
    def __init__(self, config_manager: IntegratedConfigurationManager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.original_config = config_manager.get_effective_configuration()
        self.current_config = IntegratedConfiguration(**self.original_config.__dict__)
        
        self.setWindowTitle("Crow-Eye Settings")
        self.setModal(True)
        self.resize(800, 600)
        
        self._setup_ui()
        self._load_current_settings()
        self._connect_signals()
    
    def _setup_ui(self):
        """Setup the user interface"""
        layout = QVBoxLayout(self)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        
        # Create tabs
        self._create_semantic_mapping_tab()
        self._create_weighted_scoring_tab()
        self._create_progress_tracking_tab()
        self._create_engine_selection_tab()
        self._create_case_specific_tab()
        self._create_advanced_tab()
        
        # Create button bar
        button_layout = QHBoxLayout()
        
        self.reset_button = QPushButton("Reset to Defaults")
        self.reset_button.clicked.connect(self._reset_to_defaults)
        button_layout.addWidget(self.reset_button)
        
        button_layout.addStretch()
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self._apply_settings)
        button_layout.addWidget(self.apply_button)
        
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self._ok_clicked)
        self.ok_button.setDefault(True)
        button_layout.addWidget(self.ok_button)
        
        layout.addLayout(button_layout)
    
    def _create_semantic_mapping_tab(self):
        """Create semantic mapping configuration tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Main enable/disable group
        main_group = QGroupBox("Semantic Mapping System")
        main_layout = QFormLayout(main_group)
        
        self.semantic_enabled_cb = QCheckBox("Enable semantic mapping")
        self.semantic_enabled_cb.setToolTip("Enable automatic mapping of technical values to human-readable meanings")
        main_layout.addRow(self.semantic_enabled_cb)
        
        # Global mappings configuration
        global_group = QGroupBox("Global Configuration")
        global_layout = QFormLayout(global_group)
        
        self.global_mappings_path_edit = QLineEdit()
        self.global_mappings_path_edit.setToolTip("Path to global semantic mappings file")
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._browse_global_mappings_path)
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.global_mappings_path_edit)
        path_layout.addWidget(browse_button)
        global_layout.addRow("Global mappings file:", path_layout)
        
        self.fallback_to_raw_cb = QCheckBox("Fallback to raw values when mapping fails")
        self.fallback_to_raw_cb.setToolTip("Use original technical values when semantic mapping is not available")
        global_layout.addRow(self.fallback_to_raw_cb)
        
        self.log_mapping_stats_cb = QCheckBox("Log mapping statistics")
        self.log_mapping_stats_cb.setToolTip("Log detailed statistics about semantic mapping operations")
        global_layout.addRow(self.log_mapping_stats_cb)
        
        # Case-specific configuration
        case_group = QGroupBox("Case-Specific Configuration")
        case_layout = QFormLayout(case_group)
        
        self.case_semantic_enabled_cb = QCheckBox("Enable case-specific semantic mappings")
        self.case_semantic_enabled_cb.setToolTip("Allow cases to override global semantic mappings")
        case_layout.addRow(self.case_semantic_enabled_cb)
        
        self.case_semantic_path_edit = QLineEdit()
        self.case_semantic_path_edit.setToolTip("Path template for case-specific mappings (use {case_id} placeholder)")
        case_layout.addRow("Case mappings path template:", self.case_semantic_path_edit)
        
        # Mapping management group
        mapping_mgmt_group = QGroupBox("Mapping Management")
        mapping_mgmt_layout = QHBoxLayout(mapping_mgmt_group)
        
        self.add_mapping_btn = QPushButton("Add Semantic Mapping...")
        self.add_mapping_btn.setToolTip("Create a new semantic mapping (simple or advanced with AND/OR logic)")
        self.add_mapping_btn.clicked.connect(self._open_add_mapping_dialog)
        mapping_mgmt_layout.addWidget(self.add_mapping_btn)
        
        mapping_mgmt_layout.addStretch()
        
        # Add groups to layout
        layout.addWidget(main_group)
        layout.addWidget(global_group)
        layout.addWidget(case_group)
        layout.addWidget(mapping_mgmt_group)
        layout.addStretch()
        
        self.tab_widget.addTab(tab, "Semantic Mapping")
    
    def _create_weighted_scoring_tab(self):
        """Create weighted scoring configuration tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Main enable/disable group
        main_group = QGroupBox("Weighted Scoring System")
        main_layout = QFormLayout(main_group)
        
        self.scoring_enabled_cb = QCheckBox("Enable weighted scoring")
        self.scoring_enabled_cb.setToolTip("Enable calculation of weighted relevance scores for correlation matches")
        main_layout.addRow(self.scoring_enabled_cb)
        
        self.fallback_to_simple_cb = QCheckBox("Fallback to simple count when scoring fails")
        self.fallback_to_simple_cb.setToolTip("Use simple match counting when weighted scoring encounters errors")
        main_layout.addRow(self.fallback_to_simple_cb)
        
        # Score interpretation configuration
        interpretation_group = QGroupBox("Score Interpretation")
        interpretation_layout = QGridLayout(interpretation_group)
        
        interpretation_layout.addWidget(QLabel("Level"), 0, 0)
        interpretation_layout.addWidget(QLabel("Minimum Score"), 0, 1)
        interpretation_layout.addWidget(QLabel("Label"), 0, 2)
        
        self.score_interpretation_widgets = {}
        levels = ["confirmed", "probable", "weak", "minimal"]
        for i, level in enumerate(levels):
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
            
            self.score_interpretation_widgets[level] = {
                'min_score': min_score_spin,
                'label': label_edit
            }
        
        # Default weights configuration
        weights_group = QGroupBox("Default Artifact Weights")
        weights_layout = QGridLayout(weights_group)
        
        weights_layout.addWidget(QLabel("Artifact Type"), 0, 0)
        weights_layout.addWidget(QLabel("Weight"), 0, 1)
        weights_layout.addWidget(QLabel("Slider"), 0, 2)
        
        self.default_weights_widgets = {}
        
        # Get artifact types from registry
        try:
            from ..config.artifact_type_registry import get_registry
            registry = get_registry()
            artifact_types = registry.get_all_types()
        except Exception as e:
            # Fallback to hard-coded list if registry fails
            artifact_types = ["Logs", "Prefetch", "SRUM", "AmCache", "ShimCache", "Jumplists", "LNK", "MFT", "USN"]
        
        for i, artifact_type in enumerate(artifact_types):
            row = i + 1
            
            type_label = QLabel(artifact_type)
            weights_layout.addWidget(type_label, row, 0)
            
            weight_spin = QDoubleSpinBox()
            weight_spin.setRange(0.0, 1.0)
            weight_spin.setSingleStep(0.05)
            weight_spin.setDecimals(2)
            weights_layout.addWidget(weight_spin, row, 1)
            
            weight_slider = QSlider(Qt.Horizontal)
            weight_slider.setRange(0, 100)
            weight_slider.valueChanged.connect(lambda v, spin=weight_spin: spin.setValue(v / 100.0))
            weight_spin.valueChanged.connect(lambda v, slider=weight_slider: slider.setValue(int(v * 100)))
            weights_layout.addWidget(weight_slider, row, 2)
            
            self.default_weights_widgets[artifact_type] = {
                'spin': weight_spin,
                'slider': weight_slider
            }
        
        # Case-specific configuration
        case_group = QGroupBox("Case-Specific Configuration")
        case_layout = QFormLayout(case_group)
        
        self.case_scoring_enabled_cb = QCheckBox("Enable case-specific scoring weights")
        self.case_scoring_enabled_cb.setToolTip("Allow cases to override global scoring weights")
        case_layout.addRow(self.case_scoring_enabled_cb)
        
        self.case_scoring_path_edit = QLineEdit()
        self.case_scoring_path_edit.setToolTip("Path template for case-specific weights (use {case_id} placeholder)")
        case_layout.addRow("Case weights path template:", self.case_scoring_path_edit)
        
        # Create scrollable area for the tab content
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.addWidget(main_group)
        scroll_layout.addWidget(interpretation_group)
        scroll_layout.addWidget(weights_group)
        scroll_layout.addWidget(case_group)
        scroll_layout.addStretch()
        
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        layout.addWidget(scroll_area)
        
        self.tab_widget.addTab(tab, "Weighted Scoring")
    
    def _create_progress_tracking_tab(self):
        """Create progress tracking configuration tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Main enable/disable group
        main_group = QGroupBox("Progress Tracking System")
        main_layout = QFormLayout(main_group)
        
        self.progress_enabled_cb = QCheckBox("Enable progress tracking")
        self.progress_enabled_cb.setToolTip("Enable real-time progress tracking during correlation operations")
        main_layout.addRow(self.progress_enabled_cb)
        
        # Update frequency
        self.update_frequency_spin = QSpinBox()
        self.update_frequency_spin.setRange(100, 5000)
        self.update_frequency_spin.setSingleStep(100)
        self.update_frequency_spin.setSuffix(" ms")
        self.update_frequency_spin.setToolTip("How often to update progress display (lower = more responsive, higher = less CPU usage)")
        main_layout.addRow("Update frequency:", self.update_frequency_spin)
        
        # Display options
        display_group = QGroupBox("Display Options")
        display_layout = QFormLayout(display_group)
        
        self.show_memory_usage_cb = QCheckBox("Show memory usage")
        self.show_memory_usage_cb.setToolTip("Display current memory usage in progress information")
        display_layout.addRow(self.show_memory_usage_cb)
        
        self.show_time_estimates_cb = QCheckBox("Show time estimates")
        self.show_time_estimates_cb.setToolTip("Display estimated time remaining for operations")
        display_layout.addRow(self.show_time_estimates_cb)
        
        self.log_progress_events_cb = QCheckBox("Log progress events")
        self.log_progress_events_cb.setToolTip("Log detailed progress information to console")
        display_layout.addRow(self.log_progress_events_cb)
        
        # Output options
        output_group = QGroupBox("Output Options")
        output_layout = QFormLayout(output_group)
        
        self.terminal_output_cb = QCheckBox("Enable terminal output")
        self.terminal_output_cb.setToolTip("Show progress information in terminal/console")
        output_layout.addRow(self.terminal_output_cb)
        
        self.gui_updates_cb = QCheckBox("Enable GUI updates")
        self.gui_updates_cb.setToolTip("Update GUI progress widgets (disable for better performance)")
        output_layout.addRow(self.gui_updates_cb)
        
        # Add groups to layout
        layout.addWidget(main_group)
        layout.addWidget(display_group)
        layout.addWidget(output_group)
        layout.addStretch()
        
        self.tab_widget.addTab(tab, "Progress Tracking")
    
    def _create_engine_selection_tab(self):
        """Create engine selection configuration tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Engine preferences
        engine_group = QGroupBox("Engine Selection Preferences")
        engine_layout = QFormLayout(engine_group)
        
        self.default_engine_combo = QComboBox()
        self.default_engine_combo.addItems(["identity_based", "time_window"])
        self.default_engine_combo.setToolTip("Default correlation engine to use for new analyses")
        engine_layout.addRow("Default engine:", self.default_engine_combo)
        
        self.show_engine_comparison_cb = QCheckBox("Show engine comparison")
        self.show_engine_comparison_cb.setToolTip("Display comparison information when selecting engines")
        engine_layout.addRow(self.show_engine_comparison_cb)
        
        self.show_engine_capabilities_cb = QCheckBox("Show engine capabilities")
        self.show_engine_capabilities_cb.setToolTip("Display detailed capability information for each engine")
        engine_layout.addRow(self.show_engine_capabilities_cb)
        
        self.allow_engine_switching_cb = QCheckBox("Allow engine switching")
        self.allow_engine_switching_cb.setToolTip("Allow users to switch between engines during analysis")
        engine_layout.addRow(self.allow_engine_switching_cb)
        
        # Add groups to layout
        layout.addWidget(engine_group)
        layout.addStretch()
        
        self.tab_widget.addTab(tab, "Engine Selection")
    
    def _create_case_specific_tab(self):
        """Create case-specific configuration tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Current case info
        current_case_group = QGroupBox("Current Case Configuration")
        current_case_layout = QFormLayout(current_case_group)
        
        self.current_case_label = QLabel("No case loaded")
        current_case_layout.addRow("Current case:", self.current_case_label)
        
        self.case_config_mode_label = QLabel("Global settings")
        current_case_layout.addRow("Configuration mode:", self.case_config_mode_label)
        
        # Case-specific options
        case_options_group = QGroupBox("Case-Specific Options")
        case_options_layout = QFormLayout(case_options_group)
        
        self.use_case_mappings_cb = QCheckBox("Use case-specific semantic mappings")
        self.use_case_mappings_cb.setToolTip("Override global semantic mappings for this case")
        case_options_layout.addRow(self.use_case_mappings_cb)
        
        self.use_case_scoring_cb = QCheckBox("Use case-specific scoring weights")
        self.use_case_scoring_cb.setToolTip("Override global scoring weights for this case")
        case_options_layout.addRow(self.use_case_scoring_cb)
        
        # Case management buttons
        case_management_group = QGroupBox("Case Configuration Management")
        case_management_layout = QVBoxLayout(case_management_group)
        
        button_layout = QHBoxLayout()
        
        self.create_case_config_btn = QPushButton("Create Case Configuration")
        self.create_case_config_btn.setToolTip("Create custom configuration for the current case")
        self.create_case_config_btn.clicked.connect(self._create_case_configuration)
        button_layout.addWidget(self.create_case_config_btn)
        
        self.reset_case_config_btn = QPushButton("Reset to Global")
        self.reset_case_config_btn.setToolTip("Reset case to use global configuration")
        self.reset_case_config_btn.clicked.connect(self._reset_case_configuration)
        button_layout.addWidget(self.reset_case_config_btn)
        
        case_management_layout.addLayout(button_layout)
        
        # Export/Import buttons
        export_layout = QHBoxLayout()
        
        self.export_case_config_btn = QPushButton("Export Case Config")
        self.export_case_config_btn.setToolTip("Export case configuration to file")
        self.export_case_config_btn.clicked.connect(self._export_case_configuration)
        export_layout.addWidget(self.export_case_config_btn)
        
        self.import_case_config_btn = QPushButton("Import Case Config")
        self.import_case_config_btn.setToolTip("Import case configuration from file")
        self.import_case_config_btn.clicked.connect(self._import_case_configuration)
        export_layout.addWidget(self.import_case_config_btn)
        
        case_management_layout.addLayout(export_layout)
        
        # Add groups to layout
        layout.addWidget(current_case_group)
        layout.addWidget(case_options_group)
        layout.addWidget(case_management_group)
        layout.addStretch()
        
        self.tab_widget.addTab(tab, "Case-Specific")
    
    def _create_advanced_tab(self):
        """Create advanced configuration tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Configuration validation
        validation_group = QGroupBox("Configuration Validation")
        validation_layout = QVBoxLayout(validation_group)
        
        validate_button = QPushButton("Validate Current Configuration")
        validate_button.clicked.connect(self._validate_configuration)
        validation_layout.addWidget(validate_button)
        
        self.validation_results = QTextEdit()
        self.validation_results.setReadOnly(True)
        self.validation_results.setMaximumHeight(150)
        validation_layout.addWidget(self.validation_results)
        
        # Configuration export/import
        export_group = QGroupBox("Configuration Management")
        export_layout = QHBoxLayout(export_group)
        
        export_button = QPushButton("Export Configuration")
        export_button.clicked.connect(self._export_configuration)
        export_layout.addWidget(export_button)
        
        import_button = QPushButton("Import Configuration")
        import_button.clicked.connect(self._import_configuration)
        export_layout.addWidget(import_button)
        
        # Configuration info
        info_group = QGroupBox("Configuration Information")
        info_layout = QFormLayout(info_group)
        
        self.config_version_label = QLabel()
        info_layout.addRow("Version:", self.config_version_label)
        
        self.config_created_label = QLabel()
        info_layout.addRow("Created:", self.config_created_label)
        
        self.config_modified_label = QLabel()
        info_layout.addRow("Last modified:", self.config_modified_label)
        
        # Add groups to layout
        layout.addWidget(validation_group)
        layout.addWidget(export_group)
        layout.addWidget(info_group)
        layout.addStretch()
        
        self.tab_widget.addTab(tab, "Advanced")
    
    def _load_current_settings(self):
        """Load current settings into UI controls"""
        config = self.current_config
        
        # Semantic mapping settings
        self.semantic_enabled_cb.setChecked(config.semantic_mapping.enabled)
        self.global_mappings_path_edit.setText(config.semantic_mapping.global_mappings_path)
        self.fallback_to_raw_cb.setChecked(config.semantic_mapping.fallback_to_raw_values)
        self.log_mapping_stats_cb.setChecked(config.semantic_mapping.log_mapping_statistics)
        
        case_semantic = config.semantic_mapping.case_specific
        self.case_semantic_enabled_cb.setChecked(case_semantic.get('enabled', True))
        self.case_semantic_path_edit.setText(case_semantic.get('storage_path', 'cases/{case_id}/semantic_mappings.json'))
        
        # Weighted scoring settings
        self.scoring_enabled_cb.setChecked(config.weighted_scoring.enabled)
        self.fallback_to_simple_cb.setChecked(config.weighted_scoring.fallback_to_simple_count)
        
        # Score interpretation
        for level, widgets in self.score_interpretation_widgets.items():
            if level in config.weighted_scoring.score_interpretation:
                interpretation = config.weighted_scoring.score_interpretation[level]
                widgets['min_score'].setValue(interpretation.get('min', 0.0))
                widgets['label'].setText(interpretation.get('label', level.title()))
        
        # Default weights
        for artifact_type, widgets in self.default_weights_widgets.items():
            weight = config.weighted_scoring.default_weights.get(artifact_type, 0.0)
            widgets['spin'].setValue(weight)
            widgets['slider'].setValue(int(weight * 100))
        
        case_scoring = config.weighted_scoring.case_specific
        self.case_scoring_enabled_cb.setChecked(case_scoring.get('enabled', True))
        self.case_scoring_path_edit.setText(case_scoring.get('storage_path', 'cases/{case_id}/scoring_weights.json'))
        
        # Progress tracking settings
        self.progress_enabled_cb.setChecked(config.progress_tracking.enabled)
        self.update_frequency_spin.setValue(config.progress_tracking.update_frequency_ms)
        self.show_memory_usage_cb.setChecked(config.progress_tracking.show_memory_usage)
        self.show_time_estimates_cb.setChecked(config.progress_tracking.show_time_estimates)
        self.log_progress_events_cb.setChecked(config.progress_tracking.log_progress_events)
        self.terminal_output_cb.setChecked(config.progress_tracking.terminal_output_enabled)
        self.gui_updates_cb.setChecked(config.progress_tracking.gui_updates_enabled)
        
        # Engine selection settings
        self.default_engine_combo.setCurrentText(config.engine_selection.default_engine)
        self.show_engine_comparison_cb.setChecked(config.engine_selection.show_engine_comparison)
        self.show_engine_capabilities_cb.setChecked(config.engine_selection.show_engine_capabilities)
        self.allow_engine_switching_cb.setChecked(config.engine_selection.allow_engine_switching)
        
        # Case-specific settings
        if config.case_specific:
            self.current_case_label.setText(config.case_specific.case_id)
            self.use_case_mappings_cb.setChecked(config.case_specific.use_case_specific_mappings)
            self.use_case_scoring_cb.setChecked(config.case_specific.use_case_specific_scoring)
            
            if config.case_specific.use_case_specific_mappings or config.case_specific.use_case_specific_scoring:
                self.case_config_mode_label.setText("Case-specific settings")
            else:
                self.case_config_mode_label.setText("Global settings")
        else:
            self.current_case_label.setText("No case loaded")
            self.case_config_mode_label.setText("Global settings")
            self.use_case_mappings_cb.setChecked(False)
            self.use_case_scoring_cb.setChecked(False)
        
        # Advanced settings
        self.config_version_label.setText(config.version)
        self.config_created_label.setText(config.created_date)
        self.config_modified_label.setText(config.last_modified)
    
    def _connect_signals(self):
        """Connect UI signals to update methods"""
        # Enable/disable controls based on main checkboxes
        self.semantic_enabled_cb.toggled.connect(self._update_semantic_controls)
        self.scoring_enabled_cb.toggled.connect(self._update_scoring_controls)
        self.progress_enabled_cb.toggled.connect(self._update_progress_controls)
        
        # Update controls initially
        self._update_semantic_controls()
        self._update_scoring_controls()
        self._update_progress_controls()
    
    def _update_semantic_controls(self):
        """Update semantic mapping controls based on enabled state"""
        enabled = self.semantic_enabled_cb.isChecked()
        
        # Enable/disable related controls
        self.global_mappings_path_edit.setEnabled(enabled)
        self.fallback_to_raw_cb.setEnabled(enabled)
        self.log_mapping_stats_cb.setEnabled(enabled)
        self.case_semantic_enabled_cb.setEnabled(enabled)
        self.case_semantic_path_edit.setEnabled(enabled and self.case_semantic_enabled_cb.isChecked())
    
    def _update_scoring_controls(self):
        """Update weighted scoring controls based on enabled state"""
        enabled = self.scoring_enabled_cb.isChecked()
        
        # Enable/disable related controls
        self.fallback_to_simple_cb.setEnabled(enabled)
        
        for widgets in self.score_interpretation_widgets.values():
            widgets['min_score'].setEnabled(enabled)
            widgets['label'].setEnabled(enabled)
        
        for widgets in self.default_weights_widgets.values():
            widgets['spin'].setEnabled(enabled)
            widgets['slider'].setEnabled(enabled)
        
        self.case_scoring_enabled_cb.setEnabled(enabled)
        self.case_scoring_path_edit.setEnabled(enabled and self.case_scoring_enabled_cb.isChecked())
    
    def _update_progress_controls(self):
        """Update progress tracking controls based on enabled state"""
        enabled = self.progress_enabled_cb.isChecked()
        
        # Enable/disable related controls
        self.update_frequency_spin.setEnabled(enabled)
        self.show_memory_usage_cb.setEnabled(enabled)
        self.show_time_estimates_cb.setEnabled(enabled)
        self.log_progress_events_cb.setEnabled(enabled)
        self.terminal_output_cb.setEnabled(enabled)
        self.gui_updates_cb.setEnabled(enabled)
    
    def _browse_global_mappings_path(self):
        """Browse for global semantic mappings file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Global Semantic Mappings File",
            self.global_mappings_path_edit.text(),
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            self.global_mappings_path_edit.setText(file_path)
    
    def _create_case_configuration(self):
        """Create case-specific configuration"""
        if not self.current_config.case_specific:
            QMessageBox.information(
                self,
                "No Case Loaded",
                "Please load a case first before creating case-specific configuration."
            )
            return
        
        # Open case-specific configuration dialog
        try:
            from .case_specific_configuration_dialog import CaseSpecificConfigurationDialog
            from ..integration.case_specific_configuration_integration import CaseSpecificConfigurationIntegration
            
            # Create integration if not exists
            case_integration = CaseSpecificConfigurationIntegration()
            
            # Open dialog
            dialog = CaseSpecificConfigurationDialog(
                case_integration=case_integration,
                current_case_id=self.current_config.case_specific.case_id,
                parent=self
            )
            
            # Connect signals
            dialog.configuration_changed.connect(self._on_case_configuration_changed)
            
            # Show dialog
            if dialog.exec_() == QDialog.Accepted:
                # Reload settings to reflect changes
                self.current_config = self.config_manager.get_effective_configuration()
                self._load_current_settings()
                
                QMessageBox.information(
                    self,
                    "Case Configuration Updated",
                    "Case-specific configuration has been updated successfully."
                )
            
        except ImportError as e:
            logger.error(f"Failed to import case configuration dialog: {e}")
            QMessageBox.critical(
                self,
                "Import Error",
                "Failed to load case configuration dialog. Please check the installation."
            )
        except Exception as e:
            logger.error(f"Failed to open case configuration dialog: {e}")
            QMessageBox.critical(
                self,
                "Configuration Error",
                f"Failed to open case configuration dialog: {e}"
            )
    
    def _reset_case_configuration(self):
        """Reset case to use global configuration"""
        reply = QMessageBox.question(
            self,
            "Reset Case Configuration",
            "Are you sure you want to reset this case to use global configuration? "
            "Any case-specific settings will be lost.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.use_case_mappings_cb.setChecked(False)
            self.use_case_scoring_cb.setChecked(False)
            self.case_config_mode_label.setText("Global settings")
    
    def _export_case_configuration(self):
        """Export case configuration to file"""
        if not self.current_config.case_specific:
            QMessageBox.information(
                self,
                "No Case Configuration",
                "No case-specific configuration to export."
            )
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Case Configuration",
            f"case_config_{self.current_config.case_specific.case_id}.json",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                if self.config_manager.export_configuration(file_path, include_case_specific=True):
                    QMessageBox.information(
                        self,
                        "Export Successful",
                        f"Case configuration exported to {file_path}"
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "Export Failed",
                        "Failed to export case configuration. Check the logs for details."
                    )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Export Error",
                    f"Error exporting configuration: {str(e)}"
                )
    
    def _import_case_configuration(self):
        """Import case configuration from file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Case Configuration",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                if self.config_manager.import_configuration(file_path, apply_immediately=False):
                    # Reload settings from updated configuration
                    self.current_config = self.config_manager.get_effective_configuration()
                    self._load_current_settings()
                    
                    QMessageBox.information(
                        self,
                        "Import Successful",
                        f"Case configuration imported from {file_path}"
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "Import Failed",
                        "Failed to import case configuration. Check the logs for details."
                    )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Import Error",
                    f"Error importing configuration: {str(e)}"
                )
    
    def _validate_configuration(self):
        """Validate current configuration"""
        try:
            # Get current settings from UI
            current_config = self._get_current_settings()
            
            # Validate configuration
            validation_result = self.config_manager.validate_configuration(current_config)
            
            # Display results
            results_text = []
            
            if validation_result['valid']:
                results_text.append("✅ Configuration is valid!")
            else:
                results_text.append("❌ Configuration has errors:")
                for error in validation_result['errors']:
                    results_text.append(f"  • {error}")
            
            if validation_result['warnings']:
                results_text.append("\n⚠️ Warnings:")
                for warning in validation_result['warnings']:
                    results_text.append(f"  • {warning}")
            
            if validation_result['fixes']:
                results_text.append(f"\n🔧 {len(validation_result['fixes'])} suggested fixes available")
            
            self.validation_results.setText("\n".join(results_text))
            
        except Exception as e:
            self.validation_results.setText(f"❌ Validation failed: {str(e)}")
    
    def _export_configuration(self):
        """Export complete configuration to file"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Configuration",
            "crow_eye_config.json",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                if self.config_manager.export_configuration(file_path, include_case_specific=True):
                    QMessageBox.information(
                        self,
                        "Export Successful",
                        f"Configuration exported to {file_path}"
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "Export Failed",
                        "Failed to export configuration. Check the logs for details."
                    )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Export Error",
                    f"Error exporting configuration: {str(e)}"
                )
    
    def _import_configuration(self):
        """Import complete configuration from file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Configuration",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            reply = QMessageBox.question(
                self,
                "Import Configuration",
                "Importing configuration will replace current settings. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                try:
                    if self.config_manager.import_configuration(file_path, apply_immediately=False):
                        # Reload settings from updated configuration
                        self.current_config = self.config_manager.get_effective_configuration()
                        self._load_current_settings()
                        
                        QMessageBox.information(
                            self,
                            "Import Successful",
                            f"Configuration imported from {file_path}"
                        )
                    else:
                        QMessageBox.warning(
                            self,
                            "Import Failed",
                            "Failed to import configuration. Check the logs for details."
                        )
                except Exception as e:
                    QMessageBox.critical(
                        self,
                        "Import Error",
                        f"Error importing configuration: {str(e)}"
                    )
    
    def _reset_to_defaults(self):
        """Reset all settings to defaults"""
        reply = QMessageBox.question(
            self,
            "Reset to Defaults",
            "Are you sure you want to reset all settings to defaults? "
            "This will lose all current configuration.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.current_config = IntegratedConfiguration()
            self._load_current_settings()
    
    def _get_current_settings(self) -> IntegratedConfiguration:
        """Get current settings from UI controls"""
        # Create new configuration from UI values
        semantic_config = SemanticMappingConfig(
            enabled=self.semantic_enabled_cb.isChecked(),
            global_mappings_path=self.global_mappings_path_edit.text(),
            case_specific={
                "enabled": self.case_semantic_enabled_cb.isChecked(),
                "storage_path": self.case_semantic_path_edit.text()
            },
            fallback_to_raw_values=self.fallback_to_raw_cb.isChecked(),
            log_mapping_statistics=self.log_mapping_stats_cb.isChecked()
        )
        
        # Score interpretation
        score_interpretation = {}
        for level, widgets in self.score_interpretation_widgets.items():
            score_interpretation[level] = {
                "min": widgets['min_score'].value(),
                "label": widgets['label'].text()
            }
        
        # Default weights
        default_weights = {}
        for artifact_type, widgets in self.default_weights_widgets.items():
            default_weights[artifact_type] = widgets['spin'].value()
        
        scoring_config = WeightedScoringConfig(
            enabled=self.scoring_enabled_cb.isChecked(),
            score_interpretation=score_interpretation,
            default_weights=default_weights,
            case_specific={
                "enabled": self.case_scoring_enabled_cb.isChecked(),
                "storage_path": self.case_scoring_path_edit.text()
            },
            fallback_to_simple_count=self.fallback_to_simple_cb.isChecked()
        )
        
        progress_config = ProgressTrackingConfig(
            enabled=self.progress_enabled_cb.isChecked(),
            update_frequency_ms=self.update_frequency_spin.value(),
            show_memory_usage=self.show_memory_usage_cb.isChecked(),
            show_time_estimates=self.show_time_estimates_cb.isChecked(),
            log_progress_events=self.log_progress_events_cb.isChecked(),
            terminal_output_enabled=self.terminal_output_cb.isChecked(),
            gui_updates_enabled=self.gui_updates_cb.isChecked()
        )
        
        engine_config = EngineSelectionConfig(
            default_engine=self.default_engine_combo.currentText(),
            show_engine_comparison=self.show_engine_comparison_cb.isChecked(),
            show_engine_capabilities=self.show_engine_capabilities_cb.isChecked(),
            allow_engine_switching=self.allow_engine_switching_cb.isChecked()
        )
        
        # Case-specific configuration
        case_config = None
        if self.current_config.case_specific:
            case_config = CaseSpecificConfig(
                case_id=self.current_config.case_specific.case_id,
                use_case_specific_mappings=self.use_case_mappings_cb.isChecked(),
                use_case_specific_scoring=self.use_case_scoring_cb.isChecked(),
                semantic_mappings_path=self.current_config.case_specific.semantic_mappings_path,
                scoring_weights_path=self.current_config.case_specific.scoring_weights_path
            )
        
        return IntegratedConfiguration(
            semantic_mapping=semantic_config,
            weighted_scoring=scoring_config,
            progress_tracking=progress_config,
            engine_selection=engine_config,
            case_specific=case_config
        )
    
    def _apply_settings(self):
        """Apply current settings without closing dialog and trigger live reload"""
        try:
            # Get current settings from UI
            new_config = self._get_current_settings()
            
            # Validate configuration
            validation_result = self.config_manager.validate_configuration(new_config)
            
            if not validation_result['valid']:
                reply = QMessageBox.question(
                    self,
                    "Configuration Errors",
                    f"Configuration has {len(validation_result['errors'])} errors. Apply anyway?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                
                if reply != QMessageBox.Yes:
                    return
            
            # Get old configuration for change notification
            old_config = self.config_manager.get_effective_configuration()
            
            # Update configuration manager
            self.config_manager.global_config = new_config
            
            # Save configuration (this triggers observer notifications automatically)
            self.config_manager._save_global_configuration()
            
            # Update effective configuration
            self.config_manager._update_effective_configuration()
            
            # Update current config
            self.current_config = new_config
            
            # Notify configuration change handler (if exists)
            try:
                from ..config.configuration_change_handler import notify_configuration_change
                notify_configuration_change(old_config, new_config)
            except ImportError:
                pass  # Handler may not exist
            
            # Emit signal
            self.configuration_changed.emit(new_config)
            
            # Show success message with reload information
            QMessageBox.information(
                self,
                "Settings Applied",
                "Configuration has been applied and reloaded successfully.\n\n"
                "All active integrations have been notified and will use the new configuration.\n"
                "Changes will take effect immediately for new correlations."
            )
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            QMessageBox.critical(
                self,
                "Apply Error",
                f"Error applying settings: {str(e)}\n\nSee logs for details."
            )
            import logging
            logging.error(f"Failed to apply settings: {error_details}")
    
    def _ok_clicked(self):
        """Apply settings and close dialog"""
        self._apply_settings()
        self.accept()
    
    def _on_case_configuration_changed(self, case_id: str):
        """Handle case configuration changes"""
        try:
            logger.info(f"Case configuration changed for case: {case_id}")
            
            # Reload effective configuration
            self.current_config = self.config_manager.get_effective_configuration()
            self._load_current_settings()
            
            # Emit configuration changed signal
            self.configuration_changed.emit(self.current_config)
            
        except Exception as e:
            logger.error(f"Failed to handle case configuration change: {e}")
            QMessageBox.warning(
                self,
                "Configuration Update Error",
                f"Failed to update configuration after case changes: {e}"
            )

    def _open_add_mapping_dialog(self):
        """Open the SemanticMappingDialog to add a new global mapping"""
        try:
            from ..wings.ui.semantic_mapping_dialog import SemanticMappingDialog
            
            # Open dialog with global scope - user can choose simple or advanced mode
            dialog = SemanticMappingDialog(
                parent=self,
                mapping=None,
                scope='global',
                wing_id=None,
                mode='simple'  # Default to simple, user can switch to advanced
            )
            
            if dialog.exec_() == QDialog.Accepted:
                # Check if it's an advanced rule or simple mapping
                rule = dialog.get_rule()
                
                if rule and len(rule.conditions) > 0:
                    # Advanced rule with conditions
                    try:
                        from ..config.semantic_mapping import SemanticMappingManager
                        
                        manager = SemanticMappingManager()
                        manager.add_rule(rule)
                        
                        QMessageBox.information(
                            self,
                            "Rule Added",
                            f"Semantic rule added:\n{rule.name} → {rule.semantic_value}"
                        )
                        logger.info(f"Added global semantic rule: {rule.name}")
                        
                    except Exception as e:
                        logger.error(f"Failed to add semantic rule: {e}")
                        QMessageBox.warning(self, "Error", f"Failed to add rule: {e}")
                else:
                    # Simple mapping
                    mapping_data = dialog.get_mapping()
                    if mapping_data:
                        try:
                            from ..config.semantic_mapping import SemanticMapping, SemanticMappingManager
                            
                            mapping = SemanticMapping(
                                source=mapping_data.get('source', ''),
                                field=mapping_data.get('field', ''),
                                technical_value=mapping_data.get('technical_value', ''),
                                semantic_value=mapping_data.get('semantic_value', ''),
                                description=mapping_data.get('description', ''),
                                scope='global'
                            )
                            
                            manager = SemanticMappingManager()
                            manager.add_mapping(mapping)
                            
                            QMessageBox.information(
                                self,
                                "Mapping Added",
                                f"Semantic mapping added:\n{mapping_data.get('technical_value')} → {mapping_data.get('semantic_value')}"
                            )
                            logger.info(f"Added global semantic mapping: {mapping_data.get('source')}.{mapping_data.get('field')}")
                            
                        except Exception as e:
                            logger.error(f"Failed to add semantic mapping: {e}")
                            QMessageBox.warning(self, "Error", f"Failed to add mapping: {e}")
                    
        except ImportError as e:
            logger.error(f"Failed to import SemanticMappingDialog: {e}")
            QMessageBox.critical(self, "Import Error", "Failed to load Semantic Mapping Dialog.")
        except Exception as e:
            logger.error(f"Failed to open semantic mapping dialog: {e}")
            QMessageBox.critical(self, "Error", f"Failed to open dialog: {e}")
    
