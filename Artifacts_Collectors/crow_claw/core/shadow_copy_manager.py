"""
Shadow copy creation and management with comprehensive diagnostics.

This module provides the ShadowCopyManager class for creating and managing
VSS shadow copies with detailed error handling, pre-creation checks, and
automatic remediation attempts.
"""

import ctypes
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

try:
    from .vss_diagnostics import VSSDiagnostics, ShadowCopy
except ImportError:
    # Fallback for when module is imported directly (e.g., in tests)
    from vss_diagnostics import VSSDiagnostics, ShadowCopy

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class VssAdminResult:
    """Result from executing a vssadmin command.
    
    Attributes:
        returncode: Command exit code
        stdout: Standard output from the command
        stderr: Standard error from the command
        duration_seconds: How long the command took to execute
        command: The full command that was executed
    """
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    command: str


@dataclass
class VssAdminError:
    """Structured error information from vssadmin failures.
    
    Attributes:
        error_code: Numeric error code from vssadmin
        error_category: Category of error (service, quota, permissions, disk_space, unknown)
        error_message: Brief error description
        technical_details: Full technical error details
        user_friendly_message: User-friendly explanation
        remediation_steps: List of actionable steps to fix the issue
        is_retryable: Whether the operation can be retried
    """
    error_code: int
    error_category: str
    error_message: str
    technical_details: str
    user_friendly_message: str
    remediation_steps: List[str]
    is_retryable: bool


@dataclass
class PreCreationCheckResult:
    """Results from pre-creation diagnostic checks.
    
    Attributes:
        all_passed: Whether all checks passed
        checks: Dictionary mapping check name to pass/fail status
        blocking_issues: List of critical issues preventing creation
        warnings: List of non-critical warnings
        auto_fix_attempted: Whether automatic fixes were attempted
        auto_fix_results: Results from automatic fix attempts (if any)
    """
    all_passed: bool
    checks: Dict[str, bool]
    blocking_issues: List[str]
    warnings: List[str]
    auto_fix_attempted: bool
    auto_fix_results: Optional['FixResult']


@dataclass
class FixResult:
    """Results from automatic remediation attempts.
    
    Attributes:
        attempted_fixes: List of fixes that were attempted
        successful_fixes: List of fixes that succeeded
        failed_fixes: List of fixes that failed
        overall_success: Whether all attempted fixes succeeded
    """
    attempted_fixes: List[str]
    successful_fixes: List[str]
    failed_fixes: List[str]
    overall_success: bool


@dataclass
class ShadowCopyCreationResult:
    """Complete result from a shadow copy creation attempt.
    
    Attributes:
        success: Whether shadow copy creation succeeded
        shadow_copy: The created shadow copy (if successful)
        duration_seconds: How long the creation took
        pre_creation_checks: Results from pre-creation diagnostic checks
        vssadmin_result: Raw result from vssadmin command
        error: Structured error information (if failed)
        diagnostics: Full diagnostic report (if failed)
        remediation_steps: List of actionable steps to fix issues
    """
    success: bool
    shadow_copy: Optional[ShadowCopy]
    duration_seconds: float
    pre_creation_checks: PreCreationCheckResult
    vssadmin_result: VssAdminResult
    error: Optional[VssAdminError]
    diagnostics: Optional['DiagnosticReport']
    remediation_steps: List[str]


