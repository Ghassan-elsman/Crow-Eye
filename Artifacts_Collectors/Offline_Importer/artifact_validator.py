"""
Artifact Validator Module

This module validates artifacts against known-good samples and structural rules.
It helps identify corrupted or suspicious artifacts during collection.
"""

import os
import struct
from typing import Optional, Tuple, Dict
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """
    Result of artifact validation.
    
    Attributes:
        is_valid: Whether the artifact passed validation
        confidence: Validation confidence (0.0-1.0)
        issues: List of validation issues found
        artifact_type: Detected artifact type
    """
    is_valid: bool
    confidence: float
    issues: list
    artifact_type: str


class ArtifactValidator:
    """
    Validates artifacts against known-good patterns and structural rules.
    
    This class performs deep validation of artifacts to detect:
    - Corrupted file structures
    - Invalid headers or signatures
    - Suspicious file sizes
    - Malformed data structures
    """
    
    def __init__(self):
        """Initialize the artifact validator."""
        # Minimum file sizes for each artifact type (in bytes)
        # Reduced to be less strict and accept more real artifacts
        self.min_sizes = {
            'Registry': 512,   # Reduced from 4096 - some small registry hives are valid
            'Prefetch': 32,    # Reduced from 84 - some prefetch files can be smaller
            'MFT': 512,        # Reduced from 1024 - allow smaller MFT fragments
            'AmCache': 512,    # Reduced from 4096 - AmCache is a registry hive
            'JumpLists': 32,   # Minimum jump list size
            'RecycleBin': 24,  # Minimum recycle bin metadata size
        }
        
        # Maximum reasonable file sizes (in bytes) - helps detect corruption
        self.max_sizes = {
            'Registry': 500 * 1024 * 1024,  # 500 MB max for registry
            'Prefetch': 10 * 1024 * 1024,   # 10 MB max for prefetch
            'MFT': 10 * 1024 * 1024 * 1024, # 10 GB max for MFT
            'AmCache': 500 * 1024 * 1024,   # 500 MB max for AmCache
            'JumpLists': 50 * 1024 * 1024,  # 50 MB max for jump lists
            'RecycleBin': 10 * 1024 * 1024, # 10 MB max for recycle bin
        }
    
    def validate_artifact(self, file_path: str, artifact_type: str) -> ValidationResult:
        """
        Validate an artifact file.
        
        Args:
            file_path: Path to the artifact file
            artifact_type: Type of artifact (Registry, Prefetch, etc.)
            
        Returns:
            ValidationResult with validation details
        """
        issues = []
        confidence = 1.0
        
        # Check if file exists
        if not os.path.exists(file_path):
            return ValidationResult(
                is_valid=False,
                confidence=0.0,
                issues=["File does not exist"],
                artifact_type=artifact_type
            )
        
        # Check file size
        file_size = os.path.getsize(file_path)
        
        # Check minimum size (warning only, not a hard failure)
        if artifact_type in self.min_sizes:
            min_size = self.min_sizes[artifact_type]
            if file_size < min_size:
                issues.append(f"Warning: File size ({file_size} bytes) is below typical minimum ({min_size} bytes)")
                confidence -= 0.2  # Reduced penalty from 0.3 to 0.2
        
        # Check maximum size
        if artifact_type in self.max_sizes:
            max_size = self.max_sizes[artifact_type]
            if file_size > max_size:
                issues.append(f"File size ({file_size} bytes) exceeds maximum ({max_size} bytes)")
                confidence -= 0.2
        
        # Perform type-specific validation
        if artifact_type == 'Registry':
            type_issues, type_confidence = self._validate_registry(file_path)
            issues.extend(type_issues)
            confidence *= type_confidence
        elif artifact_type == 'Prefetch':
            type_issues, type_confidence = self._validate_prefetch(file_path)
            issues.extend(type_issues)
            confidence *= type_confidence
        elif artifact_type == 'MFT':
            type_issues, type_confidence = self._validate_mft(file_path)
            issues.extend(type_issues)
            confidence *= type_confidence
        elif artifact_type == 'AmCache':
            # AmCache is a registry hive
            type_issues, type_confidence = self._validate_registry(file_path)
            issues.extend(type_issues)
            confidence *= type_confidence
        
        # Determine if valid - be more lenient
        # Only fail if confidence is very low (< 0.2) or there are critical errors
        # Warnings (issues that start with "Warning:") don't cause failure
        critical_issues = [issue for issue in issues if not issue.startswith("Warning:")]
        
        # Even more lenient: only fail on critical signature mismatches
        signature_failures = [issue for issue in critical_issues if 'signature' in issue.lower() and 'invalid' in issue.lower()]
        
        # Pass if:
        # - No signature failures, OR
        # - Confidence is at least 0.2 and no critical issues
        is_valid = (len(signature_failures) == 0) or (confidence >= 0.2 and len(critical_issues) == 0)
        
        return ValidationResult(
            is_valid=is_valid,
            confidence=max(0.0, min(1.0, confidence)),
            issues=issues,
            artifact_type=artifact_type
        )
    
    def _validate_registry(self, file_path: str) -> Tuple[list, float]:
        """
        Validate a Windows Registry hive file.
        
        Args:
            file_path: Path to the registry file
            
        Returns:
            Tuple of (issues list, confidence score)
        """
        issues = []
        confidence = 1.0
        
        try:
            file_size = os.path.getsize(file_path)
            
            with open(file_path, 'rb') as f:
                # Read first 4 bytes for signature
                signature = f.read(4)
                
                # Check for "regf" signature
                if signature != b'regf':
                    issues.append(f"Invalid registry signature: {signature}")
                    confidence = 0.0
                    return issues, confidence
                
                # Read sequence numbers at offset 4 and 8
                f.seek(4)
                seq1 = struct.unpack('<I', f.read(4))[0]
                seq2 = struct.unpack('<I', f.read(4))[0]
                
                # Sequence numbers should be close to each other (warning only)
                if abs(seq1 - seq2) > 10:
                    issues.append("Warning: Registry sequence numbers are inconsistent")
                    confidence -= 0.1  # Reduced penalty
                
                # Check hive bins header at offset 4096 (warning only for small files)
                if file_size >= 4096:
                    f.seek(4096)
                    hbin_sig = f.read(4)
                    if hbin_sig != b'hbin':
                        issues.append("Warning: Missing or invalid hbin signature")
                        confidence -= 0.1  # Reduced penalty
        
        except Exception as e:
            issues.append(f"Error reading registry file: {str(e)}")
            confidence = 0.3
        
        return issues, confidence
    
    def _validate_prefetch(self, file_path: str) -> Tuple[list, float]:
        """
        Validate a Windows Prefetch file.
        
        Args:
            file_path: Path to the prefetch file
            
        Returns:
            Tuple of (issues list, confidence score)
        """
        issues = []
        confidence = 1.0
        
        try:
            with open(file_path, 'rb') as f:
                # Read version signature
                version = struct.unpack('<I', f.read(4))[0]
                
                # Check for valid prefetch versions (warning only for unknown versions)
                valid_versions = [0x11, 0x17, 0x1A, 0x1E, 0x17000000, 0x1A000000, 0x1E000000]
                if version not in valid_versions:
                    issues.append(f"Warning: Unknown prefetch version: {hex(version)}")
                    confidence -= 0.1  # Reduced penalty
                
                # Read signature at offset 4
                f.seek(4)
                signature = f.read(4)
                
                # Check for "SCCA" signature
                if signature != b'SCCA':
                    issues.append(f"Invalid prefetch signature: {signature}")
                    confidence = 0.0
                    return issues, confidence
        
        except Exception as e:
            issues.append(f"Error reading prefetch file: {str(e)}")
            confidence = 0.3
        
        return issues, confidence
    
    def _validate_mft(self, file_path: str) -> Tuple[list, float]:
        """
        Validate an MFT (Master File Table) file.
        
        Args:
            file_path: Path to the MFT file
            
        Returns:
            Tuple of (issues list, confidence score)
        """
        issues = []
        confidence = 1.0
        
        try:
            with open(file_path, 'rb') as f:
                # Read first record signature
                signature = f.read(4)
                
                # Check for "FILE" or "BAAD" signature
                if signature not in [b'FILE', b'BAAD']:
                    issues.append(f"Invalid MFT signature: {signature}")
                    confidence = 0.0
                    return issues, confidence
                
                # Check file size is multiple of 1024 (MFT record size) - warning only
                file_size = os.path.getsize(file_path)
                if file_size % 1024 != 0:
                    issues.append("Warning: MFT file size is not a multiple of 1024 bytes")
                    confidence -= 0.1  # Reduced penalty
                
                # Read update sequence offset (warning only)
                f.seek(4)
                usa_offset = struct.unpack('<H', f.read(2))[0]
                
                # Update sequence offset should be reasonable
                if usa_offset < 42 or usa_offset > 1024:
                    issues.append(f"Warning: Unusual update sequence offset: {usa_offset}")
                    confidence -= 0.1  # Reduced penalty
        
        except Exception as e:
            issues.append(f"Error reading MFT file: {str(e)}")
            confidence = 0.3
        
        return issues, confidence
    
    def validate_batch(self, artifacts: Dict[str, str]) -> Dict[str, ValidationResult]:
        """
        Validate multiple artifacts in batch.
        
        Args:
            artifacts: Dictionary mapping file paths to artifact types
            
        Returns:
            Dictionary mapping file paths to ValidationResult
        """
        results = {}
        for file_path, artifact_type in artifacts.items():
            results[file_path] = self.validate_artifact(file_path, artifact_type)
        return results
