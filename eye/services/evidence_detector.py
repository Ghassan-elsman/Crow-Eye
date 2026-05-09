"""
Evidence Detector Service for EYE.
Identifies forensic evidence patterns in message content.
"""

import re
import hashlib
import time
import logging
from typing import Dict, Any, List
from functools import lru_cache
from collections import deque


class EvidenceDetector:
    """
    Detects forensic evidence patterns in text content.
    
    Uses compiled regex patterns for performance. Results are cached
    to avoid redundant processing of the same content.
    
    Evidence patterns detected:
    - Timestamps (ISO 8601, Windows FILETIME, Unix epoch)
    - Event IDs (Windows Event Log patterns)
    - File paths (Windows and Unix)
    - Usernames (domain\\user, user@domain)
    - IP addresses (IPv4 and IPv6)
    - Registry keys (Windows Registry paths)
    """
    
    # Evidence pattern weights for confidence scoring
    PATTERN_WEIGHTS = {
        'timestamp': 0.3,
        'event_id': 0.3,
        'file_path': 0.2,
        'username': 0.1,
        'ip_address': 0.2,
        'registry_key': 0.2
    }
    
    def __init__(self):
        """Initialize with compiled regex patterns."""
        self.logger = logging.getLogger(__name__)
        
        # Performance monitoring 
        self.detection_times = deque(maxlen=1000)  # Last 1000 detection times
        self.cache_hits = 0
        self.cache_misses = 0
        
        # Compile all patterns at initialization for performance
        self.patterns = {
            # ISO 8601, Windows FILETIME, Unix epoch timestamps
            'timestamp': re.compile(
                r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?'
            ),
            
            # Windows Event IDs (4624, 4625, etc.)
            'event_id': re.compile(
                r'(?:Event(?:ID)?|EventID)\s*:?\s*\d{4,5}',
                re.IGNORECASE
            ),
            
            # Windows and Unix file paths
            'file_path': re.compile(
                r'(?:[A-Z]:\\[\w\s\\.\\-]+)|(?:/[\w/\\.\\-]+)'
            ),
            
            # Domain\user or user@domain patterns
            'username': re.compile(
                r'(?:[A-Z][A-Z0-9_\\-]+\\[\w]+)|(?:[\w\\.\\-]+@[\w\\.\\-]+)'
            ),
            
            # IPv4 and IPv6 addresses
            'ip_address': re.compile(
                r'(?:\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})|(?:[0-9a-fA-F:]+::[0-9a-fA-F:]+)'
            ),
            
            # Windows Registry keys
            'registry_key': re.compile(
                r'HK(?:EY_)?(?:LOCAL_MACHINE|CURRENT_USER|CLASSES_ROOT|USERS|CURRENT_CONFIG|LM|CU)\\[\w\\\\]+',
                re.IGNORECASE
            )
        }
        
        # LRU cache for detection results (max 1000 entries)
        self._detect_evidence_cached = lru_cache(maxsize=1000)(self._detect_evidence_impl)
    
    def detect_evidence(self, text: str) -> Dict[str, Any]:
        """
        Scan text for forensic evidence patterns.
        """
        if not text:
            return {
                "has_evidence": False,
                "patterns_found": [],
                "confidence": 0.0,
                "matches": {}
            }
            
        start_time = time.time()
        
        try:
            # Use hash of text as cache key
            text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
            
            # Check if result is cached
            cache_info = self._detect_evidence_cached.cache_info()
            initial_hits = cache_info.hits
            
            result = self._detect_evidence_cached(text_hash, text)
            
            # Track cache performance
            cache_info_after = self._detect_evidence_cached.cache_info()
            if cache_info_after.hits > initial_hits:
                self.cache_hits += 1
            else:
                self.cache_misses += 1
            
            # Track detection time
            detection_time = (time.time() - start_time) * 1000  # Convert to ms
            self.detection_times.append(detection_time)
            
            # Log performance warning if detection is slow
            if detection_time > 50:
                self.logger.warning(
                    f"Evidence detection took {detection_time:.2f}ms (target <50ms). "
                    f"Text length: {len(text)} chars"
                )
            
            return result
            
        except Exception as e:
            # Log error with full stack trace
            import traceback
            self.logger.error(f"Evidence detection failed: {e}")
            self.logger.error(f"Stack trace: {traceback.format_exc()}")
            
            # Track detection time even for errors
            detection_time = (time.time() - start_time) * 1000
            self.detection_times.append(detection_time)
            
            # Return safe default (fail-safe: don't preserve)
            # Better to risk over-summarization than to block the investigation workflow
            return {
                "has_evidence": False,
                "patterns_found": [],
                "confidence": 0.0,
                "matches": {},
                "error": str(e)
            }
    
    def _detect_evidence_impl(self, text_hash: str, text: str) -> Dict[str, Any]:
        """
        Internal implementation of evidence detection.
        
        Args:
            text_hash: MD5 hash of text (for caching)
            text: Message content to scan
            
        Returns:
            Detection results dictionary
        """
        matches: Dict[str, List[str]] = {}
        patterns_found: List[str] = []
        
        # Scan for each evidence pattern
        for pattern_type, pattern in self.patterns.items():
            found = pattern.findall(text)
            if found:
                matches[pattern_type] = found
                patterns_found.append(pattern_type)
        
        # Calculate confidence score
        confidence = self._calculate_confidence(matches)
        
        return {
            "has_evidence": len(patterns_found) > 0,
            "patterns_found": patterns_found,
            "confidence": confidence,
            "matches": matches
        }
    
    def _calculate_confidence(self, matches: Dict[str, List[str]]) -> float:
        """
        Calculate confidence score based on number and type of matches.
        
        Weights:
        - timestamp: 0.3 (high value for forensics)
        - event_id: 0.3 (high value for forensics)
        - file_path: 0.2
        - username: 0.1
        - ip_address: 0.2
        - registry_key: 0.2
        
        Multiple matches of same type increase confidence.
        
        Args:
            matches: Dictionary mapping pattern types to matched strings
            
        Returns:
            Confidence score from 0.0 to 1.0
        """
        score = 0.0
        
        for pattern_type, match_list in matches.items():
            if match_list:
                # Base weight + bonus for multiple matches (capped at 2x)
                multiplier = min(1.0 + (len(match_list) - 1) * 0.1, 2.0)
                weight = self.PATTERN_WEIGHTS.get(pattern_type, 0.1)
                score += weight * multiplier
        
        # Cap at 1.0
        return min(score, 1.0)
    
    def should_preserve(self, text: str, threshold: float = 0.7) -> bool:
        """
        Determine if message should be preserved based on evidence detection.
        
        Args:
            text: Message content
            threshold: Confidence threshold for preservation (default 0.7)
            
        Returns:
            True if message contains sufficient evidence to preserve
        """
        result = self.detect_evidence(text)
        return result["has_evidence"] and result["confidence"] >= threshold
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """
        Get performance statistics for evidence detection.
        
        Returns:
            Dictionary containing:
                - avg_detection_time_ms: Average detection time in milliseconds
                - p50_detection_time_ms: 50th percentile (median)
                - p95_detection_time_ms: 95th percentile
                - p99_detection_time_ms: 99th percentile
                - cache_hit_rate: Percentage of cache hits
                - total_detections: Total number of detections performed
        
        """
        if not self.detection_times:
            return {
                "avg_detection_time_ms": 0.0,
                "p50_detection_time_ms": 0.0,
                "p95_detection_time_ms": 0.0,
                "p99_detection_time_ms": 0.0,
                "cache_hit_rate": 0.0,
                "total_detections": 0
            }
        
        # Calculate percentiles
        sorted_times = sorted(self.detection_times)
        n = len(sorted_times)
        
        p50_idx = int(n * 0.50)
        p95_idx = int(n * 0.95)
        p99_idx = int(n * 0.99)
        
        total_cache_operations = self.cache_hits + self.cache_misses
        cache_hit_rate = (self.cache_hits / total_cache_operations * 100) if total_cache_operations > 0 else 0.0
        
        return {
            "avg_detection_time_ms": sum(self.detection_times) / len(self.detection_times),
            "p50_detection_time_ms": sorted_times[p50_idx],
            "p95_detection_time_ms": sorted_times[p95_idx],
            "p99_detection_time_ms": sorted_times[p99_idx],
            "cache_hit_rate": cache_hit_rate,
            "total_detections": len(self.detection_times)
        }
