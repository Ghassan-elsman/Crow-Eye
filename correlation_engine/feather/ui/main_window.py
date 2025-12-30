"""
Feather Builder Main Window
Professional cyberpunk-styled PyQt5 interface for data import and normalization.
"""

import os
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QTabWidget, QLabel, QLineEdit, QPushButton, 
    QFileDialog, QMenuBar, QMenu, QAction, QStatusBar,
    QMessageBox, QProgressDialog, QInputDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont
from ..database import FeatherDatabase
from ..transformer import DataTransformer

# Import config system
try:
    from ...config import ConfigManager, FeatherConfig
    CONFIG_AVAILABLE = True
except ImportError:
    CONFIG_AVAILABLE = False
    print("Warning: Config system not available")

# Import Configuration Manager
try:
    from ....config.configuration_manager import ConfigurationManager
    CONFIG_MANAGER_AVAILABLE = True
except ImportError:
    CONFIG_MANAGER_AVAILABLE = False
    print("Warning: Configuration Manager not available")

# Import Artifact Detector
try:
    from ...wings.core.artifact_detector import ArtifactDetector
    ARTIFACT_DETECTOR_AVAILABLE = True
except ImportError:
    ARTIFACT_DETECTOR_AVAILABLE = False
    print("Warning: Artifact Detector not available")


