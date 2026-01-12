"""
Comparative Analysis Widget for Time-Based Results

Provides comparative analysis capabilities between different time periods,
including activity comparison, identity overlap analysis, and trend visualization.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass
from collections import defaultdict

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QComboBox, QGroupBox, QFormLayout, QDateTimeEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QTabWidget, QTextEdit, QSplitter,
    QProgressBar, QFrame, QScrollArea, QCheckBox, QSpinBox
)
from PyQt5.QtCore import Qt, pyqtSignal, QDateTime, QThread, pyqtSlot
from PyQt5.QtGui import QColor, QFont, QBrush, QPainter, QPen

from ..engine.data_structures import (
    AnchorTimeGroup, TimeBasedQueryResult, IdentityWithAnchors, 
    EvidenceRow, QueryFilters
)

logger = logging.getLogger(__name__)


@dataclass
class TimePeriod:
    """Represents a time period for comparison."""
    name: str
    start_time: datetime
    end_time: datetime
    color: QColor


@dataclass
class ComparisonMetrics:
    """Metrics for comparing time periods."""
    period_name: str
    total_identities: int
    total_evidence: int
    unique_identities: int
    artifact_breakdown: Dict[str, int]
    identity_type_breakdown: Dict[str, int]
    evidence_role_breakdown: Dict[str, int]
    activity_density: float  # Evidence per minute
    peak_activity_time: Optional[datetime]
    common_artifacts: List[str]
    dominant_identity_type: str


@dataclass
class ComparisonResult:
    """Result of comparative analysis between periods."""
    period_1: ComparisonMetrics
    period_2: ComparisonMetrics
    overlap_analysis: Dict[str, Any]
    trend_analysis: Dict[str, Any]
    recommendations: List[str]


class ComparativeAnalysisWorker(QThread):
    """Worker thread for performing comparative analysis."""
    
    analysis_complete = pyqtSignal(object)  # ComparisonResult
    progress_updated = pyqtSignal(int)  # Progress percentage
    
    def __init__(self, anchor_time_groups: List[AnchorTimeGroup], 
                 period_1: TimePeriod, period_2: TimePeriod):
        super().__init__()
        self.anchor_time_groups = anchor_time_groups
        self.period_1 = period_1
        self.period_2 = period_2
    
    def run(self):
        """Perform comparative analysis."""
        try:
            self.progress_updated.emit(10)
            
            # Filter data for each period
            period_1_data = self._filter_data_for_period(self.period_1)
            self.progress_updated.emit(30)
            
            period_2_data = self._filter_data_for_period(self.period_2)
            self.progress_updated.emit(50)
            
            # Calculate metrics for each period
            metrics_1 = self._calculate_metrics(period_1_data, self.period_1.name)
            self.progress_updated.emit(70)
            
            metrics_2 = self._calculate_metrics(period_2_data, self.period_2.name)
            self.progress_updated.emit(80)
            
            # Perform overlap and trend analysis
            overlap_analysis = self._analyze_overlap(period_1_data, period_2_data)
            trend_analysis = self._analyze_trends(metrics_1, metrics_2)
            recommendations = self._generate_recommendations(metrics_1, metrics_2, overlap_analysis)
            
            self.progress_updated.emit(90)
            
            # Create result
            result = ComparisonResult(
                period_1=metrics_1,
                period_2=metrics_2,
                overlap_analysis=overlap_analysis,
                trend_analysis=trend_analysis,
                recommendations=recommendations
            )
            
            self.progress_updated.emit(100)
            self.analysis_complete.emit(result)
            
        except Exception as e:
            logger.error(f"Comparative analysis failed: {e}")
    
    def _filter_data_for_period(self, period: TimePeriod) -> List[AnchorTimeGroup]:
        """Filter anchor time groups for a specific period."""
        return [
            group for group in self.anchor_time_groups
            if period.start_time <= group.anchor_time <= period.end_time
        ]
    
    def _calculate_metrics(self, data: List[AnchorTimeGroup], period_name: str) -> ComparisonMetrics:
        """Calculate metrics for a time period."""
        if not data:
            return ComparisonMetrics(
                period_name=period_name,
                total_identities=0,
                total_evidence=0,
                unique_identities=0,
                artifact_breakdown={},
                identity_type_breakdown={},
                evidence_role_breakdown={},
                activity_density=0.0,
                peak_activity_time=None,
                common_artifacts=[],
                dominant_identity_type=""
            )
        
        # Basic counts
        total_identities = sum(group.total_identities for group in data)
        total_evidence = sum(group.total_evidence for group in data)
        
        # Unique identities
        unique_identity_ids = set()
        for group in data:
            for identity in group.identities:
                unique_identity_ids.add(identity.identity_id)
        
        # Breakdowns
        artifact_breakdown = defaultdict(int)
        identity_type_breakdown = defaultdict(int)
        evidence_role_breakdown = defaultdict(int)
        
        for group in data:
            for identity in group.identities:
                identity_type_breakdown[identity.identity_type] += 1
                
                for anchor in identity.anchors:
                    for evidence in anchor.evidence_rows:
                        artifact_breakdown[evidence.artifact] += 1
                        evidence_role_breakdown[evidence.role] += 1
        
        # Activity density (evidence per minute)
        if data:
            times = [group.anchor_time for group in data]
            time_span = (max(times) - min(times)).total_seconds() / 60.0
            activity_density = total_evidence / max(time_span, 1.0)
        else:
            activity_density = 0.0
        
        # Peak activity time
        peak_activity_time = None
        max_evidence = 0
        for group in data:
            if group.total_evidence > max_evidence:
                max_evidence = group.total_evidence
                peak_activity_time = group.anchor_time
        
        # Common artifacts (top 3)
        common_artifacts = sorted(artifact_breakdown.keys(), 
                                key=lambda x: artifact_breakdown[x], 
                                reverse=True)[:3]
        
        # Dominant identity type
        dominant_identity_type = max(identity_type_breakdown.keys(), 
                                   key=lambda x: identity_type_breakdown[x]) if identity_type_breakdown else ""
        
        return ComparisonMetrics(
            period_name=period_name,
            total_identities=total_identities,
            total_evidence=total_evidence,
            unique_identities=len(unique_identity_ids),
            artifact_breakdown=dict(artifact_breakdown),
            identity_type_breakdown=dict(identity_type_breakdown),
            evidence_role_breakdown=dict(evidence_role_breakdown),
            activity_density=activity_density,
            peak_activity_time=peak_activity_time,
            common_artifacts=common_artifacts,
            dominant_identity_type=dominant_identity_type
        )
    
    def _analyze_overlap(self, period_1_data: List[AnchorTimeGroup], 
                        period_2_data: List[AnchorTimeGroup]) -> Dict[str, Any]:
        """Analyze overlap between two periods."""
        # Get identities from each period
        period_1_identities = set()
        period_1_artifacts = set()
        
        for group in period_1_data:
            for identity in group.identities:
                period_1_identities.add(identity.identity_id)
                for anchor in identity.anchors:
                    for evidence in anchor.evidence_rows:
                        period_1_artifacts.add(evidence.artifact)
        
        period_2_identities = set()
        period_2_artifacts = set()
        
        for group in period_2_data:
            for identity in group.identities:
                period_2_identities.add(identity.identity_id)
                for anchor in identity.anchors:
                    for evidence in anchor.evidence_rows:
                        period_2_artifacts.add(evidence.artifact)
        
        # Calculate overlaps
        common_identities = period_1_identities.intersection(period_2_identities)
        common_artifacts = period_1_artifacts.intersection(period_2_artifacts)
        
        total_unique_identities = period_1_identities.union(period_2_identities)
        overlap_percentage = (len(common_identities) / len(total_unique_identities) * 100) if total_unique_identities else 0
        
        return {
            "common_identities": len(common_identities),
            "common_identity_ids": list(common_identities),
            "common_artifact_types": list(common_artifacts),
            "overlap_percentage": overlap_percentage,
            "period_1_unique": len(period_1_identities - period_2_identities),
            "period_2_unique": len(period_2_identities - period_1_identities)
        }
    
    def _analyze_trends(self, metrics_1: ComparisonMetrics, 
                       metrics_2: ComparisonMetrics) -> Dict[str, Any]:
        """Analyze trends between two periods."""
        # Activity change
        if metrics_2.total_evidence > 0:
            activity_change_pct = ((metrics_1.total_evidence - metrics_2.total_evidence) / metrics_2.total_evidence) * 100
        else:
            activity_change_pct = 100 if metrics_1.total_evidence > 0 else 0
        
        if activity_change_pct > 20:
            activity_change = f"Increased by {activity_change_pct:.1f}%"
        elif activity_change_pct < -20:
            activity_change = f"Decreased by {abs(activity_change_pct):.1f}%"
        else:
            activity_change = "Stable"
        
        # Identity growth
        if metrics_2.unique_identities > 0:
            identity_growth_pct = ((metrics_1.unique_identities - metrics_2.unique_identities) / metrics_2.unique_identities) * 100
        else:
            identity_growth_pct = 100 if metrics_1.unique_identities > 0 else 0
        
        if identity_growth_pct > 10:
            identity_growth = f"Increased by {identity_growth_pct:.1f}%"
        elif identity_growth_pct < -10:
            identity_growth = f"Decreased by {abs(identity_growth_pct):.1f}%"
        else:
            identity_growth = "Stable"
        
        # Dominant pattern
        if metrics_1.activity_density > metrics_2.activity_density * 1.5:
            dominant_pattern = "Intensifying activity"
        elif metrics_1.activity_density < metrics_2.activity_density * 0.5:
            dominant_pattern = "Declining activity"
        else:
            dominant_pattern = "Consistent activity"
        
        return {
            "activity_change": activity_change,
            "activity_change_percentage": activity_change_pct,
            "identity_growth": identity_growth,
            "identity_growth_percentage": identity_growth_pct,
            "dominant_pattern": dominant_pattern,
            "density_ratio": metrics_1.activity_density / max(metrics_2.activity_density, 0.1)
        }
    
    def _generate_recommendations(self, metrics_1: ComparisonMetrics, 
                                 metrics_2: ComparisonMetrics,
                                 overlap_analysis: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on analysis."""
        recommendations = []
        
        # Activity-based recommendations
        if metrics_1.total_evidence > metrics_2.total_evidence * 2:
            recommendations.append("High activity spike detected in recent period - investigate potential security incidents")
        elif metrics_1.total_evidence < metrics_2.total_evidence * 0.5:
            recommendations.append("Significant activity decrease - verify system functionality or investigate potential evasion")
        
        # Identity-based recommendations
        overlap_pct = overlap_analysis.get("overlap_percentage", 0)
        if overlap_pct < 20:
            recommendations.append("Low identity overlap suggests different user populations or system changes")
        elif overlap_pct > 80:
            recommendations.append("High identity overlap indicates consistent user base - focus on behavioral changes")
        
        # Artifact-based recommendations
        common_artifacts = overlap_analysis.get("common_artifact_types", [])
        if len(common_artifacts) < 3:
            recommendations.append("Few common artifact types - investigate system or monitoring changes")
        
        # Density-based recommendations
        if metrics_1.activity_density > metrics_2.activity_density * 3:
            recommendations.append("Activity density spike - consider implementing rate limiting or monitoring")
        
        # Default recommendation
        if not recommendations:
            recommendations.append("Activity patterns appear normal - continue regular monitoring")
        
        return recommendations
 


