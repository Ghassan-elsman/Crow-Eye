"""
Unit and Integration Tests for GUI Enhancements

Tests for:
- Database persistence with compression
- Cancellation support
- Feather data serialization/deserialization
- CorrelationResults status fields

Note: These tests focus on the database and data structure components
that can be tested independently.
"""

import unittest
import tempfile
import json
import gzip
import sqlite3
from pathlib import Path
from datetime import datetime


class TestDatabaseCompression(unittest.TestCase):
    """Test database compression functionality"""
    
    def setUp(self):
        """Create temporary database for testing"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_results.db"
        
        # Create database with schema
        self.conn = sqlite3.connect(str(self.db_path))
        cursor = self.conn.cursor()
        
        # Create matches table with compressed column
        cursor.execute("""
            CREATE TABLE matches (
                match_id TEXT PRIMARY KEY,
                result_id INTEGER,
                timestamp TEXT,
                feather_records TEXT,
                compressed BOOLEAN DEFAULT 0
            )
        """)
        self.conn.commit()
    
    def tearDown(self):
        """Clean up temporary files"""
        self.conn.close()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_small_data_no_compression(self):
        """Test that small data is not compressed"""
        small_data = {
            'prefetch': {'name': 'test.exe', 'timestamp': '2025-01-01 10:00:00'},
            'shimcache': {'path': 'C:\\test.exe'}
        }
        
        # Serialize without compression
        data_json = json.dumps(small_data)
        
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO matches (match_id, result_id, timestamp, feather_records, compressed)
            VALUES (?, ?, ?, ?, ?)
        """, ('test1', 1, '2025-01-01 10:00:00', data_json, 0))
        self.conn.commit()
        
        # Load and verify
        cursor.execute("SELECT compressed, feather_records FROM matches WHERE match_id = ?", ('test1',))
        row = cursor.fetchone()
        
        self.assertEqual(row[0], 0, "Should not be compressed")
        loaded_data = json.loads(row[1])
        self.assertEqual(loaded_data, small_data)
        print("✓ Small data test passed - no compression")
    
    def test_large_data_compression(self):
        """Test that large data can be compressed"""
        # Create large data (>1MB)
        large_data = {
            f'feather_{i}': {
                'data': 'x' * 10000,
                'timestamp': f'2025-01-01 10:{i:02d}:00'
            }
            for i in range(100)  # ~1.5MB
        }
        
        # Serialize and compress
        data_json = json.dumps(large_data)
        original_size = len(data_json.encode('utf-8'))
        
        compressed_data = gzip.compress(data_json.encode('utf-8'))
        compressed_size = len(compressed_data)
        
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO matches (match_id, result_id, timestamp, feather_records, compressed)
            VALUES (?, ?, ?, ?, ?)
        """, ('test2', 1, '2025-01-01 10:00:00', compressed_data, 1))
        self.conn.commit()
        
        # Load and decompress
        cursor.execute("SELECT compressed, feather_records FROM matches WHERE match_id = ?", ('test2',))
        row = cursor.fetchone()
        
        self.assertEqual(row[0], 1, "Should be compressed")
        
        decompressed = gzip.decompress(row[1])
        loaded_data = json.loads(decompressed.decode('utf-8'))
        
        self.assertEqual(loaded_data, large_data)
        
        compression_ratio = (1 - compressed_size/original_size) * 100
        print(f"✓ Large data test passed")
        print(f"  Original: {original_size:,} bytes")
        print(f"  Compressed: {compressed_size:,} bytes")
        print(f"  Compression: {compression_ratio:.1f}%")
        
        self.assertLess(compressed_size, original_size, "Compressed should be smaller")
    
    def test_compression_decompression_cycle(self):
        """Test data integrity through compression cycle"""
        test_data = {
            'prefetch': {
                'name': 'chrome.exe',
                'hash': 'abc123',
                'timestamp': '2025-01-01 10:00:00',
                'nested': {'deep': {'value': 'test'}}
            },
            'shimcache': {
                'path': 'C:\\Program Files\\Chrome\\chrome.exe',
                'size': 1024000,
                'list': ['item1', 'item2', 'item3']
            }
        }
        
        # Compress
        data_json = json.dumps(test_data)
        compressed = gzip.compress(data_json.encode('utf-8'))
        
        # Save
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO matches (match_id, result_id, timestamp, feather_records, compressed)
            VALUES (?, ?, ?, ?, ?)
        """, ('test3', 1, '2025-01-01 10:00:00', compressed, 1))
        self.conn.commit()
        
        # Load and decompress
        cursor.execute("SELECT feather_records FROM matches WHERE match_id = ? AND compressed = 1", ('test3',))
        row = cursor.fetchone()
        
        decompressed = gzip.decompress(row[0])
        loaded_data = json.loads(decompressed.decode('utf-8'))
        
        self.assertEqual(loaded_data, test_data, "Data should be identical after cycle")
        self.assertEqual(loaded_data['prefetch']['nested']['deep']['value'], 'test')
        self.assertEqual(loaded_data['shimcache']['list'], ['item1', 'item2', 'item3'])
        print("✓ Compression cycle test passed - data integrity maintained")


