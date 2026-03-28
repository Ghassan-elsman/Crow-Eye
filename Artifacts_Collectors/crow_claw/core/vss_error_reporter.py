"""
VSS error reporting infrastructure for generating actionable error messages.

This module provides the VSSErrorReporter class for generating structured,
user-friendly error reports with remediation guidance when VSS operations fail.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class RemediationStep:
    """A single remediation step to fix a VSS issue.
    
    Attributes:
        step_number: Sequential number of this step
        description: Human-readable description of what to do
        command: Optional command to execute (if applicable)
        requires_admin: Whether this step requires administrator privileges
        requires_reboot: Whether this step requires a system reboot
        estimated_time: Estimated time to complete this step (e.g., "< 1 minute")
    """
    step_number: int
    description: str
    command: Optional[str]
    requires_admin: bool
    requires_reboot: bool
    estimated_time: str


@dataclass
class ErrorReport:
    """Comprehensive error report for VSS failures.
    
    Attributes:
        timestamp: When the error occurred (ISO format)
        error_category: Category of error (service, quota, permissions, disk_space, unknown)
        error_summary: Brief one-line summary of the error
        technical_details: Full technical error details for logging
        user_friendly_message: User-friendly explanation of what went wrong
        remediation_steps: List of actionable steps to fix the issue
        diagnostic_data: Additional diagnostic information (for advanced troubleshooting)
        log_file_path: Path to detailed log file (if available)
    """
    timestamp: str
    error_category: str
    error_summary: str
    technical_details: str
    user_friendly_message: str
    remediation_steps: List[RemediationStep]
    diagnostic_data: Dict[str, Any]
    log_file_path: Optional[str]


class VSSErrorReporter:
    """Generate actionable error reports for VSS failures.
    
    This class transforms technical VSS errors into structured, user-friendly
    error reports with specific remediation guidance.
    
    Requirements:
        - 7.1: Provide structured error message with category, cause, and remediation
        - 7.2: Include command to create shadow copy when none exist
        - 7.3: Include commands to start/restart VSS service for service issues
        - 7.4: Clearly state administrator privileges are required for permission errors
    """
    
    def __init__(self):
        """Initialize the VSSErrorReporter."""
        logger.info("[VSSErrorReporter] Initialized")
    
    def generate_error_report(
        self,
        creation_result: 'ShadowCopyCreationResult',
        context: Dict[str, Any]
    ) -> ErrorReport:
        """Generate comprehensive error report with remediation guidance.
        
        This method analyzes a failed shadow copy creation attempt and generates
        a structured error report with category-specific remediation steps.
        
        Args:
            creation_result: The ShadowCopyCreationResult from a failed creation attempt
            context: Additional context (e.g., file_path, artifact_type, volume)
            
        Returns:
            ErrorReport with structured error information and remediation steps
            
        Requirements:
            - 7.1: Provide structured error message with category, cause, and remediation
            - 7.2: Include command to create shadow copy when none exist
            - 7.3: Include commands to start/restart VSS service
            - 7.4: Clearly state administrator privileges required
        """
        logger.info("[VSSErrorReporter] Generating error report for failed shadow copy creation")
        
        # Generate timestamp
        timestamp = datetime.now().isoformat()
        
        # Extract information from creation result
        error_category = "unknown"
        error_summary = "Shadow copy creation failed"
        technical_details = ""
        user_friendly_message = ""
        remediation_steps = []
        diagnostic_data = {}
        
        # Get volume from context
        volume = context.get('volume', 'C:')
        file_path = context.get('file_path', '')
        
        # Check if we have a VssAdminError
        if creation_result.error:
            error = creation_result.error
            error_category = error.error_category
            error_summary = error.error_message
            technical_details = error.technical_details
            user_friendly_message = error.user_friendly_message
            
            # Convert error remediation steps to RemediationStep objects
            remediation_steps = self._convert_to_remediation_steps(
                error.remediation_steps,
                error_category
            )
        else:
            # No structured error, build from pre-creation checks
            if creation_result.pre_creation_checks:
                checks = creation_result.pre_creation_checks
                
                if checks.blocking_issues:
                    # Determine category from blocking issues
                    error_category = self._categorize_from_issues(checks.blocking_issues)
                    error_summary = checks.blocking_issues[0]
                    technical_details = "\n".join(checks.blocking_issues)
                    user_friendly_message = self._generate_user_message(
                        error_category,
                        checks.blocking_issues
                    )
                    
                    # Generate remediation steps from blocking issues
                    remediation_steps = self._generate_remediation_from_issues(
                        checks.blocking_issues,
                        volume
                    )
        
        # Add diagnostic data
        if creation_result.diagnostics:
            diag = creation_result.diagnostics
            diagnostic_data = {
                'is_admin': diag.is_admin,
                'service_running': diag.service_status.is_running,
                'shadow_copies_exist': diag.shadow_copy_status.exists,
                'shadow_copy_count': diag.shadow_copy_status.count,
                'providers_available': diag.provider_status.providers_available,
                'writers_stable': diag.writer_status.all_stable,
                'sufficient_disk_space': diag.disk_space_status.sufficient_for_shadow,
                'overall_health': diag.overall_health,
                'blocking_issues': diag.blocking_issues
            }
        
        # Add vssadmin command details
        if creation_result.vssadmin_result:
            vss_result = creation_result.vssadmin_result
            diagnostic_data['vssadmin_command'] = vss_result.command
            diagnostic_data['vssadmin_returncode'] = vss_result.returncode
            diagnostic_data['vssadmin_duration'] = vss_result.duration_seconds
        
        # Add context information
        diagnostic_data['volume'] = volume
        if file_path:
            diagnostic_data['file_path'] = file_path
        
        # If no remediation steps were generated, add generic ones
        if not remediation_steps:
            remediation_steps = self._generate_generic_remediation(volume)
        
        logger.info(
            f"[VSSErrorReporter] Generated error report: category={error_category}, "
            f"{len(remediation_steps)} remediation steps"
        )
        
        return ErrorReport(
            timestamp=timestamp,
            error_category=error_category,
            error_summary=error_summary,
            technical_details=technical_details,
            user_friendly_message=user_friendly_message,
            remediation_steps=remediation_steps,
            diagnostic_data=diagnostic_data,
            log_file_path=None  # Could be set by caller if log file exists
        )
    
    def _convert_to_remediation_steps(
        self,
        step_descriptions: List[str],
        error_category: str
    ) -> List[RemediationStep]:
        """Convert simple step descriptions to RemediationStep objects.
        
        Args:
            step_descriptions: List of remediation step descriptions
            error_category: Category of error (affects metadata)
            
        Returns:
            List of RemediationStep objects
        """
        remediation_steps = []
        
        for i, description in enumerate(step_descriptions, start=1):
            # Extract command if present (look for patterns like "command: xyz")
            command = None
            if ':' in description:
                # Check if this looks like a command instruction
                parts = description.split(':', 1)
                if len(parts) == 2:
                    prefix = parts[0].strip().lower()
                    if any(keyword in prefix for keyword in ['run', 'execute', 'use', 'command']):
                        command = parts[1].strip()
            
            # Determine if admin is required
            requires_admin = any(
                keyword in description.lower()
                for keyword in ['administrator', 'admin', 'elevated', 'vssadmin', 'net start', 'sc ']
            )
            
            # Determine if reboot is required
            requires_reboot = any(
                keyword in description.lower()
                for keyword in ['reboot', 'restart the system', 'restart system']
            )
            
            # Estimate time based on step type
            if requires_reboot:
                estimated_time = "5-10 minutes"
            elif 'service' in description.lower() and 'restart' in description.lower():
                estimated_time = "< 1 minute"
            elif 'disk space' in description.lower() or 'delete' in description.lower():
                estimated_time = "1-5 minutes"
            else:
                estimated_time = "< 1 minute"
            
            remediation_steps.append(RemediationStep(
                step_number=i,
                description=description,
                command=command,
                requires_admin=requires_admin,
                requires_reboot=requires_reboot,
                estimated_time=estimated_time
            ))
        
        return remediation_steps
    
    def _categorize_from_issues(self, blocking_issues: List[str]) -> str:
        """Determine error category from blocking issues.
        
        Args:
            blocking_issues: List of blocking issue descriptions
            
        Returns:
            Error category string
        """
        issues_text = ' '.join(blocking_issues).lower()
        
        if 'administrator' in issues_text or 'privilege' in issues_text:
            return 'permissions'
        elif 'service' in issues_text:
            return 'service'
        elif 'disk space' in issues_text or 'quota' in issues_text:
            return 'disk_space'
        elif 'provider' in issues_text:
            return 'provider'
        elif 'policy' in issues_text or 'restricted' in issues_text:
            return 'policy'
        else:
            return 'unknown'
    
    def _generate_user_message(
        self,
        error_category: str,
        blocking_issues: List[str]
    ) -> str:
        """Generate user-friendly error message based on category.
        
        Args:
            error_category: Category of error
            blocking_issues: List of blocking issues
            
        Returns:
            User-friendly error message
        """
        category_messages = {
            'permissions': (
                "Shadow copy creation requires administrator privileges. "
                "Please run this application as Administrator by right-clicking "
                "the executable and selecting 'Run as administrator'."
            ),
            'service': (
                "The Volume Shadow Copy Service (VSS) is not running or is in an invalid state. "
                "VSS must be running to create shadow copies for accessing locked files."
            ),
            'disk_space': (
                "There is insufficient disk space or the VSS storage quota has been exceeded. "
                "Shadow copies require available disk space to store file snapshots."
            ),
            'provider': (
                "No VSS providers are available on this system. VSS providers are required "
                "to create shadow copies. This may indicate a Windows installation issue."
            ),
            'policy': (
                "VSS operations appear to be restricted by Group Policy or security software. "
                "Contact your system administrator to enable VSS functionality."
            ),
            'unknown': (
                "Shadow copy creation failed for an unknown reason. "
                "Please review the diagnostic information and remediation steps below."
            )
        }
        
        return category_messages.get(error_category, category_messages['unknown'])
    
    def _generate_remediation_from_issues(
        self,
        blocking_issues: List[str],
        volume: str
    ) -> List[RemediationStep]:
        """Generate remediation steps from blocking issues.
        
        Args:
            blocking_issues: List of blocking issue descriptions
            volume: Volume letter (e.g., "C:")
            
        Returns:
            List of RemediationStep objects
        """
        steps = []
        step_num = 1
        
        for issue in blocking_issues:
            issue_lower = issue.lower()
            
            if 'administrator' in issue_lower or 'privilege' in issue_lower:
                steps.append(RemediationStep(
                    step_number=step_num,
                    description="Run this application as Administrator",
                    command=None,
                    requires_admin=True,
                    requires_reboot=False,
                    estimated_time="< 1 minute"
                ))
                step_num += 1
                steps.append(RemediationStep(
                    step_number=step_num,
                    description="Right-click the application executable and select 'Run as administrator'",
                    command=None,
                    requires_admin=False,
                    requires_reboot=False,
                    estimated_time="< 1 minute"
                ))
                step_num += 1
            
            elif 'service' in issue_lower and 'not running' in issue_lower:
                steps.append(RemediationStep(
                    step_number=step_num,
                    description="Start the VSS service",
                    command="net start VSS",
                    requires_admin=True,
                    requires_reboot=False,
                    estimated_time="< 1 minute"
                ))
                step_num += 1
                steps.append(RemediationStep(
                    step_number=step_num,
                    description="If service fails to start, restart the system",
                    command=None,
                    requires_admin=True,
                    requires_reboot=True,
                    estimated_time="5-10 minutes"
                ))
                step_num += 1
            
            elif 'disk space' in issue_lower or 'quota' in issue_lower:
                steps.append(RemediationStep(
                    step_number=step_num,
                    description=f"Free up disk space on {volume} by deleting unnecessary files",
                    command="cleanmgr.exe",
                    requires_admin=False,
                    requires_reboot=False,
                    estimated_time="1-5 minutes"
                ))
                step_num += 1
                steps.append(RemediationStep(
                    step_number=step_num,
                    description=f"Delete old shadow copies to free VSS quota",
                    command=f"vssadmin delete shadows /for={volume} /oldest",
                    requires_admin=True,
                    requires_reboot=False,
                    estimated_time="< 1 minute"
                ))
                step_num += 1
            
            elif 'provider' in issue_lower:
                steps.append(RemediationStep(
                    step_number=step_num,
                    description="Verify VSS providers are installed",
                    command="vssadmin list providers",
                    requires_admin=True,
                    requires_reboot=False,
                    estimated_time="< 1 minute"
                ))
                step_num += 1
                steps.append(RemediationStep(
                    step_number=step_num,
                    description="Run system file checker to repair Windows components",
                    command="sfc /scannow",
                    requires_admin=True,
                    requires_reboot=False,
                    estimated_time="10-30 minutes"
                ))
                step_num += 1
        
        # If no specific steps were generated, add generic ones
        if not steps:
            steps = self._generate_generic_remediation(volume)
        
        return steps
    
    def _generate_generic_remediation(self, volume: str) -> List[RemediationStep]:
        """Generate generic remediation steps when specific cause is unknown.
        
        Args:
            volume: Volume letter (e.g., "C:")
            
        Returns:
            List of generic RemediationStep objects
        """
        return [
            RemediationStep(
                step_number=1,
                description="Ensure you are running as Administrator",
                command=None,
                requires_admin=True,
                requires_reboot=False,
                estimated_time="< 1 minute"
            ),
            RemediationStep(
                step_number=2,
                description="Verify VSS service is running",
                command="sc query VSS",
                requires_admin=True,
                requires_reboot=False,
                estimated_time="< 1 minute"
            ),
            RemediationStep(
                step_number=3,
                description="Check available disk space",
                command=f"vssadmin list shadowstorage /for={volume}",
                requires_admin=True,
                requires_reboot=False,
                estimated_time="< 1 minute"
            ),
            RemediationStep(
                step_number=4,
                description="Review Windows Event Logs for VSS errors",
                command="eventvwr.msc",
                requires_admin=False,
                requires_reboot=False,
                estimated_time="2-5 minutes"
            ),
            RemediationStep(
                step_number=5,
                description="Restart the system if issues persist",
                command=None,
                requires_admin=True,
                requires_reboot=True,
                estimated_time="5-10 minutes"
            )
        ]
    
    def format_for_gui(self, report: ErrorReport) -> str:
        """Format error report for GUI display (concise).
        
        This method generates a concise, user-friendly error message suitable
        for display in a GUI dialog or notification.
        
        Args:
            report: ErrorReport to format
            
        Returns:
            Formatted string for GUI display
            
        Requirements:
            - 7.5: Format error report for GUI (concise)
        """
        lines = []
        
        # Title
        lines.append(f"VSS Error: {report.error_summary}")
        lines.append("")
        
        # User-friendly message
        if report.user_friendly_message:
            lines.append(report.user_friendly_message)
            lines.append("")
        
        # Top 3 remediation steps (keep it concise for GUI)
        if report.remediation_steps:
            lines.append("Recommended Actions:")
            for step in report.remediation_steps[:3]:
                lines.append(f"  {step.step_number}. {step.description}")
                if step.command:
                    lines.append(f"     Command: {step.command}")
            
            if len(report.remediation_steps) > 3:
                lines.append(f"  ... and {len(report.remediation_steps) - 3} more steps")
            lines.append("")
        
        # Reference to log file if available
        if report.log_file_path:
            lines.append(f"For more details, see: {report.log_file_path}")
        
        return "\n".join(lines)
    
    def format_for_log(self, report: ErrorReport) -> str:
        """Format error report for log file (detailed).
        
        This method generates a detailed error report suitable for logging,
        including all technical details and diagnostic information.
        
        Args:
            report: ErrorReport to format
            
        Returns:
            Formatted string for log file
            
        Requirements:
            - 7.5: Format error report for log file (detailed)
        """
        lines = []
        
        # Header
        lines.append("=" * 80)
        lines.append("VSS ERROR REPORT")
        lines.append("=" * 80)
        lines.append(f"Timestamp: {report.timestamp}")
        lines.append(f"Category: {report.error_category}")
        lines.append(f"Summary: {report.error_summary}")
        lines.append("")
        
        # User-friendly message
        if report.user_friendly_message:
            lines.append("User Message:")
            lines.append(report.user_friendly_message)
            lines.append("")
        
        # Technical details
        if report.technical_details:
            lines.append("Technical Details:")
            lines.append(report.technical_details)
            lines.append("")
        
        # Diagnostic data
        if report.diagnostic_data:
            lines.append("Diagnostic Information:")
            for key, value in report.diagnostic_data.items():
                lines.append(f"  {key}: {value}")
            lines.append("")
        
        # Remediation steps
        if report.remediation_steps:
            lines.append("Remediation Steps:")
            for step in report.remediation_steps:
                lines.append(f"  Step {step.step_number}: {step.description}")
                if step.command:
                    lines.append(f"    Command: {step.command}")
                lines.append(f"    Requires Admin: {step.requires_admin}")
                lines.append(f"    Requires Reboot: {step.requires_reboot}")
                lines.append(f"    Estimated Time: {step.estimated_time}")
                lines.append("")
        
        lines.append("=" * 80)
        
        return "\n".join(lines)
    
    def format_for_manifest(self, report: ErrorReport) -> Dict[str, Any]:
        """Format error report for manifest JSON.
        
        This method generates a structured dictionary suitable for inclusion
        in a JSON manifest file.
        
        Args:
            report: ErrorReport to format
            
        Returns:
            Dictionary suitable for JSON serialization
            
        Requirements:
            - 7.5: Format error report for manifest (JSON)
        """
        return {
            'timestamp': report.timestamp,
            'error_category': report.error_category,
            'error_summary': report.error_summary,
            'user_friendly_message': report.user_friendly_message,
            'technical_details': report.technical_details,
            'remediation_steps': [
                {
                    'step_number': step.step_number,
                    'description': step.description,
                    'command': step.command,
                    'requires_admin': step.requires_admin,
                    'requires_reboot': step.requires_reboot,
                    'estimated_time': step.estimated_time
                }
                for step in report.remediation_steps
            ],
            'diagnostic_data': report.diagnostic_data,
            'log_file_path': report.log_file_path
        }
