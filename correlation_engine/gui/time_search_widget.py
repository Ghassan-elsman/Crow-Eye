"""
Time-Based Search and Highlighting Widget

Provides advanced search capabilities for time-based hierarchical results with
semantic search, temporal filtering, and result highlighting.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass
from enum import Enum

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, 
    QComboBox, QCheckBox, QLabel, QFrame, QScrollArea, QListWidget,
    QListWidgetItem, QGroupBox, QFormLayout, QSpinBox, QDateTimeEdit,
    QTabWidget, QTextEdit, QSplitter
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QDateTime
from PyQt5.QtGui import QColor, QFont, QTextCharFormat, QTextCursor, QBrush

from ..engine.data_structures import (
    AnchorTimeGroup, TimeBasedQueryResult, IdentityWithAnchors, 
    EvidenceRow, QueryFilters
)

logger = logging.getLogger(__name__)


class SearchType(Enum):
    """Types of search operations."""
    TEXT = "text"
    SEMANTIC = "semantic"
    TEMPORAL = "temporal"
    PATTERN = "pattern"
    COMBINED = "combined"


@dataclass
class SearchResult:
    """Individual search result with highlighting information."""
    anchor_time: datetime
    identity_id: str
    identity_value: str
    evidence_id: str
    match_type: SearchType
    match_text: str
    context: str
    confidence: float
    highlight_positions: List[Tuple[int, int]]  # Start, end positions for highlighting


@dataclass
class SearchQuery:
    """Search query configuration."""
    query_text: str
    search_type: SearchType
    case_sensitive: bool = False
    whole_words: bool = False
    regex_enabled: bool = False
    semantic_categories: List[str] = None
    time_range: Optional[Tuple[datetime, datetime]] = None
    artifact_types: List[str] = None
    identity_types: List[str] = None
    evidence_roles: List[str] = None
    min_confidence: float = 0.0


class TimeBasedSearchWidget(QWidget):
    """
    Advanced search widget for time-based hierarchical results.
    
    Features:
    - Multi-type search (text, semantic, temporal, pattern)
    - Real-time search with debouncing
    - Result highlighting and navigation
    - Search history and saved queries
    - Advanced filtering options
    """
    
    # Signals
    search_results_updated = pyqtSignal(list)  # List[SearchResult]
    result_selected = pyqtSignal(object)  # SearchResult
    highlight_requested = pyqtSignal(str, list)  # Text, highlight positions
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.anchor_time_groups: List[AnchorTimeGroup] = []
        self.current_results: List[SearchResult] = []
        self.search_history: List[SearchQuery] = []
        self.saved_queries: Dict[str, SearchQuery] = {}
        
        # Search state
        self.current_query: Optional[SearchQuery] = None
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._perform_search)
        
        # Highlighting colors
        self.highlight_colors = {
            SearchType.TEXT: QColor(255, 255, 0, 100),      # Yellow
            SearchType.SEMANTIC: QColor(0, 255, 0, 100),    # Green
            SearchType.TEMPORAL: QColor(0, 150, 255, 100),  # Blue
            SearchType.PATTERN: QColor(255, 150, 0, 100),   # Orange
            SearchType.COMBINED: QColor(255, 0, 255, 100)   # Magenta
        }
        
        self._init_ui()
        self._setup_connections()
    
    def _init_ui(self):
        """Initialize UI components."""
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        
        # Search input section
        search_section = self._create_search_section()
        layout.addWidget(search_section)
        
        # Advanced options (collapsible)
        self.advanced_options = self._create_advanced_options()
        layout.addWidget(self.advanced_options)
        
        # Results section
        results_section = self._create_results_section()
        layout.addWidget(results_section)
    
    def _create_search_section(self) -> QWidget:
        """Create main search input section."""
        section = QGroupBox("Search")
        layout = QVBoxLayout(section)
        
        # Main search input
        search_layout = QHBoxLayout()
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search identities, artifacts, semantic data, or time patterns...")
        self.search_input.textChanged.connect(self._on_search_text_changed)
        search_layout.addWidget(self.search_input)
        
        # Search type selector
        self.search_type_combo = QComboBox()
        self.search_type_combo.addItems([
            "Smart Search", "Text Search", "Semantic Search", 
            "Temporal Search", "Pattern Search", "Combined Search"
        ])
        self.search_type_combo.setMaximumWidth(120)
        self.search_type_combo.currentTextChanged.connect(self._on_search_type_changed)
        search_layout.addWidget(self.search_type_combo)
        
        # Search button
        search_btn = QPushButton("🔍 Search")
        search_btn.setMaximumWidth(80)
        search_btn.clicked.connect(self._trigger_search)
        search_layout.addWidget(search_btn)
        
        # Clear button
        clear_btn = QPushButton("✖")
        clear_btn.setMaximumWidth(30)
        clear_btn.clicked.connect(self.clear_search)
        search_layout.addWidget(clear_btn)
        
        layout.addLayout(search_layout)
        
        # Quick options
        options_layout = QHBoxLayout()
        
        self.case_sensitive_cb = QCheckBox("Case sensitive")
        options_layout.addWidget(self.case_sensitive_cb)
        
        self.whole_words_cb = QCheckBox("Whole words")
        options_layout.addWidget(self.whole_words_cb)
        
        self.regex_cb = QCheckBox("Regex")
        options_layout.addWidget(self.regex_cb)
        
        options_layout.addStretch()
        
        # Advanced toggle
        self.advanced_toggle = QPushButton("⚙️ Advanced")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setMaximumWidth(100)
        self.advanced_toggle.toggled.connect(self._toggle_advanced_options)
        options_layout.addWidget(self.advanced_toggle)
        
        layout.addLayout(options_layout)
        
        return section
    
    def _create_advanced_options(self) -> QWidget:
        """Create advanced search options section."""
        section = QGroupBox("Advanced Options")
        section.setVisible(False)  # Initially hidden
        
        layout = QFormLayout(section)
        
        # Semantic categories
        self.semantic_categories_input = QLineEdit()
        self.semantic_categories_input.setPlaceholderText("e.g., execution, file_access, network")
        layout.addRow("Semantic Categories:", self.semantic_categories_input)
        
        # Time range
        time_layout = QHBoxLayout()
        self.start_time_edit = QDateTimeEdit()
        self.start_time_edit.setCalendarPopup(True)
        self.start_time_edit.setMaximumWidth(150)
        time_layout.addWidget(self.start_time_edit)
        
        time_layout.addWidget(QLabel("to"))
        
        self.end_time_edit = QDateTimeEdit()
        self.end_time_edit.setCalendarPopup(True)
        self.end_time_edit.setDateTime(QDateTime.currentDateTime())
        self.end_time_edit.setMaximumWidth(150)
        time_layout.addWidget(self.end_time_edit)
        
        time_layout.addStretch()
        layout.addRow("Time Range:", time_layout)
        
        # Artifact types
        self.artifact_types_input = QLineEdit()
        self.artifact_types_input.setPlaceholderText("e.g., prefetch, srum, registry")
        layout.addRow("Artifact Types:", self.artifact_types_input)
        
        # Identity types
        self.identity_types_combo = QComboBox()
        self.identity_types_combo.addItems(["All", "name", "path", "hash", "composite"])
        layout.addRow("Identity Types:", self.identity_types_combo)
        
        # Evidence roles
        self.evidence_roles_combo = QComboBox()
        self.evidence_roles_combo.addItems(["All", "primary", "secondary", "supporting"])
        layout.addRow("Evidence Roles:", self.evidence_roles_combo)
        
        # Confidence threshold
        self.confidence_spin = QSpinBox()
        self.confidence_spin.setRange(0, 100)
        self.confidence_spin.setValue(0)
        self.confidence_spin.setSuffix("%")
        layout.addRow("Min Confidence:", self.confidence_spin)
        
        return section
    
    def _create_results_section(self) -> QWidget:
        """Create search results section."""
        section = QGroupBox("Search Results")
        layout = QVBoxLayout(section)
        
        # Results summary
        self.results_summary = QLabel("No search performed")
        self.results_summary.setStyleSheet("color: #888; font-size: 9pt;")
        layout.addWidget(self.results_summary)
        
        # Results list
        self.results_list = QListWidget()
        self.results_list.setMaximumHeight(200)
        self.results_list.itemClicked.connect(self._on_result_selected)
        layout.addWidget(self.results_list)
        
        # Navigation buttons
        nav_layout = QHBoxLayout()
        
        self.prev_btn = QPushButton("◀ Previous")
        self.prev_btn.setEnabled(False)
        self.prev_btn.clicked.connect(self._navigate_previous)
        nav_layout.addWidget(self.prev_btn)
        
        self.next_btn = QPushButton("Next ▶")
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(self._navigate_next)
        nav_layout.addWidget(self.next_btn)
        
        nav_layout.addStretch()
        
        # Export results
        export_btn = QPushButton("📄 Export Results")
        export_btn.clicked.connect(self._export_results)
        nav_layout.addWidget(export_btn)
        
        layout.addLayout(nav_layout)
        
        return section
    
    def _setup_connections(self):
        """Setup signal connections."""
        # Connect option changes to search trigger
        self.case_sensitive_cb.toggled.connect(self._trigger_delayed_search)
        self.whole_words_cb.toggled.connect(self._trigger_delayed_search)
        self.regex_cb.toggled.connect(self._trigger_delayed_search)
        
        # Advanced options
        self.semantic_categories_input.textChanged.connect(self._trigger_delayed_search)
        self.start_time_edit.dateTimeChanged.connect(self._trigger_delayed_search)
        self.end_time_edit.dateTimeChanged.connect(self._trigger_delayed_search)
        self.artifact_types_input.textChanged.connect(self._trigger_delayed_search)
        self.identity_types_combo.currentTextChanged.connect(self._trigger_delayed_search)
        self.evidence_roles_combo.currentTextChanged.connect(self._trigger_delayed_search)
        self.confidence_spin.valueChanged.connect(self._trigger_delayed_search)
    
    def set_data(self, anchor_time_groups: List[AnchorTimeGroup]):
        """Set search data."""
        self.anchor_time_groups = anchor_time_groups
        
        # Update time range defaults
        if anchor_time_groups:
            times = [group.anchor_time for group in anchor_time_groups]
            start_time = min(times)
            end_time = max(times)
            
            self.start_time_edit.setDateTime(QDateTime.fromSecsSinceEpoch(int(start_time.timestamp())))
            self.end_time_edit.setDateTime(QDateTime.fromSecsSinceEpoch(int(end_time.timestamp())))
        
        # Clear previous results
        self.clear_search()
    
    def _on_search_text_changed(self, text: str):
        """Handle search text change with debouncing."""
        self._trigger_delayed_search()
    
    def _on_search_type_changed(self, search_type_text: str):
        """Handle search type change."""
        # Update UI based on search type
        if search_type_text == "Semantic Search":
            self.semantic_categories_input.setVisible(True)
        elif search_type_text == "Temporal Search":
            self.start_time_edit.setVisible(True)
            self.end_time_edit.setVisible(True)
        
        self._trigger_delayed_search()
    
    def _toggle_advanced_options(self, visible: bool):
        """Toggle advanced options visibility."""
        self.advanced_options.setVisible(visible)
        self.advanced_toggle.setText("⚙️ Advanced ▼" if visible else "⚙️ Advanced ▶")
    
    def _trigger_delayed_search(self):
        """Trigger search with delay for debouncing."""
        self.search_timer.stop()
        self.search_timer.start(300)  # 300ms delay
    
    def _trigger_search(self):
        """Trigger immediate search."""
        self.search_timer.stop()
        self._perform_search()
    
    def _perform_search(self):
        """Perform the actual search operation."""
        query_text = self.search_input.text().strip()
        
        if not query_text:
            self.clear_search()
            return
        
        # Build search query
        query = self._build_search_query(query_text)
        self.current_query = query
        
        # Perform search
        results = self._execute_search(query)
        
        # Update results
        self.current_results = results
        self._update_results_display()
        
        # Add to history
        if query not in self.search_history:
            self.search_history.append(query)
            if len(self.search_history) > 50:  # Limit history size
                self.search_history.pop(0)
        
        # Emit results
        self.search_results_updated.emit(results)
    
    def _build_search_query(self, query_text: str) -> SearchQuery:
        """Build search query from UI inputs."""
        # Determine search type
        search_type_text = self.search_type_combo.currentText()
        
        if search_type_text == "Smart Search":
            search_type = self._detect_search_type(query_text)
        elif search_type_text == "Text Search":
            search_type = SearchType.TEXT
        elif search_type_text == "Semantic Search":
            search_type = SearchType.SEMANTIC
        elif search_type_text == "Temporal Search":
            search_type = SearchType.TEMPORAL
        elif search_type_text == "Pattern Search":
            search_type = SearchType.PATTERN
        else:
            search_type = SearchType.COMBINED
        
        # Build time range
        time_range = None
        if self.advanced_options.isVisible():
            start_time = self.start_time_edit.dateTime().toPyDateTime()
            end_time = self.end_time_edit.dateTime().toPyDateTime()
            if start_time < end_time:
                time_range = (start_time, end_time)
        
        # Parse lists
        semantic_categories = []
        if self.semantic_categories_input.text().strip():
            semantic_categories = [cat.strip() for cat in self.semantic_categories_input.text().split(',')]
        
        artifact_types = []
        if self.artifact_types_input.text().strip():
            artifact_types = [art.strip() for art in self.artifact_types_input.text().split(',')]
        
        identity_types = []
        if self.identity_types_combo.currentText() != "All":
            identity_types = [self.identity_types_combo.currentText()]
        
        evidence_roles = []
        if self.evidence_roles_combo.currentText() != "All":
            evidence_roles = [self.evidence_roles_combo.currentText()]
        
        return SearchQuery(
            query_text=query_text,
            search_type=search_type,
            case_sensitive=self.case_sensitive_cb.isChecked(),
            whole_words=self.whole_words_cb.isChecked(),
            regex_enabled=self.regex_cb.isChecked(),
            semantic_categories=semantic_categories,
            time_range=time_range,
            artifact_types=artifact_types,
            identity_types=identity_types,
            evidence_roles=evidence_roles,
            min_confidence=self.confidence_spin.value() / 100.0
        )
    
    def _detect_search_type(self, query_text: str) -> SearchType:
        """Automatically detect search type from query text."""
        # Check for temporal patterns
        if re.search(r'\d{4}-\d{2}-\d{2}|\d{2}:\d{2}|today|yesterday|last\s+\w+', query_text, re.IGNORECASE):
            return SearchType.TEMPORAL
        
        # Check for regex patterns
        if any(char in query_text for char in ['[', ']', '(', ')', '*', '+', '?', '^', '$']):
            return SearchType.PATTERN
        
        # Check for semantic keywords
        semantic_keywords = ['execution', 'access', 'network', 'registry', 'file', 'process']
        if any(keyword in query_text.lower() for keyword in semantic_keywords):
            return SearchType.SEMANTIC
        
        # Default to text search
        return SearchType.TEXT
    
    def _execute_search(self, query: SearchQuery) -> List[SearchResult]:
        """Execute search query and return results."""
        results = []
        
        for group in self.anchor_time_groups:
            # Check time range filter
            if query.time_range:
                start_time, end_time = query.time_range
                if not (start_time <= group.anchor_time <= end_time):
                    continue
            
            # Search within identities
            for identity in group.identities:
                # Check identity type filter
                if query.identity_types and identity.identity_type not in query.identity_types:
                    continue
                
                # Search identity value
                identity_matches = self._search_in_text(
                    query, identity.identity_value, f"Identity: {identity.identity_value}"
                )
                
                for match in identity_matches:
                    results.append(SearchResult(
                        anchor_time=group.anchor_time,
                        identity_id=identity.identity_id,
                        identity_value=identity.identity_value,
                        evidence_id="identity",
                        match_type=query.search_type,
                        match_text=match.get('match_text', ''),
                        context=match.get('context', ''),
                        confidence=match.get('confidence', 1.0),
                        highlight_positions=match.get('positions', [])
                    ))
                
                # Search within anchors and evidence
                for anchor in identity.anchors:
                    for evidence in anchor.evidence_rows:
                        # Check evidence role filter
                        if query.evidence_roles and evidence.role not in query.evidence_roles:
                            continue
                        
                        # Check artifact type filter
                        if query.artifact_types and evidence.artifact not in query.artifact_types:
                            continue
                        
                        # Search evidence data
                        evidence_matches = self._search_in_evidence(query, evidence)
                        
                        for match in evidence_matches:
                            results.append(SearchResult(
                                anchor_time=group.anchor_time,
                                identity_id=identity.identity_id,
                                identity_value=identity.identity_value,
                                evidence_id=f"{evidence.artifact}_{evidence.row_id}",
                                match_type=query.search_type,
                                match_text=match.get('match_text', ''),
                                context=match.get('context', ''),
                                confidence=match.get('confidence', 1.0),
                                highlight_positions=match.get('positions', [])
                            ))
        
        # Filter by confidence
        if query.min_confidence > 0:
            results = [r for r in results if r.confidence >= query.min_confidence]
        
        # Sort by relevance (confidence, then time)
        results.sort(key=lambda x: (-x.confidence, x.anchor_time))
        
        return results
    
    def _search_in_text(self, query: SearchQuery, text: str, context: str) -> List[Dict[str, Any]]:
        """Search within text content."""
        matches = []
        
        if query.search_type == SearchType.TEXT or query.search_type == SearchType.COMBINED:
            # Text search
            search_text = query.query_text
            target_text = text if query.case_sensitive else text.lower()
            
            if not query.case_sensitive:
                search_text = search_text.lower()
            
            if query.regex_enabled:
                try:
                    pattern = re.compile(search_text)
                    for match in pattern.finditer(target_text):
                        matches.append({
                            'match_text': match.group(),
                            'context': context,
                            'confidence': 1.0,
                            'positions': [(match.start(), match.end())]
                        })
                except re.error:
                    pass  # Invalid regex
            else:
                if query.whole_words:
                    pattern = r'\b' + re.escape(search_text) + r'\b'
                    for match in re.finditer(pattern, target_text, re.IGNORECASE if not query.case_sensitive else 0):
                        matches.append({
                            'match_text': match.group(),
                            'context': context,
                            'confidence': 1.0,
                            'positions': [(match.start(), match.end())]
                        })
                else:
                    start = 0
                    while True:
                        pos = target_text.find(search_text, start)
                        if pos == -1:
                            break
                        matches.append({
                            'match_text': search_text,
                            'context': context,
                            'confidence': 1.0,
                            'positions': [(pos, pos + len(search_text))]
                        })
                        start = pos + 1
        
        return matches
    
    def _search_in_evidence(self, query: SearchQuery, evidence: EvidenceRow) -> List[Dict[str, Any]]:
        """Search within evidence data."""
        matches = []
        
        # Search in semantic data
        if query.search_type in [SearchType.SEMANTIC, SearchType.COMBINED]:
            for key, value in evidence.semantic.items():
                if query.semantic_categories and key not in query.semantic_categories:
                    continue
                
                text_matches = self._search_in_text(query, str(value), f"Semantic {key}")
                matches.extend(text_matches)
        
        # Search in original data
        if query.search_type in [SearchType.TEXT, SearchType.COMBINED]:
            for key, value in evidence.original_data.items():
                text_matches = self._search_in_text(query, str(value), f"Data {key}")
                matches.extend(text_matches)
        
        # Temporal search
        if query.search_type == SearchType.TEMPORAL and evidence.timestamp:
            # Check if timestamp matches temporal query
            if self._matches_temporal_query(query.query_text, evidence.timestamp):
                matches.append({
                    'match_text': evidence.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    'context': f"Timestamp: {evidence.artifact}",
                    'confidence': 1.0,
                    'positions': []
                })
        
        return matches
    
    def _matches_temporal_query(self, query_text: str, timestamp: datetime) -> bool:
        """Check if timestamp matches temporal query."""
        query_lower = query_text.lower()
        
        # Simple temporal matching
        if 'today' in query_lower:
            return timestamp.date() == datetime.now().date()
        elif 'yesterday' in query_lower:
            yesterday = datetime.now().date() - timedelta(days=1)
            return timestamp.date() == yesterday
        elif 'last hour' in query_lower:
            return timestamp > datetime.now() - timedelta(hours=1)
        elif 'last day' in query_lower:
            return timestamp > datetime.now() - timedelta(days=1)
        
        # Date pattern matching
        date_patterns = [
            r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
            r'\d{2}:\d{2}',        # HH:MM
        ]
        
        for pattern in date_patterns:
            if re.search(pattern, query_text):
                # Extract and compare dates/times
                matches = re.findall(pattern, query_text)
                for match in matches:
                    if match in timestamp.strftime('%Y-%m-%d %H:%M:%S'):
                        return True
        
        return False
    
    def _update_results_display(self):
        """Update results display."""
        self.results_list.clear()
        
        if not self.current_results:
            self.results_summary.setText("No results found")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            return
        
        # Update summary
        total_results = len(self.current_results)
        unique_identities = len(set(r.identity_id for r in self.current_results))
        unique_times = len(set(r.anchor_time for r in self.current_results))
        
        self.results_summary.setText(
            f"Found {total_results} matches across {unique_identities} identities at {unique_times} time points"
        )
        
        # Populate results list
        for i, result in enumerate(self.current_results[:100]):  # Limit display
            item_text = (
                f"{result.anchor_time.strftime('%H:%M:%S')} | "
                f"{result.identity_value[:30]}{'...' if len(result.identity_value) > 30 else ''} | "
                f"{result.match_text[:40]}{'...' if len(result.match_text) > 40 else ''}"
            )
            
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, result)
            
            # Color code by match type
            color = self.highlight_colors.get(result.match_type, QColor(200, 200, 200))
            item.setBackground(QBrush(color))
            
            self.results_list.addItem(item)
        
        # Update navigation buttons
        self.prev_btn.setEnabled(False)  # Will be implemented with result navigation
        self.next_btn.setEnabled(len(self.current_results) > 1)
    
    def _on_result_selected(self, item: QListWidgetItem):
        """Handle result selection."""
        result = item.data(Qt.UserRole)
        if result:
            self.result_selected.emit(result)
            
            # Request highlighting
            if result.highlight_positions:
                self.highlight_requested.emit(result.match_text, result.highlight_positions)
    
    def _navigate_previous(self):
        """Navigate to previous result."""
        # Implementation for result navigation
        pass
    
    def _navigate_next(self):
        """Navigate to next result."""
        # Implementation for result navigation
        pass
    
    def _export_results(self):
        """Export search results."""
        if not self.current_results:
            return
        
        # Create export data
        export_data = []
        for result in self.current_results:
            export_data.append({
                'timestamp': result.anchor_time.isoformat(),
                'identity_id': result.identity_id,
                'identity_value': result.identity_value,
                'evidence_id': result.evidence_id,
                'match_type': result.match_type.value,
                'match_text': result.match_text,
                'context': result.context,
                'confidence': result.confidence
            })
        
        # Save to file (implementation depends on requirements)
        logger.info(f"Exporting {len(export_data)} search results")
    
    def clear_search(self):
        """Clear search and results."""
        self.search_input.clear()
        self.current_results.clear()
        self.current_query = None
        self.results_list.clear()
        self.results_summary.setText("No search performed")
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
    
    def get_search_statistics(self) -> Dict[str, Any]:
        """Get search statistics."""
        if not self.current_results:
            return {}
        
        stats = {
            'total_results': len(self.current_results),
            'unique_identities': len(set(r.identity_id for r in self.current_results)),
            'unique_anchor_times': len(set(r.anchor_time for r in self.current_results)),
            'match_types': {},
            'confidence_distribution': {'high': 0, 'medium': 0, 'low': 0},
            'time_range': None
        }
        
        # Count match types
        for result in self.current_results:
            match_type = result.match_type.value
            stats['match_types'][match_type] = stats['match_types'].get(match_type, 0) + 1
            
            # Confidence distribution
            if result.confidence >= 0.8:
                stats['confidence_distribution']['high'] += 1
            elif result.confidence >= 0.5:
                stats['confidence_distribution']['medium'] += 1
            else:
                stats['confidence_distribution']['low'] += 1
        
        # Time range
        if self.current_results:
            times = [r.anchor_time for r in self.current_results]
            stats['time_range'] = (min(times), max(times))
        
        return stats