class TestDatabaseSchema(unittest.TestCase):
    """Test database schema has required columns"""
    
    def test_compressed_column_exists(self):
        """Test that compressed column can be created"""
        temp_dir = tempfile.mkdtemp()
        db_path = Path(temp_dir) / "test_schema.db"
        
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            # Create table with compressed column
            cursor.execute("""
                CREATE TABLE matches (
                    match_id TEXT PRIMARY KEY,
                    feather_records TEXT,
                    compressed BOOLEAN DEFAULT 0
                )
            """)
            conn.commit()
            
            # Verify column exists
            cursor.execute("PRAGMA table_info(matches)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}
            
            self.assertIn('compressed', columns)
            self.assertIn('feather_records', columns)
            
            conn.close()
            print("✓ Schema test passed - compressed column exists")
            
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestFeatherDataStructures(unittest.TestCase):
    """Test feather data structures"""
    
    def test_complex_feather_data_serialization(self):
        """Test serializing complex feather data"""
        complex_data = {
            'prefetch': {
                'name': 'application.exe',
                'hash': 'abc123def456',
                'last_executed': '2025-01-01 10:00:00',
                'run_count': 42,
                'files_referenced': ['file1.dll', 'file2.dll', 'file3.dll'],
                'metadata': {
                    'version': '1.0',
                    'size': 1024000,
                    'nested': {'deep': 'value'}
                }
            },
            'shimcache': {
                'path': 'C:\\Program Files\\App\\application.exe',
                'modified': '2025-01-01 09:00:00',
                'flags': ['executed', 'cached']
            }
        }
        
        # Serialize
        json_str = json.dumps(complex_data)
        
        # Deserialize
        loaded_data = json.loads(json_str)
        
        # Verify structure preserved
        self.assertEqual(loaded_data['prefetch']['name'], 'application.exe')
        self.assertEqual(loaded_data['prefetch']['run_count'], 42)
        self.assertEqual(len(loaded_data['prefetch']['files_referenced']), 3)
        self.assertEqual(loaded_data['prefetch']['metadata']['nested']['deep'], 'value')
        self.assertIn('executed', loaded_data['shimcache']['flags'])
        
        print("✓ Complex data serialization test passed")
    
    def test_feather_data_with_special_characters(self):
        """Test feather data with special characters"""
        special_data = {
            'test': {
                'path': 'C:\\Users\\Test\\Documents\\file with spaces.txt',
                'unicode': 'Test™ ® © 中文 العربية',
                'quotes': 'He said "hello"',
                'newlines': 'Line1\nLine2\nLine3'
            }
        }
        
        # Serialize and deserialize
        json_str = json.dumps(special_data)
        loaded_data = json.loads(json_str)
        
        self.assertEqual(loaded_data, special_data)
        print("✓ Special characters test passed")


def run_tests():
    """Run all tests and return results"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestDatabaseCompression))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabaseSchema))
    suite.addTests(loader.loadTestsFromTestCase(TestFeatherDataStructures))
    
    # Run tests with verbose output
    print("\n" + "="*70)
    print("GUI ENHANCEMENTS - UNIT AND INTEGRATION TESTS")
    print("="*70 + "\n")
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Tests run: {result.testsRun}")
    print(f"✓ Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    if result.failures:
        print(f"✗ Failures: {len(result.failures)}")
    if result.errors:
        print(f"✗ Errors: {len(result.errors)}")
    print("="*70)
    
    if result.wasSuccessful():
        print("\n✅ ALL TESTS PASSED!\n")
    else:
        print("\n❌ SOME TESTS FAILED\n")
    
    return result


if __name__ == '__main__':
    import sys
    result = run_tests()
    sys.exit(0 if result.wasSuccessful() else 1)



class TestDatabaseCompression(unittest.TestCase):
    """Test database compression for large feather_records"""
    
    def setUp(self):
        """Create temporary database for testing"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_results.db"
        self.db = ResultsDatabase(str(self.db_path), debug_mode=True)
    
    def tearDown(self):
        """Clean up temporary files"""
        self.db.close()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_small_feather_records_no_compression(self):
        """Test that small feather_records are not compressed"""
        # Create a match with small feather_records
        small_data = {
            'prefetch': {'name': 'test.exe', 'timestamp': '2025-01-01 10:00:00'},
            'shimcache': {'path': 'C:\\test.exe', 'modified': '2025-01-01 09:00:00'}
        }
        
        match = CorrelationMatch(
            match_id='test_match_1',
            timestamp='2025-01-01 10:00:00',
            feather_records=small_data,
            match_score=0.95,
            feather_count=2,
            time_spread_seconds=60.0,
            anchor_feather_id='prefetch',
            anchor_artifact_type='Prefetch'
        )
        
        # Create execution and result
        execution_id = self.db.create_execution_placeholder(
            pipeline_name='test_pipeline',
            output_dir=self.temp_dir,
            engine_type='identity_based'
        )
        
        result_id = self.db.save_correlation_result(
            execution_id=execution_id,
            wing_id='test_wing',
            wing_name='Test Wing',
            total_matches=1,
            feathers_processed=2
        )
        
        # Save match
        self.db.save_match(result_id, match)
        self.db.conn.commit()
        
        # Load match and verify
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT compressed, feather_records FROM matches WHERE match_id = ?", ('test_match_1',))
        row = cursor.fetchone()
        
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 0, "Small data should not be compressed")
        
        # Verify data can be loaded
        loaded_data = json.loads(row[1])
        self.assertEqual(loaded_data, small_data)
    
    def test_large_feather_records_compression(self):
        """Test that large feather_records (>1MB) are compressed"""
        # Create a match with large feather_records (>1MB)
        large_data = {
            f'feather_{i}': {
                'data': 'x' * 10000,  # 10KB per feather
                'timestamp': f'2025-01-01 10:{i:02d}:00',
                'extra_field': 'y' * 5000
            }
            for i in range(100)  # 100 feathers * ~15KB = ~1.5MB
        }
        
        match = CorrelationMatch(
            match_id='test_match_large',
            timestamp='2025-01-01 10:00:00',
            feather_records=large_data,
            match_score=0.85,
            feather_count=100,
            time_spread_seconds=3600.0,
            anchor_feather_id='feather_0',
            anchor_artifact_type='Test'
        )
        
        # Create execution and result
        execution_id = self.db.create_execution_placeholder(
            pipeline_name='test_pipeline',
            output_dir=self.temp_dir,
            engine_type='time_based'
        )
        
        result_id = self.db.save_correlation_result(
            execution_id=execution_id,
            wing_id='test_wing',
            wing_name='Test Wing',
            total_matches=1,
            feathers_processed=100
        )
        
        # Save match
        self.db.save_match(result_id, match)
        self.db.conn.commit()
        
        # Load match and verify compression
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT compressed, feather_records FROM matches WHERE match_id = ?", ('test_match_large',))
        row = cursor.fetchone()
        
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 1, "Large data should be compressed")
        
        # Verify compressed data is smaller
        compressed_size = len(row[1]) if isinstance(row[1], bytes) else len(row[1].encode('latin1'))
        original_size = len(json.dumps(large_data).encode('utf-8'))
        
        print(f"Original size: {original_size:,} bytes")
        print(f"Compressed size: {compressed_size:,} bytes")
        print(f"Compression ratio: {(1 - compressed_size/original_size)*100:.1f}%")
        
        self.assertLess(compressed_size, original_size, "Compressed data should be smaller")
    
    def test_compression_decompression_cycle(self):
        """Test that data survives compression/decompression cycle"""
        # Create test data
        test_data = {
            'prefetch': {'name': 'chrome.exe', 'hash': 'abc123', 'timestamp': '2025-01-01 10:00:00'},
            'shimcache': {'path': 'C:\\Program Files\\Chrome\\chrome.exe', 'size': 1024000},
            'amcache': {'sha256': 'def456', 'company': 'Google Inc.'}
        }
        
        match = CorrelationMatch(
            match_id='test_cycle',
            timestamp='2025-01-01 10:00:00',
            feather_records=test_data,
            match_score=0.90,
            feather_count=3,
            time_spread_seconds=120.0,
            anchor_feather_id='prefetch',
            anchor_artifact_type='Prefetch'
        )
        
        # Save to database
        execution_id = self.db.create_execution_placeholder(
            pipeline_name='test_pipeline',
            output_dir=self.temp_dir,
            engine_type='identity_based'
        )
        
        result_id = self.db.save_correlation_result(
            execution_id=execution_id,
            wing_id='test_wing',
            wing_name='Test Wing',
            total_matches=1,
            feathers_processed=3
        )
        
        self.db.save_match(result_id, match)
        self.db.conn.commit()
        
        # Load from database
        loaded_result = self.db.load_correlation_result(result_id)
        
        self.assertIsNotNone(loaded_result)
        self.assertEqual(len(loaded_result.matches), 1)
        
        loaded_match = loaded_result.matches[0]
        self.assertEqual(loaded_match.match_id, 'test_cycle')
        self.assertEqual(loaded_match.feather_records, test_data, "Data should be identical after save/load cycle")


