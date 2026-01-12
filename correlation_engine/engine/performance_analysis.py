"""
Performance Analysis Module for Time-Window Scanning Engine

Provides advanced performance analysis, metrics collection, and comparison
capabilities to validate O(N) performance and provide detailed insights.
"""

import time
import statistics
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from .performance_monitor import PerformanceMonitor, PerformanceReport, PerformanceComparison


@dataclass
class ComplexityAnalysis:
    """Analysis of algorithm complexity based on performance data."""
    dataset_sizes: List[int] = field(default_factory=list)
    execution_times: List[float] = field(default_factory=list)
    memory_usage: List[float] = field(default_factory=list)
    
    # Calculated metrics
    time_complexity_factor: Optional[float] = None
    memory_complexity_factor: Optional[float] = None
    is_linear_time: bool = False
    is_constant_memory_per_window: bool = False
    
    def analyze_complexity(self):
        """Analyze time and memory complexity from collected data."""
        if len(self.dataset_sizes) < 2:
            return
        
        # Calculate time complexity factor (should be ~1.0 for O(N))
        time_ratios = []
        for i in range(1, len(self.dataset_sizes)):
            size_ratio = self.dataset_sizes[i] / self.dataset_sizes[i-1]
            time_ratio = self.execution_times[i] / self.execution_times[i-1]
            if size_ratio > 1.1:  # Only consider significant size increases
                time_ratios.append(time_ratio / size_ratio)
        
        if time_ratios:
            self.time_complexity_factor = statistics.mean(time_ratios)
            # Linear time if factor is close to 1.0 (within 50% tolerance)
            self.is_linear_time = 0.5 <= self.time_complexity_factor <= 2.0
        
        # Analyze memory usage per record
        memory_per_record = [mem / size for mem, size in zip(self.memory_usage, self.dataset_sizes)]
        if len(memory_per_record) > 1:
            memory_variance = statistics.variance(memory_per_record)
            memory_mean = statistics.mean(memory_per_record)
            # Constant memory if variance is low relative to mean
            self.is_constant_memory_per_window = (memory_variance / memory_mean) < 0.3


@dataclass
class PhasePerformanceAnalysis:
    """Detailed analysis of individual processing phases."""
    phase_name: str
    total_duration: float = 0.0
    call_count: int = 0
    records_processed: int = 0
    operations_performed: int = 0
    memory_delta: float = 0.0
    error_count: int = 0
    
    # Calculated metrics
    average_duration: float = 0.0
    records_per_second: float = 0.0
    operations_per_second: float = 0.0
    percentage_of_total: float = 0.0
    efficiency_score: float = 0.0
    
    def calculate_metrics(self, total_execution_time: float):
        """Calculate derived performance metrics."""
        if self.call_count > 0:
            self.average_duration = self.total_duration / self.call_count
        
        if self.total_duration > 0:
            self.records_per_second = self.records_processed / self.total_duration
            self.operations_per_second = self.operations_performed / self.total_duration
        
        if total_execution_time > 0:
            self.percentage_of_total = (self.total_duration / total_execution_time) * 100
        
        # Efficiency score based on records processed per second and low error rate
        if self.records_per_second > 0:
            error_penalty = max(0, 1 - (self.error_count / max(self.records_processed, 1)))
            self.efficiency_score = self.records_per_second * error_penalty


