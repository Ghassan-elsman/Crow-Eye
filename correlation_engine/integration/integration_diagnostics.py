"""
Integration Diagnostics Tool

Provides comprehensive diagnostic tools for troubleshooting integration issues
including health checks, performance analysis, and troubleshooting recommendations.
"""

import logging
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path
import traceback

from .integration_error_handler import IntegrationErrorHandler, IntegrationComponent
from .integration_monitor import IntegrationMonitor, DiagnosticResult, MonitoringLevel

logger = logging.getLogger(__name__)


@dataclass
class IntegrationHealthReport:
    """Comprehensive health report for integration components"""
    timestamp: datetime = field(default_factory=datetime.now)
    overall_status: str = "unknown"  # healthy, warning, error
    component_health: Dict[str, str] = field(default_factory=dict)
    diagnostic_results: List[DiagnosticResult] = field(default_factory=list)
    performance_summary: Dict[str, Any] = field(default_factory=dict)
    error_summary: Dict[str, Any] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    system_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TroubleshootingGuide:
    """Troubleshooting guide for specific issues"""
    issue_type: str
    symptoms: List[str]
    possible_causes: List[str]
    diagnostic_steps: List[str]
    solutions: List[str]
    prevention_tips: List[str]


class IntegrationDiagnostics:
    """
    Comprehensive diagnostics tool for integration components.
    
    Provides:
    - Health checks and status monitoring
    - Performance analysis and bottleneck detection
    - Error pattern analysis
    - Troubleshooting guides and recommendations
    - Integration testing and validation
    """
    
    def __init__(self, error_handler: IntegrationErrorHandler, monitor: IntegrationMonitor):
        """
        Initialize integration diagnostics.
        
        Args:
            error_handler: Integration error handler instance
            monitor: Integration monitor instance
        """
        self.error_handler = error_handler
        self.monitor = monitor
        
        # Troubleshooting guides
        self.troubleshooting_guides = self._initialize_troubleshooting_guides()
        
        logger.info("IntegrationDiagnostics initialized")
    
    def run_comprehensive_health_check(self) -> IntegrationHealthReport:
        """
        Run comprehensive health check on all integration components.
        
        Returns:
            IntegrationHealthReport with complete system status
        """
        logger.info("Running comprehensive integration health check...")
        
        report = IntegrationHealthReport()
        
        try:
            # Run diagnostic checks
            report.diagnostic_results = self.monitor.run_diagnostics()
            
            # Analyze component health
            report.component_health = self._analyze_component_health(report.diagnostic_results)
            
            # Determine overall status
            report.overall_status = self._determine_overall_status(report.diagnostic_results)
            
            # Get performance summary
            report.performance_summary = self.monitor.get_performance_summary(time_window_minutes=60)
            
            # Get error summary
            report.error_summary = self.error_handler.get_error_summary()
            
            # Generate recommendations
            report.recommendations = self._generate_health_recommendations(report)
            
            # Collect system information
            report.system_info = self._collect_system_info()
            
            logger.info(f"Health check completed - Overall status: {report.overall_status}")
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            report.overall_status = "error"
            report.recommendations.append(f"Health check failed with error: {str(e)}")
        
        return report
    
    def _analyze_component_health(self, diagnostic_results: List[DiagnosticResult]) -> Dict[str, str]:
        """Analyze health status of individual components"""
        component_health = {}
        
        # Group results by component
        component_results = {}
        for result in diagnostic_results:
            if result.component not in component_results:
                component_results[result.component] = []
            component_results[result.component].append(result)
        
        # Determine health status for each component
        for component, results in component_results.items():
            error_count = sum(1 for r in results if r.status == "error")
            warning_count = sum(1 for r in results if r.status == "warning")
            
            if error_count > 0:
                component_health[component] = "error"
            elif warning_count > 0:
                component_health[component] = "warning"
            else:
                component_health[component] = "healthy"
        
        return component_health
    
    def _determine_overall_status(self, diagnostic_results: List[DiagnosticResult]) -> str:
        """Determine overall system health status"""
        error_count = sum(1 for r in diagnostic_results if r.status == "error")
        warning_count = sum(1 for r in diagnostic_results if r.status == "warning")
        
        if error_count > 0:
            return "error"
        elif warning_count > 0:
            return "warning"
        else:
            return "healthy"
    
    def _generate_health_recommendations(self, report: IntegrationHealthReport) -> List[str]:
        """Generate recommendations based on health report"""
        recommendations = []
        
        # Component-specific recommendations
        for component, status in report.component_health.items():
            if status == "error":
                recommendations.append(f"Critical issues detected in {component} - immediate attention required")
            elif status == "warning":
                recommendations.append(f"Performance issues detected in {component} - monitoring recommended")
        
        # Performance-based recommendations
        perf_summary = report.performance_summary
        for component, data in perf_summary.get('components', {}).items():
            metrics = data.get('performance_metrics', {})
            
            # Check for slow operations
            avg_duration = metrics.get('avg_duration_ms', 0)
            if avg_duration > 5000:  # 5 seconds
                recommendations.append(f"Slow performance in {component}: average {avg_duration:.0f}ms - consider optimization")
            
            # Check for high memory usage
            avg_memory = metrics.get('avg_memory_delta_mb', 0)
            if avg_memory > 100:  # 100MB
                recommendations.append(f"High memory usage in {component}: average {avg_memory:.0f}MB - consider memory optimization")
            
            # Check for low success rate
            success_rate = metrics.get('success_rate', 1.0)
            if success_rate < 0.9:  # Less than 90%
                recommendations.append(f"Low success rate in {component}: {success_rate:.1%} - investigate error causes")
        
        # Error-based recommendations
        error_summary = report.error_summary
        total_errors = error_summary.get('total_errors', 0)
        if total_errors > 10:
            recommendations.append(f"High error count: {total_errors} errors - review error logs and configuration")
        
        # System-level recommendations
        system_info = report.system_info
        memory_percent = system_info.get('memory_percent', 0)
        if memory_percent > 80:
            recommendations.append(f"High system memory usage: {memory_percent:.1f}% - consider enabling streaming mode")
        
        return recommendations
    
    def _collect_system_info(self) -> Dict[str, Any]:
        """Collect system information"""
        try:
            import psutil
            
            memory = psutil.virtual_memory()
            cpu_percent = psutil.cpu_percent(interval=1)
            
            return {
                'memory_percent': memory.percent,
                'memory_used_gb': memory.used / (1024**3),
                'memory_available_gb': memory.available / (1024**3),
                'cpu_percent': cpu_percent,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            logger.warning(f"Failed to collect system info: {e}")
            return {'error': str(e)}
    
    def analyze_performance_bottlenecks(self, time_window_minutes: int = 60) -> Dict[str, Any]:
        """
        Analyze performance bottlenecks across integration components.
        
        Args:
            time_window_minutes: Time window for analysis
            
        Returns:
            Dictionary with bottleneck analysis
        """
        logger.info(f"Analyzing performance bottlenecks (last {time_window_minutes} minutes)...")
        
        analysis = {
            'time_window_minutes': time_window_minutes,
            'bottlenecks': [],
            'performance_summary': {},
            'recommendations': []
        }
        
        try:
            # Get performance summary
            perf_summary = self.monitor.get_performance_summary(time_window_minutes=time_window_minutes)
            analysis['performance_summary'] = perf_summary
            
            # Analyze each component for bottlenecks
            for component, data in perf_summary.get('components', {}).items():
                bottlenecks = self._identify_component_bottlenecks(component, data)
                analysis['bottlenecks'].extend(bottlenecks)
            
            # Generate recommendations
            analysis['recommendations'] = self._generate_performance_recommendations(analysis['bottlenecks'])
            
        except Exception as e:
            logger.error(f"Performance bottleneck analysis failed: {e}")
            analysis['error'] = str(e)
        
        return analysis
    
    def _identify_component_bottlenecks(self, component: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Identify bottlenecks in a specific component"""
        bottlenecks = []
        metrics = data.get('performance_metrics', {})
        stats = data.get('statistics', {})
        
        # Check execution time bottlenecks
        avg_duration = metrics.get('avg_duration_ms', 0)
        max_duration = metrics.get('max_duration_ms', 0)
        
        if avg_duration > 2000:  # 2 seconds
            bottlenecks.append({
                'type': 'slow_execution',
                'component': component,
                'severity': 'high' if avg_duration > 5000 else 'medium',
                'metric': 'average_duration_ms',
                'value': avg_duration,
                'description': f"Slow average execution time: {avg_duration:.0f}ms"
            })
        
        if max_duration > 10000:  # 10 seconds
            bottlenecks.append({
                'type': 'very_slow_execution',
                'component': component,
                'severity': 'critical',
                'metric': 'max_duration_ms',
                'value': max_duration,
                'description': f"Very slow maximum execution time: {max_duration:.0f}ms"
            })
        
        # Check memory usage bottlenecks
        avg_memory = metrics.get('avg_memory_delta_mb', 0)
        max_memory = metrics.get('max_memory_delta_mb', 0)
        
        if avg_memory > 50:  # 50MB
            bottlenecks.append({
                'type': 'high_memory_usage',
                'component': component,
                'severity': 'high' if avg_memory > 100 else 'medium',
                'metric': 'average_memory_delta_mb',
                'value': avg_memory,
                'description': f"High average memory usage: {avg_memory:.0f}MB"
            })
        
        # Check error rate bottlenecks
        success_rate = metrics.get('success_rate', 1.0)
        if success_rate < 0.95:  # Less than 95%
            bottlenecks.append({
                'type': 'low_success_rate',
                'component': component,
                'severity': 'high' if success_rate < 0.8 else 'medium',
                'metric': 'success_rate',
                'value': success_rate,
                'description': f"Low success rate: {success_rate:.1%}"
            })
        
        # Check operation frequency bottlenecks
        recent_ops = data.get('recent_operations', 0)
        total_ops = stats.get('total_operations', 0)
        
        if total_ops > 0 and recent_ops == 0:
            bottlenecks.append({
                'type': 'no_recent_activity',
                'component': component,
                'severity': 'medium',
                'metric': 'recent_operations',
                'value': recent_ops,
                'description': f"No recent activity in {component}"
            })
        
        return bottlenecks
    
    def _generate_performance_recommendations(self, bottlenecks: List[Dict[str, Any]]) -> List[str]:
        """Generate performance improvement recommendations"""
        recommendations = []
        
        # Group bottlenecks by type
        bottleneck_types = {}
        for bottleneck in bottlenecks:
            btype = bottleneck['type']
            if btype not in bottleneck_types:
                bottleneck_types[btype] = []
            bottleneck_types[btype].append(bottleneck)
        
        # Generate recommendations for each type
        for btype, items in bottleneck_types.items():
            if btype == 'slow_execution':
                components = [item['component'] for item in items]
                recommendations.append(f"Optimize execution performance in: {', '.join(components)}")
                recommendations.append("Consider caching frequently accessed data")
                recommendations.append("Review algorithm efficiency and data structures")
            
            elif btype == 'very_slow_execution':
                components = [item['component'] for item in items]
                recommendations.append(f"Critical performance issue in: {', '.join(components)}")
                recommendations.append("Immediate optimization required - consider parallel processing")
            
            elif btype == 'high_memory_usage':
                components = [item['component'] for item in items]
                recommendations.append(f"Reduce memory usage in: {', '.join(components)}")
                recommendations.append("Consider streaming processing for large datasets")
                recommendations.append("Review data structures and memory management")
            
            elif btype == 'low_success_rate':
                components = [item['component'] for item in items]
                recommendations.append(f"Improve reliability in: {', '.join(components)}")
                recommendations.append("Review error handling and input validation")
                recommendations.append("Check configuration and dependencies")
            
            elif btype == 'no_recent_activity':
                components = [item['component'] for item in items]
                recommendations.append(f"Verify integration is active in: {', '.join(components)}")
                recommendations.append("Check if components are properly connected")
        
        return recommendations
    
    def analyze_error_patterns(self, time_window_hours: int = 24) -> Dict[str, Any]:
        """
        Analyze error patterns to identify common issues.
        
        Args:
            time_window_hours: Time window for error analysis
            
        Returns:
            Dictionary with error pattern analysis
        """
        logger.info(f"Analyzing error patterns (last {time_window_hours} hours)...")
        
        analysis = {
            'time_window_hours': time_window_hours,
            'error_patterns': [],
            'common_errors': {},
            'error_trends': {},
            'recommendations': []
        }
        
        try:
            # Get recent errors
            cutoff_time = datetime.now() - timedelta(hours=time_window_hours)
            recent_errors = [error for error in self.error_handler.errors 
                           if error.timestamp > cutoff_time]
            
            if not recent_errors:
                analysis['message'] = "No errors found in the specified time window"
                return analysis
            
            # Analyze error patterns
            analysis['error_patterns'] = self._identify_error_patterns(recent_errors)
            analysis['common_errors'] = self._identify_common_errors(recent_errors)
            analysis['error_trends'] = self._analyze_error_trends(recent_errors)
            analysis['recommendations'] = self._generate_error_recommendations(analysis)
            
        except Exception as e:
            logger.error(f"Error pattern analysis failed: {e}")
            analysis['error'] = str(e)
        
        return analysis
    
    def _identify_error_patterns(self, errors: List) -> List[Dict[str, Any]]:
        """Identify patterns in error occurrences"""
        patterns = []
        
        # Group errors by component and error type
        error_groups = {}
        for error in errors:
            key = f"{error.component.value}_{error.error_type}"
            if key not in error_groups:
                error_groups[key] = []
            error_groups[key].append(error)
        
        # Identify patterns
        for key, group_errors in error_groups.items():
            if len(group_errors) >= 3:  # Pattern threshold
                component, error_type = key.split('_', 1)
                
                # Calculate time intervals between errors
                timestamps = [e.timestamp for e in group_errors]
                timestamps.sort()
                
                intervals = []
                for i in range(1, len(timestamps)):
                    interval = (timestamps[i] - timestamps[i-1]).total_seconds()
                    intervals.append(interval)
                
                avg_interval = sum(intervals) / len(intervals) if intervals else 0
                
                patterns.append({
                    'component': component,
                    'error_type': error_type,
                    'occurrences': len(group_errors),
                    'average_interval_seconds': avg_interval,
                    'first_occurrence': timestamps[0].isoformat(),
                    'last_occurrence': timestamps[-1].isoformat(),
                    'pattern_type': self._classify_error_pattern(avg_interval, len(group_errors))
                })
        
        return patterns
    
    def _classify_error_pattern(self, avg_interval: float, occurrences: int) -> str:
        """Classify error pattern type"""
        if avg_interval < 60:  # Less than 1 minute
            return "burst"
        elif avg_interval < 3600:  # Less than 1 hour
            return "frequent"
        elif occurrences > 10:
            return "recurring"
        else:
            return "sporadic"
    
    def _identify_common_errors(self, errors: List) -> Dict[str, Any]:
        """Identify most common error types"""
        error_counts = {}
        component_errors = {}
        
        for error in errors:
            # Count by error type
            error_type = error.error_type
            error_counts[error_type] = error_counts.get(error_type, 0) + 1
            
            # Count by component
            component = error.component.value
            if component not in component_errors:
                component_errors[component] = {}
            component_errors[component][error_type] = component_errors[component].get(error_type, 0) + 1
        
        # Sort by frequency
        sorted_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)
        
        return {
            'most_common_errors': sorted_errors[:10],  # Top 10
            'errors_by_component': component_errors,
            'total_unique_error_types': len(error_counts)
        }
    
    def _analyze_error_trends(self, errors: List) -> Dict[str, Any]:
        """Analyze error trends over time"""
        if not errors:
            return {}
        
        # Group errors by hour
        hourly_counts = {}
        for error in errors:
            hour_key = error.timestamp.strftime('%Y-%m-%d %H:00')
            hourly_counts[hour_key] = hourly_counts.get(hour_key, 0) + 1
        
        # Calculate trend
        hours = sorted(hourly_counts.keys())
        counts = [hourly_counts[hour] for hour in hours]
        
        if len(counts) >= 2:
            # Simple trend calculation
            first_half = counts[:len(counts)//2]
            second_half = counts[len(counts)//2:]
            
            avg_first = sum(first_half) / len(first_half)
            avg_second = sum(second_half) / len(second_half)
            
            trend = "increasing" if avg_second > avg_first else "decreasing" if avg_second < avg_first else "stable"
        else:
            trend = "insufficient_data"
        
        return {
            'hourly_error_counts': hourly_counts,
            'trend': trend,
            'peak_error_hour': max(hourly_counts.items(), key=lambda x: x[1]) if hourly_counts else None,
            'total_hours_with_errors': len(hourly_counts)
        }
    
    def _generate_error_recommendations(self, analysis: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on error analysis"""
        recommendations = []
        
        # Pattern-based recommendations
        for pattern in analysis.get('error_patterns', []):
            if pattern['pattern_type'] == 'burst':
                recommendations.append(f"Investigate burst errors in {pattern['component']}: {pattern['error_type']}")
            elif pattern['pattern_type'] == 'frequent':
                recommendations.append(f"Address frequent errors in {pattern['component']}: {pattern['error_type']}")
            elif pattern['pattern_type'] == 'recurring':
                recommendations.append(f"Fix recurring issue in {pattern['component']}: {pattern['error_type']}")
        
        # Common error recommendations
        common_errors = analysis.get('common_errors', {})
        most_common = common_errors.get('most_common_errors', [])
        
        if most_common:
            top_error = most_common[0]
            recommendations.append(f"Priority fix: {top_error[0]} ({top_error[1]} occurrences)")
        
        # Trend-based recommendations
        trends = analysis.get('error_trends', {})
        if trends.get('trend') == 'increasing':
            recommendations.append("Error rate is increasing - investigate root causes immediately")
        
        return recommendations
    
    def get_troubleshooting_guide(self, issue_type: str) -> Optional[TroubleshootingGuide]:
        """
        Get troubleshooting guide for a specific issue type.
        
        Args:
            issue_type: Type of issue to get guide for
            
        Returns:
            TroubleshootingGuide or None if not found
        """
        return self.troubleshooting_guides.get(issue_type)
    
    def _initialize_troubleshooting_guides(self) -> Dict[str, TroubleshootingGuide]:
        """Initialize troubleshooting guides"""
        guides = {}
        
        # Semantic mapping issues
        guides['semantic_mapping_failure'] = TroubleshootingGuide(
            issue_type='semantic_mapping_failure',
            symptoms=[
                "Raw technical values displayed instead of semantic meanings",
                "Semantic mapping errors in logs",
                "Missing semantic information in results"
            ],
            possible_causes=[
                "Semantic mapping configuration file missing or corrupted",
                "Invalid semantic mapping patterns",
                "SemanticMappingManager initialization failure",
                "Case-specific mapping conflicts"
            ],
            diagnostic_steps=[
                "Check if semantic mapping configuration files exist",
                "Validate semantic mapping JSON syntax",
                "Test SemanticMappingManager initialization",
                "Review semantic mapping patterns for validity",
                "Check case-specific vs global mapping conflicts"
            ],
            solutions=[
                "Restore semantic mapping configuration from backup",
                "Fix JSON syntax errors in mapping files",
                "Reinitialize SemanticMappingManager",
                "Update invalid mapping patterns",
                "Resolve case-specific mapping conflicts"
            ],
            prevention_tips=[
                "Regularly backup semantic mapping configurations",
                "Validate mapping files before deployment",
                "Use version control for mapping configurations",
                "Test mappings with sample data"
            ]
        )
        
        # Weighted scoring issues
        guides['weighted_scoring_failure'] = TroubleshootingGuide(
            issue_type='weighted_scoring_failure',
            symptoms=[
                "Simple count-based scoring used instead of weighted",
                "Scoring calculation errors in logs",
                "Incorrect or missing score interpretations"
            ],
            possible_causes=[
                "WeightedScoringEngine initialization failure",
                "Invalid scoring weights configuration",
                "Wing configuration validation errors",
                "Score interpretation threshold issues"
            ],
            diagnostic_steps=[
                "Check WeightedScoringEngine initialization",
                "Validate scoring weights configuration",
                "Test wing configuration validation",
                "Review score interpretation thresholds",
                "Check for division by zero or invalid calculations"
            ],
            solutions=[
                "Reinitialize WeightedScoringEngine",
                "Fix scoring weights configuration",
                "Correct wing configuration validation errors",
                "Update score interpretation thresholds",
                "Add input validation for scoring calculations"
            ],
            prevention_tips=[
                "Validate scoring configurations before use",
                "Use reasonable weight ranges (0.0-1.0)",
                "Test scoring with various input scenarios",
                "Monitor scoring statistics regularly"
            ]
        )
        
        # Progress tracking issues
        guides['progress_tracking_failure'] = TroubleshootingGuide(
            issue_type='progress_tracking_failure',
            symptoms=[
                "No progress updates displayed",
                "Progress tracking errors in logs",
                "GUI progress widgets not updating"
            ],
            possible_causes=[
                "ProgressTracker initialization failure",
                "GUI widget connection issues",
                "Progress listener registration problems",
                "Event emission failures"
            ],
            diagnostic_steps=[
                "Check ProgressTracker initialization",
                "Verify GUI widget connections",
                "Test progress listener registration",
                "Monitor progress event emission",
                "Check for threading issues"
            ],
            solutions=[
                "Reinitialize ProgressTracker",
                "Reconnect GUI widgets",
                "Re-register progress listeners",
                "Fix event emission problems",
                "Resolve threading conflicts"
            ],
            prevention_tips=[
                "Test progress tracking in isolation",
                "Use thread-safe progress updates",
                "Monitor progress listener health",
                "Implement progress tracking fallbacks"
            ]
        )
        
        # Performance issues
        guides['performance_degradation'] = TroubleshootingGuide(
            issue_type='performance_degradation',
            symptoms=[
                "Slow correlation execution",
                "High memory usage",
                "Long response times",
                "System resource exhaustion"
            ],
            possible_causes=[
                "Large dataset processing",
                "Inefficient algorithms",
                "Memory leaks",
                "Resource contention",
                "Configuration issues"
            ],
            diagnostic_steps=[
                "Monitor system resource usage",
                "Profile component performance",
                "Check for memory leaks",
                "Analyze algorithm efficiency",
                "Review configuration settings"
            ],
            solutions=[
                "Enable streaming mode for large datasets",
                "Optimize algorithms and data structures",
                "Fix memory leaks",
                "Reduce resource contention",
                "Tune configuration parameters"
            ],
            prevention_tips=[
                "Regular performance monitoring",
                "Use appropriate data structures",
                "Implement memory management best practices",
                "Test with realistic dataset sizes"
            ]
        )
        
        return guides
    
    def run_integration_tests(self) -> Dict[str, Any]:
        """
        Run integration tests to validate component interactions.
        
        Returns:
            Dictionary with test results
        """
        logger.info("Running integration tests...")
        
        test_results = {
            'timestamp': datetime.now().isoformat(),
            'tests': [],
            'overall_status': 'unknown',
            'passed': 0,
            'failed': 0,
            'warnings': 0
        }
        
        # Test semantic mapping integration
        test_results['tests'].append(self._test_semantic_mapping_integration())
        
        # Test weighted scoring integration
        test_results['tests'].append(self._test_weighted_scoring_integration())
        
        # Test progress tracking integration
        test_results['tests'].append(self._test_progress_tracking_integration())
        
        # Test error handling integration
        test_results['tests'].append(self._test_error_handling_integration())
        
        # Calculate overall results
        for test in test_results['tests']:
            if test['status'] == 'passed':
                test_results['passed'] += 1
            elif test['status'] == 'failed':
                test_results['failed'] += 1
            elif test['status'] == 'warning':
                test_results['warnings'] += 1
        
        # Determine overall status
        if test_results['failed'] > 0:
            test_results['overall_status'] = 'failed'
        elif test_results['warnings'] > 0:
            test_results['overall_status'] = 'warning'
        else:
            test_results['overall_status'] = 'passed'
        
        logger.info(f"Integration tests completed - Status: {test_results['overall_status']}")
        
        return test_results
    
    def _test_semantic_mapping_integration(self) -> Dict[str, Any]:
        """Test semantic mapping integration"""
        test_result = {
            'test_name': 'semantic_mapping_integration',
            'status': 'unknown',
            'message': '',
            'details': {}
        }
        
        try:
            # Test basic functionality
            from .semantic_mapping_integration import SemanticMappingIntegration
            
            integration = SemanticMappingIntegration()
            
            # Test with sample data
            test_records = [
                {'event_id': '4624', 'process_name': 'explorer.exe'},
                {'status_code': '200', 'file_path': 'C:\\Windows\\System32\\test.exe'}
            ]
            
            result = integration.apply_to_correlation_results(test_records)
            
            if len(result) == len(test_records):
                test_result['status'] = 'passed'
                test_result['message'] = 'Semantic mapping integration working correctly'
            else:
                test_result['status'] = 'warning'
                test_result['message'] = 'Semantic mapping returned unexpected result count'
            
            test_result['details']['input_records'] = len(test_records)
            test_result['details']['output_records'] = len(result)
            
        except Exception as e:
            test_result['status'] = 'failed'
            test_result['message'] = f'Semantic mapping integration test failed: {str(e)}'
            test_result['details']['error'] = str(e)
        
        return test_result
    
    def _test_weighted_scoring_integration(self) -> Dict[str, Any]:
        """Test weighted scoring integration"""
        test_result = {
            'test_name': 'weighted_scoring_integration',
            'status': 'unknown',
            'message': '',
            'details': {}
        }
        
        try:
            # Test basic functionality
            from .weighted_scoring_integration import WeightedScoringIntegration
            
            integration = WeightedScoringIntegration()
            
            # Create test data
            test_records = {'test_feather': {'test_field': 'test_value'}}
            
            # Create mock wing config
            class MockWingConfig:
                def __init__(self):
                    self.feathers = []
                    self.use_weighted_scoring = True
            
            wing_config = MockWingConfig()
            
            result = integration.calculate_match_scores(test_records, wing_config)
            
            if 'score' in result:
                test_result['status'] = 'passed'
                test_result['message'] = 'Weighted scoring integration working correctly'
            else:
                test_result['status'] = 'warning'
                test_result['message'] = 'Weighted scoring returned unexpected result format'
            
            test_result['details']['result_keys'] = list(result.keys())
            
        except Exception as e:
            test_result['status'] = 'failed'
            test_result['message'] = f'Weighted scoring integration test failed: {str(e)}'
            test_result['details']['error'] = str(e)
        
        return test_result
    
    def _test_progress_tracking_integration(self) -> Dict[str, Any]:
        """Test progress tracking integration"""
        test_result = {
            'test_name': 'progress_tracking_integration',
            'status': 'unknown',
            'message': '',
            'details': {}
        }
        
        try:
            # Test basic functionality
            from .progress_tracking_integration import ProgressTrackingIntegration
            
            integration = ProgressTrackingIntegration(enable_terminal_logging=False)
            
            # Test starting correlation tracking
            config = {
                'total_windows': 10,
                'window_size_minutes': 60,
                'time_range_start': datetime(2023, 1, 1),
                'time_range_end': datetime(2023, 1, 2)
            }
            
            integration.start_correlation_tracking('test_engine', config)
            
            # Test completion
            integration.complete_correlation()
            
            test_result['status'] = 'passed'
            test_result['message'] = 'Progress tracking integration working correctly'
            
        except Exception as e:
            test_result['status'] = 'failed'
            test_result['message'] = f'Progress tracking integration test failed: {str(e)}'
            test_result['details']['error'] = str(e)
        
        return test_result
    
    def _test_error_handling_integration(self) -> Dict[str, Any]:
        """Test error handling integration"""
        test_result = {
            'test_name': 'error_handling_integration',
            'status': 'unknown',
            'message': '',
            'details': {}
        }
        
        try:
            # Test error handler functionality
            error_handler = IntegrationErrorHandler()
            
            # Test semantic mapping error handling
            test_error = ValueError("Test error")
            fallback_result = error_handler.handle_semantic_mapping_error(test_error)
            
            if fallback_result.success:
                test_result['status'] = 'passed'
                test_result['message'] = 'Error handling integration working correctly'
            else:
                test_result['status'] = 'warning'
                test_result['message'] = 'Error handling fallback not successful'
            
            test_result['details']['fallback_strategy'] = fallback_result.strategy.value
            test_result['details']['fallback_message'] = fallback_result.message
            
        except Exception as e:
            test_result['status'] = 'failed'
            test_result['message'] = f'Error handling integration test failed: {str(e)}'
            test_result['details']['error'] = str(e)
        
        return test_result
    
    def export_diagnostic_report(self, file_path: Optional[Path] = None) -> str:
        """
        Export comprehensive diagnostic report.
        
        Args:
            file_path: Optional path to save report
            
        Returns:
            JSON string with diagnostic report
        """
        logger.info("Generating comprehensive diagnostic report...")
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'health_check': self.run_comprehensive_health_check(),
            'performance_analysis': self.analyze_performance_bottlenecks(),
            'error_analysis': self.analyze_error_patterns(),
            'integration_tests': self.run_integration_tests(),
            'system_info': self._collect_system_info()
        }
        
        # Convert dataclasses to dictionaries for JSON serialization
        report_json = self._serialize_report(report)
        
        if file_path:
            try:
                with open(file_path, 'w') as f:
                    f.write(report_json)
                logger.info(f"Diagnostic report exported to {file_path}")
            except Exception as e:
                logger.error(f"Failed to export diagnostic report: {e}")
        
        return report_json
    
    def _serialize_report(self, report: Dict[str, Any]) -> str:
        """Serialize report to JSON, handling dataclasses"""
        def serialize_obj(obj):
            if hasattr(obj, '__dict__'):
                return obj.__dict__
            elif isinstance(obj, datetime):
                return obj.isoformat()
            elif isinstance(obj, list):
                return [serialize_obj(item) for item in obj]
            elif isinstance(obj, dict):
                return {key: serialize_obj(value) for key, value in obj.items()}
            else:
                return obj
        
        serialized = serialize_obj(report)
        return json.dumps(serialized, indent=2, default=str)