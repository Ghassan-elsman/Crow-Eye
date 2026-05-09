"""
Case Directory Manager for EYE Forensic Report System.

This module manages report exports to case directories with automatic organization
and indexing. It creates a Reports subdirectory within forensic case directories
and maintains a JSON index of all generated reports.

"""

import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional


class CaseDirectoryManager:
    """
    Manages report exports to case directory with automatic organization.
    
    This class handles:
    - Creating Reports subdirectory in case directories
    - Generating standardized report filenames with timestamps
    - Maintaining a reports_index.json file with metadata
    - Listing all reports in a case directory
    
    """
    
    def __init__(self, case_directory: str):
        """
        Initialize case directory manager.
        
        Args:
            case_directory: Root directory of the forensic case
        """
        self.case_directory = case_directory
        self.reports_dir = os.path.join(case_directory, "Reports")
        self.logs_dir = os.path.join(case_directory, "EYE_Logs")
        self.index_file = os.path.join(self.reports_dir, "reports_index.json")
    
    def ensure_reports_directory(self) -> None:
        """
        Create Reports subdirectory if it doesn't exist.
        """
        os.makedirs(self.reports_dir, exist_ok=True)
    
    def ensure_logs_directory(self) -> None:
        """
        Create EYE_Logs subdirectory if it doesn't exist.
        """
        os.makedirs(self.logs_dir, exist_ok=True)
    
    def generate_report_filename(
        self,
        case_number: str,
        report_type: str,
        extension: str
    ) -> str:
        """
        Generate standardized report filename.
        
        Creates a filename in the format:
        {case_number}_{report_type}_{timestamp}.{extension}
        
        The timestamp is in ISO 8601 format (YYYYMMDDTHHMMSS) to ensure
        chronological sorting and uniqueness.
        
        Args:
            case_number: Case identifier (e.g., "CASE001")
            report_type: Type of report (e.g., "executive_summary", "technical_analysis")
            extension: File extension without dot (e.g., "html", "pdf", "md")
            
        Returns:
            Filename in format: {case_number}_{report_type}_{timestamp}.{extension}
            Example: "CASE001_executive_summary_20240515T143022.pdf"
        
        """
        timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        return f"{case_number}_{report_type}_{timestamp}.{extension}"
    
    def get_report_path(
        self,
        case_number: str,
        report_type: str,
        extension: str
    ) -> str:
        """
        Get full path for report export.
        
        Combines the Reports directory path with a generated filename
        to produce the complete file path for report export.
        
        Args:
            case_number: Case identifier
            report_type: Type of report
            extension: File extension without dot
            
        Returns:
            Full path to report file in Reports directory
            Example: "/path/to/case/Reports/CASE001_executive_summary_20240515T143022.pdf"
        
        """
        filename = self.generate_report_filename(case_number, report_type, extension)
        return os.path.join(self.reports_dir, filename)
    
    def update_report_index(
        self,
        report_metadata: Dict[str, Any]
    ) -> None:
        """
        Update reports_index.json with new report metadata.
        
        This method maintains a JSON index file that tracks all reports
        generated for the case. If the index file doesn't exist, it creates
        a new one. The index is stored as a list of report metadata dictionaries.
        
        Args:
            report_metadata: Dictionary with report information containing:
                - filename: Report filename (required)
                - case_number: Case identifier (required)
                - report_type: Type of report (required)
                - timestamp: ISO 8601 timestamp (required)
                - format: File format (html, pdf, md) (required)
                - file_size: File size in bytes (optional)
                - investigator: Investigator name (optional)
                - Additional custom fields as needed
                
        Example:
            {
                "filename": "CASE001_executive_summary_20240515T143022.pdf",
                "case_number": "CASE001",
                "report_type": "executive_summary",
                "timestamp": "2024-05-15T14:30:22",
                "format": "pdf",
                "file_size": 2048576,
                "investigator": "John Doe"
            }
        
        """
        # Ensure Reports directory exists
        self.ensure_reports_directory()
        
        # Load existing index or create new one (resilient to corruption)
        index_data = []
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    if isinstance(loaded, list):
                        index_data = loaded
            except (json.JSONDecodeError, IOError):
                # Corrupted index — start fresh but preserve the old file
                import logging
                logging.getLogger(__name__).warning(
                    f"reports_index.json is corrupted. Starting fresh index."
                )
        
        # Append new report metadata
        index_data.append(report_metadata)
        
        # Write updated index back to file
        with open(self.index_file, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, indent=2, ensure_ascii=False)
    
    def list_reports(self) -> List[Dict[str, Any]]:
        """
        List all reports in the case directory.
        
        Reads the reports_index.json file and returns all report metadata.
        If the index file doesn't exist, returns an empty list.
        
        Returns:
            List of report metadata dictionaries from reports_index.json.
            Each dictionary contains the metadata that was stored when the
            report was created (filename, case_number, report_type, timestamp, etc.)
            Returns empty list if no reports exist.
        
        """
        if not os.path.exists(self.index_file):
            return []
        
        try:
            with open(self.index_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError):
            return []
