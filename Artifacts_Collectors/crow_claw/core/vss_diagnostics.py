"""
VSS diagnostic functionality for comprehensive service and system checks.

This module provides diagnostic capabilities for Volume Shadow Copy Service (VSS),
including service status checks, shadow copy enumeration, disk space verification,
and provider/writer status checks.
"""

import logging
import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Optional

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class ServiceStatus:
    """Status information for the VSS service.
    
    Attributes:
        is_running: Whether the VSS service is currently running
        start_type: Service start type ("automatic", "manual", "disabled", "unknown")
        status_message: Human-readable status message
        can_start: Whether the service can be started (not disabled)
        remediation_steps: List of actionable steps to fix service issues
    """
    is_running: bool
    start_type: str
    status_message: str
    can_start: bool
    remediation_steps: List[str]


@dataclass
class ShadowCopy:
    """Represents a VSS shadow copy.
    
    Attributes:
        shadow_copy_id: GUID identifier for the shadow copy
        shadow_copy_volume: Device path to the shadow copy volume
        creation_time: When the shadow copy was created
        original_volume: Original drive letter (e.g., "C:")
    """
    shadow_copy_id: str
    shadow_copy_volume: str
    creation_time: str  # ISO format datetime string
    original_volume: str


@dataclass
class ShadowCopyStatus:
    """Status information for shadow copies on a volume.
    
    Attributes:
        exists: Whether any shadow copies exist
        count: Number of shadow copies found
        shadow_copies: List of ShadowCopy objects
        most_recent: The most recently created shadow copy (if any)
        error_message: Error message if enumeration failed
    """
    exists: bool
    count: int
    shadow_copies: List['ShadowCopy']
    most_recent: Optional['ShadowCopy']
    error_message: Optional[str]


@dataclass
class DiskSpaceStatus:
    """Status information for disk space and VSS shadow storage.
    
    Attributes:
        volume: Drive letter (e.g., "C:")
        total_space_bytes: Total disk space in bytes
        free_space_bytes: Available disk space in bytes
        free_space_percent: Percentage of free space (0-100)
        vss_allocated_bytes: VSS shadow storage allocated space in bytes
        vss_used_bytes: VSS shadow storage used space in bytes
        vss_max_bytes: VSS shadow storage maximum allocation in bytes
        sufficient_for_shadow: Whether there's enough space for shadow copy creation
        remediation_steps: List of actionable steps to free space or adjust quota
    """
    volume: str
    total_space_bytes: int
    free_space_bytes: int
    free_space_percent: float
    vss_allocated_bytes: int
    vss_used_bytes: int
    vss_max_bytes: int
    sufficient_for_shadow: bool
    remediation_steps: List[str]


@dataclass
class ProviderStatus:
    """Status information for VSS providers.
    
    Attributes:
        providers_available: Whether any VSS providers are available
        provider_count: Number of VSS providers found
        provider_names: List of provider names/IDs
        error_message: Error message if provider enumeration failed
    """
    providers_available: bool
    provider_count: int
    provider_names: List[str]
    error_message: Optional[str]


@dataclass
class WriterStatus:
    """Status information for VSS writers.
    
    Attributes:
        all_stable: Whether all VSS writers are in a stable state
        writer_count: Number of VSS writers found
        failed_writers: List of failed writers with name, state, and error info
        remediation_steps: List of actionable steps to fix failed writers
    """
    all_stable: bool
    writer_count: int
    failed_writers: List[dict]  # Each dict has 'name', 'state', 'error_code'
    remediation_steps: List[str]


@dataclass
class PolicyStatus:
    """Status information for system policies and security restrictions.
    
    Attributes:
        vss_restricted: Whether VSS operations appear to be restricted
        restrictions_found: List of detected restrictions or policies
        bitlocker_active: Whether BitLocker encryption is active on the volume
        remediation_steps: List of actionable steps to address restrictions
    """
    vss_restricted: bool
    restrictions_found: List[str]
    bitlocker_active: bool
    remediation_steps: List[str]


@dataclass
class EventLogEntry:
    """Represents a Windows Event Log entry related to VSS.
    
    Attributes:
        timestamp: When the event occurred
        event_id: Windows Event ID
        level: Event level (Error, Warning, Information)
        source: Event source (e.g., "VSS", "VolSnap")
        message: Event message text
    """
    timestamp: str
    event_id: int
    level: str
    source: str
    message: str


@dataclass
class DiagnosticReport:
    """Comprehensive diagnostic report aggregating all VSS checks.
    
    Attributes:
        timestamp: When the diagnostic report was generated
        is_admin: Whether the current process has administrator privileges
        service_status: VSS service status information
        shadow_copy_status: Shadow copy enumeration results
        disk_space_status: Disk space and VSS quota information
        provider_status: VSS provider availability
        writer_status: VSS writer status
        policy_status: System policy and security restrictions
        event_log_errors: Recent VSS-related event log errors
        overall_health: Overall system health ("healthy", "degraded", "failed")
        can_create_shadow: Whether shadow copy creation is likely to succeed
        blocking_issues: List of critical issues preventing shadow copy creation
        remediation_summary: Consolidated list of remediation steps
    """
    timestamp: str  # ISO format datetime string
    is_admin: bool
    service_status: 'ServiceStatus'
    shadow_copy_status: 'ShadowCopyStatus'
    disk_space_status: 'DiskSpaceStatus'
    provider_status: 'ProviderStatus'
    writer_status: 'WriterStatus'
    policy_status: 'PolicyStatus'
    event_log_errors: List['EventLogEntry']
    overall_health: str
    can_create_shadow: bool
    blocking_issues: List[str]
    remediation_summary: List[str]



    @dataclass
    class DiagnosticReport:
        """Comprehensive diagnostic report aggregating all VSS checks.

        Attributes:
            timestamp: When the diagnostic report was generated
            is_admin: Whether the current process has administrator privileges
            service_status: VSS service status information
            shadow_copy_status: Shadow copy enumeration results
            disk_space_status: Disk space and VSS quota information
            provider_status: VSS provider availability
            writer_status: VSS writer status
            policy_status: System policy and security restrictions
            event_log_errors: Recent VSS-related event log errors
            overall_health: Overall system health ("healthy", "degraded", "failed")
            can_create_shadow: Whether shadow copy creation is likely to succeed
            blocking_issues: List of critical issues preventing shadow copy creation
            remediation_summary: Consolidated list of remediation steps
        """
        timestamp: str  # ISO format datetime string
        is_admin: bool
        service_status: 'ServiceStatus'
        shadow_copy_status: 'ShadowCopyStatus'
        disk_space_status: 'DiskSpaceStatus'
        provider_status: 'ProviderStatus'
        writer_status: 'WriterStatus'
        policy_status: 'PolicyStatus'
        event_log_errors: List['EventLogEntry']
        overall_health: str
        can_create_shadow: bool
        blocking_issues: List[str]
        remediation_summary: List[str]



