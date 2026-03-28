"""
VSS health check and troubleshooting tool.

This module provides the VSSHealthChecker class for running comprehensive
VSS health checks before collection, including diagnostics, optional shadow
copy creation testing, and overall system readiness assessment.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

try:
    from .shadow_copy_manager import ShadowCopyCreationResult, ShadowCopyManager
    from .vss_diagnostics import DiagnosticReport, VSSDiagnostics
except ImportError:
    # Fallback for when module is imported directly (e.g., in tests)
    from shadow_copy_manager import ShadowCopyCreationResult, ShadowCopyManager
    from vss_diagnostics import DiagnosticReport, VSSDiagnostics

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class HealthCheckReport:
    """Comprehensive VSS health check report.
    
    Attributes:
        timestamp: When the health check was performed
        system_info: System information (OS version, admin status, etc.)
        diagnostic_report: Full diagnostic report from VSSDiagnostics
        test_shadow_creation: Results from optional shadow copy creation test
        overall_status: Overall health status ("pass", "warning", "fail")
        issues_found: List of issues discovered during health check
        recommendations: List of recommended actions
        ready_for_collection: Whether the system is ready for VSS-based collection
    """
    timestamp: str  # ISO format datetime string
    system_info: Dict[str, str]
    diagnostic_report: DiagnosticReport
    test_shadow_creation: Optional[ShadowCopyCreationResult]
    overall_status: str
    issues_found: List[str]
    recommendations: List[str]
    ready_for_collection: bool


@dataclass
class RemediationResult:
    """Result of attempting to remediate VSS issues.
    
    Attributes:
        attempted: Whether remediation was attempted
        steps_taken: List of remediation steps that were attempted
        successful: Whether all fixes succeeded
        remaining_issues: Issues that couldn't be fixed automatically
        requires_manual_intervention: Whether manual steps are needed
    """
    attempted: bool
    steps_taken: List[str]
    successful: bool
    remaining_issues: List[str]
    requires_manual_intervention: bool



    @dataclass
    class RemediationResult:
        """Result of attempting to remediate VSS issues.

        Attributes:
            attempted: Whether remediation was attempted
            steps_taken: List of remediation steps that were attempted
            successful: Whether all fixes succeeded
            remaining_issues: Issues that couldn't be fixed automatically
            requires_manual_intervention: Whether manual steps are needed
        """
        attempted: bool
        steps_taken: List[str]
        successful: bool
        remaining_issues: List[str]
        requires_manual_intervention: bool



class VSSHealthChecker:
    """Standalone VSS health check and troubleshooting tool.
    
    This class provides comprehensive VSS health checking capabilities for
    pre-collection verification. It runs diagnostics, optionally tests shadow
    copy creation, and determines overall system readiness.
    
    Requirements:
        - 10.1: Standalone tool that can be run independently
        - 10.2: Check VSS service status, shadow copies, disk space, providers, and writers
        - 10.3: Generate comprehensive report with pass/fail status for each check
    """
    
    def __init__(self):
        """Initialize the VSSHealthChecker.
        
        Creates instances of VSSDiagnostics and ShadowCopyManager for
        performing health checks.
        
        Requirements:
            - 10.1: Standalone tool initialization
        """
        self.diagnostics = VSSDiagnostics()
        self.manager = ShadowCopyManager(self.diagnostics)
        logger.info("[VSSHealthChecker] Initialized VSS health checker")
    
    def run_health_check(
        self,
        volume: str = "C:",
        test_creation: bool = False
    ) -> HealthCheckReport:
        """Run comprehensive VSS health check.
        
        This method performs a complete health check including:
        1. Collecting system information (OS version, admin status)
        2. Running full diagnostics (service, shadow copies, disk space, providers, writers)
        3. Optionally testing shadow copy creation
        4. Determining overall status and readiness
        5. Compiling issues and recommendations
        
        Args:
            volume: Drive letter to check (e.g., "C:" or "C")
            test_creation: Whether to test shadow copy creation (default: False)
            
        Returns:
            HealthCheckReport with comprehensive health check results
            
        Requirements:
            - 10.2: Check VSS service status, shadow copies, disk space, providers, and writers
            - 10.3: Generate comprehensive report with pass/fail status for each check
        """
        # Normalize volume format
        if not volume.endswith(":"):
            volume = volume + ":"
        
        timestamp = datetime.now().isoformat()
        logger.info(f"[VSSHealthChecker] Starting health check for volume {volume} at {timestamp}")
        
        # Collect system information
        logger.info("[VSSHealthChecker] Collecting system information")
        system_info = self._collect_system_info()
        
        # Run full diagnostics
        logger.info("[VSSHealthChecker] Running full diagnostics")
        diagnostic_report = self.diagnostics.run_full_diagnostics(volume)
        
        # Optionally test shadow copy creation
        test_shadow_result = None
        if test_creation:
            logger.info("[VSSHealthChecker] Testing shadow copy creation")
            test_shadow_result = self.manager.create_shadow_copy(volume)
            
            if test_shadow_result.success:
                logger.info("[VSSHealthChecker] Shadow copy creation test succeeded")
            else:
                logger.warning("[VSSHealthChecker] Shadow copy creation test failed")
        
        # Determine overall status
        logger.info("[VSSHealthChecker] Determining overall status")
        overall_status, issues_found, recommendations, ready_for_collection = (
            self._determine_overall_status(diagnostic_report, test_shadow_result)
        )
        
        logger.info(
            f"[VSSHealthChecker] Health check complete: status={overall_status}, "
            f"ready={ready_for_collection}, issues={len(issues_found)}"
        )
        
        return HealthCheckReport(
            timestamp=timestamp,
            system_info=system_info,
            diagnostic_report=diagnostic_report,
            test_shadow_creation=test_shadow_result,
            overall_status=overall_status,
            issues_found=issues_found,
            recommendations=recommendations,
            ready_for_collection=ready_for_collection
        )
    
    def _collect_system_info(self) -> Dict[str, str]:
        """Collect system information for the health check report.
        
        Returns:
            Dictionary containing system information
        """
        import ctypes
        import platform
        
        system_info = {}
        
        # OS version
        try:
            system_info["os_version"] = platform.platform()
            system_info["os_release"] = platform.release()
            system_info["os_architecture"] = platform.machine()
        except Exception as e:
            logger.warning(f"[VSSHealthChecker] Could not get OS version: {e}")
            system_info["os_version"] = "Unknown"
        
        # Administrator status
        try:
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
            system_info["is_admin"] = "Yes" if is_admin else "No"
        except Exception as e:
            logger.warning(f"[VSSHealthChecker] Could not check admin status: {e}")
            system_info["is_admin"] = "Unknown"
        
        # Python version
        system_info["python_version"] = platform.python_version()
        
        logger.debug(f"[VSSHealthChecker] System info: {system_info}")
        
        return system_info
    
    def _determine_overall_status(
        self,
        diagnostic_report: DiagnosticReport,
        test_shadow_result: Optional[ShadowCopyCreationResult]
    ) -> tuple:
        """Determine overall health status and readiness.
        
        Args:
            diagnostic_report: Full diagnostic report
            test_shadow_result: Optional shadow copy creation test result
            
        Returns:
            Tuple of (overall_status, issues_found, recommendations, ready_for_collection)
        """
        issues_found = []
        recommendations = []
        
        # Check diagnostic report for issues
        if not diagnostic_report.is_admin:
            issues_found.append("Not running as Administrator")
            recommendations.append("Run as Administrator for VSS operations")
        
        if not diagnostic_report.service_status.is_running:
            issues_found.append(f"VSS service not running: {diagnostic_report.service_status.status_message}")
            recommendations.extend(diagnostic_report.service_status.remediation_steps)
        
        if not diagnostic_report.shadow_copy_status.exists:
            issues_found.append(f"No shadow copies exist for volume")
            recommendations.append("Shadow copies will be created automatically during collection if needed")
        
        if not diagnostic_report.disk_space_status.sufficient_for_shadow:
            issues_found.append(
                f"Insufficient disk space or VSS quota: "
                f"{diagnostic_report.disk_space_status.free_space_bytes / (1024**3):.2f} GB free"
            )
            recommendations.extend(diagnostic_report.disk_space_status.remediation_steps)
        
        if not diagnostic_report.provider_status.providers_available:
            issues_found.append("No VSS providers available")
            if diagnostic_report.provider_status.error_message:
                issues_found.append(f"Provider error: {diagnostic_report.provider_status.error_message}")
            recommendations.append("Check VSS providers: vssadmin list providers")
            recommendations.append("Restart VSS service or reboot system")
        
        if not diagnostic_report.writer_status.all_stable:
            issues_found.append(
                f"{len(diagnostic_report.writer_status.failed_writers)} VSS writer(s) in failed state"
            )
            recommendations.extend(diagnostic_report.writer_status.remediation_steps)
        
        if diagnostic_report.policy_status.vss_restricted:
            issues_found.append("VSS operations may be restricted by system policies")
            recommendations.extend(diagnostic_report.policy_status.remediation_steps)
        
        # Add blocking issues from diagnostic report
        issues_found.extend(diagnostic_report.blocking_issues)
        
        # Add remediation summary from diagnostic report
        recommendations.extend(diagnostic_report.remediation_summary)
        
        # Check shadow copy creation test result if performed
        if test_shadow_result is not None:
            if not test_shadow_result.success:
                issues_found.append("Shadow copy creation test failed")
                if test_shadow_result.error:
                    issues_found.append(f"Creation error: {test_shadow_result.error.error_message}")
                recommendations.extend(test_shadow_result.remediation_steps)
        
        # Remove duplicate recommendations
        recommendations = list(dict.fromkeys(recommendations))
        
        # Determine overall status
        if diagnostic_report.overall_health == "failed" or len(diagnostic_report.blocking_issues) > 0:
            overall_status = "fail"
            ready_for_collection = False
        elif diagnostic_report.overall_health == "degraded" or len(issues_found) > 0:
            overall_status = "warning"
            # System may still be ready if issues are non-critical
            ready_for_collection = diagnostic_report.can_create_shadow
        else:
            overall_status = "pass"
            ready_for_collection = True
        
        # If shadow copy creation test failed, mark as not ready
        if test_shadow_result is not None and not test_shadow_result.success:
            ready_for_collection = False
            if overall_status == "pass":
                overall_status = "warning"
        
        logger.debug(
            f"[VSSHealthChecker] Status determination: overall={overall_status}, "
            f"ready={ready_for_collection}, issues={len(issues_found)}, "
            f"recommendations={len(recommendations)}"
        )
        
        return overall_status, issues_found, recommendations, ready_for_collection

        def generate_report(
            self,
            report: HealthCheckReport,
            format: str = "text"
        ) -> str:
            """Generate health check report in specified format.

            This method generates a comprehensive health check report in the
            requested format (text, JSON, or HTML). The report includes all
            diagnostic results, issues found, and recommendations.

            Args:
                report: HealthCheckReport to format
                format: Output format - "text", "json", or "html" (default: "text")

            Returns:
                Formatted report as a string

            Raises:
                ValueError: If format is not one of "text", "json", "html"

            Requirements:
                - 10.3: Generate comprehensive report with pass/fail status for each check
                - 10.4: Provide specific commands to resolve each issue
            """
            format = format.lower()

            if format == "text":
                return self._generate_text_report(report)
            elif format == "json":
                return self._generate_json_report(report)
            elif format == "html":
                return self._generate_html_report(report)
            else:
                raise ValueError(f"Unsupported format: {format}. Must be 'text', 'json', or 'html'")

        def _generate_text_report(self, report: HealthCheckReport) -> str:
            """Generate human-readable text report.

            Args:
                report: HealthCheckReport to format

            Returns:
                Text-formatted report
            """
            lines = []

            # Header
            lines.append("=" * 80)
            lines.append("VSS HEALTH CHECK REPORT")
            lines.append("=" * 80)
            lines.append(f"Timestamp: {report.timestamp}")
            lines.append(f"Overall Status: {report.overall_status.upper()}")
            lines.append(f"Ready for Collection: {'YES' if report.ready_for_collection else 'NO'}")
            lines.append("")

            # System Information
            lines.append("-" * 80)
            lines.append("SYSTEM INFORMATION")
            lines.append("-" * 80)
            for key, value in report.system_info.items():
                lines.append(f"  {key.replace('_', ' ').title()}: {value}")
            lines.append("")

            # Diagnostic Results
            lines.append("-" * 80)
            lines.append("DIAGNOSTIC RESULTS")
            lines.append("-" * 80)

            # VSS Service Status
            lines.append(f"VSS Service: {'PASS' if report.diagnostic_report.service_status.is_running else 'FAIL'}")
            lines.append(f"  Status: {report.diagnostic_report.service_status.status_message}")
            lines.append(f"  Start Type: {report.diagnostic_report.service_status.start_type}")
            lines.append("")

            # Shadow Copies
            lines.append(f"Shadow Copies: {'PASS' if report.diagnostic_report.shadow_copy_status.exists else 'WARNING'}")
            lines.append(f"  Count: {report.diagnostic_report.shadow_copy_status.count}")
            if report.diagnostic_report.shadow_copy_status.most_recent:
                lines.append(f"  Most Recent: {report.diagnostic_report.shadow_copy_status.most_recent.creation_time}")
            if report.diagnostic_report.shadow_copy_status.error_message:
                lines.append(f"  Error: {report.diagnostic_report.shadow_copy_status.error_message}")
            lines.append("")

            # Disk Space
            lines.append(f"Disk Space: {'PASS' if report.diagnostic_report.disk_space_status.sufficient_for_shadow else 'FAIL'}")
            lines.append(f"  Volume: {report.diagnostic_report.disk_space_status.volume}")
            lines.append(f"  Free Space: {report.diagnostic_report.disk_space_status.free_space_bytes / (1024**3):.2f} GB "
                        f"({report.diagnostic_report.disk_space_status.free_space_percent:.1f}%)")
            lines.append(f"  VSS Allocated: {report.diagnostic_report.disk_space_status.vss_allocated_bytes / (1024**3):.2f} GB")
            lines.append(f"  VSS Used: {report.diagnostic_report.disk_space_status.vss_used_bytes / (1024**3):.2f} GB")
            lines.append(f"  VSS Max: {report.diagnostic_report.disk_space_status.vss_max_bytes / (1024**3):.2f} GB")
            lines.append("")

            # VSS Providers
            lines.append(f"VSS Providers: {'PASS' if report.diagnostic_report.provider_status.providers_available else 'FAIL'}")
            lines.append(f"  Count: {report.diagnostic_report.provider_status.provider_count}")
            if report.diagnostic_report.provider_status.provider_names:
                for provider in report.diagnostic_report.provider_status.provider_names:
                    lines.append(f"    - {provider}")
            if report.diagnostic_report.provider_status.error_message:
                lines.append(f"  Error: {report.diagnostic_report.provider_status.error_message}")
            lines.append("")

            # VSS Writers
            lines.append(f"VSS Writers: {'PASS' if report.diagnostic_report.writer_status.all_stable else 'FAIL'}")
            lines.append(f"  Total Writers: {report.diagnostic_report.writer_status.writer_count}")
            lines.append(f"  Failed Writers: {len(report.diagnostic_report.writer_status.failed_writers)}")
            if report.diagnostic_report.writer_status.failed_writers:
                for writer in report.diagnostic_report.writer_status.failed_writers:
                    lines.append(f"    - {writer.get('name', 'Unknown')}: {writer.get('state', 'Unknown')} "
                               f"(Error: {writer.get('error_code', 'N/A')})")
            lines.append("")

            # System Policies
            lines.append(f"System Policies: {'PASS' if not report.diagnostic_report.policy_status.vss_restricted else 'WARNING'}")
            if report.diagnostic_report.policy_status.vss_restricted:
                lines.append("  VSS operations may be restricted")
                for restriction in report.diagnostic_report.policy_status.restrictions_found:
                    lines.append(f"    - {restriction}")
            if report.diagnostic_report.policy_status.bitlocker_active:
                lines.append("  BitLocker: Active")
            lines.append("")

            # Shadow Copy Creation Test (if performed)
            if report.test_shadow_creation is not None:
                lines.append("-" * 80)
                lines.append("SHADOW COPY CREATION TEST")
                lines.append("-" * 80)
                lines.append(f"Result: {'PASS' if report.test_shadow_creation.success else 'FAIL'}")
                lines.append(f"Duration: {report.test_shadow_creation.duration_seconds:.2f} seconds")
                if report.test_shadow_creation.success:
                    lines.append(f"Shadow Copy ID: {report.test_shadow_creation.shadow_copy.shadow_copy_id}")
                    lines.append(f"Creation Time: {report.test_shadow_creation.shadow_copy.creation_time}")
                else:
                    if report.test_shadow_creation.error:
                        lines.append(f"Error Category: {report.test_shadow_creation.error.error_category}")
                        lines.append(f"Error Message: {report.test_shadow_creation.error.error_message}")
                lines.append("")

            # Issues Found
            if report.issues_found:
                lines.append("-" * 80)
                lines.append("ISSUES FOUND")
                lines.append("-" * 80)
                for i, issue in enumerate(report.issues_found, 1):
                    lines.append(f"{i}. {issue}")
                lines.append("")

            # Recommendations
            if report.recommendations:
                lines.append("-" * 80)
                lines.append("RECOMMENDATIONS")
                lines.append("-" * 80)
                for i, recommendation in enumerate(report.recommendations, 1):
                    lines.append(f"{i}. {recommendation}")
                lines.append("")

            # Footer
            lines.append("=" * 80)
            lines.append(f"End of Report - Status: {report.overall_status.upper()}")
            lines.append("=" * 80)

            return "\n".join(lines)

        def _generate_json_report(self, report: HealthCheckReport) -> str:
            """Generate JSON-formatted report.

            Args:
                report: HealthCheckReport to format

            Returns:
                JSON-formatted report
            """
            import json

            # Convert report to dictionary
            report_dict = {
                "timestamp": report.timestamp,
                "overall_status": report.overall_status,
                "ready_for_collection": report.ready_for_collection,
                "system_info": report.system_info,
                "diagnostics": {
                    "is_admin": report.diagnostic_report.is_admin,
                    "overall_health": report.diagnostic_report.overall_health,
                    "can_create_shadow": report.diagnostic_report.can_create_shadow,
                    "service_status": {
                        "is_running": report.diagnostic_report.service_status.is_running,
                        "start_type": report.diagnostic_report.service_status.start_type,
                        "status_message": report.diagnostic_report.service_status.status_message,
                        "can_start": report.diagnostic_report.service_status.can_start,
                        "remediation_steps": report.diagnostic_report.service_status.remediation_steps
                    },
                    "shadow_copy_status": {
                        "exists": report.diagnostic_report.shadow_copy_status.exists,
                        "count": report.diagnostic_report.shadow_copy_status.count,
                        "most_recent": {
                            "shadow_copy_id": report.diagnostic_report.shadow_copy_status.most_recent.shadow_copy_id,
                            "creation_time": str(report.diagnostic_report.shadow_copy_status.most_recent.creation_time),
                            "original_volume": report.diagnostic_report.shadow_copy_status.most_recent.original_volume
                        } if report.diagnostic_report.shadow_copy_status.most_recent else None,
                        "error_message": report.diagnostic_report.shadow_copy_status.error_message
                    },
                    "disk_space_status": {
                        "volume": report.diagnostic_report.disk_space_status.volume,
                        "total_space_gb": report.diagnostic_report.disk_space_status.total_space_bytes / (1024**3),
                        "free_space_gb": report.diagnostic_report.disk_space_status.free_space_bytes / (1024**3),
                        "free_space_percent": report.diagnostic_report.disk_space_status.free_space_percent,
                        "vss_allocated_gb": report.diagnostic_report.disk_space_status.vss_allocated_bytes / (1024**3),
                        "vss_used_gb": report.diagnostic_report.disk_space_status.vss_used_bytes / (1024**3),
                        "vss_max_gb": report.diagnostic_report.disk_space_status.vss_max_bytes / (1024**3),
                        "sufficient_for_shadow": report.diagnostic_report.disk_space_status.sufficient_for_shadow,
                        "remediation_steps": report.diagnostic_report.disk_space_status.remediation_steps
                    },
                    "provider_status": {
                        "providers_available": report.diagnostic_report.provider_status.providers_available,
                        "provider_count": report.diagnostic_report.provider_status.provider_count,
                        "provider_names": report.diagnostic_report.provider_status.provider_names,
                        "error_message": report.diagnostic_report.provider_status.error_message
                    },
                    "writer_status": {
                        "all_stable": report.diagnostic_report.writer_status.all_stable,
                        "writer_count": report.diagnostic_report.writer_status.writer_count,
                        "failed_writers": report.diagnostic_report.writer_status.failed_writers,
                        "remediation_steps": report.diagnostic_report.writer_status.remediation_steps
                    },
                    "policy_status": {
                        "vss_restricted": report.diagnostic_report.policy_status.vss_restricted,
                        "restrictions_found": report.diagnostic_report.policy_status.restrictions_found,
                        "bitlocker_active": report.diagnostic_report.policy_status.bitlocker_active,
                        "remediation_steps": report.diagnostic_report.policy_status.remediation_steps
                    },
                    "blocking_issues": report.diagnostic_report.blocking_issues,
                    "remediation_summary": report.diagnostic_report.remediation_summary
                },
                "test_shadow_creation": {
                    "success": report.test_shadow_creation.success,
                    "duration_seconds": report.test_shadow_creation.duration_seconds,
                    "shadow_copy": {
                        "shadow_copy_id": report.test_shadow_creation.shadow_copy.shadow_copy_id,
                        "creation_time": str(report.test_shadow_creation.shadow_copy.creation_time),
                        "original_volume": report.test_shadow_creation.shadow_copy.original_volume
                    } if report.test_shadow_creation.shadow_copy else None,
                    "error": {
                        "error_code": report.test_shadow_creation.error.error_code,
                        "error_category": report.test_shadow_creation.error.error_category,
                        "error_message": report.test_shadow_creation.error.error_message,
                        "user_friendly_message": report.test_shadow_creation.error.user_friendly_message
                    } if report.test_shadow_creation.error else None,
                    "remediation_steps": report.test_shadow_creation.remediation_steps
                } if report.test_shadow_creation else None,
                "issues_found": report.issues_found,
                "recommendations": report.recommendations
            }

            return json.dumps(report_dict, indent=2)

        def _generate_html_report(self, report: HealthCheckReport) -> str:
            """Generate HTML-formatted report.

            Args:
                report: HealthCheckReport to format

            Returns:
                HTML-formatted report
            """
            # Status colors
            status_colors = {
                "pass": "#28a745",
                "warning": "#ffc107",
                "fail": "#dc3545"
            }

            status_color = status_colors.get(report.overall_status, "#6c757d")

            html = f"""<!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>VSS Health Check Report</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 20px;
                background-color: #f5f5f5;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
                background-color: white;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            h1 {{
                color: #333;
                border-bottom: 3px solid {status_color};
                padding-bottom: 10px;
            }}
            h2 {{
                color: #555;
                margin-top: 30px;
                border-bottom: 2px solid #ddd;
                padding-bottom: 5px;
            }}
            .status-badge {{
                display: inline-block;
                padding: 5px 15px;
                border-radius: 4px;
                color: white;
                font-weight: bold;
                background-color: {status_color};
            }}
            .info-grid {{
                display: grid;
                grid-template-columns: 200px 1fr;
                gap: 10px;
                margin: 15px 0;
            }}
            .info-label {{
                font-weight: bold;
                color: #666;
            }}
            .check-item {{
                margin: 15px 0;
                padding: 10px;
                background-color: #f9f9f9;
                border-left: 4px solid #ddd;
                border-radius: 4px;
            }}
            .check-pass {{
                border-left-color: #28a745;
            }}
            .check-warning {{
                border-left-color: #ffc107;
            }}
            .check-fail {{
                border-left-color: #dc3545;
            }}
            .check-title {{
                font-weight: bold;
                margin-bottom: 5px;
            }}
            .check-details {{
                margin-left: 20px;
                color: #666;
            }}
            ul {{
                margin: 10px 0;
                padding-left: 20px;
            }}
            li {{
                margin: 5px 0;
            }}
            .issue {{
                color: #dc3545;
            }}
            .recommendation {{
                color: #007bff;
            }}
            .footer {{
                margin-top: 30px;
                padding-top: 20px;
                border-top: 2px solid #ddd;
                text-align: center;
                color: #666;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>VSS Health Check Report</h1>

            <div class="info-grid">
                <div class="info-label">Timestamp:</div>
                <div>{report.timestamp}</div>

                <div class="info-label">Overall Status:</div>
                <div><span class="status-badge">{report.overall_status.upper()}</span></div>

                <div class="info-label">Ready for Collection:</div>
                <div><strong>{'YES' if report.ready_for_collection else 'NO'}</strong></div>
            </div>

            <h2>System Information</h2>
            <div class="info-grid">
    """

            for key, value in report.system_info.items():
                html += f"""            <div class="info-label">{key.replace('_', ' ').title()}:</div>
                <div>{value}</div>
    """

            html += """        </div>

            <h2>Diagnostic Results</h2>
    """

            # VSS Service
            service_class = "check-pass" if report.diagnostic_report.service_status.is_running else "check-fail"
            html += f"""        <div class="check-item {service_class}">
                <div class="check-title">VSS Service: {'PASS' if report.diagnostic_report.service_status.is_running else 'FAIL'}</div>
                <div class="check-details">
                    Status: {report.diagnostic_report.service_status.status_message}<br>
                    Start Type: {report.diagnostic_report.service_status.start_type}
                </div>
            </div>
    """

            # Shadow Copies
            shadow_class = "check-pass" if report.diagnostic_report.shadow_copy_status.exists else "check-warning"
            html += f"""        <div class="check-item {shadow_class}">
                <div class="check-title">Shadow Copies: {'PASS' if report.diagnostic_report.shadow_copy_status.exists else 'WARNING'}</div>
                <div class="check-details">
                    Count: {report.diagnostic_report.shadow_copy_status.count}<br>
    """
            if report.diagnostic_report.shadow_copy_status.most_recent:
                html += f"                Most Recent: {report.diagnostic_report.shadow_copy_status.most_recent.creation_time}<br>\n"
            if report.diagnostic_report.shadow_copy_status.error_message:
                html += f"                Error: {report.diagnostic_report.shadow_copy_status.error_message}<br>\n"
            html += """            </div>
            </div>
    """

            # Disk Space
            disk_class = "check-pass" if report.diagnostic_report.disk_space_status.sufficient_for_shadow else "check-fail"
            html += f"""        <div class="check-item {disk_class}">
                <div class="check-title">Disk Space: {'PASS' if report.diagnostic_report.disk_space_status.sufficient_for_shadow else 'FAIL'}</div>
                <div class="check-details">
                    Volume: {report.diagnostic_report.disk_space_status.volume}<br>
                    Free Space: {report.diagnostic_report.disk_space_status.free_space_bytes / (1024**3):.2f} GB ({report.diagnostic_report.disk_space_status.free_space_percent:.1f}%)<br>
                    VSS Allocated: {report.diagnostic_report.disk_space_status.vss_allocated_bytes / (1024**3):.2f} GB<br>
                    VSS Used: {report.diagnostic_report.disk_space_status.vss_used_bytes / (1024**3):.2f} GB<br>
                    VSS Max: {report.diagnostic_report.disk_space_status.vss_max_bytes / (1024**3):.2f} GB
                </div>
            </div>
    """

            # VSS Providers
            provider_class = "check-pass" if report.diagnostic_report.provider_status.providers_available else "check-fail"
            html += f"""        <div class="check-item {provider_class}">
                <div class="check-title">VSS Providers: {'PASS' if report.diagnostic_report.provider_status.providers_available else 'FAIL'}</div>
                <div class="check-details">
                    Count: {report.diagnostic_report.provider_status.provider_count}<br>
    """
            if report.diagnostic_report.provider_status.provider_names:
                html += "                Providers:<br>\n"
                for provider in report.diagnostic_report.provider_status.provider_names:
                    html += f"                &nbsp;&nbsp;- {provider}<br>\n"
            if report.diagnostic_report.provider_status.error_message:
                html += f"                Error: {report.diagnostic_report.provider_status.error_message}<br>\n"
            html += """            </div>
            </div>
    """

            # VSS Writers
            writer_class = "check-pass" if report.diagnostic_report.writer_status.all_stable else "check-fail"
            html += f"""        <div class="check-item {writer_class}">
                <div class="check-title">VSS Writers: {'PASS' if report.diagnostic_report.writer_status.all_stable else 'FAIL'}</div>
                <div class="check-details">
                    Total Writers: {report.diagnostic_report.writer_status.writer_count}<br>
                    Failed Writers: {len(report.diagnostic_report.writer_status.failed_writers)}<br>
    """
            if report.diagnostic_report.writer_status.failed_writers:
                html += "                Failed:<br>\n"
                for writer in report.diagnostic_report.writer_status.failed_writers:
                    html += f"                &nbsp;&nbsp;- {writer.get('name', 'Unknown')}: {writer.get('state', 'Unknown')} (Error: {writer.get('error_code', 'N/A')})<br>\n"
            html += """            </div>
            </div>
    """

            # System Policies
            policy_class = "check-pass" if not report.diagnostic_report.policy_status.vss_restricted else "check-warning"
            html += f"""        <div class="check-item {policy_class}">
                <div class="check-title">System Policies: {'PASS' if not report.diagnostic_report.policy_status.vss_restricted else 'WARNING'}</div>
                <div class="check-details">
    """
            if report.diagnostic_report.policy_status.vss_restricted:
                html += "                VSS operations may be restricted<br>\n"
                for restriction in report.diagnostic_report.policy_status.restrictions_found:
                    html += f"                &nbsp;&nbsp;- {restriction}<br>\n"
            if report.diagnostic_report.policy_status.bitlocker_active:
                html += "                BitLocker: Active<br>\n"
            html += """            </div>
            </div>
    """

            # Shadow Copy Creation Test
            if report.test_shadow_creation is not None:
                test_class = "check-pass" if report.test_shadow_creation.success else "check-fail"
                html += f"""
            <h2>Shadow Copy Creation Test</h2>
            <div class="check-item {test_class}">
                <div class="check-title">Result: {'PASS' if report.test_shadow_creation.success else 'FAIL'}</div>
                <div class="check-details">
                    Duration: {report.test_shadow_creation.duration_seconds:.2f} seconds<br>
    """
                if report.test_shadow_creation.success:
                    html += f"""                Shadow Copy ID: {report.test_shadow_creation.shadow_copy.shadow_copy_id}<br>
                    Creation Time: {report.test_shadow_creation.shadow_copy.creation_time}<br>
    """
                else:
                    if report.test_shadow_creation.error:
                        html += f"""                Error Category: {report.test_shadow_creation.error.error_category}<br>
                    Error Message: {report.test_shadow_creation.error.error_message}<br>
    """
                html += """            </div>
            </div>
    """

            # Issues Found
            if report.issues_found:
                html += """
            <h2>Issues Found</h2>
            <ul>
    """
                for issue in report.issues_found:
                    html += f"""            <li class="issue">{issue}</li>
    """
                html += """        </ul>
    """

            # Recommendations
            if report.recommendations:
                html += """
            <h2>Recommendations</h2>
            <ul>
    """
                for recommendation in report.recommendations:
                    html += f"""            <li class="recommendation">{recommendation}</li>
    """
                html += """        </ul>
    """

            # Footer
            html += f"""
            <div class="footer">
                <p>End of Report - Status: <strong>{report.overall_status.upper()}</strong></p>
                <p>Generated: {report.timestamp}</p>
            </div>
        </div>
    </body>
    </html>
    """

            return html


    def generate_report(
        self,
        report: HealthCheckReport,
        format: str = "text"
    ) -> str:
        """Generate health check report in specified format.
        
        This method generates a comprehensive health check report in the
        requested format (text, JSON, or HTML). The report includes all
        diagnostic results, issues found, and recommendations.
        
        Args:
            report: HealthCheckReport to format
            format: Output format - "text", "json", or "html" (default: "text")
            
        Returns:
            Formatted report as a string
            
        Raises:
            ValueError: If format is not one of "text", "json", "html"
            
        Requirements:
            - 10.3: Generate comprehensive report with pass/fail status for each check
            - 10.4: Provide specific commands to resolve each issue
        """
        format = format.lower()
        
        if format == "text":
            return self._generate_text_report(report)
        elif format == "json":
            return self._generate_json_report(report)
        elif format == "html":
            return self._generate_html_report(report)
        else:
            raise ValueError(f"Unsupported format: {format}. Must be 'text', 'json', or 'html'")
    
    def _generate_text_report(self, report: HealthCheckReport) -> str:
        """Generate human-readable text report.
        
        Args:
            report: HealthCheckReport to format
            
        Returns:
            Text-formatted report
        """
        lines = []
        
        # Header
        lines.append("=" * 80)
        lines.append("VSS HEALTH CHECK REPORT")
        lines.append("=" * 80)
        lines.append(f"Timestamp: {report.timestamp}")
        lines.append(f"Overall Status: {report.overall_status.upper()}")
        lines.append(f"Ready for Collection: {'YES' if report.ready_for_collection else 'NO'}")
        lines.append("")
        
        # System Information
        lines.append("-" * 80)
        lines.append("SYSTEM INFORMATION")
        lines.append("-" * 80)
        for key, value in report.system_info.items():
            lines.append(f"  {key.replace('_', ' ').title()}: {value}")
        lines.append("")
        
        # Diagnostic Results
        lines.append("-" * 80)
        lines.append("DIAGNOSTIC RESULTS")
        lines.append("-" * 80)
        
        # VSS Service Status
        lines.append(f"VSS Service: {'PASS' if report.diagnostic_report.service_status.is_running else 'FAIL'}")
        lines.append(f"  Status: {report.diagnostic_report.service_status.status_message}")
        lines.append(f"  Start Type: {report.diagnostic_report.service_status.start_type}")
        lines.append("")
        
        # Shadow Copies
        lines.append(f"Shadow Copies: {'PASS' if report.diagnostic_report.shadow_copy_status.exists else 'WARNING'}")
        lines.append(f"  Count: {report.diagnostic_report.shadow_copy_status.count}")
        if report.diagnostic_report.shadow_copy_status.most_recent:
            lines.append(f"  Most Recent: {report.diagnostic_report.shadow_copy_status.most_recent.creation_time}")
        if report.diagnostic_report.shadow_copy_status.error_message:
            lines.append(f"  Error: {report.diagnostic_report.shadow_copy_status.error_message}")
        lines.append("")
        
        # Disk Space
        lines.append(f"Disk Space: {'PASS' if report.diagnostic_report.disk_space_status.sufficient_for_shadow else 'FAIL'}")
        lines.append(f"  Volume: {report.diagnostic_report.disk_space_status.volume}")
        lines.append(f"  Free Space: {report.diagnostic_report.disk_space_status.free_space_bytes / (1024**3):.2f} GB "
                    f"({report.diagnostic_report.disk_space_status.free_space_percent:.1f}%)")
        lines.append(f"  VSS Allocated: {report.diagnostic_report.disk_space_status.vss_allocated_bytes / (1024**3):.2f} GB")
        lines.append(f"  VSS Used: {report.diagnostic_report.disk_space_status.vss_used_bytes / (1024**3):.2f} GB")
        lines.append(f"  VSS Max: {report.diagnostic_report.disk_space_status.vss_max_bytes / (1024**3):.2f} GB")
        lines.append("")
        
        # VSS Providers
        lines.append(f"VSS Providers: {'PASS' if report.diagnostic_report.provider_status.providers_available else 'FAIL'}")
        lines.append(f"  Count: {report.diagnostic_report.provider_status.provider_count}")
        if report.diagnostic_report.provider_status.provider_names:
            for provider in report.diagnostic_report.provider_status.provider_names:
                lines.append(f"    - {provider}")
        if report.diagnostic_report.provider_status.error_message:
            lines.append(f"  Error: {report.diagnostic_report.provider_status.error_message}")
        lines.append("")
        
        # VSS Writers
        lines.append(f"VSS Writers: {'PASS' if report.diagnostic_report.writer_status.all_stable else 'FAIL'}")
        lines.append(f"  Total Writers: {report.diagnostic_report.writer_status.writer_count}")
        lines.append(f"  Failed Writers: {len(report.diagnostic_report.writer_status.failed_writers)}")
        if report.diagnostic_report.writer_status.failed_writers:
            for writer in report.diagnostic_report.writer_status.failed_writers:
                lines.append(f"    - {writer.get('name', 'Unknown')}: {writer.get('state', 'Unknown')} "
                           f"(Error: {writer.get('error_code', 'N/A')})")
        lines.append("")
        
        # System Policies
        lines.append(f"System Policies: {'PASS' if not report.diagnostic_report.policy_status.vss_restricted else 'WARNING'}")
        if report.diagnostic_report.policy_status.vss_restricted:
            lines.append("  VSS operations may be restricted")
            for restriction in report.diagnostic_report.policy_status.restrictions_found:
                lines.append(f"    - {restriction}")
        if report.diagnostic_report.policy_status.bitlocker_active:
            lines.append("  BitLocker: Active")
        lines.append("")
        
        # Shadow Copy Creation Test (if performed)
        if report.test_shadow_creation is not None:
            lines.append("-" * 80)
            lines.append("SHADOW COPY CREATION TEST")
            lines.append("-" * 80)
            lines.append(f"Result: {'PASS' if report.test_shadow_creation.success else 'FAIL'}")
            lines.append(f"Duration: {report.test_shadow_creation.duration_seconds:.2f} seconds")
            if report.test_shadow_creation.success:
                lines.append(f"Shadow Copy ID: {report.test_shadow_creation.shadow_copy.shadow_copy_id}")
                lines.append(f"Creation Time: {report.test_shadow_creation.shadow_copy.creation_time}")
            else:
                if report.test_shadow_creation.error:
                    lines.append(f"Error Category: {report.test_shadow_creation.error.error_category}")
                    lines.append(f"Error Message: {report.test_shadow_creation.error.error_message}")
            lines.append("")
        
        # Issues Found
        if report.issues_found:
            lines.append("-" * 80)
            lines.append("ISSUES FOUND")
            lines.append("-" * 80)
            for i, issue in enumerate(report.issues_found, 1):
                lines.append(f"{i}. {issue}")
            lines.append("")
        
        # Recommendations
        if report.recommendations:
            lines.append("-" * 80)
            lines.append("RECOMMENDATIONS")
            lines.append("-" * 80)
            for i, recommendation in enumerate(report.recommendations, 1):
                lines.append(f"{i}. {recommendation}")
            lines.append("")
        
        # Footer
        lines.append("=" * 80)
        lines.append(f"End of Report - Status: {report.overall_status.upper()}")
        lines.append("=" * 80)
        
        return "\n".join(lines)
    
    def _generate_json_report(self, report: HealthCheckReport) -> str:
        """Generate JSON-formatted report.
        
        Args:
            report: HealthCheckReport to format
            
        Returns:
            JSON-formatted report
        """
        import json
        
        # Convert report to dictionary
        report_dict = {
            "timestamp": report.timestamp,
            "overall_status": report.overall_status,
            "ready_for_collection": report.ready_for_collection,
            "system_info": report.system_info,
            "diagnostics": {
                "is_admin": report.diagnostic_report.is_admin,
                "overall_health": report.diagnostic_report.overall_health,
                "can_create_shadow": report.diagnostic_report.can_create_shadow,
                "service_status": {
                    "is_running": report.diagnostic_report.service_status.is_running,
                    "start_type": report.diagnostic_report.service_status.start_type,
                    "status_message": report.diagnostic_report.service_status.status_message,
                    "can_start": report.diagnostic_report.service_status.can_start,
                    "remediation_steps": report.diagnostic_report.service_status.remediation_steps
                },
                "shadow_copy_status": {
                    "exists": report.diagnostic_report.shadow_copy_status.exists,
                    "count": report.diagnostic_report.shadow_copy_status.count,
                    "most_recent": {
                        "shadow_copy_id": report.diagnostic_report.shadow_copy_status.most_recent.shadow_copy_id,
                        "creation_time": str(report.diagnostic_report.shadow_copy_status.most_recent.creation_time),
                        "original_volume": report.diagnostic_report.shadow_copy_status.most_recent.original_volume
                    } if report.diagnostic_report.shadow_copy_status.most_recent else None,
                    "error_message": report.diagnostic_report.shadow_copy_status.error_message
                },
                "disk_space_status": {
                    "volume": report.diagnostic_report.disk_space_status.volume,
                    "total_space_gb": report.diagnostic_report.disk_space_status.total_space_bytes / (1024**3),
                    "free_space_gb": report.diagnostic_report.disk_space_status.free_space_bytes / (1024**3),
                    "free_space_percent": report.diagnostic_report.disk_space_status.free_space_percent,
                    "vss_allocated_gb": report.diagnostic_report.disk_space_status.vss_allocated_bytes / (1024**3),
                    "vss_used_gb": report.diagnostic_report.disk_space_status.vss_used_bytes / (1024**3),
                    "vss_max_gb": report.diagnostic_report.disk_space_status.vss_max_bytes / (1024**3),
                    "sufficient_for_shadow": report.diagnostic_report.disk_space_status.sufficient_for_shadow,
                    "remediation_steps": report.diagnostic_report.disk_space_status.remediation_steps
                },
                "provider_status": {
                    "providers_available": report.diagnostic_report.provider_status.providers_available,
                    "provider_count": report.diagnostic_report.provider_status.provider_count,
                    "provider_names": report.diagnostic_report.provider_status.provider_names,
                    "error_message": report.diagnostic_report.provider_status.error_message
                },
                "writer_status": {
                    "all_stable": report.diagnostic_report.writer_status.all_stable,
                    "writer_count": report.diagnostic_report.writer_status.writer_count,
                    "failed_writers": report.diagnostic_report.writer_status.failed_writers,
                    "remediation_steps": report.diagnostic_report.writer_status.remediation_steps
                },
                "policy_status": {
                    "vss_restricted": report.diagnostic_report.policy_status.vss_restricted,
                    "restrictions_found": report.diagnostic_report.policy_status.restrictions_found,
                    "bitlocker_active": report.diagnostic_report.policy_status.bitlocker_active,
                    "remediation_steps": report.diagnostic_report.policy_status.remediation_steps
                },
                "blocking_issues": report.diagnostic_report.blocking_issues,
                "remediation_summary": report.diagnostic_report.remediation_summary
            },
            "test_shadow_creation": {
                "success": report.test_shadow_creation.success,
                "duration_seconds": report.test_shadow_creation.duration_seconds,
                "shadow_copy": {
                    "shadow_copy_id": report.test_shadow_creation.shadow_copy.shadow_copy_id,
                    "creation_time": str(report.test_shadow_creation.shadow_copy.creation_time),
                    "original_volume": report.test_shadow_creation.shadow_copy.original_volume
                } if report.test_shadow_creation.shadow_copy else None,
                "error": {
                    "error_code": report.test_shadow_creation.error.error_code,
                    "error_category": report.test_shadow_creation.error.error_category,
                    "error_message": report.test_shadow_creation.error.error_message,
                    "user_friendly_message": report.test_shadow_creation.error.user_friendly_message
                } if report.test_shadow_creation.error else None,
                "remediation_steps": report.test_shadow_creation.remediation_steps
            } if report.test_shadow_creation else None,
            "issues_found": report.issues_found,
            "recommendations": report.recommendations
        }
        
        return json.dumps(report_dict, indent=2)
    
    def _generate_html_report(self, report: HealthCheckReport) -> str:
        """Generate HTML-formatted report.
        
        Args:
            report: HealthCheckReport to format
            
        Returns:
            HTML-formatted report
        """
        # Status colors
        status_colors = {
            "pass": "#28a745",
            "warning": "#ffc107",
            "fail": "#dc3545"
        }
        
        status_color = status_colors.get(report.overall_status, "#6c757d")
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>VSS Health Check Report</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid {status_color};
            padding-bottom: 10px;
        }}
        h2 {{
            color: #555;
            margin-top: 30px;
            border-bottom: 2px solid #ddd;
            padding-bottom: 5px;
        }}
        .status-badge {{
            display: inline-block;
            padding: 5px 15px;
            border-radius: 4px;
            color: white;
            font-weight: bold;
            background-color: {status_color};
        }}
        .info-grid {{
            display: grid;
            grid-template-columns: 200px 1fr;
            gap: 10px;
            margin: 15px 0;
        }}
        .info-label {{
            font-weight: bold;
            color: #666;
        }}
        .check-item {{
            margin: 15px 0;
            padding: 10px;
            background-color: #f9f9f9;
            border-left: 4px solid #ddd;
            border-radius: 4px;
        }}
        .check-pass {{
            border-left-color: #28a745;
        }}
        .check-warning {{
            border-left-color: #ffc107;
        }}
        .check-fail {{
            border-left-color: #dc3545;
        }}
        .check-title {{
            font-weight: bold;
            margin-bottom: 5px;
        }}
        .check-details {{
            margin-left: 20px;
            color: #666;
        }}
        ul {{
            margin: 10px 0;
            padding-left: 20px;
        }}
        li {{
            margin: 5px 0;
        }}
        .issue {{
            color: #dc3545;
        }}
        .recommendation {{
            color: #007bff;
        }}
        .footer {{
            margin-top: 30px;
            padding-top: 20px;
            border-top: 2px solid #ddd;
            text-align: center;
            color: #666;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>VSS Health Check Report</h1>
        
        <div class="info-grid">
            <div class="info-label">Timestamp:</div>
            <div>{report.timestamp}</div>
            
            <div class="info-label">Overall Status:</div>
            <div><span class="status-badge">{report.overall_status.upper()}</span></div>
            
            <div class="info-label">Ready for Collection:</div>
            <div><strong>{'YES' if report.ready_for_collection else 'NO'}</strong></div>
        </div>
        
        <h2>System Information</h2>
        <div class="info-grid">
"""
        
        for key, value in report.system_info.items():
            html += f"""            <div class="info-label">{key.replace('_', ' ').title()}:</div>
            <div>{value}</div>
"""
        
        html += """        </div>
        
        <h2>Diagnostic Results</h2>
"""
        
        # VSS Service
        service_class = "check-pass" if report.diagnostic_report.service_status.is_running else "check-fail"
        html += f"""        <div class="check-item {service_class}">
            <div class="check-title">VSS Service: {'PASS' if report.diagnostic_report.service_status.is_running else 'FAIL'}</div>
            <div class="check-details">
                Status: {report.diagnostic_report.service_status.status_message}<br>
                Start Type: {report.diagnostic_report.service_status.start_type}
            </div>
        </div>
"""
        
        # Shadow Copies
        shadow_class = "check-pass" if report.diagnostic_report.shadow_copy_status.exists else "check-warning"
        html += f"""        <div class="check-item {shadow_class}">
            <div class="check-title">Shadow Copies: {'PASS' if report.diagnostic_report.shadow_copy_status.exists else 'WARNING'}</div>
            <div class="check-details">
                Count: {report.diagnostic_report.shadow_copy_status.count}<br>
"""
        if report.diagnostic_report.shadow_copy_status.most_recent:
            html += f"                Most Recent: {report.diagnostic_report.shadow_copy_status.most_recent.creation_time}<br>\n"
        if report.diagnostic_report.shadow_copy_status.error_message:
            html += f"                Error: {report.diagnostic_report.shadow_copy_status.error_message}<br>\n"
        html += """            </div>
        </div>
"""
        
        # Disk Space
        disk_class = "check-pass" if report.diagnostic_report.disk_space_status.sufficient_for_shadow else "check-fail"
        html += f"""        <div class="check-item {disk_class}">
            <div class="check-title">Disk Space: {'PASS' if report.diagnostic_report.disk_space_status.sufficient_for_shadow else 'FAIL'}</div>
            <div class="check-details">
                Volume: {report.diagnostic_report.disk_space_status.volume}<br>
                Free Space: {report.diagnostic_report.disk_space_status.free_space_bytes / (1024**3):.2f} GB ({report.diagnostic_report.disk_space_status.free_space_percent:.1f}%)<br>
                VSS Allocated: {report.diagnostic_report.disk_space_status.vss_allocated_bytes / (1024**3):.2f} GB<br>
                VSS Used: {report.diagnostic_report.disk_space_status.vss_used_bytes / (1024**3):.2f} GB<br>
                VSS Max: {report.diagnostic_report.disk_space_status.vss_max_bytes / (1024**3):.2f} GB
            </div>
        </div>
"""
        
        # VSS Providers
        provider_class = "check-pass" if report.diagnostic_report.provider_status.providers_available else "check-fail"
        html += f"""        <div class="check-item {provider_class}">
            <div class="check-title">VSS Providers: {'PASS' if report.diagnostic_report.provider_status.providers_available else 'FAIL'}</div>
            <div class="check-details">
                Count: {report.diagnostic_report.provider_status.provider_count}<br>
"""
        if report.diagnostic_report.provider_status.provider_names:
            html += "                Providers:<br>\n"
            for provider in report.diagnostic_report.provider_status.provider_names:
                html += f"                &nbsp;&nbsp;- {provider}<br>\n"
        if report.diagnostic_report.provider_status.error_message:
            html += f"                Error: {report.diagnostic_report.provider_status.error_message}<br>\n"
        html += """            </div>
        </div>
"""
        
        # VSS Writers
        writer_class = "check-pass" if report.diagnostic_report.writer_status.all_stable else "check-fail"
        html += f"""        <div class="check-item {writer_class}">
            <div class="check-title">VSS Writers: {'PASS' if report.diagnostic_report.writer_status.all_stable else 'FAIL'}</div>
            <div class="check-details">
                Total Writers: {report.diagnostic_report.writer_status.writer_count}<br>
                Failed Writers: {len(report.diagnostic_report.writer_status.failed_writers)}<br>
"""
        if report.diagnostic_report.writer_status.failed_writers:
            html += "                Failed:<br>\n"
            for writer in report.diagnostic_report.writer_status.failed_writers:
                html += f"                &nbsp;&nbsp;- {writer.get('name', 'Unknown')}: {writer.get('state', 'Unknown')} (Error: {writer.get('error_code', 'N/A')})<br>\n"
        html += """            </div>
        </div>
"""
        
        # System Policies
        policy_class = "check-pass" if not report.diagnostic_report.policy_status.vss_restricted else "check-warning"
        html += f"""        <div class="check-item {policy_class}">
            <div class="check-title">System Policies: {'PASS' if not report.diagnostic_report.policy_status.vss_restricted else 'WARNING'}</div>
            <div class="check-details">
"""
        if report.diagnostic_report.policy_status.vss_restricted:
            html += "                VSS operations may be restricted<br>\n"
            for restriction in report.diagnostic_report.policy_status.restrictions_found:
                html += f"                &nbsp;&nbsp;- {restriction}<br>\n"
        if report.diagnostic_report.policy_status.bitlocker_active:
            html += "                BitLocker: Active<br>\n"
        html += """            </div>
        </div>
"""
        
        # Shadow Copy Creation Test
        if report.test_shadow_creation is not None:
            test_class = "check-pass" if report.test_shadow_creation.success else "check-fail"
            html += f"""        
        <h2>Shadow Copy Creation Test</h2>
        <div class="check-item {test_class}">
            <div class="check-title">Result: {'PASS' if report.test_shadow_creation.success else 'FAIL'}</div>
            <div class="check-details">
                Duration: {report.test_shadow_creation.duration_seconds:.2f} seconds<br>
"""
            if report.test_shadow_creation.success:
                html += f"""                Shadow Copy ID: {report.test_shadow_creation.shadow_copy.shadow_copy_id}<br>
                Creation Time: {report.test_shadow_creation.shadow_copy.creation_time}<br>
"""
            else:
                if report.test_shadow_creation.error:
                    html += f"""                Error Category: {report.test_shadow_creation.error.error_category}<br>
                Error Message: {report.test_shadow_creation.error.error_message}<br>
"""
            html += """            </div>
        </div>
"""
        
        # Issues Found
        if report.issues_found:
            html += """        
        <h2>Issues Found</h2>
        <ul>
"""
            for issue in report.issues_found:
                html += f"""            <li class="issue">{issue}</li>
"""
            html += """        </ul>
"""
        
        # Recommendations
        if report.recommendations:
            html += """        
        <h2>Recommendations</h2>
        <ul>
"""
            for recommendation in report.recommendations:
                html += f"""            <li class="recommendation">{recommendation}</li>
"""
            html += """        </ul>
"""
        
        # Footer
        html += f"""        
        <div class="footer">
            <p>End of Report - Status: <strong>{report.overall_status.upper()}</strong></p>
            <p>Generated: {report.timestamp}</p>
        </div>
    </div>
</body>
</html>
"""
        
        return html

    def attempt_remediation(
        self,
        report: HealthCheckReport,
        interactive: bool = True
    ) -> RemediationResult:
        """Attempt to fix identified issues (with user confirmation if interactive).
        
        This method attempts to automatically remediate VSS issues found during
        the health check. If interactive mode is enabled, it prompts the user
        for confirmation before attempting fixes.
        
        Args:
            report: HealthCheckReport containing identified issues
            interactive: Whether to prompt user for confirmation (default: True)
            
        Returns:
            RemediationResult with details of attempted fixes and outcomes
            
        Requirements:
            - 10.4: Provide specific commands to resolve each issue
        """
        logger.info("[VSSHealthChecker] Starting remediation attempt")
        
        steps_taken = []
        remaining_issues = []
        successful_fixes = 0
        failed_fixes = 0
        
        # If interactive, prompt user for confirmation
        if interactive:
            logger.info("[VSSHealthChecker] Interactive mode: prompting user for confirmation")
            print("\n" + "=" * 80)
            print("VSS ISSUE REMEDIATION")
            print("=" * 80)
            print(f"\nFound {len(report.issues_found)} issue(s) that may be fixable automatically:")
            for i, issue in enumerate(report.issues_found, 1):
                print(f"  {i}. {issue}")
            print("\nThe following remediation steps will be attempted:")
            for i, recommendation in enumerate(report.recommendations, 1):
                print(f"  {i}. {recommendation}")
            print("\n" + "-" * 80)
            response = input("Attempt automatic remediation? (yes/no): ").strip().lower()
            
            if response not in ['yes', 'y']:
                logger.info("[VSSHealthChecker] User declined remediation")
                return RemediationResult(
                    attempted=False,
                    steps_taken=[],
                    successful=False,
                    remaining_issues=report.issues_found,
                    requires_manual_intervention=True
                )
        
        logger.info("[VSSHealthChecker] User confirmed or non-interactive mode, proceeding with remediation")
        
        # Attempt to fix VSS service if not running
        if not report.diagnostic_report.service_status.is_running:
            logger.info("[VSSHealthChecker] Attempting to start VSS service")
            step = "Start VSS service"
            steps_taken.append(step)
            
            try:
                import subprocess
                result = subprocess.run(
                    ["net", "start", "vss"],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.returncode == 0:
                    logger.info("[VSSHealthChecker] VSS service started successfully")
                    successful_fixes += 1
                    if interactive:
                        print(f"✓ {step}: SUCCESS")
                else:
                    logger.warning(f"[VSSHealthChecker] Failed to start VSS service: {result.stderr}")
                    remaining_issues.append("VSS service not running (failed to start automatically)")
                    failed_fixes += 1
                    if interactive:
                        print(f"✗ {step}: FAILED - {result.stderr.strip()}")
            except Exception as e:
                logger.error(f"[VSSHealthChecker] Error starting VSS service: {e}")
                remaining_issues.append(f"VSS service not running (error: {str(e)})")
                failed_fixes += 1
                if interactive:
                    print(f"✗ {step}: ERROR - {str(e)}")
        
        # Check for other issues that cannot be fixed automatically
        for issue in report.issues_found:
            # Disk space issues require manual intervention
            if "disk space" in issue.lower() or "quota" in issue.lower():
                remaining_issues.append(issue)
                logger.info(f"[VSSHealthChecker] Issue requires manual intervention: {issue}")
            
            # Permission issues require manual intervention
            elif "administrator" in issue.lower() or "permission" in issue.lower():
                remaining_issues.append(issue)
                logger.info(f"[VSSHealthChecker] Issue requires manual intervention: {issue}")
            
            # Provider/writer issues - attempt service restart
            elif "provider" in issue.lower() or "writer" in issue.lower():
                if not report.diagnostic_report.service_status.is_running:
                    # Already attempted to start service above
                    remaining_issues.append(issue)
                else:
                    # Try restarting the service
                    logger.info("[VSSHealthChecker] Attempting to restart VSS service for provider/writer issues")
                    step = "Restart VSS service to fix provider/writer issues"
                    steps_taken.append(step)
                    
                    try:
                        import subprocess
                        # Stop service
                        subprocess.run(
                            ["net", "stop", "vss"],
                            capture_output=True,
                            text=True,
                            timeout=30
                        )
                        # Start service
                        result = subprocess.run(
                            ["net", "start", "vss"],
                            capture_output=True,
                            text=True,
                            timeout=30
                        )
                        
                        if result.returncode == 0:
                            logger.info("[VSSHealthChecker] VSS service restarted successfully")
                            successful_fixes += 1
                            if interactive:
                                print(f"✓ {step}: SUCCESS")
                        else:
                            logger.warning(f"[VSSHealthChecker] Failed to restart VSS service: {result.stderr}")
                            remaining_issues.append(issue)
                            failed_fixes += 1
                            if interactive:
                                print(f"✗ {step}: FAILED - {result.stderr.strip()}")
                    except Exception as e:
                        logger.error(f"[VSSHealthChecker] Error restarting VSS service: {e}")
                        remaining_issues.append(issue)
                        failed_fixes += 1
                        if interactive:
                            print(f"✗ {step}: ERROR - {str(e)}")
            
            # Policy/security restrictions require manual intervention
            elif "policy" in issue.lower() or "restricted" in issue.lower():
                remaining_issues.append(issue)
                logger.info(f"[VSSHealthChecker] Issue requires manual intervention: {issue}")
        
        # Determine overall success
        successful = (failed_fixes == 0 and len(remaining_issues) == 0)
        requires_manual = len(remaining_issues) > 0
        
        if interactive:
            print("\n" + "=" * 80)
            print("REMEDIATION SUMMARY")
            print("=" * 80)
            print(f"Steps attempted: {len(steps_taken)}")
            print(f"Successful fixes: {successful_fixes}")
            print(f"Failed fixes: {failed_fixes}")
            print(f"Remaining issues: {len(remaining_issues)}")
            
            if remaining_issues:
                print("\nIssues requiring manual intervention:")
                for i, issue in enumerate(remaining_issues, 1):
                    print(f"  {i}. {issue}")
            
            if successful:
                print("\n✓ All issues resolved successfully!")
            elif successful_fixes > 0:
                print("\n⚠ Some issues resolved, but manual intervention required for remaining issues.")
            else:
                print("\n✗ No issues could be resolved automatically. Manual intervention required.")
            print("=" * 80 + "\n")
        
        logger.info(
            f"[VSSHealthChecker] Remediation complete: attempted={len(steps_taken)}, "
            f"successful={successful_fixes}, failed={failed_fixes}, remaining={len(remaining_issues)}"
        )
        
        return RemediationResult(
            attempted=True,
            steps_taken=steps_taken,
            successful=successful,
            remaining_issues=remaining_issues,
            requires_manual_intervention=requires_manual
        )
