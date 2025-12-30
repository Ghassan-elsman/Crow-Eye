"""
Complete identifier extraction and correlation pipeline.

This module wires together all components for end-to-end identifier extraction,
correlation, and persistence.
"""

import logging
from pathlib import Path
from typing import List, Optional

from correlation_engine.config.identifier_extraction_config import WingsConfig
from correlation_engine.engine.feather_loader import FeatherLoader
from correlation_engine.engine.identifier_correlation_engine import IdentifierCorrelationEngine
from correlation_engine.engine.database_persistence import DatabasePersistence
from correlation_engine.engine.timestamp_parser import TimestampParser

logger = logging.getLogger(__name__)


class IdentifierExtractionPipeline:
    """
    Complete pipeline for identifier extraction and correlation.
    
    Workflow:
    1. Load Wings config
    2. Initialize components
    3. Load Feather tables
    4. Extract identifiers
    5. Correlate evidence
    6. Persist to database
    """
    
    def __init__(self, config_path: str):
        """
        Initialize pipeline.
        
        Args:
            config_path: Path to Wings configuration file
        """
        self.config = WingsConfig.load_from_file(config_path)
        self.timestamp_parser = TimestampParser(
            custom_formats=self.config.timestamp_parsing.custom_formats
        )
        self.correlation_engine = IdentifierCorrelationEngine(self.config)
        
        logger.info(f"Pipeline initialized with config: {config_path}")
    
    def run(self, feather_paths: List[str], output_db: Optional[str] = None):
        """
        Run complete pipeline.
        
        Args:
            feather_paths: List of paths to Feather databases
            output_db: Optional output database path (uses config if not provided)
        """
        if output_db is None:
            output_db = self.config.correlation_database
        
        logger.info(f"Starting pipeline with {len(feather_paths)} Feather tables")
        
        # Load and process each Feather table
        for feather_path in feather_paths:
            logger.info(f"Processing: {feather_path}")
            
            try:
                # Create feather loader with config and timestamp parser
                feather_loader = FeatherLoader(
                    feather_path, 
                    config=self.config, 
                    timestamp_parser=self.timestamp_parser
                )
                
                for extracted_values in feather_loader.load_table_with_extraction():
                    self.correlation_engine.process_evidence(extracted_values)
            
            except Exception as e:
                logger.error(f"Error processing {feather_path}: {e}")
                continue
        
        # Get statistics
        stats = self.correlation_engine.get_statistics()
        logger.info(f"Correlation complete: {stats}")
        
        # Persist to database
        logger.info(f"Persisting to database: {output_db}")
        with DatabasePersistence(output_db) as db:
            db.persist_engine_state(
                self.correlation_engine.engine_state,
                wings_config_path=str(Path(self.config.correlation_database).parent)
            )
        
        db_stats = DatabasePersistence(output_db)
        db_stats.connect()
        final_stats = db_stats.get_database_stats()
        db_stats.disconnect()
        
        logger.info(f"Pipeline complete. Database stats: {final_stats}")
        
        return {
            'correlation_stats': stats,
            'database_stats': final_stats,
            'output_database': output_db
        }


def run_identifier_extraction(config_path: str, feather_paths: List[str], 
                              output_db: Optional[str] = None):
    """
    Convenience function to run identifier extraction pipeline.
    
    Args:
        config_path: Path to Wings configuration
        feather_paths: List of Feather database paths
        output_db: Optional output database path
        
    Returns:
        Dictionary with pipeline results
    """
    pipeline = IdentifierExtractionPipeline(config_path)
    return pipeline.run(feather_paths, output_db)


if __name__ == "__main__":
    # Example usage
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) < 3:
        print("Usage: python identifier_extraction_pipeline.py <config_path> <feather_path1> [feather_path2 ...]")
        sys.exit(1)
    
    config_path = sys.argv[1]
    feather_paths = sys.argv[2:]
    
    results = run_identifier_extraction(config_path, feather_paths)
    print(f"\nPipeline Results:")
    print(f"  Identities: {results['database_stats']['identities']}")
    print(f"  Anchors: {results['database_stats']['anchors']}")
    print(f"  Evidence: {results['database_stats']['evidence']}")
    print(f"  Output: {results['output_database']}")
