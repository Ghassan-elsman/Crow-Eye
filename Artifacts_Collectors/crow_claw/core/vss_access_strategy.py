"""
Volume Shadow Copy Service (VSS) access strategy implementation.

This module implements the VSSAccessStrategy which accesses files through
VSS snapshots. This is useful for accessing locked system files on live systems.
"""

import logging
import os
import re
import shutil
import subprocess
import time
import locale
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from .access_strategy import FileAccessStrategy
from .shadow_copy import ShadowCopy

if TYPE_CHECKING:
    from .access_result import AccessResult

# Configure logging
logger = logging.getLogger(__name__)


class VSSAccessStrategy(FileAccessStrategy):
    """Access files via Volume Shadow Copy Service.
    
    This strategy accesses files through VSS snapshots, which is useful for
    collecting locked system files on live Windows systems. It requires
    administrator privileges and the VSS service to be running.
    
    Requirements:
        - 1.1: Attempt VSS access for locked files
        - 1.2: Enumerate and select most recent shadow copy
        - 1.3: Verify VSS service is running
        - 1.6: Require admin privileges
    """
    
    def __init__(self):
        """Initialize the VSS access strategy.
        
        Initializes the shadow copy cache and VSS availability flag.
        Shadow copies are enumerated on first use.
        """
        super().__init__()
        from .vss_diagnostics import VSSDiagnostics
        from .shadow_copy_manager import ShadowCopyManager
        from .vss_error_reporter import VSSErrorReporter
        
        self.diagnostics = VSSDiagnostics()
        self.shadow_manager = ShadowCopyManager(self.diagnostics)
        self.error_reporter = VSSErrorReporter()
        self.shadow_copies: List[ShadowCopy] = []
        self.vss_available: bool = False
        self._enumerated: bool = False
        self._creation_attempted: dict[str, bool] = {}  # Track per volume
    
    def _check_admin_privileges(self) -> bool:
        """Check if current process has administrator privileges.

        Returns:
            True if running with admin privileges, False otherwise
        """
        if os.name == 'nt':
            try:
                import ctypes
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
            except Exception:
                return False
        else:
            try:
                return getattr(os, 'getuid', lambda: 1)() == 0
            except:
                return False
    
    def _parse_datetime_flexible(self, time_str: str) -> Optional[datetime]:
        """Parse datetime string with multiple format attempts.
        
        Tries various datetime formats to handle different Windows versions
        and locale settings.
        
        Args:
            time_str: Datetime string to parse
            
        Returns:
            Parsed datetime object, or None if parsing fails
        """
        if not time_str:
            return None
        
        time_str = time_str.strip()
        
        # List of datetime formats to try
        formats = [
            "%m/%d/%Y %I:%M:%S %p",      # 3/7/2026 3:48:13 AM
            "%m/%d/%Y %H:%M:%S",          # 3/7/2026 15:48:13
            "%d/%m/%Y %I:%M:%S %p",      # 7/3/2026 3:48:13 AM (European)
            "%d/%m/%Y %H:%M:%S",          # 7/3/2026 15:48:13 (European)
            "%Y-%m-%d %H:%M:%S",          # 2026-03-07 15:48:13 (ISO)
            "%Y/%m/%d %H:%M:%S",          # 2026/03/07 15:48:13
            "%m-%d-%Y %I:%M:%S %p",      # 03-07-2026 3:48:13 AM
            "%m-%d-%Y %H:%M:%S",          # 03-07-2026 15:48:13
            "%d.%m.%Y %H:%M:%S",          # 07.03.2026 15:48:13 (German)
            "%Y.%m.%d %H:%M:%S",          # 2026.03.07 15:48:13
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue
        
        # If all formats fail, try to extract components manually
        try:
            # Try to parse with dateutil if available
            from dateutil import parser
            return parser.parse(time_str)
        except:
            pass
        
        return None
    
    def _check_vss_service(self) -> bool:
        """Check if the VSS service is running.
        
        Verifies that the Volume Shadow Copy service is running before
        attempting to enumerate or access shadow copies.
        
        Returns:
            True if VSS service is running, False otherwise
            
        Requirements:
            - 1.3: Verify VSS service is running
        """
        try:
            # Try using win32serviceutil if available
            try:
                import win32serviceutil
                import win32service
                
                # Check if VSS service is running
                # Service name is "VSS" (Volume Shadow Copy)
                status = win32serviceutil.QueryServiceStatus("VSS")
                return status[1] == win32service.SERVICE_RUNNING
                
            except (ImportError, Exception):
                # Fall back to subprocess if win32serviceutil not available or fails
                result = subprocess.run(
                    ["sc", "query", "VSS"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                # Check if service is running
                if result.returncode == 0:
                    return "RUNNING" in result.stdout
                return False
                
        except Exception:
            # If we can't check the service, try to enumerate anyway
            # (vssadmin might still work)
            return True  # Changed from False to True - be optimistic
    
    def enumerate_shadow_copies(self) -> List[ShadowCopy]:
        """Enumerate available VSS snapshots.
        
        Uses vssadmin to list all available shadow copies on the system.
        Parses the output to extract shadow copy metadata.
        
        Returns:
            List of ShadowCopy objects, sorted by creation time (newest first)
            
        Requirements:
            - 1.2: Enumerate all available shadow copies
        """
        if self._enumerated:
            return self.shadow_copies
        
        self._enumerated = True
        shadow_copies = []
        
        try:
            # Check if VSS service is running first
            if not self._check_vss_service():
                self.vss_available = False
                return shadow_copies
            
            # Run vssadmin to list shadow copies
            result = subprocess.run(
                ["vssadmin", "list", "shadows"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                self.vss_available = False
                return shadow_copies
            
            # Parse the output
            output = result.stdout
            
            # Split by "Contents of shadow copy set ID:" to get each set
            set_entries = re.split(r'Contents of shadow copy set ID:', output)
            
            for set_entry in set_entries:
                if not set_entry.strip():
                    continue
                
                # Extract creation time - try multiple formats
                set_time_match = None
                time_str = None
                
                # Format 1: "Contained X shadow copies at creation time: DATE"
                set_time_match = re.search(
                    r'Contained \d+ shadow cop(?:y|ies) at creation time:\s*([^\r\n]+)',
                    set_entry,
                    re.IGNORECASE
                )
                
                if set_time_match:
                    time_str = set_time_match.group(1).strip()
                
                # Split into individual shadow copy entries within this set
                # Each entry starts with "Shadow Copy ID:"
                shadow_entries = re.split(r'(?=Shadow Copy ID:)', set_entry)
                
                for entry in shadow_entries:
                    if not entry.strip() or 'Shadow Copy ID:' not in entry:
                        continue
                    
                    # Extract shadow copy ID
                    id_match = re.search(r'Shadow Copy ID:\s*(\{[^}]+\})', entry, re.IGNORECASE)
                    if not id_match:
                        continue
                    shadow_id = id_match.group(1)
                    
                    # Extract shadow copy volume path
                    volume_match = re.search(
                        r'Shadow Copy Volume:\s*([^\r\n]+)',
                        entry,
                        re.IGNORECASE
                    )
                    if not volume_match:
                        continue
                    shadow_volume = volume_match.group(1).strip()
                    
                    # Parse creation time - try multiple formats
                    creation_time = None
                    
                    # First try to find "Creation Time:" field in the entry itself
                    entry_time_match = re.search(
                        r'Creation Time:\s*([^\r\n]+)',
                        entry,
                        re.IGNORECASE
                    )
                    
                    if entry_time_match:
                        time_str = entry_time_match.group(1).strip()
                    
                    if time_str:
                        creation_time = self._parse_datetime_flexible(time_str)
                    
                    if not creation_time:
                        # Use current time as fallback
                        creation_time = datetime.now()
                    
                    # Extract original volume - try multiple formats
                    original_volume = None
                    
                    # Format 1: "Original Volume: (C:)\\?\Volume{...}"
                    orig_volume_match = re.search(
                        r'Original Volume:\s*\(([A-Z]:)\)',
                        entry,
                        re.IGNORECASE
                    )
                    
                    if orig_volume_match:
                        original_volume = orig_volume_match.group(1)
                    else:
                        # Format 2: "Original Volume: C:\" or similar
                        orig_volume_match = re.search(
                            r'Original Volume:\s*([A-Z]:)',
                            entry,
                            re.IGNORECASE
                        )
                        if orig_volume_match:
                            original_volume = orig_volume_match.group(1)
                        else:
                            # Format 3: Extract from full path
                            orig_volume_match = re.search(
                                r'Original Volume:\s*([^\r\n]+)',
                                entry,
                                re.IGNORECASE
                            )
                            if orig_volume_match:
                                vol_str = orig_volume_match.group(1).strip()
                                # Try to extract drive letter from various formats
                                drive_match = re.search(r'\(([A-Z]:)\)', vol_str)
                                if drive_match:
                                    original_volume = drive_match.group(1)
                                else:
                                    # Default to C: if we can't parse
                                    original_volume = "C:"
                    
                    if not original_volume:
                        # Default to C: if we can't determine the volume
                        original_volume = "C:"
                    
                    # Ensure format is "X:" without trailing backslash
                    if original_volume and not original_volume.endswith(':'):
                        original_volume = original_volume.rstrip('\\')
                    if original_volume and len(original_volume) > 2:
                        original_volume = original_volume[:2]
                    
                    # Create ShadowCopy object
                    shadow_copy = ShadowCopy(
                        shadow_copy_id=shadow_id,
                        shadow_copy_volume=shadow_volume,
                        creation_time=creation_time,
                        original_volume=original_volume
                    )
                    shadow_copies.append(shadow_copy)
            
            # Sort by creation time (newest first)
            shadow_copies.sort(key=lambda sc: sc.creation_time, reverse=True)
            
            self.shadow_copies = shadow_copies
            self.vss_available = len(shadow_copies) > 0
            
            # Debug logging
            logger.debug(f"[VSS] Enumerated {len(shadow_copies)} shadow copies")
            for sc in shadow_copies:
                logger.debug(f"[VSS]   - {sc.shadow_copy_id} for {sc.original_volume} at {sc.creation_time}")
            
        except Exception as e:
            # If enumeration fails, VSS is not available
            # Log the error for debugging
            import traceback
            logger.error(f"[VSS] Failed to enumerate shadow copies: {e}")
            logger.error(f"[VSS] Traceback: {traceback.format_exc()}")
            self.vss_available = False
        
        return shadow_copies
    
    def get_most_recent_shadow_copy(self, volume: str = "C:\\") -> Optional[ShadowCopy]:
        """Get the most recent shadow copy for a given volume.
        
        Args:
            volume: The volume to find a shadow copy for (e.g., "C:\\")
            
        Returns:
            The most recent ShadowCopy for the volume, or None if not found
            
        Requirements:
            - 1.2: Select the most recent snapshot
        """
        # Ensure shadow copies are enumerated
        if not self._enumerated:
            self.enumerate_shadow_copies()
        
        # Normalize volume format
        if not volume.endswith("\\"):
            volume = volume + "\\"
        
        # Find shadow copies for this volume
        for shadow_copy in self.shadow_copies:
            # Match volume (handle different formats)
            orig_vol = shadow_copy.original_volume
            if not orig_vol.endswith("\\"):
                orig_vol = orig_vol + "\\"
            
            if orig_vol.upper() == volume.upper():
                return shadow_copy
        
        return None
    
    def get_vss_path(self, file_path: str, shadow_copy: ShadowCopy) -> str:
        r"""Convert regular path to VSS path.
        
        Converts a standard file path to a VSS shadow copy path that can
        be used to access the file from the snapshot.
        
        Args:
            file_path: Regular file path (e.g., C:\Windows\System32\config\SYSTEM)
            shadow_copy: The shadow copy to use
            
        Returns:
            VSS path (e.g., \\?\GLOBALROOT\Device\HarddiskVolumeShadowCopy1\Windows\System32\config\SYSTEM)
        """
        # Extract the path without the drive letter
        # C:\Windows\System32\config\SYSTEM -> \Windows\System32\config\SYSTEM
        if len(file_path) >= 2 and file_path[1] == ':':
            path_without_drive = file_path[2:]
        else:
            path_without_drive = file_path
        
        # Remove leading backslash if present
        if path_without_drive.startswith("\\"):
            path_without_drive = path_without_drive[1:]
        
        # Construct VSS path
        # Format: \\?\GLOBALROOT\Device\HarddiskVolumeShadowCopy{N}\path
        vss_path = f"{shadow_copy.shadow_copy_volume}\\{path_without_drive}"
        
        return vss_path
    
    def create_temporary_shadow_copy(self, volume: str = "C:") -> Optional[ShadowCopy]:
        """Create a temporary shadow copy for the specified volume.
        
        Args:
            volume: The volume to create a shadow copy for (e.g., "C:")
            
        Returns:
            The newly created ShadowCopy, or None if creation fails
        """
        # Ensure volume format is "C:"
        volume = volume.rstrip('\\')
        if len(volume) > 2:
            volume = volume[:2]
            
        try:
            # Command: vssadmin create shadow /for=C:
            logger.info(f"[VSS] Attempting to create shadow copy for {volume}")
            result = subprocess.run(
                ["vssadmin", "create", "shadow", f"/for={volume}"],
                capture_output=True,
                text=True,
                timeout=60 # Creating a shadow can take some time
            )
            
            if result.returncode != 0:
                # Log the actual error from vssadmin
                logger.error(f"[VSS] Shadow copy creation failed with return code {result.returncode}")
                logger.error(f"[VSS] stdout: {result.stdout}")
                logger.error(f"[VSS] stderr: {result.stderr}")
                return None
            
            logger.info(f"[VSS] Shadow copy creation command succeeded")
            
            # Re-enumerate to find the new shadow copy
            self._enumerated = False
            self.enumerate_shadow_copies()
            
            # Return the most recent one (which should be the one we just created)
            return self.get_most_recent_shadow_copy(f"{volume}\\")
            
        except Exception as e:
            logger.error(f"[VSS] Exception during shadow copy creation: {e}")
            import traceback
            logger.error(f"[VSS] Traceback: {traceback.format_exc()}")
            return None

    def _attempt_shadow_creation_with_diagnostics(
        self,
        volume: str
    ) -> 'ShadowCopyCreationResult':
        """Attempt shadow copy creation with full diagnostic support.
        
        Checks if creation has already been attempted for this volume in the current
        session. If not, delegates to ShadowCopyManager to create a shadow copy with
        comprehensive diagnostics and error reporting.
        
        Args:
            volume: Drive letter to create shadow copy for (e.g., "C:" or "C")
            
        Returns:
            ShadowCopyCreationResult with detailed information about the attempt
            
        Requirements:
            - 8.1: Attempt shadow copy creation when none exist
            - 8.4: Log attempt, duration, and outcome
            - 8.5: Only attempt automatic shadow copy creation once per volume per collection session
        """
        import logging
        import time
        from .shadow_copy_manager import ShadowCopyCreationResult, PreCreationCheckResult, VssAdminResult, VssAdminError
        
        logger = logging.getLogger(__name__)
        
        # Normalize volume format to "X:" (no trailing backslash)
        volume_normalized = volume.rstrip('\\')
        if not volume_normalized.endswith(':'):
            volume_normalized = volume_normalized + ':'
        
        logger.info(f"[VSSAccessStrategy] Attempting shadow copy creation for volume {volume_normalized}")
        
        # Check if creation already attempted for this volume
        if volume_normalized in self._creation_attempted:
            logger.warning(
                f"[VSSAccessStrategy] Shadow copy creation already attempted for volume {volume_normalized} "
                "in this session - skipping to prevent repeated failures"
            )
            
            # Return a failed result indicating we won't retry
            return ShadowCopyCreationResult(
                success=False,
                shadow_copy=None,
                duration_seconds=0.0,
                pre_creation_checks=PreCreationCheckResult(
                    all_passed=False,
                    checks={"already_attempted": False},
                    blocking_issues=[
                        f"Shadow copy creation already attempted for volume {volume_normalized} in this session"
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
                    technical_details=f"Shadow copy creation was already attempted for {volume_normalized}",
                    user_friendly_message=(
                        f"Shadow copy creation was already attempted for volume {volume_normalized} in this session. "
                        "To prevent repeated failures, we only attempt creation once per volume per session."
                    ),
                    remediation_steps=[
                        "Restart the collection to reset attempt tracking",
                        f"Manually create a shadow copy using: vssadmin create shadow /for={volume_normalized}",
                        "Check if a shadow copy already exists: vssadmin list shadows"
                    ],
                    is_retryable=False
                ),
                diagnostics=None,
                remediation_steps=[
                    "Restart the collection to reset attempt tracking",
                    f"Manually create a shadow copy using: vssadmin create shadow /for={volume_normalized}"
                ]
            )
        
        # Mark volume as attempted BEFORE calling create_shadow_copy
        # This ensures we track the attempt even if the manager's internal tracking fails
        self._creation_attempted[volume_normalized] = True
        logger.debug(f"[VSSAccessStrategy] Marked volume {volume_normalized} as attempted")
        
        # Delegate to ShadowCopyManager for actual creation with diagnostics
        logger.info(f"[VSSAccessStrategy] Delegating to ShadowCopyManager for volume {volume_normalized}")
        start_time = time.time()
        
        result = self.shadow_manager.create_shadow_copy(volume=volume_normalized, timeout=120)
        
        duration = time.time() - start_time
        
        # Log the outcome
        if result.success:
            logger.info(
                f"[VSSAccessStrategy] Shadow copy creation succeeded for volume {volume_normalized} "
                f"(duration: {duration:.2f}s)"
            )
        else:
            logger.error(
                f"[VSSAccessStrategy] Shadow copy creation failed for volume {volume_normalized} "
                f"(duration: {duration:.2f}s): {result.error.error_message if result.error else 'Unknown error'}"
            )
        
        return result

    def can_handle(self, file_path: str, artifact_type: str) -> bool:
            """
            Return True if administrator privileges exist.
            Do NOT enumerate shadow copies here - that happens in access_file().

            Args:
                file_path: Path to the file to access
                artifact_type: Type of artifact (not used for VSS)

            Returns:
                True if administrator privileges exist
            """
            return self._check_admin_privileges()


    def access_file(self, file_path: str, dest_path: str) -> 'AccessResult':
        """Attempt to access and copy the file via VSS.
        
        Enhanced with diagnostic-driven shadow copy creation.
        
        Process:
        1. Enumerate shadow copies if not already done
        2. If shadow copy exists, use it
        3. If no shadow copy exists:
           a. Run diagnostics to check if creation is possible
           b. Attempt automatic shadow copy creation
           c. If creation succeeds, retry access
           d. If creation fails, return detailed error report
        
        Args:
            file_path: Source file path
            dest_path: Destination file path
            
        Returns:
            AccessResult containing success status, VSS details, and any errors
            
        Requirements:
            - 8.1: Attempt shadow copy creation when none exist
            - 8.2: Re-enumerate and retry on successful creation
            - 8.3: Report failure with diagnostic information
            - 9.3: Enumerate shadow copies on first access_file() call
            - 9.4: Cache enumeration results
        """
        from .access_result import AccessResult
        
        start_time = time.time()
        
        # Enumerate shadow copies if not already done (lazy enumeration)
        if not self._enumerated:
            self.enumerate_shadow_copies()
        
        # Extract volume from file path
        if len(file_path) >= 2 and file_path[1] == ':':
            volume_letter = file_path[0:2]
            volume = volume_letter + "\\"
        else:
            duration = time.time() - start_time
            error_msg = "Invalid file path format (no drive letter)"
            logger.error(
                f"[VSSAccessStrategy] {error_msg}: {file_path}"
            )
            return AccessResult(
                success=False,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="vss",
                error=error_msg,
                duration_seconds=duration,
                status="failed"
            )
        
        # Get shadow copy for this volume
        shadow_copy = self.get_most_recent_shadow_copy(volume)
        
        # Debug logging
        logger.debug(f"[VSS] Attempting to access: {file_path}")
        logger.debug(f"[VSS] Volume: {volume}")
        logger.debug(f"[VSS] Shadow copy found: {shadow_copy is not None}")
        if shadow_copy:
            logger.debug(f"[VSS] Shadow copy ID: {shadow_copy.shadow_copy_id}")
        
        # If no shadow copy exists, attempt diagnostic-driven creation
        if not shadow_copy:
            logger.warning(f"[VSS] No shadow copy found for volume {volume_letter}, attempting diagnostic-driven creation...")
            creation_result = self._attempt_shadow_creation_with_diagnostics(volume_letter)
            
            if creation_result.success:
                # Creation succeeded - re-enumerate and get the new shadow copy
                logger.info(f"[VSS] Shadow copy created successfully for volume {volume_letter}")
                self._enumerated = False
                self.enumerate_shadow_copies()
                shadow_copy = self.get_most_recent_shadow_copy(volume)
                
                if shadow_copy:
                    logger.info(f"[VSS] Using newly created shadow copy: {shadow_copy.shadow_copy_id}")
            else:
                # Creation failed - generate detailed error report with RED logging
                error_msg = creation_result.error.error_message if creation_result.error else 'Unknown error'
                logger.error(f"[VSS] Shadow copy creation FAILED for volume {volume_letter}: {error_msg}")
                
                # Log detailed diagnostic information
                if creation_result.pre_creation_checks and not creation_result.pre_creation_checks.all_passed:
                    logger.error(f"[VSS] Pre-creation checks FAILED:")
                    for issue in creation_result.pre_creation_checks.blocking_issues:
                        logger.error(f"[VSS]   - {issue}")
                
                # Log vssadmin command output if available
                if creation_result.vssadmin_result:
                    logger.error(f"[VSS] vssadmin return code: {creation_result.vssadmin_result.returncode}")
                    if creation_result.vssadmin_result.stderr:
                        logger.error(f"[VSS] vssadmin stderr: {creation_result.vssadmin_result.stderr}")
                
                # Generate structured error report
                error_report = self.error_reporter.generate_error_report(
                    creation_result,
                    context={
                        'volume': volume_letter,
                        'file_path': file_path,
                        'artifact_type': 'locked_file'
                    }
                )
                
                # Log remediation steps
                if error_report.remediation_steps:
                    logger.error(f"[VSS] Recommended actions to fix VSS issues:")
                    for step in error_report.remediation_steps[:3]:  # Top 3 steps
                        logger.error(f"[VSS]   {step.step_number}. {step.description}")
                        if step.command:
                            logger.error(f"[VSS]      Command: {step.command}")
                
                # Format error for AccessResult
                error_message = error_report.user_friendly_message
                if error_report.remediation_steps:
                    error_message += "\n\nRecommended actions:\n"
                    for step in error_report.remediation_steps[:3]:  # Top 3 steps
                        error_message += f"  {step.step_number}. {step.description}\n"
                        if step.command:
                            error_message += f"     Command: {step.command}\n"
                
                duration = time.time() - start_time
                return AccessResult(
                    success=False,
                    source_path=file_path,
                    dest_path=dest_path,
                    strategy_used="vss",
                    error=error_message,
                    duration_seconds=duration,
                    status="failed"
                )
            
        if not shadow_copy:
            duration = time.time() - start_time
            error_msg = f"No shadow copy found or could be created for volume {volume}"
            logger.error(
                f"[VSSAccessStrategy] {error_msg} (file: {file_path})"
            )
            return AccessResult(
                success=False,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="vss",
                error=error_msg,
                duration_seconds=duration,
                status="failed"
            )
        
        # Convert to VSS path
        vss_path = self.get_vss_path(file_path, shadow_copy)
        
        # Debug logging
        logger.debug(f"[VSS] VSS path: {vss_path}")
        logger.debug(f"[VSS] Checking if VSS path exists...")
        vss_exists = os.path.exists(vss_path)
        logger.debug(f"[VSS] VSS path exists: {vss_exists}")
        
        try:
            # Ensure destination directory exists
            dest_dir = os.path.dirname(dest_path)
            if dest_dir and not os.path.exists(dest_dir):
                os.makedirs(dest_dir, exist_ok=True)
            
            # FIXED: Use raw file operations instead of shutil.copy2
            # shutil.copy2 tries to preserve metadata which fails on VSS device paths
            # Use simple binary copy instead
            try:
                with open(vss_path, 'rb') as src_file:
                    with open(dest_path, 'wb') as dst_file:
                        # Copy in chunks to handle large files
                        chunk_size = 1024 * 1024  # 1MB chunks
                        while True:
                            chunk = src_file.read(chunk_size)
                            if not chunk:
                                break
                            dst_file.write(chunk)
            except Exception as copy_error:
                # If raw copy fails, try shutil.copy (not copy2) as fallback
                # shutil.copy doesn't preserve metadata, so it's more reliable
                shutil.copy(vss_path, dest_path)
            
            # Get file size after successful copy
            file_size = os.path.getsize(dest_path)
            
            duration = time.time() - start_time
            
            return AccessResult(
                success=True,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="vss",
                file_size=file_size,
                vss_shadow_copy_id=shadow_copy.shadow_copy_id,
                duration_seconds=duration,
                status="success"
            )
            
        except FileNotFoundError:
            # File doesn't exist in shadow copy
            duration = time.time() - start_time
            error_msg = f"File not found in shadow copy: {vss_path}"
            logger.error(
                f"[VSSAccessStrategy] {error_msg} (original: {file_path}, shadow_copy_id: {shadow_copy.shadow_copy_id})"
            )
            return AccessResult(
                success=False,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="vss",
                error=error_msg,
                vss_shadow_copy_id=shadow_copy.shadow_copy_id,
                duration_seconds=duration,
                status="failed"
            )
            
        except PermissionError as e:
            # Still locked even in shadow copy (rare)
            duration = time.time() - start_time
            error_msg = f"Permission denied accessing VSS: {str(e)}"
            logger.error(
                f"[VSSAccessStrategy] {error_msg} (file: {file_path}, vss_path: {vss_path}, shadow_copy_id: {shadow_copy.shadow_copy_id})"
            )
            return AccessResult(
                success=False,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="vss",
                error=error_msg,
                vss_shadow_copy_id=shadow_copy.shadow_copy_id,
                duration_seconds=duration,
                status="failed"
            )
            
        except OSError as e:
            # Other OS errors
            duration = time.time() - start_time
            error_msg = f"OS error accessing VSS: {str(e)}"
            
            if hasattr(e, 'winerror'):
                error_msg = f"OS error (code {e.winerror}) accessing VSS: {str(e)}"
            
            logger.error(
                f"[VSSAccessStrategy] {error_msg} (file: {file_path}, vss_path: {vss_path}, shadow_copy_id: {shadow_copy.shadow_copy_id})"
            )
            
            return AccessResult(
                success=False,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="vss",
                error=error_msg,
                vss_shadow_copy_id=shadow_copy.shadow_copy_id,
                duration_seconds=duration,
                status="failed"
            )
            
        except Exception as e:
            # Catch-all for unexpected errors
            duration = time.time() - start_time
            error_msg = f"Unexpected error accessing VSS: {str(e)}"
            logger.error(
                f"[VSSAccessStrategy] {error_msg} (file: {file_path}, vss_path: {vss_path}, shadow_copy_id: {shadow_copy.shadow_copy_id})",
                exc_info=True  # Include stack trace for unexpected errors
            )
            return AccessResult(
                success=False,
                source_path=file_path,
                dest_path=dest_path,
                strategy_used="vss",
                error=error_msg,
                vss_shadow_copy_id=shadow_copy.shadow_copy_id,
                duration_seconds=duration,
                status="failed"
            )
    
    def requires_admin(self) -> bool:
        """Check if this strategy requires administrator privileges.
        
        VSS access requires administrator privileges.
        
        Returns:
            True - VSS access requires admin privileges
            
        Requirements:
            - 1.6: Require admin privileges for VSS
        """
        return True