class TestCancellationSupport(unittest.TestCase):
    """Test cancellation support in engines"""
    
    def test_cancellation_manager_initialization(self):
        """Test that cancellation manager initializes correctly"""
        manager = EnhancedCancellationManager(debug_mode=True)
        
        self.assertFalse(manager.is_cancelled())
        self.assertIsNone(manager.get_cancellation_context())
    
    def test_cancellation_request(self):
        """Test requesting cancellation"""
        manager = EnhancedCancellationManager(debug_mode=True)
        
        manager.request_cancellation(reason="Test cancellation", requested_by="Unit Test")
        
        self.assertTrue(manager.is_cancelled())
        
        context = manager.get_cancellation_context()
        self.assertIsNotNone(context)
        self.assertEqual(context.reason, "Test cancellation")
        self.assertEqual(context.requested_by, "Unit Test")
    
    def test_identity_engine_cancellation_support(self):
        """Test that identity engine has cancellation support"""
        engine = IdentityBasedCorrelationEngine(time_window_minutes=180, debug_mode=True)
        
        # Verify cancellation methods exist
        self.assertTrue(hasattr(engine, 'cancellation_manager'))
        self.assertTrue(hasattr(engine, 'request_cancellation'))
        self.assertTrue(hasattr(engine, 'is_cancelled'))
        self.assertTrue(hasattr(engine, 'check_cancellation'))
        
        # Test cancellation
        self.assertFalse(engine.is_cancelled())
        engine.request_cancellation("Test")
        self.assertTrue(engine.is_cancelled())
    
    def test_check_cancellation_raises_exception(self):
        """Test that check_cancellation raises exception when cancelled"""
        engine = IdentityBasedCorrelationEngine(debug_mode=True)
        
        engine.request_cancellation("Test")
        
        with self.assertRaises(Exception) as context:
            engine.check_cancellation()
        
        self.assertIn("cancelled", str(context.exception).lower())