class VSSDiagnostics:
    """Comprehensive VSS diagnostic capabilities.
    
    This class provides methods to diagnose VSS-related issues including
    service status, shadow copy availability, disk space, and system configuration.
    
    Requirements:
        - 1.1: Check if VSS service is running
        - 1.2: Report service status and provide remediation steps
        - 1.3: Use both win32serviceutil and subprocess fallback methods
        - 1.4: Log specific errors encountered
        - 1.5: Verify VSS service configuration (start type, dependencies)
    """
    
    def __init__(self):
        """Initialize the VSS diagnostics system."""
        logger.info("[VSSDiagnostics] Initializing VSS diagnostics")
    
    def check_vss_service_status(self) -> ServiceStatus:
        """Check if VSS service is running and properly configured.
        
        This method attempts to check the VSS service status using two methods:
        1. win32serviceutil (preferred, more detailed information)
        2. subprocess with 'sc query' command (fallback)
        
        Returns:
            ServiceStatus object containing service state and remediation steps
            
        Requirements:
            - 1.1: Check if VSS service is running
            - 1.2: Report service status and provide remediation steps
            - 1.3: Use both win32serviceutil and subprocess fallback methods
            - 1.4: Log specific errors encountered
            - 1.5: Verify VSS service configuration
        """
        logger.info("[VSSDiagnostics] Checking VSS service status")
        
        # Try win32serviceutil first (preferred method)
        try:
            import win32serviceutil
            import win32service
            
            logger.debug("[VSSDiagnostics] Using win32serviceutil to check VSS service")
            
            try:
                # Query the VSS service status
                # Service name is "VSS" (Volume Shadow Copy)
                status = win32serviceutil.QueryServiceStatus("VSS")
                
                # status is a tuple: (scvType, svcState, svcControls, err, svcErr, svcCP, svcWH)
                # We care about svcState (index 1)
                service_state = status[1]
                
                is_running = (service_state == win32service.SERVICE_RUNNING)
                
                # Get start type
                try:
                    # Open service to query configuration
                    import win32con
                    hscm = win32service.OpenSCManager(None, None, win32con.GENERIC_READ)
                    hs = win32service.OpenService(hscm, "VSS", win32con.GENERIC_READ)
                    config = win32service.QueryServiceConfig(hs)
                    win32service.CloseServiceHandle(hs)
                    win32service.CloseServiceHandle(hscm)
                    
                    # config[1] is the start type
                    start_type_code = config[1]
                    start_type_map = {
                        win32service.SERVICE_AUTO_START: "automatic",
                        win32service.SERVICE_DEMAND_START: "manual",
                        win32service.SERVICE_DISABLED: "disabled",
                        win32service.SERVICE_BOOT_START: "boot",
                        win32service.SERVICE_SYSTEM_START: "system"
                    }
                    start_type = start_type_map.get(start_type_code, "unknown")
                    
                except Exception as config_error:
                    logger.warning(f"[VSSDiagnostics] Could not query service configuration: {config_error}")
                    start_type = "unknown"
                
                # Determine if service can be started
                can_start = (start_type != "disabled")
                
                # Build status message
                state_names = {
                    win32service.SERVICE_STOPPED: "stopped",
                    win32service.SERVICE_START_PENDING: "starting",
                    win32service.SERVICE_STOP_PENDING: "stopping",
                    win32service.SERVICE_RUNNING: "running",
                    win32service.SERVICE_CONTINUE_PENDING: "resuming",
                    win32service.SERVICE_PAUSE_PENDING: "pausing",
                    win32service.SERVICE_PAUSED: "paused"
                }
                state_name = state_names.get(service_state, f"unknown state ({service_state})")
                
                status_message = f"VSS service is {state_name} (start type: {start_type})"
                
                # Build remediation steps
                remediation_steps = []
                if not is_running:
                    if start_type == "disabled":
                        remediation_steps.append("Enable the VSS service: sc config VSS start=demand")
                        remediation_steps.append("Start the VSS service: net start VSS")
                    elif can_start:
                        remediation_steps.append("Start the VSS service: net start VSS")
                        remediation_steps.append("Or use: sc start VSS")
                    else:
                        remediation_steps.append("Check Windows Event Logs for VSS service errors")
                        remediation_steps.append("Restart the system if VSS service cannot be started")
                
                logger.info(f"[VSSDiagnostics] VSS service status (win32): {status_message}")
                
                return ServiceStatus(
                    is_running=is_running,
                    start_type=start_type,
                    status_message=status_message,
                    can_start=can_start,
                    remediation_steps=remediation_steps
                )
                
            except Exception as query_error:
                logger.error(f"[VSSDiagnostics] win32serviceutil query failed: {query_error}")
                # Fall through to subprocess fallback
                
        except ImportError:
            logger.debug("[VSSDiagnostics] win32serviceutil not available, using subprocess fallback")
        except Exception as e:
            logger.warning(f"[VSSDiagnostics] win32serviceutil method failed: {e}")
        
        # Fallback to subprocess method
        logger.debug("[VSSDiagnostics] Using subprocess (sc query) to check VSS service")
        
        try:
            result = subprocess.run(
                ["sc", "query", "VSS"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            logger.debug(f"[VSSDiagnostics] sc query return code: {result.returncode}")
            logger.debug(f"[VSSDiagnostics] sc query stdout: {result.stdout}")
            
            if result.returncode == 0:
                output = result.stdout
                
                # Check if service is running
                is_running = "RUNNING" in output
                
                # Try to determine start type by querying config
                start_type = "unknown"
                try:
                    config_result = subprocess.run(
                        ["sc", "qc", "VSS"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    
                    if config_result.returncode == 0:
                        config_output = config_result.stdout
                        if "AUTO_START" in config_output:
                            start_type = "automatic"
                        elif "DEMAND_START" in config_output:
                            start_type = "manual"
                        elif "DISABLED" in config_output:
                            start_type = "disabled"
                        
                        logger.debug(f"[VSSDiagnostics] sc qc output: {config_output}")
                        
                except Exception as config_error:
                    logger.warning(f"[VSSDiagnostics] Could not query service config via sc: {config_error}")
                
                # Determine if service can be started
                can_start = (start_type != "disabled")
                
                # Build status message
                if is_running:
                    status_message = f"VSS service is running (start type: {start_type})"
                else:
                    if "STOPPED" in output:
                        status_message = f"VSS service is stopped (start type: {start_type})"
                    else:
                        status_message = f"VSS service status unknown (start type: {start_type})"
                
                # Build remediation steps
                remediation_steps = []
                if not is_running:
                    if start_type == "disabled":
                        remediation_steps.append("Enable the VSS service: sc config VSS start=demand")
                        remediation_steps.append("Start the VSS service: net start VSS")
                    elif can_start:
                        remediation_steps.append("Start the VSS service: net start VSS")
                        remediation_steps.append("Or use: sc start VSS")
                    else:
                        remediation_steps.append("Check Windows Event Logs for VSS service errors")
                        remediation_steps.append("Restart the system if VSS service cannot be started")
                
                logger.info(f"[VSSDiagnostics] VSS service status (subprocess): {status_message}")
                
                return ServiceStatus(
                    is_running=is_running,
                    start_type=start_type,
                    status_message=status_message,
                    can_start=can_start,
                    remediation_steps=remediation_steps
                )
            else:
                # Service query failed
                logger.error(f"[VSSDiagnostics] sc query failed with return code {result.returncode}")
                logger.error(f"[VSSDiagnostics] stderr: {result.stderr}")
                
                return ServiceStatus(
                    is_running=False,
                    start_type="unknown",
                    status_message=f"Failed to query VSS service (error code: {result.returncode})",
                    can_start=False,
                    remediation_steps=[
                        "Verify VSS service exists: sc query VSS",
                        "Check if running as Administrator",
                        "Restart the system and try again"
                    ]
                )
                
        except subprocess.TimeoutExpired:
            logger.error("[VSSDiagnostics] sc query command timed out")
            return ServiceStatus(
                is_running=False,
                start_type="unknown",
                status_message="VSS service query timed out",
                can_start=False,
                remediation_steps=[
                    "System may be unresponsive",
                    "Check system performance and resource usage",
                    "Restart the system if necessary"
                ]
            )
            
        except FileNotFoundError:
            logger.error("[VSSDiagnostics] sc command not found")
            return ServiceStatus(
                is_running=False,
                start_type="unknown",
                status_message="Service control command (sc.exe) not found",
                can_start=False,
                remediation_steps=[
                    "Verify Windows system files are intact",
                    "Run system file checker: sfc /scannow",
                    "Reinstall Windows if system files are corrupted"
                ]
            )
            
        except Exception as e:
            logger.error(f"[VSSDiagnostics] Unexpected error checking VSS service: {e}")
            import traceback
            logger.debug(f"[VSSDiagnostics] Traceback: {traceback.format_exc()}")
            
            return ServiceStatus(
                is_running=False,
                start_type="unknown",
                status_message=f"Unexpected error checking VSS service: {str(e)}",
                can_start=False,
                remediation_steps=[
                    "Check Windows Event Logs for system errors",
                    "Verify system integrity: sfc /scannow",
                    "Restart the system and try again"
                ]
            )
    
    def check_shadow_copies(self, volume: str = "C:") -> ShadowCopyStatus:
        """Check if shadow copies exist for the specified volume.
        
        This method executes 'vssadmin list shadows' and parses the output
        to identify shadow copies for the specified volume. It handles various
        Windows versions and locales by using flexible parsing.
        
        Args:
            volume: Drive letter to check (e.g., "C:" or "C")
            
        Returns:
            ShadowCopyStatus object containing shadow copy information
            
        Requirements:
            - 2.1: Execute vssadmin list shadows and capture output
            - 2.2: Log return code, stdout, and stderr on failure
            - 2.3: Report clearly when no shadow copies exist
            - 2.4: Report count, creation times, and volumes when shadow copies exist
            - 2.5: Parse shadow copy output for all supported Windows versions and locales
        """
        # Normalize volume format (ensure it ends with :)
        if not volume.endswith(":"):
            volume = volume + ":"
        
        logger.info(f"[VSSDiagnostics] Checking shadow copies for volume {volume}")
        
        try:
            # Execute vssadmin list shadows
            result = subprocess.run(
                ["vssadmin", "list", "shadows"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            logger.debug(f"[VSSDiagnostics] vssadmin list shadows return code: {result.returncode}")
            logger.debug(f"[VSSDiagnostics] vssadmin list shadows stdout length: {len(result.stdout)}")
            
            if result.returncode != 0:
                # Command failed
                logger.error(f"[VSSDiagnostics] vssadmin list shadows failed with return code {result.returncode}")
                logger.error(f"[VSSDiagnostics] stderr: {result.stderr}")
                
                return ShadowCopyStatus(
                    exists=False,
                    count=0,
                    shadow_copies=[],
                    most_recent=None,
                    error_message=f"Failed to enumerate shadow copies (error code: {result.returncode}): {result.stderr}"
                )
            
            # Parse the output
            output = result.stdout
            shadow_copies = []
            
            # Split output into shadow copy blocks
            # Each shadow copy starts with "Shadow Copy ID:" or similar
            # We'll use a flexible approach that works across locales
            
            lines = output.split('\n')
            current_shadow = {}
            
            for line in lines:
                line = line.strip()
                
                if not line:
                    # Empty line might indicate end of a shadow copy block
                    if current_shadow and 'shadow_copy_id' in current_shadow:
                        # Check if this shadow copy is for our volume
                        if 'original_volume' in current_shadow:
                            orig_vol = current_shadow['original_volume']
                            # Normalize for comparison
                            if not orig_vol.endswith(":"):
                                orig_vol = orig_vol + ":"
                            
                            if orig_vol.upper() == volume.upper():
                                shadow_copies.append(ShadowCopy(
                                    shadow_copy_id=current_shadow['shadow_copy_id'],
                                    shadow_copy_volume=current_shadow.get('shadow_copy_volume', ''),
                                    creation_time=current_shadow.get('creation_time', ''),
                                    original_volume=current_shadow['original_volume']
                                ))
                        
                        current_shadow = {}
                    continue
                
                # Parse key-value pairs
                # Format is typically "Key: Value" or "Key : Value"
                if ':' in line:
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        key = parts[0].strip().lower()
                        value = parts[1].strip()
                        
                        # Map various possible key names to our standard names
                        # This handles different Windows versions and locales
                        if 'shadow copy id' in key or 'shadow id' in key:
                            current_shadow['shadow_copy_id'] = value
                        elif 'shadow copy volume' in key or 'shadow volume name' in key:
                            current_shadow['shadow_copy_volume'] = value
                        elif 'creation time' in key or 'created' in key:
                            current_shadow['creation_time'] = value
                        elif 'original volume' in key or 'original machine' in key:
                            # Sometimes the original volume is listed as "Original Volume: (C:)\\?\Volume{...}"
                            # We want to extract just the drive letter
                            if '(' in value and ')' in value:
                                # Extract drive letter from parentheses
                                start = value.index('(') + 1
                                end = value.index(')')
                                drive = value[start:end].strip()
                                current_shadow['original_volume'] = drive
                            else:
                                # Try to extract drive letter from the value
                                # Look for patterns like "C:" or "\\?\Volume{...}\C:"
                                import re
                                match = re.search(r'([A-Z]:)', value.upper())
                                if match:
                                    current_shadow['original_volume'] = match.group(1)
                                else:
                                    current_shadow['original_volume'] = value
            
            # Don't forget the last shadow copy if file doesn't end with empty line
            if current_shadow and 'shadow_copy_id' in current_shadow:
                if 'original_volume' in current_shadow:
                    orig_vol = current_shadow['original_volume']
                    if not orig_vol.endswith(":"):
                        orig_vol = orig_vol + ":"
                    
                    if orig_vol.upper() == volume.upper():
                        shadow_copies.append(ShadowCopy(
                            shadow_copy_id=current_shadow['shadow_copy_id'],
                            shadow_copy_volume=current_shadow.get('shadow_copy_volume', ''),
                            creation_time=current_shadow.get('creation_time', ''),
                            original_volume=current_shadow['original_volume']
                        ))
            
            # Determine most recent shadow copy
            most_recent = None
            if shadow_copies:
                # The most recent is typically the last one in the list
                # but we could also parse creation times if needed
                most_recent = shadow_copies[-1]
            
            count = len(shadow_copies)
            exists = count > 0
            
            if exists:
                logger.info(f"[VSSDiagnostics] Found {count} shadow copy(ies) for volume {volume}")
                for sc in shadow_copies:
                    logger.debug(f"[VSSDiagnostics]   - ID: {sc.shadow_copy_id}, Created: {sc.creation_time}")
            else:
                logger.info(f"[VSSDiagnostics] No shadow copies found for volume {volume}")
            
            return ShadowCopyStatus(
                exists=exists,
                count=count,
                shadow_copies=shadow_copies,
                most_recent=most_recent,
                error_message=None
            )
            
        except subprocess.TimeoutExpired:
            logger.error("[VSSDiagnostics] vssadmin list shadows command timed out")
            return ShadowCopyStatus(
                exists=False,
                count=0,
                shadow_copies=[],
                most_recent=None,
                error_message="Shadow copy enumeration timed out (command took longer than 30 seconds)"
            )
            
        except FileNotFoundError:
            logger.error("[VSSDiagnostics] vssadmin command not found")
            return ShadowCopyStatus(
                exists=False,
                count=0,
                shadow_copies=[],
                most_recent=None,
                error_message="vssadmin command not found - VSS may not be installed or available"
            )
            
        except Exception as e:
            logger.error(f"[VSSDiagnostics] Unexpected error enumerating shadow copies: {e}")
            import traceback
            logger.debug(f"[VSSDiagnostics] Traceback: {traceback.format_exc()}")
            
            return ShadowCopyStatus(
                exists=False,
                count=0,
                shadow_copies=[],
                most_recent=None,
                error_message=f"Unexpected error enumerating shadow copies: {str(e)}"
            )
    
    def check_disk_space(self, volume: str = "C:") -> DiskSpaceStatus:
        """Check available disk space and VSS shadow storage allocation.
        
        This method queries:
        1. Available disk space on the target volume using shutil.disk_usage
        2. VSS shadow storage allocation using 'vssadmin list shadowstorage'
        
        Args:
            volume: Drive letter to check (e.g., "C:" or "C")
            
        Returns:
            DiskSpaceStatus object containing disk space and VSS quota information
            
        Requirements:
            - 4.1: Query available disk space on the target volume
            - 4.2: Query VSS shadow storage allocation using vssadmin list shadowstorage
            - 4.3: Report when VSS shadow storage is full or quota is exceeded
            - 4.4: Report available space and estimated requirement
            - 4.5: Provide commands to increase VSS quota or free disk space
        """
        # Normalize volume format (ensure it ends with :)
        if not volume.endswith(":"):
            volume = volume + ":"
        
        logger.info(f"[VSSDiagnostics] Checking disk space and VSS quota for volume {volume}")
        
        # Initialize with default values
        total_space_bytes = 0
        free_space_bytes = 0
        free_space_percent = 0.0
        vss_allocated_bytes = 0
        vss_used_bytes = 0
        vss_max_bytes = 0
        remediation_steps = []
        
        # Step 1: Query disk space using shutil
        try:
            # shutil.disk_usage requires a path, use volume root
            volume_path = volume + "\\"
            usage = shutil.disk_usage(volume_path)
            
            total_space_bytes = usage.total
            free_space_bytes = usage.free
            free_space_percent = (free_space_bytes / total_space_bytes * 100) if total_space_bytes > 0 else 0.0
            
            logger.info(f"[VSSDiagnostics] Disk space on {volume}: {free_space_bytes / (1024**3):.2f} GB free of {total_space_bytes / (1024**3):.2f} GB ({free_space_percent:.1f}%)")
            
        except Exception as e:
            logger.error(f"[VSSDiagnostics] Failed to query disk space: {e}")
            remediation_steps.append(f"Could not query disk space for {volume}: {str(e)}")
        
        # Step 2: Query VSS shadow storage allocation
        try:
            result = subprocess.run(
                ["vssadmin", "list", "shadowstorage"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            logger.debug(f"[VSSDiagnostics] vssadmin list shadowstorage return code: {result.returncode}")
            
            if result.returncode == 0:
                output = result.stdout
                logger.debug(f"[VSSDiagnostics] vssadmin list shadowstorage output length: {len(output)}")
                
                # Parse the output to find shadow storage info for our volume
                # Output format varies by locale, but typically contains:
                # "For volume: (C:)\\?\Volume{...}"
                # "Shadow Copy Storage volume: ..."
                # "Used Shadow Copy Storage space: X.XX GB"
                # "Allocated Shadow Copy Storage space: X.XX GB"
                # "Maximum Shadow Copy Storage space: X.XX GB (UNBOUNDED)" or specific value
                
                lines = output.split('\n')
                in_target_volume_section = False
                
                for i, line in enumerate(lines):
                    line_stripped = line.strip()
                    
                    # Check if this line indicates the start of our volume's section
                    if 'for volume' in line_stripped.lower():
                        # Extract volume letter from line
                        if f"({volume})" in line_stripped or f"({volume[0]}:)" in line_stripped:
                            in_target_volume_section = True
                            logger.debug(f"[VSSDiagnostics] Found shadow storage section for {volume}")
                        else:
                            in_target_volume_section = False
                        continue
                    
                    # If we're in the target volume section, parse the values
                    if in_target_volume_section and ':' in line_stripped:
                        key_value = line_stripped.split(':', 1)
                        if len(key_value) == 2:
                            key = key_value[0].strip().lower()
                            value = key_value[1].strip()
                            
                            # Parse storage values
                            # Values can be in formats like "1.23 GB", "512 MB", "UNBOUNDED"
                            if 'used' in key and 'space' in key:
                                vss_used_bytes = self._parse_storage_size(value)
                                logger.debug(f"[VSSDiagnostics] VSS used space: {vss_used_bytes / (1024**3):.2f} GB")
                            
                            elif 'allocated' in key and 'space' in key:
                                vss_allocated_bytes = self._parse_storage_size(value)
                                logger.debug(f"[VSSDiagnostics] VSS allocated space: {vss_allocated_bytes / (1024**3):.2f} GB")
                            
                            elif 'maximum' in key and 'space' in key:
                                # Maximum can be "UNBOUNDED" or a specific size
                                if 'unbounded' in value.lower():
                                    # Use total disk space as the theoretical maximum
                                    vss_max_bytes = total_space_bytes
                                    logger.debug(f"[VSSDiagnostics] VSS maximum space: UNBOUNDED")
                                else:
                                    vss_max_bytes = self._parse_storage_size(value)
                                    logger.debug(f"[VSSDiagnostics] VSS maximum space: {vss_max_bytes / (1024**3):.2f} GB")
                    
                    # Check if we've moved to a different volume section
                    if in_target_volume_section and line_stripped == '':
                        # Empty line might indicate end of section
                        # But we'll keep parsing in case there are multiple empty lines
                        pass
                
                logger.info(f"[VSSDiagnostics] VSS shadow storage: {vss_used_bytes / (1024**3):.2f} GB used, {vss_allocated_bytes / (1024**3):.2f} GB allocated, {vss_max_bytes / (1024**3):.2f} GB max")
                
            else:
                logger.warning(f"[VSSDiagnostics] vssadmin list shadowstorage failed with return code {result.returncode}")
                logger.warning(f"[VSSDiagnostics] stderr: {result.stderr}")
                remediation_steps.append(f"Could not query VSS shadow storage: {result.stderr}")
        
        except subprocess.TimeoutExpired:
            logger.error("[VSSDiagnostics] vssadmin list shadowstorage command timed out")
            remediation_steps.append("VSS shadow storage query timed out")
        
        except FileNotFoundError:
            logger.error("[VSSDiagnostics] vssadmin command not found")
            remediation_steps.append("vssadmin command not found - VSS may not be installed")
        
        except Exception as e:
            logger.error(f"[VSSDiagnostics] Unexpected error querying VSS shadow storage: {e}")
            remediation_steps.append(f"Unexpected error querying VSS shadow storage: {str(e)}")
        
        # Step 3: Determine if there's sufficient space for shadow copy creation
        # Rule of thumb: Need at least 300 MB free disk space and VSS quota not exceeded
        MIN_FREE_SPACE_BYTES = 300 * 1024 * 1024  # 300 MB
        MIN_FREE_SPACE_PERCENT = 5.0  # 5%
        
        sufficient_for_shadow = True
        
        # Check free disk space
        if free_space_bytes < MIN_FREE_SPACE_BYTES:
            sufficient_for_shadow = False
            remediation_steps.append(f"Insufficient disk space: {free_space_bytes / (1024**3):.2f} GB free (need at least 0.3 GB)")
            remediation_steps.append(f"Free up disk space on {volume} by deleting unnecessary files")
            remediation_steps.append("Run Disk Cleanup: cleanmgr.exe")
        
        if free_space_percent < MIN_FREE_SPACE_PERCENT:
            sufficient_for_shadow = False
            if f"Insufficient disk space" not in str(remediation_steps):
                remediation_steps.append(f"Low disk space: {free_space_percent:.1f}% free (recommend at least 5%)")
        
        # Check VSS quota
        if vss_max_bytes > 0 and vss_used_bytes >= vss_max_bytes:
            sufficient_for_shadow = False
            remediation_steps.append(f"VSS shadow storage quota exceeded: {vss_used_bytes / (1024**3):.2f} GB used of {vss_max_bytes / (1024**3):.2f} GB maximum")
            remediation_steps.append(f"Delete old shadow copies: vssadmin delete shadows /for={volume} /oldest")
            remediation_steps.append(f"Or increase VSS quota: vssadmin resize shadowstorage /for={volume} /maxsize=10GB")
        
        elif vss_max_bytes > 0 and vss_allocated_bytes > 0:
            # Check if we're close to the quota (within 10%)
            usage_percent = (vss_used_bytes / vss_max_bytes * 100) if vss_max_bytes > 0 else 0
            if usage_percent > 90:
                remediation_steps.append(f"VSS shadow storage nearly full: {usage_percent:.1f}% used")
                remediation_steps.append(f"Consider deleting old shadow copies: vssadmin delete shadows /for={volume} /oldest")
        
        # If no issues found, add a positive message
        if sufficient_for_shadow and not remediation_steps:
            remediation_steps.append("Disk space and VSS quota are sufficient for shadow copy creation")
        
        logger.info(f"[VSSDiagnostics] Sufficient space for shadow copy: {sufficient_for_shadow}")
        
        return DiskSpaceStatus(
            volume=volume,
            total_space_bytes=total_space_bytes,
            free_space_bytes=free_space_bytes,
            free_space_percent=free_space_percent,
            vss_allocated_bytes=vss_allocated_bytes,
            vss_used_bytes=vss_used_bytes,
            vss_max_bytes=vss_max_bytes,
            sufficient_for_shadow=sufficient_for_shadow,
            remediation_steps=remediation_steps
        )
    
    def _parse_storage_size(self, size_str: str) -> int:
        """Parse a storage size string (e.g., '1.23 GB', '512 MB') to bytes.
        
        Args:
            size_str: Size string from vssadmin output
            
        Returns:
            Size in bytes, or 0 if parsing fails
        """
        try:
            size_str = size_str.strip().upper()
            
            # Remove any parenthetical notes like "(UNBOUNDED)"
            if '(' in size_str:
                size_str = size_str.split('(')[0].strip()
            
            # Check for UNBOUNDED
            if 'UNBOUNDED' in size_str:
                return 0
            
            # Parse number and unit
            import re
            match = re.match(r'([\d.,]+)\s*([KMGT]?B)', size_str)
            
            if match:
                # Replace comma with dot for decimal parsing (handles different locales)
                number_str = match.group(1).replace(',', '.')
                number = float(number_str)
                unit = match.group(2)
                
                # Convert to bytes
                multipliers = {
                    'B': 1,
                    'KB': 1024,
                    'MB': 1024 ** 2,
                    'GB': 1024 ** 3,
                    'TB': 1024 ** 4
                }
                
                multiplier = multipliers.get(unit, 1)
                return int(number * multiplier)
            
            return 0
            
        except Exception as e:
            logger.debug(f"[VSSDiagnostics] Failed to parse storage size '{size_str}': {e}")
            return 0
    
    def check_vss_providers(self) -> ProviderStatus:
        """Check VSS provider availability and status.
        
        This method executes 'vssadmin list providers' and parses the output
        to identify available VSS providers on the system.
        
        Returns:
            ProviderStatus object containing provider information
            
        Requirements:
            - 5.1: Execute vssadmin list providers and report results
            - 5.4: Report when no VSS providers are available
        """
        logger.info("[VSSDiagnostics] Checking VSS providers")
        
        try:
            # Execute vssadmin list providers
            result = subprocess.run(
                ["vssadmin", "list", "providers"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            logger.debug(f"[VSSDiagnostics] vssadmin list providers return code: {result.returncode}")
            logger.debug(f"[VSSDiagnostics] vssadmin list providers stdout length: {len(result.stdout)}")
            
            if result.returncode != 0:
                # Command failed
                logger.error(f"[VSSDiagnostics] vssadmin list providers failed with return code {result.returncode}")
                logger.error(f"[VSSDiagnostics] stderr: {result.stderr}")
                
                return ProviderStatus(
                    providers_available=False,
                    provider_count=0,
                    provider_names=[],
                    error_message=f"Failed to enumerate VSS providers (error code: {result.returncode}): {result.stderr}"
                )
            
            # Parse the output
            output = result.stdout
            provider_names = []
            
            # Split output into lines and look for provider information
            # Typical format:
            # Provider name: 'Microsoft Software Shadow Copy provider 1.0'
            # Provider type: System
            # Provider Id: {b5946137-7b9f-4925-af80-51abd60b20d5}
            # Version: 1.0.0.7
            
            lines = output.split('\n')
            current_provider_name = None
            
            for line in lines:
                line = line.strip()
                
                if not line:
                    # Empty line might indicate end of a provider block
                    if current_provider_name:
                        provider_names.append(current_provider_name)
                        current_provider_name = None
                    continue
                
                # Parse key-value pairs
                if ':' in line:
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        key = parts[0].strip().lower()
                        value = parts[1].strip()
                        
                        # Look for provider name
                        if 'provider name' in key:
                            # Remove quotes if present
                            current_provider_name = value.strip("'\"")
                        elif 'provider id' in key and current_provider_name:
                            # We have both name and ID, add to list
                            provider_names.append(current_provider_name)
                            current_provider_name = None
            
            # Don't forget the last provider if file doesn't end with empty line
            if current_provider_name:
                provider_names.append(current_provider_name)
            
            provider_count = len(provider_names)
            providers_available = provider_count > 0
            
            if providers_available:
                logger.info(f"[VSSDiagnostics] Found {provider_count} VSS provider(s)")
                for provider in provider_names:
                    logger.debug(f"[VSSDiagnostics]   - {provider}")
            else:
                logger.warning("[VSSDiagnostics] No VSS providers found - this is a critical issue")
            
            return ProviderStatus(
                providers_available=providers_available,
                provider_count=provider_count,
                provider_names=provider_names,
                error_message=None
            )
            
        except subprocess.TimeoutExpired:
            logger.error("[VSSDiagnostics] vssadmin list providers command timed out")
            return ProviderStatus(
                providers_available=False,
                provider_count=0,
                provider_names=[],
                error_message="VSS provider enumeration timed out (command took longer than 30 seconds)"
            )
            
        except FileNotFoundError:
            logger.error("[VSSDiagnostics] vssadmin command not found")
            return ProviderStatus(
                providers_available=False,
                provider_count=0,
                provider_names=[],
                error_message="vssadmin command not found - VSS may not be installed or available"
            )
            
        except Exception as e:
            logger.error(f"[VSSDiagnostics] Unexpected error enumerating VSS providers: {e}")
            import traceback
            logger.debug(f"[VSSDiagnostics] Traceback: {traceback.format_exc()}")
            
            return ProviderStatus(
                providers_available=False,
                provider_count=0,
                provider_names=[],
                error_message=f"Unexpected error enumerating VSS providers: {str(e)}"
            )
    
    def check_vss_writers(self) -> WriterStatus:
        """Check VSS writer status and identify failed writers.
        
        This method executes 'vssadmin list writers' and parses the output
        to identify writer status. Failed writers can prevent shadow copy creation.
        
        Returns:
            WriterStatus object containing writer status and remediation steps
            
        Requirements:
            - 5.2: Execute vssadmin list writers and report writer status
            - 5.3: Report which writers failed and their error codes
            - 5.5: Provide remediation steps for failed VSS writers
        """
        logger.info("[VSSDiagnostics] Checking VSS writers")
        
        try:
            # Execute vssadmin list writers
            result = subprocess.run(
                ["vssadmin", "list", "writers"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            logger.debug(f"[VSSDiagnostics] vssadmin list writers return code: {result.returncode}")
            logger.debug(f"[VSSDiagnostics] vssadmin list writers stdout length: {len(result.stdout)}")
            
            if result.returncode != 0:
                # Command failed
                logger.error(f"[VSSDiagnostics] vssadmin list writers failed with return code {result.returncode}")
                logger.error(f"[VSSDiagnostics] stderr: {result.stderr}")
                
                return WriterStatus(
                    all_stable=False,
                    writer_count=0,
                    failed_writers=[],
                    remediation_steps=[
                        f"Failed to enumerate VSS writers (error code: {result.returncode})",
                        "Verify you are running as Administrator",
                        "Check Windows Event Logs for VSS errors"
                    ]
                )
            
            # Parse the output
            output = result.stdout
            writers = []
            failed_writers = []
            
            # Split output into lines and look for writer information
            # Typical format:
            # Writer name: 'Task Scheduler Writer'
            # Writer Id: {d61d61c8-d73a-4eee-8cdd-f6f9786b7124}
            # Writer Instance Id: {1234-5678-...}
            # State: [1] Stable
            # Last error: No error
            
            lines = output.split('\n')
            current_writer = {}
            
            for line in lines:
                line = line.strip()
                
                if not line:
                    # Empty line might indicate end of a writer block
                    if current_writer and 'name' in current_writer:
                        writers.append(current_writer)
                        
                        # Check if writer is in a failed state
                        state = current_writer.get('state', '').lower()
                        last_error = current_writer.get('last_error', '').lower()
                        
                        # Failed states include anything other than "stable"
                        # Common failed states: "Failed", "Unknown", "Waiting for completion"
                        is_failed = ('stable' not in state) or ('no error' not in last_error and last_error != '')
                        
                        if is_failed:
                            failed_writers.append({
                                'name': current_writer.get('name', 'Unknown'),
                                'state': current_writer.get('state', 'Unknown'),
                                'error_code': current_writer.get('last_error', 'Unknown error')
                            })
                        
                        current_writer = {}
                    continue
                
                # Parse key-value pairs
                if ':' in line:
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        key = parts[0].strip().lower()
                        value = parts[1].strip()
                        
                        # Look for writer information
                        if 'writer name' in key:
                            # Remove quotes if present
                            current_writer['name'] = value.strip("'\"")
                        elif 'state' in key and 'instance' not in key:
                            # State line format: "[1] Stable" or "[5] Failed"
                            current_writer['state'] = value
                        elif 'last error' in key:
                            current_writer['last_error'] = value
            
            # Don't forget the last writer if file doesn't end with empty line
            if current_writer and 'name' in current_writer:
                writers.append(current_writer)
                
                state = current_writer.get('state', '').lower()
                last_error = current_writer.get('last_error', '').lower()
                is_failed = ('stable' not in state) or ('no error' not in last_error and last_error != '')
                
                if is_failed:
                    failed_writers.append({
                        'name': current_writer.get('name', 'Unknown'),
                        'state': current_writer.get('state', 'Unknown'),
                        'error_code': current_writer.get('last_error', 'Unknown error')
                    })
            
            writer_count = len(writers)
            all_stable = len(failed_writers) == 0
            
            # Build remediation steps
            remediation_steps = []
            
            if not all_stable:
                logger.warning(f"[VSSDiagnostics] Found {len(failed_writers)} failed VSS writer(s)")
                for writer in failed_writers:
                    logger.warning(f"[VSSDiagnostics]   - {writer['name']}: {writer['state']} ({writer['error_code']})")
                
                remediation_steps.append(f"Found {len(failed_writers)} failed VSS writer(s)")
                remediation_steps.append("Restart the VSS service: net stop vss && net start vss")
                remediation_steps.append("Restart related services for failed writers")
                remediation_steps.append("If issue persists, reboot the system")
                remediation_steps.append("Check Windows Event Logs for writer-specific errors")
                
                # Add specific remediation for common failed writers
                for writer in failed_writers:
                    writer_name = writer['name'].lower()
                    if 'sql' in writer_name:
                        remediation_steps.append("For SQL Server Writer: Restart SQL Server services")
                    elif 'exchange' in writer_name:
                        remediation_steps.append("For Exchange Writer: Restart Exchange services")
                    elif 'hyper-v' in writer_name:
                        remediation_steps.append("For Hyper-V Writer: Restart Hyper-V services")
            else:
                logger.info(f"[VSSDiagnostics] All {writer_count} VSS writer(s) are stable")
                remediation_steps.append(f"All {writer_count} VSS writer(s) are in stable state")
            
            return WriterStatus(
                all_stable=all_stable,
                writer_count=writer_count,
                failed_writers=failed_writers,
                remediation_steps=remediation_steps
            )
            
        except subprocess.TimeoutExpired:
            logger.error("[VSSDiagnostics] vssadmin list writers command timed out")
            return WriterStatus(
                all_stable=False,
                writer_count=0,
                failed_writers=[],
                remediation_steps=[
                    "VSS writer enumeration timed out (command took longer than 30 seconds)",
                    "System may be unresponsive or writers may be hung",
                    "Restart the VSS service: net stop vss && net start vss",
                    "Reboot the system if issue persists"
                ]
            )
            
        except FileNotFoundError:
            logger.error("[VSSDiagnostics] vssadmin command not found")
            return WriterStatus(
                all_stable=False,
                writer_count=0,
                failed_writers=[],
                remediation_steps=[
                    "vssadmin command not found - VSS may not be installed or available",
                    "Verify Windows installation integrity",
                    "Run system file checker: sfc /scannow"
                ]
            )
            
        except Exception as e:
            logger.error(f"[VSSDiagnostics] Unexpected error enumerating VSS writers: {e}")
            import traceback
            logger.debug(f"[VSSDiagnostics] Traceback: {traceback.format_exc()}")
            
            return WriterStatus(
                all_stable=False,
                writer_count=0,
                failed_writers=[],
                remediation_steps=[
                    f"Unexpected error enumerating VSS writers: {str(e)}",
                    "Check Windows Event Logs for system errors",
                    "Restart the VSS service: net stop vss && net start vss",
                    "Reboot the system if issue persists"
                ]
            )
    
    def check_system_policies(self) -> PolicyStatus:
        """Check for Group Policy or security restrictions on VSS.
        
        This method checks for:
        1. Group Policy restrictions that might block VSS operations
        2. BitLocker encryption status (can affect VSS performance)
        3. Other security software that might interfere with VSS
        
        Returns:
            PolicyStatus object containing policy and security restriction information
            
        Requirements:
            - 6.2: Check for Group Policy restrictions on VSS
            - 6.3: Report if security software may be blocking VSS
            - 6.4: Report BitLocker or other encryption status and potential impact on VSS
            - 6.5: Provide guidance on temporarily disabling security restrictions
        """
        logger.info("[VSSDiagnostics] Checking system policies and security restrictions")
        
        vss_restricted = False
        restrictions_found = []
        bitlocker_active = False
        remediation_steps = []
        
        # Step 1: Check BitLocker status
        try:
            # Use manage-bde to check BitLocker status
            result = subprocess.run(
                ["manage-bde", "-status"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            logger.debug(f"[VSSDiagnostics] manage-bde -status return code: {result.returncode}")
            
            if result.returncode == 0:
                output = result.stdout.lower()
                
                # Check if any volume has BitLocker enabled
                if "protection on" in output or "encryption method" in output:
                    bitlocker_active = True
                    restrictions_found.append("BitLocker encryption is active on one or more volumes")
                    logger.info("[VSSDiagnostics] BitLocker encryption detected")
                    
                    # BitLocker doesn't typically block VSS, but can affect performance
                    remediation_steps.append("BitLocker is active - VSS should work but may be slower")
                    remediation_steps.append("Ensure BitLocker is fully encrypted (not in progress)")
                else:
                    logger.info("[VSSDiagnostics] BitLocker is not active")
            else:
                logger.debug(f"[VSSDiagnostics] manage-bde failed: {result.stderr}")
                
        except subprocess.TimeoutExpired:
            logger.warning("[VSSDiagnostics] manage-bde command timed out")
            restrictions_found.append("Could not check BitLocker status (command timed out)")
            
        except FileNotFoundError:
            logger.debug("[VSSDiagnostics] manage-bde command not found (BitLocker may not be available)")
            
        except Exception as e:
            logger.debug(f"[VSSDiagnostics] Error checking BitLocker status: {e}")
        
        # Step 2: Check for Group Policy restrictions
        # Query registry keys that might indicate VSS restrictions
        try:
            import winreg
            
            # Check common Group Policy registry locations for VSS restrictions
            gp_keys_to_check = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\Backup\Client"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows NT\SystemRestore"),
                (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\VSS"),
            ]
            
            for hkey, subkey in gp_keys_to_check:
                try:
                    key = winreg.OpenKey(hkey, subkey, 0, winreg.KEY_READ)
                    
                    # Check for DisableVSS or similar values
                    try:
                        disable_value, _ = winreg.QueryValueEx(key, "DisableVSS")
                        if disable_value == 1:
                            vss_restricted = True
                            restrictions_found.append(f"Group Policy: VSS is disabled in {subkey}")
                            remediation_steps.append(f"VSS is disabled by Group Policy in {subkey}")
                            remediation_steps.append("Contact system administrator to enable VSS")
                            logger.warning(f"[VSSDiagnostics] VSS disabled by Group Policy in {subkey}")
                    except FileNotFoundError:
                        # Value doesn't exist, which is fine
                        pass
                    
                    winreg.CloseKey(key)
                    
                except FileNotFoundError:
                    # Key doesn't exist, which is fine
                    pass
                except PermissionError:
                    logger.debug(f"[VSSDiagnostics] Permission denied accessing registry key: {subkey}")
                    
        except ImportError:
            logger.debug("[VSSDiagnostics] winreg module not available")
        except Exception as e:
            logger.debug(f"[VSSDiagnostics] Error checking Group Policy registry: {e}")
        
        # Step 3: Check VSS service start type (if disabled, might be policy-restricted)
        try:
            service_status = self.check_vss_service_status()
            if service_status.start_type == "disabled":
                vss_restricted = True
                restrictions_found.append("VSS service is disabled (may be restricted by policy)")
                remediation_steps.append("VSS service is disabled - enable it: sc config VSS start=demand")
                logger.warning("[VSSDiagnostics] VSS service is disabled")
        except Exception as e:
            logger.debug(f"[VSSDiagnostics] Error checking VSS service status: {e}")
        
        # Step 4: Check for common antivirus/security software that might interfere
        # This is a heuristic check - we look for common security software processes
        try:
            result = subprocess.run(
                ["tasklist"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                output = result.stdout.lower()
                
                # List of security software that might interfere with VSS
                security_software = [
                    ("mcafee", "McAfee"),
                    ("symantec", "Symantec/Norton"),
                    ("kaspersky", "Kaspersky"),
                    ("avast", "Avast"),
                    ("avg", "AVG"),
                    ("bitdefender", "Bitdefender"),
                    ("eset", "ESET"),
                    ("trendmicro", "Trend Micro"),
                    ("sophos", "Sophos"),
                    ("crowdstrike", "CrowdStrike"),
                    ("carbonblack", "Carbon Black"),
                    ("cylance", "Cylance"),
                ]
                
                detected_security = []
                for process_name, display_name in security_software:
                    if process_name in output:
                        detected_security.append(display_name)
                
                if detected_security:
                    restrictions_found.append(f"Security software detected: {', '.join(detected_security)}")
                    remediation_steps.append(f"Security software detected: {', '.join(detected_security)}")
                    remediation_steps.append("Security software may interfere with VSS operations")
                    remediation_steps.append("Check security software logs for VSS-related blocks")
                    remediation_steps.append("Temporarily disable security software or whitelist vssadmin.exe")
                    logger.info(f"[VSSDiagnostics] Security software detected: {', '.join(detected_security)}")
                    
        except Exception as e:
            logger.debug(f"[VSSDiagnostics] Error checking for security software: {e}")
        
        # Step 5: Summary
        if not vss_restricted and not restrictions_found:
            remediation_steps.append("No obvious policy or security restrictions detected")
            logger.info("[VSSDiagnostics] No policy or security restrictions detected")
        else:
            logger.warning(f"[VSSDiagnostics] Found {len(restrictions_found)} potential restriction(s)")
        
        return PolicyStatus(
            vss_restricted=vss_restricted,
            restrictions_found=restrictions_found,
            bitlocker_active=bitlocker_active,
            remediation_steps=remediation_steps
        )
    
    def get_vss_event_log_errors(self, hours: int = 24) -> List[EventLogEntry]:
        """Retrieve VSS-related errors from Windows Event Log.
        
        This method queries the Windows Event Log for VSS-related errors
        from the specified time period. It looks in the System and Application
        logs for events from VSS, VolSnap, and related sources.
        
        Args:
            hours: Number of hours to look back in the event log (default: 24)
            
        Returns:
            List of EventLogEntry objects containing VSS-related errors
            
        Requirements:
            - 6.1: Check Windows Event Logs for VSS-related errors
        """
        logger.info(f"[VSSDiagnostics] Retrieving VSS event log errors from last {hours} hours")
        
        event_entries = []
        
        # Calculate time range
        from datetime import datetime, timedelta
        start_time = datetime.now() - timedelta(hours=hours)
        
        # Format time for wevtutil (ISO 8601 format)
        # wevtutil uses format: YYYY-MM-DDTHH:MM:SS
        start_time_str = start_time.strftime("%Y-%m-%dT%H:%M:%S")
        
        # VSS-related event sources to check
        vss_sources = ["VSS", "VolSnap", "VSSControl", "VSSVC"]
        
        # Event logs to check
        log_names = ["System", "Application"]
        
        for log_name in log_names:
            for source in vss_sources:
                try:
                    # Build XPath query to filter events
                    # Query for Error and Warning events from VSS sources
                    xpath_query = (
                        f"*[System[Provider[@Name='{source}'] and "
                        f"(Level=1 or Level=2 or Level=3) and "
                        f"TimeCreated[@SystemTime>='{start_time_str}']]]"
                    )
                    
                    # Use wevtutil to query event log
                    result = subprocess.run(
                        ["wevtutil", "qe", log_name, "/q:" + xpath_query, "/f:text", "/c:50"],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    
                    logger.debug(f"[VSSDiagnostics] wevtutil query for {source} in {log_name}: return code {result.returncode}")
                    
                    if result.returncode == 0 and result.stdout.strip():
                        # Parse the text output
                        output = result.stdout
                        
                        # Parse events from text format
                        # Text format has sections like:
                        # Event[0]:
                        #   Log Name: System
                        #   Source: VSS
                        #   Date: 2024-01-15T10:30:45.123
                        #   Event ID: 8193
                        #   Level: Error
                        #   ...
                        #   Description:
                        #   <message text>
                        
                        events = output.split("Event[")
                        for event_text in events[1:]:  # Skip first empty split
                            try:
                                event_data = {}
                                lines = event_text.split('\n')
                                
                                # Parse key-value pairs
                                current_key = None
                                message_lines = []
                                in_description = False
                                
                                for line in lines:
                                    line_stripped = line.strip()
                                    
                                    if not line_stripped:
                                        continue
                                    
                                    if line_stripped.startswith("Description:"):
                                        in_description = True
                                        continue
                                    
                                    if in_description:
                                        # Collect message lines
                                        message_lines.append(line_stripped)
                                    elif ':' in line_stripped:
                                        parts = line_stripped.split(':', 1)
                                        if len(parts) == 2:
                                            key = parts[0].strip().lower()
                                            value = parts[1].strip()
                                            
                                            if 'date' in key:
                                                event_data['timestamp'] = value
                                            elif 'event id' in key:
                                                try:
                                                    event_data['event_id'] = int(value)
                                                except ValueError:
                                                    event_data['event_id'] = 0
                                            elif 'level' in key:
                                                event_data['level'] = value
                                            elif 'source' in key:
                                                event_data['source'] = value
                                
                                # Build message from collected lines
                                if message_lines:
                                    event_data['message'] = ' '.join(message_lines)
                                
                                # Create EventLogEntry if we have required fields
                                if 'timestamp' in event_data and 'event_id' in event_data:
                                    entry = EventLogEntry(
                                        timestamp=event_data.get('timestamp', ''),
                                        event_id=event_data.get('event_id', 0),
                                        level=event_data.get('level', 'Unknown'),
                                        source=event_data.get('source', source),
                                        message=event_data.get('message', '')
                                    )
                                    event_entries.append(entry)
                                    logger.debug(f"[VSSDiagnostics] Found event: ID {entry.event_id}, Level {entry.level}")
                                    
                            except Exception as parse_error:
                                logger.debug(f"[VSSDiagnostics] Error parsing event: {parse_error}")
                                continue
                    
                except subprocess.TimeoutExpired:
                    logger.warning(f"[VSSDiagnostics] wevtutil query timed out for {source} in {log_name}")
                    
                except FileNotFoundError:
                    logger.debug("[VSSDiagnostics] wevtutil command not found")
                    break  # No point trying other sources if wevtutil doesn't exist
                    
                except Exception as e:
                    logger.debug(f"[VSSDiagnostics] Error querying event log for {source} in {log_name}: {e}")
        
        # Sort events by timestamp (most recent first)
        event_entries.sort(key=lambda e: e.timestamp, reverse=True)
        
        logger.info(f"[VSSDiagnostics] Found {len(event_entries)} VSS-related event log entries")
        
        return event_entries

    def run_full_diagnostics(self, volume: str = "C:") -> DiagnosticReport:
        """Run all diagnostic checks and return comprehensive report.
        
        This method aggregates all diagnostic checks into a single comprehensive
        report, determines overall system health, identifies blocking issues,
        and generates a consolidated remediation summary.
        
        Args:
            volume: Drive letter to check (e.g., "C:" or "C")
            
        Returns:
            DiagnosticReport object containing all diagnostic information
            
        Requirements:
            - 10.2: Generate comprehensive report with pass/fail status for each check
            - 10.3: Provide specific commands to resolve each issue
        """
        from datetime import datetime
        import ctypes
        
        logger.info(f"[VSSDiagnostics] Running full diagnostics for volume {volume}")
        
        # Generate timestamp
        timestamp = datetime.now().isoformat()
        
        # Check if running as administrator
        is_admin = False
        try:
            if os.name == 'nt':
                is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
            else:
                is_admin = os.getuid() == 0
            logger.info(f"[VSSDiagnostics] Administrator privileges: {is_admin}")
        except Exception as e:
            logger.warning(f"[VSSDiagnostics] Could not check admin privileges: {e}")
        
        # Run all diagnostic checks
        logger.info("[VSSDiagnostics] Running service status check...")
        service_status = self.check_vss_service_status()
        
        logger.info("[VSSDiagnostics] Running shadow copy enumeration...")
        shadow_copy_status = self.check_shadow_copies(volume)
        
        logger.info("[VSSDiagnostics] Running disk space check...")
        disk_space_status = self.check_disk_space(volume)
        
        logger.info("[VSSDiagnostics] Running provider check...")
        provider_status = self.check_vss_providers()
        
        logger.info("[VSSDiagnostics] Running writer check...")
        writer_status = self.check_vss_writers()
        
        logger.info("[VSSDiagnostics] Running policy check...")
        policy_status = self.check_system_policies()
        
        logger.info("[VSSDiagnostics] Retrieving event log errors...")
        event_log_errors = self.get_vss_event_log_errors(hours=24)
        
        # Determine overall health and blocking issues
        blocking_issues = []
        can_create_shadow = True
        
        # Check for critical blocking issues
        if not is_admin:
            blocking_issues.append("Not running as Administrator - VSS operations require elevated privileges")
            can_create_shadow = False
        
        if not service_status.is_running:
            blocking_issues.append(f"VSS service is not running: {service_status.status_message}")
            can_create_shadow = False
        
        if not provider_status.providers_available:
            blocking_issues.append("No VSS providers available - VSS functionality is not available")
            can_create_shadow = False
        
        if not disk_space_status.sufficient_for_shadow:
            blocking_issues.append("Insufficient disk space or VSS quota for shadow copy creation")
            can_create_shadow = False
        
        if not writer_status.all_stable:
            # Failed writers are a warning, not necessarily blocking
            # But we'll note it as a potential issue
            logger.warning(f"[VSSDiagnostics] {len(writer_status.failed_writers)} VSS writer(s) in failed state")
        
        if policy_status.vss_restricted:
            blocking_issues.append("VSS operations may be restricted by Group Policy or security software")
            # This might not always block, but we'll be conservative
            can_create_shadow = False
        
        # Determine overall health status
        if len(blocking_issues) == 0:
            if not writer_status.all_stable or len(event_log_errors) > 0:
                overall_health = "degraded"
                logger.info("[VSSDiagnostics] Overall health: degraded (minor issues detected)")
            else:
                overall_health = "healthy"
                logger.info("[VSSDiagnostics] Overall health: healthy")
        else:
            overall_health = "failed"
            logger.warning(f"[VSSDiagnostics] Overall health: failed ({len(blocking_issues)} blocking issue(s))")
        
        # Generate consolidated remediation summary
        remediation_summary = []
        
        # Add admin privilege requirement first if needed
        if not is_admin:
            remediation_summary.append("Run this application as Administrator (right-click -> Run as administrator)")
        
        # Add service-related remediation
        if service_status.remediation_steps:
            for step in service_status.remediation_steps:
                if step not in remediation_summary:
                    remediation_summary.append(step)
        
        # Add disk space remediation
        if disk_space_status.remediation_steps:
            for step in disk_space_status.remediation_steps:
                # Skip only the positive "sufficient" message, but include warnings and errors
                if "sufficient" in step.lower() and "insufficient" not in step.lower():
                    continue
                if step not in remediation_summary:
                    remediation_summary.append(step)
        
        # Add provider remediation
        if provider_status.error_message:
            remediation_summary.append(f"VSS Provider issue: {provider_status.error_message}")
        
        # Add writer remediation
        if writer_status.remediation_steps:
            for step in writer_status.remediation_steps:
                # Skip the "all stable" message
                if "stable" not in step.lower() or "failed" in step.lower():
                    if step not in remediation_summary:
                        remediation_summary.append(step)
        
        # Add policy remediation
        if policy_status.remediation_steps:
            for step in policy_status.remediation_steps:
                # Skip the "no restrictions" message
                if "no obvious" not in step.lower() and step not in remediation_summary:
                    remediation_summary.append(step)
        
        # Add event log guidance if there are errors
        if len(event_log_errors) > 0:
            remediation_summary.append(f"Found {len(event_log_errors)} VSS-related error(s) in Event Log - review for additional details")
        
        # If no issues found, add positive message
        if len(remediation_summary) == 0:
            remediation_summary.append("All VSS diagnostic checks passed - system is ready for shadow copy creation")
        
        logger.info(f"[VSSDiagnostics] Diagnostic report complete: {overall_health}, {len(blocking_issues)} blocking issue(s), {len(remediation_summary)} remediation step(s)")
        
        # Create and return the diagnostic report
        return DiagnosticReport(
            timestamp=timestamp,
            is_admin=is_admin,
            service_status=service_status,
            shadow_copy_status=shadow_copy_status,
            disk_space_status=disk_space_status,
            provider_status=provider_status,
            writer_status=writer_status,
            policy_status=policy_status,
            event_log_errors=event_log_errors,
            overall_health=overall_health,
            can_create_shadow=can_create_shadow,
            blocking_issues=blocking_issues,
            remediation_summary=remediation_summary
        )
