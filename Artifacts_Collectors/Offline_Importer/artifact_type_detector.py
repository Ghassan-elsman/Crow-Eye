"""
Artifact Type Detector for Offline Artifact Importer

This module provides functionality to detect Windows forensic artifact types
from raw files using ONLY filename and extension patterns for fast detection.
No file signature/magic byte checking is performed.
"""

import os
import re
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class ArtifactDetectionResult:
    """
    Result of artifact type detection.
    
    Attributes:
        file_path: Path to the file that was analyzed
        artifact_type: Detected artifact type (Registry, Prefetch, JumpLists, 
                      MFT, USN, RecycleBin, AmCache, Unknown)
        confidence: Detection confidence level (0.0 to 1.0)
        detection_method: Method used for detection (signature, filename, extension)
        file_size: Size of the file in bytes
    """
    file_path: str
    artifact_type: str
    confidence: float
    detection_method: str
    file_size: int


class ArtifactTypeDetector:
    """
    Detects Windows forensic artifact types from raw files.
    
    Uses ONLY filename and extension patterns for fast detection.
    No file reading or signature checking is performed.
    """
    
    def __init__(self):
        """Initialize the artifact type detector."""
        # No signature detector - using only filename/extension patterns for speed
        
        # Registry hive filename patterns (case-insensitive)
        # Smart patterns that handle variations, samples, and numbers
        self.registry_patterns = [
            r'NTUSER\.DAT',  # Exact match for NTUSER.DAT
            r'^SYSTEM',      # Starts with SYSTEM (allows SYSTEM.001, SYSTEM.bak, SYSTEM_001, etc.)
            r'^SOFTWARE',    # Starts with SOFTWARE
            r'^SAM',         # Starts with SAM
            r'^SECURITY',    # Starts with SECURITY
            r'UsrClass\.dat', # Contains UsrClass.dat
            r'^DEFAULT',     # Starts with DEFAULT
            r'^COMPONENTS',  # Starts with COMPONENTS
            r'^BCD',         # Starts with BCD
            r'Amcache\.hve'  # Contains Amcache.hve
        ]
        
        # Prefetch filename pattern - smart detection
        # Matches .pf extension anywhere in filename (allows variations like file.pf, file.001.pf, etc.)
        self.prefetch_pattern = r'\.pf$'
        
        # Jump Lists filename patterns - smart detection
        # Handles variations like automaticDestinations-ms, automaticDestinations-ms-001, etc.
        self.jumplist_patterns = [
            r'automaticDestinations-ms',  # Contains automaticDestinations-ms (allows numbers, samples)
            r'customDestinations-ms',     # Contains customDestinations-ms (allows numbers, samples)
            r'\.lnk$',                    # .lnk files (shortcuts) - exact extension match
        ]
        
        # MFT filename patterns - smart detection
        # Handles variations like $MFT, $MFT.001, $MFT.bak, mft.bin, MFT.bin, etc.
        self.mft_patterns = [
            r'\$MFT',      # Contains $MFT (allows $MFT.001, $MFT.bak, etc.)
            r'mft\.bin',   # Contains mft.bin (allows mft.bin.001, mft.bin.bak, etc.)
            r'MFT\.bin'    # Contains MFT.bin (allows MFT.bin.001, MFT.bin.bak, etc.)
        ]
        
        # USN Journal filename patterns - smart detection
        # Handles variations like $UsnJrnl, $UsnJrnl.001, $J, $J.001, usn.bin, USN.bin, etc.
        self.usn_patterns = [
            r'\$UsnJrnl',  # Contains $UsnJrnl (allows $UsnJrnl.001, $UsnJrnl.bak, etc.)
            r'\$J',        # Contains $J (allows $J.001, $J.bak, etc.)
            r'usn\.bin',   # Contains usn.bin (allows usn.bin.001, usn.bin.bak, etc.)
            r'USN\.bin'    # Contains USN.bin (allows USN.bin.001, USN.bin.bak, etc.)
        ]
        
        # Recycle Bin filename patterns - smart detection
        # Handles variations like $I*, $R*, INFO2, INFO2.001, etc.
        self.recyclebin_patterns = [
            r'\$I',   # Contains $I (allows $I123, $I456, $I.001, etc.)
            r'\$R',   # Contains $R (allows $R123, $R456, $R.001, etc.)
            r'INFO2'  # Contains INFO2 (allows INFO2.001, INFO2.bak, etc.)
        ]
        
        # AmCache filename patterns - smart detection
        # Handles variations like Amcache.hve, AmCache.hve, AMCACHE.HVE, Amcache.hve.001, etc.
        self.amcache_patterns = [
            r'Amcache\.hve',  # Contains Amcache.hve (allows Amcache.hve.001, Amcache.hve.bak, etc.)
            r'AmCache\.hve',  # Contains AmCache.hve (allows AmCache.hve.001, AmCache.hve.bak, etc.)
            r'AMCACHE\.HVE'   # Contains AMCACHE.HVE (allows AMCACHE.HVE.001, AMCACHE.HVE.bak, etc.)
        ]
        
        # ShimCache (AppCompatCache) is inside SYSTEM hive - smart detection
        # Handles variations like SYSTEM, SYSTEM.001, SYSTEM.bak, etc.
        self.shimcache_patterns = [
            r'SYSTEM'  # Contains SYSTEM (allows SYSTEM.001, SYSTEM.bak, SYSTEM_001, etc.)
        ]
        
        # EVTX (Windows Event Log) filename patterns - smart detection
        # Handles variations like Security.evtx, Application.evtx, System.evtx, etc.
        self.evtx_patterns = [
            r'\.evtx$',  # .evtx extension (exact match)
            r'\.evt$',   # .evt extension (older format)
        ]
        
        # Common Windows Event Log names for type detection
        self.evtx_type_patterns = {
            'Security': r'Security',      # Security event log
            'System': r'System',          # System event log
            'Application': r'Application', # Application event log
            'Setup': r'Setup',            # Setup event log
            'ForwardedEvents': r'ForwardedEvents', # Forwarded events
            'Microsoft-Windows': r'Microsoft-Windows', # Windows component logs
            'Windows PowerShell': r'Windows PowerShell', # PowerShell logs
        }
        
        # SRUM (System Resource Usage Monitor) database patterns
        # Handles SRUM database files
        self.srum_patterns = [
            r'SRUDB\.dat$',  # SRUM database file
            r'SRU\.dat$',    # Alternative SRUM name
            r'SRUCHET\.dat$', # SRUM cheat database
        ]
        
        # Enhanced LNK file patterns - more comprehensive detection
        self.lnk_patterns = [
            r'\.lnk$',  # .lnk extension (exact match)
            r'\.url$',  # .url extension (internet shortcuts)
            r'\.pif$',  # .pif extension (program information files)
            r'\.scf$',  # .scf extension (shell command files)
        ]
    
    def detect_artifact_type(self, file_path: str) -> ArtifactDetectionResult:
        """
        Detect the type of artifact from a file.
        
        Uses ONLY filename and extension pattern matching for detection.
        Signature detection is disabled to prevent false positives with log files.
        
        Args:
            file_path: Path to the file to analyze
            
        Returns:
            ArtifactDetectionResult containing:
                - artifact_type: Detected type (Registry, Prefetch, etc.)
                - confidence: Detection confidence (0.0-1.0)
                - detection_method: How it was detected (filename, extension)
        """
        # Get file size
        try:
            file_size = os.path.getsize(file_path)
        except Exception:
            file_size = 0
        
        # ONLY use filename pattern matching - no signature detection
        # This prevents false positives with log files and other non-artifacts
        filename_result = self._check_filename(file_path)
        if filename_result:
            artifact_type, confidence = filename_result
            return ArtifactDetectionResult(
                file_path=file_path,
                artifact_type=artifact_type,
                confidence=confidence,
                detection_method='filename',
                file_size=file_size
            )
        
        # Unknown artifact type - not a Windows artifact
        return ArtifactDetectionResult(
            file_path=file_path,
            artifact_type='Unknown',
            confidence=0.0,
            detection_method='none',
            file_size=file_size
        )
    
    def _check_signature(self, file_path: str) -> Optional[Tuple[str, float]]:
        """
        Check file signature using FileSignatureDetector.
        
        Args:
            file_path: Path to the file to check
            
        Returns:
            Tuple of (artifact_type, confidence) or None if no match
        """
        try:
            desc, ext = self.signature_detector.detect_file_signature(file_path)
            
            # Map signature detection result to artifact type
            artifact_type = self._map_signature_to_artifact_type(ext, desc)
            
            if artifact_type:
                # Check if filename also matches for higher confidence
                filename_result = self._check_filename(file_path)
                if filename_result and filename_result[0] == artifact_type:
                    # Both signature and filename match - highest confidence
                    return artifact_type, 1.0
                else:
                    # Signature match only - high confidence
                    return artifact_type, 1.0
            
            return None
            
        except Exception:
            return None
    
    def _check_filename(self, file_path: str) -> Optional[Tuple[str, float]]:
        """
        Check filename pattern and return (artifact_type, confidence).
        Smart detection that handles variations, samples, and numbers.
        
        Args:
            file_path: Path to the file to check
            
        Returns:
            Tuple of (artifact_type, confidence) or None if no match
        """
        filename = os.path.basename(file_path)
        filename_upper = filename.upper()
        
        # Check EVTX patterns first (Windows Event Logs)
        for pattern in self.evtx_patterns:
            if re.search(pattern, filename, re.IGNORECASE):
                # Return normalized type "EVTX" for all event logs
                return 'EVTX', 0.9
        
        # Check SRUM patterns
        for pattern in self.srum_patterns:
            if re.search(pattern, filename, re.IGNORECASE):
                return 'SRUM', 0.9
        
        # Check AmCache patterns
        for pattern in self.amcache_patterns:
            if re.search(pattern, filename, re.IGNORECASE):
                return 'AmCache', 0.9
        
        # Check Registry patterns
        for pattern in self.registry_patterns:
            if re.search(pattern, filename, re.IGNORECASE):
                # Special case: SYSTEM file in shimcache directory should be ShimCache
                if 'SYSTEM' in filename_upper and 'shimcache' in file_path.lower():
                    return 'ShimCache', 0.9
                # Return normalized type "Registry" for all registry hives
                return 'Registry', 0.8
        
        # Check Prefetch pattern
        if re.search(self.prefetch_pattern, filename, re.IGNORECASE):
            return 'Prefetch', 0.9
        
        # Check Jump Lists patterns
        for pattern in self.jumplist_patterns:
            if re.search(pattern, filename, re.IGNORECASE):
                return 'link_jumplist', 0.9
        
        # Check LNK/Shortcut patterns (enhanced detection)
        # Map to JumpLists for parser compatibility
        for pattern in self.lnk_patterns:
            if re.search(pattern, filename, re.IGNORECASE):
                return 'link_jumplist', 0.9
        
        # Check MFT patterns
        for pattern in self.mft_patterns:
            if re.search(pattern, filename, re.IGNORECASE):
                return 'MFT', 0.9
        
        # Check USN patterns
        for pattern in self.usn_patterns:
            if re.search(pattern, filename, re.IGNORECASE):
                return 'USN', 0.9
        
        # Check Recycle Bin patterns
        for pattern in self.recyclebin_patterns:
            if re.search(pattern, filename, re.IGNORECASE):
                return 'RecycleBin', 0.9
        
        # Check ShimCache patterns
        for pattern in self.shimcache_patterns:
            if re.search(pattern, filename, re.IGNORECASE):
                return 'ShimCache', 0.8
        
        # Additional smart checks for variations
        
        # Check for EVTX variations
        if filename_upper.endswith('.EVTX') or filename_upper.endswith('.EVT'):
            # Return normalized type "EVTX" for all event logs
            return 'EVTX', 0.8
        
        # Check for SRUM variations
        if 'SRUM' in filename_upper or 'SRU' in filename_upper:
            return 'SRUM', 0.8
        
        # Check for LNK/Shortcut variations
        # Map to JumpLists for parser compatibility
        if any(ext in filename_upper for ext in ['.LNK', '.URL', '.PIF', '.SCF']):
            return 'link_jumplist', 0.8
        
        # Check for registry variations
        registry_keywords = ['NTUSER', 'SYSTEM', 'SOFTWARE', 'SAM', 'SECURITY', 'DEFAULT', 'COMPONENTS', 'BCD']
        for keyword in registry_keywords:
            if keyword in filename_upper:
                if any(ext in filename_upper for ext in ['.DAT', '.LOG', '.BAK', '.001', '.002']):
                    return 'Registry', 0.7
        
        # Check for MFT/USN variations
        if ('$MFT' in filename_upper or 'MFT' in filename_upper) and any(ext in filename_upper for ext in ['.BIN', '.001', '.BAK']):
            return 'MFT', 0.7
        
        if ('$USN' in filename_upper or 'USN' in filename_upper) and any(ext in filename_upper for ext in ['.BIN', '.001', '.BAK']):
            return 'USN', 0.7
        
        # Check for prefetch variations
        if '.PF' in filename_upper:
            return 'Prefetch', 0.7
        
        return None
    
    # Signature detection methods removed - using only filename/extension patterns for speed
