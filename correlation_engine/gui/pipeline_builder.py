"""
Pipeline Builder Widget
Interface for creating and editing pipeline configurations.
"""

import os
from datetime import datetime
from typing import Optional, List
from pathlib import Path

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QLineEdit,
    QTextEdit, QPushButton, QListWidget, QListWidgetItem, QFileDialog,
    QMessageBox, QSplitter, QFormLayout, QMenu
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QIcon
from .ui_styling import CorrelationEngineStyles


from ..config import PipelineConfig, FeatherConfig, WingConfig
from ..integration.feather_mappings import (
    detect_artifact_type_from_name, 
    get_artifact_type_info,
    get_parent_artifact_type,
    ENHANCED_ARTIFACT_TYPES
)


class PipelineBuilderWidget(QWidget):
    """Widget for building and editing pipeline configurations"""
    
    pipeline_modified = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.current_pipeline: Optional[PipelineConfig] = None
        self.config_manager = None  # Will be set by correlation integration
        self.case_directory = None  # Case directory for extracting case name
        self.case_name = None  # Extracted case name
        
        # File monitoring
        self._feathers_watch_dir = None
        self._wings_watch_dir = None
        self._known_feather_configs = set()
        self._known_wing_configs = set()
        self._watch_timer = QTimer()
        self._watch_timer.timeout.connect(self._check_for_new_configs)
        self._watch_timer.setInterval(2000)  # Check every 2 seconds
        
        self._init_ui()
        
    def set_config_manager(self, config_manager):
        """
        Set Configuration Manager and connect signals.
        
        Args:
            config_manager: ConfigurationManager instance
        """
        self.config_manager = config_manager
        
        # Connect signals for real-time updates
        if self.config_manager:
            self.config_manager.feather_added.connect(self._on_feather_added)
            self.config_manager.feather_removed.connect(self._on_feather_removed)
            self.config_manager.wing_added.connect(self._on_wing_added)
            self.config_manager.wing_removed.connect(self._on_wing_removed)
            self.config_manager.configurations_loaded.connect(self._on_configurations_loaded)
            print("[Pipeline Builder] Connected to Configuration Manager signals")
    
    def set_case_directory(self, case_directory: str):
        """
        Set the case directory and extract case name.
        
        Args:
            case_directory: Path to the case directory
        """
        self.case_directory = case_directory
        self.case_name = self._extract_case_name(case_directory)
        
        # Update case name display
        self.case_name_display.setText(self.case_name)
        
        # Update pipeline name if it's empty or default
        if self.name_input.text().strip() == "" or self.name_input.text().strip() == "New Pipeline":
            self._set_default_pipeline_name()
        
        # Set up watch directories for the case's Correlation folder
        from pathlib import Path
        correlation_dir = Path(case_directory) / "Correlation"
        self._feathers_watch_dir = correlation_dir / "feathers"
        self._wings_watch_dir = correlation_dir / "wings"
        
        # Initialize known configs
        if self._feathers_watch_dir.exists():
            self._known_feather_configs = set(f.stem for f in self._feathers_watch_dir.glob("*.json"))
        else:
            self._known_feather_configs = set()
            
        if self._wings_watch_dir.exists():
            self._known_wing_configs = set(f.stem for f in self._wings_watch_dir.glob("*.json"))
        else:
            self._known_wing_configs = set()
        
        print(f"[Pipeline Builder] Case directory set: {case_directory}")
        print(f"[Pipeline Builder] Extracted case name: {self.case_name}")
        print(f"[Pipeline Builder] Feathers watch dir: {self._feathers_watch_dir}")
        print(f"[Pipeline Builder] Wings watch dir: {self._wings_watch_dir}")
    
    def _extract_case_name(self, case_directory: str) -> str:
        """
        Extract case name from case directory path.
        
        Args:
            case_directory: Path to the case directory
            
        Returns:
            Extracted case name
        """
        from pathlib import Path
        
        # Get the directory name (last component of path)
        case_path = Path(case_directory)
        case_name = case_path.name
        
        # Clean up the case name (remove special characters, keep alphanumeric and spaces)
        import re
        case_name = re.sub(r'[^\w\s-]', '', case_name)
        case_name = case_name.strip()
        
        # If empty after cleaning, use a default
        if not case_name:
            case_name = "UnknownCase"
        
        return case_name
    
    def _set_default_pipeline_name(self):
        """Set default pipeline name based on case name."""
        if self.case_name:
            default_name = f"{self.case_name}_Pipeline"
            self.name_input.setText(default_name)
            print(f"[Pipeline Builder] Set default pipeline name: {default_name}")
    
    def _validate_pipeline_name_uniqueness(self, pipeline_name: str) -> tuple[bool, Optional[str]]:
        """
        Validate that pipeline name is unique in the case directory.
        
        Args:
            pipeline_name: Pipeline name to validate
            
        Returns:
            Tuple of (is_unique, error_message)
        """
        if not self.case_directory:
            return (True, None)  # Can't validate without case directory
        
        from pathlib import Path
        
        # Check pipelines directory
        pipelines_dir = Path(self.case_directory) / "Correlation" / "pipelines"
        
        if not pipelines_dir.exists():
            return (True, None)  # No pipelines yet, so it's unique
        
        # Generate config name from pipeline name
        config_name = pipeline_name.strip().replace(' ', '_').lower()
        expected_filename = f"{config_name}.json"
        
        # Check if file exists
        pipeline_file = pipelines_dir / expected_filename
        
        # If we're editing an existing pipeline, allow the same name
        if self.current_pipeline and self.current_pipeline.pipeline_name == pipeline_name:
            return (True, None)
        
        if pipeline_file.exists():
            return (False, f"A pipeline named '{pipeline_name}' already exists in this case")
        
        return (True, None)
    
    def _init_ui(self):
        """Initialize the user interface"""
        layout = QVBoxLayout(self)
        
        # Create top bar with output directory
        top_bar = self._create_top_bar()
        layout.addWidget(top_bar)
        
        # Create splitter for main layout
        splitter = QSplitter(Qt.Vertical)
        layout.addWidget(splitter)
        
        # Metadata section
        metadata_group = self._create_metadata_section()
        splitter.addWidget(metadata_group)
        
        # Feathers and Wings section
        components_widget = QWidget()
        components_layout = QHBoxLayout(components_widget)
        
        # Feathers section
        feathers_group = self._create_feathers_section()
        components_layout.addWidget(feathers_group)
        
        # Wings section
        wings_group = self._create_wings_section()
        components_layout.addWidget(wings_group)
        
        splitter.addWidget(components_widget)
        
        # Validation status section
        validation_group = self._create_validation_section()
        layout.addWidget(validation_group)
        
        # Set splitter sizes
        splitter.setSizes([200, 350])
    
    def _create_top_bar(self) -> QWidget:
        """Create top bar with output directory"""
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 10)
        
        # Add stretch to push output directory to the right
        top_layout.addStretch()
        
        # Output directory label
        output_label = QLabel("Output Directory:")
        output_label.setStyleSheet("font-weight: bold; color: #00FFFF;")
        top_layout.addWidget(output_label)
        
        # Output directory input
        self.output_dir_input = QLineEdit()
        self.output_dir_input.setPlaceholderText("Output directory for results and configs")
        self.output_dir_input.setText("output")
        self.output_dir_input.setMinimumWidth(300)
        self.output_dir_input.textChanged.connect(self._on_modified)
        top_layout.addWidget(self.output_dir_input)
        
        # Browse button
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_output_dir)
        top_layout.addWidget(browse_btn)
        
        return top_widget
    
    def _create_metadata_section(self) -> QGroupBox:
        """Create metadata input section"""
        group = QGroupBox("Pipeline Metadata")
        layout = QFormLayout()
        
        # Case name display (read-only, auto-populated)
        self.case_name_display = QLabel("Not set")
        self.case_name_display.setStyleSheet("color: #00FFFF; font-weight: bold;")
        layout.addRow("Case:", self.case_name_display)
        
        # Pipeline name
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter pipeline name...")
        self.name_input.textChanged.connect(self._on_pipeline_name_changed)
        layout.addRow("Pipeline Name:", self.name_input)
        
        # Pipeline name validation label
        self.name_validation_label = QLabel("")
        self.name_validation_label.setWordWrap(True)
        layout.addRow("", self.name_validation_label)
        
        # Description
        self.description_input = QTextEdit()
        self.description_input.setPlaceholderText("Enter pipeline description...")
        self.description_input.setMaximumHeight(60)
        self.description_input.textChanged.connect(self._on_modified)
        layout.addRow("Description:", self.description_input)
        
        # Case information (optional additional fields)
        self.case_name_input = QLineEdit()
        self.case_name_input.setPlaceholderText("Optional case name override...")
        self.case_name_input.textChanged.connect(self._on_modified)
        layout.addRow("Case Name (optional):", self.case_name_input)
        
        self.case_id_input = QLineEdit()
        self.case_id_input.setPlaceholderText("Optional case ID...")
        self.case_id_input.textChanged.connect(self._on_modified)
        layout.addRow("Case ID:", self.case_id_input)
        
        self.investigator_input = QLineEdit()
        self.investigator_input.setPlaceholderText("Optional investigator name...")
        self.investigator_input.textChanged.connect(self._on_modified)
        layout.addRow("Investigator:", self.investigator_input)
        
        group.setLayout(layout)
        return group
    
    def _on_pipeline_name_changed(self):
        """Handle pipeline name change with validation."""
        pipeline_name = self.name_input.text().strip()
        
        if pipeline_name:
            # Validate uniqueness
            is_unique, error_msg = self._validate_pipeline_name_uniqueness(pipeline_name)
            
            if not is_unique:
                self.name_validation_label.setText(f"⚠ {error_msg}")
                self.name_validation_label.setStyleSheet("color: #FF9800;")
            else:
                self.name_validation_label.setText("")
        else:
            self.name_validation_label.setText("")
        
        self._on_modified()
    
    def _create_feathers_section(self) -> QGroupBox:
        """Create feathers list section"""
        group = QGroupBox("Feathers")
        layout = QVBoxLayout()
        
        # Feathers list
        self.feathers_list = QListWidget()
        self.feathers_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.feathers_list.customContextMenuRequested.connect(self._show_feather_context_menu)
        self.feathers_list.itemDoubleClicked.connect(self._edit_feather)
        layout.addWidget(self.feathers_list)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        
        self.add_feather_btn = QPushButton("Add Feather")
        self.add_feather_btn.clicked.connect(self._add_feather)
        buttons_layout.addWidget(self.add_feather_btn)
        
        self.create_feather_btn = QPushButton("Create Feather")
        self.create_feather_btn.clicked.connect(self._create_feather)
        buttons_layout.addWidget(self.create_feather_btn)
        
        self.remove_feather_btn = QPushButton("Remove")
        self.remove_feather_btn.clicked.connect(self._remove_feather)
        self.remove_feather_btn.setEnabled(False)
        buttons_layout.addWidget(self.remove_feather_btn)
        
        layout.addLayout(buttons_layout)
        
        # Connect selection change
        self.feathers_list.itemSelectionChanged.connect(self._on_feather_selection_changed)
        
        group.setLayout(layout)
        return group
    
    def _create_wings_section(self) -> QGroupBox:
        """Create wings list section"""
        group = QGroupBox("Wings")
        layout = QVBoxLayout()
        
        # Wings list
        self.wings_list = QListWidget()
        self.wings_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.wings_list.customContextMenuRequested.connect(self._show_wing_context_menu)
        self.wings_list.itemDoubleClicked.connect(self._edit_wing)
        layout.addWidget(self.wings_list)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        
        self.add_wing_btn = QPushButton("Add Wing")
        self.add_wing_btn.clicked.connect(self._add_wing)
        buttons_layout.addWidget(self.add_wing_btn)
        
        self.create_wing_btn = QPushButton("Create Wing")
        self.create_wing_btn.clicked.connect(self._create_wing)
        buttons_layout.addWidget(self.create_wing_btn)
        
        self.remove_wing_btn = QPushButton("Remove")
        self.remove_wing_btn.clicked.connect(self._remove_wing)
        self.remove_wing_btn.setEnabled(False)
        buttons_layout.addWidget(self.remove_wing_btn)
        
        layout.addLayout(buttons_layout)
        
        # Connect selection change
        self.wings_list.itemSelectionChanged.connect(self._on_wing_selection_changed)
        
        group.setLayout(layout)
        return group
    
    def _create_validation_section(self) -> QGroupBox:
        """Create validation status section"""
        group = QGroupBox("Validation Status")
        layout = QVBoxLayout()
        
        self.validation_label = QLabel("No pipeline loaded")
        self.validation_label.setWordWrap(True)
        layout.addWidget(self.validation_label)
        
        group.setLayout(layout)
        return group
    
    def load_pipeline(self, pipeline: PipelineConfig):
        """
        Load pipeline configuration into builder.
        
        Args:
            pipeline: Pipeline configuration to load
        """
        self.current_pipeline = pipeline
        
        # Update case name display if we have a case name
        if self.case_name:
            self.case_name_display.setText(self.case_name)
        
        # Load metadata
        self.name_input.setText(pipeline.pipeline_name)
        self.description_input.setPlainText(pipeline.description)
        self.output_dir_input.setText(pipeline.output_directory or "output")
        self.case_name_input.setText(pipeline.case_name)
        self.case_id_input.setText(pipeline.case_id)
        self.investigator_input.setText(pipeline.investigator)
        
        # Load feathers
        self.feathers_list.clear()
        for feather_config in pipeline.feather_configs:
            self._add_feather_to_list(feather_config)
        
        # Load wings
        self.wings_list.clear()
        for wing_config in pipeline.wing_configs:
            self._add_wing_to_list(wing_config)
        
        # Validate
        self.validate_pipeline()
    
    def get_pipeline_config(self) -> Optional[PipelineConfig]:
        """
        Get current pipeline configuration.
        
        Returns:
            PipelineConfig object or None if invalid
        """
        output_dir = self.output_dir_input.text().strip() or "output"
        
        if not self.current_pipeline:
            # Create new pipeline
            config_name = self.name_input.text().strip().replace(' ', '_').lower()
            if not config_name:
                return None
            
            # Use extracted case name if available, otherwise use optional input
            case_name_value = self.case_name if self.case_name else self.case_name_input.text().strip()
            
            self.current_pipeline = PipelineConfig(
                config_name=config_name,
                pipeline_name=self.name_input.text().strip(),
                description=self.description_input.toPlainText().strip(),
                case_name=case_name_value,
                case_id=self.case_id_input.text().strip(),
                investigator=self.investigator_input.text().strip(),
                output_directory=output_dir,
                created_date=datetime.now().isoformat(),
                last_modified=datetime.now().isoformat()
            )
        else:
            # Update existing pipeline
            self.current_pipeline.pipeline_name = self.name_input.text().strip()
            self.current_pipeline.description = self.description_input.toPlainText().strip()
            
            # Use extracted case name if available, otherwise use optional input
            case_name_value = self.case_name if self.case_name else self.case_name_input.text().strip()
            self.current_pipeline.case_name = case_name_value
            
            self.current_pipeline.case_id = self.case_id_input.text().strip()
            self.current_pipeline.investigator = self.investigator_input.text().strip()
            self.current_pipeline.output_directory = output_dir
            self.current_pipeline.last_modified = datetime.now().isoformat()
        
        # Use default scoring config (semantic rules managed elsewhere)
        if not self.current_pipeline.scoring_config:
            self.current_pipeline.scoring_config = {
                'enabled': True,
                'use_weighted_scoring': True,
                'thresholds': {
                    'low': 0.3,
                    'medium': 0.5,
                    'high': 0.7,
                    'critical': 0.9
                },
                'default_tier_weights': {
                    'tier1': 1.0,
                    'tier2': 0.8,
                    'tier3': 0.6,
                    'tier4': 0.4
                }
            }
        
        # Create output directory structure
        from pathlib import Path
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectories for configs
        (output_path / "configs").mkdir(exist_ok=True)
        (output_path / "results").mkdir(exist_ok=True)
        
        return self.current_pipeline
    
    def validate_pipeline(self) -> tuple[bool, List[str]]:
        """
        Validate current pipeline configuration.
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        # Check pipeline name
        if not self.name_input.text().strip():
            errors.append("Pipeline name is required")
        else:
            # Check pipeline name uniqueness
            pipeline_name = self.name_input.text().strip()
            is_unique, error_msg = self._validate_pipeline_name_uniqueness(pipeline_name)
            if not is_unique:
                errors.append(error_msg)
        
        # Check feathers
        if self.feathers_list.count() == 0:
            errors.append("At least one feather is required")
        
        # Check wings
        if self.wings_list.count() == 0:
            errors.append("At least one wing is required")
        
        # Check wing references
        # Build a set of available feather database filenames
        feather_db_files = set()
        for i in range(self.feathers_list.count()):
            item = self.feathers_list.item(i)
            feather_data = item.data(Qt.UserRole)
            if feather_data:
                # Extract database filename
                db_path = None
                if hasattr(feather_data, 'output_database'):
                    db_path = feather_data.output_database
                elif isinstance(feather_data, dict):
                    db_path = feather_data.get('database_path', '')
                
                if db_path:
                    import os
                    db_filename = os.path.basename(db_path)
                    feather_db_files.add(db_filename)
        
        # Check if wings reference valid feathers
        for i in range(self.wings_list.count()):
            item = self.wings_list.item(i)
            wing_config = item.data(Qt.UserRole)
            if wing_config:
                for feather_ref in wing_config.feathers:
                    # Check by database filename (from feather_database_path)
                    ref_db_filename = os.path.basename(feather_ref.feather_database_path)
                    
                    if ref_db_filename not in feather_db_files:
                        errors.append(
                            f"Wing '{wing_config.wing_name}' references unknown feather "
                            f"'{ref_db_filename}'"
                        )
        
        # Update validation label
        if errors:
            self.validation_label.setText("❌ Validation failed:\n" + "\n".join(f"• {e}" for e in errors))
            self.validation_label.setStyleSheet("color: #F44336;")
        else:
            self.validation_label.setText("✓ Pipeline configuration is valid")
            self.validation_label.setStyleSheet("color: #4CAF50;")
        
        return (len(errors) == 0, errors)
    
    def _add_feather(self):
        """Add feather from file"""
        # Use output directory's configs/feathers folder
        from pathlib import Path
        output_dir = self.output_dir_input.text().strip() or "output"
        feathers_dir = Path(output_dir) / "configs" / "feathers"
        feathers_dir.mkdir(parents=True, exist_ok=True)
        
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Add Feather Configuration",
            str(feathers_dir),
            "Feather Config Files (*.json);;All Files (*)"
        )
        
        if filepath:
            try:
                feather_config = FeatherConfig.load_from_file(filepath)
                self._add_feather_to_list(feather_config)
                self._on_modified()
                self.validate_pipeline()
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Load Error",
                    f"Failed to load feather configuration:\n{str(e)}"
                )
    
    def _create_feather(self):
        """Launch Feather Creator"""
        try:
            from PyQt5.QtWidgets import QApplication
            from correlation_engine.feather.ui.main_window import FeatherBuilderWindow
            from correlation_engine.config import ConfigManager
            from pathlib import Path
            
            # Get output directory and create configs subdirectory
            output_dir = self.output_dir_input.text().strip() or "output"
            configs_dir = Path(output_dir) / "configs"
            feathers_dir = configs_dir / "feathers"
            feathers_dir.mkdir(parents=True, exist_ok=True)
            
            # Set up monitoring
            self._feathers_watch_dir = feathers_dir
            self._known_feather_configs = set(f.stem for f in feathers_dir.glob("*.json"))
            
            # Start watching for new configs
            if not self._watch_timer.isActive():
                self._watch_timer.start()
            
            # Create a new window instance
            feather_window = FeatherBuilderWindow()
            
            # Replace the config manager with one pointing to our output directory
            feather_window.config_manager = ConfigManager(str(configs_dir))
            
            # Set the save location path in the UI
            feather_window.feather_path = str(feathers_dir)
            feather_window.feather_path_input.setText(str(feathers_dir))
            
            feather_window.show()
            
            # Store reference to prevent garbage collection
            if not hasattr(self, '_child_windows'):
                self._child_windows = []
            self._child_windows.append(feather_window)
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Launch Error",
                f"Failed to open Feather Creator:\n{str(e)}"
            )
    
    def _enhance_artifact_type_display(self, feather_config: FeatherConfig) -> str:
        """
        Enhance artifact type display with detailed information.
        
        Args:
            feather_config: Feather configuration
            
        Returns:
            Enhanced display string with artifact type and forensic value
        """
        artifact_type = feather_config.artifact_type
        
        # Try to detect enhanced artifact type if not already specific
        if artifact_type in ['Registry', 'AmCache', 'SRUM', 'Logs', 'Jumplists']:
            # Try to detect more specific type from feather name
            enhanced_type = detect_artifact_type_from_name(
                feather_config.feather_name,
                getattr(feather_config, 'source_table', None),
                getattr(feather_config, 'source_database', None)
            )
            if enhanced_type != artifact_type and enhanced_type in ENHANCED_ARTIFACT_TYPES:
                artifact_type = enhanced_type
        
        # Get artifact type info
        type_info = get_artifact_type_info(artifact_type)
        
        # Create enhanced display
        display_name = f"{feather_config.feather_name} ({artifact_type})"
        
        # Add forensic value indicator
        forensic_value = type_info.get('forensic_value', 'Unknown')
        if 'High' in forensic_value:
            display_name += " 🔴"  # High value
        elif 'Medium' in forensic_value:
            display_name += " 🟡"  # Medium value
        else:
            display_name += " ⚪"  # Low/Unknown value
            
        return display_name
    
    def _create_enhanced_tooltip(self, feather_config: FeatherConfig, wing_name: str = None) -> str:
        """
        Create enhanced tooltip with artifact type information.
        
        Args:
            feather_config: Feather configuration
            wing_name: Optional wing name
            
        Returns:
            Enhanced tooltip string
        """
        artifact_type = feather_config.artifact_type
        
        # Try to detect enhanced artifact type
        if artifact_type in ['Registry', 'AmCache', 'SRUM', 'Logs', 'Jumplists']:
            enhanced_type = detect_artifact_type_from_name(
                feather_config.feather_name,
                getattr(feather_config, 'source_table', None),
                getattr(feather_config, 'source_database', None)
            )
            if enhanced_type != artifact_type and enhanced_type in ENHANCED_ARTIFACT_TYPES:
                artifact_type = enhanced_type
        
        # Get detailed info
        type_info = get_artifact_type_info(artifact_type)
        parent_type = get_parent_artifact_type(artifact_type)
        
        # Build tooltip
        tooltip_parts = []
        
        if hasattr(feather_config, 'output_database'):
            tooltip_parts.append(f"Database: {feather_config.output_database}")
        
        tooltip_parts.append(f"Artifact Type: {artifact_type}")
        
        if parent_type != artifact_type:
            tooltip_parts.append(f"Category: {parent_type}")
        
        tooltip_parts.append(f"Description: {type_info.get('description', 'No description')}")
        tooltip_parts.append(f"Forensic Value: {type_info.get('forensic_value', 'Unknown')}")
        
        if wing_name:
            tooltip_parts.append(f"From Wing: {wing_name}")
        
        return "\n".join(tooltip_parts)
    
    def _add_feather_to_list(self, feather_config: FeatherConfig):
        """Add feather config to list widget with enhanced artifact type display"""
        display_name = self._enhance_artifact_type_display(feather_config)
        
        item = QListWidgetItem(display_name)
        item.setData(Qt.UserRole, feather_config)
        
        # Enhanced tooltip
        tooltip = self._create_enhanced_tooltip(feather_config)
        item.setToolTip(tooltip)
        
        self.feathers_list.addItem(item)
        
        # Add to pipeline if exists
        if self.current_pipeline:
            if feather_config not in self.current_pipeline.feather_configs:
                self.current_pipeline.add_feather_config(feather_config)
    
    def _remove_feather(self):
        """Remove selected feather"""
        current_item = self.feathers_list.currentItem()
        if current_item:
            feather_config = current_item.data(Qt.UserRole)
            
            # Remove from pipeline
            if self.current_pipeline and feather_config in self.current_pipeline.feather_configs:
                self.current_pipeline.feather_configs.remove(feather_config)
            
            # Remove from list
            self.feathers_list.takeItem(self.feathers_list.row(current_item))
            
            self._on_modified()
            self.validate_pipeline()
    
    def _add_wing(self):
        """Add wing from file"""
        # Use output directory's configs/wings folder
        from pathlib import Path
        output_dir = self.output_dir_input.text().strip() or "output"
        wings_dir = Path(output_dir) / "configs" / "wings"
        wings_dir.mkdir(parents=True, exist_ok=True)
        
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Add Wing Configuration",
            str(wings_dir),
            "Wing Config Files (*.json);;All Files (*)"
        )
        
        if filepath:
            try:
                wing_config = WingConfig.load_from_file(filepath)
                self._add_wing_to_list(wing_config)
                self._on_modified()
                self.validate_pipeline()
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Load Error",
                    f"Failed to load wing configuration:\n{str(e)}"
                )
    
    def _create_wing(self):
        """Launch Wing Creator"""
        try:
            from PyQt5.QtWidgets import QApplication
            from correlation_engine.wings.ui.main_window import WingsCreatorWindow
            from correlation_engine.config import ConfigManager
            from pathlib import Path
            
            # Get output directory and create configs subdirectory
            output_dir = self.output_dir_input.text().strip() or "output"
            configs_dir = Path(output_dir) / "configs"
            wings_dir = configs_dir / "wings"
            wings_dir.mkdir(parents=True, exist_ok=True)
            
            # Set up monitoring
            self._wings_watch_dir = wings_dir
            self._known_wing_configs = set(f.stem for f in wings_dir.glob("*.json"))
            
            # Start watching for new configs
            if not self._watch_timer.isActive():
                self._watch_timer.start()
            
            # Create a new window instance
            wing_window = WingsCreatorWindow()
            
            # Set case directory for feather path resolution
            case_directory = configs_dir.parent  # Go up from Correlation to case directory
            wing_window.set_case_directory(str(case_directory))
            
            # Replace the config manager with one pointing to our output directory
            wing_window.config_manager = ConfigManager(str(configs_dir))
            
            wing_window.show()
            
            # Store reference to prevent garbage collection
            if not hasattr(self, '_child_windows'):
                self._child_windows = []
            self._child_windows.append(wing_window)
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Launch Error",
                f"Failed to open Wing Creator:\n{str(e)}"
            )
    
    def _add_wing_to_list(self, wing_config: WingConfig):
        """Add wing config to list widget and automatically add its feathers"""
        item = QListWidgetItem(
            f"{wing_config.wing_name} ({len(wing_config.feathers)} feathers)"
        )
        item.setData(Qt.UserRole, wing_config)
        item.setToolTip(f"Time window: {wing_config.time_window_minutes} minutes")
        self.wings_list.addItem(item)
        
        # Add to pipeline if exists
        if self.current_pipeline:
            if wing_config not in self.current_pipeline.wing_configs:
                self.current_pipeline.add_wing_config(wing_config)
        
        # Automatically add feathers from this Wing to the feathers list
        self._add_wing_feathers_to_list(wing_config)
    
    def _add_wing_feathers_to_list(self, wing_config: WingConfig):
        """
        Automatically add feathers from a Wing to the feathers list.
        
        This method implements Requirement 5: Feather Loading from Wings
        - Automatically loads all feathers referenced by the wing
        - Resolves feather paths relative to case Correlation directory
        - Creates placeholder entries for missing feathers
        - Avoids adding duplicate feathers
        - Validates that feather database files exist
        
        Args:
            wing_config: WingConfig object containing feather references
        """
        if not wing_config.feathers:
            print(f"[Pipeline Builder] Wing '{wing_config.wing_name}' has no feathers to load")
            return
        
        print(f"[Pipeline Builder] Auto-loading {len(wing_config.feathers)} feathers from Wing '{wing_config.wing_name}'")
        
        # Get feathers directory - check both output dir and case correlation dir
        output_dir = self.output_dir_input.text().strip() or "output"
        feathers_dir = Path(output_dir) / "configs" / "feathers"
        
        # Resolve feather paths relative to case's Correlation/feathers/ directory (Requirement 5.2)
        case_feathers_dir = None
        if self.case_directory:
            case_feathers_dir = Path(self.case_directory) / "Correlation" / "feathers"
            print(f"[Pipeline Builder] Case feathers directory: {case_feathers_dir}")
        else:
            # Try to infer case directory from output directory
            # Output is typically: <case_dir>/Correlation/output
            output_path = Path(output_dir)
            if output_path.is_absolute():
                # Check if parent is "Correlation" folder
                if output_path.parent.name == "Correlation":
                    case_feathers_dir = output_path.parent / "feathers"
                    print(f"[Pipeline Builder] Inferred case feathers directory from output: {case_feathers_dir}")
                elif "Correlation" in str(output_path):
                    # Try to find Correlation folder in path
                    parts = output_path.parts
                    for i, part in enumerate(parts):
                        if part == "Correlation" and i < len(parts) - 1:
                            correlation_path = Path(*parts[:i+1])
                            case_feathers_dir = correlation_path / "feathers"
                            print(f"[Pipeline Builder] Found Correlation folder in path: {case_feathers_dir}")
                            break
        
        feathers_added = 0
        feathers_skipped = 0
        placeholders_created = 0
        
        for feather_ref in wing_config.feathers:
            # Extract feather name from reference
            feather_name = feather_ref.feather_config_name
            
            # Requirement 5.4: Avoid adding duplicate feathers
            already_added = False
            
            for i in range(self.feathers_list.count()):
                existing_item = self.feathers_list.item(i)
                existing_config = existing_item.data(Qt.UserRole)
                if existing_config:
                    # Check both FeatherConfig objects and metadata dicts
                    existing_name = None
                    if hasattr(existing_config, 'feather_name'):
                        existing_name = existing_config.feather_name
                    elif hasattr(existing_config, 'config_name'):
                        existing_name = existing_config.config_name
                    elif isinstance(existing_config, dict):
                        existing_name = existing_config.get('feather_id', '') or existing_config.get('feather_name', '')
                    
                    # Check for exact match or if feather_name is contained
                    if existing_name and (existing_name == feather_name or feather_name in existing_name):
                        already_added = True
                        feathers_skipped += 1
                        print(f"[Pipeline Builder] Skipping duplicate feather: {feather_name}")
                        break
            
            if already_added:
                continue
            
            # Try to load feather config from JSON file - check multiple locations
            feather_json_path = None
            
            # First, try case feathers directory (primary location for case feathers)
            if case_feathers_dir:
                test_path = case_feathers_dir / f"{feather_name}.json"
                if test_path.exists():
                    feather_json_path = test_path
            
            # If not found, try output directory
            if not feather_json_path:
                test_path = feathers_dir / f"{feather_name}.json"
                if test_path.exists():
                    feather_json_path = test_path
            
            # Requirement 5.1: Load feather config if it exists
            if feather_json_path:
                try:
                    from ..config import FeatherConfig
                    feather_config = FeatherConfig.load_from_file(str(feather_json_path))
                    
                    # Requirement 5.5: Validate that feather database file exists
                    db_path = Path(feather_config.output_database)
                    if not db_path.is_absolute() and case_feathers_dir:
                        # First try relative to case Correlation directory
                        db_path = case_feathers_dir.parent / feather_config.output_database
                        if not db_path.exists():
                            # Fallback: try just the filename in feathers directory
                            db_path = case_feathers_dir / Path(feather_config.output_database).name
                    
                    if db_path.exists():
                        # Add to feathers list with enhanced display
                        display_name = self._enhance_artifact_type_display(feather_config)
                        item = QListWidgetItem(display_name)
                        item.setData(Qt.UserRole, feather_config)
                        
                        # Enhanced tooltip
                        tooltip = self._create_enhanced_tooltip(feather_config, wing_config.wing_name)
                        item.setToolTip(tooltip)
                        
                        self.feathers_list.addItem(item)
                        
                        # Add to pipeline if exists
                        if self.current_pipeline:
                            if feather_config not in self.current_pipeline.feather_configs:
                                self.current_pipeline.add_feather_config(feather_config)
                        
                        feathers_added += 1
                        print(f"[Pipeline Builder] ✓ Auto-added feather from Wing: {feather_name} (DB exists)")
                    else:
                        print(f"[Pipeline Builder] ⚠ Warning: Feather database not found: {db_path}")
                        # Still add it but with a warning and enhanced display
                        display_name = self._enhance_artifact_type_display(feather_config) + " ⚠"
                        item = QListWidgetItem(display_name)
                        item.setData(Qt.UserRole, feather_config)
                        
                        # Enhanced tooltip with warning
                        tooltip = self._create_enhanced_tooltip(feather_config, wing_config.wing_name)
                        tooltip = f"⚠ Database not found: {feather_config.output_database}\n\n{tooltip}"
                        item.setToolTip(tooltip)
                        
                        self.feathers_list.addItem(item)
                        
                        # Add to pipeline if exists
                        if self.current_pipeline:
                            if feather_config not in self.current_pipeline.feather_configs:
                                self.current_pipeline.add_feather_config(feather_config)
                        
                        feathers_added += 1
                    
                except Exception as e:
                    print(f"[Pipeline Builder] ⚠ Error loading feather config {feather_name}: {e}")
                    # Fall through to create placeholder
                    feather_json_path = None
            
            # Requirement 5.3: Create placeholder entry for missing feathers
            if not feather_json_path:
                # Try to find the .db file to validate it exists
                feather_db_path = None
                db_exists = False
                
                # Resolve feather database path relative to case Correlation directory
                if case_feathers_dir:
                    # Try using the feather_database_path from the reference
                    if feather_ref.feather_database_path:
                        # First try the path as-is relative to case Correlation directory
                        potential_db = case_feathers_dir.parent / feather_ref.feather_database_path
                        if potential_db.exists():
                            feather_db_path = str(potential_db)
                            db_exists = True
                        else:
                            # Fallback: Extract just the filename if it's a path
                            db_filename = Path(feather_ref.feather_database_path).name
                            potential_db = case_feathers_dir / db_filename
                            if potential_db.exists():
                                feather_db_path = str(potential_db)
                                db_exists = True
                    
                    # Also try with feather_name
                    if not db_exists:
                        potential_db = case_feathers_dir / f"{feather_name}.db"
                        if potential_db.exists():
                            feather_db_path = str(potential_db)
                            db_exists = True
                
                # If still not found, use the reference path as-is
                if not feather_db_path:
                    feather_db_path = feather_ref.feather_database_path
                
                # Create a minimal FeatherConfig for the placeholder so it can be used by correlation engine
                try:
                    from ..config import FeatherConfig
                    
                    # Create minimal FeatherConfig with required fields
                    placeholder_config = FeatherConfig(
                        config_name=feather_name,
                        feather_name=feather_name,
                        artifact_type=feather_ref.artifact_type,
                        source_database="",  # Unknown for placeholder
                        source_table="",  # Unknown for placeholder
                        selected_columns=[],  # Unknown for placeholder
                        column_mapping={},  # Unknown for placeholder
                        timestamp_column="timestamp",  # Default assumption
                        timestamp_format="",  # Unknown for placeholder
                        output_database=feather_db_path
                    )
                    
                    # Create display entry
                    display_name = f"{feather_name} ({feather_ref.artifact_type})"
                    if not db_exists:
                        display_name += " ⚠"
                        print(f"[Pipeline Builder] ⚠ Warning: Creating placeholder for missing feather: {feather_name}")
                    
                    item = QListWidgetItem(display_name)
                    item.setData(Qt.UserRole, placeholder_config)
                    
                    tooltip = f"From Wing: {wing_config.wing_name}\nDatabase: {feather_db_path}"
                    if not db_exists:
                        tooltip = f"⚠ Feather not created yet - Click 'Create Feather' to build it\n{tooltip}"
                    item.setToolTip(tooltip)
                    
                    self.feathers_list.addItem(item)
                    
                    # Add to pipeline if exists
                    if self.current_pipeline:
                        if placeholder_config not in self.current_pipeline.feather_configs:
                            self.current_pipeline.add_feather_config(placeholder_config)
                    
                    placeholders_created += 1
                    print(f"[Pipeline Builder] ✓ Created placeholder FeatherConfig for: {feather_name}")
                    
                except Exception as e:
                    print(f"[Pipeline Builder] ⚠ Error creating placeholder FeatherConfig for {feather_name}: {e}")
                    # Fallback to dict-based placeholder
                    display_name = f"{feather_name} ({feather_ref.artifact_type})"
                    if not db_exists:
                        display_name += " ⚠"
                    
                    item = QListWidgetItem(display_name)
                    item.setData(Qt.UserRole, {
                        'feather_id': feather_ref.feather_id,
                        'feather_name': feather_name,
                        'artifact_type': feather_ref.artifact_type,
                        'database_path': feather_db_path,
                        'is_placeholder': True
                    })
                    
                    tooltip = f"From Wing: {wing_config.wing_name}\nDatabase: {feather_db_path}"
                    if not db_exists:
                        tooltip = f"⚠ Feather not created yet - Click 'Create Feather' to build it\n{tooltip}"
                    item.setToolTip(tooltip)
                    
                    self.feathers_list.addItem(item)
                    placeholders_created += 1
        
        # Log summary
        print(f"[Pipeline Builder] Feather auto-load summary for Wing '{wing_config.wing_name}':")
        print(f"  - Added: {feathers_added}")
        print(f"  - Skipped (duplicates): {feathers_skipped}")
        print(f"  - Placeholders created: {placeholders_created}")
        
        # Trigger validation after adding feathers
        if feathers_added > 0 or placeholders_created > 0:
            self._on_modified()
    
    def _remove_wing(self):
        """Remove selected wing"""
        current_item = self.wings_list.currentItem()
        if current_item:
            wing_config = current_item.data(Qt.UserRole)
            
            # Remove from pipeline
            if self.current_pipeline and wing_config in self.current_pipeline.wing_configs:
                self.current_pipeline.wing_configs.remove(wing_config)
            
            # Remove from list
            self.wings_list.takeItem(self.wings_list.row(current_item))
            
            self._on_modified()
            self.validate_pipeline()
    
    def _on_feather_selection_changed(self):
        """Handle feather selection change"""
        self.remove_feather_btn.setEnabled(self.feathers_list.currentItem() is not None)
    
    def _edit_feather(self, item: QListWidgetItem):
        """
        Edit selected feather by opening FeatherBuilder with the feather loaded.
        
        Args:
            item: The list widget item that was double-clicked
        """
        feather_config = item.data(Qt.UserRole)
        if not feather_config:
            QMessageBox.warning(
                self,
                "Edit Error",
                "Cannot edit this feather - no configuration data available."
            )
            return
        
        try:
            from PyQt5.QtWidgets import QApplication
            from correlation_engine.feather.ui.main_window import FeatherBuilderWindow
            from correlation_engine.config import ConfigManager
            from pathlib import Path
            
            # Get output directory
            output_dir = self.output_dir_input.text().strip() or "output"
            configs_dir = Path(output_dir) / "configs"
            feathers_dir = configs_dir / "feathers"
            feathers_dir.mkdir(parents=True, exist_ok=True)
            
            # Create a new window instance
            feather_window = FeatherBuilderWindow()
            
            # Replace the config manager with one pointing to our output directory
            feather_window.config_manager = ConfigManager(str(configs_dir))
            
            # Set the save location path in the UI
            feather_window.feather_path = str(feathers_dir)
            feather_window.feather_path_input.setText(str(feathers_dir))
            
            # Load the feather database if it exists
            if hasattr(feather_config, 'output_database'):
                db_path = feather_config.output_database
            elif isinstance(feather_config, dict):
                db_path = feather_config.get('database_path', '')
            else:
                db_path = ''
            
            if db_path and os.path.exists(db_path):
                # Set feather name and path
                feather_window.feather_path = os.path.dirname(db_path)
                feather_window.feather_name = os.path.splitext(os.path.basename(db_path))[0]
                feather_window.feather_name_input.setText(feather_window.feather_name)
                feather_window.feather_path_input.setText(feather_window.feather_path)
                
                # Detect artifact type from opened database
                feather_window.detect_artifact_type_from_database()
                
                # Initialize and load the database
                feather_window.initialize_feather_database()
                feather_window.data_viewer.set_feather_database(feather_window.feather_db)
                feather_window.data_viewer.refresh_data()
                
                feather_window.status_bar.showMessage(f"Editing feather: {db_path}")
            else:
                # Set feather name from config
                if hasattr(feather_config, 'feather_name'):
                    feather_window.feather_name_input.setText(feather_config.feather_name)
                elif isinstance(feather_config, dict):
                    feather_window.feather_name_input.setText(feather_config.get('feather_id', ''))
            
            # Set up monitoring for changes
            self._feathers_watch_dir = feathers_dir
            if not self._watch_timer.isActive():
                self._watch_timer.start()
            
            feather_window.show()
            
            # Store reference to prevent garbage collection
            if not hasattr(self, '_child_windows'):
                self._child_windows = []
            self._child_windows.append(feather_window)
            
            print(f"[Pipeline Builder] Opened feather for editing: {feather_config}")
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Edit Error",
                f"Failed to open Feather Builder for editing:\n{str(e)}"
            )
            import traceback
            traceback.print_exc()
    
    def _edit_wing(self, item: QListWidgetItem):
        """
        Edit selected wing by opening WingsCreator with the wing loaded.
        
        Args:
            item: The list widget item that was double-clicked
        """
        wing_config = item.data(Qt.UserRole)
        if not wing_config:
            QMessageBox.warning(
                self,
                "Edit Error",
                "Cannot edit this wing - no configuration data available."
            )
            return
        
        try:
            from PyQt5.QtWidgets import QApplication
            from correlation_engine.wings.ui.main_window import WingsCreatorWindow
            from correlation_engine.config import ConfigManager
            from pathlib import Path
            
            # Get output directory
            output_dir = self.output_dir_input.text().strip() or "output"
            configs_dir = Path(output_dir) / "configs"
            wings_dir = configs_dir / "wings"
            wings_dir.mkdir(parents=True, exist_ok=True)
            
            # Create a new window instance
            wing_window = WingsCreatorWindow()
            
            # Set case directory for feather path resolution
            case_directory = configs_dir.parent  # Go up from Correlation to case directory
            print(f"[Pipeline Builder] configs_dir: {configs_dir}")
            print(f"[Pipeline Builder] case_directory: {case_directory}")
            wing_window.set_case_directory(str(case_directory))
            
            # Replace the config manager with one pointing to our output directory
            wing_window.config_manager = ConfigManager(str(configs_dir))
            
            # Load the wing configuration
            if hasattr(wing_config, 'wing_name'):
                # Convert WingConfig to Wing model
                from correlation_engine.wings.core.wing_model import Wing
                
                try:
                    # Try multiple possible filenames for the wing
                    possible_filenames = []
                    
                    # First try the source filename if available
                    if hasattr(wing_config, '_source_filename'):
                        possible_filenames.append(wing_config._source_filename)
                    
                    # Then try other variations
                    possible_filenames.extend([
                        f"{wing_config.config_name}.json",
                        f"{wing_config.wing_name}.json",
                        f"{wing_config.wing_id}.json"
                    ])
                    
                    wing_file = None
                    for filename in possible_filenames:
                        test_path = wings_dir / filename
                        print(f"[Pipeline Builder] Trying wing file: {test_path}")
                        if test_path.exists():
                            wing_file = test_path
                            print(f"[Pipeline Builder] Found wing file: {wing_file}")
                            break
                    
                    if wing_file and wing_file.exists():
                        wing_window.wing = Wing.load_from_file(str(wing_file))
                        wing_window.load_wing_to_ui()
                        wing_window.status_bar.showMessage(f"Editing wing: {wing_config.wing_name}")
                        print(f"[Pipeline Builder] Loaded wing with {len(wing_window.wing.feathers)} feathers")
                        print(f"[Pipeline Builder] Opened wing for editing: {wing_config.wing_name}")
                    else:
                        print(f"[Pipeline Builder] Wing file not found in: {wings_dir}")
                        print(f"[Pipeline Builder] Tried filenames: {possible_filenames}")
                        print(f"[Pipeline Builder] Converting WingConfig to Wing with {len(wing_config.feathers)} feathers")
                        
                        # Convert WingConfig feathers to FeatherSpec objects
                        from correlation_engine.wings.core.wing_model import FeatherSpec, CorrelationRules
                        
                        feathers = []
                        for feather_ref in wing_config.feathers:
                            feather_spec = FeatherSpec(
                                feather_id=feather_ref.feather_id,
                                database_filename=feather_ref.feather_database_path,
                                artifact_type=feather_ref.artifact_type,
                                detection_confidence='high',
                                manually_overridden=True,
                                detection_method='metadata',
                                feather_config_name=getattr(feather_ref, 'feather_config_name', None),
                                weight=getattr(feather_ref, 'weight', 0.0),
                                tier=getattr(feather_ref, 'tier', 0),
                                tier_name=getattr(feather_ref, 'tier_name', '')
                            )
                            feathers.append(feather_spec)
                            print(f"[Pipeline Builder]   Converted feather: {feather_spec.feather_id}")
                        
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
                        
                        # Create Wing with feathers
                        wing_window.wing = Wing(
                            wing_id=wing_config.wing_id,
                            wing_name=wing_config.wing_name,
                            description=wing_config.description,
                            proves=wing_config.proves,
                            author=wing_config.author,
                            created_date=wing_config.created_date,
                            feathers=feathers,
                            correlation_rules=correlation_rules
                        )
                        wing_window.load_wing_to_ui()
                        wing_window.status_bar.showMessage(f"Editing wing: {wing_config.wing_name}")
                        print(f"[Pipeline Builder] Created wing with {len(wing_window.wing.feathers)} feathers")
                except Exception as e:
                    print(f"[Pipeline Builder] Error loading wing: {e}")
                    import traceback
                    traceback.print_exc()
                    QMessageBox.warning(
                        self,
                        "Load Error",
                        f"Failed to load wing configuration:\n{str(e)}"
                    )
                    return
            else:
                QMessageBox.warning(
                    self,
                    "Edit Error",
                    "Cannot edit this wing - invalid configuration format."
                )
                return
            
            # Set up monitoring for changes
            self._wings_watch_dir = wings_dir
            if not self._watch_timer.isActive():
                self._watch_timer.start()
            
            wing_window.show()
            
            # Store reference to prevent garbage collection
            if not hasattr(self, '_child_windows'):
                self._child_windows = []
            self._child_windows.append(wing_window)
            
            print(f"[Pipeline Builder] Opened wing for editing: {wing_config.wing_name}")
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Edit Error",
                f"Failed to open Wings Creator for editing:\n{str(e)}"
            )
            import traceback
            traceback.print_exc()

    
    def _on_wing_selection_changed(self):
        """Handle wing selection change"""
        self.remove_wing_btn.setEnabled(self.wings_list.currentItem() is not None)
    
    def _show_feather_context_menu(self, position):
        """Show context menu for feather item"""
        item = self.feathers_list.itemAt(position)
        if not item:
            return
        
        menu = QMenu(self)
        
        extract_action = menu.addAction("Extract Feather")
        extract_action.triggered.connect(lambda: self._extract_feather(item))
        
        menu.exec_(self.feathers_list.mapToGlobal(position))
    
    def _show_wing_context_menu(self, position):
        """Show context menu for wing item"""
        item = self.wings_list.itemAt(position)
        if not item:
            return
        
        menu = QMenu(self)
        
        extract_action = menu.addAction("Extract Wing")
        extract_action.triggered.connect(lambda: self._extract_wing(item))
        
        menu.exec_(self.wings_list.mapToGlobal(position))
    
    def _extract_feather(self, item: QListWidgetItem):
        """Extract feather to standalone config file"""
        feather_config = item.data(Qt.UserRole)
        if not feather_config:
            return
        
        # Ensure demo_configs/feathers directory exists
        from pathlib import Path
        feathers_dir = Path("demo_configs/feathers")
        feathers_dir.mkdir(parents=True, exist_ok=True)
        
        # Show save dialog
        default_name = f"{feather_config.config_name}.json"
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Extract Feather Configuration",
            str(feathers_dir / default_name),
            "JSON Files (*.json);;All Files (*)"
        )
        
        if filepath:
            try:
                # Ensure .json extension
                if not filepath.endswith('.json'):
                    filepath += '.json'
                
                # Save feather config
                feather_config.save_to_file(filepath)
                
                QMessageBox.information(
                    self,
                    "Extract Successful",
                    f"Feather configuration extracted to:\n{filepath}"
                )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Extract Error",
                    f"Failed to extract feather:\n{str(e)}"
                )
    
    def _extract_wing(self, item: QListWidgetItem):
        """Extract wing to standalone config file"""
        wing_config = item.data(Qt.UserRole)
        if not wing_config:
            return
        
        # Ensure demo_configs/wings directory exists
        from pathlib import Path
        wings_dir = Path("demo_configs/wings")
        wings_dir.mkdir(parents=True, exist_ok=True)
        
        # Show save dialog
        default_name = f"{wing_config.config_name}.json"
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Extract Wing Configuration",
            str(wings_dir / default_name),
            "JSON Files (*.json);;All Files (*)"
        )
        
        if filepath:
            try:
                # Ensure .json extension
                if not filepath.endswith('.json'):
                    filepath += '.json'
                
                # Save wing config
                wing_config.save_to_file(filepath)
                
                QMessageBox.information(
                    self,
                    "Extract Successful",
                    f"Wing configuration extracted to:\n{filepath}"
                )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Extract Error",
                    f"Failed to extract wing:\n{str(e)}"
                )
    
    def _on_modified(self):
        """Handle modification of pipeline"""
        self.pipeline_modified.emit()
        # Auto-validate when content changes
        self.validate_pipeline()
    
    def _browse_output_dir(self):
        """Browse for output directory"""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            self.output_dir_input.text() or "output"
        )
        
        if directory:
            self.output_dir_input.setText(directory)
            self._on_modified()
    
    def load_existing_configs(self):
        """Load all existing feather and wing configs from watch directories immediately"""
        print("[Pipeline Builder] Loading existing configs...")
        
        # Load existing feathers
        if self._feathers_watch_dir and self._feathers_watch_dir.exists():
            feather_files = list(self._feathers_watch_dir.glob("*.json"))
            print(f"[Pipeline Builder] Found {len(feather_files)} feather files in {self._feathers_watch_dir}")
            
            for config_path in feather_files:
                try:
                    feather_config = FeatherConfig.load_from_file(str(config_path))
                    
                    # Check if not already in list
                    already_added = False
                    for i in range(self.feathers_list.count()):
                        item = self.feathers_list.item(i)
                        existing_data = item.data(Qt.UserRole)
                        if existing_data:
                            # Handle both FeatherConfig objects and metadata dicts
                            existing_name = None
                            if hasattr(existing_data, 'config_name'):
                                existing_name = existing_data.config_name
                            elif isinstance(existing_data, dict):
                                existing_name = existing_data.get('feather_id')
                            
                            if existing_name == feather_config.config_name:
                                already_added = True
                                break
                    
                    if not already_added:
                        self._add_feather_to_list(feather_config)
                        print(f"[Pipeline Builder] ✓ Loaded feather: {feather_config.feather_name}")
                except Exception as e:
                    print(f"[Pipeline Builder] Error loading feather {config_path.name}: {e}")
            
            # Update known configs
            self._known_feather_configs = set(f.stem for f in feather_files)
        
        # Load existing wings
        if self._wings_watch_dir and self._wings_watch_dir.exists():
            wing_files = list(self._wings_watch_dir.glob("*.json"))
            print(f"[Pipeline Builder] Found {len(wing_files)} wing files in {self._wings_watch_dir}")
            
            for config_path in wing_files:
                try:
                    wing_config = WingConfig.load_from_file(str(config_path))
                    
                    # Store the original filename for later reference
                    wing_config._source_filename = config_path.name
                    
                    # Debug: print config details
                    print(f"[Pipeline Builder] Wing loaded from: {config_path.name}")
                    print(f"[Pipeline Builder]   config_name: {wing_config.config_name}")
                    print(f"[Pipeline Builder]   wing_name: {wing_config.wing_name}")
                    print(f"[Pipeline Builder]   wing_id: {wing_config.wing_id}")
                    print(f"[Pipeline Builder]   feathers: {len(wing_config.feathers)}")
                    
                    # Check if not already in list
                    already_added = False
                    for i in range(self.wings_list.count()):
                        item = self.wings_list.item(i)
                        existing_config = item.data(Qt.UserRole)
                        if existing_config and existing_config.config_name == wing_config.config_name:
                            already_added = True
                            break
                    
                    if not already_added:
                        self._add_wing_to_list(wing_config)
                        print(f"[Pipeline Builder] ✓ Loaded wing: {wing_config.wing_name}")
                except Exception as e:
                    print(f"[Pipeline Builder] Error loading wing {config_path.name}: {e}")
            
            # Update known configs
            self._known_wing_configs = set(f.stem for f in wing_files)
        
        # Validate after loading
        self.validate_pipeline()
        print(f"[Pipeline Builder] Loaded {self.feathers_list.count()} feathers and {self.wings_list.count()} wings")
    
    def _check_for_new_configs(self):
        """Check for new and modified feather and wing configs and auto-add/update them"""
        # Check for new and modified feathers
        if self._feathers_watch_dir and self._feathers_watch_dir.exists():
            current_configs = set(f.stem for f in self._feathers_watch_dir.glob("*.json"))
            new_configs = current_configs - self._known_feather_configs
            
            # Check for new feathers
            for config_name in new_configs:
                try:
                    config_path = self._feathers_watch_dir / f"{config_name}.json"
                    feather_config = FeatherConfig.load_from_file(str(config_path))
                    
                    # Check if not already in list
                    already_added = False
                    for i in range(self.feathers_list.count()):
                        item = self.feathers_list.item(i)
                        existing_config = item.data(Qt.UserRole)
                        if existing_config and existing_config.config_name == feather_config.config_name:
                            already_added = True
                            break
                    
                    if not already_added:
                        self._add_feather_to_list(feather_config)
                        self._on_modified()
                        self.show_notification(f"✓ New feather added: {feather_config.feather_name}")
                        print(f"[Pipeline Builder] ✓ Added new feather: {feather_config.feather_name}")
                except Exception as e:
                    print(f"[Pipeline Builder] Error auto-adding feather {config_name}: {e}")
            
            # Check for modified feathers (existing configs that have been updated)
            for i in range(self.feathers_list.count()):
                item = self.feathers_list.item(i)
                existing_config = item.data(Qt.UserRole)
                if existing_config and hasattr(existing_config, 'config_name'):
                    config_name = existing_config.config_name
                    config_path = self._feathers_watch_dir / f"{config_name}.json"
                    
                    if config_path.exists():
                        try:
                            # Check if file was modified
                            file_mtime = config_path.stat().st_mtime
                            
                            # Store last modified time in item data if not present
                            if not hasattr(item, '_last_mtime'):
                                item._last_mtime = file_mtime
                            elif item._last_mtime < file_mtime:
                                # File was modified, reload it
                                updated_config = FeatherConfig.load_from_file(str(config_path))
                                item.setData(Qt.UserRole, updated_config)
                                item.setText(f"{updated_config.feather_name} ({updated_config.artifact_type})")
                                item.setToolTip(f"Database: {updated_config.output_database}")
                                item._last_mtime = file_mtime
                                
                                # Update in pipeline
                                if self.current_pipeline:
                                    for j, fc in enumerate(self.current_pipeline.feather_configs):
                                        if fc.config_name == config_name:
                                            self.current_pipeline.feather_configs[j] = updated_config
                                            break
                                
                                self._on_modified()
                                self.show_notification(f"✓ Feather updated: {updated_config.feather_name}")
                                print(f"[Pipeline Builder] ✓ Updated feather: {updated_config.feather_name}")
                        except Exception as e:
                            print(f"[Pipeline Builder] Error checking feather modification {config_name}: {e}")
            
            self._known_feather_configs = current_configs
        
        # Check for new and modified wings
        if self._wings_watch_dir and self._wings_watch_dir.exists():
            current_configs = set(f.stem for f in self._wings_watch_dir.glob("*.json"))
            new_configs = current_configs - self._known_wing_configs
            
            # Check for new wings
            for config_name in new_configs:
                try:
                    config_path = self._wings_watch_dir / f"{config_name}.json"
                    wing_config = WingConfig.load_from_file(str(config_path))
                    
                    # Check if not already in list
                    already_added = False
                    for i in range(self.wings_list.count()):
                        item = self.wings_list.item(i)
                        existing_config = item.data(Qt.UserRole)
                        if existing_config and existing_config.config_name == wing_config.config_name:
                            already_added = True
                            break
                    
                    if not already_added:
                        self._add_wing_to_list(wing_config)
                        self._on_modified()
                        self.show_notification(f"✓ New wing added: {wing_config.wing_name}")
                        print(f"[Pipeline Builder] ✓ Added new wing: {wing_config.wing_name}")
                except Exception as e:
                    print(f"[Pipeline Builder] Error auto-adding wing {config_name}: {e}")
            
            # Check for modified wings (existing configs that have been updated)
            for i in range(self.wings_list.count()):
                item = self.wings_list.item(i)
                existing_config = item.data(Qt.UserRole)
                if existing_config and hasattr(existing_config, 'config_name'):
                    config_name = existing_config.config_name
                    config_path = self._wings_watch_dir / f"{config_name}.json"
                    
                    if config_path.exists():
                        try:
                            # Check if file was modified
                            file_mtime = config_path.stat().st_mtime
                            
                            # Store last modified time in item data if not present
                            if not hasattr(item, '_last_mtime'):
                                item._last_mtime = file_mtime
                            elif item._last_mtime < file_mtime:
                                # File was modified, reload it
                                updated_config = WingConfig.load_from_file(str(config_path))
                                item.setData(Qt.UserRole, updated_config)
                                item.setText(f"{updated_config.wing_name} ({len(updated_config.feathers)} feathers)")
                                item.setToolTip(f"Time window: {updated_config.time_window_minutes} minutes")
                                item._last_mtime = file_mtime
                                
                                # Update in pipeline
                                if self.current_pipeline:
                                    for j, wc in enumerate(self.current_pipeline.wing_configs):
                                        if wc.config_name == config_name:
                                            self.current_pipeline.wing_configs[j] = updated_config
                                            break
                                
                                self._on_modified()
                                self.show_notification(f"✓ Wing updated: {updated_config.wing_name}")
                                print(f"[Pipeline Builder] ✓ Updated wing: {updated_config.wing_name}")
                        except Exception as e:
                            print(f"[Pipeline Builder] Error checking wing modification {config_name}: {e}")
            
            self._known_wing_configs = current_configs
        
        # Validate if configs were added or modified
        if new_configs:
            self.validate_pipeline()
    
    def show_notification(self, message: str):
        """Show a brief notification"""
        # This would ideally show a toast notification
        # For now, just update validation label briefly
        original_text = self.validation_label.text()
        original_style = self.validation_label.styleSheet()
        
        self.validation_label.setText(message)
        self.validation_label.setStyleSheet("color: #10B981; font-weight: bold;")
        
        # Reset after 3 seconds
        QTimer.singleShot(3000, lambda: (
            self.validation_label.setText(original_text),
            self.validation_label.setStyleSheet(original_style)
        ))
    
    def clear(self):
        """Clear all inputs"""
        self.current_pipeline = None
        self.name_input.clear()
        self.description_input.clear()
        self.output_dir_input.setText("output")
        self.case_name_input.clear()
        self.case_id_input.clear()
        self.investigator_input.clear()
        self.feathers_list.clear()
        self.wings_list.clear()
        self.validation_label.setText("No pipeline loaded")
        self.validation_label.setStyleSheet("")
        
        # Clear semantic configuration
        self.semantic_rules_list.clear()
        self.enable_scoring_checkbox.setChecked(True)
        self.threshold_low.setValue(0.3)
        self.threshold_medium.setValue(0.5)
        self.threshold_high.setValue(0.7)
        self.threshold_critical.setValue(0.9)

    def _on_feather_added(self, feather_metadata: dict):
        """
        Handle feather added signal from Configuration Manager.
        
        Args:
            feather_metadata: Dictionary containing feather metadata
        """
        try:
            # Check if feather already in list
            feather_id = feather_metadata.get('feather_id')
            for i in range(self.feathers_list.count()):
                item = self.feathers_list.item(i)
                existing_config = item.data(Qt.UserRole)
                if existing_config and existing_config.get('feather_id') == feather_id:
                    print(f"[Pipeline Builder] Feather already in list: {feather_id}")
                    return
            
            # Create FeatherConfig from metadata
            from ..config import FeatherConfig
            feather_config = FeatherConfig(
                config_name=feather_metadata.get('feather_id', 'unknown'),
                feather_name=feather_metadata.get('feather_name', 'Unknown'),
                artifact_type=feather_metadata.get('artifact_type', 'Unknown'),
                output_database=feather_metadata.get('database_path', '')
            )
            
            # Add to list
            self._add_feather_to_list(feather_config)
            
            # Scroll to new item
            self.feathers_list.scrollToBottom()
            
            # Show notification
            self.show_notification(f"✓ New feather added: {feather_config.feather_name}")
            
            # Validate pipeline
            self.validate_pipeline()
            
            print(f"[Pipeline Builder] Added feather from signal: {feather_config.feather_name}")
            
        except Exception as e:
            print(f"[Pipeline Builder] Error handling feather_added signal: {e}")
    
    def _on_feather_removed(self, feather_id: str):
        """
        Handle feather removed signal from Configuration Manager.
        
        Args:
            feather_id: ID of removed feather
        """
        try:
            # Find and remove from list
            for i in range(self.feathers_list.count()):
                item = self.feathers_list.item(i)
                feather_config = item.data(Qt.UserRole)
                if feather_config and feather_config.config_name == feather_id:
                    self.feathers_list.takeItem(i)
                    print(f"[Pipeline Builder] Removed feather: {feather_id}")
                    self.validate_pipeline()
                    break
                    
        except Exception as e:
            print(f"[Pipeline Builder] Error handling feather_removed signal: {e}")
    
    def _on_wing_added(self, wing_path: str):
        """
        Handle wing added signal from Configuration Manager.
        
        Args:
            wing_path: Path to wing configuration file
        """
        try:
            # Check if wing already in list
            for i in range(self.wings_list.count()):
                item = self.wings_list.item(i)
                wing_config = item.data(Qt.UserRole)
                if wing_config and hasattr(wing_config, 'config_path'):
                    if wing_config.config_path == wing_path:
                        print(f"[Pipeline Builder] Wing already in list: {wing_path}")
                        return
            
            # Load wing config
            from ..config import WingConfig
            wing_config = WingConfig.load_from_file(wing_path)
            
            # Add to list
            self._add_wing_to_list(wing_config)
            
            # Scroll to new item
            self.wings_list.scrollToBottom()
            
            # Show notification
            self.show_notification(f"✓ New wing added: {wing_config.wing_name}")
            
            # Validate pipeline
            self.validate_pipeline()
            
            print(f"[Pipeline Builder] Added wing from signal: {wing_config.wing_name}")
            
        except Exception as e:
            print(f"[Pipeline Builder] Error handling wing_added signal: {e}")
    
    def _on_wing_removed(self, wing_path: str):
        """
        Handle wing removed signal from Configuration Manager.
        
        Args:
            wing_path: Path to removed wing configuration
        """
        try:
            # Find and remove from list
            for i in range(self.wings_list.count()):
                item = self.wings_list.item(i)
                wing_config = item.data(Qt.UserRole)
                if wing_config and hasattr(wing_config, 'config_path'):
                    if wing_config.config_path == wing_path:
                        self.wings_list.takeItem(i)
                        print(f"[Pipeline Builder] Removed wing: {wing_path}")
                        self.validate_pipeline()
                        break
                        
        except Exception as e:
            print(f"[Pipeline Builder] Error handling wing_removed signal: {e}")
    
    def _on_configurations_loaded(self):
        """Handle configurations loaded signal from Configuration Manager."""
        print("[Pipeline Builder] Configurations loaded signal received")
        
        # Load feathers from Configuration Manager
        if self.config_manager:
            try:
                feathers = self.config_manager.get_all_feathers()
                print(f"[Pipeline Builder] Loading {len(feathers)} feathers from Configuration Manager")
                
                for feather_metadata in feathers:
                    try:
                        # Check if not already in list
                        feather_id = feather_metadata.get('feather_id')
                        already_added = False
                        
                        for i in range(self.feathers_list.count()):
                            item = self.feathers_list.item(i)
                            existing_data = item.data(Qt.UserRole)
                            
                            # Check both FeatherConfig objects and metadata dicts
                            if existing_data:
                                if hasattr(existing_data, 'config_name'):
                                    # It's a FeatherConfig object
                                    if existing_data.config_name == feather_id:
                                        already_added = True
                                        break
                                elif isinstance(existing_data, dict):
                                    # It's a metadata dict
                                    if existing_data.get('feather_id') == feather_id:
                                        already_added = True
                                        break
                        
                        if not already_added:
                            # Try to create FeatherConfig from metadata
                            try:
                                from ..config import FeatherConfig
                                feather_config = FeatherConfig(
                                    config_name=feather_metadata.get('feather_id', 'unknown'),
                                    feather_name=feather_metadata.get('feather_id', 'Unknown'),
                                    artifact_type=feather_metadata.get('artifact_type', 'Unknown'),
                                    output_database=feather_metadata.get('database_path', '')
                                )
                                
                                self._add_feather_to_list(feather_config)
                                print(f"[Pipeline Builder] ✓ Loaded feather: {feather_config.feather_name}")
                            
                            except Exception as e:
                                # Fallback: Add feather directly without FeatherConfig
                                print(f"[Pipeline Builder] FeatherConfig creation failed, using fallback: {e}")
                                
                                from PyQt5.QtWidgets import QListWidgetItem
                                feather_name = feather_metadata.get('feather_id', 'Unknown')
                                artifact_type = feather_metadata.get('artifact_type', 'Unknown')
                                db_path = feather_metadata.get('database_path', '')
                                
                                item = QListWidgetItem(f"{feather_name} ({artifact_type})")
                                item.setData(Qt.UserRole, feather_metadata)  # Store metadata directly
                                item.setToolTip(f"Database: {db_path}")
                                self.feathers_list.addItem(item)
                                
                                print(f"[Pipeline Builder] ✓ Loaded feather (fallback): {feather_name}")
                    
                    except Exception as e:
                        print(f"[Pipeline Builder] Error loading feather {feather_id}: {e}")
                        import traceback
                        traceback.print_exc()
            
            except Exception as e:
                print(f"[Pipeline Builder] Error in _on_configurations_loaded: {e}")
                import traceback
                traceback.print_exc()
        
        # Also load from file system (for backward compatibility)
        try:
            self.load_existing_configs()
        except Exception as e:
            print(f"[Pipeline Builder] Error in load_existing_configs: {e}")
        
        # Validate after loading
        try:
            self.validate_pipeline()
        except Exception as e:
            print(f"[Pipeline Builder] Error in validate_pipeline: {e}")