"""
Feather Widget
Widget for configuring individual feather specifications.
"""

import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QComboBox, QRadioButton,
    QButtonGroup, QFileDialog, QMessageBox, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from correlation_engine.wings.core.wing_model import FeatherSpec
from correlation_engine.wings.core.artifact_detector import ArtifactDetector


class FeatherWidget(QWidget):
    """Widget for configuring a single feather"""
    
    feather_changed = pyqtSignal()
    remove_requested = pyqtSignal(object)  # Passes self as argument
    
    def __init__(self, feather_number: int):
        super().__init__()
        self.feather_number = feather_number
        self.case_directory = None  # Store case directory for path resolution
        self.feather_spec = FeatherSpec(
            feather_id=f"feather_{feather_number}",
            database_filename="",
            artifact_type="Unknown",
            detection_confidence="low",
            manually_overridden=False
        )
        self.init_ui()
    
    def set_case_directory(self, case_directory: str):
        """Set the case directory for feather path resolution"""
        self.case_directory = case_directory
        print(f"[FeatherWidget] Case directory set to: {case_directory}")
        
        # If we already have a feather_spec, re-resolve paths
        if self.feather_spec and self.feather_spec.database_filename:
            self._resolve_feather_path()
    
    def _resolve_feather_path(self):
        """
        Resolve feather database path with comprehensive search.
        
        This method attempts to find the actual feather database file by checking
        multiple potential locations. It provides visual feedback through color coding:
        - Green: Path found and exists
        - Orange: Path not found (needs to be created or corrected)
        """
        if not self.feather_spec:
            return
        
        from pathlib import Path
        
        # Start with what we have
        current_path = self.feather_spec.database_filename
        
        # If it's already an absolute path that exists, use it
        if current_path and os.path.isabs(current_path) and os.path.exists(current_path):
            self.db_path_edit.setText(current_path)
            self.db_path_edit.setStyleSheet("color: #00FF00;")  # Green = found
            print(f"[FeatherWidget] Using absolute path: {current_path}")
            return
        
        # Build list of potential paths
        potential_paths = []
        
        # Priority 1: Case directory paths
        if self.case_directory:
            case_path = Path(self.case_directory)
            correlation_dir = case_path / "Correlation" / "feathers"
            
            # Try with database_filename as-is
            if current_path:
                # Remove any leading path components to get just the filename
                filename_only = Path(current_path).name
                potential_paths.append(correlation_dir / filename_only)
                
                # Also try the full relative path from case root
                potential_paths.append(case_path / current_path)
                potential_paths.append(case_path / "Correlation" / current_path)
            
            # Try with feather_config_name (from default wings)
            if hasattr(self.feather_spec, 'feather_config_name') and self.feather_spec.feather_config_name:
                config_name = self.feather_spec.feather_config_name
                potential_paths.extend([
                    correlation_dir / f"{config_name}.db",
                    correlation_dir / config_name,  # In case it already has .db
                ])
            
            # Try with feather_id
            if self.feather_spec.feather_id:
                fid = self.feather_spec.feather_id
                potential_paths.extend([
                    correlation_dir / f"{fid}.db",
                    correlation_dir / f"{fid}_CrowEyeFeather.db",
                ])
        
        # Priority 2: Relative to current working directory
        if current_path:
            potential_paths.extend([
                Path(current_path),
                Path("feathers") / Path(current_path).name,
                Path("Correlation") / "feathers" / Path(current_path).name,
            ])
        
        # Try each path
        for path in potential_paths:
            if path.exists():
                resolved_path = str(path.absolute())
                print(f"[FeatherWidget] ✓ Resolved path: {resolved_path}")
                self.db_path_edit.setText(resolved_path)
                self.db_path_edit.setStyleSheet("color: #00FF00;")  # Green = found
                
                # Update feather spec with resolved path
                self.feather_spec.database_filename = resolved_path
                return
        
        # Not found - show original path in orange
        print(f"[FeatherWidget] ✗ Could not resolve path for: {current_path}")
        print(f"[FeatherWidget]   Tried {len(potential_paths)} locations")
        if current_path:
            self.db_path_edit.setText(current_path)
        else:
            self.db_path_edit.setText(f"[Not Set - {self.feather_spec.feather_id}]")
        self.db_path_edit.setStyleSheet("color: #FFA500;")  # Orange = not found
    
    def init_ui(self):
        """Initialize the user interface"""
        # Main group box
        self.group_box = QGroupBox(f"Feather {self.feather_number}")
        layout = QVBoxLayout(self)
        layout.addWidget(self.group_box)
        
        # Group box layout
        group_layout = QVBoxLayout(self.group_box)
        
        # Database selection section
        db_section = self.create_database_section()
        group_layout.addWidget(db_section)
        
        # Artifact type section
        artifact_section = self.create_artifact_section()
        group_layout.addWidget(artifact_section)
        
        # Remove button
        remove_layout = QHBoxLayout()
        remove_layout.addStretch()
        self.remove_btn = QPushButton("Remove Feather")
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        remove_layout.addWidget(self.remove_btn)
        group_layout.addLayout(remove_layout)
    
    def create_database_section(self):
        """Create database selection section"""
        frame = QFrame()
        layout = QGridLayout(frame)
        
        # Database file selection
        layout.addWidget(QLabel("Feather Database:"), 0, 0)
        
        db_layout = QHBoxLayout()
        self.db_path_edit = QLineEdit()
        self.db_path_edit.setPlaceholderText("Select Feather database file...")
        self.db_path_edit.textChanged.connect(self.on_database_changed)
        db_layout.addWidget(self.db_path_edit)
        
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.browse_database)
        db_layout.addWidget(browse_btn)
        
        layout.addLayout(db_layout, 0, 1)
        
        # Database info
        self.db_info_label = QLabel("No database selected")
        self.db_info_label.setStyleSheet("color: #666; font-size: 10px;")
        layout.addWidget(self.db_info_label, 1, 1)
        
        return frame
    
    def create_artifact_section(self):
        """Create artifact type selection section"""
        frame = QFrame()
        layout = QGridLayout(frame)
        
        # Detection result
        layout.addWidget(QLabel("Auto-Detected:"), 0, 0)
        self.detection_label = QLabel("⚠ No database selected")
        layout.addWidget(self.detection_label, 0, 1)
        
        # Artifact type selection
        layout.addWidget(QLabel("Artifact Type:"), 1, 0)
        self.artifact_combo = QComboBox()
        self.populate_artifact_combo()
        self.artifact_combo.currentTextChanged.connect(self.on_artifact_type_changed)
        layout.addWidget(self.artifact_combo, 1, 1)
        
        return frame
    

    def populate_artifact_combo(self):
        """Populate artifact type combo box"""
        self.artifact_combo.clear()
        
        # Add "Unknown" option
        self.artifact_combo.addItem("⚠ Unknown - Please select")
        
        # Add all artifact types
        for artifact_type in ArtifactDetector.get_all_artifact_types():
            self.artifact_combo.addItem(artifact_type)
    
    def browse_database(self):
        """Browse for database file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Feather Database", "", 
            "Database Files (*.db);;All Files (*)"
        )
        
        if file_path:
            self.db_path_edit.setText(file_path)
    
    def on_database_changed(self):
        """Handle database path change with metadata-first detection"""
        db_path = self.db_path_edit.text().strip()
        
        if not db_path:
            self.db_info_label.setText("No database selected")
            self.detection_label.setText("⚠ No database selected")
            self.artifact_combo.setCurrentIndex(0)  # Unknown
            return
        
        # Check if file exists
        if not os.path.exists(db_path):
            self.db_info_label.setText("⚠ File not found")
            self.detection_label.setText("⚠ File not found")
            return
        
        # Update feather spec
        self.feather_spec.database_filename = os.path.basename(db_path)
        
        # Priority detection: metadata → table name → filename
        detected_type, confidence, method = self._detect_with_metadata_priority(db_path)
        
        # Update detection display
        icon = ArtifactDetector.get_confidence_icon(confidence)
        method_text = self._get_method_display_text(method)
        self.detection_label.setText(
            f"{icon} {detected_type} ({confidence} confidence - {method_text})"
        )
        
        # Update artifact combo
        if detected_type != "Unknown":
            # Find and select the detected type
            for i in range(self.artifact_combo.count()):
                if self.artifact_combo.itemText(i) == detected_type:
                    self.artifact_combo.setCurrentIndex(i)
                    break
        
        # Update feather spec
        self.feather_spec.artifact_type = detected_type
        self.feather_spec.detection_confidence = confidence
        self.feather_spec.detection_method = method
        self.feather_spec.manually_overridden = False
        
        # Show database info
        try:
            file_size = os.path.getsize(db_path)
            size_mb = file_size / (1024 * 1024)
            self.db_info_label.setText(f"Database loaded - {size_mb:.1f} MB")
        except:
            self.db_info_label.setText("Database loaded")
        
        self.feather_changed.emit()
    
    def _detect_with_metadata_priority(self, db_path: str):
        """
        Detect artifact type with metadata-first priority.
        
        Returns:
            Tuple of (artifact_type, confidence, method)
            method: "metadata", "table_name", "filename", "unknown"
        """
        # Try metadata first
        metadata_type = ArtifactDetector.detect_from_metadata(db_path)
        if metadata_type:
            return metadata_type, "high", "metadata"
        
        # Try table name
        table_type, table_confidence = ArtifactDetector.detect_from_table_name(db_path)
        if table_type != "Unknown":
            return table_type, table_confidence, "table_name"
        
        # Fall back to filename (current behavior)
        filename = os.path.basename(db_path)
        filename_type, filename_confidence = ArtifactDetector.detect_from_filename(filename)
        return filename_type, filename_confidence, "filename"
    
    def _get_method_display_text(self, method: str) -> str:
        """Get user-friendly display text for detection method"""
        return {
            "metadata": "from metadata",
            "table_name": "from table name",
            "filename": "from filename",
            "unknown": "unknown"
        }.get(method, method)
    
    def on_artifact_type_changed(self):
        """Handle artifact type selection change"""
        selected_text = self.artifact_combo.currentText()
        
        if selected_text.startswith("⚠ Unknown"):
            self.feather_spec.artifact_type = "Unknown"
        else:
            self.feather_spec.artifact_type = selected_text
            
            # Check if this is a manual override
            if hasattr(self, 'feather_spec') and self.feather_spec.database_filename:
                # Re-detect to see if user changed from auto-detection
                filename = self.feather_spec.database_filename
                detected_type, _ = ArtifactDetector.detect_from_filename(filename)
                
                if detected_type != selected_text:
                    self.feather_spec.manually_overridden = True
                    # Update detection label to show override
                    self.detection_label.setText(
                        f"✓ {selected_text} (manually selected, was {detected_type})"
                    )
        
        self.feather_changed.emit()
    

    def get_feather_spec(self) -> FeatherSpec:
        """Get the current feather specification"""
        return self.feather_spec
    
    def set_feather_spec(self, feather_spec: FeatherSpec):
        """Set the feather specification and resolve paths"""
        self.feather_spec = feather_spec
        
        # Resolve and set the path
        self._resolve_feather_path()
        
        # Set artifact type
        if feather_spec.artifact_type == "Unknown":
            self.artifact_combo.setCurrentIndex(0)
        else:
            for i in range(self.artifact_combo.count()):
                if self.artifact_combo.itemText(i) == feather_spec.artifact_type:
                    self.artifact_combo.setCurrentIndex(i)
                    break
        
        # Update detection display with proper icons
        if feather_spec.manually_overridden:
            self.detection_label.setText(
                f"✓ {feather_spec.artifact_type} (manually selected)"
            )
        else:
            icon = ArtifactDetector.get_confidence_icon(feather_spec.detection_confidence)
            method_text = self._get_method_display_text(
                getattr(feather_spec, 'detection_method', 'filename')
            )
            self.detection_label.setText(
                f"{icon} {feather_spec.artifact_type} ({feather_spec.detection_confidence} confidence - {method_text})"
            )
    
    def set_feather_number(self, number: int):
        """Update feather number"""
        self.feather_number = number
        self.group_box.setTitle(f"Feather {number}")
        self.feather_spec.feather_id = f"feather_{number}"
