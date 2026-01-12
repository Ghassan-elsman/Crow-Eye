"""
Semantic Mapping Performance Optimizer

Provides performance optimizations for semantic mapping operations including:
- Pattern compilation caching
- Batch processing for large datasets
- Lookup indexing and optimization
- Memory-efficient mapping storage
"""

import logging
import time
import threading
from collections import defaultdict, OrderedDict
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass
import re
from functools import lru_cache

from ..config.semantic_mapping import SemanticMapping, SemanticMappingManager

logger = logging.getLogger(__name__)


@dataclass
class SemanticMappingPerformanceMetrics:
    """Performance metrics for semantic mapping operations"""
    total_lookups: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    pattern_compilations: int = 0
    batch_operations: int = 0
    index_rebuilds: int = 0
    average_lookup_time_ms: float = 0.0
    total_processing_time_ms: float = 0.0
    memory_usage_mb: float = 0.0
    
    @property
    def cache_hit_rate(self) -> float:
        """Calculate cache hit rate percentage"""
        if self.total_lookups == 0:
            return 0.0
        return (self.cache_hits / self.total_lookups) * 100.0


class OptimizedSemanticMappingManager:
    """
    Performance-optimized semantic mapping manager with advanced caching and indexing.
    
    Key optimizations:
    - LRU cache for frequent lookups
    - Compiled pattern caching with size limits
    - Field-based indexing for faster lookups
    - Batch processing for large datasets
    - Memory-efficient storage
    """
    
    def __init__(self, cache_size: int = 10000, pattern_cache_size: int = 1000):
        """
        Initialize optimized semantic mapping manager.
        
        Args:
            cache_size: Size of LRU cache for lookups
            pattern_cache_size: Size of compiled pattern cache
        """
        self.base_manager = SemanticMappingManager()
        self.cache_size = cache_size
        self.pattern_cache_size = pattern_cache_size
        
        # Performance optimization structures
        self._lookup_cache: OrderedDict = OrderedDict()
        self._pattern_cache: OrderedDict = OrderedDict()
        self._field_index: Dict[str, List[SemanticMapping]] = defaultdict(list)
        self._source_index: Dict[str, List[SemanticMapping]] = defaultdict(list)
        self._artifact_index: Dict[str, List[SemanticMapping]] = defaultdict(list)
        
        # Performance metrics
        self.metrics = SemanticMappingPerformanceMetrics()
        
        # Thread safety
        self._cache_lock = threading.RLock()
        self._index_lock = threading.RLock()
        
        # Build initial indexes
        self._rebuild_indexes()
        
        logger.info(f"OptimizedSemanticMappingManager initialized with cache_size={cache_size}, "
                   f"pattern_cache_size={pattern_cache_size}")
    
    def _rebuild_indexes(self):
        """Rebuild all performance indexes"""
        start_time = time.time()
        
        with self._index_lock:
            # Clear existing indexes
            self._field_index.clear()
            self._source_index.clear()
            self._artifact_index.clear()
            
            # Rebuild indexes from all mappings
            all_mappings = []
            all_mappings.extend(self.base_manager.get_all_mappings('global'))
            
            # Add wing and pipeline mappings
            for wing_id in self.base_manager.wing_mappings:
                all_mappings.extend(self.base_manager.get_all_mappings('wing', wing_id))
            
            for pipeline_id in self.base_manager.pipeline_mappings:
                all_mappings.extend(self.base_manager.get_all_mappings('pipeline', pipeline_id=pipeline_id))
            
            # Build indexes
            for mapping in all_mappings:
                # Field index
                field_key = f"{mapping.source}.{mapping.field}"
                self._field_index[field_key].append(mapping)
                
                # Source index
                self._source_index[mapping.source].append(mapping)
                
                # Artifact index
                if mapping.artifact_type:
                    self._artifact_index[mapping.artifact_type].append(mapping)
            
            self.metrics.index_rebuilds += 1
            
        rebuild_time = (time.time() - start_time) * 1000
        logger.debug(f"Rebuilt semantic mapping indexes in {rebuild_time:.2f}ms")
    
    @lru_cache(maxsize=10000)
    def _get_cached_semantic_value(self, source: str, field: str, technical_value: str,
                                  wing_id: Optional[str] = None, pipeline_id: Optional[str] = None) -> Optional[str]:
        """
        Cached version of semantic value lookup.
        
        Args:
            source: Source of the value
            field: Field name
            technical_value: Technical value to map
            wing_id: Optional wing ID
            pipeline_id: Optional pipeline ID
            
        Returns:
            Semantic value if found, None otherwise
        """
        return self.base_manager.get_semantic_value(source, field, technical_value, wing_id, pipeline_id)
    
    def get_semantic_value_optimized(self, source: str, field: str, technical_value: str,
                                   wing_id: Optional[str] = None, pipeline_id: Optional[str] = None) -> Optional[str]:
        """
        Optimized semantic value lookup with caching and indexing.
        
        Args:
            source: Source of the value
            field: Field name
            technical_value: Technical value to map
            wing_id: Optional wing ID
            pipeline_id: Optional pipeline ID
            
        Returns:
            Semantic value if found, None otherwise
        """
        start_time = time.time()
        self.metrics.total_lookups += 1
        
        # Create cache key
        cache_key = f"{source}|{field}|{technical_value}|{wing_id or ''}|{pipeline_id or ''}"
        
        with self._cache_lock:
            # Check cache first
            if cache_key in self._lookup_cache:
                # Move to end (LRU)
                result = self._lookup_cache.pop(cache_key)
                self._lookup_cache[cache_key] = result
                self.metrics.cache_hits += 1
                
                lookup_time = (time.time() - start_time) * 1000
                self._update_average_lookup_time(lookup_time)
                
                return result
            
            self.metrics.cache_misses += 1
        
        # Use indexed lookup for better performance
        result = self._indexed_semantic_lookup(source, field, technical_value, wing_id, pipeline_id)
        
        with self._cache_lock:
            # Add to cache
            self._lookup_cache[cache_key] = result
            
            # Maintain cache size limit
            if len(self._lookup_cache) > self.cache_size:
                # Remove oldest entry
                self._lookup_cache.popitem(last=False)
        
        lookup_time = (time.time() - start_time) * 1000
        self._update_average_lookup_time(lookup_time)
        
        return result
    
    def _indexed_semantic_lookup(self, source: str, field: str, technical_value: str,
                                wing_id: Optional[str] = None, pipeline_id: Optional[str] = None) -> Optional[str]:
        """
        Perform semantic lookup using indexes for better performance.
        
        Args:
            source: Source of the value
            field: Field name
            technical_value: Technical value to map
            wing_id: Optional wing ID
            pipeline_id: Optional pipeline ID
            
        Returns:
            Semantic value if found, None otherwise
        """
        with self._index_lock:
            # Use field index for faster lookup
            field_key = f"{source}.{field}"
            candidate_mappings = self._field_index.get(field_key, [])
            
            # Check wing-specific mappings first (highest priority)
            if wing_id:
                wing_mappings = [m for m in candidate_mappings if m.scope == 'wing' and m.wing_id == wing_id]
                for mapping in wing_mappings:
                    if self._matches_optimized(mapping, technical_value):
                        return mapping.semantic_value
            
            # Check pipeline-specific mappings
            if pipeline_id:
                pipeline_mappings = [m for m in candidate_mappings if m.scope == 'pipeline' and m.pipeline_id == pipeline_id]
                for mapping in pipeline_mappings:
                    if self._matches_optimized(mapping, technical_value):
                        return mapping.semantic_value
            
            # Check global mappings
            global_mappings = [m for m in candidate_mappings if m.scope == 'global']
            for mapping in global_mappings:
                if self._matches_optimized(mapping, technical_value):
                    return mapping.semantic_value
        
        return None
    
    def _matches_optimized(self, mapping: SemanticMapping, value: str) -> bool:
        """
        Optimized pattern matching with compiled pattern caching.
        
        Args:
            mapping: SemanticMapping to test
            value: Value to match
            
        Returns:
            True if matches, False otherwise
        """
        if mapping.pattern:
            # Use cached compiled pattern
            compiled_pattern = self._get_compiled_pattern(mapping.pattern)
            if compiled_pattern:
                return bool(compiled_pattern.search(value))
            return False
        else:
            # Exact matching (case-insensitive)
            return value.lower() == mapping.technical_value.lower()
    
    def _get_compiled_pattern(self, pattern: str) -> Optional[re.Pattern]:
        """
        Get compiled regex pattern with caching.
        
        Args:
            pattern: Regex pattern string
            
        Returns:
            Compiled pattern or None if invalid
        """
        with self._cache_lock:
            # Check pattern cache
            if pattern in self._pattern_cache:
                # Move to end (LRU)
                compiled_pattern = self._pattern_cache.pop(pattern)
                self._pattern_cache[pattern] = compiled_pattern
                return compiled_pattern
            
            # Compile new pattern
            try:
                compiled_pattern = re.compile(pattern, re.IGNORECASE)
                self._pattern_cache[pattern] = compiled_pattern
                self.metrics.pattern_compilations += 1
                
                # Maintain cache size limit
                if len(self._pattern_cache) > self.pattern_cache_size:
                    self._pattern_cache.popitem(last=False)
                
                return compiled_pattern
                
            except re.error as e:
                logger.error(f"Invalid regex pattern '{pattern}': {e}")
                # Cache the failure to avoid repeated compilation attempts
                self._pattern_cache[pattern] = None
                return None
    
    def apply_to_records_batch(self, records: List[Dict[str, Any]], 
                              artifact_type: Optional[str] = None,
                              wing_id: Optional[str] = None, 
                              pipeline_id: Optional[str] = None,
                              batch_size: int = 1000) -> List[List[SemanticMapping]]:
        """
        Apply semantic mappings to a batch of records with optimized processing.
        
        Args:
            records: List of records to process
            artifact_type: Optional artifact type for filtering
            wing_id: Optional wing ID
            pipeline_id: Optional pipeline ID
            batch_size: Size of processing batches
            
        Returns:
            List of matching mappings for each record
        """
        start_time = time.time()
        results = []
        
        # Process in batches to manage memory
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            batch_results = []
            
            for record in batch:
                matching_mappings = self._apply_to_record_optimized(
                    record, artifact_type, wing_id, pipeline_id
                )
                batch_results.append(matching_mappings)
            
            results.extend(batch_results)
            self.metrics.batch_operations += 1
        
        processing_time = (time.time() - start_time) * 1000
        self.metrics.total_processing_time_ms += processing_time
        
        logger.debug(f"Processed {len(records)} records in {len(results) // batch_size + 1} batches "
                    f"in {processing_time:.2f}ms")
        
        return results
    
    def _apply_to_record_optimized(self, record: Dict[str, Any], 
                                  artifact_type: Optional[str] = None,
                                  wing_id: Optional[str] = None, 
                                  pipeline_id: Optional[str] = None) -> List[SemanticMapping]:
        """
        Optimized version of apply_to_record with indexing and caching.
        
        Args:
            record: Record dictionary to apply mappings to
            artifact_type: Optional artifact type for filtering
            wing_id: Optional wing ID
            pipeline_id: Optional pipeline ID
            
        Returns:
            List of matching SemanticMapping objects
        """
        matching_mappings = []
        
        with self._index_lock:
            # Get candidate mappings using indexes
            candidates = set()
            
            # Add artifact-specific mappings if artifact_type provided
            if artifact_type and artifact_type in self._artifact_index:
                candidates.update(self._artifact_index[artifact_type])
            
            # Add field-specific mappings for fields in the record
            for field_name in record.keys():
                if not field_name.startswith('_'):  # Skip internal fields
                    # Try different source combinations
                    for source in ['SecurityLogs', 'SystemLogs', 'ApplicationLogs', 'Prefetch', 'Registry']:
                        field_key = f"{source}.{field_name}"
                        if field_key in self._field_index:
                            candidates.update(self._field_index[field_key])
            
            # If no specific candidates found, use all mappings (fallback)
            if not candidates:
                candidates.update(self.base_manager.get_all_mappings('global'))
                if wing_id:
                    candidates.update(self.base_manager.get_all_mappings('wing', wing_id))
                if pipeline_id:
                    candidates.update(self.base_manager.get_all_mappings('pipeline', pipeline_id=pipeline_id))
        
        # Test each candidate mapping
        for mapping in candidates:
            # Check if field exists in record
            if mapping.field not in record:
                continue
            
            field_value = str(record[mapping.field])
            
            # Check if value matches using optimized matching
            if not self._matches_optimized(mapping, field_value):
                continue
            
            # Check conditions (use base manager's method)
            if not mapping.evaluate_conditions(record):
                continue
            
            # Mapping matches!
            matching_mappings.append(mapping)
        
        # Sort by confidence (highest first)
        matching_mappings.sort(key=lambda m: m.confidence, reverse=True)
        
        return matching_mappings
    
    def precompile_patterns(self, mappings: List[SemanticMapping]):
        """
        Precompile regex patterns for a list of mappings to improve performance.
        
        Args:
            mappings: List of semantic mappings to precompile patterns for
        """
        start_time = time.time()
        compiled_count = 0
        
        for mapping in mappings:
            if mapping.pattern and mapping.pattern not in self._pattern_cache:
                self._get_compiled_pattern(mapping.pattern)
                compiled_count += 1
        
        compile_time = (time.time() - start_time) * 1000
        logger.info(f"Precompiled {compiled_count} regex patterns in {compile_time:.2f}ms")
    
    def optimize_for_dataset(self, sample_records: List[Dict[str, Any]], 
                           artifact_type: Optional[str] = None):
        """
        Optimize the manager for a specific dataset by analyzing field patterns.
        
        Args:
            sample_records: Sample records to analyze
            artifact_type: Optional artifact type
        """
        start_time = time.time()
        
        # Analyze field frequency
        field_frequency = defaultdict(int)
        value_patterns = defaultdict(set)
        
        for record in sample_records:
            for field_name, field_value in record.items():
                if not field_name.startswith('_'):
                    field_frequency[field_name] += 1
                    value_patterns[field_name].add(str(field_value)[:50])  # Limit pattern length
        
        # Prioritize indexes for frequent fields
        frequent_fields = sorted(field_frequency.items(), key=lambda x: x[1], reverse=True)[:20]
        
        logger.info(f"Dataset optimization complete. Top frequent fields: "
                   f"{[f[0] for f in frequent_fields[:5]]}")
        
        # Precompile patterns for relevant mappings
        relevant_mappings = []
        for field_name, _ in frequent_fields:
            for source in ['SecurityLogs', 'SystemLogs', 'ApplicationLogs', 'Prefetch', 'Registry']:
                field_key = f"{source}.{field_name}"
                if field_key in self._field_index:
                    relevant_mappings.extend(self._field_index[field_key])
        
        if relevant_mappings:
            self.precompile_patterns(relevant_mappings)
        
        optimization_time = (time.time() - start_time) * 1000
        logger.info(f"Dataset optimization completed in {optimization_time:.2f}ms")
    
    def _update_average_lookup_time(self, lookup_time_ms: float):
        """Update average lookup time metric"""
        if self.metrics.total_lookups == 1:
            self.metrics.average_lookup_time_ms = lookup_time_ms
        else:
            # Running average
            self.metrics.average_lookup_time_ms = (
                (self.metrics.average_lookup_time_ms * (self.metrics.total_lookups - 1) + lookup_time_ms) /
                self.metrics.total_lookups
            )
    
    def clear_caches(self):
        """Clear all caches to free memory"""
        with self._cache_lock:
            self._lookup_cache.clear()
            self._pattern_cache.clear()
        
        logger.info("Semantic mapping caches cleared")
    
    def get_performance_metrics(self) -> SemanticMappingPerformanceMetrics:
        """Get current performance metrics"""
        return self.metrics
    
    def get_cache_statistics(self) -> Dict[str, Any]:
        """Get detailed cache statistics"""
        with self._cache_lock:
            return {
                'lookup_cache_size': len(self._lookup_cache),
                'lookup_cache_limit': self.cache_size,
                'pattern_cache_size': len(self._pattern_cache),
                'pattern_cache_limit': self.pattern_cache_size,
                'cache_hit_rate': self.metrics.cache_hit_rate,
                'total_lookups': self.metrics.total_lookups,
                'cache_hits': self.metrics.cache_hits,
                'cache_misses': self.metrics.cache_misses,
                'pattern_compilations': self.metrics.pattern_compilations
            }
    
    def get_index_statistics(self) -> Dict[str, Any]:
        """Get index statistics"""
        with self._index_lock:
            return {
                'field_index_entries': len(self._field_index),
                'source_index_entries': len(self._source_index),
                'artifact_index_entries': len(self._artifact_index),
                'total_indexed_mappings': sum(len(mappings) for mappings in self._field_index.values()),
                'index_rebuilds': self.metrics.index_rebuilds
            }
    
    # Delegate other methods to base manager
    def add_mapping(self, mapping: SemanticMapping):
        """Add mapping and update indexes"""
        self.base_manager.add_mapping(mapping)
        self._rebuild_indexes()
        self.clear_caches()  # Clear caches to ensure consistency
    
    def get_all_mappings(self, scope: str = "global", wing_id: Optional[str] = None, 
                        pipeline_id: Optional[str] = None) -> List[SemanticMapping]:
        """Delegate to base manager"""
        return self.base_manager.get_all_mappings(scope, wing_id, pipeline_id)
    
    def load_from_file(self, file_path):
        """Load mappings and rebuild indexes"""
        self.base_manager.load_from_file(file_path)
        self._rebuild_indexes()
        self.clear_caches()
    
    def save_to_file(self, file_path, scope: str = "global", wing_id: Optional[str] = None, 
                    pipeline_id: Optional[str] = None):
        """Delegate to base manager"""
        self.base_manager.save_to_file(file_path, scope, wing_id, pipeline_id)