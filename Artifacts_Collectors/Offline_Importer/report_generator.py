"""
Report Generator Module

This module generates collection reports in HTML and PDF formats.
Reports include collection summary, artifact details, and statistics.
"""

import os
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from .collection_coordinator import CollectionSummary
    from .artifact_collector import CollectedArtifactInfo


class ReportGenerator:
    """
    Generates collection reports in HTML and PDF formats.
    
    This class creates detailed reports of artifact collection sessions,
    including summary statistics, artifact details, and error information.
    """
    
    def __init__(self, case_root: str):
        """
        Initialize the report generator.
        
        Args:
            case_root: Root directory of the case
        """
        self.case_root = case_root
        self.reports_dir = os.path.join(case_root, 'reports')
        os.makedirs(self.reports_dir, exist_ok=True)
    
    def generate_html_report(self, summary: "CollectionSummary", 
                            errors: List[str] = None,
                            warnings: List[str] = None) -> str:
        """
        Generate an HTML report of the collection session.
        
        Args:
            summary: Collection summary with artifact details
            errors: List of error messages
            warnings: List of warning messages
            
        Returns:
            Path to the generated HTML report file
        """
        errors = errors or []
        warnings = warnings or []
        
        # Generate report filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"collection_report_{timestamp}.html"
        report_path = os.path.join(self.reports_dir, report_filename)
        
        # Generate HTML content
        html_content = self._generate_html_content(summary, errors, warnings)
        
        # Write to file
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return report_path
    
    def _generate_html_content(self, summary: "CollectionSummary",
                               errors: List[str],
                               warnings: List[str]) -> str:
        """
        Generate the HTML content for the report.
        
        Args:
            summary: Collection summary
            errors: List of errors
            warnings: List of warnings
            
        Returns:
            HTML content as string
        """
        # Calculate statistics
        success_count = sum(1 for a in summary.artifacts if a.collection_status == "success")
        failed_count = sum(1 for a in summary.artifacts if a.collection_status == "failed")
        duplicate_count = sum(1 for a in summary.artifacts if a.collection_status == "skipped_duplicate")
        
        # Group artifacts by type
        artifacts_by_type = {}
        for artifact in summary.artifacts:
            if artifact.artifact_type not in artifacts_by_type:
                artifacts_by_type[artifact.artifact_type] = []
            artifacts_by_type[artifact.artifact_type].append(artifact)
        
        # Build HTML
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Artifact Collection Report</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 30px;
            border-bottom: 2px solid #ecf0f1;
            padding-bottom: 5px;
        }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }}
        .summary-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .summary-card.success {{
            background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
        }}
        .summary-card.failed {{
            background: linear-gradient(135deg, #eb3349 0%, #f45c43 100%);
        }}
        .summary-card.duplicate {{
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        }}
        .summary-card h3 {{
            margin: 0 0 10px 0;
            font-size: 14px;
            opacity: 0.9;
        }}
        .summary-card .value {{
            font-size: 32px;
            font-weight: bold;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #3498db;
            color: white;
            font-weight: bold;
        }}
        tr:hover {{
            background-color: #f5f5f5;
        }}
        .status-success {{
            color: #27ae60;
            font-weight: bold;
        }}
        .status-failed {{
            color: #e74c3c;
            font-weight: bold;
        }}
        .status-duplicate {{
            color: #f39c12;
            font-weight: bold;
        }}
        .error-list, .warning-list {{
            background-color: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            margin: 10px 0;
        }}
        .error-list {{
            background-color: #f8d7da;
            border-left-color: #dc3545;
        }}
        .error-list li, .warning-list li {{
            margin: 5px 0;
        }}
        .metadata {{
            background-color: #ecf0f1;
            padding: 15px;
            border-radius: 5px;
            margin: 20px 0;
        }}
        .metadata p {{
            margin: 5px 0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Artifact Collection Report</h1>
        
        <div class="metadata">
            <p><strong>Case:</strong> {os.path.basename(self.case_root)}</p>
            <p><strong>Collection Start:</strong> {summary.start_time.strftime("%Y-%m-%d %H:%M:%S")}</p>
            <p><strong>Collection End:</strong> {summary.end_time.strftime("%Y-%m-%d %H:%M:%S")}</p>
            <p><strong>Duration:</strong> {summary.collection_time:.2f} seconds</p>
        </div>
        
        <h2>Summary Statistics</h2>
        <div class="summary-grid">
            <div class="summary-card">
                <h3>Total Found</h3>
                <div class="value">{summary.total_found}</div>
            </div>
            <div class="summary-card success">
                <h3>Successfully Collected</h3>
                <div class="value">{success_count}</div>
            </div>
            <div class="summary-card failed">
                <h3>Failed</h3>
                <div class="value">{failed_count}</div>
            </div>
            <div class="summary-card duplicate">
                <h3>Skipped (Duplicates)</h3>
                <div class="value">{duplicate_count}</div>
            </div>
        </div>
"""
        
        # Add artifacts by type section
        html += "<h2>Artifacts by Type</h2>\n"
        for artifact_type, artifacts in sorted(artifacts_by_type.items()):
            html += f"<h3>{artifact_type} ({len(artifacts)} artifacts)</h3>\n"
            html += "<table>\n"
            html += "<tr><th>Source Path</th><th>Status</th><th>Size</th><th>Hash</th></tr>\n"
            
            for artifact in artifacts:
                status_class = f"status-{artifact.collection_status.replace('_', '-')}"
                size_mb = artifact.file_size / (1024 * 1024)
                hash_short = artifact.file_hash[:16] + "..." if artifact.file_hash else "N/A"
                
                html += f"<tr>\n"
                html += f"  <td>{artifact.source_path}</td>\n"
                html += f"  <td class='{status_class}'>{artifact.collection_status}</td>\n"
                html += f"  <td>{size_mb:.2f} MB</td>\n"
                html += f"  <td>{hash_short}</td>\n"
                html += f"</tr>\n"
            
            html += "</table>\n"
        
        # Add errors section
        if errors:
            html += "<h2>Errors</h2>\n"
            html += "<ul class='error-list'>\n"
            for error in errors:
                html += f"  <li>{error}</li>\n"
            html += "</ul>\n"
        
        # Add warnings section
        if warnings:
            html += "<h2>Warnings</h2>\n"
            html += "<ul class='warning-list'>\n"
            for warning in warnings:
                html += f"  <li>{warning}</li>\n"
            html += "</ul>\n"
        
        html += """
    </div>
</body>
</html>
"""
        
        return html
    
    def generate_pdf_report(self, summary: "CollectionSummary",
                           errors: List[str] = None,
                           warnings: List[str] = None) -> Optional[str]:
        """
        Generate a PDF report of the collection session.
        
        This method requires the 'weasyprint' library to be installed.
        If not available, it will return None and log a warning.
        
        Args:
            summary: Collection summary with artifact details
            errors: List of error messages
            warnings: List of warning messages
            
        Returns:
            Path to the generated PDF report file, or None if PDF generation failed
        """
        try:
            # Try to import weasyprint
            from weasyprint import HTML
        except ImportError:
            print("Warning: weasyprint not installed. PDF generation not available.")
            print("Install with: pip install weasyprint")
            return None
        
        # Generate HTML first
        html_content = self._generate_html_content(summary, errors, warnings)
        
        # Generate PDF filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_filename = f"collection_report_{timestamp}.pdf"
        pdf_path = os.path.join(self.reports_dir, pdf_filename)
        
        try:
            # Convert HTML to PDF
            HTML(string=html_content).write_pdf(pdf_path)
            return pdf_path
        except Exception as e:
            print(f"Error generating PDF: {e}")
            return None
