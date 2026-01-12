"""
Results Tab Widget

Multi-tab result management with semantic mapping and scoring support.
Ensures semantic mapping information and scoring data are preserved across tabs.

Provides engine-specific column configurations for time-window and identity-based engines.
Includes integrated tab close button styling with theme support.
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QGroupBox, QFormLayout,
    QPushButton, QLineEdit, QSlider, QCheckBox, QComboBox,
    QSplitter, QTextEdit, QMessageBox, QFileDialog, QDateTimeEdit,
    QFrame, QMenu, QAction
)
from PyQt5.QtCore import Qt, pyqtSignal, QDateTime
from PyQt5.QtGui import QColor, QContextMenuEvent

from ..engine.correlation_result import CorrelationResult, CorrelationMatch
from .scoring_breakdown_widget import ScoringBreakdownWidget
from .semantic_info_display_widget import SemanticInfoDisplayWidget


# ============================================================================
# Tab Close Button Styling - Integrated
# ============================================================================

def apply_tab_close_button_styling(tab_widget: QTabWidget, theme: str = "dark"):
    """
    Apply enhanced styling to tab close buttons with theme support.
    
    This function applies comprehensive styling to QTabWidget close buttons,
    ensuring they are visible, properly sized, and have appropriate hover effects.
    
    Args:
        tab_widget: QTabWidget to apply styling to
        theme: Theme to use ("dark" or "light"), defaults to "dark"
    
    Features:
        - Properly sized and positioned close buttons
        - Visible close button indicators (×)
        - Hover effects for better UX
        - Theme-aware colors
        - Consistent styling across tabs
    """
    if theme == "light":
        # Light theme colors
        pane_bg = "#f5f5f5"
        tab_bg = "#e0e0e0"
        tab_selected_bg = "#ffffff"
        tab_hover_bg = "#eeeeee"
        tab_text = "#333333"
        tab_selected_text = "#000000"
        close_btn_hover_bg = "#ff5252"
        border_color = "#cccccc"
    else:
        # Dark theme colors (default)
        pane_bg = "#1a1a2e"
        tab_bg = "#2a2a3e"
        tab_selected_bg = "#3a3a4e"
        tab_hover_bg = "#3a3a4e"
        tab_text = "#aaaaaa"
        tab_selected_text = "#ffffff"
        close_btn_hover_bg = "#f44336"
        border_color = "#444444"
    
    # Comprehensive stylesheet for tab widget and close buttons
    stylesheet = f"""
        QTabWidget::pane {{
            border: 1px solid {border_color};
            background-color: {pane_bg};
            border-radius: 4px;
            top: -1px;
        }}
        
        QTabBar::tab {{
            background-color: {tab_bg};
            color: {tab_text};
            padding: 6px 12px;
            padding-right: 25px;
            margin-right: 2px;
            border: 1px solid {border_color};
            border-bottom: none;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            min-width: 80px;
        }}
        
        QTabBar::tab:selected {{
            background-color: {tab_selected_bg};
            color: {tab_selected_text};
            border-bottom: 2px solid #2196F3;
            font-weight: bold;
        }}
        
        QTabBar::tab:hover:!selected {{
            background-color: {tab_hover_bg};
        }}
        
        QTabBar::tab:!selected {{
            margin-top: 2px;
        }}
        
        QTabBar::close-button {{
            image: none;
            subcontrol-position: right;
            subcontrol-origin: padding;
            background-color: transparent;
            border: none;
            border-radius: 2px;
            padding: 2px;
            margin: 2px;
            width: 16px;
            height: 16px;
        }}
        
        QTabBar::close-button:hover {{
            background-color: {close_btn_hover_bg};
            border-radius: 3px;
        }}
        
        QTabBar::close-button:pressed {{
            background-color: #d32f2f;
        }}
    """
    
    tab_widget.setStyleSheet(stylesheet)
    
    if not tab_widget.tabsClosable():
        tab_widget.setTabsClosable(True)
    
    tab_bar = tab_widget.tabBar()
    if tab_bar:
        tab_bar.setMouseTracking(True)
        tab_bar.setElideMode(Qt.ElideRight)
        tab_bar.setExpanding(False)


# ============================================================================
# Results Table Widget
# ============================================================================


class SimpleResultsTableWidget(QTableWidget):
    """Engine-aware results table widget with semantic value and scoring support."""
    
    match_selected = pyqtSignal(dict)
    
    # Engine-specific column configurations (mirrors ResultsTabWidget)
    TIME_WINDOW_COLUMNS = [
        {"name": "Match ID", "width": 80},
        {"name": "Window Start", "width": 150},
        {"name": "Window End", "width": 150},
        {"name": "Score", "width": 80},
        {"name": "Interpretation", "width": 120},
        {"name": "Feather Count", "width": 100},
        {"name": "Time Spread (s)", "width": 100},
        {"name": "Semantic Value", "width": 150},
        {"name": "Application", "width": 150},
        {"name": "File Path", "width": 200}
    ]
    
    IDENTITY_COLUMNS = [
        {"name": "Match ID", "width": 80},
        {"name": "Identity Value", "width": 150},
        {"name": "Identity Type", "width": 100},
        {"name": "Semantic Value", "width": 150},
        {"name": "Score", "width": 80},
        {"name": "Interpretation", "width": 120},
        {"name": "Feather Count", "width": 100},
        {"name": "First Seen", "width": 150},
        {"name": "Last Seen", "width": 150},
        {"name": "Application", "width": 150}
    ]
    
    def __init__(self, parent=None, engine_type: str = "time_based"):
        super().__init__(parent)
        self.all_matches = []
        self.engine_type = engine_type
        self._init_ui()
    
    def _init_ui(self):
        """Initialize table with engine-specific columns."""
        self._configure_columns()
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.itemSelectionChanged.connect(self._on_selection_changed)
    
    def _configure_columns(self):
        """Configure columns based on engine type."""
        columns = self.IDENTITY_COLUMNS if self.engine_type == "identity_based" else self.TIME_WINDOW_COLUMNS
        self.setColumnCount(len(columns))
        self.setHorizontalHeaderLabels([col["name"] for col in columns])
        
        # Set column widths
        for i, col in enumerate(columns):
            self.setColumnWidth(i, col["width"])
    
    def set_engine_type(self, engine_type: str):
        """Change engine type and reconfigure columns."""
        if self.engine_type != engine_type:
            self.engine_type = engine_type
            self._configure_columns()
            # Re-populate if we have matches
            if self.all_matches:
                self.populate_results(self.all_matches)
    
    def _get_semantic_value(self, match: 'CorrelationMatch') -> str:
        """
        Extract semantic value from match data for either engine type.
        
        Checks:
        1. Match-level semantic_data field
        2. Feather records for _semantic_mappings key
        
        Returns:
            Semantic value string or "-" if not available
        """
        # Check match-level semantic data
        if match.semantic_data:
            # Skip unavailable marker
            if match.semantic_data.get('_unavailable'):
                pass
            else:
                for field_name, field_info in match.semantic_data.items():
                    if isinstance(field_info, dict) and 'semantic_value' in field_info:
                        return str(field_info['semantic_value'])
                    elif isinstance(field_info, str) and field_name != '_reason':
                        return field_info
        
        # Check feather records for semantic mappings
        if match.feather_records:
            for feather_id, record in match.feather_records.items():
                if isinstance(record, dict):
                    semantic_mappings = record.get('_semantic_mappings', {})
                    if isinstance(semantic_mappings, dict):
                        for field_name, mapping_info in semantic_mappings.items():
                            if isinstance(mapping_info, dict) and 'semantic_value' in mapping_info:
                                return str(mapping_info['semantic_value'])
                            elif isinstance(mapping_info, str):
                                return mapping_info
        
        return "-"  # Default when no semantic data available
    
    def _get_score_display(self, match: 'CorrelationMatch') -> tuple:
        """
        Get score value and interpretation for display.
        
        Returns:
            Tuple of (score_value: float, interpretation: str)
        """
        if match.weighted_score and isinstance(match.weighted_score, dict):
            score_value = match.weighted_score.get('score', match.match_score)
            interpretation = match.weighted_score.get('interpretation', '-')
        else:
            score_value = match.match_score
            interpretation = '-'
        return float(score_value) if score_value is not None else 0.0, str(interpretation)
    
    def _get_identity_type(self, match: 'CorrelationMatch') -> str:
        """Extract identity type from match data."""
        # Check feather metadata or records for identity type
        if match.feather_records:
            for feather_id, record in match.feather_records.items():
                if isinstance(record, dict):
                    if 'identity_type' in record:
                        return str(record['identity_type'])
                    if '_identity_type' in record:
                        return str(record['_identity_type'])
        return "application"  # Default identity type
    
    def _format_timestamp(self, timestamp) -> str:
        """Format timestamp for display."""
        if timestamp is None:
            return "-"
        if isinstance(timestamp, str):
            return timestamp[:19] if len(timestamp) > 19 else timestamp
        if hasattr(timestamp, 'isoformat'):
            return timestamp.isoformat()[:19]
        return str(timestamp)[:19]
    
    def populate_results(self, matches):
        """Populate table with matches using engine-specific columns."""
        self.all_matches = matches
        self.setRowCount(len(matches))
        
        for i, match in enumerate(matches):
            self._populate_row(i, match)
            # Store match data for selection handling
            self.item(i, 0).setData(Qt.UserRole, match)
    
    def _populate_row(self, row: int, match: 'CorrelationMatch'):
        """Populate a single row with match data based on engine type."""
        semantic_value = self._get_semantic_value(match)
        score_value, interpretation = self._get_score_display(match)
        
        if self.engine_type == "identity_based":
            self._populate_identity_row(row, match, semantic_value, score_value, interpretation)
        else:
            self._populate_time_window_row(row, match, semantic_value, score_value, interpretation)
    
    def _populate_time_window_row(self, row: int, match: 'CorrelationMatch', 
                                   semantic_value: str, score_value: float, interpretation: str):
        """Populate row for time-window engine."""
        # Column order: Match ID, Window Start, Window End, Score, Interpretation, 
        #               Feather Count, Time Spread, Semantic Value, Application, File Path
        self.setItem(row, 0, QTableWidgetItem(match.match_id[:8]))
        self.setItem(row, 1, QTableWidgetItem(self._format_timestamp(match.timestamp)))
        
        # Window End - calculate from timestamp + time_spread
        window_end = match.timestamp  # Simplified - same as start for now
        self.setItem(row, 2, QTableWidgetItem(self._format_timestamp(window_end)))
        
        self.setItem(row, 3, QTableWidgetItem(f"{score_value:.2f}"))
        self.setItem(row, 4, QTableWidgetItem(interpretation))
        self.setItem(row, 5, QTableWidgetItem(str(match.feather_count)))
        self.setItem(row, 6, QTableWidgetItem(f"{match.time_spread_seconds:.1f}"))
        self.setItem(row, 7, QTableWidgetItem(semantic_value))
        self.setItem(row, 8, QTableWidgetItem(match.matched_application or "-"))
        self.setItem(row, 9, QTableWidgetItem(match.matched_file_path or "-"))
    
    def _populate_identity_row(self, row: int, match: 'CorrelationMatch',
                                semantic_value: str, score_value: float, interpretation: str):
        """Populate row for identity-based engine."""
        # Column order: Match ID, Identity Value, Identity Type, Semantic Value,
        #               Score, Interpretation, Feather Count, First Seen, Last Seen, Application
        self.setItem(row, 0, QTableWidgetItem(match.match_id[:8]))
        
        # Identity Value - use matched_application or matched_file_path
        identity_value = match.matched_application or match.matched_file_path or "-"
        self.setItem(row, 1, QTableWidgetItem(identity_value))
        
        self.setItem(row, 2, QTableWidgetItem(self._get_identity_type(match)))
        self.setItem(row, 3, QTableWidgetItem(semantic_value))
        self.setItem(row, 4, QTableWidgetItem(f"{score_value:.2f}"))
        self.setItem(row, 5, QTableWidgetItem(interpretation))
        self.setItem(row, 6, QTableWidgetItem(str(match.feather_count)))
        
        # First Seen / Last Seen - use timestamp for both (simplified)
        self.setItem(row, 7, QTableWidgetItem(self._format_timestamp(match.timestamp)))
        self.setItem(row, 8, QTableWidgetItem(self._format_timestamp(match.timestamp)))
        
        self.setItem(row, 9, QTableWidgetItem(match.matched_application or "-"))
    
    def apply_filters(self, filters):
        """Apply filters (simplified)."""
        pass
    
    def _on_selection_changed(self):
        """Handle selection change."""
        selected_items = self.selectedItems()
        if selected_items:
            row = selected_items[0].row()
            match = self.item(row, 0).data(Qt.UserRole)
            if match:
                self.match_selected.emit(match.to_dict())


class SimpleMatchDetailViewer(QWidget):
    """Simple match detail viewer for testing."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        
        self.detail_label = QLabel("Select a match to view details")
        layout.addWidget(self.detail_label)
    
    def display_match(self, match_data):
        """Display match details."""
        if match_data:
            match_id = match_data.get('match_id', 'Unknown')
            score = match_data.get('match_score', 0)
            self.detail_label.setText(f"Match: {match_id}\nScore: {score:.2f}")
        else:
            self.detail_label.setText("Select a match to view details")


