"""Simple test framework for the enhanced Crow Eye features."""

import unittest
import asyncio
import os
import tempfile
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the modules to test
from utils.performance_monitor import PerformanceMonitor, OperationTimer
from utils.enhanced_processing import StreamingDataProcessor, DataCorrelator
from utils.advanced_search import AdvancedSearchEngine, SearchCriteria, FilterEngine, FilterRule
from utils.reporting_engine import ReportGenerator, Finding, SeverityLevel, ReportFormat
from ui.timeline_widget import TimelineEvent, assign_event_colors_by_type


class TestPerformanceMonitor(unittest.TestCase):
    """Test cases for the performance monitoring system."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.monitor = PerformanceMonitor()
    
    def tearDown(self):
        """Clean up after tests."""
        self.monitor.stop_monitoring()
        self.monitor.clear_metrics()
    
    def test_operation_timing(self):
        """Test operation timing functionality."""
        # Time a simple operation
        with self.monitor.time_operation("test_operation", 10):
            import time
            time.sleep(0.1)  # Simulate work
        
        # Check that metrics were recorded
        summary = self.monitor.get_metrics_summary("test_operation")
        self.assertIn("performance", summary)
        self.assertGreater(summary["performance"]["avg_duration_ms"], 90)  # Should be ~100ms
        self.assertEqual(summary["performance"]["total_records_processed"], 10)
    
    def test_monitoring_start_stop(self):
        """Test starting and stopping monitoring."""
        self.monitor.start_monitoring(interval=0.1)
        
        import time
        time.sleep(0.3)  # Let it collect some metrics
        
        self.monitor.stop_monitoring()
        
        # Should have some metrics
        summary = self.monitor.get_metrics_summary()
        self.assertGreater(summary["total_operations"], 0)
    
    def test_metrics_export(self):
        """Test metrics export functionality."""
        # Add a metric
        with self.monitor.time_operation("export_test"):
            import time
            time.sleep(0.1)
        
        # Export to temporary file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_file = f.name
        
        try:
            self.monitor.export_metrics(temp_file)
            
            # Verify file was created and has content
            self.assertTrue(os.path.exists(temp_file))
            
            with open(temp_file, 'r') as f:
                data = json.load(f)
                self.assertIsInstance(data, list)
                self.assertGreater(len(data), 0)
        finally:
            os.unlink(temp_file)


class TestEnhancedProcessing(unittest.TestCase):
    """Test cases for enhanced data processing."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.processor = StreamingDataProcessor(chunk_size=10, max_workers=2)
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up after tests."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_streaming_processor_json(self):
        """Test streaming processing of JSON data."""
        # Create test JSON file
        test_data = [{"id": i, "value": f"test_{i}"} for i in range(25)]
        test_file = os.path.join(self.temp_dir, "test.json")
        
        with open(test_file, 'w') as f:
            json.dump(test_data, f)
        
        # Define processor function
        def test_processor(chunk):
            return [{"processed": True, **item} for item in chunk]
        
        # Run async test
        async def run_test():
            result = await self.processor.process_large_file(
                file_path=test_file,
                processor_func=test_processor,
                output_db=os.path.join(self.temp_dir, "output.db"),
                table_name="test_table"
            )
            return result
        
        result = asyncio.run(run_test())
        
        # Verify results
        self.assertTrue(result.success)
        self.assertEqual(result.records_processed, 25)
        self.assertGreater(result.duration_seconds, 0)
    
    def test_data_correlator_initialization(self):
        """Test data correlator initialization."""
        db_paths = {
            "test1": os.path.join(self.temp_dir, "test1.db"),
            "test2": os.path.join(self.temp_dir, "test2.db")
        }
        
        correlator = DataCorrelator(db_paths)
        self.assertEqual(correlator.database_paths, db_paths)