class ShadowCopyManager:
    """Enhanced shadow copy creation and management.
    
    This class manages VSS shadow copy creation with comprehensive diagnostics,
    pre-creation checks, automatic remediation, and per-volume attempt tracking.
    
    Requirements:
        - 8.5: Only attempt shadow copy creation once per volume per collection session
        - 3.1: Execute vssadmin create shadow and capture all output
        - 3.2: Log return code, stdout, and stderr on failure
        - 3.3: Check for common failure causes before attempting creation
        - 3.4: Provide actionable remediation steps for specific error codes
        - 3.5: Verify administrator privileges before attempting creation
    """
    
    def __init__(self, diagnostics: VSSDiagnostics):
        """Initialize the ShadowCopyManager.
        
        Args:
            diagnostics: VSSDiagnostics instance for running diagnostic checks
            
        Requirements:
            - 8.5: Track creation attempts per volume
        """
        self.diagnostics = diagnostics
        self.creation_attempts: Dict[str, int] = {}  # Track attempts per volume
        logger.info("[ShadowCopyManager] Initialized with VSSDiagnostics integration")
    
    def create_shadow_copy(
        self,
        volume: str = "C:",
        timeout: int = 120
    ) -> ShadowCopyCreationResult:
        """Create a shadow copy with comprehensive diagnostics.
        
        Process:
        1. Check if creation has already been attempted for this volume
        2. Run pre-creation diagnostics
        3. Attempt to fix common issues automatically
        4. Execute vssadmin create shadow
        5. Verify creation success
        6. Return detailed result with diagnostics
        
        Args:
            volume: Drive letter to create shadow copy for (e.g., "C:" or "C")
            timeout: Maximum time to wait for creation (seconds)
            
        Returns:
            ShadowCopyCreationResult with detailed information about the attempt
            
        Requirements:
            - 8.5: Only attempt creation once per volume per session
            - 3.1: Execute vssadmin create shadow and capture all output
            - 3.2: Log return code, stdout, and stderr
            - 8.4: Log attempt, duration, and outcome
        """
        # Normalize volume format
        if not volume.endswith(":"):
            volume = volume + ":"
        
        start_time = time.time()
        
        logger.info(f"[ShadowCopyManager] Starting shadow copy creation for volume {volume}")
        
        # Check if we've already attempted creation for this volume
        if volume in self.creation_attempts:
            attempts = self.creation_attempts[volume]
            logger.warning(
                f"[ShadowCopyManager] Shadow copy creation already attempted {attempts} time(s) "
                f"for volume {volume} in this session"
            )
            
            # Return failure result indicating we won't retry
            duration = time.time() - start_time
            return ShadowCopyCreationResult(
                success=False,
                shadow_copy=None,
                duration_seconds=duration,
                pre_creation_checks=PreCreationCheckResult(
                    all_passed=False,
                    checks={"already_attempted": False},
                    blocking_issues=[
                        f"Shadow copy creation already attempted for volume {volume} in this session"
                    ],
                    warnings=[],
                    auto_fix_attempted=False,
                    auto_fix_results=None
                ),
                vssadmin_result=VssAdminResult(
                    returncode=-1,
                    stdout="",
                    stderr="",
                    duration_seconds=0.0,
                    command=""
                ),
                error=VssAdminError(
                    error_code=-1,
                    error_category="session_limit",
                    error_message="Creation already attempted for this volume",
                    technical_details=f"Shadow copy creation was already attempted {attempts} time(s) for {volume}",
                    user_friendly_message=(
                        f"Shadow copy creation was already attempted for volume {volume} in this session. "
                        "To prevent repeated failures, we only attempt creation once per volume per session."
                    ),
                    remediation_steps=[
                        "Restart the collection to reset attempt tracking",
                        "Manually create a shadow copy using: vssadmin create shadow /for=" + volume,
                        "Check if a shadow copy already exists: vssadmin list shadows"
                    ],
                    is_retryable=False
                ),
                diagnostics=None,
                remediation_steps=[
                    "Restart the collection to reset attempt tracking",
                    f"Manually create a shadow copy using: vssadmin create shadow /for={volume}"
                ]
            )
        
        # Track this attempt
        self.creation_attempts[volume] = self.creation_attempts.get(volume, 0) + 1
        logger.info(f"[ShadowCopyManager] Attempt #{self.creation_attempts[volume]} for volume {volume}")
        
        # Run pre-creation checks
        logger.info("[ShadowCopyManager] Running pre-creation diagnostic checks")
        pre_checks = self._run_pre_creation_checks(volume)
        
        if not pre_checks.all_passed:
            logger.warning(
                f"[ShadowCopyManager] Pre-creation checks failed: {len(pre_checks.blocking_issues)} blocking issue(s)"
            )
            for issue in pre_checks.blocking_issues:
                logger.warning(f"[ShadowCopyManager]   - {issue}")
            
            # Attempt automatic fixes if possible
            if pre_checks.blocking_issues:
                logger.info("[ShadowCopyManager] Attempting automatic fixes")
                fix_result = self._attempt_automatic_fixes(pre_checks.blocking_issues)
                pre_checks.auto_fix_attempted = True
                pre_checks.auto_fix_results = fix_result
                
                if fix_result.overall_success:
                    logger.info("[ShadowCopyManager] Automatic fixes succeeded, re-running checks")
                    # Re-run checks after fixes
                    pre_checks = self._run_pre_creation_checks(volume)
                else:
                    logger.warning(
                        f"[ShadowCopyManager] Automatic fixes failed: {len(fix_result.failed_fixes)} fix(es) failed"
                    )
        
        # If checks still fail after fixes, return failure
        if not pre_checks.all_passed:
            duration = time.time() - start_time
            logger.error(
                f"[ShadowCopyManager] Cannot proceed with shadow copy creation due to blocking issues "
                f"(duration: {duration:.2f}s)"
            )
            
            return ShadowCopyCreationResult(
                success=False,
                shadow_copy=None,
                duration_seconds=duration,
                pre_creation_checks=pre_checks,
                vssadmin_result=VssAdminResult(
                    returncode=-1,
                    stdout="",
                    stderr="",
                    duration_seconds=0.0,
                    command=""
                ),
                error=VssAdminError(
                    error_code=-1,
                    error_category="pre_check_failure",
                    error_message="Pre-creation checks failed",
                    technical_details="; ".join(pre_checks.blocking_issues),
                    user_friendly_message=(
                        "Shadow copy creation cannot proceed due to system issues. "
                        "Please resolve the issues listed below."
                    ),
                    remediation_steps=self._generate_remediation_from_checks(pre_checks),
                    is_retryable=True
                ),
                diagnostics=None,
                remediation_steps=self._generate_remediation_from_checks(pre_checks)
            )
        
        # Get shadow copy count before creation for verification
        shadow_status_before = self.diagnostics.check_shadow_copies(volume)
        count_before = shadow_status_before.count
        logger.debug(f"[ShadowCopyManager] Shadow copy count before creation: {count_before}")
        
        # Execute vssadmin create shadow
        logger.info(f"[ShadowCopyManager] Executing vssadmin create shadow /for={volume}")
        vssadmin_result = self._execute_vssadmin_create(volume, timeout)
        
        # Log the result
        logger.info(
            f"[ShadowCopyManager] vssadmin create shadow completed with return code {vssadmin_result.returncode} "
            f"(duration: {vssadmin_result.duration_seconds:.2f}s)"
        )
        logger.debug(f"[ShadowCopyManager] stdout: {vssadmin_result.stdout[:500]}")  # First 500 chars
        if vssadmin_result.stderr:
            logger.debug(f"[ShadowCopyManager] stderr: {vssadmin_result.stderr}")
        
        # Check if creation succeeded
        if vssadmin_result.returncode == 0:
            # Verify creation by checking if shadow copy count increased
            logger.info("[ShadowCopyManager] Verifying shadow copy creation")
            if self._verify_creation_success(volume, count_before):
                # Get the newly created shadow copy
                shadow_status_after = self.diagnostics.check_shadow_copies(volume)
                new_shadow = shadow_status_after.most_recent
                
                duration = time.time() - start_time
                logger.info(
                    f"[ShadowCopyManager] Shadow copy creation succeeded for volume {volume} "
                    f"(total duration: {duration:.2f}s)"
                )
                
                return ShadowCopyCreationResult(
                    success=True,
                    shadow_copy=new_shadow,
                    duration_seconds=duration,
                    pre_creation_checks=pre_checks,
                    vssadmin_result=vssadmin_result,
                    error=None,
                    diagnostics=None,
                    remediation_steps=[]
                )
            else:
                logger.error("[ShadowCopyManager] Shadow copy creation reported success but verification failed")
                # Fall through to error handling
        
        # Creation failed - parse error and generate detailed result
        logger.error(f"[ShadowCopyManager] Shadow copy creation failed for volume {volume}")
        error = self._parse_vssadmin_error(
            vssadmin_result.returncode,
            vssadmin_result.stdout,
            vssadmin_result.stderr
        )
        
        duration = time.time() - start_time
        
        return ShadowCopyCreationResult(
            success=False,
            shadow_copy=None,
            duration_seconds=duration,
            pre_creation_checks=pre_checks,
            vssadmin_result=vssadmin_result,
            error=error,
            diagnostics=None,  # Could run full diagnostics here if needed
            remediation_steps=error.remediation_steps
        )

    
    def _run_pre_creation_checks(self, volume: str) -> PreCreationCheckResult:
        """Run all prerequisite checks before attempting shadow copy creation.
        
        Args:
            volume: Drive letter to check
            
        Returns:
            PreCreationCheckResult with detailed check results
            
        Requirements:
            - 3.3: Check for common failure causes (disk space, VSS quota, permissions)
            - 3.5: Verify administrator privileges before attempting creation
        """
        logger.debug(f"[ShadowCopyManager] Running pre-creation checks for volume {volume}")
        
        checks = {}
        blocking_issues = []
        warnings = []
        
        # Check 1: Administrator privileges
        logger.debug("[ShadowCopyManager] Checking administrator privileges")
        try:
            if os.name == 'nt':
                is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
            else:
                is_admin = os.getuid() == 0
            checks["admin_privileges"] = is_admin
            
            if not is_admin:
                blocking_issues.append("Administrator privileges required for shadow copy creation")
                logger.warning("[ShadowCopyManager] Not running as administrator")
            else:
                logger.debug("[ShadowCopyManager] Running as administrator")
        except Exception as e:
            logger.warning(f"[ShadowCopyManager] Could not check admin privileges: {e}")
            checks["admin_privileges"] = False
            blocking_issues.append(f"Could not verify administrator privileges: {e}")
        
        # Check 2: VSS service status
        logger.debug("[ShadowCopyManager] Checking VSS service status")
        service_status = self.diagnostics.check_vss_service_status()
        checks["vss_service_running"] = service_status.is_running
        
        if not service_status.is_running:
            if service_status.can_start:
                warnings.append(f"VSS service is not running: {service_status.status_message}")
                logger.warning(f"[ShadowCopyManager] VSS service not running but can be started")
            else:
                blocking_issues.append(f"VSS service is not running: {service_status.status_message}")
                logger.warning(f"[ShadowCopyManager] VSS service not running and cannot be started")
        else:
            logger.debug("[ShadowCopyManager] VSS service is running")
        
        # Check 3: Disk space and VSS quota
        logger.debug("[ShadowCopyManager] Checking disk space and VSS quota")
        disk_status = self.diagnostics.check_disk_space(volume)
        checks["sufficient_disk_space"] = disk_status.sufficient_for_shadow
        
        if not disk_status.sufficient_for_shadow:
            blocking_issues.append(
                f"Insufficient disk space or VSS quota: "
                f"{disk_status.free_space_bytes / (1024**3):.2f} GB free, "
                f"VSS used: {disk_status.vss_used_bytes / (1024**3):.2f} GB / "
                f"{disk_status.vss_max_bytes / (1024**3):.2f} GB"
            )
            logger.warning(
                f"[ShadowCopyManager] Insufficient disk space: "
                f"{disk_status.free_space_bytes / (1024**3):.2f} GB free"
            )
        else:
            logger.debug(
                f"[ShadowCopyManager] Sufficient disk space: "
                f"{disk_status.free_space_bytes / (1024**3):.2f} GB free"
            )
        
        # Check 4: VSS providers
        logger.debug("[ShadowCopyManager] Checking VSS providers")
        provider_status = self.diagnostics.check_vss_providers()
        checks["vss_providers_available"] = provider_status.providers_available
        
        if not provider_status.providers_available:
            blocking_issues.append(
                f"No VSS providers available: {provider_status.error_message or 'Unknown error'}"
            )
            logger.warning("[ShadowCopyManager] No VSS providers available")
        else:
            logger.debug(f"[ShadowCopyManager] {provider_status.provider_count} VSS provider(s) available")
        
        # Check 5: VSS writers
        logger.debug("[ShadowCopyManager] Checking VSS writers")
        writer_status = self.diagnostics.check_vss_writers()
        checks["vss_writers_stable"] = writer_status.all_stable
        
        if not writer_status.all_stable:
            warnings.append(
                f"{len(writer_status.failed_writers)} VSS writer(s) in failed state"
            )
            logger.warning(
                f"[ShadowCopyManager] {len(writer_status.failed_writers)} VSS writer(s) failed"
            )
        else:
            logger.debug(f"[ShadowCopyManager] All {writer_status.writer_count} VSS writer(s) stable")
        
        all_passed = len(blocking_issues) == 0
        
        logger.info(
            f"[ShadowCopyManager] Pre-creation checks complete: "
            f"{'PASSED' if all_passed else 'FAILED'} "
            f"({len(blocking_issues)} blocking issue(s), {len(warnings)} warning(s))"
        )
        
        return PreCreationCheckResult(
            all_passed=all_passed,
            checks=checks,
            blocking_issues=blocking_issues,
            warnings=warnings,
            auto_fix_attempted=False,
            auto_fix_results=None
        )
    
    def _attempt_automatic_fixes(self, issues: List[str]) -> FixResult:
        """Attempt to automatically fix common issues.
        
        Args:
            issues: List of blocking issues to attempt to fix
            
        Returns:
            FixResult with details of fix attempts
        """
        logger.info(f"[ShadowCopyManager] Attempting automatic fixes for {len(issues)} issue(s)")
        
        attempted_fixes = []
        successful_fixes = []
        failed_fixes = []
        
        for issue in issues:
            issue_lower = issue.lower()
            
            # Fix 1: Start VSS service if not running
            if "vss service" in issue_lower and "not running" in issue_lower:
                fix_name = "Start VSS service"
                attempted_fixes.append(fix_name)
                logger.info("[ShadowCopyManager] Attempting to start VSS service")
                
                try:
                    result = subprocess.run(
                        ["net", "start", "VSS"],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    
                    if result.returncode == 0:
                        logger.info("[ShadowCopyManager] Successfully started VSS service")
                        successful_fixes.append(fix_name)
                        # Wait a moment for service to stabilize
                        time.sleep(2)
                    else:
                        logger.warning(
                            f"[ShadowCopyManager] Failed to start VSS service: {result.stderr}"
                        )
                        failed_fixes.append(fix_name)
                        
                except Exception as e:
                    logger.warning(f"[ShadowCopyManager] Error starting VSS service: {e}")
                    failed_fixes.append(fix_name)
        
        overall_success = len(failed_fixes) == 0 and len(successful_fixes) > 0
        
        logger.info(
            f"[ShadowCopyManager] Automatic fixes complete: "
            f"{len(successful_fixes)} succeeded, {len(failed_fixes)} failed"
        )
        
        return FixResult(
            attempted_fixes=attempted_fixes,
            successful_fixes=successful_fixes,
            failed_fixes=failed_fixes,
            overall_success=overall_success
        )
    
    def _execute_vssadmin_create(self, volume: str, timeout: int) -> VssAdminResult:
        """Execute shadow copy creation command using PowerShell/WMIC.
        
        Note: vssadmin create shadow was removed in Windows 10/11.
        We use PowerShell WMI or WMIC as alternatives.
        
        Args:
            volume: Drive letter to create shadow copy for
            timeout: Maximum time to wait for creation (seconds)
            
        Returns:
            VssAdminResult with command execution details
            
        Requirements:
            - 3.1: Execute shadow copy creation and capture all output
            - 3.2: Log return code, stdout, and stderr
        """
        # Normalize volume format for WMI (needs trailing backslash)
        volume_path = volume if volume.endswith("\\") else volume + "\\"
        
        # Try PowerShell first (preferred method for Windows 10/11)
        powershell_command = f"(Get-WmiObject -List Win32_ShadowCopy).Create('{volume_path}', 'ClientAccessible')"
        logger.info(f"[ShadowCopyManager] Executing PowerShell command: {powershell_command}")
        
        start_time = time.time()
        
        try:
            # Try PowerShell method first
            result = subprocess.run(
                ["powershell", "-Command", powershell_command],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            duration = time.time() - start_time
            
            logger.debug(
                f"[ShadowCopyManager] PowerShell command completed in {duration:.2f}s with return code {result.returncode}"
            )
            
            # Check if PowerShell command succeeded
            if result.returncode == 0 and "ReturnValue" in result.stdout:
                # Parse return value from PowerShell output
                # Format can be: "ReturnValue : 0", "ReturnValue      : 0", or "ReturnValue=0"
                # Extract the return value number
                match = re.search(r'ReturnValue\s*[:=]\s*(\d+)', result.stdout)
                if match:
                    return_value = int(match.group(1))
                    if return_value == 0:
                        logger.info("[ShadowCopyManager] Shadow copy created successfully via PowerShell")
                        return VssAdminResult(
                            returncode=0,
                            stdout=result.stdout,
                            stderr=result.stderr,
                            duration_seconds=duration,
                            command=f"powershell -Command {powershell_command}"
                        )
                    else:
                        # PowerShell command ran but returned error
                        logger.error(f"[ShadowCopyManager] PowerShell returned ReturnValue={return_value}")
                        return VssAdminResult(
                            returncode=return_value,
                            stdout=result.stdout,
                            stderr=result.stderr if result.stderr else f"Shadow copy creation failed with ReturnValue={return_value}",
                            duration_seconds=duration,
                            command=f"powershell -Command {powershell_command}"
                        )
                else:
                    logger.warning(f"[ShadowCopyManager] Could not parse ReturnValue from PowerShell output")
                    return VssAdminResult(
                        returncode=1,
                        stdout=result.stdout,
                        stderr=result.stderr if result.stderr else "Could not parse ReturnValue from output",
                        duration_seconds=duration,
                        command=f"powershell -Command {powershell_command}"
                    )
            
            # PowerShell failed, try WMIC as fallback
            logger.warning("[ShadowCopyManager] PowerShell method failed, trying WMIC fallback")
            wmic_command = f"wmic shadowcopy call create Volume={volume_path}"
            logger.info(f"[ShadowCopyManager] Executing WMIC command: {wmic_command}")
            
            wmic_start = time.time()
            wmic_result = subprocess.run(
                ["wmic", "shadowcopy", "call", "create", f"Volume={volume_path}"],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            wmic_duration = time.time() - wmic_start
            total_duration = time.time() - start_time
            
            logger.debug(
                f"[ShadowCopyManager] WMIC command completed in {wmic_duration:.2f}s with return code {wmic_result.returncode}"
            )
            
            # WMIC returns 0 on success
            if wmic_result.returncode == 0:
                logger.info("[ShadowCopyManager] Shadow copy created successfully via WMIC")
            
            return VssAdminResult(
                returncode=wmic_result.returncode,
                stdout=wmic_result.stdout,
                stderr=wmic_result.stderr,
                duration_seconds=total_duration,
                command=f"wmic shadowcopy call create Volume={volume_path}"
            )
            
        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            logger.error(f"[ShadowCopyManager] Command timed out after {timeout}s")
            
            return VssAdminResult(
                returncode=-1,
                stdout="",
                stderr=f"Command timed out after {timeout} seconds",
                duration_seconds=duration,
                command=f"powershell/wmic shadow copy creation"
            )
            
        except FileNotFoundError as e:
            duration = time.time() - start_time
            logger.error(f"[ShadowCopyManager] Command not found: {e}")
            
            return VssAdminResult(
                returncode=-1,
                stdout="",
                stderr=f"Command not found: {str(e)}",
                duration_seconds=duration,
                command=f"powershell/wmic shadow copy creation"
            )
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"[ShadowCopyManager] Unexpected error executing vssadmin: {e}")
            
            return VssAdminResult(
                returncode=-1,
                stdout="",
                stderr=f"Unexpected error: {str(e)}",
                duration_seconds=duration,
                command=command
            )
    
    def _verify_creation_success(self, volume: str, before_count: int) -> bool:
        """Verify that a new shadow copy was actually created.
        
        Args:
            volume: Drive letter that was used for creation
            before_count: Number of shadow copies before creation attempt
            
        Returns:
            True if a new shadow copy was created, False otherwise
        """
        logger.debug(f"[ShadowCopyManager] Verifying shadow copy creation for volume {volume}")
        
        # Re-enumerate shadow copies
        shadow_status = self.diagnostics.check_shadow_copies(volume)
        
        if shadow_status.error_message:
            logger.warning(
                f"[ShadowCopyManager] Could not verify creation: {shadow_status.error_message}"
            )
            return False
        
        after_count = shadow_status.count
        logger.debug(
            f"[ShadowCopyManager] Shadow copy count: before={before_count}, after={after_count}"
        )
        
        if after_count > before_count:
            logger.info(
                f"[ShadowCopyManager] Verification successful: "
                f"shadow copy count increased from {before_count} to {after_count}"
            )
            return True
        else:
            logger.warning(
                f"[ShadowCopyManager] Verification failed: "
                f"shadow copy count did not increase (still {after_count})"
            )
            return False
    
    def _parse_vssadmin_error(
        self,
        returncode: int,
        stdout: str,
        stderr: str
    ) -> VssAdminError:
        """Parse vssadmin error output into structured error.
        
        Args:
            returncode: Command exit code
            stdout: Standard output
            stderr: Standard error
            
        Returns:
            VssAdminError with structured error information
            
        Requirements:
            - 3.4: Provide actionable remediation steps for specific error codes
        """
        logger.debug(f"[ShadowCopyManager] Parsing vssadmin error (return code: {returncode})")
        
        # Combine stdout and stderr for error analysis
        error_text = (stdout + "\n" + stderr).lower()
        
        # Map common error patterns to structured errors
        # Based on VSS_ERROR_CODES from design document
        
        if "access" in error_text and "denied" in error_text:
            return VssAdminError(
                error_code=0x80070005,
                error_category="permissions",
                error_message="Access denied - insufficient privileges",
                technical_details=f"Return code: {returncode}\nStdout: {stdout}\nStderr: {stderr}",
                user_friendly_message=(
                    "Shadow copy creation failed due to insufficient privileges. "
                    "You must run this program as Administrator."
                ),
                remediation_steps=[
                    "Right-click the program and select 'Run as Administrator'",
                    "Verify UAC is not blocking the operation",
                    "Check that your user account has administrator rights"
                ],
                is_retryable=True
            )
        
        elif "insufficient storage" in error_text or "not enough" in error_text:
            return VssAdminError(
                error_code=0x8004230C,
                error_category="disk_space",
                error_message="Insufficient disk space for shadow copy",
                technical_details=f"Return code: {returncode}\nStdout: {stdout}\nStderr: {stderr}",
                user_friendly_message=(
                    "Shadow copy creation failed due to insufficient disk space. "
                    "Free up disk space or increase VSS shadow storage allocation."
                ),
                remediation_steps=[
                    "Free up disk space by deleting unnecessary files",
                    "Increase VSS shadow storage: vssadmin resize shadowstorage /for=C: /maxsize=10GB",
                    "Delete old shadow copies: vssadmin delete shadows /for=C: /oldest"
                ],
                is_retryable=True
            )
        
        elif "maximum number" in error_text or "quota" in error_text:
            return VssAdminError(
                error_code=0x80042308,
                error_category="quota",
                error_message="Maximum number of shadow copies reached",
                technical_details=f"Return code: {returncode}\nStdout: {stdout}\nStderr: {stderr}",
                user_friendly_message=(
                    "Shadow copy creation failed because the maximum number of shadow copies "
                    "has been reached. Delete old shadow copies or increase the quota."
                ),
                remediation_steps=[
                    "Delete old shadow copies: vssadmin delete shadows /for=C: /oldest",
                    "Delete all shadow copies: vssadmin delete shadows /for=C: /all",
                    "Increase VSS quota: vssadmin resize shadowstorage /for=C: /maxsize=UNBOUNDED"
                ],
                is_retryable=True
            )
        
        elif "provider" in error_text and ("not registered" in error_text or "not found" in error_text):
            return VssAdminError(
                error_code=0x80042306,
                error_category="provider",
                error_message="No VSS provider is registered",
                technical_details=f"Return code: {returncode}\nStdout: {stdout}\nStderr: {stderr}",
                user_friendly_message=(
                    "Shadow copy creation failed because no VSS provider is registered. "
                    "This may indicate a corrupted Windows installation."
                ),
                remediation_steps=[
                    "Verify Windows installation integrity: sfc /scannow",
                    "Check VSS providers: vssadmin list providers",
                    "Restart the VSS service: net stop VSS && net start VSS",
                    "Consider reinstalling Windows if the issue persists"
                ],
                is_retryable=False
            )
        
        elif "bad state" in error_text or "invalid state" in error_text:
            return VssAdminError(
                error_code=0x80042301,
                error_category="service",
                error_message="VSS service is in an invalid state",
                technical_details=f"Return code: {returncode}\nStdout: {stdout}\nStderr: {stderr}",
                user_friendly_message=(
                    "Shadow copy creation failed because the VSS service is in an invalid state. "
                    "Restart the VSS service or reboot the system."
                ),
                remediation_steps=[
                    "Restart the VSS service: net stop VSS && net start VSS",
                    "Check Windows Event Logs for VSS errors",
                    "Reboot the system if restarting the service doesn't help"
                ],
                is_retryable=True
            )
        
        elif "not supported" in error_text or "volume" in error_text:
            return VssAdminError(
                error_code=0x80042314,
                error_category="volume",
                error_message="Volume does not support shadow copies",
                technical_details=f"Return code: {returncode}\nStdout: {stdout}\nStderr: {stderr}",
                user_friendly_message=(
                    "Shadow copy creation failed because the volume does not support shadow copies. "
                    "Ensure the volume is NTFS and not a network drive."
                ),
                remediation_steps=[
                    "Verify the volume is formatted as NTFS",
                    "Check that the volume is not a network drive",
                    "Ensure the volume is a local physical or virtual disk"
                ],
                is_retryable=False
            )
        
        elif "timed out" in error_text or returncode == -1:
            return VssAdminError(
                error_code=-1,
                error_category="timeout",
                error_message="Shadow copy creation timed out",
                technical_details=f"Return code: {returncode}\nStdout: {stdout}\nStderr: {stderr}",
                user_friendly_message=(
                    "Shadow copy creation timed out. This may indicate a slow disk or "
                    "system performance issues."
                ),
                remediation_steps=[
                    "Check system performance and disk I/O",
                    "Try again with a longer timeout",
                    "Check for disk errors: chkdsk /f",
                    "Restart the system if performance issues persist"
                ],
                is_retryable=True
            )
        
        else:
            # Unknown error
            return VssAdminError(
                error_code=returncode,
                error_category="unknown",
                error_message="Unknown VSS error occurred",
                technical_details=f"Return code: {returncode}\nStdout: {stdout}\nStderr: {stderr}",
                user_friendly_message=(
                    f"Shadow copy creation failed with an unknown error (code: {returncode}). "
                    "Check the Windows Event Logs for more details."
                ),
                remediation_steps=[
                    "Check Windows Event Logs for VSS-related errors",
                    "Restart the VSS service: net stop VSS && net start VSS",
                    "Verify system integrity: sfc /scannow",
                    "Reboot the system and try again"
                ],
                is_retryable=True
            )
    
    def _generate_remediation_from_checks(self, checks: PreCreationCheckResult) -> List[str]:
        """Generate remediation steps from pre-creation check results.
        
        Args:
            checks: Pre-creation check results
            
        Returns:
            List of actionable remediation steps
        """
        remediation = []
        
        for issue in checks.blocking_issues:
            issue_lower = issue.lower()
            
            if "administrator" in issue_lower or "privileges" in issue_lower:
                remediation.append("Run the program as Administrator")
                remediation.append("Right-click and select 'Run as Administrator'")
            
            elif "vss service" in issue_lower:
                remediation.append("Start the VSS service: net start VSS")
                remediation.append("Or use: sc start VSS")
            
            elif "disk space" in issue_lower or "quota" in issue_lower:
                remediation.append("Free up disk space by deleting unnecessary files")
                remediation.append("Increase VSS quota: vssadmin resize shadowstorage /for=C: /maxsize=10GB")
                remediation.append("Delete old shadow copies: vssadmin delete shadows /for=C: /oldest")
            
            elif "provider" in issue_lower:
                remediation.append("Check VSS providers: vssadmin list providers")
                remediation.append("Restart VSS service: net stop VSS && net start VSS")
                remediation.append("Verify Windows installation: sfc /scannow")
        
        # Add fix results if available
        if checks.auto_fix_results and checks.auto_fix_results.failed_fixes:
            remediation.append("Automatic fixes failed for: " + ", ".join(checks.auto_fix_results.failed_fixes))
        
        # Remove duplicates while preserving order
        seen = set()
        unique_remediation = []
        for step in remediation:
            if step not in seen:
                seen.add(step)
                unique_remediation.append(step)
        
        return unique_remediation
