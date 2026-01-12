"""
Performance Benchmarking Utility for Time-Window Scanning Engine

Provides comprehensive benchmarking capabilities to compare the Time-Window Scanning Engine
with anchor-based approaches and validate O(N) complexity performance.
"""

import time
import json
import statistics
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable, Tuple
from dataclasses import dataclass, field
from pathlib import Path

from .performance_monitor import create_performance_monitor, PerformanceComparison
from .performance_analysis import create_performance_analyzer, generate_performance_report_summary


@dataclass
class BenchmarkConfiguration:
    """Configuration for performance benchmarking."""
    
    # Test data configuration
    record_counts: List[int] = field(default_factory=lambda: [1000, 5000, 10000, 50000])
    window_sizes_minutes: List[int] = field(default_factory=lambda: [5, 15, 30, 60])
    feather_counts: List[int] = field(default_factory=lambda: [2, 5, 10])
    
    # Benchmark parameters
    iterations_per_test: int = 3
    warmup_iterations: int = 1
    timeout_seconds: int = 300
    
    # Output configuration
    export_detailed_results: bool = True
    export_path: Optional[str] = None


@dataclass
class BenchmarkResult:
    """Results from a single benchmark test."""
    
    engine_name: str
    configuration: Dict[str, Any]
    
    # Performance metrics
    execution_time_seconds: float
    memory_peak_mb: float
    records_processed: int
    matches_found: int
    windows_processed: int
    
    # Efficiency metrics
    records_per_second: float
    memory_per_1k_records_mb: float
    complexity_validation: bool
    
    # Error information
    success: bool = True
    error_message: Optional[str] = None


@dataclass
class ComparisonResult:
    """Results from comparing two engines."""
    
    time_window_result: BenchmarkResult
    anchor_based_result: BenchmarkResult
    
    # Improvement factors
    speed_improvement: float
    memory_improvement: float
    
    # Analysis
    complexity_advantage: bool
    scalability_advantage: bool
    overall_winner: str