class TestAdvancedSearch(unittest.TestCase):
    """Test cases for advanced search functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_db = os.path.join(self.temp_dir, "test.db")
        self._create_test_database()
        
        self.search_engine = AdvancedSearchEngine(
            {"test": self.test_db},
            max_workers=2
        )
    
    def tearDown(self):
        """Clean up after tests."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def _create_test_database(self):
        """Create a test database with sample data."""
        conn = sqlite3.connect(self.test_db)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE test_table (
                id INTEGER PRIMARY KEY,
                name TEXT,
                description TEXT,
                timestamp TEXT,
                size INTEGER
            )
        ''')
        
        test_data = [
            (1, "powershell.exe", "Windows PowerShell", "2024-01-01 10:00:00", 1024),
            (2, "cmd.exe", "Command Prompt", "2024-01-01 11:00:00", 512),
            (3, "notepad.exe", "Text Editor", "2024-01-01 12:00:00", 256),
            (4, "PowerShell_ISE.exe", "PowerShell ISE", "2024-01-01 13:00:00", 2048)
        ]
        
        cursor.executemany('''
            INSERT INTO test_table (id, name, description, timestamp, size)
            VALUES (?, ?, ?, ?, ?)
        ''', test_data)
        
        conn.commit()
        conn.close()
    
    def test_basic_search(self):
        """Test basic text search functionality."""
        criteria = SearchCriteria(query="powershell", case_sensitive=False)
        results = self.search_engine.search(criteria, use_cache=False)
        
        # Should find 2 PowerShell-related entries
        self.assertEqual(len(results), 2)
        
        # Verify relevance scoring
        for result in results:
            self.assertGreater(result.relevance_score, 0)
            self.assertEqual(result.artifact_type, "test")
    
    def test_case_sensitive_search(self):
        """Test case-sensitive search."""
        criteria = SearchCriteria(query="PowerShell", case_sensitive=True)
        results = self.search_engine.search(criteria, use_cache=False)
        
        # Should find only exact case matches
        self.assertEqual(len(results), 1)
    
    def test_filter_engine(self):
        """Test the filtering engine."""
        filter_engine = FilterEngine()
        
        # Test data
        data = [
            {"name": "test1.exe", "size": 100},
            {"name": "test2.exe", "size": 200},
            {"name": "test3.doc", "size": 150}
        ]
        
        # Create filter rules
        filters = [
            FilterRule("name", "contains", ".exe"),
            FilterRule("size", "gt", 120)
        ]
        
        # Apply filters
        filtered_data = filter_engine.apply_filters(data, filters)
        
        # Should only match test2.exe (exe file with size > 120)
        self.assertEqual(len(filtered_data), 1)
        self.assertEqual(filtered_data[0]["name"], "test2.exe")


class TestReportingEngine(unittest.TestCase):
    """Test cases for the reporting engine."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.report_generator = ReportGenerator(
            {"test": "dummy.db"},
            output_dir=self.temp_dir
        )
    
    def tearDown(self):
        """Clean up after tests."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_finding_creation(self):
        """Test creating forensic findings."""
        finding = Finding(
            title="Test Finding",
            description="This is a test finding",
            severity=SeverityLevel.HIGH,
            artifact_type="test",
            evidence=[{"key": "value"}],
            timestamps=["2024-01-01 10:00:00"],
            confidence=0.8,
            iocs=["test.exe"],
            recommendations=["Investigate further"],
            metadata={"source": "test"}
        )
        
        self.assertEqual(finding.title, "Test Finding")
        self.assertEqual(finding.severity, SeverityLevel.HIGH)
        self.assertEqual(finding.confidence, 0.8)
    
    def test_finding_analysis(self):
        """Test the finding analysis methods."""
        # This is a simplified test since we don't have real databases
        findings = self.report_generator.analyze_artifacts()
        
        # Should return empty list for non-existent databases
        self.assertIsInstance(findings, list)
    
    def test_statistics_generation(self):
        """Test statistics generation."""
        stats = self.report_generator.generate_statistics()
        
        self.assertIn("total_artifacts", stats)
        self.assertIn("artifact_counts", stats)
        self.assertIsInstance(stats["artifact_counts"], dict)


class TestTimelineWidget(unittest.TestCase):
    """Test cases for timeline functionality."""
    
    def test_timeline_event_creation(self):
        """Test creating timeline events."""
        event = TimelineEvent(
            timestamp=datetime.now(),
            event_type="test",
            title="Test Event",
            description="This is a test event",
            artifact_type="test",
            metadata={"key": "value"},
            importance=3,
            color="#FF0000"
        )
        
        self.assertEqual(event.title, "Test Event")
        self.assertEqual(event.importance, 3)
        self.assertEqual(event.color, "#FF0000")
    
    def test_color_assignment(self):
        """Test automatic color assignment by artifact type."""
        events = [
            TimelineEvent(
                timestamp=datetime.now(),
                event_type="test",
                title="Prefetch Event",
                description="Test",
                artifact_type="prefetch",
                metadata={},
                importance=1
            ),
            TimelineEvent(
                timestamp=datetime.now(),
                event_type="test",
                title="Registry Event",
                description="Test",
                artifact_type="registry",
                metadata={},
                importance=1
            )
        ]
        
        # Assign colors
        colored_events = assign_event_colors_by_type(events)
        
        # Verify colors were assigned
        self.assertNotEqual(colored_events[0].color, "#94A3B8")  # Should not be default gray
        self.assertNotEqual(colored_events[1].color, "#94A3B8")  # Should not be default gray


class TestIntegration(unittest.TestCase):
    """Integration tests for multiple components working together."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up after tests."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_performance_monitoring_with_search(self):
        """Test performance monitoring integration with search."""
        # Create performance monitor
        monitor = PerformanceMonitor()
        
        # Create test database
        test_db = os.path.join(self.temp_dir, "test.db")
        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE test_table (
                id INTEGER PRIMARY KEY,
                name TEXT
            )
        ''')
        cursor.execute("INSERT INTO test_table (name) VALUES ('test')")
        conn.commit()
        conn.close()
        
        # Create search engine
        search_engine = AdvancedSearchEngine({"test": test_db})
        
        # Perform monitored search
        with monitor.time_operation("search_test"):
            criteria = SearchCriteria(query="test")
            results = search_engine.search(criteria, use_cache=False)
        
        # Verify monitoring worked
        summary = monitor.get_metrics_summary("search_test")
        self.assertIn("performance", summary)
        self.assertGreater(summary["performance"]["avg_duration_ms"], 0)
        
        # Verify search worked
        self.assertGreaterEqual(len(results), 0)


def run_all_tests():
    """Run all test suites."""
    print("🧪 Running Crow Eye Enhancement Tests")
    print("=" * 50)
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test cases
    test_classes = [
        TestPerformanceMonitor,
        TestEnhancedProcessing,
        TestAdvancedSearch,
        TestReportingEngine,
        TestTimelineWidget,
        TestIntegration
    ]
    
    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "=" * 50)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success rate: {((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100):.1f}%")
    
    if result.failures:
        print(f"\n❌ Failures ({len(result.failures)}):")
        for test, traceback in result.failures:
            print(f"  - {test}: {traceback.split('AssertionError:')[-1].strip()}")
    
    if result.errors:
        print(f"\n💥 Errors ({len(result.errors)}):")
        for test, traceback in result.errors:
            print(f"  - {test}: {traceback.split('Exception:')[-1].strip()}")
    
    if not result.failures and not result.errors:
        print("\n✅ All tests passed successfully!")
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)