"""
Partition and Volume Analysis Window for Crow Eye
=================================================

This module provides a modern cyberpunk-themed UI window for displaying
disk partition and volume information. It features:
- Visual partition layout representation
- Detailed partition information table
- Color-coded partition types (boot, system, swap, Linux)
- Neon glow effects and dark theme aesthetics

Author: Ghassan Elsman (Crow Eye Team)
License: GPL-3.0
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QFrame, QScrollArea, QWidget, QPushButton, QProgressBar,
    QHeaderView, QSizePolicy
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QPalette
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Artifacts_Collectors.partition_analyzer import PartitionAnalyzer, PartitionInfo, DiskInfo


class PartitionLoadWorker(QThread):
    """Worker thread to load partition data without blocking the UI"""
    finished = pyqtSignal(list)  # Emits list of DiskInfo objects
    error = pyqtSignal(str)  # Emits error message
    status = pyqtSignal(str)  # Emits status messages
    
    def __init__(self, db_path=None, force_refresh=False):
        super().__init__()
        self.db_path = db_path
        self.force_refresh = force_refresh
    
    def run(self):
        """Load partition data in background thread"""
        try:
            analyzer = PartitionAnalyzer()
            disks = []
            
            # Debug: Print db_path
            print(f"[PartitionLoadWorker] db_path: {self.db_path}")
            print(f"[PartitionLoadWorker] force_refresh: {self.force_refresh}")
            
            # Check if database exists and load from it (unless force refresh)
            if self.db_path and os.path.exists(self.db_path) and not self.force_refresh:
                self.status.emit("Loading cached partition data...")
                print(f"[PartitionLoadWorker] Loading from existing database: {self.db_path}")
                disks = analyzer.load_from_database(self.db_path)
                
                if disks:
                    self.status.emit(f"Loaded {len(disks)} disk(s) from cache")
                    self.finished.emit(disks)
                    return
                else:
                    self.status.emit("Cache invalid, running fresh analysis...")
                    print("[PartitionLoadWorker] Database exists but returned no data")
            else:
                if self.force_refresh:
                    self.status.emit("Running fresh partition analysis...")
                    print("[PartitionLoadWorker] Force refresh requested")
                elif not self.db_path:
                    self.status.emit("No database path provided, analyzing partitions...")
                    print("[PartitionLoadWorker] No db_path provided")
                else:
                    self.status.emit("No cache found, analyzing partitions...")
                    print(f"[PartitionLoadWorker] Database does not exist: {self.db_path}")
            
            # Run fresh analysis
            disks = analyzer.get_disks_with_partitions()
            
            # Save to database if path provided
            if self.db_path:
                # Ensure directory exists
                db_dir = os.path.dirname(self.db_path)
                if db_dir and not os.path.exists(db_dir):
                    print(f"[PartitionLoadWorker] Creating directory: {db_dir}")
                    os.makedirs(db_dir, exist_ok=True)
                
                self.status.emit("Saving results to database...")
                print(f"[PartitionLoadWorker] Saving to database: {self.db_path}")
                success = analyzer.save_to_database(self.db_path, disks)
                if success:
                    print(f"[PartitionLoadWorker] Successfully saved to database")
                else:
                    print(f"[PartitionLoadWorker] Failed to save to database")
            else:
                print("[PartitionLoadWorker] No db_path, skipping database save")
                
            self.status.emit("Analysis complete")
            self.finished.emit(disks)
        except Exception as e:
            print(f"[PartitionLoadWorker] Error: {e}")
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))


class PartitionVisualizationWidget(QWidget):
    """Widget to display visual representation of disk partitions"""
    
    def __init__(self, disk: DiskInfo, analyzer: PartitionAnalyzer, parent=None):
        super().__init__(parent)
        self.disk = disk
        self.analyzer = analyzer
        self.init_ui()
    
    def _get_partition_color(self, partition: PartitionInfo) -> tuple:
        """
        Determine the color scheme for a partition based on its type.
        
        Args:
            partition: PartitionInfo object
            
        Returns:
            Tuple of (bg_color, border_color, text_color)
        """
        if partition.is_boot or partition.is_efi_system or "efi" in str(partition.partition_type).lower():
            return ("#00CED1", "#00FFFF", "#000000")  # Cyan for boot/EFI
        elif partition.is_system:
            return ("#3B82F6", "#60A5FA", "#FFFFFF")  # Blue for system
        elif partition.is_swap or "swap" in str(partition.partition_type).lower() or "hibernate" in str(partition.partition_type).lower():
            return ("#8B5CF6", "#A78BFA", "#FFFFFF")  # Purple for swap/hibernate
        elif partition.is_linux:
            return ("#10B981", "#34D399", "#FFFFFF")  # Green for Linux
        elif "recovery" in str(partition.partition_type).lower():
            return ("#F59E0B", "#FBBF24", "#000000")  # Orange for Recovery
        elif "reserved" in str(partition.partition_type).lower() or "msr" in str(partition.partition_type).lower():
            return ("#64748B", "#94A3B8", "#FFFFFF")  # Slate Gray for Reserved/MSR
        else:
            return ("#475569", "#64748B", "#E2E8F0")  # Gray for data
    
    def init_ui(self):
        """Initialize the partition visualization UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # Disk header
        header_layout = QHBoxLayout()
        
        disk_label = QLabel(f"💾 Disk {self.disk.disk_index}: {self.disk.model}")
        disk_label.setStyleSheet("""
            QLabel {
                color: #00FFFF;
                font-size: 14px;
                font-weight: bold;
                font-family: 'Segoe UI', sans-serif;
                padding: 5px;
            }
        """)
        header_layout.addWidget(disk_label)
        
        disk_size_label = QLabel(f"Size: {self.analyzer.format_size(self.disk.size)}")
        disk_size_label.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 12px;
                font-family: 'Segoe UI', sans-serif;
                padding: 5px;
            }
        """)
        header_layout.addWidget(disk_size_label)
        
        # Add forensic badges
        if self.disk.is_bootable:
            boot_badge = QLabel("BOOTABLE")
            boot_badge.setStyleSheet("""
                QLabel {
                    background-color: #EF4444;
                    color: #FFFFFF;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 3px 6px;
                    border-radius: 4px;
                }
            """)
            header_layout.addWidget(boot_badge)
            
        if self.disk.is_usb:
            usb_badge = QLabel("USB")
            usb_badge.setStyleSheet("""
                QLabel {
                    background-color: #F59E0B;
                    color: #FFFFFF;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 3px 6px;
                    border-radius: 4px;
                }
            """)
            header_layout.addWidget(usb_badge)
            
        if self.disk.is_removable:
            rem_badge = QLabel("REMOVABLE")
            rem_badge.setStyleSheet("""
                QLabel {
                    background-color: #8B5CF6;
                    color: #FFFFFF;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 3px 6px;
                    border-radius: 4px;
                }
            """)
            header_layout.addWidget(rem_badge)
            
        header_layout.addStretch()
        
        layout.addLayout(header_layout)
        
        # Visual partition bar
        partition_bar = QWidget()
        partition_bar.setMinimumHeight(60)
        partition_bar.setMaximumHeight(60)
        partition_bar.setStyleSheet("""
            QWidget {
                background-color: #0F172A;
                border: none;
            }
        """)
        partition_bar_layout = QHBoxLayout(partition_bar)
        partition_bar_layout.setContentsMargins(0, 0, 0, 0)
        partition_bar_layout.setSpacing(2)
        
        # Calculate total size for proportional display
        total_size = self.disk.size if self.disk.size > 0 else sum(p.total_size for p in self.disk.partitions)
        
        for partition in self.disk.partitions:
            # Calculate partition width based on size
            if total_size > 0:
                width_ratio = partition.total_size / total_size
            else:
                width_ratio = 1.0 / len(self.disk.partitions) if self.disk.partitions else 1.0
            
            # Create partition segment
            segment = QFrame()
            segment.setFrameShape(QFrame.Box)
            
            # Determine color based on partition type using helper method
            bg_color, border_color, text_color = self._get_partition_color(partition)
            
            segment.setStyleSheet(f"""
                QFrame {{
                    background-color: {bg_color};
                    border: 2px solid {border_color};
                    border-radius: 4px;
                }}
            """)
            
            # Add label inside segment
            segment_layout = QVBoxLayout(segment)
            segment_layout.setContentsMargins(2, 2, 2, 2)
            
            # Partition label
            label_text = partition.mountpoint if partition.mountpoint else partition.device
            label = QLabel(label_text)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(f"""
                QLabel {{
                    color: {text_color};
                    font-size: 10px;
                    font-weight: bold;
                    background: transparent;
                    border: none;
                }}
            """)
            segment_layout.addWidget(label)
            
            # Size label
            size_label = QLabel(self.analyzer.format_size(partition.total_size))
            size_label.setAlignment(Qt.AlignCenter)
            size_label.setStyleSheet(f"""
                QLabel {{
                    color: {text_color};
                    font-size: 8px;
                    background: transparent;
                    border: none;
                }}
            """)
            segment_layout.addWidget(size_label)
            
            # Set size policy and stretch factor
            segment.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            partition_bar_layout.addWidget(segment, int(width_ratio * 100))
        
        layout.addWidget(partition_bar)
        
        # Legend
        legend_layout = QHBoxLayout()
        legend_layout.setSpacing(15)
        
        legend_items = [
            ("Boot", "#00CED1"),
            ("System", "#3B82F6"),
            ("Swap", "#8B5CF6"),
            ("Linux", "#10B981"),
            ("Recovery", "#F59E0B"),
            ("Data", "#475569")
        ]
        
        for label_text, color in legend_items:
            legend_item = QHBoxLayout()
            
            color_box = QFrame()
            color_box.setFixedSize(12, 12)
            color_box.setStyleSheet(f"""
                QFrame {{
                    background-color: {color};
                    border: 1px solid #FFFFFF;
                    border-radius: 2px;
                }}
            """)
            legend_item.addWidget(color_box)
            
            label = QLabel(label_text)
            label.setStyleSheet("""
                QLabel {
                    color: #94A3B8;
                    font-size: 10px;
                    font-family: 'Segoe UI', sans-serif;
                }
            """)
            legend_item.addWidget(label)
            
            legend_layout.addLayout(legend_item)
        
        legend_layout.addStretch()
        layout.addLayout(legend_layout)
        
        # Set widget style - DARK THEME
        self.setStyleSheet("""
            QWidget {
                background-color: #0F172A;
                border: 1px solid #334155;
                border-radius: 8px;
            }
        """)


class PartitionWindow(QDialog):
    """
    Main window for displaying partition and volume analysis.
    Features a modern cyberpunk-themed UI with neon accents.
    """
    
    def __init__(self, db_path=None, parent=None):
        super().__init__(parent)
        self.analyzer = PartitionAnalyzer()
        self.disks = []
        self.db_path = db_path
        self.init_ui()
        self.load_partition_data()
    
    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("Partition & Volume Analysis - Crow Eye")
        self.setMinimumSize(1200, 800)
        
        # Set window style
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0a0a0a, stop:0.5 #0F172A, stop:1 #0a0a0a);
                color: #E2E8F0;
            }
        """)
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # Header
        header = self.create_header()
        main_layout.addWidget(header)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("""
            QFrame {
                background-color: #00FFFF;
                border: none;
                height: 2px;
                margin: 10px 0;
            }
        """)
        main_layout.addWidget(separator)
        
        # Disk visualization area (scrollable)
        self.disk_viz_scroll = QScrollArea()
        self.disk_viz_scroll.setWidgetResizable(True)
        self.disk_viz_scroll.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background-color: #1E293B;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #475569;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #00FFFF;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)
        
        self.disk_viz_container = QWidget()
        self.disk_viz_container.setStyleSheet("""
            QWidget {
                background-color: #0F172A;
            }
        """)
        self.disk_viz_layout = QVBoxLayout(self.disk_viz_container)
        self.disk_viz_layout.setSpacing(15)
        self.disk_viz_scroll.setWidget(self.disk_viz_container)
        
        main_layout.addWidget(self.disk_viz_scroll, 1)
        
        # Partition details table
        table_label = QLabel("📊 Partition Details")
        table_label.setStyleSheet("""
            QLabel {
                color: #00FFFF;
                font-size: 16px;
                font-weight: bold;
                font-family: 'Segoe UI', sans-serif;
                padding: 10px 0;
            }
        """)
        main_layout.addWidget(table_label)
        
        self.partition_table = self.create_partition_table()
        main_layout.addWidget(self.partition_table, 2)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        refresh_btn = QPushButton("Refresh Analysis")
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: #FFFFFF;
                border: 2px solid #34D399;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: #34D399;
                border: 2px solid #6EE7B7;
            }
            QPushButton:pressed {
                background-color: #059669;
            }
        """)
        refresh_btn.clicked.connect(self.refresh_data)
        button_layout.addWidget(refresh_btn)
        
        button_layout.addStretch()
        
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: #FFFFFF;
                border: 2px solid #60A5FA;
                border-radius: 8px;
                padding: 10px 30px;
                font-weight: bold;
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: #60A5FA;
                border: 2px solid #93C5FD;
            }
            QPushButton:pressed {
                background-color: #1E40AF;
            }
        """)
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)
        
        main_layout.addLayout(button_layout)
    
    def create_header(self):
        """Create the header section with title and description"""
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(5)
        
        # Title
        title = QLabel("⚡ PARTITION & VOLUME ANALYSIS")
        title.setStyleSheet("""
            QLabel {
                color: #00FFFF;
                font-size: 28px;
                font-weight: bold;
                font-family: 'Segoe UI', sans-serif;
                text-transform: uppercase;
                letter-spacing: 2px;
                padding: 5px 0;
            }
        """)
        header_layout.addWidget(title)
        
        # Subtitle with boot mode
        boot_mode_text = f"Boot Mode: {self.analyzer.boot_mode} | Comprehensive disk and partition information with BIOS/UEFI and MBR/GPT detection"
        subtitle = QLabel(boot_mode_text)
        subtitle.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
                padding: 0 0 5px 0;
            }
        """)
        header_layout.addWidget(subtitle)
        
        return header_widget
    
    def create_partition_table(self):
        """Create the partition details table with enhanced forensic columns"""
        table = QTableWidget()
        table.setColumnCount(15)
        table.setHorizontalHeaderLabels([
            "Disk", "Volume", "Device", "Mount Point", "File System", 
            "Total Size", "Used", "% Used", "Partition Style", "Type", 
            "Volume Serial", "GUID", "Flags", "Boot Mode", "Disk Sig"
        ])
        
        # Set table style
        table.setStyleSheet("""
            QTableWidget {
                background-color: #0B1220;
                alternate-background-color: #0F172A;
                color: #E2E8F0;
                gridline-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 8px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                selection-background-color: #3B82F6;
                selection-color: #FFFFFF;
            }
            QTableWidget::item {
                padding: 10px;
                border-bottom: 1px solid #1E293B;
                background-color: transparent;
            }
            QTableWidget::item:selected {
                background-color: #2563EB;
                color: #FFFFFF;
            }
            QTableWidget::item:hover {
                background-color: #1E293B;
            }
            QHeaderView::section {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1E293B, stop:1 #0F172A);
                color: #38BDF8;
                padding: 12px;
                border: none;
                border-right: 1px solid #334155;
                border-bottom: 2px solid #38BDF8;
                font-weight: bold;
                font-size: 12px;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            QHeaderView::section:hover {
                background-color: #334155;
                color: #00FFFF;
            }
            QTableCornerButton::section {
                background-color: #0B1220;
                border: none;
                border-right: 1px solid #334155;
                border-bottom: 2px solid #38BDF8;
            }
            QScrollBar:vertical {
                background-color: #0B1220;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #475569;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #00FFFF;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
            QScrollBar:horizontal {
                background-color: #0B1220;
                height: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal {
                background-color: #475569;
                border-radius: 6px;
                min-width: 20px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #00FFFF;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: transparent;
            }
        """)
        
        # Configure table properties
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setSortingEnabled(True)
        table.verticalHeader().setVisible(False)
        
        # Set column widths
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        
        return table
    
    def load_partition_data(self, force_refresh=False):
        """Load partition data in background thread"""
        # Show loading state
        self.partition_table.setRowCount(0)
        
        # Clear visualizations
        while self.disk_viz_layout.count():
            child = self.disk_viz_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
                
        self.loading_label = QLabel("Initializing...")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet("color: #00FFFF; font-size: 16px; padding: 20px;")
        self.disk_viz_layout.addWidget(self.loading_label)
        
        self.worker = PartitionLoadWorker(self.db_path, force_refresh)
        self.worker.finished.connect(self.on_data_loaded)
        self.worker.error.connect(self.on_load_error)
        self.worker.status.connect(self.on_status_update)
        self.worker.start()
        
    def on_status_update(self, message):
        """Update loading status message"""
        if hasattr(self, 'loading_label') and self.loading_label:
            self.loading_label.setText(message)
        
    def refresh_data(self):
        """Refresh the partition data (force fresh analysis)"""
        self.load_partition_data(force_refresh=True)
    
    def on_data_loaded(self, disks):
        """Handle loaded partition data"""
        # Sort disks by disk_index to ensure Disk 0 appears first
        self.disks = sorted(disks, key=lambda d: d.disk_index)
        self.populate_disk_visualizations()
        self.populate_partition_table()
    
    def on_load_error(self, error_msg):
        """Handle data loading error"""
        error_label = QLabel(f"❌ Error loading partition data: {error_msg}")
        error_label.setStyleSheet("""
            QLabel {
                color: #EF4444;
                font-size: 14px;
                font-weight: bold;
                padding: 20px;
            }
        """)
        self.disk_viz_layout.addWidget(error_label)
    
    def populate_disk_visualizations(self):
        """Populate the disk visualization area"""
        # Clear existing widgets
        while self.disk_viz_layout.count():
            child = self.disk_viz_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        # Add visualization for each disk
        for disk in self.disks:
            viz_widget = PartitionVisualizationWidget(disk, self.analyzer)
            self.disk_viz_layout.addWidget(viz_widget)
        
        # Add stretch at the end
        self.disk_viz_layout.addStretch()
    
    def populate_partition_table(self):
        """Populate the partition details table"""
        self.partition_table.setRowCount(0)
        
        for disk in self.disks:
            for partition in disk.partitions:
                row = self.partition_table.rowCount()
                self.partition_table.insertRow(row)
                
                # Disk number (NEW - Column 0)
                disk_item = QTableWidgetItem(f"Disk {disk.disk_index}")
                disk_item.setForeground(QColor("#00FFFF"))  # Cyan for disk number
                self.partition_table.setItem(row, 0, disk_item)
                
                # Volume label
                self.partition_table.setItem(row, 1, QTableWidgetItem(partition.volume_label or "-"))
                
                # Device
                self.partition_table.setItem(row, 2, QTableWidgetItem(partition.device))
                
                # Mount point
                self.partition_table.setItem(row, 3, QTableWidgetItem(partition.mountpoint))
                
                # File system
                fs_item = QTableWidgetItem(partition.fstype)
                if partition.is_linux:
                    fs_item.setForeground(QColor("#10B981"))  # Green for Linux FS
                self.partition_table.setItem(row, 4, fs_item)
                
                # Total size
                self.partition_table.setItem(row, 5, QTableWidgetItem(
                    self.analyzer.format_size(partition.total_size)))
                
                # Used
                self.partition_table.setItem(row, 6, QTableWidgetItem(
                    self.analyzer.format_size(partition.used_size)))
                
                # % Used (with color coding)
                percent_item = QTableWidgetItem(f"{partition.percent_used:.1f}%")
                if partition.percent_used > 90:
                    percent_item.setForeground(QColor("#EF4444"))  # Red
                elif partition.percent_used > 75:
                    percent_item.setForeground(QColor("#F59E0B"))  # Orange
                else:
                    percent_item.setForeground(QColor("#10B981"))  # Green
                self.partition_table.setItem(row, 7, percent_item)
                
                # Partition Style (MBR/GPT)
                style_item = QTableWidgetItem(partition.partition_style)
                if partition.partition_style == "GPT":
                    style_item.setForeground(QColor("#00FFFF"))  # Cyan for GPT
                elif partition.partition_style == "MBR":
                    style_item.setForeground(QColor("#F59E0B"))  # Orange for MBR
                self.partition_table.setItem(row, 8, style_item)
                
                # Type
                self.partition_table.setItem(row, 9, QTableWidgetItem(partition.partition_type))
                
                # Volume Serial
                self.partition_table.setItem(row, 10, QTableWidgetItem(partition.volume_serial or "-"))
                
                # Partition GUID
                guid_text = partition.partition_guid[:36] if partition.partition_guid else "-"
                self.partition_table.setItem(row, 11, QTableWidgetItem(guid_text))
                
                # Flags
                flags = []
                if partition.is_boot:
                    flags.append("BOOT")
                if partition.is_system:
                    flags.append("SYSTEM")
                if partition.is_swap:
                    flags.append("SWAP")
                if partition.is_linux:
                    flags.append("LINUX")
                if partition.is_efi_system:
                    flags.append("EFI")
                if partition.is_active:
                    flags.append("ACTIVE")
                if partition.is_hidden:
                    flags.append("HIDDEN")
                
                flags_item = QTableWidgetItem(", ".join(flags) if flags else "-")
                if partition.is_boot or partition.is_efi_system:
                    flags_item.setForeground(QColor("#00FFFF"))  # Cyan for boot/EFI
                elif partition.is_system:
                    flags_item.setForeground(QColor("#3B82F6"))  # Blue for system
                elif partition.is_hidden:
                    flags_item.setForeground(QColor("#EF4444"))  # Red for hidden
                self.partition_table.setItem(row, 12, flags_item)
                
                # Boot Mode (from disk)
                boot_mode = disk.boot_mode if hasattr(disk, 'boot_mode') else "Unknown"
                boot_item = QTableWidgetItem(boot_mode)
                if boot_mode == "UEFI":
                    boot_item.setForeground(QColor("#00FFFF"))  # Cyan for UEFI
                elif boot_mode == "BIOS":
                    boot_item.setForeground(QColor("#F59E0B"))  # Orange for BIOS
                self.partition_table.setItem(row, 13, boot_item)
                
                # Disk Signature
                disk_sig = partition.disk_signature if partition.disk_signature else "-"
                self.partition_table.setItem(row, 14, QTableWidgetItem(disk_sig))
        
        # Resize columns to content
        self.partition_table.resizeColumnsToContents()


def main():
    """Test function to display the partition window"""
    from PyQt5.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    window = PartitionWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