class AdvancedPerformanceAnalyzer:
    """
    Advanced performance analyzer for Time-Window Scanning Engine.
    
    Provides detailed analysis capabilities including:
    - Algorithm complexity validation
    - Phase-by-phase performance breakdown
    - Memory efficiency analysis
    - Performance trend analysis
    - Bottleneck identification
    """
    
    def __init__(self):
        self.performance_history: List[PerformanceReport] = []
        self.complexity_data = ComplexityAnalysis()
        self.phase_analysis: Dict[str, PhasePerformanceAnalysis] = {}
        
    def add_performance_report(self, report: PerformanceReport):
        """Add a performance report for analysis."""
        self.performance_history.append(report)
        
        # Update complexity analysis data
        if report.total_records_processed > 0:
            self.complexity_data.dataset_sizes.append(report.total_records_processed)
            self.complexity_data.execution_times.append(report.total_duration_seconds or 0)
            self.complexity_data.memory_usage.append(report.peak_memory_mb)
        
        # Update phase analysis
        for phase, metrics in report.phase_metrics.items():
            phase_name = phase.value
            if phase_name not in self.phase_analysis:
                self.phase_analysis[phase_name] = PhasePerformanceAnalysis(phase_name)
            
            phase_analysis = self.phase_analysis[phase_name]
            phase_analysis.total_duration += metrics.duration_seconds or 0
            phase_analysis.call_count += 1
            phase_analysis.records_processed += metrics.records_processed
            phase_analysis.operations_performed += metrics.operations_count
            phase_analysis.memory_delta += metrics.memory_delta_mb or 0
            phase_analysis.error_count += metrics.error_count
    
    def analyze_algorithm_complexity(self) -> Dict[str, Any]:
        """
        Analyze algorithm complexity to validate O(N) performance.
        
        Returns:
            Dictionary with complexity analysis results
        """
        self.complexity_data.analyze_complexity()
        
        return {
            'time_complexity': {
                'is_linear': self.complexity_data.is_linear_time,
                'complexity_factor': self.complexity_data.time_complexity_factor,
                'analysis': self._get_time_complexity_analysis()
            },
            'memory_complexity': {
                'is_constant_per_window': self.complexity_data.is_constant_memory_per_window,
                'analysis': self._get_memory_complexity_analysis()
            },
            'dataset_analysis': {
                'samples_analyzed': len(self.complexity_data.dataset_sizes),
                'size_range': {
                    'min_records': min(self.complexity_data.dataset_sizes) if self.complexity_data.dataset_sizes else 0,
                    'max_records': max(self.complexity_data.dataset_sizes) if self.complexity_data.dataset_sizes else 0
                },
                'performance_trend': self._analyze_performance_trend()
            }
        }
    
    def analyze_phase_performance(self) -> Dict[str, Any]:
        """
        Analyze performance of individual processing phases.
        
        Returns:
            Dictionary with phase performance analysis
        """
        if not self.performance_history:
            return {}
        
        # Calculate total execution time across all reports
        total_execution_time = sum(report.total_duration_seconds or 0 for report in self.performance_history)
        
        # Calculate metrics for each phase
        for phase_analysis in self.phase_analysis.values():
            phase_analysis.calculate_metrics(total_execution_time)
        
        # Identify bottlenecks
        bottlenecks = self._identify_bottlenecks()
        
        # Create phase breakdown
        phase_breakdown = {}
        for phase_name, analysis in self.phase_analysis.items():
            phase_breakdown[phase_name] = {
                'total_duration_seconds': analysis.total_duration,
                'average_duration_seconds': analysis.average_duration,
                'call_count': analysis.call_count,
                'records_processed': analysis.records_processed,
                'records_per_second': analysis.records_per_second,
                'operations_per_second': analysis.operations_per_second,
                'percentage_of_total_time': analysis.percentage_of_total,
                'efficiency_score': analysis.efficiency_score,
                'memory_delta_mb': analysis.memory_delta,
                'error_count': analysis.error_count,
                'is_bottleneck': phase_name in bottlenecks
            }
        
        return {
            'phase_breakdown': phase_breakdown,
            'bottlenecks': bottlenecks,
            'performance_summary': self._get_phase_performance_summary(),
            'optimization_recommendations': self._get_optimization_recommendations()
        }
    
    def compare_with_anchor_engine(self, anchor_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compare time-window scanning performance with anchor-based engine.
        
        Args:
            anchor_metrics: Performance metrics from anchor-based engine
            
        Returns:
            Detailed comparison analysis
        """
        if not self.performance_history:
            return {'error': 'No performance data available for comparison'}
        
        # Use the most recent performance report
        latest_report = self.performance_history[-1]
        
        comparison = {
            'time_window_engine': {
                'execution_time_seconds': latest_report.total_duration_seconds,
                'memory_peak_mb': latest_report.peak_memory_mb,
                'records_processed': latest_report.total_records_processed,
                'matches_found': latest_report.total_matches_found,
                'windows_processed': latest_report.total_windows_processed,
                'records_per_second': latest_report.records_per_second,
                'memory_efficiency_mb_per_1k_records': latest_report.memory_efficiency_mb_per_1k_records
            },
            'anchor_based_engine': anchor_metrics,
            'improvements': {},
            'analysis': {}
        }
        
        # Calculate improvements
        if anchor_metrics.get('execution_time_seconds', 0) > 0:
            speed_improvement = anchor_metrics['execution_time_seconds'] / (latest_report.total_duration_seconds or 1)
            comparison['improvements']['speed_improvement'] = speed_improvement
            comparison['analysis']['speed'] = self._analyze_speed_improvement(speed_improvement)
        
        if anchor_metrics.get('memory_peak_mb', 0) > 0:
            memory_improvement = anchor_metrics['memory_peak_mb'] / latest_report.peak_memory_mb
            comparison['improvements']['memory_improvement'] = memory_improvement
            comparison['analysis']['memory'] = self._analyze_memory_improvement(memory_improvement)
        
        # Scalability comparison
        comparison['scalability_analysis'] = self._analyze_scalability_comparison(anchor_metrics)
        
        return comparison
    
    def generate_performance_insights(self) -> Dict[str, Any]:
        """
        Generate comprehensive performance insights and recommendations.
        
        Returns:
            Dictionary with performance insights
        """
        insights = {
            'overall_performance': self._assess_overall_performance(),
            'complexity_validation': self.analyze_algorithm_complexity(),
            'phase_analysis': self.analyze_phase_performance(),
            'memory_analysis': self._analyze_memory_patterns(),
            'scalability_assessment': self._assess_scalability(),
            'recommendations': self._generate_recommendations()
        }
        
        return insights
    
    def _get_time_complexity_analysis(self) -> str:
        """Get human-readable time complexity analysis."""
        if self.complexity_data.time_complexity_factor is None:
            return "Insufficient data for complexity analysis"
        
        factor = self.complexity_data.time_complexity_factor
        if self.complexity_data.is_linear_time:
            return f"Algorithm demonstrates O(N) linear time complexity (factor: {factor:.2f})"
        elif factor < 0.5:
            return f"Algorithm is better than linear time (factor: {factor:.2f})"
        elif factor > 2.0:
            return f"Algorithm may be worse than linear time (factor: {factor:.2f})"
        else:
            return f"Algorithm shows near-linear performance (factor: {factor:.2f})"
    
    def _get_memory_complexity_analysis(self) -> str:
        """Get human-readable memory complexity analysis."""
        if self.complexity_data.is_constant_memory_per_window:
            return "Memory usage is constant per time window, demonstrating efficient memory management"
        else:
            return "Memory usage varies with dataset size, may indicate memory inefficiencies"
    
    def _analyze_performance_trend(self) -> str:
        """Analyze performance trend across different dataset sizes."""
        if len(self.complexity_data.execution_times) < 3:
            return "Insufficient data for trend analysis"
        
        # Calculate if performance is improving, degrading, or stable
        recent_times = self.complexity_data.execution_times[-3:]
        recent_sizes = self.complexity_data.dataset_sizes[-3:]
        
        # Normalize times by dataset size
        normalized_times = [t/s for t, s in zip(recent_times, recent_sizes)]
        
        if len(set(normalized_times)) == 1:
            return "Stable performance across dataset sizes"
        elif normalized_times[-1] < normalized_times[0]:
            return "Performance improving with larger datasets"
        else:
            return "Performance degrading with larger datasets"
    
    def _identify_bottlenecks(self) -> List[str]:
        """Identify performance bottlenecks in processing phases."""
        bottlenecks = []
        
        if not self.phase_analysis:
            return bottlenecks
        
        # Find phases that take more than 20% of total time
        for phase_name, analysis in self.phase_analysis.items():
            if analysis.percentage_of_total > 20:
                bottlenecks.append(phase_name)
        
        # Find phases with low efficiency scores
        efficiency_scores = [analysis.efficiency_score for analysis in self.phase_analysis.values()]
        if efficiency_scores:
            avg_efficiency = statistics.mean(efficiency_scores)
            for phase_name, analysis in self.phase_analysis.items():
                if analysis.efficiency_score < avg_efficiency * 0.5:
                    if phase_name not in bottlenecks:
                        bottlenecks.append(phase_name)
        
        return bottlenecks
    
    def _get_phase_performance_summary(self) -> Dict[str, Any]:
        """Get summary of phase performance."""
        if not self.phase_analysis:
            return {}
        
        total_records = sum(analysis.records_processed for analysis in self.phase_analysis.values())
        total_operations = sum(analysis.operations_performed for analysis in self.phase_analysis.values())
        total_errors = sum(analysis.error_count for analysis in self.phase_analysis.values())
        
        return {
            'total_phases_analyzed': len(self.phase_analysis),
            'total_records_processed': total_records,
            'total_operations_performed': total_operations,
            'total_errors': total_errors,
            'error_rate': (total_errors / max(total_records, 1)) * 100,
            'most_time_consuming_phase': max(self.phase_analysis.items(), 
                                           key=lambda x: x[1].total_duration)[0] if self.phase_analysis else None,
            'most_efficient_phase': max(self.phase_analysis.items(), 
                                      key=lambda x: x[1].efficiency_score)[0] if self.phase_analysis else None
        }
    
    def _get_optimization_recommendations(self) -> List[str]:
        """Generate optimization recommendations based on analysis."""
        recommendations = []
        
        bottlenecks = self._identify_bottlenecks()
        if bottlenecks:
            recommendations.append(f"Focus optimization efforts on bottleneck phases: {', '.join(bottlenecks)}")
        
        # Check for high error rates
        for phase_name, analysis in self.phase_analysis.items():
            if analysis.records_processed > 0:
                error_rate = (analysis.error_count / analysis.records_processed) * 100
                if error_rate > 5:
                    recommendations.append(f"Investigate high error rate in {phase_name} phase ({error_rate:.1f}%)")
        
        # Check memory efficiency
        if not self.complexity_data.is_constant_memory_per_window:
            recommendations.append("Consider implementing memory pooling or streaming for better memory efficiency")
        
        return recommendations
    
    def _analyze_speed_improvement(self, speed_factor: float) -> str:
        """Analyze speed improvement factor."""
        if speed_factor > 10:
            return f"Dramatic speed improvement: {speed_factor:.1f}x faster than anchor-based engine"
        elif speed_factor > 5:
            return f"Significant speed improvement: {speed_factor:.1f}x faster than anchor-based engine"
        elif speed_factor > 2:
            return f"Notable speed improvement: {speed_factor:.1f}x faster than anchor-based engine"
        elif speed_factor > 1.2:
            return f"Moderate speed improvement: {speed_factor:.1f}x faster than anchor-based engine"
        elif speed_factor > 0.8:
            return f"Similar performance: {speed_factor:.1f}x compared to anchor-based engine"
        else:
            return f"Slower performance: {1/speed_factor:.1f}x slower than anchor-based engine"
    
    def _analyze_memory_improvement(self, memory_factor: float) -> str:
        """Analyze memory improvement factor."""
        if memory_factor > 5:
            return f"Dramatic memory efficiency: {memory_factor:.1f}x less memory than anchor-based engine"
        elif memory_factor > 2:
            return f"Significant memory efficiency: {memory_factor:.1f}x less memory than anchor-based engine"
        elif memory_factor > 1.2:
            return f"Better memory efficiency: {memory_factor:.1f}x less memory than anchor-based engine"
        elif memory_factor > 0.8:
            return f"Similar memory usage: {memory_factor:.1f}x compared to anchor-based engine"
        else:
            return f"Higher memory usage: {1/memory_factor:.1f}x more memory than anchor-based engine"
    
    def _analyze_scalability_comparison(self, anchor_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze scalability comparison between engines."""
        return {
            'time_window_advantages': [
                "O(N) time complexity scales linearly with dataset size",
                "Constant memory usage per time window",
                "Parallel processing capabilities",
                "Efficient timestamp indexing"
            ],
            'anchor_based_limitations': [
                "O(N²) time complexity for large datasets",
                "Memory usage grows with dataset size",
                "Sequential processing bottlenecks",
                "Inefficient for sparse temporal data"
            ],
            'scalability_verdict': "Time-window scanning engine provides superior scalability for large datasets"
        }
    
    def _assess_overall_performance(self) -> Dict[str, Any]:
        """Assess overall performance of the engine."""
        if not self.performance_history:
            return {}
        
        latest_report = self.performance_history[-1]
        
        # Performance rating based on multiple factors
        performance_score = 0
        factors = []
        
        # Speed factor (records per second)
        if latest_report.records_per_second > 10000:
            performance_score += 25
            factors.append("Excellent processing speed")
        elif latest_report.records_per_second > 5000:
            performance_score += 20
            factors.append("Good processing speed")
        elif latest_report.records_per_second > 1000:
            performance_score += 15
            factors.append("Moderate processing speed")
        else:
            performance_score += 10
            factors.append("Slow processing speed")
        
        # Memory efficiency factor
        if latest_report.memory_efficiency_mb_per_1k_records < 10:
            performance_score += 25
            factors.append("Excellent memory efficiency")
        elif latest_report.memory_efficiency_mb_per_1k_records < 50:
            performance_score += 20
            factors.append("Good memory efficiency")
        else:
            performance_score += 10
            factors.append("Poor memory efficiency")
        
        # Error rate factor
        error_rate = (latest_report.error_count / max(latest_report.total_records_processed, 1)) * 100
        if error_rate < 1:
            performance_score += 25
            factors.append("Very low error rate")
        elif error_rate < 5:
            performance_score += 20
            factors.append("Low error rate")
        else:
            performance_score += 10
            factors.append("High error rate")
        
        # Complexity validation factor
        if self.complexity_data.is_linear_time:
            performance_score += 25
            factors.append("Validated O(N) time complexity")
        else:
            performance_score += 10
            factors.append("Time complexity not validated as O(N)")
        
        # Determine overall rating
        if performance_score >= 90:
            rating = "Excellent"
        elif performance_score >= 75:
            rating = "Good"
        elif performance_score >= 60:
            rating = "Fair"
        else:
            rating = "Poor"
        
        return {
            'overall_rating': rating,
            'performance_score': performance_score,
            'contributing_factors': factors,
            'key_metrics': {
                'records_per_second': latest_report.records_per_second,
                'memory_efficiency_mb_per_1k_records': latest_report.memory_efficiency_mb_per_1k_records,
                'error_rate_percent': error_rate,
                'windows_per_second': latest_report.windows_per_second
            }
        }
    
    def _analyze_memory_patterns(self) -> Dict[str, Any]:
        """Analyze memory usage patterns."""
        if not self.performance_history:
            return {}
        
        memory_peaks = [report.peak_memory_mb for report in self.performance_history]
        memory_baselines = [report.baseline_memory_mb for report in self.performance_history]
        
        return {
            'memory_growth_pattern': self._analyze_memory_growth(),
            'peak_memory_statistics': {
                'min_peak_mb': min(memory_peaks),
                'max_peak_mb': max(memory_peaks),
                'average_peak_mb': statistics.mean(memory_peaks),
                'memory_variance': statistics.variance(memory_peaks) if len(memory_peaks) > 1 else 0
            },
            'memory_efficiency_trend': self._analyze_memory_efficiency_trend(),
            'memory_recommendations': self._get_memory_recommendations()
        }
    
    def _analyze_memory_growth(self) -> str:
        """Analyze memory growth pattern."""
        if len(self.performance_history) < 2:
            return "Insufficient data for memory growth analysis"
        
        memory_deltas = []
        for i in range(1, len(self.performance_history)):
            prev_peak = self.performance_history[i-1].peak_memory_mb
            curr_peak = self.performance_history[i].peak_memory_mb
            memory_deltas.append(curr_peak - prev_peak)
        
        avg_delta = statistics.mean(memory_deltas)
        if abs(avg_delta) < 5:
            return "Stable memory usage across executions"
        elif avg_delta > 0:
            return f"Memory usage increasing by average {avg_delta:.1f}MB per execution"
        else:
            return f"Memory usage decreasing by average {abs(avg_delta):.1f}MB per execution"
    
    def _analyze_memory_efficiency_trend(self) -> str:
        """Analyze memory efficiency trend."""
        if len(self.performance_history) < 2:
            return "Insufficient data for efficiency trend analysis"
        
        efficiency_values = [report.memory_efficiency_mb_per_1k_records for report in self.performance_history]
        
        if efficiency_values[-1] < efficiency_values[0]:
            return "Memory efficiency improving over time"
        elif efficiency_values[-1] > efficiency_values[0]:
            return "Memory efficiency degrading over time"
        else:
            return "Memory efficiency remains stable"
    
    def _get_memory_recommendations(self) -> List[str]:
        """Get memory optimization recommendations."""
        recommendations = []
        
        if not self.performance_history:
            return recommendations
        
        latest_report = self.performance_history[-1]
        
        if latest_report.memory_efficiency_mb_per_1k_records > 100:
            recommendations.append("Consider implementing memory pooling to reduce per-record memory overhead")
        
        if latest_report.peak_memory_mb > latest_report.baseline_memory_mb * 5:
            recommendations.append("High memory usage detected - consider streaming mode for large datasets")
        
        if not self.complexity_data.is_constant_memory_per_window:
            recommendations.append("Implement fixed-size memory windows to achieve constant memory usage per window")
        
        return recommendations
    
    def _assess_scalability(self) -> Dict[str, Any]:
        """Assess scalability characteristics."""
        return {
            'time_complexity_assessment': {
                'is_linear': self.complexity_data.is_linear_time,
                'scalability_rating': "Excellent" if self.complexity_data.is_linear_time else "Poor",
                'large_dataset_suitability': "Highly suitable" if self.complexity_data.is_linear_time else "Not suitable"
            },
            'memory_scalability': {
                'is_constant_per_window': self.complexity_data.is_constant_memory_per_window,
                'memory_scalability_rating': "Excellent" if self.complexity_data.is_constant_memory_per_window else "Fair",
                'streaming_capability': "Supported" if self.complexity_data.is_constant_memory_per_window else "Required for large datasets"
            },
            'parallel_processing_benefits': [
                "Multiple time windows can be processed simultaneously",
                "Independent window processing enables horizontal scaling",
                "Memory isolation between parallel workers"
            ]
        }
    
    def _generate_recommendations(self) -> List[str]:
        """Generate comprehensive optimization recommendations."""
        recommendations = []
        
        # Add complexity-based recommendations
        if not self.complexity_data.is_linear_time:
            recommendations.append("Investigate algorithm implementation to ensure O(N) time complexity")
        
        # Add phase-based recommendations
        recommendations.extend(self._get_optimization_recommendations())
        
        # Add memory-based recommendations
        recommendations.extend(self._get_memory_recommendations())
        
        # Add general recommendations
        if self.performance_history:
            latest_report = self.performance_history[-1]
            if latest_report.windows_per_second < 10:
                recommendations.append("Consider increasing parallel processing workers to improve window throughput")
            
            if latest_report.error_count > 0:
                recommendations.append("Implement better error handling and recovery mechanisms")
        
        return list(set(recommendations))  # Remove duplicates
    
    def analyze_performance_report(self, report: PerformanceReport) -> Dict[str, Any]:
        """
        Analyze a single performance report and return detailed analysis.
        
        Args:
            report: PerformanceReport object to analyze
            
        Returns:
            Dictionary with detailed performance analysis
        """
        if not report:
            return {'error': 'No performance report provided'}
        
        # Add report to history for analysis
        self.add_performance_report(report)
        
        # Generate comprehensive analysis
        return {
            'summary': {
                'engine_name': report.engine_name,
                'execution_time_seconds': report.total_duration_seconds,
                'records_processed': report.total_records_processed,
                'windows_processed': report.total_windows_processed,
                'matches_found': report.total_matches_found,
                'error_count': report.error_count
            },
            'performance_rates': {
                'records_per_second': report.records_per_second,
                'windows_per_second': report.windows_per_second,
                'matches_per_second': report.matches_per_second
            },
            'memory_metrics': {
                'baseline_mb': report.baseline_memory_mb,
                'peak_mb': report.peak_memory_mb,
                'average_mb': report.average_memory_mb,
                'efficiency_mb_per_1k_records': report.memory_efficiency_mb_per_1k_records
            },
            'phase_breakdown': {
                phase.value: {
                    'duration_seconds': metrics.duration_seconds,
                    'records_processed': metrics.records_processed,
                    'error_count': metrics.error_count
                }
                for phase, metrics in report.phase_metrics.items()
                if metrics.duration_seconds is not None
            },
            'overall_assessment': self._assess_overall_performance(),
            'recommendations': self._generate_recommendations()
        }


def create_performance_analyzer() -> AdvancedPerformanceAnalyzer:
    """Create a new advanced performance analyzer instance."""
    return AdvancedPerformanceAnalyzer()


def generate_performance_report_summary(report: PerformanceReport) -> str:
    """
    Generate a human-readable summary of a performance report.
    
    Args:
        report: PerformanceReport object from performance monitoring
        
    Returns:
        Formatted string summary of the performance report
    """
    if not report:
        return "No performance data available"
    
    lines = []
    lines.append(f"Engine: {report.engine_name}")
    lines.append(f"Execution Time: {report.total_duration_seconds or 0:.2f}s")
    lines.append(f"Records Processed: {report.total_records_processed:,}")
    lines.append(f"Windows Processed: {report.total_windows_processed:,}")
    lines.append(f"Matches Found: {report.total_matches_found:,}")
    
    if report.records_per_second > 0:
        lines.append(f"Processing Rate: {report.records_per_second:,.0f} records/sec")
    
    if report.windows_per_second > 0:
        lines.append(f"Window Rate: {report.windows_per_second:,.1f} windows/sec")
    
    lines.append(f"Peak Memory: {report.peak_memory_mb:.1f} MB")
    lines.append(f"Memory Efficiency: {report.memory_efficiency_mb_per_1k_records:.2f} MB/1k records")
    
    if report.error_count > 0:
        lines.append(f"Errors: {report.error_count}")
    
    return "\n".join(lines)
