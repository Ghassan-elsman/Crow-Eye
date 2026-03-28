"""
Status Reporting for Collection Operations
==========================================

Reports collection status to user with access method details and real-time progress.

Requirements: 9.1, 9.2, 9.3, 9.4
"""

from typing import Optional, Callable


class StatusReporter:
    """
    Reports collection status to user with access method details.
    
    Provides real-time progress updates during collection, including:
    - Current artifact being processed
    - Access method being used (standard, VSS, raw disk)
    - Progress percentage
    - File counts and byte counts
    - Errors as they occur
    """

    def __init__(self, status_callback: Optional[Callable] = None):
        """
        Initialize status reporter.
        
        Args:
            status_callback: Optional callback function for status updates
        """
        self.status_callback = status_callback
        self.total_files_collected = 0
        self.total_bytes_collected = 0

    def set_status_callback(self, callback: Callable):
        """Set the status callback function."""
        self.status_callback = callback

    def display_status(self, message: str):
        """
        Display a status message with safe encoding for Windows console.
        
        Args:
            message: Status message to display
        """
        if self.status_callback:
            self.status_callback(message)
        else:
            try:
                print(message)
            except UnicodeEncodeError:
                # Fallback: replace problematic characters with ASCII equivalents
                safe_message = message.encode('ascii', 'replace').decode('ascii')
                print(safe_message)

    def report_artifact_collection(
        self,
        artifact_name: str,
        status: str,
        access_method: Optional[str] = None,
        progress_percent: int = 0
    ):
        """
        Report artifact collection progress with access method.
        
        Args:
            artifact_name: Name of the artifact being collected
            status: Current status (e.g., "Collecting...", "Complete", "Failed")
            access_method: Access method being used (standard, vss, raw_disk)
            progress_percent: Overall progress percentage
        """
        message = f"[{progress_percent}%] {artifact_name}: {status}"
        if access_method:
            method_display = self._format_access_method(access_method)
            message += f" (via {method_display})"
        
        self.display_status(message)

    def report_access_attempt(
        self,
        artifact_name: str,
        access_method: str,
        attempt_number: int = 1
    ):
        """
        Report access attempt in progress.
        
        Args:
            artifact_name: Name of the artifact
            access_method: Access method being attempted
            attempt_number: Attempt number (for retries)
        """
        method_display = self._format_access_method(access_method)
        message = f"Attempting {artifact_name} via {method_display}"
        if attempt_number > 1:
            message += f" (attempt {attempt_number})"
        
        self.display_status(message)

    def report_collection_complete(
        self,
        artifact_name: str,
        access_method: str,
        file_count: int,
        size: int
    ):
        """
        Report successful collection with method used.
        
        Args:
            artifact_name: Name of the artifact
            access_method: Access method that succeeded
            file_count: Number of files collected
            size: Total size in bytes
        """
        method_display = self._format_access_method(access_method)
        size_formatted = self.format_size(size)
        message = f"[OK] {artifact_name}: {file_count} files ({size_formatted}) via {method_display}"
        
        self.display_status(message)
        
        # Update totals
        self.total_files_collected += file_count
        self.total_bytes_collected += size

    def report_error(self, artifact_name: str, error_message: str):
        """
        Report an error immediately.
        
        Args:
            artifact_name: Name of the artifact
            error_message: Error message
        """
        message = f"[ERROR] {artifact_name}: {error_message}"
        self.display_status(message)

    def report_real_time_stats(self):
        """
        Report real-time collection statistics.
        
        Displays total files collected and total bytes collected.
        """
        size_formatted = self.format_size(self.total_bytes_collected)
        message = f"Progress: {self.total_files_collected} files ({size_formatted}) collected"
        self.display_status(message)

    def report_collection_summary(
        self,
        total_artifacts: int,
        successful: int,
        failed: int,
        duration_seconds: float,
        access_method_stats: Optional[dict] = None
    ):
        """
        Report collection completion summary.
        
        Args:
            total_artifacts: Total number of artifacts attempted
            successful: Number of successful collections
            failed: Number of failed collections
            duration_seconds: Total collection duration
            access_method_stats: Dictionary with counts per access method
        """
        self.display_status("\n" + "="*60)
        self.display_status("Collection Summary:")
        self.display_status(f"- Total Artifacts: {total_artifacts}")
        self.display_status(f"- Successful: {successful}")
        self.display_status(f"- Failed: {failed}")
        self.display_status(f"- Total Files: {self.total_files_collected}")
        self.display_status(f"- Total Size: {self.format_size(self.total_bytes_collected)}")
        self.display_status(f"- Duration: {duration_seconds:.2f} seconds")
        
        if access_method_stats:
            self.display_status("\nAccess Methods Used:")
            for method, count in access_method_stats.items():
                method_display = self._format_access_method(method)
                self.display_status(f"  * {method_display}: {count} artifacts")
        
        self.display_status("="*60)

    def _format_access_method(self, method: str) -> str:
        """
        Format access method for display.
        
        Args:
            method: Access method name (standard, vss, raw_disk)
            
        Returns:
            Formatted method name
        """
        method_map = {
            "standard": "Standard Copy",
            "vss": "VSS",
            "raw_disk": "Raw Disk Access",
            "": "Unknown"
        }
        return method_map.get(method.lower(), method)

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

    def reset_stats(self):
        """Reset collection statistics."""
        self.total_files_collected = 0
        self.total_bytes_collected = 0
