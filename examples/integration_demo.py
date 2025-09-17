"""Integration examples showing how to use the new enhanced features in Crow Eye."""

import sys
import os
from pathlib import Path
from typing import Dict, List, Any
import asyncio
from datetime import datetime, timedelta

# Add the project root to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the new enhancement modules
from utils.performance_monitor import performance_monitor, PerformanceMonitor
from utils.enhanced_processing import StreamingDataProcessor, DataCorrelator, BatchProcessor
from utils.advanced_search import AdvancedSearchEngine, SearchCriteria, create_basic_search_criteria
from utils.reporting_engine import ReportGenerator, ReportFormat
from ui.timeline_widget import TimelineWidget, TimelineEvent, create_timeline_events_from_database

# Import existing Crow Eye components
try:
    from styles import CrowEyeStyles
except ImportError:
    print("Note: styles.py not found, using fallback styling")


class EnhancedCrowEyeIntegration:
    """Example integration class showing how to use the new enhancements."""
    
    def __init__(self, database_paths: Dict[str, str]):
        """Initialize the enhanced Crow Eye integration.
        
        Args:
            database_paths: Dictionary mapping artifact types to database paths
        """
        self.database_paths = database_paths
        
        # Initialize enhancement components
        self.performance_monitor = PerformanceMonitor()
        self.streaming_processor = StreamingDataProcessor(chunk_size=1000, max_workers=4)
        self.search_engine = AdvancedSearchEngine(database_paths, max_workers=4)
        self.report_generator = ReportGenerator(database_paths)
        self.data_correlator = DataCorrelator(database_paths)
        
        print("🚀 Enhanced Crow Eye Integration initialized successfully!")
    
    def demonstrate_performance_monitoring(self):
        """Demonstrate the performance monitoring capabilities."""
        print("\n📊 Performance Monitoring Demo")
        print("=" * 50)
        
        # Start monitoring
        self.performance_monitor.start_monitoring(interval=1.0)
        
        # Simulate some work with performance tracking
        with self.performance_monitor.time_operation("demo_database_operation", 100):
            import time
            time.sleep(2)  # Simulate database work
            
        # Get performance summary
        summary = self.performance_monitor.get_metrics_summary()
        print(f"Performance Summary: {summary}")
        
        # Stop monitoring
        self.performance_monitor.stop_monitoring()
        
        # Export metrics
        metrics_file = "performance_metrics.json"
        self.performance_monitor.export_metrics(metrics_file)
        print(f"📄 Performance metrics exported to {metrics_file}")
    
    async def demonstrate_streaming_processing(self):
        """Demonstrate streaming data processing for large datasets."""
        print("\n🔄 Streaming Data Processing Demo")
        print("=" * 50)
        
        # Create a sample data file for processing
        sample_file = self._create_sample_data_file()
        
        def sample_processor(chunk: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            """Sample processing function that adds metadata to each record."""
            processed_chunk = []
            for record in chunk:
                processed_record = record.copy()
                processed_record['processed_at'] = datetime.now().isoformat()
                processed_record['processing_status'] = 'enhanced'
                processed_chunk.append(processed_record)
            return processed_chunk
        
        def progress_callback(current: int, total: int):
            percentage = (current / total) * 100 if total > 0 else 0
            print(f"Processing progress: {current}/{total} ({percentage:.1f}%)")
        
        # Process the file
        result = await self.streaming_processor.process_large_file(
            file_path=sample_file,
            processor_func=sample_processor,
            output_db="processed_data.db",
            table_name="enhanced_records",
            progress_callback=progress_callback
        )
        
        print(f"✅ Processing completed: {result.records_processed} records in {result.duration_seconds:.2f}s")
        print(f"📈 Throughput: {result.metadata.get('throughput_records_per_second', 0):.1f} records/sec")
        
        # Clean up
        os.remove(sample_file)
    
    def demonstrate_advanced_search(self):
        """Demonstrate advanced search capabilities."""
        print("\n🔍 Advanced Search Demo")
        print("=" * 50)
        
        # Create search criteria
        criteria = SearchCriteria(
            query="powershell",
            case_sensitive=False,
            regex_mode=False,
            whole_word=True,
            artifact_types=["prefetch", "registry"]
        )
        
        print(f"Searching for: '{criteria.query}' across {criteria.artifact_types}")
        
        def progress_callback(current: int, total: int):
            print(f"Search progress: {current}/{total} databases")
        
        # Perform search
        results = self.search_engine.search(criteria, progress_callback=progress_callback)
        
        print(f"🎯 Found {len(results)} search results")
        
        # Display top results
        for i, result in enumerate(results[:3], 1):
            print(f"\n{i}. {result.artifact_type.title()} - Score: {result.relevance_score:.1f}")
            print(f"   Table: {result.table_name}")
            print(f"   Matched Fields: {', '.join(result.matched_fields)}")
            if result.timestamp:
                print(f"   Timestamp: {result.timestamp}")
    
    async def demonstrate_data_correlation(self):
        """Demonstrate cross-artifact data correlation."""
        print("\n🔗 Data Correlation Demo")
        print("=" * 50)
        
        # Perform timestamp-based correlation
        correlations = await self.data_correlator.correlate_by_timestamp(
            time_window_minutes=5,
            artifact_types=["prefetch", "registry", "logs"]
        )
        
        print(f"🔍 Found {len(correlations)} correlation groups")
        
        for correlation in correlations[:3]:  # Show first 3 correlations
            print(f"\nCorrelation {correlation['correlation_id']}:")
            print(f"  Time Window: {correlation['time_window_start']} - {correlation['time_window_end']}")
            print(f"  Artifacts: {correlation['artifact_count']} ({', '.join(correlation['artifact_types'])})")
    
    def demonstrate_timeline_creation(self):
        """Demonstrate timeline widget creation and data population."""
        print("\n📅 Timeline Visualization Demo")
        print("=" * 50)
        
        # Create sample timeline events
        events = self._create_sample_timeline_events()
        
        print(f"📊 Created {len(events)} timeline events")
        
        # In a real integration, you would:
        # 1. Create the timeline widget: timeline = TimelineWidget()
        # 2. Add events: timeline.add_events(events)
        # 3. Add to your main UI layout
        
        # Export timeline data for demonstration
        timeline_data = {
            "events": [
                {
                    "timestamp": event.timestamp.isoformat(),
                    "title": event.title,
                    "artifact_type": event.artifact_type,
                    "importance": event.importance
                }
                for event in events
            ]
        }
        
        import json
        with open("timeline_demo.json", "w") as f:
            json.dump(timeline_data, f, indent=2)
        
        print("📄 Timeline data exported to timeline_demo.json")
    
    def demonstrate_report_generation(self):
        """Demonstrate automated report generation."""
        print("\n📋 Automated Report Generation Demo")
        print("=" * 50)
        
        # Generate HTML report
        html_report = self.report_generator.generate_report(
            case_name="Demo_Investigation",
            examiner="Enhanced Crow Eye",
            report_format=ReportFormat.HTML,
            include_charts=True
        )
        
        print(f"📄 HTML report generated: {html_report}")
        
        # Generate JSON report for programmatic use
        json_report = self.report_generator.generate_report(
            case_name="Demo_Investigation",
            examiner="Enhanced Crow Eye",
            report_format=ReportFormat.JSON
        )
        
        print(f"📊 JSON report generated: {json_report}")
        
        # Generate CSV for spreadsheet analysis
        csv_report = self.report_generator.generate_report(
            case_name="Demo_Investigation",
            examiner="Enhanced Crow Eye",
            report_format=ReportFormat.CSV
        )
        
        print(f"📈 CSV report generated: {csv_report}")
    
    def _create_sample_data_file(self) -> str:
        """Create a sample JSON data file for processing demonstration."""
        import json
        
        sample_data = []
        for i in range(100):
            record = {
                "id": i,
                "filename": f"sample_file_{i}.exe",
                "timestamp": (datetime.now() - timedelta(days=i % 30)).isoformat(),
                "size": 1024 * (i + 1),
                "hash": f"hash_{i:04d}",
                "description": f"Sample record number {i}"
            }
            sample_data.append(record)
        
        filename = "sample_data.json"
        with open(filename, "w") as f:
            json.dump(sample_data, f)
        
        return filename
    
    def _create_sample_timeline_events(self) -> List[TimelineEvent]:
        """Create sample timeline events for demonstration."""
        events = []
        base_time = datetime.now() - timedelta(days=7)
        
        # Prefetch events
        for i in range(5):
            event = TimelineEvent(
                timestamp=base_time + timedelta(hours=i * 6),
                event_type="execution",
                title=f"Program Execution {i+1}",
                description=f"Executed program_{i+1}.exe",
                artifact_type="prefetch",
                metadata={"executable": f"program_{i+1}.exe", "run_count": i+1},
                importance=3,
                color="#FF6B6B"
            )
            events.append(event)
        
        # Registry events
        for i in range(3):
            event = TimelineEvent(
                timestamp=base_time + timedelta(hours=i * 8 + 2),
                event_type="registry_modification",
                title=f"Registry Change {i+1}",
                description=f"Modified registry key {i+1}",
                artifact_type="registry",
                metadata={"key": f"HKLM\\Software\\Key{i+1}", "action": "modified"},
                importance=2,
                color="#4ECDC4"
            )
            events.append(event)
        
        # Log events
        for i in range(4):
            event = TimelineEvent(
                timestamp=base_time + timedelta(hours=i * 12 + 4),
                event_type="security_event",
                title=f"Security Event {i+1}",
                description=f"Security event ID 46{20+i}",
                artifact_type="logs",
                metadata={"event_id": 4620+i, "level": "Information"},
                importance=4,
                color="#45B7D1"
            )
            events.append(event)
        
        return events


async def main():
    """Main demonstration function."""
    print("🔍 Crow Eye Enhanced Features Demonstration")
    print("=" * 60)
    
    # Define sample database paths (these would be real paths in actual usage)
    database_paths = {
        "prefetch": "prefetch_data.db",
        "registry": "registry_data.db", 
        "logs": "log_data.db",
        "lnk": "lnk_data.db",
        "amcache": "amcache_data.db"
    }
    
    # Create integration instance
    integration = EnhancedCrowEyeIntegration(database_paths)
    
    # Demonstrate each enhancement
    print("\n1. Performance Monitoring")
    integration.demonstrate_performance_monitoring()
    
    print("\n2. Streaming Data Processing")
    await integration.demonstrate_streaming_processing()
    
    print("\n3. Advanced Search Engine")
    integration.demonstrate_advanced_search()
    
    print("\n4. Cross-Artifact Correlation")
    await integration.demonstrate_data_correlation()
    
    print("\n5. Timeline Visualization")
    integration.demonstrate_timeline_creation()
    
    print("\n6. Automated Report Generation")
    integration.demonstrate_report_generation()
    
    print("\n✅ All demonstrations completed successfully!")
    print("\nIntegration Notes:")
    print("- All modules are designed to integrate seamlessly with existing Crow Eye code")
    print("- Performance monitoring can be enabled globally or per-operation")
    print("- Streaming processing handles large datasets without memory issues")
    print("- Advanced search provides powerful filtering and correlation capabilities")
    print("- Timeline widgets can be embedded directly in the main UI")
    print("- Report generation can be triggered manually or automatically")


def demonstrate_integration_in_existing_ui():
    """Show how to integrate these enhancements in the existing Crow Eye UI."""
    integration_code = '''
    # Example integration in the main Crow Eye UI class:
    
    class Ui_Crow_Eye(object):
        def __init__(self):
            # Existing initialization code...
            
            # Add enhanced components
            self.performance_monitor = PerformanceMonitor()
            self.search_engine = AdvancedSearchEngine(self.database_paths)
            self.report_generator = ReportGenerator(self.database_paths)
            
            # Start performance monitoring
            self.performance_monitor.start_monitoring()
            
        def setupUi(self, Crow_Eye):
            # Existing UI setup code...
            
            # Add timeline widget to a tab
            self.timeline_widget = TimelineWidget()
            self.tabWidget.addTab(self.timeline_widget, "Timeline")
            
            # Connect timeline events
            self.timeline_widget.event_selected.connect(self.on_timeline_event_selected)
            
        def enhanced_search_implementation(self):
            """Replace existing search with enhanced version."""
            search_text = self.search_input.text()
            criteria = create_basic_search_criteria(search_text)
            
            # Use the enhanced search engine
            results = self.search_engine.search(criteria)
            
            # Display results with highlighting
            self.display_enhanced_search_results(results)
            
        def generate_forensic_report(self):
            """Generate comprehensive forensic report."""
            case_name = self.get_current_case_name()
            
            # Generate HTML report
            report_path = self.report_generator.generate_report(
                case_name=case_name,
                examiner="Crow Eye Analyst",
                report_format=ReportFormat.HTML,
                include_charts=True
            )
            
            # Show report location to user
            QMessageBox.information(
                self.main_window,
                "Report Generated",
                f"Forensic report generated successfully:\\n{report_path}"
            )
            
        def load_timeline_data(self):
            """Load data into timeline widget."""
            events = []
            
            # Create events from each database
            for artifact_type, db_path in self.database_paths.items():
                artifact_events = create_timeline_events_from_database(
                    db_path, artifact_type
                )
                events.extend(artifact_events)
            
            # Assign colors by type and add to timeline
            assign_event_colors_by_type(events)
            self.timeline_widget.add_events(events)
    '''
    
    print("\n💡 Integration Example Code:")
    print("=" * 60)
    print(integration_code)


if __name__ == "__main__":
    # Run the demonstrations
    asyncio.run(main())
    
    # Show integration examples
    demonstrate_integration_in_existing_ui()
    
    print("\n🎯 Next Steps for Full Integration:")
    print("1. Add the enhanced modules to your main Crow Eye application")
    print("2. Update the UI setup to include timeline and advanced search widgets")
    print("3. Replace existing search functionality with the enhanced search engine")
    print("4. Add report generation buttons to the main interface")
    print("5. Enable performance monitoring for all major operations")
    print("6. Configure database paths in the enhancement components")