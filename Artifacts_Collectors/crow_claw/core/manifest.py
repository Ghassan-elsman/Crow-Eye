"""
Collection Manifest Generation
===============================

Creates and manages collection manifests in JSON format.
Tracks all collected artifacts and their metadata.

Phase 4: Manifest Generation
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List


class CollectionManifest:
    """
    Represents a complete collection manifest.

    Contains all metadata about a forensic artifact collection operation.
    """

    def __init__(
        self,
        case_name: str,
        case_path: str,
        collector_version: str = "1.0"
    ):
        """
        Initialize manifest.

        Args:
            case_name: Name of the forensic case
            case_path: Root directory for case
            collector_version: Version of Crow-Claw
        """
        self.case_name = case_name
        self.case_path = case_path
        self.collector_version = collector_version
        self.timestamp = datetime.now().isoformat()

        self.artifacts: List[Dict[str, Any]] = []
        self.collection_start_time: Optional[str] = None
        self.collection_end_time: Optional[str] = None
        self.total_artifacts = 0
        self.successful_artifacts = 0
        self.failed_artifacts = 0
        self.total_size = 0
        self.warnings: List[str] = []
        self.errors: List[str] = []
        
        # Enhanced fields for validation and system info
        self.system_info: Dict[str, Any] = {}
        self.validation_errors: List[Dict[str, Any]] = []
        self.validation_warnings: List[Dict[str, Any]] = []
        self.access_method_stats: Dict[str, int] = {
            "standard": 0,
            "vss": 0,
            "raw_disk": 0
        }

    def add_artifact(
        self,
        artifact_name: str,
        artifact_type: str,
        source_paths: List[str],
        dest_path: str,
        status: str,
        files_collected: int,
        bytes_collected: int,
        errors: List[str],
        duration_seconds: float = 0.0
    ):
        """
        Add artifact record to manifest.

        Args:
            artifact_name: Human-readable artifact name
            artifact_type: Artifact type (registry, prefetch, etc.)
            source_paths: List of source paths collected from
            dest_path: Destination path where collected
            status: Collection status (success, partial_success, failed)
            files_collected: Number of files collected
            bytes_collected: Total bytes collected
            errors: List of error messages
            duration_seconds: Collection duration in seconds
        """
        artifact_record = {
            "type": artifact_type,
            "name": artifact_name,
            "source_paths": source_paths,
            "dest_path": dest_path,
            "status": status,
            "files_collected": files_collected,
            "bytes_collected": bytes_collected,
            "size_formatted": self.format_size(bytes_collected),
            "errors": errors,
            "timestamp": datetime.now().isoformat(),
            "duration_seconds": duration_seconds
        }

        self.artifacts.append(artifact_record)
        self.total_artifacts += 1
        self.total_size += bytes_collected

        if status == "success":
            self.successful_artifacts += 1
        elif status == "partial_success":
            self.successful_artifacts += 1
        elif errors:
            self.failed_artifacts += 1

    def add_artifact_with_validation(
        self,
        artifact_name: str,
        artifact_type: str,
        source_paths: List[str],
        dest_path: str,
        status: str,
        files_collected: int,
        bytes_collected: int,
        errors: List[str],
        duration_seconds: float = 0.0,
        access_method: str = "standard",
        attempts: int = 1,
        vss_shadow_copy_id: Optional[str] = None,
        vss_timestamp: Optional[str] = None,
        md5_hash: Optional[str] = None,
        sha256_hash: Optional[str] = None,
        signature_valid: Optional[bool] = None,
        validation_warnings: Optional[List[str]] = None,
        validation_errors: Optional[List[str]] = None
    ):
        """
        Add artifact with full access and validation details.
        
        Args:
            artifact_name: Human-readable artifact name
            artifact_type: Artifact type (registry, prefetch, etc.)
            source_paths: List of source paths collected from
            dest_path: Destination path where collected
            status: Collection status (success, partial_success, failed)
            files_collected: Number of files collected
            bytes_collected: Total bytes collected
            errors: List of error messages
            duration_seconds: Collection duration in seconds
            access_method: Access method used (standard, vss, raw_disk)
            attempts: Number of attempts required
            vss_shadow_copy_id: VSS shadow copy ID if VSS was used
            vss_timestamp: VSS shadow copy timestamp if VSS was used
            md5_hash: MD5 hash of collected file(s)
            sha256_hash: SHA256 hash of collected file(s)
            signature_valid: Whether signature validation passed
            validation_warnings: List of validation warnings
            validation_errors: List of validation errors
        """
        artifact_record = {
            "type": artifact_type,
            "name": artifact_name,
            "source_paths": source_paths,
            "dest_path": dest_path,
            "status": status,
            "files_collected": files_collected,
            "bytes_collected": bytes_collected,
            "size_formatted": self.format_size(bytes_collected),
            "errors": errors,
            "timestamp": datetime.now().isoformat(),
            "duration_seconds": duration_seconds,
            "access_method": access_method,
            "attempts": attempts,
            "vss_shadow_copy_id": vss_shadow_copy_id,
            "vss_timestamp": vss_timestamp,
            "md5_hash": md5_hash,
            "sha256_hash": sha256_hash,
            "signature_valid": signature_valid,
            "validation_warnings": validation_warnings or [],
            "validation_errors": validation_errors or []
        }

        self.artifacts.append(artifact_record)
        self.total_artifacts += 1
        self.total_size += bytes_collected

        # Update access method statistics
        if access_method in self.access_method_stats:
            self.access_method_stats[access_method] += 1

        # Track validation issues
        if validation_warnings:
            for warning in validation_warnings:
                self.validation_warnings.append({
                    "artifact": artifact_name,
                    "warning": warning
                })
        
        if validation_errors:
            for error in validation_errors:
                self.validation_errors.append({
                    "artifact": artifact_name,
                    "error": error
                })

        if status == "success":
            self.successful_artifacts += 1
        elif status == "partial_success":
            self.successful_artifacts += 1
        elif errors:
            self.failed_artifacts += 1

    def add_warning(self, warning: str):
        """Add a warning message."""
        self.warnings.append(warning)

    def add_error(self, error: str):
        """Add an error message."""
        self.errors.append(error)

    def add_system_info(self, system_info: Dict[str, Any]):
        """
        Add system information to manifest.
        
        Args:
            system_info: Dictionary containing system information:
                - windows_version: Windows version string
                - hostname: System hostname
                - is_admin: Whether running with admin privileges
                - vss_available: Whether VSS is available
                - vss_shadow_copies: List of available shadow copies
        """
        self.system_info = {
            "windows_version": system_info.get("windows_version", "Unknown"),
            "hostname": system_info.get("hostname", "Unknown"),
            "is_admin": system_info.get("is_admin", False),
            "vss_available": system_info.get("vss_available", False),
            "vss_shadow_copies": system_info.get("vss_shadow_copies", []),
            "platform_info": system_info.get("platform_info", {})
        }

    def set_collection_times(self, start_time: datetime, end_time: datetime):
        """Set collection start and end times."""
        self.collection_start_time = start_time.isoformat()
        self.collection_end_time = end_time.isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert manifest to dictionary.

        Returns:
            Dictionary representation of manifest
        """
        return {
            "collection_info": {
                "case_name": self.case_name,
                "case_path": self.case_path,
                "collector_version": self.collector_version,
                "manifest_timestamp": self.timestamp,
                "collection_start_time": self.collection_start_time,
                "collection_end_time": self.collection_end_time,
            },
            "system_info": self.system_info,
            "collection_summary": {
                "total_artifacts": self.total_artifacts,
                "successful_artifacts": self.successful_artifacts,
                "failed_artifacts": self.failed_artifacts,
                "total_size_bytes": self.total_size,
                "total_size_formatted": self.format_size(self.total_size),
                "warnings_count": len(self.warnings),
                "errors_count": len(self.errors),
                "validation_errors_count": len(self.validation_errors),
                "validation_warnings_count": len(self.validation_warnings),
                "status": self.get_status(),
                "access_method_stats": self.access_method_stats
            },
            "artifacts": self.artifacts,
            "warnings": self.warnings,
            "errors": self.errors,
            "validation": {
                "errors": self.validation_errors,
                "warnings": self.validation_warnings
            },
            "next_steps": self.get_next_steps()
        }

    def to_json(self, indent: int = 2) -> str:
        """
        Convert manifest to JSON string.

        Args:
            indent: JSON indentation level

        Returns:
            JSON string representation
        """
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def save(self, output_path: str) -> bool:
        """
        Save manifest to JSON file.

        Args:
            output_path: Path to save manifest to

        Returns:
            True if saved successfully
        """
        try:
            # Ensure directory exists
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            # Write manifest
            with open(output_path, 'w') as f:
                f.write(self.to_json())

            return True
        except Exception as e:
            print(f"Error saving manifest: {e}")
            return False

    @staticmethod
    def load(manifest_path: str) -> Optional['CollectionManifest']:
        """
        Load manifest from JSON file.

        Args:
            manifest_path: Path to manifest file

        Returns:
            CollectionManifest object or None if error
        """
        try:
            with open(manifest_path, 'r') as f:
                data = json.load(f)

            # Create manifest object
            collection_info = data.get("collection_info", {})
            manifest = CollectionManifest(
                case_name=collection_info.get("case_name", "Unknown"),
                case_path=collection_info.get("case_path", ""),
                collector_version=collection_info.get("collector_version", "1.0")
            )

            # Restore timestamps
            manifest.timestamp = collection_info.get("manifest_timestamp", "")
            manifest.collection_start_time = collection_info.get("collection_start_time")
            manifest.collection_end_time = collection_info.get("collection_end_time")

            # Restore summary info
            summary = data.get("collection_summary", {})
            manifest.total_artifacts = summary.get("total_artifacts", 0)
            manifest.successful_artifacts = summary.get("successful_artifacts", 0)
            manifest.failed_artifacts = summary.get("failed_artifacts", 0)
            manifest.total_size = summary.get("total_size_bytes", 0)
            manifest.access_method_stats = summary.get("access_method_stats", {
                "standard": 0,
                "vss": 0,
                "raw_disk": 0
            })

            # Restore system info
            manifest.system_info = data.get("system_info", {})

            # Restore artifacts
            manifest.artifacts = data.get("artifacts", [])

            # Restore warnings and errors
            manifest.warnings = data.get("warnings", [])
            manifest.errors = data.get("errors", [])
            
            # Restore validation info
            validation = data.get("validation", {})
            manifest.validation_errors = validation.get("errors", [])
            manifest.validation_warnings = validation.get("warnings", [])

            return manifest

        except Exception as e:
            print(f"Error loading manifest: {e}")
            return None

    def get_status(self) -> str:
        """
        Get overall collection status.

        Returns:
            Status string (success, partial_success, failed)
        """
        if self.total_artifacts == 0:
            return "not_started"
        elif self.failed_artifacts == 0:
            return "success"
        elif self.successful_artifacts > 0:
            return "partial_success"
        else:
            return "failed"

    def get_next_steps(self) -> List[str]:
        """
        Get recommended next steps.

        Returns:
            List of next steps
        """
        steps = []

        if self.get_status() == "success":
            steps.append("All artifacts collected successfully.")
            steps.append("Run offline parsers to analyze collected artifacts:")
            steps.append("  - offlineRegClaw.py for Registry analysis")
            steps.append("  - offlineACJL.py for Jump Lists/LNK analysis")
            steps.append("  - Other specialized parsers for specific artifact types")
        elif self.get_status() == "partial_success":
            steps.append("Some artifacts were collected successfully.")
            steps.append("Review errors above for collection issues.")
            steps.append("Run offline parsers on successfully collected artifacts.")
        else:
            steps.append("Collection failed. Check errors above.")
            steps.append("Verify:")
            steps.append("  - Admin privileges are enabled for protected artifacts")
            steps.append("  - Output directory is writable")
            steps.append("  - Source paths are correct")
            steps.append("  - Sufficient disk space available")

        return steps

    @staticmethod
    def format_size(bytes_size: int) -> str:
        """
        Format bytes to human-readable size.

        Args:
            bytes_size: Size in bytes

        Returns:
            Formatted size string
        """
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.2f} PB"

    def generate_html_report(self) -> str:
        """
        Generate HTML report of collection.

        Returns:
            HTML string
        """
        html = """
<!DOCTYPE html>
<html>
<head>
    <title>Crow-Claw Collection Report</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background-color: #0F172A;
            color: #FFFFFF;
            margin: 20px;
        }
        h1, h2 {
            color: #00FFFF;
        }
        table {
            border-collapse: collapse;
            width: 100%;
            margin-top: 20px;
        }
        th, td {
            border: 1px solid #00FFFF;
            padding: 10px;
            text-align: left;
        }
        th {
            background-color: #1E293B;
        }
        .success {
            color: #10B981;
        }
        .failed {
            color: #EF4444;
        }
        .warning {
            color: #F59E0B;
        }
        .summary {
            background-color: #1E293B;
            padding: 15px;
            border-radius: 4px;
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <h1>Crow-Claw Collection Report</h1>
    <div class="summary">
        <h2>Collection Summary</h2>
        <p><b>Case Name:</b> {case_name}</p>
        <p><b>Timestamp:</b> {timestamp}</p>
        <p><b>Status:</b> <span class="{status_class}">{status}</span></p>
        <p><b>Total Artifacts:</b> {total_artifacts}</p>
        <p><b>Successful:</b> <span class="success">{successful}</span></p>
        <p><b>Failed:</b> <span class="failed">{failed}</span></p>
        <p><b>Total Size:</b> {size}</p>
    </div>

    <h2>Artifact Details</h2>
    <table>
        <tr>
            <th>Artifact Name</th>
            <th>Type</th>
            <th>Status</th>
            <th>Files</th>
            <th>Size</th>
        </tr>
"""

        for artifact in self.artifacts:
            status_class = "success" if artifact["status"] == "success" else "failed"
            html += f"""
        <tr>
            <td>{artifact['name']}</td>
            <td>{artifact['type']}</td>
            <td><span class="{status_class}">{artifact['status']}</span></td>
            <td>{artifact['files_collected']}</td>
            <td>{artifact['size_formatted']}</td>
        </tr>
"""

        html += """
    </table>
</body>
</html>
"""

        status_class = "success" if self.get_status() == "success" else "failed"
        html = html.format(
            case_name=self.case_name,
            timestamp=self.collection_end_time or self.timestamp,
            status=self.get_status().upper(),
            status_class=status_class,
            total_artifacts=self.total_artifacts,
            successful=self.successful_artifacts,
            failed=self.failed_artifacts,
            size=self.format_size(self.total_size)
        )

        return html