class TabState:
    """
    Represents the state of a result tab including semantic and scoring information.
    """
    
    def __init__(self, tab_id: str, wing_name: str, result: CorrelationResult):
        """
        Initialize tab state.
        
        Args:
            tab_id: Unique identifier for the tab
            wing_name: Name of the wing
            result: Correlation result data
        """
        self.tab_id = tab_id
        self.wing_name = wing_name
        self.result = result
        self.semantic_mappings: Dict[str, Any] = {}
        self.scoring_configuration: Dict[str, Any] = {}
        self.filter_state: Dict[str, Any] = {}
        self.selected_match_id: Optional[str] = None
        self.scroll_position: int = 0
        self.sort_column: int = 0
        self.sort_order: int = Qt.AscendingOrder
        self.created_timestamp = datetime.now()
        self.last_accessed = datetime.now()
    
    def update_semantic_mappings(self, semantic_mappings: Dict[str, Any]):
        """Update semantic mapping information for this tab."""
        self.semantic_mappings = semantic_mappings
        self.last_accessed = datetime.now()
    
    def update_scoring_configuration(self, scoring_config: Dict[str, Any]):
        """Update scoring configuration for this tab."""
        self.scoring_configuration = scoring_config
        self.last_accessed = datetime.now()
    
    def update_filter_state(self, filter_state: Dict[str, Any]):
        """Update filter state for this tab."""
        self.filter_state = filter_state
        self.last_accessed = datetime.now()
    
    def update_selection(self, match_id: Optional[str]):
        """Update selected match for this tab."""
        self.selected_match_id = match_id
        self.last_accessed = datetime.now()
    
    def update_view_state(self, scroll_position: int, sort_column: int, sort_order: int):
        """Update view state (scroll position, sorting) for this tab."""
        self.scroll_position = scroll_position
        self.sort_column = sort_column
        self.sort_order = sort_order
        self.last_accessed = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert tab state to dictionary for serialization."""
        return {
            'tab_id': self.tab_id,
            'wing_name': self.wing_name,
            'semantic_mappings': self.semantic_mappings,
            'scoring_configuration': self.scoring_configuration,
            'filter_state': self.filter_state,
            'selected_match_id': self.selected_match_id,
            'scroll_position': self.scroll_position,
            'sort_column': self.sort_column,
            'sort_order': self.sort_order,
            'created_timestamp': self.created_timestamp.isoformat(),
            'last_accessed': self.last_accessed.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], result: CorrelationResult) -> 'TabState':
        """Create tab state from dictionary."""
        tab_state = cls(data['tab_id'], data['wing_name'], result)
        tab_state.semantic_mappings = data.get('semantic_mappings', {})
        tab_state.scoring_configuration = data.get('scoring_configuration', {})
        tab_state.filter_state = data.get('filter_state', {})
        tab_state.selected_match_id = data.get('selected_match_id')
        tab_state.scroll_position = data.get('scroll_position', 0)
        tab_state.sort_column = data.get('sort_column', 0)
        tab_state.sort_order = data.get('sort_order', Qt.AscendingOrder)
        
        # Parse timestamps
        if 'created_timestamp' in data:
            tab_state.created_timestamp = datetime.fromisoformat(data['created_timestamp'])
        if 'last_accessed' in data:
            tab_state.last_accessed = datetime.fromisoformat(data['last_accessed'])
        
        return tab_state


class ResultTab(QWidget):
    """
    Result tab with semantic and scoring state management.
    """
    
    # Signals
    tab_state_changed = pyqtSignal(str, dict)  # tab_id, state_data
    match_selected = pyqtSignal(str, dict)  # tab_id, match_data
    export_requested = pyqtSignal(str, dict)  # tab_id, export_options
    
    def __init__(self, tab_state: TabState, engine_type: str = "time_based", parent=None):
        """
        Initialize result tab.
        
        Args:
            tab_state: Tab state containing result data and configuration
            engine_type: Engine type for column configuration ("time_based" or "identity_based")
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.tab_state = tab_state
        self.engine_type = engine_type
        self.semantic_info_widget = None
        self.scoring_widget = None
        self.results_table = None
        self.match_detail_viewer = None
        self.filter_panel = None
        
        self._init_ui()
        self._restore_state()
    
    def _init_ui(self):
        """Initialize the tab UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        
        # Top section: Summary and filters
        top_section = self._create_top_section()
        layout.addWidget(top_section)
        
        # Main content: Splitter with results table and details
        main_splitter = QSplitter(Qt.Vertical)
        
        # Results table with engine-specific columns
        self.results_table = SimpleResultsTableWidget(engine_type=self.engine_type)
        self.results_table.populate_results(self.tab_state.result.matches)
        self.results_table.match_selected.connect(self._on_match_selected)
        main_splitter.addWidget(self.results_table)
        
        # Details panel with semantic and scoring information
        details_panel = self._create_details_panel()
        main_splitter.addWidget(details_panel)
        
        # Set splitter proportions (70% table, 30% details)
        main_splitter.setSizes([700, 300])
        
        layout.addWidget(main_splitter)
        
        # Connect signals for state tracking
        self._connect_state_signals()

    def _create_top_section(self) -> QWidget:
        """Create the top section with summary and filters."""
        frame = QFrame()
        frame.setMaximumHeight(80)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(2)
        
        # Summary row
        summary_layout = QHBoxLayout()
        
        # Basic statistics
        total_matches = len(self.tab_state.result.matches)
        avg_score = sum(m.match_score for m in self.tab_state.result.matches) / total_matches if total_matches > 0 else 0
        
        # Check for weighted scoring
        uses_weighted = any(m.weighted_score is not None for m in self.tab_state.result.matches)
        if uses_weighted:
            weighted_scores = [m.weighted_score.get('score', 0) for m in self.tab_state.result.matches if m.weighted_score and isinstance(m.weighted_score, dict)]
            avg_weighted = sum(weighted_scores) / len(weighted_scores) if weighted_scores else 0
            score_text = f"Avg Score: {avg_weighted:.2f} (Weighted)"
        else:
            score_text = f"Avg Score: {avg_score:.2f} (Simple)"
        
        # Summary labels
        wing_label = QLabel(f"Wing: {self.tab_state.wing_name}")
        wing_label.setStyleSheet("font-weight: bold; color: #2196F3;")
        summary_layout.addWidget(wing_label)
        
        matches_label = QLabel(f"Matches: {total_matches:,}")
        matches_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
        summary_layout.addWidget(matches_label)
        
        score_label = QLabel(score_text)
        score_label.setStyleSheet("color: #FF9800;")
        summary_layout.addWidget(score_label)
        
        # Semantic mapping status
        semantic_count = len(self.tab_state.semantic_mappings)
        if semantic_count > 0:
            semantic_label = QLabel(f"Semantic: {semantic_count} mappings")
            semantic_label.setStyleSheet("color: #9C27B0;")
            summary_layout.addWidget(semantic_label)
        
        # Scoring configuration status
        if self.tab_state.scoring_configuration:
            scoring_label = QLabel("Scoring: Configured")
            scoring_label.setStyleSheet("color: #607D8B;")
            summary_layout.addWidget(scoring_label)
        
        summary_layout.addStretch()
        
        # Tab actions
        actions_layout = QHBoxLayout()
        
        export_btn = QPushButton("Export")
        export_btn.setMaximumWidth(60)
        export_btn.clicked.connect(self._export_tab_data)
        actions_layout.addWidget(export_btn)
        
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setMaximumWidth(60)
        refresh_btn.clicked.connect(self._refresh_tab)
        actions_layout.addWidget(refresh_btn)
        
        summary_layout.addLayout(actions_layout)
        
        layout.addLayout(summary_layout)
        
        # Filter row
        filter_layout = QHBoxLayout()
        
        # Create compact filter controls
        self.app_filter = QLineEdit()
        self.app_filter.setPlaceholderText("Application...")
        self.app_filter.setMaximumWidth(120)
        filter_layout.addWidget(self.app_filter)
        
        self.path_filter = QLineEdit()
        self.path_filter.setPlaceholderText("File path...")
        self.path_filter.setMaximumWidth(120)
        filter_layout.addWidget(self.path_filter)
        
        self.score_slider = QSlider(Qt.Horizontal)
        self.score_slider.setMinimum(0)
        self.score_slider.setMaximum(100)
        self.score_slider.setValue(0)
        self.score_slider.setMaximumWidth(80)
        filter_layout.addWidget(self.score_slider)
        
        self.score_min_label = QLabel("Min: 0.00")
        self.score_min_label.setStyleSheet("font-size: 8pt;")
        filter_layout.addWidget(self.score_min_label)
        
        reset_btn = QPushButton("Reset")
        reset_btn.setMaximumWidth(45)
        reset_btn.clicked.connect(self._reset_filters)
        filter_layout.addWidget(reset_btn)
        
        filter_layout.addStretch()
        layout.addLayout(filter_layout)
        
        return frame
    
    def _create_details_panel(self) -> QWidget:
        """Create the details panel with semantic and scoring information."""
        splitter = QSplitter(Qt.Horizontal)
        
        # Left side: Match details
        match_details_frame = QFrame()
        match_details_layout = QVBoxLayout(match_details_frame)
        match_details_layout.setContentsMargins(2, 2, 2, 2)
        
        match_details_label = QLabel("Match Details")
        match_details_label.setStyleSheet("font-weight: bold; color: #2196F3;")
        match_details_layout.addWidget(match_details_label)
        
        self.match_detail_viewer = SimpleMatchDetailViewer()
        match_details_layout.addWidget(self.match_detail_viewer)
        
        splitter.addWidget(match_details_frame)
        
        # Middle: Scoring breakdown
        scoring_frame = QFrame()
        scoring_layout = QVBoxLayout(scoring_frame)
        scoring_layout.setContentsMargins(2, 2, 2, 2)
        
        scoring_label = QLabel("Scoring Breakdown")
        scoring_label.setStyleSheet("font-weight: bold; color: #FF9800;")
        scoring_layout.addWidget(scoring_label)
        
        self.scoring_widget = ScoringBreakdownWidget()
        scoring_layout.addWidget(self.scoring_widget)
        
        splitter.addWidget(scoring_frame)
        
        # Right side: Semantic information
        semantic_frame = QFrame()
        semantic_layout = QVBoxLayout(semantic_frame)
        semantic_layout.setContentsMargins(2, 2, 2, 2)
        
        semantic_label = QLabel("Semantic Information")
        semantic_label.setStyleSheet("font-weight: bold; color: #9C27B0;")
        semantic_layout.addWidget(semantic_label)
        
        self.semantic_info_widget = SemanticInfoDisplayWidget()
        semantic_layout.addWidget(self.semantic_info_widget)
        
        splitter.addWidget(semantic_frame)
        
        # Set equal proportions
        splitter.setSizes([333, 333, 334])
        
        return splitter
    
    def _connect_state_signals(self):
        """Connect signals for state tracking."""
        # Filter changes
        self.app_filter.textChanged.connect(self._on_filter_changed)
        self.path_filter.textChanged.connect(self._on_filter_changed)
        self.score_slider.valueChanged.connect(self._on_filter_changed)
        
        # Table state changes
        if self.results_table:
            # Connect to table sorting and scrolling signals
            header = self.results_table.horizontalHeader()
            header.sectionClicked.connect(self._on_sort_changed)
    
    def _restore_state(self):
        """Restore the tab state from stored information."""
        # Restore filter state
        filter_state = self.tab_state.filter_state
        if filter_state:
            self.app_filter.setText(filter_state.get('application', ''))
            self.path_filter.setText(filter_state.get('file_path', ''))
            score_min = int(filter_state.get('score_min', 0) * 100)
            self.score_slider.setValue(score_min)
            self.score_min_label.setText(f"Min: {score_min / 100.0:.2f}")
            
            # Apply filters to table
            self._apply_current_filters()
        
        # Restore selection
        if self.tab_state.selected_match_id:
            self._restore_selection(self.tab_state.selected_match_id)
        
        # Restore sorting
        if self.results_table:
            self.results_table.sortItems(self.tab_state.sort_column, self.tab_state.sort_order)
    
    def _apply_current_filters(self):
        """Apply current filter settings to the results table."""
        filters = {
            'application': self.app_filter.text().strip(),
            'file_path': self.path_filter.text().strip(),
            'score_min': self.score_slider.value() / 100.0
        }
        
        if self.results_table:
            self.results_table.apply_filters(filters)
        
        # Update tab state
        self.tab_state.update_filter_state(filters)
        self._emit_state_changed()
    
    def _restore_selection(self, match_id: str):
        """Restore selection to a specific match."""
        if not self.results_table:
            return
        
        # Find the row with the matching ID
        for row in range(self.results_table.rowCount()):
            item = self.results_table.item(row, 0)
            if item:
                stored_match = item.data(Qt.UserRole + 1)
                if stored_match and stored_match.match_id == match_id:
                    self.results_table.selectRow(row)
                    break
    
    def _on_match_selected(self, match_data: dict):
        """Handle match selection and coordinate viewer updates."""
        match_id = match_data.get('match_id')
        
        # Update match details
        if self.match_detail_viewer:
            try:
                self.match_detail_viewer.display_match(match_data)
            except Exception as e:
                print(f"[ResultTab] Error updating match detail viewer: {e}")
        
        # Update scoring breakdown with semantic information
        if self.scoring_widget:
            try:
                weighted_score = match_data.get('weighted_score')
                semantic_info = self.tab_state.semantic_mappings
                self.scoring_widget.display_scoring(weighted_score, semantic_info)
            except Exception as e:
                print(f"[ResultTab] Error updating scoring widget: {e}")
        
        # Update semantic information display
        if self.semantic_info_widget:
            try:
                if self.tab_state.semantic_mappings:
                    feather_records = match_data.get('feather_records', {})
                    # Find semantic data for this match
                    match_semantic_data = {}
                    for feather_id, record in feather_records.items():
                        if feather_id in self.tab_state.semantic_mappings:
                            match_semantic_data[feather_id] = self.tab_state.semantic_mappings[feather_id]
                    
                    if match_semantic_data:
                        # Display semantic info for the first feather record (simplified)
                        first_record = next(iter(feather_records.values()), {})
                        first_semantic = next(iter(match_semantic_data.values()), {})
                        self.semantic_info_widget.display_semantic_info(first_record, {'_semantic_mappings': first_semantic})
            except Exception as e:
                print(f"[ResultTab] Error updating semantic info widget: {e}")
        
        # Update tab state
        self.tab_state.update_selection(match_id)
        self._emit_state_changed()
        
        # Emit signal for external handling
        self.match_selected.emit(self.tab_state.tab_id, match_data)
    
    def _on_filter_changed(self):
        """Handle filter changes."""
        self.score_min_label.setText(f"Min: {self.score_slider.value() / 100.0:.2f}")
        self._apply_current_filters()
    
    def _on_sort_changed(self, logical_index: int):
        """Handle sorting changes."""
        if self.results_table:
            sort_order = self.results_table.horizontalHeader().sortIndicatorOrder()
            self.tab_state.update_view_state(0, logical_index, sort_order)
            self._emit_state_changed()
    
    def _reset_filters(self):
        """Reset all filters to default values."""
        self.app_filter.clear()
        self.path_filter.clear()
        self.score_slider.setValue(0)
        self.score_min_label.setText("Min: 0.00")
        self._apply_current_filters()
    
    def _refresh_tab(self):
        """Refresh the tab data."""
        # Reload results table
        if self.results_table:
            self.results_table.populate_results(self.tab_state.result.matches)
            self._apply_current_filters()
        
        # Clear details if no selection
        if not self.tab_state.selected_match_id:
            if self.match_detail_viewer:
                self.match_detail_viewer.display_match({})
            if self.scoring_widget:
                self.scoring_widget.clear()
            if self.semantic_info_widget:
                self.semantic_info_widget.clear()
    
    def set_engine_type(self, engine_type: str):
        """Update engine type and reconfigure the results table."""
        if self.engine_type != engine_type:
            self.engine_type = engine_type
            if self.results_table:
                self.results_table.set_engine_type(engine_type)
    
    def _export_tab_data(self):
        """Export tab data with semantic and scoring metadata."""
        export_options = {
            'include_semantic_mappings': True,
            'include_scoring_configuration': True,
            'include_filter_state': True,
            'format': 'json'  # Default format
        }
        
        self.export_requested.emit(self.tab_state.tab_id, export_options)
    
    def _emit_state_changed(self):
        """Emit tab state changed signal."""
        self.tab_state_changed.emit(self.tab_state.tab_id, self.tab_state.to_dict())
    
    def update_semantic_mappings(self, semantic_mappings: Dict[str, Any]):
        """Update semantic mappings for this tab."""
        self.tab_state.update_semantic_mappings(semantic_mappings)
        
        # Refresh semantic display if a match is selected
        if self.tab_state.selected_match_id and self.semantic_info_widget:
            # Re-trigger match selection to update semantic display
            current_selection = self.results_table.selectedItems()
            if current_selection:
                row = current_selection[0].row()
                match = self.results_table.item(row, 0).data(Qt.UserRole + 1)
                if match:
                    self._on_match_selected(match.to_dict())
        
        self._emit_state_changed()
    
    def update_scoring_configuration(self, scoring_config: Dict[str, Any]):
        """Update scoring configuration for this tab."""
        self.tab_state.update_scoring_configuration(scoring_config)
        
        # Refresh scoring display if a match is selected
        if self.tab_state.selected_match_id and self.scoring_widget:
            current_selection = self.results_table.selectedItems()
            if current_selection:
                row = current_selection[0].row()
                match = self.results_table.item(row, 0).data(Qt.UserRole + 1)
                if match:
                    weighted_score = match.to_dict().get('weighted_score')
                    self.scoring_widget.display_scoring(weighted_score, self.tab_state.semantic_mappings)
        
        self._emit_state_changed()
    
    def get_tab_state(self) -> TabState:
        """Get current tab state."""
        return self.tab_state
    
    def contextMenuEvent(self, event: QContextMenuEvent):
        """Handle context menu for tab-specific actions."""
        menu = QMenu(self)
        
        # Export actions
        export_action = QAction("Export Tab Data", self)
        export_action.triggered.connect(self._export_tab_data)
        menu.addAction(export_action)
        
        # Refresh action
        refresh_action = QAction("Refresh Tab", self)
        refresh_action.triggered.connect(self._refresh_tab)
        menu.addAction(refresh_action)
        
        menu.addSeparator()
        
        # State management actions
        save_state_action = QAction("Save Tab State", self)
        save_state_action.triggered.connect(lambda: self._emit_state_changed())
        menu.addAction(save_state_action)
        
        menu.exec_(event.globalPos())


class ResultsTabWidget(QWidget):
    """
    Multi-tab result management widget with semantic and scoring support.
    
    Provides engine-specific column configurations for time-window and identity-based engines.
    """
    
    # Engine-specific column configurations
    TIME_WINDOW_COLUMNS = [
        {"name": "Match ID", "width": 80, "sortable": True},
        {"name": "Window Start", "width": 150, "sortable": True},
        {"name": "Window End", "width": 150, "sortable": True},
        {"name": "Score", "width": 80, "sortable": True},
        {"name": "Interpretation", "width": 120, "sortable": True},
        {"name": "Feather Count", "width": 100, "sortable": True},
        {"name": "Time Spread (s)", "width": 100, "sortable": True},
        {"name": "Semantic Value", "width": 150, "sortable": True},
        {"name": "Application", "width": 150, "sortable": True},
        {"name": "File Path", "width": 200, "sortable": True}
    ]
    
    IDENTITY_COLUMNS = [
        {"name": "Match ID", "width": 80, "sortable": True},
        {"name": "Identity Value", "width": 150, "sortable": True},
        {"name": "Identity Type", "width": 100, "sortable": True},
        {"name": "Semantic Value", "width": 150, "sortable": True},
        {"name": "Score", "width": 80, "sortable": True},
        {"name": "Interpretation", "width": 120, "sortable": True},
        {"name": "Feather Count", "width": 100, "sortable": True},
        {"name": "First Seen", "width": 150, "sortable": True},
        {"name": "Last Seen", "width": 150, "sortable": True},
        {"name": "Application", "width": 150, "sortable": True}
    ]
    
    # Signals
    tab_state_changed = pyqtSignal(str, dict)  # tab_id, state_data
    match_selected = pyqtSignal(str, dict)  # tab_id, match_data
    export_requested = pyqtSignal(str, dict)  # tab_id, export_options
    
    def __init__(self, parent=None):
        """Initialize results tab widget."""
        super().__init__(parent)
        
        self.tab_states: Dict[str, TabState] = {}
        self.engine_type = "time_based"
        self.global_semantic_mappings: Dict[str, Any] = {}
        self.global_scoring_configuration: Dict[str, Any] = {}
        self._current_columns = self.TIME_WINDOW_COLUMNS
        
        self._init_ui()
    
    def _init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.tabCloseRequested.connect(self._close_tab)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        
        # Style the tab widget
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #334155;
                background: #1E293B;
                border-radius: 8px;
            }
            QTabBar::tab {
                background: #1E293B;
                color: #94A3B8;
                border: 1px solid #334155;
                padding: 6px 12px;
                font-weight: 600;
                font-size: 8pt;
                min-height: 16px;
                min-width: 120px;
                max-width: 200px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected {
                background-color: #0B1220;
                color: #00FFFF;
                border-bottom: 2px solid #00FFFF;
            }
            QTabBar::tab:hover:!selected {
                background-color: #334155;
                color: #FFFFFF;
            }
            QTabBar::close-button {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background: transparent;
                subcontrol-position: right;
                margin: 2px;
            }
            QTabBar::close-button:hover {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 8px;
            }
            QTabBar::close-button:pressed {
                background: rgba(255, 255, 255, 0.3);
            }
        """)
        
        layout.addWidget(self.tab_widget)
        
        # Apply proper close button styling
        apply_tab_close_button_styling(self.tab_widget, "dark")
        
        # Create summary tab
        self.summary_tab = self._create_summary_tab()
        self.tab_widget.addTab(self.summary_tab, "📊 Summary")
    
    def _create_summary_tab(self) -> QWidget:
        """Create summary statistics tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Overall statistics
        stats_group = QGroupBox("Overall Statistics")
        stats_layout = QFormLayout()
        
        self.total_matches_label = QLabel("0")
        stats_layout.addRow("Total Matches:", self.total_matches_label)
        
        self.total_tabs_label = QLabel("0")
        stats_layout.addRow("Active Tabs:", self.total_tabs_label)
        
        self.avg_score_label = QLabel("0.00")
        stats_layout.addRow("Average Score:", self.avg_score_label)
        
        self.engine_type_label = QLabel("Time-Based")
        stats_layout.addRow("Engine Type:", self.engine_type_label)
        
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        # Integration status
        integration_group = QGroupBox("Integration Status")
        integration_layout = QFormLayout()
        
        self.semantic_status_label = QLabel("Not configured")
        integration_layout.addRow("Semantic Mappings:", self.semantic_status_label)
        
        self.scoring_status_label = QLabel("Not configured")
        integration_layout.addRow("Weighted Scoring:", self.scoring_status_label)
        
        integration_group.setLayout(integration_layout)
        layout.addWidget(integration_group)
        
        # Tab breakdown table
        breakdown_group = QGroupBox("Tab Breakdown")
        breakdown_layout = QVBoxLayout()
        
        self.breakdown_table = QTableWidget()
        self.breakdown_table.setColumnCount(6)
        self.breakdown_table.setHorizontalHeaderLabels([
            "Tab", "Wing", "Matches", "Avg Score", "Semantic", "Last Accessed"
        ])
        self.breakdown_table.horizontalHeader().setStretchLastSection(True)
        breakdown_layout.addWidget(self.breakdown_table)
        
        breakdown_group.setLayout(breakdown_layout)
        layout.addWidget(breakdown_group)
        
        layout.addStretch()
        
        return widget
    
    def set_engine_type(self, engine_type: str):
        """Set the engine type for results display and reconfigure all tabs."""
        old_engine_type = self.engine_type
        self.engine_type = engine_type
        self.configure_for_engine(engine_type)
        
        if engine_type == "identity_based":
            self.engine_type_label.setText("Identity-Based")
        else:
            self.engine_type_label.setText("Time-Based")
        
        # Reconfigure all existing tabs if engine type changed
        if old_engine_type != engine_type:
            self._reconfigure_all_tabs()
    
    def _reconfigure_all_tabs(self):
        """Reconfigure all viewer components when engine type changes."""
        for tab_id, tab_state in self.tab_states.items():
            tab_widget = self._get_tab_widget(tab_id)
            if tab_widget and isinstance(tab_widget, ResultTab):
                # Update engine type and refresh the tab
                try:
                    tab_widget.set_engine_type(self.engine_type)
                    tab_widget._refresh_tab()
                except Exception as e:
                    print(f"[ResultsTabWidget] Error reconfiguring tab {tab_id}: {e}")
        
        # Update summary with new terminology
        self._update_summary()
    
    def configure_for_engine(self, engine_type: str):
        """
        Configure the widget for a specific engine type.
        
        Switches column layouts and display configurations based on engine type.
        
        Args:
            engine_type: Either "time_based", "time_window_scanning", or "identity_based"
        """
        if engine_type == "identity_based":
            self._current_columns = self.IDENTITY_COLUMNS
            self._configure_identity_display()
        else:
            # Default to time_window for any unrecognized type
            self._current_columns = self.TIME_WINDOW_COLUMNS
            self._configure_time_window_display()
            if engine_type not in ("time_based", "time_window_scanning"):
                print(f"[ResultsTabWidget] Warning: Unrecognized engine type '{engine_type}', defaulting to time_window_scanning")
    
    def _configure_time_window_display(self):
        """Configure display for time-window scanning engine."""
        # Update breakdown table headers for time-window context
        self.breakdown_table.setHorizontalHeaderLabels([
            "Tab", "Wing", "Matches", "Avg Score", "Semantic", "Last Accessed"
        ])
    
    def _configure_identity_display(self):
        """Configure display for identity-based engine."""
        # Update breakdown table headers for identity context
        self.breakdown_table.setHorizontalHeaderLabels([
            "Tab", "Wing", "Identities", "Avg Score", "Semantic", "Last Accessed"
        ])
    
    def get_current_columns(self) -> List[Dict[str, Any]]:
        """
        Get the current column configuration based on engine type.
        
        Returns:
            List of column configuration dictionaries
        """
        return self._current_columns
    
    def update_global_semantic_mappings(self, semantic_mappings: Dict[str, Any]):
        """Update global semantic mappings for all tabs."""
        self.global_semantic_mappings = semantic_mappings
        
        # Update all existing tabs
        for tab_id, tab_state in self.tab_states.items():
            tab_widget = self._get_tab_widget(tab_id)
            if tab_widget and isinstance(tab_widget, ResultTab):
                tab_widget.update_semantic_mappings(semantic_mappings)
        
        self._update_summary()
    
    def update_global_scoring_configuration(self, scoring_config: Dict[str, Any]):
        """Update global scoring configuration for all tabs."""
        self.global_scoring_configuration = scoring_config
        
        # Update all existing tabs
        for tab_id, tab_state in self.tab_states.items():
            tab_widget = self._get_tab_widget(tab_id)
            if tab_widget and isinstance(tab_widget, ResultTab):
                tab_widget.update_scoring_configuration(scoring_config)
        
        self._update_summary()
    
    def add_result_tab(self, wing_name: str, result: CorrelationResult, 
                      semantic_mappings: Optional[Dict[str, Any]] = None,
                      scoring_config: Optional[Dict[str, Any]] = None) -> str:
        """
        Add a new result tab with semantic and scoring support.
        
        Args:
            wing_name: Name of the wing
            result: Correlation result data
            semantic_mappings: Optional semantic mappings for this tab
            scoring_config: Optional scoring configuration for this tab
            
        Returns:
            Tab ID of the created tab
        """
        # Generate unique tab ID
        tab_id = f"{wing_name}_{datetime.now().strftime('%H%M%S')}"
        
        # Create tab state
        tab_state = TabState(tab_id, wing_name, result)
        
        # Set semantic mappings (tab-specific or global)
        if semantic_mappings:
            tab_state.update_semantic_mappings(semantic_mappings)
        elif self.global_semantic_mappings:
            tab_state.update_semantic_mappings(self.global_semantic_mappings)
        
        # Set scoring configuration (tab-specific or global)
        if scoring_config:
            tab_state.update_scoring_configuration(scoring_config)
        elif self.global_scoring_configuration:
            tab_state.update_scoring_configuration(self.global_scoring_configuration)
        
        # Create tab widget with engine type for proper column configuration
        tab_widget = ResultTab(tab_state, engine_type=self.engine_type)
        tab_widget.tab_state_changed.connect(self._on_tab_state_changed)
        tab_widget.match_selected.connect(self.match_selected)
        tab_widget.export_requested.connect(self.export_requested)
        
        # Add to tab widget
        tab_label = self._generate_tab_label(wing_name, result)
        tab_index = self.tab_widget.addTab(tab_widget, tab_label)
        
        # Store tab state
        self.tab_states[tab_id] = tab_state
        
        # Switch to new tab
        self.tab_widget.setCurrentIndex(tab_index)
        
        # Update summary
        self._update_summary()
        
        return tab_id
    
    def _generate_tab_label(self, wing_name: str, result: CorrelationResult) -> str:
        """Generate a descriptive tab label."""
        # Choose icon based on engine type
        if self.engine_type == "identity_based":
            icon = "🔷"
        else:
            icon = "⏱️"
        
        # Include match count
        match_count = len(result.matches)
        
        # Truncate wing name if too long
        display_name = wing_name
        if len(display_name) > 15:
            display_name = display_name[:12] + "..."
        
        return f"{icon} {display_name} ({match_count})"
    
    def _get_tab_widget(self, tab_id: str) -> Optional[QWidget]:
        """Get tab widget by tab ID."""
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if isinstance(widget, ResultTab) and widget.tab_state.tab_id == tab_id:
                return widget
        return None
    
    def _close_tab(self, index: int):
        """Close a tab and clean up its state."""
        if index == 0:  # Don't close summary tab
            return
        
        widget = self.tab_widget.widget(index)
        if isinstance(widget, ResultTab):
            tab_id = widget.tab_state.tab_id
            
            # Remove from state tracking
            if tab_id in self.tab_states:
                del self.tab_states[tab_id]
        
        # Remove tab
        self.tab_widget.removeTab(index)
        
        # Update summary
        self._update_summary()
    
    def _on_tab_changed(self, index: int):
        """Handle tab change."""
        widget = self.tab_widget.widget(index)
        if isinstance(widget, ResultTab):
            # Update last accessed time
            widget.tab_state.last_accessed = datetime.now()
            self._update_summary()
    
    def _on_tab_state_changed(self, tab_id: str, state_data: dict):
        """Handle tab state changes."""
        self.tab_state_changed.emit(tab_id, state_data)
        self._update_summary()
    
    def _update_summary(self):
        """Update the summary tab with current statistics."""
        # Calculate overall statistics
        total_matches = sum(len(state.result.matches) for state in self.tab_states.values())
        total_tabs = len(self.tab_states)
        
        all_scores = []
        for state in self.tab_states.values():
            all_scores.extend([m.match_score for m in state.result.matches])
        
        avg_score = sum(all_scores) / len(all_scores) if all_scores else 0.0
        
        # Update labels
        self.total_matches_label.setText(f"{total_matches:,}")
        self.total_tabs_label.setText(str(total_tabs))
        self.avg_score_label.setText(f"{avg_score:.2f}")
        
        # Update integration status
        semantic_count = len(self.global_semantic_mappings)
        if semantic_count > 0:
            self.semantic_status_label.setText(f"Active ({semantic_count} mappings)")
            self.semantic_status_label.setStyleSheet("color: #4CAF50;")
        else:
            self.semantic_status_label.setText("Not configured")
            self.semantic_status_label.setStyleSheet("color: #9E9E9E;")
        
        if self.global_scoring_configuration:
            self.scoring_status_label.setText("Active")
            self.scoring_status_label.setStyleSheet("color: #4CAF50;")
        else:
            self.scoring_status_label.setText("Not configured")
            self.scoring_status_label.setStyleSheet("color: #9E9E9E;")
        
        # Update breakdown table
        self._update_breakdown_table()
    
    def _update_breakdown_table(self):
        """Update the tab breakdown table."""
        self.breakdown_table.setRowCount(0)
        
        for tab_id, tab_state in self.tab_states.items():
            row = self.breakdown_table.rowCount()
            self.breakdown_table.insertRow(row)
            
            # Tab ID (shortened)
            short_id = tab_id[:8] + "..." if len(tab_id) > 8 else tab_id
            self.breakdown_table.setItem(row, 0, QTableWidgetItem(short_id))
            
            # Wing name
            self.breakdown_table.setItem(row, 1, QTableWidgetItem(tab_state.wing_name))
            
            # Match count
            match_count = len(tab_state.result.matches)
            self.breakdown_table.setItem(row, 2, QTableWidgetItem(str(match_count)))
            
            # Average score
            if tab_state.result.matches:
                avg_score = sum(m.match_score for m in tab_state.result.matches) / len(tab_state.result.matches)
                self.breakdown_table.setItem(row, 3, QTableWidgetItem(f"{avg_score:.2f}"))
            else:
                self.breakdown_table.setItem(row, 3, QTableWidgetItem("0.00"))
            
            # Semantic status
            semantic_count = len(tab_state.semantic_mappings)
            semantic_text = f"{semantic_count} mappings" if semantic_count > 0 else "None"
            self.breakdown_table.setItem(row, 4, QTableWidgetItem(semantic_text))
            
            # Last accessed
            last_accessed = tab_state.last_accessed.strftime("%H:%M:%S")
            self.breakdown_table.setItem(row, 5, QTableWidgetItem(last_accessed))
    
    def get_all_tab_states(self) -> Dict[str, TabState]:
        """Get all current tab states."""
        return self.tab_states.copy()
    
    def restore_tab_states(self, tab_states_data: Dict[str, dict], results_data: Dict[str, CorrelationResult]):
        """
        Restore tab states from saved data.
        
        Args:
            tab_states_data: Dictionary of tab state data
            results_data: Dictionary of correlation results by wing name
        """
        for tab_id, state_data in tab_states_data.items():
            wing_name = state_data.get('wing_name')
            if wing_name in results_data:
                result = results_data[wing_name]
                tab_state = TabState.from_dict(state_data, result)
                
                # Create tab widget
                tab_widget = ResultTab(tab_state)
                tab_widget.tab_state_changed.connect(self._on_tab_state_changed)
                tab_widget.match_selected.connect(self.match_selected)
                tab_widget.export_requested.connect(self.export_requested)
                
                # Add to tab widget
                tab_label = self._generate_tab_label(wing_name, result)
                self.tab_widget.addTab(tab_widget, tab_label)
                
                # Store tab state
                self.tab_states[tab_id] = tab_state
        
        # Update summary
        self._update_summary()
    
    def clear_all_tabs(self):
        """Clear all result tabs except summary."""
        while self.tab_widget.count() > 1:
            self.tab_widget.removeTab(1)
        
        self.tab_states.clear()
        self._update_summary()
    
    def list_available_results(self, base_output_dir: str) -> List[Dict[str, Any]]:
        """
        List available result sets with timestamps and summaries.
        
        Args:
            base_output_dir: Base directory containing result subdirectories
            
        Returns:
            List of dictionaries with result set information
        """
        result_sets = []
        base_path = Path(base_output_dir)
        
        if not base_path.exists():
            return result_sets
        
        # Look for timestamped subdirectories or direct result files
        for item in sorted(base_path.iterdir(), reverse=True):  # Most recent first
            if item.is_dir():
                # Check for pipeline_summary.json
                summary_file = item / "pipeline_summary.json"
                if summary_file.exists():
                    try:
                        with open(summary_file, 'r') as f:
                            summary_data = json.load(f)
                        
                        result_sets.append({
                            'path': str(item),
                            'name': item.name,
                            'timestamp': summary_data.get('execution_time', item.name),
                            'engine_type': summary_data.get('engine_type', 'unknown'),
                            'total_matches': summary_data.get('total_matches', 0),
                            'total_wings': summary_data.get('total_wings', 0),
                            'has_summary': True
                        })
                    except Exception:
                        # Directory exists but summary is invalid
                        result_sets.append({
                            'path': str(item),
                            'name': item.name,
                            'timestamp': item.name,
                            'engine_type': 'unknown',
                            'total_matches': 0,
                            'total_wings': 0,
                            'has_summary': False
                        })
                else:
                    # Check for result files directly
                    result_files = list(item.glob("result_*.json"))
                    if result_files:
                        result_sets.append({
                            'path': str(item),
                            'name': item.name,
                            'timestamp': item.name,
                            'engine_type': 'unknown',
                            'total_matches': 0,
                            'total_wings': len(result_files),
                            'has_summary': False
                        })
        
        return result_sets
    
    def load_last_results(self, base_output_dir: str) -> bool:
        """
        Load the most recent result set from the base output directory.
        
        Args:
            base_output_dir: Base directory containing result subdirectories
            
        Returns:
            True if results were loaded, False otherwise
        """
        result_sets = self.list_available_results(base_output_dir)
        
        if not result_sets:
            print(f"[ResultsTabWidget] No result sets found in {base_output_dir}")
            return False
        
        # Load the most recent (first in the sorted list)
        latest = result_sets[0]
        print(f"[ResultsTabWidget] Loading last results from {latest['path']}")
        self.load_results(latest['path'])
        return True
    
    def load_results(self, output_dir: str, wing_id: Optional[str] = None, pipeline_id: Optional[str] = None):
        """
        Load results from database with semantic and scoring support.
        
        Args:
            output_dir: Directory containing correlation_results.db
            wing_id: Optional Wing ID for Wing-specific semantic mappings
            pipeline_id: Optional Pipeline ID for Pipeline-specific semantic mappings
        """
        # Handle None input
        if output_dir is None:
            print("❌ No output directory specified")
            return
        
        output_path = Path(output_dir)
        
        if not output_path.exists():
            QMessageBox.warning(
                self,
                "Directory Not Found",
                f"Output directory not found:\n{output_dir}"
            )
            return
        
        # Check for database file
        db_path = output_path / "correlation_results.db"
        
        if not db_path.exists():
            print(f"[ResultsTabWidget] Database not found: {db_path}")
            QMessageBox.warning(
                self,
                "Database Not Found",
                f"Correlation results database not found:\n{db_path}\n\n"
                "Please ensure the correlation engine has been executed and results saved to database."
            )
            return
        
        # Clear existing tabs
        self.clear_all_tabs()
        
        # Import semantic mapping formatter
        try:
            from ..engine.results_formatter import apply_semantic_mappings_to_result
        except ImportError:
            apply_semantic_mappings_to_result = None
        
        print(f"[ResultsTabWidget] Loading results from database: {db_path}")
        
        try:
            from ..engine.database_persistence import ResultsDatabase
            
            with ResultsDatabase(str(db_path)) as db:
                # Get the latest execution
                latest_execution_id = db.get_latest_execution_id()
                
                if not latest_execution_id:
                    print("[ResultsTabWidget] No executions found in database")
                    QMessageBox.information(
                        self,
                        "No Results",
                        "No correlation results found in database."
                    )
                    return
                
                print(f"[ResultsTabWidget] Loading results for execution {latest_execution_id}")
                
                # Load all results for the latest execution
                correlation_results = db.load_execution_results(latest_execution_id)
                
                if not correlation_results:
                    print("[ResultsTabWidget] No results found for latest execution")
                    QMessageBox.information(
                        self,
                        "No Results",
                        f"No correlation results found for execution {latest_execution_id}."
                    )
                    return
                
                print(f"[ResultsTabWidget] Loaded {len(correlation_results)} correlation results from database")
                
                loaded_count = 0
                error_count = 0
                
                for result in correlation_results:
                    try:
                        # Apply semantic mappings if available
                        if apply_semantic_mappings_to_result:
                            result = apply_semantic_mappings_to_result(
                                result,
                                wing_id=wing_id or result.wing_id,
                                pipeline_id=pipeline_id
                            )
                        
                        # Create tab for this result
                        self.add_result_tab(result)
                        loaded_count += 1
                        
                        print(f"[ResultsTabWidget] ✓ Loaded {result.wing_name}: {len(result.matches):,} matches")
                        
                    except Exception as e:
                        error_count += 1
                        print(f"[ResultsTabWidget] ✗ Error processing result {result.wing_name}: {e}")
                
                print(f"[ResultsTabWidget] ✓ Successfully loaded {loaded_count} results from database")
                
                if error_count > 0:
                    print(f"[ResultsTabWidget] ⚠ {error_count} results had errors")
                
                # Update summary
                self._update_summary()
        
        except Exception as e:
            print(f"[ResultsTabWidget] Error loading results from database: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self,
                "Database Error",
                f"Failed to load results from database:\n\n{str(e)}"
            )


# Backward compatibility aliases
EnhancedResultsTabWidget = ResultsTabWidget
EnhancedResultTab = ResultTab


class ResultsTabWidget(QWidget):
    """
    Multi-tab result management widget with semantic and scoring support.
    
    Provides engine-specific column configurations for time-window and identity-based engines.
    """
    
    # Engine-specific column configurations
    TIME_WINDOW_COLUMNS = [
        {"name": "Match ID", "width": 80, "sortable": True},
        {"name": "Window Start", "width": 150, "sortable": True},
        {"name": "Window End", "width": 150, "sortable": True},
        {"name": "Score", "width": 80, "sortable": True},
        {"name": "Interpretation", "width": 120, "sortable": True},
        {"name": "Feather Count", "width": 100, "sortable": True},
        {"name": "Time Spread (s)", "width": 100, "sortable": True},
        {"name": "Semantic Value", "width": 150, "sortable": True},
        {"name": "Application", "width": 150, "sortable": True},
        {"name": "File Path", "width": 200, "sortable": True}
    ]
    
    IDENTITY_COLUMNS = [
        {"name": "Match ID", "width": 80, "sortable": True},
        {"name": "Identity Value", "width": 150, "sortable": True},
        {"name": "Identity Type", "width": 100, "sortable": True},
        {"name": "Semantic Value", "width": 150, "sortable": True},
        {"name": "Score", "width": 80, "sortable": True},
        {"name": "Interpretation", "width": 120, "sortable": True},
        {"name": "Feather Count", "width": 100, "sortable": True},
        {"name": "First Seen", "width": 150, "sortable": True},
        {"name": "Last Seen", "width": 150, "sortable": True},
        {"name": "Application", "width": 150, "sortable": True}
    ]
    
    # Signals
    tab_state_changed = pyqtSignal(str, dict)
    match_selected = pyqtSignal(str, dict)
    export_requested = pyqtSignal(str, dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tab_states: Dict[str, TabState] = {}
        self.engine_type = "time_based"
        self.global_semantic_mappings: Dict[str, Any] = {}
        self.global_scoring_configuration: Dict[str, Any] = {}
        self._current_columns = self.TIME_WINDOW_COLUMNS
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.tabCloseRequested.connect(self._close_tab)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #334155; background: #1E293B; border-radius: 8px; }
            QTabBar::tab { background: #1E293B; color: #94A3B8; border: 1px solid #334155; padding: 6px 12px; }
            QTabBar::tab:selected { background-color: #0B1220; color: #00FFFF; border-bottom: 2px solid #00FFFF; }
        """)
        
        layout.addWidget(self.tab_widget)
        apply_tab_close_button_styling(self.tab_widget, "dark")
        
        self.summary_tab = self._create_summary_tab()
        self.tab_widget.addTab(self.summary_tab, "📊 Summary")
    
    def _create_summary_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        stats_group = QGroupBox("Overall Statistics")
        stats_layout = QFormLayout()
        self.total_matches_label = QLabel("0")
        stats_layout.addRow("Total Matches:", self.total_matches_label)
        self.total_tabs_label = QLabel("0")
        stats_layout.addRow("Active Tabs:", self.total_tabs_label)
        self.avg_score_label = QLabel("0.00")
        stats_layout.addRow("Average Score:", self.avg_score_label)
        self.engine_type_label = QLabel("Time-Based")
        stats_layout.addRow("Engine Type:", self.engine_type_label)
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        integration_group = QGroupBox("Integration Status")
        integration_layout = QFormLayout()
        self.semantic_status_label = QLabel("Not configured")
        integration_layout.addRow("Semantic Mappings:", self.semantic_status_label)
        self.scoring_status_label = QLabel("Not configured")
        integration_layout.addRow("Weighted Scoring:", self.scoring_status_label)
        integration_group.setLayout(integration_layout)
        layout.addWidget(integration_group)
        
        breakdown_group = QGroupBox("Tab Breakdown")
        breakdown_layout = QVBoxLayout()
        self.breakdown_table = QTableWidget()
        self.breakdown_table.setColumnCount(6)
        self.breakdown_table.setHorizontalHeaderLabels(["Tab", "Wing", "Matches", "Avg Score", "Semantic", "Last Accessed"])
        self.breakdown_table.horizontalHeader().setStretchLastSection(True)
        breakdown_layout.addWidget(self.breakdown_table)
        breakdown_group.setLayout(breakdown_layout)
        layout.addWidget(breakdown_group)
        layout.addStretch()
        return widget
    
    def set_engine_type(self, engine_type: str):
        old_engine_type = self.engine_type
        self.engine_type = engine_type
        self.configure_for_engine(engine_type)
        self.engine_type_label.setText("Identity-Based" if engine_type == "identity_based" else "Time-Based")
        if old_engine_type != engine_type:
            self._reconfigure_all_tabs()
    
    def _reconfigure_all_tabs(self):
        for tab_id in self.tab_states:
            tab_widget = self._get_tab_widget(tab_id)
            if tab_widget and isinstance(tab_widget, ResultTab):
                try:
                    tab_widget.set_engine_type(self.engine_type)
                    tab_widget._refresh_tab()
                except Exception as e:
                    print(f"[ResultsTabWidget] Error reconfiguring tab {tab_id}: {e}")
        self._update_summary()
    
    def configure_for_engine(self, engine_type: str):
        if engine_type == "identity_based":
            self._current_columns = self.IDENTITY_COLUMNS
            self._configure_identity_display()
        else:
            self._current_columns = self.TIME_WINDOW_COLUMNS
            self._configure_time_window_display()
    
    def _configure_time_window_display(self):
        self.breakdown_table.setHorizontalHeaderLabels(["Tab", "Wing", "Matches", "Avg Score", "Semantic", "Last Accessed"])
    
    def _configure_identity_display(self):
        self.breakdown_table.setHorizontalHeaderLabels(["Tab", "Wing", "Identities", "Avg Score", "Semantic", "Last Accessed"])
    
    def get_current_columns(self) -> List[Dict[str, Any]]:
        return self._current_columns
    
    def update_global_semantic_mappings(self, semantic_mappings: Dict[str, Any]):
        self.global_semantic_mappings = semantic_mappings
        for tab_id in self.tab_states:
            tab_widget = self._get_tab_widget(tab_id)
            if tab_widget and isinstance(tab_widget, ResultTab):
                tab_widget.update_semantic_mappings(semantic_mappings)
        self._update_summary()
    
    def update_global_scoring_configuration(self, scoring_config: Dict[str, Any]):
        self.global_scoring_configuration = scoring_config
        for tab_id in self.tab_states:
            tab_widget = self._get_tab_widget(tab_id)
            if tab_widget and isinstance(tab_widget, ResultTab):
                tab_widget.update_scoring_configuration(scoring_config)
        self._update_summary()
    
    def add_result_tab(self, wing_name: str, result: CorrelationResult, 
                      semantic_mappings: Optional[Dict[str, Any]] = None,
                      scoring_config: Optional[Dict[str, Any]] = None) -> str:
        tab_id = f"{wing_name}_{datetime.now().strftime('%H%M%S')}"
        tab_state = TabState(tab_id, wing_name, result)
        
        if semantic_mappings:
            tab_state.update_semantic_mappings(semantic_mappings)
        elif self.global_semantic_mappings:
            tab_state.update_semantic_mappings(self.global_semantic_mappings)
        
        if scoring_config:
            tab_state.update_scoring_configuration(scoring_config)
        elif self.global_scoring_configuration:
            tab_state.update_scoring_configuration(self.global_scoring_configuration)
        
        tab_widget = ResultTab(tab_state, engine_type=self.engine_type)
        tab_widget.tab_state_changed.connect(self._on_tab_state_changed)
        tab_widget.match_selected.connect(self.match_selected)
        tab_widget.export_requested.connect(self.export_requested)
        
        tab_label = self._generate_tab_label(wing_name, result)
        tab_index = self.tab_widget.addTab(tab_widget, tab_label)
        self.tab_states[tab_id] = tab_state
        self.tab_widget.setCurrentIndex(tab_index)
        self._update_summary()
        return tab_id
    
    def _generate_tab_label(self, wing_name: str, result: CorrelationResult) -> str:
        icon = "🔷" if self.engine_type == "identity_based" else "⏱️"
        match_count = len(result.matches)
        display_name = wing_name[:12] + "..." if len(wing_name) > 15 else wing_name
        return f"{icon} {display_name} ({match_count})"
    
    def _get_tab_widget(self, tab_id: str) -> Optional[QWidget]:
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if isinstance(widget, ResultTab) and widget.tab_state.tab_id == tab_id:
                return widget
        return None
    
    def _close_tab(self, index: int):
        if index == 0:
            return
        widget = self.tab_widget.widget(index)
        if isinstance(widget, ResultTab):
            tab_id = widget.tab_state.tab_id
            if tab_id in self.tab_states:
                del self.tab_states[tab_id]
        self.tab_widget.removeTab(index)
        self._update_summary()
    
    def _on_tab_changed(self, index: int):
        widget = self.tab_widget.widget(index)
        if isinstance(widget, ResultTab):
            widget.tab_state.last_accessed = datetime.now()
            self._update_summary()
    
    def _on_tab_state_changed(self, tab_id: str, state_data: dict):
        self.tab_state_changed.emit(tab_id, state_data)
        self._update_summary()
    
    def _update_summary(self):
        total_matches = sum(len(state.result.matches) for state in self.tab_states.values())
        total_tabs = len(self.tab_states)
        all_scores = [m.match_score for state in self.tab_states.values() for m in state.result.matches]
        avg_score = sum(all_scores) / len(all_scores) if all_scores else 0.0
        
        self.total_matches_label.setText(f"{total_matches:,}")
        self.total_tabs_label.setText(str(total_tabs))
        self.avg_score_label.setText(f"{avg_score:.2f}")
        
        semantic_count = len(self.global_semantic_mappings)
        if semantic_count > 0:
            self.semantic_status_label.setText(f"Active ({semantic_count} mappings)")
            self.semantic_status_label.setStyleSheet("color: #4CAF50;")
        else:
            self.semantic_status_label.setText("Not configured")
            self.semantic_status_label.setStyleSheet("color: #9E9E9E;")
        
        if self.global_scoring_configuration:
            self.scoring_status_label.setText("Active")
            self.scoring_status_label.setStyleSheet("color: #4CAF50;")
        else:
            self.scoring_status_label.setText("Not configured")
            self.scoring_status_label.setStyleSheet("color: #9E9E9E;")
        
        self._update_breakdown_table()
    
    def _update_breakdown_table(self):
        self.breakdown_table.setRowCount(0)
        for tab_id, tab_state in self.tab_states.items():
            row = self.breakdown_table.rowCount()
            self.breakdown_table.insertRow(row)
            short_id = tab_id[:8] + "..." if len(tab_id) > 8 else tab_id
            self.breakdown_table.setItem(row, 0, QTableWidgetItem(short_id))
            self.breakdown_table.setItem(row, 1, QTableWidgetItem(tab_state.wing_name))
            match_count = len(tab_state.result.matches)
            self.breakdown_table.setItem(row, 2, QTableWidgetItem(str(match_count)))
            if tab_state.result.matches:
                avg = sum(m.match_score for m in tab_state.result.matches) / len(tab_state.result.matches)
                self.breakdown_table.setItem(row, 3, QTableWidgetItem(f"{avg:.2f}"))
            else:
                self.breakdown_table.setItem(row, 3, QTableWidgetItem("0.00"))
            sem_count = len(tab_state.semantic_mappings)
            self.breakdown_table.setItem(row, 4, QTableWidgetItem(f"{sem_count} mappings" if sem_count > 0 else "None"))
            self.breakdown_table.setItem(row, 5, QTableWidgetItem(tab_state.last_accessed.strftime("%H:%M:%S")))
    
    def get_all_tab_states(self) -> Dict[str, TabState]:
        return self.tab_states.copy()
    
    def clear_all_tabs(self):
        while self.tab_widget.count() > 1:
            self.tab_widget.removeTab(1)
        self.tab_states.clear()
        self._update_summary()
    
    def load_results(self, output_dir: str, wing_id: Optional[str] = None, pipeline_id: Optional[str] = None):
        if output_dir is None:
            return
        output_path = Path(output_dir)
        if not output_path.exists():
            QMessageBox.warning(self, "Directory Not Found", f"Output directory not found:\n{output_dir}")
            return
        
        self.clear_all_tabs()
        
        try:
            from ..engine.results_formatter import apply_semantic_mappings_to_result
        except ImportError:
            apply_semantic_mappings_to_result = None
        
        summary_file = output_path / "pipeline_summary.json"
        if summary_file.exists():
            try:
                with open(summary_file, 'r') as f:
                    summary_data = json.load(f)
                    if 'engine_type' in summary_data:
                        self.set_engine_type(summary_data['engine_type'])
            except Exception:
                pass
        
        result_files = list(output_path.glob("result_*.json"))
        for wing_dir in output_path.iterdir():
            if wing_dir.is_dir() and not wing_dir.name.startswith('.'):
                result_files.extend(wing_dir.glob("result_*.json"))
        result_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        
        for result_file in result_files:
            try:
                result = CorrelationResult.load_from_file(str(result_file))
                if apply_semantic_mappings_to_result:
                    result = apply_semantic_mappings_to_result(result, wing_id=wing_id or result.wing_id, pipeline_id=pipeline_id)
                semantic_mappings = {}
                scoring_config = {}
                if hasattr(result, 'metadata') and result.metadata:
                    semantic_mappings = result.metadata.get('semantic_mappings', {})
                    scoring_config = result.metadata.get('scoring_configuration', {})
                self.add_result_tab(result.wing_name, result, semantic_mappings=semantic_mappings, scoring_config=scoring_config)
            except Exception as e:
                print(f"[ResultsTabWidget] Error loading result file {result_file}: {e}")


# Backward compatibility aliases
EnhancedResultsTabWidget = ResultsTabWidget
EnhancedResultTab = ResultTab
