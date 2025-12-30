"""
Configuration Library Widget
Browse and manage saved pipeline, feather, and wing configurations.
"""

import os
import json
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QListWidget,
    QListWidgetItem, QLineEdit, QPushButton, QLabel, QMenu,
    QMessageBox, QFileDialog, QComboBox, QGroupBox, QFormLayout
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIcon

from ..config import PipelineConfig, FeatherConfig, WingConfig


class ConfigurationLibraryWidget(QWidget):
    """Widget for browsing and managing configuration library"""
    
    config_selected = pyqtSignal(object)  # Emits config object
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.base_path = Path("demo_configs")
        self.pipelines_path = self.base_path / "pipelines"
        self.feathers_path = self.base_path / "feathers"
        self.wings_path = self.base_path / "wings"
        
        # Ensure directories exist
        self.pipelines_path.mkdir(parents=True, exist_ok=True)
        self.feathers_path.mkdir(parents=True, exist_ok=True)
        self.wings_path.mkdir(parents=True, exist_ok=True)
        
        self._init_ui()
        self._load_all_configurations()
    
    def _init_ui(self):
        """Initialize the user interface"""
        layout = QVBoxLayout(self)
        
        # Search and filter section
        filter_group = self._create_filter_section()
        layout.addWidget(filter_group)
        
        # Tabbed interface for different config types
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        
        # Create tabs
        self.pipelines_tab = self._create_pipelines_tab()
        self.feathers_tab = self._create_feathers_tab()
        self.wings_tab = self._create_wings_tab()
        
        self.tab_widget.addTab(self.pipelines_tab, "Pipelines")
        self.tab_widget.addTab(self.feathers_tab, "Feathers")
        self.tab_widget.addTab(self.wings_tab, "Wings")
        
        # Connect tab change
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
    
    def _create_filter_section(self) -> QGroupBox:
        """Create search and filter controls"""
        group = QGroupBox("Search and Filter")
        layout = QHBoxLayout()
        
        # Search box
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search configurations...")
        self.search_input.textChanged.connect(self._apply_filters)
        layout.addWidget(QLabel("Search:"))
        layout.addWidget(self.search_input)
        
        # Filter by type (for feathers)
        self.type_filter = QComboBox()
        self.type_filter.addItem("All Types")
        self.type_filter.addItems([
            "Browser", "Prefetch", "SRUM", "AmCache", "ShimCache",
            "Jumplists", "LNK", "MFT", "USN", "Logs"
        ])
        self.type_filter.currentTextChanged.connect(self._apply_filters)
        layout.addWidget(QLabel("Type:"))
        layout.addWidget(self.type_filter)
        
        # Refresh button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._load_all_configurations)
        layout.addWidget(refresh_btn)
        
        layout.addStretch()
        
        group.setLayout(layout)
        return group
    
    def _create_pipelines_tab(self) -> QWidget:
        """Create pipelines list tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # List widget
        self.pipelines_list = QListWidget()
        self.pipelines_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pipelines_list.customContextMenuRequested.connect(
            lambda pos: self._show_context_menu(pos, "pipeline")
        )
        self.pipelines_list.itemDoubleClicked.connect(self._on_pipeline_double_clicked)
        layout.addWidget(self.pipelines_list)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        
        load_btn = QPushButton("Load Pipeline")
        load_btn.clicked.connect(self._load_selected_pipeline)
        buttons_layout.addWidget(load_btn)
        
        import_btn = QPushButton("Import...")
        import_btn.clicked.connect(lambda: self._import_configuration("pipeline"))
        buttons_layout.addWidget(import_btn)
        
        buttons_layout.addStretch()
        
        layout.addLayout(buttons_layout)
        
        return widget
    
    def _create_feathers_tab(self) -> QWidget:
        """Create feathers list tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # List widget
        self.feathers_list = QListWidget()
        self.feathers_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.feathers_list.customContextMenuRequested.connect(
            lambda pos: self._show_context_menu(pos, "feather")
        )
        self.feathers_list.itemDoubleClicked.connect(self._on_feather_double_clicked)
        layout.addWidget(self.feathers_list)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        
        import_btn = QPushButton("Import...")
        import_btn.clicked.connect(lambda: self._import_configuration("feather"))
        buttons_layout.addWidget(import_btn)
        
        buttons_layout.addStretch()
        
        layout.addLayout(buttons_layout)
        
        return widget
    
    def _create_wings_tab(self) -> QWidget:
        """Create wings list tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # List widget
        self.wings_list = QListWidget()
        self.wings_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.wings_list.customContextMenuRequested.connect(
            lambda pos: self._show_context_menu(pos, "wing")
        )
        self.wings_list.itemDoubleClicked.connect(self._on_wing_double_clicked)
        layout.addWidget(self.wings_list)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        
        import_btn = QPushButton("Import...")
        import_btn.clicked.connect(lambda: self._import_configuration("wing"))
        buttons_layout.addWidget(import_btn)
        
        buttons_layout.addStretch()
        
        layout.addLayout(buttons_layout)
        
        return widget
    
    def _load_all_configurations(self):
        """Load all configurations from filesystem"""
        self._load_pipelines()
        self._load_feathers()
        self._load_wings()
    
    def _load_pipelines(self):
        """Load pipeline configurations"""
        self.pipelines_list.clear()
        
        if not self.pipelines_path.exists():
            return
        
        for filepath in self.pipelines_path.glob("*.json"):
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                
                name = data.get('pipeline_name', filepath.stem)
                description = data.get('description', '')
                feather_count = len(data.get('feather_configs', []))
                wing_count = len(data.get('wing_configs', []))
                created_date = data.get('created_date', '')
                
                item = QListWidgetItem(
                    f"{name}\n"
                    f"Feathers: {feather_count}, Wings: {wing_count}\n"
                    f"{description[:60]}..."
                )
                item.setData(Qt.UserRole, str(filepath))
                item.setData(Qt.UserRole + 1, data)
                item.setToolTip(f"Path: {filepath}\nCreated: {created_date}")
                
                self.pipelines_list.addItem(item)
                
            except Exception as e:
                print(f"Error loading pipeline {filepath}: {e}")
    
    def _load_feathers(self):
        """Load feather configurations"""
        self.feathers_list.clear()
        
        if not self.feathers_path.exists():
            return
        
        for filepath in self.feathers_path.glob("*.json"):
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                
                name = data.get('feather_name', filepath.stem)
                artifact_type = data.get('artifact_type', 'Unknown')
                database_path = data.get('output_database', '')
                record_count = data.get('total_records', 0)
                
                item = QListWidgetItem(
                    f"{name} ({artifact_type})\n"
                    f"Records: {record_count:,}\n"
                    f"Database: {Path(database_path).name}"
                )
                item.setData(Qt.UserRole, str(filepath))
                item.setData(Qt.UserRole + 1, data)
                item.setData(Qt.UserRole + 2, artifact_type)
                item.setToolTip(f"Path: {filepath}\nDatabase: {database_path}")
                
                self.feathers_list.addItem(item)
                
            except Exception as e:
                print(f"Error loading feather {filepath}: {e}")
    
    def _load_wings(self):
        """Load wing configurations"""
        self.wings_list.clear()
        
        if not self.wings_path.exists():
            return
        
        for filepath in self.wings_path.glob("*.json"):
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                
                name = data.get('wing_name', filepath.stem)
                description = data.get('description', '')
                time_window = data.get('time_window_minutes', 0)
                feather_count = len(data.get('feathers', []))
                
                item = QListWidgetItem(
                    f"{name}\n"
                    f"Time Window: {time_window} min, Feathers: {feather_count}\n"
                    f"{description[:60]}..."
                )
                item.setData(Qt.UserRole, str(filepath))
                item.setData(Qt.UserRole + 1, data)
                item.setToolTip(f"Path: {filepath}\nProves: {data.get('proves', '')}")
                
                self.wings_list.addItem(item)
                
            except Exception as e:
                print(f"Error loading wing {filepath}: {e}")
    
    def _apply_filters(self):
        """Apply search and filter criteria"""
        search_text = self.search_input.text().lower()
        type_filter = self.type_filter.currentText()
        
        # Get current tab
        current_tab = self.tab_widget.currentIndex()
        
        if current_tab == 0:  # Pipelines
            self._filter_list(self.pipelines_list, search_text, None)
        elif current_tab == 1:  # Feathers
            artifact_type = None if type_filter == "All Types" else type_filter
            self._filter_list(self.feathers_list, search_text, artifact_type)
        elif current_tab == 2:  # Wings
            self._filter_list(self.wings_list, search_text, None)
    
    def _filter_list(self, list_widget: QListWidget, search_text: str, artifact_type: Optional[str]):
        """Filter list widget items"""
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            
            # Check search text
            text_match = search_text in item.text().lower() if search_text else True
            
            # Check artifact type (for feathers)
            type_match = True
            if artifact_type and list_widget == self.feathers_list:
                item_type = item.data(Qt.UserRole + 2)
                type_match = item_type == artifact_type
            
            # Show/hide item
            item.setHidden(not (text_match and type_match))
    
    def _show_context_menu(self, position, config_type: str):
        """Show context menu for configuration item"""
        # Get appropriate list widget
        if config_type == "pipeline":
            list_widget = self.pipelines_list
        elif config_type == "feather":
            list_widget = self.feathers_list
        else:
            list_widget = self.wings_list
        
        item = list_widget.itemAt(position)
        if not item:
            return
        
        menu = QMenu(self)
        
        # Load action
        if config_type == "pipeline":
            load_action = menu.addAction("Load Pipeline")
            load_action.triggered.connect(self._load_selected_pipeline)
        
        # Duplicate action
        duplicate_action = menu.addAction("Duplicate")
        duplicate_action.triggered.connect(lambda: self._duplicate_configuration(item, config_type))
        
        # Export action
        export_action = menu.addAction("Export...")
        export_action.triggered.connect(lambda: self._export_configuration(item, config_type))
        
        menu.addSeparator()
        
        # Delete action
        delete_action = menu.addAction("Delete")
        delete_action.triggered.connect(lambda: self._delete_configuration(item, config_type))
        
        menu.exec_(list_widget.mapToGlobal(position))
    
    def _import_configuration(self, config_type: str):
        """Import configuration from external location"""
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            f"Import {config_type.capitalize()} Configuration",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if not filepath:
            return
        
        try:
            # Determine destination path
            if config_type == "pipeline":
                dest_dir = self.pipelines_path
            elif config_type == "feather":
                dest_dir = self.feathers_path
            else:
                dest_dir = self.wings_path
            
            # Create directory if it doesn't exist
            dest_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy file
            dest_path = dest_dir / Path(filepath).name
            shutil.copy2(filepath, dest_path)
            
            # Reload configurations
            self._load_all_configurations()
            
            QMessageBox.information(
                self,
                "Import Successful",
                f"Configuration imported to:\n{dest_path}"
            )
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Import Error",
                f"Failed to import configuration:\n{str(e)}"
            )
    
    def _export_configuration(self, item: QListWidgetItem, config_type: str):
        """Export configuration to external location"""
        source_path = item.data(Qt.UserRole)
        
        dest_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export {config_type.capitalize()} Configuration",
            Path(source_path).name,
            "JSON Files (*.json);;All Files (*)"
        )
        
        if not dest_path:
            return
        
        try:
            shutil.copy2(source_path, dest_path)
            
            QMessageBox.information(
                self,
                "Export Successful",
                f"Configuration exported to:\n{dest_path}"
            )
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"Failed to export configuration:\n{str(e)}"
            )
    
    def _duplicate_configuration(self, item: QListWidgetItem, config_type: str):
        """Duplicate configuration"""
        source_path = Path(item.data(Qt.UserRole))
        
        # Generate new name
        base_name = source_path.stem
        counter = 1
        while True:
            new_name = f"{base_name}_copy{counter if counter > 1 else ''}.json"
            new_path = source_path.parent / new_name
            if not new_path.exists():
                break
            counter += 1
        
        try:
            # Copy file
            shutil.copy2(source_path, new_path)
            
            # Update config name in file
            with open(new_path, 'r') as f:
                data = json.load(f)
            
            if config_type == "pipeline":
                data['pipeline_name'] += f" (Copy {counter})" if counter > 1 else " (Copy)"
                data['config_name'] = new_path.stem
            elif config_type == "feather":
                data['feather_name'] += f" (Copy {counter})" if counter > 1 else " (Copy)"
                data['config_name'] = new_path.stem
            else:  # wing
                data['wing_name'] += f" (Copy {counter})" if counter > 1 else " (Copy)"
                data['config_name'] = new_path.stem
            
            with open(new_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            # Reload configurations
            self._load_all_configurations()
            
            QMessageBox.information(
                self,
                "Duplicate Successful",
                f"Configuration duplicated to:\n{new_path}"
            )
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Duplicate Error",
                f"Failed to duplicate configuration:\n{str(e)}"
            )
    
    def _delete_configuration(self, item: QListWidgetItem, config_type: str):
        """Delete configuration"""
        filepath = Path(item.data(Qt.UserRole))
        
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete this {config_type}?\n\n{filepath.name}",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                filepath.unlink()
                self._load_all_configurations()
                
                QMessageBox.information(
                    self,
                    "Delete Successful",
                    f"Configuration deleted:\n{filepath.name}"
                )
                
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Delete Error",
                    f"Failed to delete configuration:\n{str(e)}"
                )
    
    def _load_selected_pipeline(self):
        """Load selected pipeline"""
        item = self.pipelines_list.currentItem()
        if item:
            filepath = item.data(Qt.UserRole)
            try:
                pipeline = PipelineConfig.load_from_file(filepath)
                self.config_selected.emit(pipeline)
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Load Error",
                    f"Failed to load pipeline:\n{str(e)}"
                )
    
    def _on_pipeline_double_clicked(self, item: QListWidgetItem):
        """Handle pipeline double-click"""
        self._load_selected_pipeline()
    
    def _on_feather_double_clicked(self, item: QListWidgetItem):
        """Handle feather double-click"""
        filepath = item.data(Qt.UserRole)
        try:
            feather = FeatherConfig.load_from_file(filepath)
            self.config_selected.emit(feather)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Load Error",
                f"Failed to load feather:\n{str(e)}"
            )
    
    def _on_wing_double_clicked(self, item: QListWidgetItem):
        """Handle wing double-click"""
        filepath = item.data(Qt.UserRole)
        try:
            wing = WingConfig.load_from_file(filepath)
            self.config_selected.emit(wing)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Load Error",
                f"Failed to load wing:\n{str(e)}"
            )
    
    def _on_tab_changed(self, index: int):
        """Handle tab change"""
        # Update type filter visibility
        self.type_filter.setVisible(index == 1)  # Show only for feathers tab
        
        # Reapply filters
        self._apply_filters()