class FeatherBuilderWindow(QMainWindow):
    """Main window for the Feather Builder application."""
    
    def __init__(self):
        super().__init__()
        self.feather_name = ""
        self.feather_path = ""
        self.feather_db = None
        self.current_config = None  # Store current feather config
        self.config_manager = ConfigManager() if CONFIG_AVAILABLE else None
        self.configuration_manager = ConfigurationManager.get_instance() if CONFIG_MANAGER_AVAILABLE else None
        self.artifact_type = "Unknown"  # Track selected artifact type
        self.detection_method = "unknown"  # Track how artifact type was detected
        self.detection_confidence = "low"  # Track detection confidence
        self.auto_registration_service = None  # Set by pipeline builder
        self.source_database_path = None  # Track source database for detection
        
        # Auto-set feather path to Configuration Manager's feathers directory
        if self.configuration_manager and self.configuration_manager.feathers_dir:
            self.feather_path = str(self.configuration_manager.feathers_dir)
        
        self.init_ui()
        self.load_stylesheet()
        self.connect_import_signals()
        
        # Update path input if auto-set
        if self.feather_path:
            self.feather_path_input.setText(self.feather_path)
    
    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("Crow-Eye Feather Builder")
        self.setGeometry(100, 100, 1200, 800)
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Create header section with feather name and path
        header_layout = self.create_header_section()
        main_layout.addLayout(header_layout)
        
        # Create artifact type section
        artifact_section = self.create_artifact_type_section()
        main_layout.addWidget(artifact_section)
        
        # Create tab widget for different import types
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        # Add tabs (placeholders for now)
        self.create_tabs()
        
        # Create menu bar
        self.create_menu_bar()
        
        # Create status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready to import data...")
    
    def create_header_section(self):
        """Create the header section with feather name and path selection."""
        header_layout = QVBoxLayout()
        
        # Title label
        title_label = QLabel("FEATHER BUILDER")
        title_font = QFont("Consolas", 18, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(title_label)
        
        # Feather name and path row
        name_path_layout = QHBoxLayout()
        
        # Feather name input
        name_label = QLabel("Feather Name:")
        name_label.setMinimumWidth(120)
        self.feather_name_input = QLineEdit()
        self.feather_name_input.setPlaceholderText("Enter feather database name...")
        self.feather_name_input.textChanged.connect(self.on_feather_name_changed)
        
        # Path selection
        path_label = QLabel("Save Location:")
        path_label.setMinimumWidth(120)
        self.feather_path_input = QLineEdit()
        self.feather_path_input.setPlaceholderText("Select save location...")
        self.feather_path_input.setReadOnly(True)
        
        self.path_button = QPushButton("Browse...")
        self.path_button.setMaximumWidth(120)
        self.path_button.clicked.connect(self.select_feather_path)
        
        # Add to layout
        name_path_layout.addWidget(name_label)
        name_path_layout.addWidget(self.feather_name_input, 2)
        name_path_layout.addWidget(path_label)
        name_path_layout.addWidget(self.feather_path_input, 2)
        name_path_layout.addWidget(self.path_button)
        
        header_layout.addLayout(name_path_layout)
        
        return header_layout
    
    def create_artifact_type_section(self):
        """Create artifact type selection section."""
        from PyQt5.QtWidgets import QGroupBox, QComboBox
        from ...wings.core.artifact_detector import ArtifactDetector
        
        group = QGroupBox("Artifact Type")
        layout = QVBoxLayout()
        layout.setSpacing(10)
        
        # Auto-detection display
        detection_layout = QHBoxLayout()
        detection_label = QLabel("Auto-Detected:")
        detection_label.setMinimumWidth(120)
        self.artifact_detection_label = QLabel("⚠ Not detected yet")
        self.artifact_detection_label.setStyleSheet("color: #00d9ff; font-weight: bold;")
        detection_layout.addWidget(detection_label)
        detection_layout.addWidget(self.artifact_detection_label)
        detection_layout.addStretch()
        layout.addLayout(detection_layout)
        
        # Artifact type selection
        type_layout = QHBoxLayout()
        type_label = QLabel("Artifact Type:")
        type_label.setMinimumWidth(120)
        self.artifact_type_combo = QComboBox()
        self.populate_artifact_types()
        self.artifact_type_combo.currentTextChanged.connect(self.on_artifact_type_changed)
        type_layout.addWidget(type_label)
        type_layout.addWidget(self.artifact_type_combo, 1)
        layout.addLayout(type_layout)
        
        # Help text
        help_label = QLabel(
            "The artifact type helps the correlation engine understand your data. "
            "This will be saved to the feather_metadata table."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #888; font-size: 9pt;")
        layout.addWidget(help_label)
        
        group.setLayout(layout)
        return group
    
    def populate_artifact_types(self):
        """Populate artifact type combo box."""
        from ...wings.core.artifact_detector import ArtifactDetector
        
        self.artifact_type_combo.clear()
        
        # Add "Unknown" option
        self.artifact_type_combo.addItem("⚠ Unknown - Please select")
        
        # Add all artifact types
        for artifact_type in ArtifactDetector.get_all_artifact_types():
            self.artifact_type_combo.addItem(artifact_type)
    
    def on_artifact_type_changed(self):
        """Handle artifact type selection change."""
        selected_text = self.artifact_type_combo.currentText()
        
        if selected_text.startswith("⚠ Unknown"):
            self.artifact_type = "Unknown"
        else:
            self.artifact_type = selected_text
            
            # Check if this is a manual override
            if hasattr(self, 'detection_method') and self.detection_method != "unknown":
                # User manually changed from auto-detected type
                # Check if it's different from what was detected
                current_label = self.artifact_detection_label.text()
                if self.artifact_type not in current_label or "manually selected" in current_label:
                    # This is a manual override
                    original_type = "auto-detected"
                    # Try to extract original type from label
                    if "(" in current_label:
                        parts = current_label.split()
                        if len(parts) > 1:
                            original_type = parts[1]
                    
                    self.artifact_detection_label.setText(
                        f"✓ {self.artifact_type} (manually selected, was {original_type})"
                    )
                    self.detection_method = "manual"
        
        self.update_status()
    
    def detect_artifact_type_from_database(self):
        """Detect artifact type when database is loaded or table is created."""
        from ...wings.core.artifact_detector import ArtifactDetector
        
        if not self.feather_path or not self.feather_name:
            return
        
        db_path = os.path.join(self.feather_path, f"{self.feather_name}.db")
        
        if not os.path.exists(db_path):
            # Database doesn't exist yet, try filename detection
            filename_type, confidence = ArtifactDetector.detect_from_filename(self.feather_name)
            if filename_type != "Unknown":
                icon = ArtifactDetector.get_confidence_icon(confidence)
                self.artifact_detection_label.setText(
                    f"{icon} {filename_type} ({confidence} confidence - from filename)"
                )
                self._select_artifact_type(filename_type)
                self.detection_method = "filename"
            return
        
        # Priority 1: Check existing metadata
        existing_type = self._read_artifact_type_from_metadata(db_path)
        if existing_type:
            self.artifact_detection_label.setText(
                f"✓ {existing_type} (from existing metadata)"
            )
            self._select_artifact_type(existing_type)
            self.detection_method = "metadata"
            return
        
        # Priority 2: Detect from table names
        table_type, confidence = ArtifactDetector.detect_from_table_name(db_path)
        if table_type != "Unknown":
            icon = ArtifactDetector.get_confidence_icon(confidence)
            self.artifact_detection_label.setText(
                f"{icon} {table_type} ({confidence} confidence - from table name)"
            )
            self._select_artifact_type(table_type)
            self.detection_method = "table_name"
            return
        
        # Priority 3: Detect from filename
        filename_type, confidence = ArtifactDetector.detect_from_filename(self.feather_name)
        icon = ArtifactDetector.get_confidence_icon(confidence)
        self.artifact_detection_label.setText(
            f"{icon} {filename_type} ({confidence} confidence - from filename)"
        )
        self._select_artifact_type(filename_type)
        self.detection_method = "filename"
    
    def _read_artifact_type_from_metadata(self, db_path: str):
        """Read artifact type from existing feather_metadata table."""
        import sqlite3
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='feather_metadata'"
            )
            if not cursor.fetchone():
                conn.close()
                return None
            
            # Use key-value structure
            cursor.execute("SELECT value FROM feather_metadata WHERE key = 'artifact_type' LIMIT 1")
            row = cursor.fetchone()
            conn.close()
            
            return row[0] if row and row[0] else None
        except Exception as e:
            print(f"Error reading metadata: {e}")
            return None
    
    def _select_artifact_type(self, artifact_type: str):
        """Select artifact type in combo box."""
        if artifact_type == "Unknown":
            self.artifact_type_combo.setCurrentIndex(0)
        else:
            for i in range(self.artifact_type_combo.count()):
                if self.artifact_type_combo.itemText(i) == artifact_type:
                    self.artifact_type_combo.setCurrentIndex(i)
                    break
    
    def save_artifact_type_to_metadata(self):
        """Save artifact type to feather_metadata table."""
        import sqlite3
        from datetime import datetime
        
        selected_type = self.artifact_type_combo.currentText()
        
        if selected_type.startswith("⚠"):
            # User hasn't selected a valid type
            reply = QMessageBox.question(
                self, "Artifact Type Not Set",
                "You haven't selected an artifact type. Continue without setting it?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return False
            selected_type = "Unknown"
        
        if not self.feather_db or not self.feather_db.connection:
            print("Warning: No active database connection")
            return False
        
        try:
            cursor = self.feather_db.connection.cursor()
            
            # Check if metadata table exists
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='feather_metadata'"
            )
            
            if cursor.fetchone():
                # Check if artifact_type key exists
                cursor.execute(
                    "SELECT value FROM feather_metadata WHERE key = 'artifact_type'"
                )
                if cursor.fetchone():
                    # Update existing artifact_type
                    cursor.execute(
                        "UPDATE feather_metadata SET value = ? WHERE key = 'artifact_type'",
                        (selected_type,)
                    )
                else:
                    # Insert new artifact_type
                    cursor.execute(
                        "INSERT INTO feather_metadata (key, value) VALUES ('artifact_type', ?)",
                        (selected_type,)
                    )
            else:
                # Create metadata table with key-value structure
                cursor.execute("""
                    CREATE TABLE feather_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)
                cursor.execute(
                    "INSERT INTO feather_metadata (key, value) VALUES ('artifact_type', ?)",
                    (selected_type,)
                )
                cursor.execute(
                    "INSERT INTO feather_metadata (key, value) VALUES ('created_date', ?)",
                    (datetime.now().isoformat(),)
                )
            
            self.feather_db.connection.commit()
            return True
            
        except Exception as e:
            QMessageBox.critical(
                self, "Save Error",
                f"Failed to save artifact type to metadata:\n{str(e)}"
            )
            return False
    
    def create_tabs(self):
        """Create tabs for different import types."""
        from .database_tab import DatabaseTab
        from .csv_tab import CSVTab
        from .json_tab import JSONTab
        
        # Database import tab
        self.db_tab = DatabaseTab()
        self.tab_widget.addTab(self.db_tab, "Database")
        
        # Connect database selection signal for artifact detection
        self.db_tab.database_selected.connect(self.on_source_database_selected)
        
        # CSV import tab
        self.csv_tab = CSVTab()
        self.tab_widget.addTab(self.csv_tab, "CSV")
        
        # JSON import tab
        self.json_tab = JSONTab()
        self.tab_widget.addTab(self.json_tab, "JSON")
        
        # Data viewer tab
        from .data_viewer import DataViewer
        self.data_viewer = DataViewer()
        self.tab_widget.addTab(self.data_viewer, "View Data")
    
    def create_menu_bar(self):
        """Create the menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("File")
        
        new_action = QAction("New Feather", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self.new_feather)
        file_menu.addAction(new_action)
        
        open_action = QAction("Open Feather", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_feather)
        file_menu.addAction(open_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Config menu
        if CONFIG_AVAILABLE:
            config_menu = menubar.addMenu("Config")
            
            save_config_action = QAction("Save Configuration...", self)
            save_config_action.setShortcut("Ctrl+S")
            save_config_action.triggered.connect(self.save_feather_config)
            config_menu.addAction(save_config_action)
            
            load_config_action = QAction("Load Configuration...", self)
            load_config_action.setShortcut("Ctrl+L")
            load_config_action.triggered.connect(self.load_feather_config)
            config_menu.addAction(load_config_action)
            
            config_menu.addSeparator()
            
            list_configs_action = QAction("List Configurations", self)
            list_configs_action.triggered.connect(self.list_feather_configs)
            config_menu.addAction(list_configs_action)
        
        # Edit menu
        edit_menu = menubar.addMenu("Edit")
        
        # View menu
        view_menu = menubar.addMenu("View")
        
        # Help menu
        help_menu = menubar.addMenu("Help")
        
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def load_stylesheet(self):
        """Load the cyberpunk stylesheet."""
        style_path = os.path.join(os.path.dirname(__file__), "styles.qss")
        try:
            with open(style_path, 'r') as f:
                stylesheet = f.read()
                self.setStyleSheet(stylesheet)
        except FileNotFoundError:
            print(f"Warning: Stylesheet not found at {style_path}")
    
    def on_feather_name_changed(self, text):
        """Handle feather name input changes."""
        self.feather_name = text
        self.update_status()
        # Trigger artifact type detection
        self.detect_artifact_type_from_database()
    
    def select_feather_path(self):
        """Open file dialog to select feather save location."""
        # Determine default directory
        default_dir = ""
        
        # Try to use Configuration Manager's feathers directory
        if self.configuration_manager:
            feathers_dir = self.configuration_manager.feathers_dir
            if feathers_dir and feathers_dir.exists():
                default_dir = str(feathers_dir)
        
        path = QFileDialog.getExistingDirectory(
            self,
            "Select Feather Save Location",
            default_dir,
            QFileDialog.ShowDirsOnly
        )
        
        if path:
            self.feather_path = path
            self.feather_path_input.setText(path)
            self.update_status()
            # Trigger artifact type detection
            self.detect_artifact_type_from_database()
    
    def update_status(self):
        """Update status bar with current feather info."""
        if self.feather_name and self.feather_path:
            full_path = os.path.join(self.feather_path, f"{self.feather_name}.db")
            self.status_bar.showMessage(f"Feather will be saved to: {full_path}")
        elif self.feather_name:
            self.status_bar.showMessage(f"Feather name: {self.feather_name} - Select save location")
        elif self.feather_path:
            self.status_bar.showMessage(f"Save location: {self.feather_path} - Enter feather name")
        else:
            self.status_bar.showMessage("Ready to import data...")
    
    def new_feather(self):
        """Create a new feather database."""
        # Close existing database connection
        if self.feather_db:
            try:
                self.feather_db.close()
            except:
                pass
            self.feather_db = None
        
        self.feather_name_input.clear()
        self.feather_path_input.clear()
        self.feather_name = ""
        self.feather_path = ""
        self.status_bar.showMessage("New feather - Enter name and select location")
    
    def open_feather(self):
        """Open an existing feather database."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Feather Database",
            "",
            "SQLite Database (*.db);;All Files (*)"
        )
        
        if file_path:
            # Close existing database connection
            if self.feather_db:
                try:
                    self.feather_db.close()
                except:
                    pass
                self.feather_db = None
            
            self.feather_path = os.path.dirname(file_path)
            self.feather_name = os.path.splitext(os.path.basename(file_path))[0]
            self.feather_name_input.setText(self.feather_name)
            self.feather_path_input.setText(self.feather_path)
            self.status_bar.showMessage(f"Opened feather: {file_path}")
            
            # Detect artifact type from opened database
            self.detect_artifact_type_from_database()
            
            # Initialize and load the database
            self.initialize_feather_database()
            self.data_viewer.set_feather_database(self.feather_db)
            self.data_viewer.refresh_data()
    
    def show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About Feather Builder",
            "Crow-Eye Feather Builder v0.1.0\n\n"
            "Professional forensic data normalization tool\n"
            "Part of the Correlation Engine system"
        )
    
    def connect_import_signals(self):
        """Connect import button signals from tabs."""
        try:
            self.db_tab.import_btn.clicked.disconnect()
        except:
            pass
        self.db_tab.import_btn.clicked.connect(self.handle_database_import)
        
        try:
            self.csv_tab.import_btn.clicked.disconnect()
        except:
            pass
        self.csv_tab.import_btn.clicked.connect(self.handle_csv_import)
        
        try:
            self.json_tab.import_btn.clicked.disconnect()
        except:
            pass
        self.json_tab.import_btn.clicked.connect(self.handle_json_import)
    
    def validate_feather_setup(self) -> bool:
        """Validate that feather name and path are set."""
        if not self.feather_name:
            QMessageBox.warning(self, "Missing Name", "Please enter a feather name.")
            return False
        
        if not self.feather_path:
            QMessageBox.warning(self, "Missing Path", "Please select a save location.")
            return False
        
        return True
    
    def initialize_feather_database(self):
        """Initialize or connect to feather database."""
        # Close existing connection if any
        if self.feather_db:
            try:
                self.feather_db.close()
            except:
                pass
        
        # Create new database connection
        self.feather_db = FeatherDatabase(self.feather_path, self.feather_name)
        self.feather_db.connect()
        self.feather_db.create_base_schema()
    
    def handle_database_import(self):
        """Handle database import."""
        if not self.validate_feather_setup():
            return
        
        try:
            config = self.db_tab.get_import_config()
            # Use the source table name as the feather table name
            table_name = config.get('table_name', 'database_data')
            self.perform_import(config, table_name)
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import database: {str(e)}")
    
    def handle_csv_import(self):
        """Handle CSV import."""
        if not self.validate_feather_setup():
            return
        
        try:
            config = self.csv_tab.get_import_config()
            # Use the CSV filename (without extension) as the table name
            import os
            csv_filename = os.path.splitext(os.path.basename(config['source_path']))[0]
            table_name = csv_filename if csv_filename else 'csv_data'
            self.perform_import(config, table_name)
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import CSV: {str(e)}")
    
    def handle_json_import(self):
        """Handle JSON import."""
        if not self.validate_feather_setup():
            return
        
        try:
            config = self.json_tab.get_import_config()
            # Use the JSON filename (without extension) as the table name
            import os
            json_filename = os.path.splitext(os.path.basename(config['source_path']))[0]
            table_name = json_filename if json_filename else 'json_data'
            self.perform_import(config, table_name)
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import JSON: {str(e)}")
    
    def perform_import(self, config: dict, table_name: str):
        """Perform the actual import operation."""
        self.initialize_feather_database()
        
        # Show progress dialog
        progress = QProgressDialog("Importing data...", "Cancel", 0, 100, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setValue(10)
        
        try:
            # Create feather table
            progress.setLabelText("Creating feather table...")
            self.feather_db.create_feather_table(table_name, config['columns'])
            progress.setValue(30)
            
            # Prepare data
            progress.setLabelText("Preparing data...")
            data = self.prepare_import_data(config)
            progress.setValue(50)
            
            # Validate and transform data
            progress.setLabelText("Validating data...")
            transformer = DataTransformer()
            valid_data, invalid_data, errors = transformer.validate_data(data, config['columns'])
            progress.setValue(70)
            
            if errors:
                error_msg = f"Found {len(errors)} validation errors. Continue with {len(valid_data)} valid records?"
                reply = QMessageBox.question(
                    self, "Validation Errors", error_msg,
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.No:
                    progress.close()
                    return
            
            # Insert data
            progress.setLabelText("Inserting data into feather...")
            source_info = {
                'source_type': config['source_type'],
                'source_path': config['source_path'],
                'source_tool': 'Feather Builder',
                'artifact_type': config['source_type']
            }
            
            success, error = self.feather_db.insert_data(
                table_name, valid_data, source_info, config['columns']
            )
            progress.setValue(100)
            
            if success:
                # Ensure data is committed and connection is refreshed
                self.feather_db.connection.commit()
                
                # Save artifact type to metadata
                progress.setLabelText("Saving metadata...")
                if not self.save_artifact_type_to_metadata():
                    # User cancelled or error occurred
                    progress.close()
                    return
                
                QMessageBox.information(
                    self, "Import Complete",
                    f"Successfully imported {len(valid_data)} records into feather database.\n\n"
                    f"Artifact Type: {self.artifact_type}\n"
                    f"This metadata will be used when adding this feather to Wings."
                )
                self.status_bar.showMessage(f"Import complete: {len(valid_data)} records imported")
                
                # Auto-save configuration after successful import
                self._auto_save_config_after_import(config, table_name, len(valid_data))
                
                # Auto-register feather if service is available
                self._auto_register_feather_if_available()
                
                # Update data viewer with fresh database connection
                self.data_viewer.set_feather_database(self.feather_db)
                self.data_viewer.refresh_data()
                self.tab_widget.setCurrentWidget(self.data_viewer)
            else:
                QMessageBox.critical(self, "Import Failed", f"Import failed: {error}")
            
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Import failed: {str(e)}")
        finally:
            progress.close()
    
    def prepare_import_data(self, config: dict) -> list:
        """Prepare data for import based on source type."""
        if config['source_type'] == 'database':
            return self.prepare_database_data(config)
        elif config['source_type'] == 'csv':
            return self.prepare_csv_data(config)
        elif config['source_type'] == 'json':
            return self.prepare_json_data(config)
        return []
    
    def prepare_database_data(self, config: dict) -> list:
        """Prepare database data for import."""
        connection = config['connection']
        table_name = config['table_name']
        columns = config['columns']
        
        cursor = connection.cursor()
        
        # Get column names (excluding generated ones)
        col_names = [col['original'] for col in columns if col['original'] != '[ROW_COUNT]']
        col_str = ', '.join(col_names)
        
        cursor.execute(f"SELECT {col_str} FROM {table_name}")
        rows = cursor.fetchall()
        
        # Convert to list of dicts
        data = []
        for row in rows:
            record = dict(zip(col_names, row))
            data.append(record)
        
        return data
    
    def prepare_csv_data(self, config: dict) -> list:
        """Prepare CSV data for import."""
        data = config['data']
        headers = config['headers']
        columns = config['columns']
        
        # Convert rows to dicts
        result = []
        for row in data:
            if len(row) == len(headers):
                record = dict(zip(headers, row))
                result.append(record)
        
        return result
    
    def prepare_json_data(self, config: dict) -> list:
        """Prepare JSON data for import."""
        data = config['data']
        columns = config['columns']
        
        # Flatten nested JSON if needed
        result = []
        for item in data:
            record = {}
            for col in columns:
                if col['original'] == '[ROW_COUNT]':
                    continue
                
                # Handle nested keys
                value = self.get_nested_json_value(item, col['original'])
                record[col['original']] = value
            
            result.append(record)
        
        return result
    
    def get_nested_json_value(self, obj: dict, key_path: str):
        """Get value from nested JSON using dot notation."""
        keys = key_path.split('.')
        value = obj
        
        try:
            for key in keys:
                if isinstance(value, dict):
                    value = value.get(key)
                elif isinstance(value, list) and value:
                    value = value[0].get(key) if isinstance(value[0], dict) else None
                else:
                    return None
            return value
        except:
            return None
    
    def closeEvent(self, event):
        """Handle window close event."""
        # Close database connection
        if self.feather_db:
            try:
                self.feather_db.close()
            except:
                pass
        
        # Close source database connections from tabs
        if hasattr(self, 'db_tab') and self.db_tab.db_connection:
            try:
                self.db_tab.db_connection.close()
            except:
                pass
        
        event.accept()

    # Configuration Methods
    
    def save_feather_config(self):
        """Save current feather configuration"""
        if not CONFIG_AVAILABLE:
            QMessageBox.warning(self, "Not Available", "Configuration system not available")
            return
        
        # Get config name from user
        config_name, ok = QInputDialog.getText(
            self, "Save Configuration",
            "Enter configuration name:",
            QLineEdit.Normal,
            self.feather_name or "feather_config"
        )
        
        if not ok or not config_name:
            return
        
        try:
            # Capture current settings
            # Note: This is a simplified version - you'll need to capture actual settings
            # from the tabs (CSV, JSON, Database) based on which one is active
            
            config = FeatherConfig(
                config_name=config_name,
                feather_name=self.feather_name or "Unnamed Feather",
                artifact_type="Unknown",  # Should be detected or selected
                source_database="",  # Capture from active tab
                source_table="",  # Capture from active tab
                selected_columns=[],  # Capture from active tab
                column_mapping={},  # Capture from active tab
                timestamp_column="timestamp",
                timestamp_format="ISO8601",
                output_database=self.feather_path or "",
                created_by=os.getenv('USERNAME', 'Unknown'),
                description=f"Configuration for {self.feather_name}"
            )
            
            # Save configuration
            saved_path = self.config_manager.save_feather_config(config)
            
            QMessageBox.information(
                self, "Configuration Saved",
                f"Configuration saved successfully:\n{saved_path}\n\n"
                f"You can reuse this configuration in other cases."
            )
            
            self.current_config = config
            self.status_bar.showMessage(f"Configuration saved: {config_name}")
            
        except Exception as e:
            QMessageBox.critical(
                self, "Save Error",
                f"Failed to save configuration:\n{str(e)}"
            )
    
    def _auto_save_config_after_import(self, import_config: dict, table_name: str, record_count: int):
        """Automatically save feather configuration after successful import"""
        if not CONFIG_AVAILABLE or not self.config_manager:
            return
        
        try:
            # Generate config name from feather name
            config_name = self.feather_name.replace(' ', '_').lower() if self.feather_name else "feather_config"
            
            # Create feather config
            config = FeatherConfig(
                config_name=config_name,
                feather_name=self.feather_name or "Unnamed Feather",
                artifact_type=import_config.get('source_type', 'Unknown'),
                source_database=import_config.get('source_path', ''),
                source_table=import_config.get('source_table', table_name),
                selected_columns=[col['name'] for col in import_config.get('columns', [])],
                column_mapping={col['name']: col.get('feather_name', col['name']) 
                               for col in import_config.get('columns', [])},
                timestamp_column=import_config.get('timestamp_column', 'timestamp'),
                timestamp_format=import_config.get('timestamp_format', 'ISO8601'),
                output_database=self.feather_path or "",
                created_by=os.getenv('USERNAME', 'Unknown'),
                description=f"Auto-saved configuration for {self.feather_name}",
                total_records=record_count
            )
            
            # Save configuration silently
            saved_path = self.config_manager.save_feather_config(config)
            self.current_config = config
            self.status_bar.showMessage(f"✓ Config auto-saved: {config_name}")
            
        except Exception as e:
            # Don't show error to user, just log it
            print(f"Auto-save config failed: {e}")
    
    def load_feather_config(self):
        """Load a feather configuration"""
        if not CONFIG_AVAILABLE:
            QMessageBox.warning(self, "Not Available", "Configuration system not available")
            return
        
        try:
            # Get list of available configs
            configs = self.config_manager.list_feather_configs()
            
            if not configs:
                QMessageBox.information(
                    self, "No Configurations",
                    "No saved configurations found.\n\n"
                    "Create a feather and save its configuration first."
                )
                return
            
            # Let user select a config
            config_name, ok = QInputDialog.getItem(
                self, "Load Configuration",
                "Select configuration to load:",
                configs, 0, False
            )
            
            if not ok or not config_name:
                return
            
            # Load the configuration
            config = self.config_manager.load_feather_config(config_name)
            
            # Apply configuration to UI
            self.feather_name_input.setText(config.feather_name)
            self.feather_path_input.setText(config.output_database)
            
            # Show configuration details
            details = (
                f"Configuration: {config.config_name}\n"
                f"Artifact Type: {config.artifact_type}\n"
                f"Source: {config.source_database}\n"
                f"Columns: {len(config.selected_columns)}\n"
                f"Created: {config.created_date}\n\n"
                f"Note: You'll need to select the source data and apply the column mappings."
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
    
    def list_feather_configs(self):
        """List all available feather configurations"""
        if not CONFIG_AVAILABLE:
            QMessageBox.warning(self, "Not Available", "Configuration system not available")
            return
        
        try:
            configs = self.config_manager.list_feather_configs()
            
            if not configs:
                QMessageBox.information(
                    self, "No Configurations",
                    "No saved configurations found."
                )
                return
            
            # Build list of configs with details
            config_list = []
            for config_name in configs:
                try:
                    info = self.config_manager.get_config_info("feather", config_name)
                    config_list.append(
                        f"• {config_name}\n"
                        f"  Type: {info.get('artifact_type', 'Unknown')}\n"
                        f"  Records: {info.get('records', 0)}\n"
                    )
                except:
                    config_list.append(f"• {config_name}\n")
            
            message = "Available Feather Configurations:\n\n" + "\n".join(config_list)
            
            QMessageBox.information(
                self, "Feather Configurations",
                message
            )
            
        except Exception as e:
            QMessageBox.critical(
                self, "Error",
                f"Failed to list configurations:\n{str(e)}"
            )

    
    def on_source_database_selected(self, db_path: str):
        """
        Handle source database selection and perform artifact detection.
        
        Args:
            db_path: Path to selected source database
        """
        if not ARTIFACT_DETECTOR_AVAILABLE:
            return
        
        self.source_database_path = db_path
        
        try:
            # Perform artifact detection
            artifact_type, confidence, reason = ArtifactDetector.detect_artifact_type(db_path)
            
            if artifact_type:
                # Update detection display
                confidence_icon = "✓" if confidence >= 0.8 else "●" if confidence >= 0.6 else "○"
                self.artifact_detection_label.setText(
                    f"{confidence_icon} {artifact_type} ({confidence:.0%} confidence)"
                )
                self.artifact_detection_label.setStyleSheet("color: #00ff00; font-weight: bold;")
                
                # Update artifact type
                self.artifact_type = artifact_type
                self.detection_method = "auto"
                self.detection_confidence = confidence
                
                # Set combo box to detected type
                index = self.artifact_type_combo.findText(artifact_type)
                if index >= 0:
                    self.artifact_type_combo.setCurrentIndex(index)
                
                # Auto-generate feather name if not already set
                if not self.feather_name_input.text():
                    feather_name = ArtifactDetector.generate_feather_name(artifact_type)
                    self.feather_name_input.setText(feather_name)
                
                self.status_bar.showMessage(f"Detected artifact type: {artifact_type} - {reason}", 5000)
            else:
                # No detection
                self.artifact_detection_label.setText("⚠ Could not detect artifact type")
                self.artifact_detection_label.setStyleSheet("color: #ff9900; font-weight: bold;")
                self.status_bar.showMessage(f"Artifact detection: {reason}", 5000)
                
        except Exception as e:
            print(f"Error during artifact detection: {e}")
            self.artifact_detection_label.setText("⚠ Detection error")
            self.artifact_detection_label.setStyleSheet("color: #ff0000; font-weight: bold;")
    
    def _auto_register_feather_if_available(self):
        """
        Auto-register feather if auto-registration service is available.
        Called after successful import completion.
        """
        # Try Configuration Manager first
        if self.configuration_manager and self.feather_path and self.feather_name:
            try:
                # Get full database path
                db_path = os.path.join(self.feather_path, f"{self.feather_name}.db")
                
                # Get record count
                record_count = 0
                if self.feather_db and self.feather_db.connection:
                    cursor = self.feather_db.connection.cursor()
                    # Get first data table
                    cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name NOT IN ('feather_metadata', 'sqlite_sequence', 'import_history', 'data_lineage')"
                    )
                    tables = cursor.fetchall()
                    if tables:
                        table_name = tables[0][0]
                        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                        record_count = cursor.fetchone()[0]
                
                # Prepare metadata
                metadata = {
                    'source_database': self.source_database_path,
                    'import_date': __import__('datetime').datetime.now().isoformat(),
                    'record_count': record_count,
                    'detection_method': self.detection_method,
                    'detection_confidence': self.detection_confidence
                }
                
                # Register with Configuration Manager
                success = self.configuration_manager.add_feather(
                    feather_id=self.feather_name,
                    db_path=db_path,
                    artifact_type=self.artifact_type,
                    metadata=metadata
                )
                
                if success:
                    self.status_bar.showMessage(
                        f"✓ Feather registered: {self.feather_name}",
                        5000
                    )
                    print(f"[Feather Builder] Registered feather: {self.feather_name}")
                    return
                    
            except Exception as e:
                print(f"Configuration Manager registration failed: {e}")
        
        # Fallback to auto-registration service
        if not self.auto_registration_service:
            return
        
        if not self.feather_path or not self.feather_name:
            return
        
        try:
            # Get full database path
            db_path = os.path.join(self.feather_path, f"{self.feather_name}.db")
            
            # Register the feather with detected artifact type
            feather_config = self.auto_registration_service.register_new_feather(
                database_path=db_path,
                artifact_type=self.artifact_type,
                detection_method=self.detection_method,
                confidence=self.detection_confidence
            )
            
            # Show success notification
            self.status_bar.showMessage(
                f"✓ Feather auto-registered: {feather_config.feather_name}",
                5000
            )
            
        except Exception as e:
            # Don't fail the import if auto-registration fails
            print(f"Auto-registration failed: {e}")
            self.status_bar.showMessage(
                f"⚠ Auto-registration failed: {str(e)}",
                5000
            )
    
    def set_auto_registration_service(self, service):
        """
        Set the auto-registration service.
        Called by pipeline builder when opening feather builder.
        
        Args:
            service: FeatherAutoRegistrationService instance
        """
        self.auto_registration_service = service