class ComparativeAnalysisWidget(QWidget):
    """
    Widget for performing comparative analysis between time periods.
    
    Features:
    - Period selection and comparison setup
    - Automated analysis with progress tracking
    - Results visualization and export
    - Integration with timeline and tree views
    """
    
    # Signals
    comparison_complete = pyqtSignal(object)  # ComparisonResult
    period_selected = pyqtSignal(object)  # TimePeriod
    analysis_started = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.anchor_time_groups: List[AnchorTimeGroup] = []
        self.current_periods: List[TimePeriod] = []
        self.current_result: Optional[ComparisonResult] = None
        self.analysis_worker: Optional[ComparativeAnalysisWorker] = None
        
        self._init_ui()
        self._setup_connections()
    
    def _init_ui(self):
        """Initialize UI components."""
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        
        # Period selection section
        periods_section = self._create_periods_section()
        layout.addWidget(periods_section)
        
        # Analysis controls
        controls_section = self._create_controls_section()
        layout.addWidget(controls_section)
        
        # Results display
        results_section = self._create_results_section()
        layout.addWidget(results_section)
    
    def _create_periods_section(self) -> QWidget:
        """Create period selection section."""
        section = QGroupBox("Time Periods")
        layout = QVBoxLayout(section)
        
        # Period 1
        period1_layout = QHBoxLayout()
        period1_layout.addWidget(QLabel("Period 1:"))
        
        self.period1_start = QDateTimeEdit()
        self.period1_start.setCalendarPopup(True)
        self.period1_start.setMaximumWidth(150)
        period1_layout.addWidget(self.period1_start)
        
        period1_layout.addWidget(QLabel("to"))
        
        self.period1_end = QDateTimeEdit()
        self.period1_end.setCalendarPopup(True)
        self.period1_end.setMaximumWidth(150)
        period1_layout.addWidget(self.period1_end)
        
        period1_layout.addStretch()
        layout.addLayout(period1_layout)
        
        # Period 2
        period2_layout = QHBoxLayout()
        period2_layout.addWidget(QLabel("Period 2:"))
        
        self.period2_start = QDateTimeEdit()
        self.period2_start.setCalendarPopup(True)
        self.period2_start.setMaximumWidth(150)
        period2_layout.addWidget(self.period2_start)
        
        period2_layout.addWidget(QLabel("to"))
        
        self.period2_end = QDateTimeEdit()
        self.period2_end.setCalendarPopup(True)
        self.period2_end.setMaximumWidth(150)
        period2_layout.addWidget(self.period2_end)
        
        period2_layout.addStretch()
        layout.addLayout(period2_layout)
        
        return section
    
    def _create_controls_section(self) -> QWidget:
        """Create analysis controls section."""
        section = QGroupBox("Analysis Controls")
        layout = QHBoxLayout(section)
        
        # Start analysis button
        self.start_analysis_btn = QPushButton("🔍 Start Analysis")
        self.start_analysis_btn.setMaximumWidth(120)
        self.start_analysis_btn.clicked.connect(self._start_analysis)
        layout.addWidget(self.start_analysis_btn)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Cancel button
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setMaximumWidth(80)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel_analysis)
        layout.addWidget(self.cancel_btn)
        
        layout.addStretch()
        
        return section
    
    def _create_results_section(self) -> QWidget:
        """Create results display section."""
        section = QGroupBox("Comparison Results")
        layout = QVBoxLayout(section)
        
        # Results text area
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setPlaceholderText("Analysis results will appear here...")
        layout.addWidget(self.results_text)
        
        # Export button
        export_layout = QHBoxLayout()
        export_layout.addStretch()
        
        export_btn = QPushButton("📊 Export Results")
        export_btn.setMaximumWidth(120)
        export_btn.clicked.connect(self._export_results)
        export_layout.addWidget(export_btn)
        
        layout.addLayout(export_layout)
        
        return section
    
    def _setup_connections(self):
        """Setup signal connections."""
        # Period selection changes
        self.period1_start.dateTimeChanged.connect(self._on_period_changed)
        self.period1_end.dateTimeChanged.connect(self._on_period_changed)
        self.period2_start.dateTimeChanged.connect(self._on_period_changed)
        self.period2_end.dateTimeChanged.connect(self._on_period_changed)
    
    def set_data(self, anchor_time_groups: List[AnchorTimeGroup]):
        """Set data for analysis."""
        self.anchor_time_groups = anchor_time_groups
        
        # Set default periods if data is available
        if anchor_time_groups:
            times = [group.anchor_time for group in anchor_time_groups]
            start_time = min(times)
            end_time = max(times)
            
            # Set Period 1 to second half of time range
            mid_time = start_time + (end_time - start_time) / 2
            self.period1_start.setDateTime(QDateTime.fromSecsSinceEpoch(int(mid_time.timestamp())))
            self.period1_end.setDateTime(QDateTime.fromSecsSinceEpoch(int(end_time.timestamp())))
            
            # Set Period 2 to first half of time range
            self.period2_start.setDateTime(QDateTime.fromSecsSinceEpoch(int(start_time.timestamp())))
            self.period2_end.setDateTime(QDateTime.fromSecsSinceEpoch(int(mid_time.timestamp())))
    
    def set_comparison_periods(self, period1: TimePeriod, period2: TimePeriod):
        """Set specific periods for comparison."""
        self.period1_start.setDateTime(QDateTime.fromSecsSinceEpoch(int(period1.start_time.timestamp())))
        self.period1_end.setDateTime(QDateTime.fromSecsSinceEpoch(int(period1.end_time.timestamp())))
        
        self.period2_start.setDateTime(QDateTime.fromSecsSinceEpoch(int(period2.start_time.timestamp())))
        self.period2_end.setDateTime(QDateTime.fromSecsSinceEpoch(int(period2.end_time.timestamp())))
    
    def start_comparison(self, anchor_time_groups: List[AnchorTimeGroup]):
        """Start comparison with provided data."""
        self.set_data(anchor_time_groups)
        self._start_analysis()
    
    def _on_period_changed(self):
        """Handle period selection change."""
        # Create TimePeriod objects and emit signal
        try:
            period1 = TimePeriod(
                "Period 1",
                self.period1_start.dateTime().toPyDateTime(),
                self.period1_end.dateTime().toPyDateTime(),
                QColor(100, 150, 255)
            )
            
            period2 = TimePeriod(
                "Period 2", 
                self.period2_start.dateTime().toPyDateTime(),
                self.period2_end.dateTime().toPyDateTime(),
                QColor(255, 150, 100)
            )
            
            self.current_periods = [period1, period2]
            
        except Exception as e:
            logger.warning(f"Error updating periods: {e}")
    
    def _start_analysis(self):
        """Start comparative analysis."""
        if not self.anchor_time_groups:
            self.results_text.setPlainText("No data available for analysis")
            return
        
        if not self.current_periods or len(self.current_periods) < 2:
            self._on_period_changed()  # Update periods
        
        if len(self.current_periods) < 2:
            self.results_text.setPlainText("Please select valid time periods for comparison")
            return
        
        # Show progress UI
        self.start_analysis_btn.setVisible(False)
        self.progress_bar.setVisible(True)
        self.cancel_btn.setVisible(True)
        self.progress_bar.setValue(0)
        
        # Start analysis worker
        self.analysis_worker = ComparativeAnalysisWorker(
            self.anchor_time_groups,
            self.current_periods[0],
            self.current_periods[1]
        )
        
        self.analysis_worker.analysis_complete.connect(self._on_analysis_complete)
        self.analysis_worker.progress_updated.connect(self._on_progress_updated)
        self.analysis_worker.start()
        
        self.analysis_started.emit()
    
    def _cancel_analysis(self):
        """Cancel ongoing analysis."""
        if self.analysis_worker and self.analysis_worker.isRunning():
            self.analysis_worker.terminate()
            self.analysis_worker.wait()
        
        self._reset_ui()
        self.results_text.setPlainText("Analysis cancelled")
    
    def _on_progress_updated(self, progress: int):
        """Handle progress update."""
        self.progress_bar.setValue(progress)
    
    def _on_analysis_complete(self, result: ComparisonResult):
        """Handle analysis completion."""
        self.current_result = result
        self._reset_ui()
        
        if result:
            self._display_results(result)
            self.comparison_complete.emit(result)
        else:
            self.results_text.setPlainText("Analysis failed - no results generated")
    
    def _reset_ui(self):
        """Reset UI to initial state."""
        self.start_analysis_btn.setVisible(True)
        self.progress_bar.setVisible(False)
        self.cancel_btn.setVisible(False)
        self.progress_bar.setValue(0)
    
    def _display_results(self, result: ComparisonResult):
        """Display comparison results."""
        text_parts = []
        
        # Header
        text_parts.append("=== COMPARATIVE ANALYSIS RESULTS ===\n")
        
        # Period summaries
        text_parts.append(f"📊 {result.period_1.period_name}:")
        text_parts.append(f"  • Identities: {result.period_1.total_identities}")
        text_parts.append(f"  • Evidence: {result.period_1.total_evidence}")
        text_parts.append(f"  • Activity Density: {result.period_1.activity_density:.2f} evidence/min")
        text_parts.append(f"  • Dominant Identity Type: {result.period_1.dominant_identity_type}")
        text_parts.append("")
        
        text_parts.append(f"📊 {result.period_2.period_name}:")
        text_parts.append(f"  • Identities: {result.period_2.total_identities}")
        text_parts.append(f"  • Evidence: {result.period_2.total_evidence}")
        text_parts.append(f"  • Activity Density: {result.period_2.activity_density:.2f} evidence/min")
        text_parts.append(f"  • Dominant Identity Type: {result.period_2.dominant_identity_type}")
        text_parts.append("")
        
        # Overlap analysis
        overlap = result.overlap_analysis
        text_parts.append("🔗 OVERLAP ANALYSIS:")
        text_parts.append(f"  • Common Identities: {overlap.get('common_identities', 0)}")
        text_parts.append(f"  • Common Artifacts: {len(overlap.get('common_artifact_types', []))}")
        text_parts.append(f"  • Overlap Percentage: {overlap.get('overlap_percentage', 0):.1f}%")
        text_parts.append("")
        
        # Trend analysis
        trends = result.trend_analysis
        text_parts.append("📈 TREND ANALYSIS:")
        text_parts.append(f"  • Activity Change: {trends.get('activity_change', 'N/A')}")
        text_parts.append(f"  • Identity Growth: {trends.get('identity_growth', 'N/A')}")
        text_parts.append(f"  • Dominant Pattern: {trends.get('dominant_pattern', 'N/A')}")
        text_parts.append("")
        
        # Recommendations
        if result.recommendations:
            text_parts.append("💡 RECOMMENDATIONS:")
            for i, rec in enumerate(result.recommendations, 1):
                text_parts.append(f"  {i}. {rec}")
        
        self.results_text.setPlainText("\n".join(text_parts))
    
    def _export_results(self):
        """Export comparison results."""
        if not self.current_result:
            self.results_text.setPlainText("No results to export")
            return
        
        from PyQt5.QtWidgets import QFileDialog
        import json
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Comparison Results",
            f"comparison_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if filename:
            try:
                # Convert result to exportable format
                export_data = {
                    "export_timestamp": datetime.now().isoformat(),
                    "period_1": {
                        "name": self.current_result.period_1.period_name,
                        "total_identities": self.current_result.period_1.total_identities,
                        "total_evidence": self.current_result.period_1.total_evidence,
                        "activity_density": self.current_result.period_1.activity_density,
                        "dominant_identity_type": self.current_result.period_1.dominant_identity_type,
                        "artifact_breakdown": self.current_result.period_1.artifact_breakdown,
                        "identity_type_breakdown": self.current_result.period_1.identity_type_breakdown
                    },
                    "period_2": {
                        "name": self.current_result.period_2.period_name,
                        "total_identities": self.current_result.period_2.total_identities,
                        "total_evidence": self.current_result.period_2.total_evidence,
                        "activity_density": self.current_result.period_2.activity_density,
                        "dominant_identity_type": self.current_result.period_2.dominant_identity_type,
                        "artifact_breakdown": self.current_result.period_2.artifact_breakdown,
                        "identity_type_breakdown": self.current_result.period_2.identity_type_breakdown
                    },
                    "overlap_analysis": self.current_result.overlap_analysis,
                    "trend_analysis": self.current_result.trend_analysis,
                    "recommendations": self.current_result.recommendations
                }
                
                with open(filename, 'w') as f:
                    json.dump(export_data, f, indent=2, default=str)
                
                self.results_text.append(f"\n✅ Results exported to: {filename}")
                
            except Exception as e:
                self.results_text.append(f"\n❌ Export failed: {str(e)}")