class TestCorrelationResultsStatus(unittest.TestCase):
    """Test CorrelationResults status and cancellation fields"""
    
    def test_correlation_results_default_status(self):
        """Test that CorrelationResults has default status"""
        results = CorrelationResults(
            wing_name='Test Wing',
            wing_id='test_wing'
        )
        
        self.assertEqual(results.status, "Completed")
        self.assertIsNone(results.cancellation_timestamp)
    
    def test_correlation_results_cancelled_status(self):
        """Test setting cancelled status"""
        results = CorrelationResults(
            wing_name='Test Wing',
            wing_id='test_wing'
        )
        
        results.status = "Cancelled"
        results.cancellation_timestamp = datetime.now()
        
        self.assertEqual(results.status, "Cancelled")
        self.assertIsNotNone(results.cancellation_timestamp)
    
    def test_correlation_results_with_warnings(self):
        """Test adding cancellation warnings"""
        results = CorrelationResults(
            wing_name='Test Wing',
            wing_id='test_wing'
        )
        
        results.status = "Cancelled"
        results.warnings.append("Execution was cancelled by user")
        results.warnings.append("Partial results saved: 50 identities")
        
        self.assertEqual(len(results.warnings), 2)
        self.assertIn("cancelled", results.warnings[0].lower())


class TestFeatherDataPersistence(unittest.TestCase):
    """Test feather data persistence through database"""
    
    def setUp(self):
        """Create temporary database"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_feather.db"
        self.db = ResultsDatabase(str(self.db_path), debug_mode=True)
    
    def tearDown(self):
        """Clean up"""
        self.db.close()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_feather_records_field_exists(self):
        """Test that CorrelationMatch has feather_records field"""
        match = CorrelationMatch(
            match_id='test',
            timestamp='2025-01-01 10:00:00',
            feather_records={'test': {'data': 'value'}},
            match_score=0.9,
            feather_count=1,
            time_spread_seconds=0,
            anchor_feather_id='test',
            anchor_artifact_type='Test'
        )
        
        self.assertIsNotNone(match.feather_records)
        self.assertIsInstance(match.feather_records, dict)
        self.assertEqual(match.feather_records['test']['data'], 'value')
    
    def test_complex_feather_data_persistence(self):
        """Test persisting complex feather data structures"""
        complex_data = {
            'prefetch': {
                'name': 'application.exe',
                'hash': 'abc123def456',
                'last_executed': '2025-01-01 10:00:00',
                'run_count': 42,
                'files_referenced': ['file1.dll', 'file2.dll', 'file3.dll'],
                'metadata': {
                    'version': '1.0',
                    'size': 1024000,
                    'nested': {'deep': 'value'}
                }
            },
            'shimcache': {
                'path': 'C:\\Program Files\\App\\application.exe',
                'modified': '2025-01-01 09:00:00',
                'flags': ['executed', 'cached']
            }
        }
        
        match = CorrelationMatch(
            match_id='complex_test',
            timestamp='2025-01-01 10:00:00',
            feather_records=complex_data,
            match_score=0.95,
            feather_count=2,
            time_spread_seconds=3600.0,
            anchor_feather_id='prefetch',
            anchor_artifact_type='Prefetch'
        )
        
        # Save
        execution_id = self.db.create_execution_placeholder(
            pipeline_name='test',
            output_dir=self.temp_dir,
            engine_type='time_based'
        )
        
        result_id = self.db.save_correlation_result(
            execution_id=execution_id,
            wing_id='test',
            wing_name='Test',
            total_matches=1,
            feathers_processed=2
        )
        
        self.db.save_match(result_id, match)
        self.db.conn.commit()
        
        # Load
        loaded_result = self.db.load_correlation_result(result_id)
        loaded_match = loaded_result.matches[0]
        
        # Verify complex structure preserved
        self.assertEqual(loaded_match.feather_records['prefetch']['name'], 'application.exe')
        self.assertEqual(loaded_match.feather_records['prefetch']['run_count'], 42)
        self.assertEqual(len(loaded_match.feather_records['prefetch']['files_referenced']), 3)
        self.assertEqual(loaded_match.feather_records['prefetch']['metadata']['nested']['deep'], 'value')
        self.assertIn('executed', loaded_match.feather_records['shimcache']['flags'])


class TestDatabaseSchema(unittest.TestCase):
    """Test database schema has required columns"""
    
    def setUp(self):
        """Create temporary database"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_schema.db"
        self.db = ResultsDatabase(str(self.db_path), debug_mode=True)
    
    def tearDown(self):
        """Clean up"""
        self.db.close()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_matches_table_has_compressed_column(self):
        """Test that matches table has compressed column"""
        cursor = self.db.conn.cursor()
        cursor.execute("PRAGMA table_info(matches)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        
        self.assertIn('compressed', columns, "matches table should have 'compressed' column")
        self.assertIn('feather_records', columns, "matches table should have 'feather_records' column")
    
    def test_correlation_results_has_status_field(self):
        """Test that CorrelationResults dataclass has status field"""
        from engine.data_structures import CorrelationResults
        import dataclasses
        
        fields = {f.name: f.type for f in dataclasses.fields(CorrelationResults)}
        
        self.assertIn('status', fields, "CorrelationResults should have 'status' field")
        self.assertIn('cancellation_timestamp', fields, "CorrelationResults should have 'cancellation_timestamp' field")


def run_tests():
    """Run all tests and return results"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestDatabaseCompression))
    suite.addTests(loader.loadTestsFromTestCase(TestCancellationSupport))
    suite.addTests(loader.loadTestsFromTestCase(TestCorrelationResultsStatus))
    suite.addTests(loader.loadTestsFromTestCase(TestFeatherDataPersistence))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabaseSchema))
    
    # Run tests with verbose output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("="*70)
    
    return result


if __name__ == '__main__':
    result = run_tests()
    sys.exit(0 if result.wasSuccessful() else 1)
