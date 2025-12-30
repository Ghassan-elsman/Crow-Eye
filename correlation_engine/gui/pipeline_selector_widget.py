"""
Pipeline Selector Widget

GUI component for selecting and managing pipelines in the correlation engine.
"""

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QComboBox, QLabel, QPushButton, QToolButton
)
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QIcon
from typing import List, Optional

from ..config.session_state import PipelineMetadata, PipelineBundle, LoadStatus
from ..config.pipeline_config_manager import PipelineConfigurationManager


class PipelineSelectorWidget(QWidget):
    """
    Widget for selecting and managing pipelines.
    Displays available pipelines in a dropdown with status and quick actions.
    """
    
    # Signals
    pipeline_selected = pyqtSignal(str)  # Emits pipeline path
    pipeline_switched = pyqtSignal(object)  # Emits PipelineBundle
    refresh_requested = pyqtSignal()
    create_requested = pyqtSignal()
    
    def __init__(self, config_manager: PipelineConfigurationManager, parent=None):
        """
        Initialize pipeline selector widget.
        
        Args:
            config_manager: PipelineConfigurationManager instance
            parent: Parent widget
        """
        super().__init__(parent)
        self.config_manager = config_manager
        self._current_bundle: Optional[PipelineBundle] = None
        self._pipelines: List[PipelineMetadata] = []
        
        self._init_ui()
    
    def _init_ui(self):
        """Initialize user interface."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Pipeline label
        self.label = QLabel("Pipeline:")
        layout.addWidget(self.label)
        
        # Pipeline dropdown
        self.pipeline_combo = QComboBox()
        self.pipeline_combo.setMinimumWidth(250)
        self.pipeline_combo.setToolTip("Select a pipeline configuration")
        self.pipeline_combo.currentIndexChanged.connect(self._on_pipeline_selected)
        layout.addWidget(self.pipeline_combo)
        
        # Status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666;")
        layout.addWidget(self.status_label)
        
        # Refresh button
        self.refresh_button = QToolButton()
        self.refresh_button.setText("🔄")
        self.refresh_button.setToolTip("Refresh pipeline list")
        self.refresh_button.clicked.connect(self._on_refresh_clicked)
        layout.addWidget(self.refresh_button)
        
        # Create new button
        self.create_button = QPushButton("Create New")
        self.create_button.setToolTip("Create a new pipeline")
        self.create_button.clicked.connect(self._on_create_clicked)
        layout.addWidget(self.create_button)
        
        layout.addStretch()
    
    def populate_pipelines(self, pipelines: List[PipelineMetadata]):
        """
        Populate dropdown with available pipelines.
        
        Args:
            pipelines: List of PipelineMetadata
        """
        self._pipelines = pipelines
        
        # Block signals while populating
        self.pipeline_combo.blockSignals(True)
        self.pipeline_combo.clear()
        
        if not pipelines:
            self.pipeline_combo.addItem("No pipelines available")
            self.pipeline_combo.setEnabled(False)
            self.status_label.setText("")
        else:
            self.pipeline_combo.setEnabled(True)
            
            for pipeline in pipelines:
                # Display name with metadata
                display_text = f"{pipeline.pipeline_name}"
                if pipeline.feather_count > 0 or pipeline.wing_count > 0:
                    display_text += f" ({pipeline.feather_count}F, {pipeline.wing_count}W)"
                
                self.pipeline_combo.addItem(display_text)
                
                # Store metadata in item data
                self.pipeline_combo.setItemData(
                    self.pipeline_combo.count() - 1,
                    pipeline,
                    Qt.UserRole
                )
                
                # Mark invalid pipelines
                if not pipeline.is_valid:
                    self.pipeline_combo.setItemData(
                        self.pipeline_combo.count() - 1,
                        "color: red;",
                        Qt.ToolTipRole
                    )
        
        self.pipeline_combo.blockSignals(False)
    
    def set_current_pipeline(self, pipeline_bundle: PipelineBundle):
        """
        Set and display current pipeline.
        
        Args:
            pipeline_bundle: Loaded PipelineBundle
        """
        self._current_bundle = pipeline_bundle
        
        # Find and select in dropdown
        pipeline_name = pipeline_bundle.pipeline_config.pipeline_name
        for i in range(self.pipeline_combo.count()):
            metadata = self.pipeline_combo.itemData(i, Qt.UserRole)
            if metadata and metadata.pipeline_name == pipeline_name:
                self.pipeline_combo.blockSignals(True)
                self.pipeline_combo.setCurrentIndex(i)
                self.pipeline_combo.blockSignals(False)
                break
        
        # Update status
        self.show_load_status(pipeline_bundle.load_status)
    
    def show_load_status(self, status: LoadStatus):
        """
        Display pipeline load status.
        
        Args:
            status: LoadStatus to display
        """
        if status.is_complete:
            self.status_label.setText(
                f"✓ Loaded: {status.feathers_loaded} feathers, {status.wings_loaded} wings"
            )
            self.status_label.setStyleSheet("color: green;")
        else:
            # Partial load
            self.status_label.setText(
                f"⚠ Partial: {status.feathers_loaded}/{status.feathers_total} feathers, "
                f"{status.wings_loaded}/{status.wings_total} wings"
            )
            self.status_label.setStyleSheet("color: orange;")
    
    def show_loading(self):
        """Show loading indicator."""
        self.status_label.setText("Loading...")
        self.status_label.setStyleSheet("color: #666;")
        self.pipeline_combo.setEnabled(False)
        self.create_button.setEnabled(False)
    
    def show_error(self, error_message: str):
        """
        Show error message.
        
        Args:
            error_message: Error message to display
        """
        self.status_label.setText(f"✗ Error: {error_message}")
        self.status_label.setStyleSheet("color: red;")
        self.pipeline_combo.setEnabled(True)
        self.create_button.setEnabled(True)
    
    def clear_status(self):
        """Clear status message."""
        self.status_label.setText("")
        self.pipeline_combo.setEnabled(True)
        self.create_button.setEnabled(True)
    
    def refresh_pipelines(self):
        """Refresh pipeline list from config manager."""
        try:
            self.config_manager.refresh_configurations()
            pipelines = self.config_manager.get_available_pipelines()
            self.populate_pipelines(pipelines)
            self.status_label.setText("✓ Refreshed")
            self.status_label.setStyleSheet("color: green;")
        except Exception as e:
            self.show_error(f"Refresh failed: {e}")
    
    def get_selected_pipeline(self) -> Optional[PipelineMetadata]:
        """
        Get currently selected pipeline metadata.
        
        Returns:
            PipelineMetadata or None
        """
        index = self.pipeline_combo.currentIndex()
        if index >= 0:
            return self.pipeline_combo.itemData(index, Qt.UserRole)
        return None
    
    def get_current_bundle(self) -> Optional[PipelineBundle]:
        """
        Get current pipeline bundle.
        
        Returns:
            PipelineBundle or None
        """
        return self._current_bundle
    
    def _on_pipeline_selected(self, index: int):
        """Handle pipeline selection from dropdown."""
        if index < 0:
            return
        
        metadata = self.pipeline_combo.itemData(index, Qt.UserRole)
        if metadata:
            self.pipeline_selected.emit(str(metadata.file_path))
    
    def _on_refresh_clicked(self):
        """Handle refresh button click."""
        self.refresh_requested.emit()
        self.refresh_pipelines()
    
    def _on_create_clicked(self):
        """Handle create new button click."""
        self.create_requested.emit()