class PerformanceBenchmark:
    """
    Comprehensive performance benchmarking system.
    
    Compares Time-Window Scanning Engine with anchor-based approaches
    across various data sizes and configurations.
    """
    
    def __init__(self, config: BenchmarkConfiguration = None):
        self.config = config or BenchmarkConfiguration()
        self.results: List[BenchmarkResult] = []
        self.comparisons: List[ComparisonResult] = []
    
    def run_comprehensive_benchmark(self, 
                                   time_window_engine_func: Callable,
                                   anchor_engine_func: Optional[Callable] = None) -> Dict[str, Any]:
        """
        Run comprehensive benchmark comparing engines across multiple configurations.
        
        Args:
            time_window_engine_func: Function that runs time-window engine
            anchor_engine_func: Function that runs anchor-based engine (optional)
            
        Returns:
            Dictionary with comprehensive benchmark results
        """
        
        print("Starting comprehensive performance benchmark...")
        print(f"Testing {len(self.config.record_counts)} record counts")
        print(f"Testing {len(self.config.window_sizes_minutes)} window sizes")
        print(f"Testing {len(self.config.feather_counts)} feather configurations")
        
        benchmark_results = {
            'benchmark_start': datetime.now().isoformat(),
            'configuration': self.config.__dict__,
            'time_window_results': [],
            'anchor_based_results': [],
            'comparisons': [],
            'summary': {}
        }
        
        # Test time-window engine across configurations
        for record_count in self.config.record_counts:
            for window_size in self.config.window_sizes_minutes:
                for feather_count in self.config.feather_counts:
                    
                    test_config = {
                        'record_count': record_count,
                        'window_size_minutes': window_size,
                        'feather_count': feather_count
                    }
                    
                    print(f"Testing Time-Window Engine: {record_count} records, "
                          f"{window_size}min windows, {feather_count} feathers")
                    
                    # Benchmark time-window engine
                    tw_result = self._benchmark_engine(
                        time_window_engine_func,
                        "TimeWindowScanningEngine",
                        test_config
                    )
                    benchmark_results['time_window_results'].append(tw_result.__dict__)
                    
                    # Benchmark anchor-based engine if provided
                    if anchor_engine_func:
                        print(f"Testing Anchor-Based Engine: {record_count} records, "
                              f"{feather_count} feathers")
                        
                        anchor_result = self._benchmark_engine(
                            anchor_engine_func,
                            "AnchorBasedEngine",
                            test_config
                        )
                        benchmark_results['anchor_based_results'].append(anchor_result.__dict__)
                        
                        # Compare results
                        comparison = self._compare_results(tw_result, anchor_result)
                        benchmark_results['comparisons'].append(comparison.__dict__)
        
        # Generate summary
        benchmark_results['summary'] = self._generate_benchmark_summary(benchmark_results)
        benchmark_results['benchmark_end'] = datetime.now().isoformat()
        
        # Export results if configured
        if self.config.export_detailed_results:
            self._export_benchmark_results(benchmark_results)
        
        return benchmark_results
    
    def _benchmark_engine(self, engine_func: Callable, engine_name: str, 
                         test_config: Dict[str, Any]) -> BenchmarkResult:
        """Benchmark a single engine with given configuration."""
        
        results = []
        
        # Run warmup iterations
        for _ in range(self.config.warmup_iterations):
            try:
                engine_func(test_config)
            except Exception:
                pass  # Ignore warmup errors
        
        # Run actual benchmark iterations
        for iteration in range(self.config.iterations_per_test):
            try:
                # Create performance monitor
                monitor = create_performance_monitor(engine_name, enable_detailed=True)
                
                # Start monitoring
                report = monitor.start_execution(test_config)
                
                # Run engine
                start_time = time.time()
                result = engine_func(test_config)
                end_time = time.time()
                
                # Complete monitoring
                final_report = monitor.complete_execution()
                
                # Create benchmark result
                benchmark_result = BenchmarkResult(
                    engine_name=engine_name,
                    configuration=test_config,
                    execution_time_seconds=end_time - start_time,
                    memory_peak_mb=final_report.peak_memory_mb,
                    records_processed=final_report.total_records_processed,
                    matches_found=final_report.total_matches_found,
                    windows_processed=final_report.total_windows_processed,
                    records_per_second=final_report.records_per_second,
                    memory_per_1k_records_mb=final_report.memory_efficiency_mb_per_1k_records,
                    complexity_validation=self._validate_complexity(final_report),
                    success=True
                )
                
                results.append(benchmark_result)
                
            except Exception as e:
                # Record failed benchmark
                benchmark_result = BenchmarkResult(
                    engine_name=engine_name,
                    configuration=test_config,
                    execution_time_seconds=0,
                    memory_peak_mb=0,
                    records_processed=0,
                    matches_found=0,
                    windows_processed=0,
                    records_per_second=0,
                    memory_per_1k_records_mb=0,
                    complexity_validation=False,
                    success=False,
                    error_message=str(e)
                )
                results.append(benchmark_result)
        
        # Return average of successful results
        successful_results = [r for r in results if r.success]
        if not successful_results:
            return results[0]  # Return failed result
        
        # Calculate averages
        avg_result = BenchmarkResult(
            engine_name=engine_name,
            configuration=test_config,
            execution_time_seconds=statistics.mean([r.execution_time_seconds for r in successful_results]),
            memory_peak_mb=statistics.mean([r.memory_peak_mb for r in successful_results]),
            records_processed=successful_results[0].records_processed,  # Should be same for all
            matches_found=int(statistics.mean([r.matches_found for r in successful_results])),
            windows_processed=successful_results[0].windows_processed,  # Should be same for all
            records_per_second=statistics.mean([r.records_per_second for r in successful_results]),
            memory_per_1k_records_mb=statistics.mean([r.memory_per_1k_records_mb for r in successful_results]),
            complexity_validation=all(r.complexity_validation for r in successful_results),
            success=True
        )
        
        return avg_result
    
    def _validate_complexity(self, report) -> bool:
        """Validate O(N) complexity from performance report."""
        
        # Simple validation: time per record should be reasonable for O(N)
        if report.total_records_processed > 0 and report.total_duration_seconds:
            time_per_record_ms = (report.total_duration_seconds * 1000) / report.total_records_processed
            return time_per_record_ms < 1.0  # Less than 1ms per record
        
        return False
    
    def _compare_results(self, tw_result: BenchmarkResult, 
                        anchor_result: BenchmarkResult) -> ComparisonResult:
        """Compare results between time-window and anchor-based engines."""
        
        # Calculate improvement factors
        speed_improvement = 1.0
        if anchor_result.execution_time_seconds > 0:
            speed_improvement = anchor_result.execution_time_seconds / max(tw_result.execution_time_seconds, 0.001)
        
        memory_improvement = 1.0
        if anchor_result.memory_peak_mb > 0:
            memory_improvement = anchor_result.memory_peak_mb / max(tw_result.memory_peak_mb, 0.001)
        
        # Analyze advantages
        complexity_advantage = tw_result.complexity_validation and not anchor_result.complexity_validation
        scalability_advantage = speed_improvement > 1.2  # At least 20% faster
        
        # Determine overall winner
        if speed_improvement > 1.2 and memory_improvement > 1.0:
            overall_winner = "TimeWindowScanningEngine"
        elif speed_improvement < 0.8 or memory_improvement < 0.8:
            overall_winner = "AnchorBasedEngine"
        else:
            overall_winner = "Tie"
        
        return ComparisonResult(
            time_window_result=tw_result,
            anchor_based_result=anchor_result,
            speed_improvement=speed_improvement,
            memory_improvement=memory_improvement,
            complexity_advantage=complexity_advantage,
            scalability_advantage=scalability_advantage,
            overall_winner=overall_winner
        )
    
    def _generate_benchmark_summary(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate summary of benchmark results."""
        
        tw_results = [BenchmarkResult(**r) for r in results['time_window_results'] if r['success']]
        anchor_results = [BenchmarkResult(**r) for r in results['anchor_based_results'] if r['success']]
        comparisons = [ComparisonResult(**c) for c in results['comparisons']]
        
        summary = {
            'total_tests': len(results['time_window_results']),
            'successful_tests': len(tw_results),
            'time_window_engine': {},
            'anchor_based_engine': {},
            'overall_comparison': {}
        }
        
        # Time-window engine summary
        if tw_results:
            summary['time_window_engine'] = {
                'avg_records_per_second': statistics.mean([r.records_per_second for r in tw_results]),
                'avg_memory_per_1k_records': statistics.mean([r.memory_per_1k_records_mb for r in tw_results]),
                'complexity_validation_rate': sum(r.complexity_validation for r in tw_results) / len(tw_results),
                'best_performance_records_per_sec': max([r.records_per_second for r in tw_results]),
                'most_memory_efficient_mb_per_1k': min([r.memory_per_1k_records_mb for r in tw_results])
            }
        
        # Anchor-based engine summary
        if anchor_results:
            summary['anchor_based_engine'] = {
                'avg_records_per_second': statistics.mean([r.records_per_second for r in anchor_results]),
                'avg_memory_per_1k_records': statistics.mean([r.memory_per_1k_records_mb for r in anchor_results]),
                'complexity_validation_rate': sum(r.complexity_validation for r in anchor_results) / len(anchor_results)
            }
        
        # Overall comparison
        if comparisons:
            summary['overall_comparison'] = {
                'avg_speed_improvement': statistics.mean([c.speed_improvement for c in comparisons]),
                'avg_memory_improvement': statistics.mean([c.memory_improvement for c in comparisons]),
                'time_window_wins': sum(1 for c in comparisons if c.overall_winner == "TimeWindowScanningEngine"),
                'anchor_based_wins': sum(1 for c in comparisons if c.overall_winner == "AnchorBasedEngine"),
                'ties': sum(1 for c in comparisons if c.overall_winner == "Tie"),
                'complexity_advantage_rate': sum(c.complexity_advantage for c in comparisons) / len(comparisons),
                'scalability_advantage_rate': sum(c.scalability_advantage for c in comparisons) / len(comparisons)
            }
        
        return summary
    
    def _export_benchmark_results(self, results: Dict[str, Any]):
        """Export benchmark results to file."""
        
        if self.config.export_path:
            export_path = self.config.export_path
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            export_path = f"performance_benchmark_{timestamp}.json"
        
        with open(export_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"Benchmark results exported to {export_path}")
    
    def run_scalability_test(self, engine_func: Callable, 
                           record_counts: List[int] = None) -> Dict[str, Any]:
        """
        Run scalability test to validate O(N) complexity.
        
        Args:
            engine_func: Engine function to test
            record_counts: List of record counts to test
            
        Returns:
            Scalability test results
        """
        
        if record_counts is None:
            record_counts = [1000, 5000, 10000, 25000, 50000]
        
        print(f"Running scalability test with record counts: {record_counts}")
        
        results = []
        
        for record_count in record_counts:
            test_config = {
                'record_count': record_count,
                'window_size_minutes': 15,
                'feather_count': 5
            }
            
            print(f"Testing scalability with {record_count} records...")
            
            result = self._benchmark_engine(engine_func, "TimeWindowScanningEngine", test_config)
            results.append(result)
        
        # Analyze scalability
        scalability_analysis = self._analyze_scalability(results)
        
        return {
            'test_configuration': {
                'record_counts': record_counts,
                'window_size_minutes': 15,
                'feather_count': 5
            },
            'results': [r.__dict__ for r in results],
            'scalability_analysis': scalability_analysis
        }
    
    def _analyze_scalability(self, results: List[BenchmarkResult]) -> Dict[str, Any]:
        """Analyze scalability characteristics from benchmark results."""
        
        if len(results) < 2:
            return {'error': 'Need at least 2 data points for scalability analysis'}
        
        # Calculate time per record for each test
        time_per_record_values = []
        record_counts = []
        
        for result in results:
            if result.success and result.records_processed > 0:
                time_per_record = result.execution_time_seconds / result.records_processed
                time_per_record_values.append(time_per_record)
                record_counts.append(result.records_processed)
        
        if len(time_per_record_values) < 2:
            return {'error': 'Not enough successful results for analysis'}
        
        # For O(N) complexity, time per record should remain relatively constant
        time_per_record_std = statistics.stdev(time_per_record_values)
        time_per_record_mean = statistics.mean(time_per_record_values)
        coefficient_of_variation = time_per_record_std / time_per_record_mean
        
        # Determine complexity classification
        if coefficient_of_variation < 0.3:
            complexity_classification = "O(N) - Linear"
            scalability_grade = "Excellent"
        elif coefficient_of_variation < 0.5:
            complexity_classification = "O(N log N) - Near Linear"
            scalability_grade = "Good"
        elif coefficient_of_variation < 1.0:
            complexity_classification = "O(N²) - Quadratic"
            scalability_grade = "Poor"
        else:
            complexity_classification = "Worse than O(N²)"
            scalability_grade = "Very Poor"
        
        return {
            'time_per_record_mean_seconds': time_per_record_mean,
            'time_per_record_std_dev': time_per_record_std,
            'coefficient_of_variation': coefficient_of_variation,
            'complexity_classification': complexity_classification,
            'scalability_grade': scalability_grade,
            'achieves_linear_complexity': coefficient_of_variation < 0.3,
            'record_count_range': f"{min(record_counts):,} - {max(record_counts):,}",
            'performance_consistency': "High" if coefficient_of_variation < 0.3 else "Medium" if coefficient_of_variation < 0.5 else "Low"
        }


def create_benchmark_configuration(record_counts: List[int] = None,
                                 window_sizes: List[int] = None,
                                 feather_counts: List[int] = None) -> BenchmarkConfiguration:
    """Create a benchmark configuration with custom parameters."""
    
    config = BenchmarkConfiguration()
    
    if record_counts:
        config.record_counts = record_counts
    if window_sizes:
        config.window_sizes_minutes = window_sizes
    if feather_counts:
        config.feather_counts = feather_counts
    
    return config


def run_quick_performance_test(engine_func: Callable) -> Dict[str, Any]:
    """
    Run a quick performance test to validate basic functionality.
    
    Args:
        engine_func: Engine function to test
        
    Returns:
        Quick test results
    """
    
    config = BenchmarkConfiguration(
        record_counts=[1000, 5000],
        window_sizes_minutes=[15],
        feather_counts=[3],
        iterations_per_test=1
    )
    
    benchmark = PerformanceBenchmark(config)
    return benchmark.run_comprehensive_benchmark(engine_func)