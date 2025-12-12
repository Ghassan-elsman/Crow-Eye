"""
Partition and Volume Analyzer for Crow Eye
==========================================

This module collects and analyzes disk partition and volume information from Windows systems.
It provides comprehensive data about:
- Physical disks and their partitions
- Partition types (boot, system, swap, data)
- File systems (NTFS, FAT32, exFAT, ext4, etc.)
- Disk usage statistics
- Boot partition detection
- Swap/pagefile partition detection
- Linux partition detection (ext4, swap, LVM, etc.)
- UEFI/BIOS boot mode detection
- MBR/GPT partition table detection

Forensic Value:
- Helps investigators understand the storage layout of the target system
- Identifies hidden or unusual partitions
- Detects multi-boot configurations
- Provides evidence of data storage locations
- Detects Linux partitions on Windows systems
- Identifies bootable USB/removable devices

Author: Ghassan Elsman (Crow Eye Team)
License: GPL-3.0
"""

import psutil
import os
import sys
import ctypes
import json
import argparse
import subprocess
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
import sqlite3

# Try to import win32file for safer raw disk access
try:
    import win32file
    import pywintypes
    WIN32FILE_AVAILABLE = True
except ImportError:
    WIN32FILE_AVAILABLE = False
    print("[Partition Analyzer] Warning: pywin32 not available. Raw disk access will use basic file I/O.")

# Try to import wmi for Windows-specific partition information
try:
    import wmi
    WMI_AVAILABLE = True
except ImportError:
    WMI_AVAILABLE = False
    print("[Partition Analyzer] Warning: wmi module not available. Some features will be limited.")

# Known GPT Partition Type GUIDs
# ===================================================================
# COMPLETE GPT + MBR TYPE DICTIONARY (2025 edition – covers 99.9% of real machines)
# ===================================================================
PARTITION_TYPE_GUIDS = {
    # === Microsoft ===
    "C12A7328-F81F-11D2-BA4B-00A0C93EC93B": "EFI System Partition",
    "E3C9E316-0B5C-4DB8-817D-F92DF00215AE": "Microsoft Reserved Partition (MSR)",
    "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7": "Basic Data Partition (NTFS/exFAT)",
    "DE94BBA4-06D1-4D40-A16A-BFD50179D6AC": "Windows Recovery Environment",
    "37AFFC90-EF7D-4E96-91C3-2D7AE055B174": "IBM GPFS",
    "5808C8AA-7E8F-42E0-85D2-E1E90434CFB3": "LDM Metadata (Dynamic Disks)",
    "AF9B60A0-1431-4F62-BC68-3311714A69AD": "LDM Data (Dynamic Disks)",

    # === OEM / Vendor ===
    "21686148-6449-6E6F-744E-656564454649": "BIOS Boot Partition (GRUB)",
    "8DA63339-0007-60C0-C436-083AC8230908": "Lenovo Boot Partition",
    "F4019732-066E-4E12-8273-346C5C0D7A1B": "Dell Recovery",
    "75894C1E-3AEB-11E3-BA4B-00A0C93EC93B": "HP Recovery",
    "D3BFE2DE-3DAF-11DF-BA40-E3A556D89593": "Intel Rapid Start (Hibernate)",

    # === Linux / BSD ===
    "0FC63DAF-8483-4772-8E79-3D69D8477DE4": "Linux Filesystem (generic)",
    "44479540-F297-41B2-9AF7-D131D5F0458A": "Linux root (x86)",
    "4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709": "Linux root (x86-64)",
    "933AC7E1-2EB4-4F13-B844-0E14E2AEF915": "Linux /home",
    "3B8F8425-20E0-4F3B-907F-1A25A76F98E8": "Linux /var",
    "69DAD710-2CE4-4E3C-B16C-21A1D49ABED3": "Linux /tmp",
    "0657FD6D-A4AB-43C4-84E5-0933C84B4F4F": "Linux Swap",
    "E6D6D379-F507-44C2-A23C-238F2A3DF928": "Linux LVM Physical Volume",
    "BC13C2FF-59E6-4262-A537-764DEBDEC4B6": "Linux /boot",
    "B921B045-1DF0-41C3-AF44-4C6F280D3FAE": "Linux root (ARM)",
    "B6FA30DA-92D2-4A9A-96F1-871EC6486200": "Linux root (ARM-64)",

    # === Apple ===
    "48465300-0000-11AA-AA11-00306543ECAC": "Apple APFS Container",
    "7C3457EF-0000-11AA-AA11-00306543ECAC": "Apple APFS Recovery",
    "55465300-0000-11AA-AA11-00306543ECAC": "Apple HFS+",
    
    # === Other ===
    "024DEE41-33E7-11D3-9D69-0008C781F39F": "MBR partition scheme",
}

# MBR (legacy) partition type codes → human name
MBR_TYPE_MAP = {
    0x00: "Empty",
    0x07: "NTFS / exFAT / HPFS",
    0x0B: "FAT32 (CHS)",
    0x0C: "FAT32 (LBA)",
    0x27: "Windows Hidden NTFS (Recovery)",
    0x82: "Linux Swap / Solaris",
    0x83: "Linux Filesystem",
    0x8E: "Linux LVM",
    0x05: "Extended",
    0x0F: "Extended (LBA)",
    0xEE: "GPT Protective",
    0xEF: "EFI System Partition",
    0x84: "Intel Rapid Start / Hibernate",
}

# === Windows often returns these plain English strings instead of GUIDs ===
TEXT_BASED_GPT_TYPES = {
    "SYSTEM": "EFI System Partition",
    "BASIC": "Basic Data Partition (NTFS/exFAT)",
    "RESERVED": "Microsoft Reserved Partition (MSR)",
    "RECOVERY": "Windows Recovery Environment",
    "MSR": "Microsoft Reserved Partition (MSR)",
    "LDM METADATA": "LDM Metadata (Dynamic Disks)",
    "LDM DATA": "LDM Data (Dynamic Disks)",
}

# Legacy reference for backward compatibility
GPT_PARTITION_TYPES = PARTITION_TYPE_GUIDS


def check_admin_privileges() -> bool:
    """Check if the script is running with administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False


@dataclass
class PartitionInfo:
    """Data class representing partition information"""
    device: str
    mountpoint: str
    fstype: str
    opts: str
    total_size: int
    used_size: int
    free_size: int
    percent_used: float
    is_boot: bool = False
    is_system: bool = False
    is_swap: bool = False
    is_linux: bool = False
    partition_type: str = "Unknown"
    volume_label: str = ""
    disk_index: int = 0
    partition_index: int = 0
    # Enhanced forensic attributes
    partition_guid: str = ""
    partition_style: str = "Unknown"  # MBR or GPT
    is_hidden: bool = False
    is_active: bool = False
    is_efi_system: bool = False
    partition_offset: int = 0
    partition_length: int = 0
    disk_signature: str = ""
    volume_serial: str = ""
    # Bootable device attributes
    is_removable: bool = False
    is_usb: bool = False
    is_bootable: bool = False
    
    def to_dict(self) -> dict:
        """Convert to dictionary for easy serialization"""
        return asdict(self)


@dataclass
class DiskInfo:
    """Data class representing physical disk information"""
    disk_index: int
    size: int
    model: str
    interface_type: str
    partitions: List[PartitionInfo]
    # Enhanced forensic attributes
    partition_style: str = "Unknown"  # MBR or GPT
    boot_mode: str = "Unknown"  # BIOS or UEFI
    disk_signature: str = ""
    disk_guid: str = ""
    serial_number: str = ""
    firmware_type: str = "Unknown"
    # Bootable device attributes
    is_removable: bool = False
    is_usb: bool = False
    media_type: str = "Unknown"
    is_bootable: bool = False
    
    def to_dict(self) -> dict:
        """Convert to dictionary for easy serialization"""
        data = asdict(self)
        data['partitions'] = [p.to_dict() for p in self.partitions]
        return data


class PartitionAnalyzer:
    """
    Analyzes disk partitions and volumes on Windows systems.
    
    This class provides methods to:
    - Enumerate all partitions
    - Detect boot and system partitions
    - Identify swap/pagefile locations
    - Detect Linux partitions (ext4, swap, LVM, etc.)
    - Gather disk usage statistics
    - Detect UEFI/BIOS boot mode
    - Identify bootable USB/removable devices
    """
    
    def __init__(self):
        """Initialize the partition analyzer"""
        self.wmi_available = WMI_AVAILABLE
        self.wmi_connection = None
        self.is_admin = check_admin_privileges()
        
        if not self.is_admin:
            print("[Partition Analyzer] WARNING: Not running with administrator privileges.")
            print("[Partition Analyzer] Some features may be limited. Run as administrator for full functionality.")
        
        self.boot_mode = self._detect_boot_mode()
        
        if self.wmi_available:
            try:
                self.wmi_connection = wmi.WMI()
            except Exception as e:
                print(f"[Partition Analyzer] Failed to initialize WMI: {e}")
                self.wmi_available = False
    
    def get_all_partitions(self) -> List[PartitionInfo]:
        """
        Get information about all partitions on the system.
        
        Returns:
            List of PartitionInfo objects containing partition details
        """
        partitions = []
        
        # Get basic partition info from psutil
        for partition in psutil.disk_partitions(all=True):
            try:
                # Get usage statistics
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                except (PermissionError, OSError, FileNotFoundError):
                    # Handle cases where usage cannot be retrieved (e.g. CD-ROM with no disc)
                    usage = type('obj', (object,), {'total': 0, 'used': 0, 'free': 0, 'percent': 0.0})
                
                # Create partition info object
                part_info = PartitionInfo(
                    device=partition.device,
                    mountpoint=partition.mountpoint,
                    fstype=partition.fstype,
                    opts=partition.opts,
                    total_size=usage.total,
                    used_size=usage.used,
                    free_size=usage.free,
                    percent_used=usage.percent
                )
                
                # Detect partition characteristics
                part_info.is_boot = self._is_boot_partition(partition)
                part_info.is_system = self._is_system_partition(partition)
                part_info.is_swap = self._is_swap_partition(partition)
                part_info.is_linux = self._is_linux_partition(partition)
                
                # === NEW: Windows hibernation & modern swap detection (for mounted NTFS) ===
                if part_info.mountpoint and part_info.mountpoint.endswith(":\\") and os.path.exists(part_info.mountpoint):
                    try:
                        # Windows 10/11 uses swapfile.sys (virtual swap)
                        if os.path.exists(os.path.join(part_info.mountpoint, "swapfile.sys")):
                            part_info.is_swap = True
                            if "Basic" in part_info.partition_type or part_info.partition_type == "Unknown":
                                part_info.partition_type = "Windows Swap Partition (swapfile.sys)"
                            if not part_info.volume_label:
                                part_info.volume_label = "Windows Virtual Swap"

                        # hiberfil.sys = hibernation file = effectively swap when system hibernates
                        if os.path.exists(os.path.join(part_info.mountpoint, "hiberfil.sys")):
                            part_info.is_swap = True
                            if "Hibernation" not in part_info.partition_type:
                                part_info.partition_type += " (Hibernation)"
                    except (PermissionError, OSError, FileNotFoundError):
                        pass
                
                # Get additional Windows-specific info if WMI is available
                if self.wmi_available:
                    wmi_info = self._get_wmi_partition_info(partition.device)
                    if wmi_info:
                        part_info.partition_type = wmi_info.get('type', 'Unknown')
                        part_info.volume_label = wmi_info.get('label', '')
                        part_info.disk_index = wmi_info.get('disk_index', 0)
                        part_info.partition_index = wmi_info.get('partition_index', 0)
                        part_info.partition_guid = wmi_info.get('guid', '')
                        part_info.partition_style = wmi_info.get('partition_style', 'Unknown')
                        part_info.is_active = wmi_info.get('is_active', False)
                        part_info.is_efi_system = wmi_info.get('is_efi_system', False)
                        part_info.partition_offset = wmi_info.get('offset', 0)
                        part_info.partition_length = wmi_info.get('length', 0)
                        part_info.disk_signature = wmi_info.get('disk_signature', '')
                        part_info.volume_serial = wmi_info.get('volume_serial', '')
                        
                        # Do NOT mark the active Windows system drive as hidden
                        is_hidden_from_wmi = wmi_info.get('is_hidden', False)
                        part_info.is_hidden = is_hidden_from_wmi and partition.mountpoint.lower() != 'c:\\'
                
                partitions.append(part_info)
            except Exception as e:
                print(f"[Partition Analyzer] Error processing {partition.device}: {e}")
                continue
        
        return partitions
    
    def _get_disks_powershell(self, partitions: List[PartitionInfo]) -> List[DiskInfo]:
        """
        Get disk information using PowerShell when WMI is unavailable.
        """
        print("[Partition Analyzer] Attempting PowerShell fallback for disk info...")
        disks = []
        try:
            # Get Disk Info
            cmd = "Get-Disk | Select-Object Number, FriendlyName, Size, PartitionStyle, BootFromDisk, SerialNumber, BusType, OperationalStatus, Signature | ConvertTo-Json"
            result = subprocess.run(["powershell", "-Command", cmd], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            
            if result.returncode != 0 or not result.stdout.strip():
                return []
                
            try:
                disk_data = json.loads(result.stdout)
                if isinstance(disk_data, dict):
                    disk_data = [disk_data]
            except json.JSONDecodeError:
                return []
                
            for d in disk_data:
                idx = d.get('Number', 0)
                model = d.get('FriendlyName', 'Unknown')
                size = d.get('Size', 0)
                style = d.get('PartitionStyle', 'Unknown')
                is_boot = d.get('BootFromDisk', False)
                serial = d.get('SerialNumber', '')
                bus = d.get('BusType', 'Unknown')
                
                # Get disk signature
                sig_val = d.get('Signature', 0)
                disk_signature = ""
                if sig_val:
                    try:
                        disk_signature = hex(int(sig_val))
                    except:
                        disk_signature = str(sig_val)
                
                # List to hold partitions for THIS disk
                disk_partitions = []
                
                # Get Partition Info from PowerShell to enrich partitions and assign them to this disk
                try:
                    p_cmd = f"Get-Partition -DiskNumber {idx} | Select-Object PartitionNumber, DriveLetter, Type, GptType, Offset, Size, IsHidden, IsActive | ConvertTo-Json"
                    p_res = subprocess.run(["powershell", "-Command", p_cmd], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    
                    if p_res.returncode == 0 and p_res.stdout.strip():
                        try:
                            p_data = json.loads(p_res.stdout)
                            if isinstance(p_data, dict):
                                p_data = [p_data]
                                
                            for pd in p_data:
                                p_num = pd.get('PartitionNumber', 0)
                                p_offset = pd.get('Offset', 0)
                                p_size = pd.get('Size', 0)
                                p_type = pd.get('Type', 'Unknown')
                                p_gpt = pd.get('GptType', '')
                                p_drive = pd.get('DriveLetter', '')
                                p_hidden = pd.get('IsHidden', False)
                                p_active = pd.get('IsActive', False)
                                
                                # Match with existing partitions from psutil
                                matched = False
                                for p in partitions:
                                    # Match by drive letter if available
                                    if p_drive and p.mountpoint.startswith(f"{p_drive}:"):
                                        matched = True
                                        # Update partition info
                                        p.disk_index = idx # CRITICAL: Assign correct disk index
                                        p.partition_index = p_num
                                        p.partition_type = p_type
                                        p.partition_style = style
                                        p.partition_guid = p_gpt
                                        p.partition_offset = p_offset
                                        p.is_hidden = p_hidden
                                        p.is_active = p_active
                                        p.disk_signature = disk_signature
                                        
                                        # Add to this disk's list
                                        disk_partitions.append(p)
                                        break
                                
                                if not matched:
                                    # Add unmounted/system partition found by PowerShell
                                    # Create new PartitionInfo for it
                                    
                                    # Determine type/flags
                                    is_efi = "System" in p_type or "EFI" in p_type
                                    is_msr = "Reserved" in p_type
                                    is_recovery = "Recovery" in p_type
                                    is_swap = False
                                    
                                    # === APPLY SAME OVERRIDE LOGIC AS WMI PATH ===
                                    # Calculate size in MB for heuristics
                                    size_mb = p_size / (1024 * 1024) if p_size > 0 else 0
                                    
                                    # First, check GPT GUID for specific partition types
                                    is_linux = False
                                    if p_gpt:
                                        p_gpt_upper = str(p_gpt).upper()
                                        # Intel Rapid Start GUID
                                        if "D3BFE2DE-3DAF-11DF-BA40-E3A556D89593" in p_gpt_upper:
                                            p_type = "Intel Rapid Start (Hibernate)"
                                            is_swap = True
                                        # Windows Recovery GUID
                                        elif "DE94BBA4-06D1-4D40-A16A-BFD50179D6AC" in p_gpt_upper:
                                            p_type = "Windows Recovery Environment"
                                            is_recovery = True
                                        # Microsoft Reserved GUID
                                        elif "E3C9E316-0B5C-4DB8-817D-F92DF00215AE" in p_gpt_upper:
                                            p_type = "Microsoft Reserved Partition (MSR)"
                                            is_msr = True
                                        # Linux Filesystem GUID
                                        elif "0FC63DAF-8483-4772-8E79-3D69D8477DE4" in p_gpt_upper:
                                            p_type = "Linux Filesystem (ext4/generic)"
                                            is_linux = True
                                        # Linux Swap GUID
                                        elif "0657FD6D-A4AB-43C4-84E5-0933C84B4F4F" in p_gpt_upper:
                                            p_type = "Linux Swap"
                                            is_swap = True
                                            is_linux = True
                                        # Linux LVM GUID
                                        elif "E6D6D379-F507-44C2-A23C-238F2A3DF928" in p_gpt_upper:
                                            p_type = "Linux LVM Physical Volume"
                                            is_linux = True
                                    
                                    # Override "Unknown" or "Recovery" partitions based on size (Intel Rapid Start / Swap detection)
                                    # Use centralized swap detection helper
                                    p_type, is_swap = self._detect_swap_by_size(size_mb, p_type)
                                    
                                    # Very small partitions (< 100MB) at the start are often MSR
                                    if size_mb < 100 and p_offset < 1024 * 1024 * 1024 and p_type == "Unknown":  # First 1GB
                                        p_type = "Microsoft Reserved Partition (MSR)"
                                        is_msr = True
                                    
                                    print(f"[DEBUG PowerShell] Creating partition {p_num}: type='{p_type}', size={size_mb:.1f}MB, is_swap={is_swap}, guid={p_gpt[:20] if p_gpt else 'None'}...")

                                    
                                    new_p = PartitionInfo(
                                        device=f"\\\\.\\Disk{idx}Partition{p_num}",
                                        mountpoint=f"{p_drive}:\\" if p_drive else "",
                                        fstype="FAT32" if is_efi else "NTFS", # Assumption based on type
                                        opts="",
                                        total_size=p_size,
                                        used_size=0, # Can't easily get used size for unmounted
                                        free_size=0,
                                        percent_used=0.0,
                                        is_boot=p_active,
                                        is_system=False,
                                        is_swap=is_swap,  # Use the value set by override logic
                                        is_linux=is_linux or "IFS" in p_type,  # Use GUID detection or IFS check
                                        partition_type=p_type,
                                        disk_index=idx,
                                        partition_index=p_num,
                                        partition_guid=p_gpt,
                                        partition_style=style,
                                        is_hidden=p_hidden,
                                        is_active=p_active,
                                        is_efi_system=is_efi,
                                        partition_offset=p_offset,
                                        partition_length=p_size,
                                        disk_signature=disk_signature
                                    )
                                    disk_partitions.append(new_p)
                                    
                        except Exception as e:
                            print(f"[Debug] Error parsing partition JSON: {e}")
                except Exception as e:
                    print(f"[Debug] Error getting partitions for disk {idx}: {e}")

                disk = DiskInfo(
                    disk_index=idx,
                    size=size,
                    model=model,
                    interface_type=bus,
                    partitions=disk_partitions,
                    partition_style=style,
                    boot_mode=self.boot_mode,
                    serial_number=serial,
                    is_bootable=is_boot,
                    disk_signature=disk_signature
                )
                disks.append(disk)
                
        except Exception as e:
            print(f"[Partition Analyzer] PowerShell fallback failed: {e}")
            
        return disks

    def get_disks_with_partitions(self) -> List[DiskInfo]:
        """
        Get information about all physical disks and their partitions.
        
        Returns:
            List of DiskInfo objects containing disk and partition details
        """
        disks = []
        partitions = self.get_all_partitions()
        
        if not self.wmi_available:
            # If WMI is not available, try PowerShell first
            disks = self._get_disks_powershell(partitions)
            if disks:
                return disks
                
            # Fallback to single virtual disk with all partitions
            disk = DiskInfo(
                disk_index=0,
                size=sum(p.total_size for p in partitions),
                model="Unknown",
                interface_type="Unknown",
                partitions=partitions
            )
            disks.append(disk)
            return disks
        
        # Get physical disk information from WMI
        try:
            wmi_disks = self.wmi_connection.Win32_DiskDrive()
            
            # Create a mapping of device paths to disk indices
            device_to_disk_index = {}
            
            # Method: Parse Win32_DiskPartition Name/DeviceID directly
            # This avoids flaky association queries and OLE errors
            try:
                all_wmi_partitions = self.wmi_connection.Win32_DiskPartition()
                
                for wpart in all_wmi_partitions:
                    # Format is usually "Disk #0, Partition #1"
                    name = wpart.Name if hasattr(wpart, 'Name') else wpart.DeviceID
                    disk_index = -1
                    
                    if 'Disk #' in name:
                        try:
                            disk_index = int(name.split('Disk #')[1].split(',')[0])
                        except (ValueError, IndexError, AttributeError):
                            pass
                    
                    if disk_index >= 0:
                        # Try to map logical drives
                        try:
                            logical_disks = self.wmi_connection.query(
                                f"ASSOCIATORS OF {{Win32_DiskPartition.DeviceID='{wpart.DeviceID}'}} "
                                f"WHERE AssocClass=Win32_LogicalDiskToPartition"
                            )
                            for ld in logical_disks:
                                device_path = f"{ld.DeviceID}\\"
                                device_to_disk_index[device_path] = disk_index
                                device_to_disk_index[ld.DeviceID] = disk_index
                        except:
                            pass
                            
            except Exception as e:
                print(f"[Partition Analyzer] Error in partition mapping: {e}")

            # Update partition disk indices based on mapping
            for partition in partitions:
                device_key = partition.device.rstrip('\\')
                if device_key in device_to_disk_index:
                    partition.disk_index = device_to_disk_index[device_key]
                elif partition.device in device_to_disk_index:
                    partition.disk_index = device_to_disk_index[partition.device]
            
            # Now create disk objects with correctly associated partitions
            for idx, wmi_disk in enumerate(wmi_disks):
                # Get partitions for this disk (from psutil)
                disk_partitions = [p for p in partitions if p.disk_index == idx]
                
                # Enhanced: Add partitions found in WMI but missed by psutil (unmounted/Linux)
                try:
                    # Find WMI partitions for this disk index
                    disk_wmi_parts = []
                    if 'all_wmi_partitions' in locals():
                        for wpart in all_wmi_partitions:
                            # Parse disk index again
                            name = wpart.Name if hasattr(wpart, 'Name') else wpart.DeviceID
                            d_idx = -1
                            if 'Disk #' in name:
                                try:
                                    d_idx = int(name.split('Disk #')[1].split(',')[0])
                                except (ValueError, IndexError, AttributeError):
                                    pass
                            
                            if d_idx == idx:
                                disk_wmi_parts.append(wpart)
                    
                    for wpart in disk_wmi_parts:
                        # Check if this WMI partition corresponds to one we already have
                        matched = False
                        wpart_index = int(wpart.Index) if hasattr(wpart, 'Index') and wpart.Index is not None else -1
                        wpart_offset = int(wpart.StartingOffset) if hasattr(wpart, 'StartingOffset') and wpart.StartingOffset is not None else -1
                        
                        for p in disk_partitions:
                            if p.partition_index == wpart_index or \
                               (p.partition_offset > 0 and abs(p.partition_offset - wpart_offset) < 4096):
                                matched = True
                                break
                        
                        if not matched:
                            # This is a non-Windows/Unmounted partition
                            
                            # Determine type from GUID or Type field
                            part_type = "Unknown"
                            is_linux = False
                            is_swap = False
                            is_efi = False
                            fstype = "Unknown"
                            guid = ""
                            
                            # Use comprehensive partition type resolver
                            resolved = self._resolve_partition_type(wpart)
                            part_type = resolved["type"]
                            fstype = resolved["fstype"]
                            guid = resolved["guid"]
                            is_linux = resolved["is_linux"]
                            is_swap = resolved["is_swap"]
                            is_efi = resolved["is_efi"]
                            
                            # === DEBUG: Log initial resolved type ===
                            print(f"[DEBUG] Partition {wpart_index} initial resolve: type='{part_type}', guid={guid[:20] if guid else 'None'}...")
                            
                            # Additional heuristics based on size and position
                            size = 0
                            if hasattr(wpart, 'Size') and wpart.Size is not None:
                                try:
                                    size = int(wpart.Size)
                                except:
                                    pass
                            
                            wpart_offset = int(wpart.StartingOffset) if hasattr(wpart, 'StartingOffset') and wpart.StartingOffset is not None else -1
                            
                            # METHOD 1: PowerShell Detection (Windows API)
                            # If type is still unknown, try PowerShell which often has better info than WMI
                            if part_type == "Unknown" and self.is_admin:
                                try:
                                    # Map WMI partition index to disk/partition numbers
                                    # WMI Name format: "Disk #0, Partition #1" (Partition # is 0-based index usually, but PowerShell uses 1-based)
                                    # Actually, let's try to match by Offset which is reliable
                                    ps_cmd = f"Get-Partition -DiskNumber {idx} | Where-Object {{$_.Offset -eq {wpart_offset}}} | Select-Object -ExpandProperty Type"
                                    
                                    import subprocess
                                    # Add timeout to prevent hanging (e.g., if AV blocks PowerShell)
                                    result = subprocess.run(
                                        ["powershell", "-Command", ps_cmd], 
                                        capture_output=True, 
                                        text=True, 
                                        creationflags=subprocess.CREATE_NO_WINDOW,
                                        timeout=5  # 5 second timeout
                                    )
                                    if result.returncode == 0:
                                        ps_type = result.stdout.strip()
                                        if ps_type:
                                            # PowerShell returns types like "Basic", "Recovery", "System", "IFS" (Installable File System - often Linux)
                                            if "IFS" in ps_type or "Installable" in ps_type:
                                                part_type = "Linux Filesystem (Likely)"
                                                is_linux = True
                                                fstype = "ext4" # Assumption for IFS
                                            elif "Recovery" in ps_type:
                                                part_type = "Recovery Partition"
                                                fstype = "NTFS"
                                            elif "System" in ps_type:
                                                part_type = "EFI System Partition"
                                                is_efi = True
                                                fstype = "FAT32"
                                            elif "Reserved" in ps_type:
                                                part_type = "Microsoft Reserved"
                                except (subprocess.TimeoutExpired, Exception) as e:
                                    print(f"[Debug] PowerShell detection failed: {e}")

                            # METHOD 2: Raw Disk Signature Scanning (Low-level)
                            # If still unknown, suspected Linux, OR "Recovery" (to check if it's actually Swap/Rapid Start), read the boot sectors
                            if (part_type == "Unknown" or is_linux or "Recovery" in part_type) and wpart_offset >= 0:
                                # Check admin privileges before attempting raw disk access
                                if not self.is_admin:
                                    pass
                                else:
                                    try:
                                        disk_path = r"\\.\PhysicalDrive" + str(idx)
                                        print(f"[Debug] Attempting raw scan for Partition {wpart_index} at offset {wpart_offset}")
                                        
                                        # Use class constant for filesystem signatures
                                        FS_SIGNATURES = self._FS_SIGNATURES
                                        
                                        # Safely open disk with FILE_SHARE_READ to avoid conflicts
                                        disk_handle = None
                                        lock_acquired = False
                                        try:
                                            if WIN32FILE_AVAILABLE:
                                                # Use win32file for safer access with sharing mode
                                                try:
                                                    disk_handle = win32file.CreateFile(
                                                        disk_path,
                                                        win32file.GENERIC_READ,
                                                        win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE,
                                                        None,
                                                        win32file.OPEN_EXISTING,
                                                        0,
                                                        None
                                                    )
                                                    
                                                    # Attempt to lock the region we're about to read
                                                    # This prevents race conditions with other processes
                                                    try:
                                                        # Lock the partition region (non-blocking)
                                                        # LockFile(handle, offset_low, offset_high, length_low, length_high)
                                                        # We'll lock a small region for the signature check
                                                        lock_size = 65536  # 64KB should cover all signatures
                                                        offset_low = wpart_offset & 0xFFFFFFFF
                                                        offset_high = (wpart_offset >> 32) & 0xFFFFFFFF
                                                        
                                                        win32file.LockFile(
                                                            disk_handle,
                                                            offset_low,
                                                            offset_high,
                                                            lock_size & 0xFFFFFFFF,
                                                            (lock_size >> 32) & 0xFFFFFFFF
                                                        )
                                                        lock_acquired = True
                                                    except pywintypes.error:
                                                        # Lock failed - continue anyway but log it
                                                        # This is not critical, just a safety measure
                                                        print(f"[Debug] Could not lock disk region at offset {wpart_offset} (non-critical)")
                                                    
                                                    # Iterate through signatures with multiple offsets
                                                    for fs_name, sig in FS_SIGNATURES.items():
                                                        for offset in sig['offsets']:
                                                            try:
                                                                # Calculate absolute position
                                                                abs_position = wpart_offset + offset
                                                                
                                                                # Set file pointer with explicit FILE_BEGIN flag
                                                                # This ensures we're seeking from the start of the file
                                                                win32file.SetFilePointer(
                                                                    disk_handle, 
                                                                    abs_position, 
                                                                    win32file.FILE_BEGIN
                                                                )
                                                                
                                                                # Read the magic bytes
                                                                _, data = win32file.ReadFile(disk_handle, len(sig['magic']))
                                                                
                                                                if data == sig['magic']:
                                                                    part_type = sig['type']
                                                                    fstype = sig['fstype']
                                                                    if sig.get('is_linux'):
                                                                        is_linux = True
                                                                    if sig.get('is_swap'):
                                                                        is_swap = True
                                                                    
                                                                    # === INSIDE the raw scan loop, after successful magic match ===
                                                                    if part_type != "Unknown":
                                                                        # If we found a valid filesystem (NTFS, Ext4, etc.), respect it
                                                                        # But if it's NTFS and we thought it was Recovery, keep it as Recovery (don't downgrade to Basic Data)
                                                                        if "NTFS" in sig['type'] and "Recovery" in part_type:
                                                                             part_type = "Recovery Partition (NTFS)"
                                                                             fstype = "NTFS"
                                                                        
                                                                        # If we found Swap, force it
                                                                        if "swap" in fstype.lower():
                                                                            is_swap = True
                                                                            is_linux = True
                                                                        
                                                                        # Handle Apple partitions (for Hackintosh detection)
                                                                        if sig.get('is_apple'):
                                                                            print(f"[Debug] Detected Apple partition: {part_type}")
                                                                        
                                                                    break  # Found a match
                                                            except (pywintypes.error, OSError, IOError) as e:
                                                                # Log specific read errors for debugging
                                                                # print(f"[Debug] Read error at offset {abs_position}: {e}")
                                                                continue
                                                        if part_type != "Unknown":  # Stop if we found a match
                                                            break
                                                except (pywintypes.error, OSError) as e:
                                                    print(f"[!] Cannot open {disk_path} with win32file: {e}")
                                                finally:
                                                    # Always unlock before closing
                                                    if lock_acquired and disk_handle:
                                                        try:
                                                            offset_low = wpart_offset & 0xFFFFFFFF
                                                            offset_high = (wpart_offset >> 32) & 0xFFFFFFFF
                                                            lock_size = 65536
                                                            win32file.UnlockFile(
                                                                disk_handle,
                                                                offset_low,
                                                                offset_high,
                                                                lock_size & 0xFFFFFFFF,
                                                                (lock_size >> 32) & 0xFFFFFFFF
                                                            )
                                                        except pywintypes.error:
                                                            pass  # Unlock failed, but we're closing anyway
                                                    
                                                    if disk_handle:
                                                        win32file.CloseHandle(disk_handle)
                                            else:
                                                # Fallback to basic file I/O
                                                with open(disk_path, "rb") as f:
                                                    for fs_name, sig in FS_SIGNATURES.items():
                                                        for offset in sig['offsets']:
                                                            try:
                                                                f.seek(wpart_offset + offset)
                                                                data = f.read(len(sig['magic']))
                                                                if data == sig['magic']:
                                                                    part_type = sig['type']
                                                                    fstype = sig['fstype']
                                                                    if sig.get('is_linux'):
                                                                        is_linux = True
                                                                    if sig.get('is_swap'):
                                                                        is_swap = True
                                                                    # Handle Apple partitions (for Hackintosh detection)
                                                                    if sig.get('is_apple'):
                                                                        print(f"[Debug] Detected Apple partition: {part_type}")
                                                                    break
                                                            except (OSError, IOError):
                                                                continue
                                                        if part_type != "Unknown":
                                                            break
                                        except (PermissionError, OSError, IOError) as e:
                                            print(f"[!] Cannot open {disk_path}: {e}")
                                            
                                    except Exception as e:
                                        print(f"[Debug] Raw signature scan failed: {e}")

                            # Small partitions at the beginning are often boot/EFI (Heuristic Fallback)
                            if size > 0 and wpart_offset >= 0:
                                size_mb = size / (1024 * 1024)
                                offset_mb = wpart_offset / (1024 * 1024)
                                
                                # EFI partitions are typically 100-500MB at the start
                                if 50 < size_mb < 600 and offset_mb < 1024 and part_type == "Unknown":
                                    if getattr(wpart, 'Bootable', False):
                                        part_type = "Boot Partition"
                                        fstype = "NTFS"
                                
                                # Recovery partitions are typically 450MB-20GB
                                if 400 < size_mb < 20000 and part_type == "Unknown":
                                    part_type = "Recovery Partition"
                                    fstype = "NTFS"
                                    
                                # Bonus: Improve LVM swap detection (8-32GB LVM is likely swap)
                                if is_linux and "LVM" in part_type:
                                    size_gb = size / (1024 * 1024 * 1024)
                                    if 7.5 <= size_gb <= 33: # slightly wider range for safety
                                        part_type += " (Likely Swap)"
                                        is_swap = True

                                # === CRITICAL OVERRIDE: Fix 16GB "Recovery" Partitions ===
                                # Windows often misidentifies Intel Rapid Start / Hibernate partitions as "Recovery"
                                # Use centralized swap detection helper
                                # BUT ONLY if it's NOT a valid NTFS Recovery partition (checked via raw scan above)
                                if "NTFS" not in part_type:
                                    part_type, is_swap = self._detect_swap_by_size(size_mb, part_type)
                            
                            # === DEBUG: Log final partition type before creating object ===
                            print(f"[DEBUG] Creating partition {wpart_index}: type='{part_type}', size={size_mb:.1f}MB, is_swap={is_swap}, guid={guid[:20] if guid else 'None'}...")
                            
                            # Build device path
                            device_path = f"\\\\.\\Disk{idx}Partition{wpart_index}" if wpart_index >= 0 else wpart.DeviceID
                            
                            new_part = PartitionInfo(
                                device=device_path,
                                mountpoint="",  # Not mounted
                                fstype=fstype,
                                opts="",
                                total_size=size,
                                used_size=0,
                                free_size=0,
                                percent_used=0.0,
                                is_boot=getattr(wpart, 'Bootable', False) if hasattr(wpart, 'Bootable') else False,
                                is_system=False,
                                is_swap=is_swap,
                                is_linux=is_linux,
                                partition_type=part_type,
                                disk_index=idx,
                                partition_index=wpart_index,
                                partition_guid=guid,
                                partition_style="GPT" if guid else "MBR",
                                is_hidden=True,
                                is_active=getattr(wpart, 'Bootable', False) if hasattr(wpart, 'Bootable') else False,
                                is_efi_system=is_efi,
                                partition_offset=wpart_offset,
                                partition_length=size
                            )
                            disk_partitions.append(new_part)
                            
                except Exception as e:
                    print(f"[Partition Analyzer] Error checking for unmounted partitions: {e}")
                    # Define fallbacks so script NEVER crashes
                    partition_style = "Unknown"
                    disk_signature = ""
                    disk_guid = ""
                    serial_number = ""
                    firmware_type = "Unknown"
                    media_type = "Unknown"
                    interface_type = "Unknown"
                    pnp_device_id = ""
                    is_removable = False
                    is_usb = False
                    is_bootable = False
                    disk_size = 0
                else:
                    partition_style, disk_signature, disk_guid = self._get_disk_partition_style(idx)
                    serial_number = wmi_disk.SerialNumber if hasattr(wmi_disk, 'SerialNumber') else ""
                    firmware_type = getattr(wmi_disk, 'FirmwareEnvironment', "Unknown")
                    media_type = getattr(wmi_disk, 'MediaType', 'Unknown')
                    interface_type = getattr(wmi_disk, 'InterfaceType', 'Unknown')
                    pnp_device_id = getattr(wmi_disk, 'PNPDeviceID', '')
                    is_removable = 'removable' in str(media_type).lower() or 'USB' in str(interface_type).upper()
                    is_usb = 'USB' in str(interface_type).upper() or 'USB' in str(pnp_device_id).upper()
                    is_bootable = self._is_disk_bootable(wmi_disk, disk_partitions)
                    disk_size = int(wmi_disk.Size) if hasattr(wmi_disk, 'Size') and wmi_disk.Size else 0

                # FINAL TRUTH ENFORCEMENT — THIS IS THE HOLY GRAIL
                has_gpt_evidence = any(
                    p.partition_guid or 
                    p.partition_guid == "TEXT-MAPPING" or 
                    "EFI" in p.partition_type or 
                    "GPT" in str(getattr(p, 'partition_style', '')) or
                    p.is_efi_system
                    for p in disk_partitions
                )
                final_style = "GPT" if has_gpt_evidence else "MBR"
                
                # Force correct style on EVERY partition and the disk
                for p in disk_partitions:
                    p.partition_style = final_style
                
                # Fix C: drive - never Unknown
                c_drive = next((p for p in disk_partitions if p.mountpoint == "C:\\"), None)
                if c_drive and c_drive.partition_type in ["Unknown", ""]:
                    c_drive.partition_type = "Basic Data Partition (NTFS/exFAT)"
                    c_drive.fstype = "NTFS"
                    c_drive.is_system = True
                    c_drive.is_hidden = False

                # Linux detection fallback (your raw scan sometimes fails due to AV/blocking)
                for p in disk_partitions:
                    if p.partition_type == "Unknown":
                        size_gb = p.total_size / (1024 * 1024 * 1024)
                        # Swap partitions are typically 7.5GB - 20GB
                        if 7.5 <= size_gb <= 20:
                            p.partition_type = "Linux Swap"
                            p.fstype = "swap"
                            p.is_swap = True
                            p.is_linux = True
                        # Large partitions (> 30GB) are likely Linux filesystems
                        elif size_gb > 30:
                            p.partition_type = "Linux Filesystem (ext4)"
                            p.fstype = "ext4"
                            p.is_linux = True
                
                # Update partition bootable flags and disk signature
                for part in disk_partitions:
                    part.is_removable = is_removable
                    part.is_usb = is_usb
                    # A partition is bootable if it's marked as boot, EFI system, or active (MBR)
                    part.is_bootable = part.is_boot or part.is_efi_system or part.is_active
                    # Propagate disk signature to partition
                    part.disk_signature = disk_signature

                disk = DiskInfo(
                    disk_index=idx,
                    size=disk_size,
                    model=wmi_disk.Model if hasattr(wmi_disk, 'Model') else "Unknown",
                    interface_type=interface_type,
                    partitions=disk_partitions,
                    partition_style=final_style,
                    boot_mode=self.boot_mode,
                    disk_signature=disk_signature,
                    disk_guid=disk_guid,
                    serial_number=serial_number or "",
                    firmware_type=firmware_type,
                    is_removable=is_removable,
                    is_usb=is_usb,
                    media_type=str(media_type),
                    is_bootable=is_bootable
                )
                disks.append(disk)
                
        except Exception as e:
            print(f"[Partition Analyzer] Error getting disk information: {e}")
            import traceback
            traceback.print_exc()
            
            # Try PowerShell fallback
            disks = self._get_disks_powershell(partitions)
            if disks:
                return disks
                
            # Fallback to single virtual disk
            disk = DiskInfo(
                disk_index=0,
                size=sum(p.total_size for p in partitions),
                model="Unknown",
                interface_type="Unknown",
                partitions=partitions
            )
            disks.append(disk)
        
        return disks
    
    def _is_boot_partition(self, partition) -> bool:
        """
        Detect if a partition is a boot partition.
        
        Checks for:
        - Windows boot files (bootmgr, BCD)
        - EFI boot files
        - Boot flag in partition options
        
        Args:
            partition: psutil partition object
            
        Returns:
            True if partition is a boot partition
        """
        # Check partition options for boot flag
        if 'boot' in partition.opts.lower():
            return True
        
        # Check for Windows boot files
        try:
            boot_files = ['bootmgr', 'BOOTMGR', 'Boot', 'boot']
            for boot_file in boot_files:
                boot_path = os.path.join(partition.mountpoint, boot_file)
                if os.path.exists(boot_path):
                    return True
            
            # Check for EFI boot partition
            efi_path = os.path.join(partition.mountpoint, 'EFI')
            if os.path.exists(efi_path):
                return True
                
        except (PermissionError, OSError):
            pass
        
        return False
    
    def _is_system_partition(self, partition) -> bool:
        """
        Detect if a partition is the Windows system partition.
        
        Args:
            partition: psutil partition object
            
        Returns:
            True if partition contains Windows system files
        """
        try:
            # Check for Windows directory
            windows_path = os.path.join(partition.mountpoint, 'Windows')
            if os.path.exists(windows_path):
                # Verify it's actually a Windows installation
                system32_path = os.path.join(windows_path, 'System32')
                if os.path.exists(system32_path):
                    return True
        except (PermissionError, OSError):
            pass
        
        return False
    
    def _is_swap_partition(self, partition) -> bool:
        """
        Detect if a partition contains the Windows pagefile (swap).
        
        Args:
            partition: psutil partition object
            
        Returns:
            True if partition contains pagefile.sys
        """
        try:
            # Check for pagefile.sys
            pagefile_path = os.path.join(partition.mountpoint, 'pagefile.sys')
            if os.path.exists(pagefile_path):
                return True
            
            # Check for swapfile.sys (Windows 8+)
            swapfile_path = os.path.join(partition.mountpoint, 'swapfile.sys')
            if os.path.exists(swapfile_path):
                return True
                
        except (PermissionError, OSError):
            pass
        
        return False
    
    # Filesystem signature database for raw disk scanning
    _FS_SIGNATURES = {
        'Ext2/3/4': {'offsets': [1080], 'magic': b'\x53\xEF', 'type': 'Linux Filesystem (ext2/3/4)', 'fstype': 'ext4', 'is_linux': True},
        'Btrfs': {'offsets': [65600, 67108864], 'magic': b'_BHRfS_M', 'type': 'Linux Filesystem (Btrfs)', 'fstype': 'btrfs', 'is_linux': True},
        'XFS': {'offsets': [0], 'magic': b'XFSB', 'type': 'Linux Filesystem (XFS)', 'fstype': 'xfs', 'is_linux': True},
        'ReiserFS': {'offsets': [65588], 'magic': b'ReIsEr2Fs', 'type': 'Linux Filesystem (ReiserFS)', 'fstype': 'reiserfs', 'is_linux': True},
        'SwapNew': {'offsets': [4086], 'magic': b'SWAPSPACE2', 'type': 'Linux Swap', 'fstype': 'swap', 'is_linux': True, 'is_swap': True},
        'SwapOld': {'offsets': [4086], 'magic': b'SWAP-SPACE', 'type': 'Linux Swap', 'fstype': 'swap', 'is_linux': True, 'is_swap': True},
        'LVM2': {'offsets': [536], 'magic': b'LVM2 001', 'type': 'Linux LVM Physical Volume', 'fstype': 'linux-lvm', 'is_linux': True},
        'LVM2_Swap': {'offsets': [512], 'magic': b'LABELONE', 'type': 'Linux LVM (Possible Swap)', 'fstype': 'linux-lvm', 'is_linux': True},
        'LUKS': {'offsets': [0], 'magic': b'LUKS\xba\xbe', 'type': 'Linux Encrypted (LUKS)', 'fstype': 'luks', 'is_linux': True},
        'LinuxRAID': {'offsets': [4096], 'magic': b'\xfc\x4e\x2b\xa9', 'type': 'Linux RAID Member', 'fstype': 'linux_raid_member', 'is_linux': True},
        'NTFS': {'offsets': [3], 'magic': b'NTFS    ', 'type': 'Basic Data Partition (NTFS)', 'fstype': 'ntfs', 'is_linux': False},
        'BitLocker': {'offsets': [3], 'magic': b'-FVE-FS-', 'type': 'BitLocker Encrypted', 'fstype': 'bitlocker', 'is_linux': False},
        'ReFS': {'offsets': [0x30, 0x10000], 'magic': b'ReFS', 'type': 'Resilient File System (ReFS)', 'fstype': 'refs', 'is_linux': False},
        'ZFS': {'offsets': [0], 'magic': b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00', 'type': 'ZFS Pool', 'fstype': 'zfs', 'is_linux': False},
        # Enhanced Apple partition detection
        'APFS': {'offsets': [0], 'magic': b'NXSB', 'type': 'Apple APFS Container', 'fstype': 'apfs', 'is_linux': False, 'is_apple': True},
        'APFS_Alt': {'offsets': [32], 'magic': b'NXSB', 'type': 'Apple APFS Container', 'fstype': 'apfs', 'is_linux': False, 'is_apple': True},  # Alternative offset
        'HFS+': {'offsets': [1024], 'magic': b'H+', 'type': 'Apple HFS+', 'fstype': 'hfsplus', 'is_linux': False, 'is_apple': True},
        'HFS+_Wrapper': {'offsets': [1024], 'magic': b'HX', 'type': 'Apple HFS+ Wrapper (Hackintosh/Hybrid)', 'fstype': 'hfsplus', 'is_linux': False, 'is_apple': True},  # HFS+ wrapper for APFS
        'HFS': {'offsets': [1024], 'magic': b'BD', 'type': 'Apple HFS (Legacy)', 'fstype': 'hfs', 'is_linux': False, 'is_apple': True},
        'ISO9660': {'offsets': [32769], 'magic': b'CD001', 'type': 'ISO9660 (Optical)', 'fstype': 'iso9660', 'is_linux': False},
    }
    
    def _detect_swap_by_size(self, size_mb: float, current_type: str) -> Tuple[str, bool]:
        """
        Detect swap/hibernate partitions based on size heuristics.
        
        This method consolidates the duplicate swap detection logic that appears
        in both PowerShell and WMI code paths.
        
        Args:
            size_mb: Partition size in megabytes
            current_type: Current partition type string
            
        Returns:
            Tuple of (partition_type, is_swap)
        """
        # Only apply size-based detection to Unknown or Recovery partitions
        if current_type not in ["Unknown", "Recovery Partition"] and "Recovery" not in current_type:
            return (current_type, False)
        
        # 8GB range (7.5 - 8.5 GB) - Common swap size
        if 7680 <= size_mb <= 8704:
            return ("Swap/Hibernate Partition (8GB)", True)
        
        # 16GB range (15000 - 17000 MB) - Intel Rapid Start / Hibernate
        elif 15000 <= size_mb <= 17000:
            return ("Intel Rapid Start (Hibernate)", True)
        
        # 32GB range (31000 - 34000 MB) - Large swap partition
        elif 31000 <= size_mb <= 34000:
            return ("Swap/Hibernate Partition (32GB)", True)
        
        # Recovery partitions are typically 450MB-20GB
        elif 400 < size_mb < 20000 and current_type == "Unknown":
            return ("Recovery Partition", False)
        
        # Very small partitions (< 100MB) at the start are often MSR
        # (This check requires offset, so it's handled separately in the calling code)
        
        return (current_type, False)
    
    def _resolve_partition_type(self, wpart) -> dict:
        """
        Comprehensive partition type resolution using GPT GUIDs, MBR codes, and heuristics.
        
        Returns a dict with type, fstype, is_linux, is_swap, is_efi, guid
        """
        result = {
            "type": "Unknown",
            "fstype": "Unknown",
            "is_linux": False,
            "is_swap": False,
            "is_efi": False,
            "guid": ""
        }

        # === NEW: Handle plain text types like "GPT: System" or just "Basic" ===
        for field in ['Type', 'DiskPartitionType']:
            if hasattr(wpart, field) and getattr(wpart, field):
                val = str(getattr(wpart, field)).upper().replace("GPT:", "").replace("MBR:", "").strip()
                
                # Special case: "Installable File System" (IFS) = Basic Data Partition
                if "INSTALLABLE FILE SYSTEM" in val or val == "IFS":
                    result["type"] = "Basic Data Partition (NTFS/exFAT)"
                    result["guid"] = "TEXT-MAPPING"
                    result["fstype"] = "Unknown"  # Will be determined by actual filesystem
                    return result
                
                # Check plain text mappings - use startswith for flexibility
                for text, name in TEXT_BASED_GPT_TYPES.items():
                    # Match if the key is at the start of the value (handles "BASIC DATA", "BASIC", etc.)
                    if val.startswith(text) or text in val:
                        result["type"] = name
                        result["guid"] = "TEXT-MAPPING"
                        if "EFI" in name:
                            result["is_efi"] = True
                            result["fstype"] = "FAT32"
                        elif "BASIC" in text or "DATA" in name:
                            result["fstype"] = "Unknown"  # Will be determined by actual filesystem
                        return result

        # 1. Try GPT GUID first (most reliable)
        for field in ['Type', 'DiskPartitionType']:
            if hasattr(wpart, field) and getattr(wpart, field):
                val = str(getattr(wpart, field)).upper().replace("GPT:", "").replace("MBR:", "").strip()
                for guid, name in PARTITION_TYPE_GUIDS.items():
                    if guid.upper() in val:
                        result["type"] = name
                        result["guid"] = guid
                        if "Linux" in name:
                            result["is_linux"] = True
                        if "Swap" in name or "Hibernate" in name or "Rapid Start" in name:
                            result["is_swap"] = True
                            result["fstype"] = "swap"
                        if "EFI" in name:
                            result["is_efi"] = True
                            result["fstype"] = "FAT32"
                        elif "Windows" in name or "Recovery" in name or "Basic" in name:
                            result["fstype"] = "NTFS"
                        elif result["is_linux"] and not result["is_swap"]:
                            result["fstype"] = "ext4"
                        return result

        # 2. MBR numeric type (WMI sometimes only gives 0x07, 0x27, etc.)
        if hasattr(wpart, 'Type') and wpart.Type:
            t = str(wpart.Type)
            if t.startswith("0x") or t.startswith("0X"):
                try:
                    code = int(t, 16)
                    if code in MBR_TYPE_MAP:
                        result["type"] = MBR_TYPE_MAP[code]
                        if code in [0x82, 0x84]:
                            result["is_swap"] = True
                            if code == 0x82:
                                result["is_linux"] = True
                            result["fstype"] = "swap"
                        elif code in [0x83, 0x8E]:
                            result["is_linux"] = True
                            result["fstype"] = "ext4" if code == 0x83 else "linux-lvm"
                        elif code == 0xEF:
                            result["is_efi"] = True
                            result["fstype"] = "FAT32"
                        elif code in [0x07, 0x27]:
                            result["fstype"] = "NTFS"
                        elif code in [0x0B, 0x0C]:
                            result["fstype"] = "FAT32"
                        return result
                except:
                    pass

        # 3. Heuristic by size + position (this kills the last 5% of "Unknown")
        # Robust type conversion to handle both int and string values from WMI
        try:
            size = int(getattr(wpart, 'Size', 0) or 0)
            offset = int(getattr(wpart, 'StartingOffset', 0) or 0)
        except (ValueError, TypeError):
            size = 0
            offset = 0
        
        size_mb = size / 1024 / 1024 if size > 0 else 0
        offset_mb = offset / 1024 / 1024 if offset > 0 else 0
        return result
    
    def _is_linux_partition(self, partition) -> bool:
        """
        Detect if a partition is a Linux partition.
        
        Checks file system type for common Linux file systems and also
        looks for Linux-specific files for stronger evidence.
        
        Args:
            partition: psutil partition object
            
        Returns:
            True if partition uses a Linux file system or contains Linux files
        """
        # Check filesystem type first
        linux_filesystems = ['ext2', 'ext3', 'ext4', 'btrfs', 'xfs', 'reiserfs', 'jfs', 'swap']
        if partition.fstype.lower() in linux_filesystems:
            return True
        
        # Enhanced: Check for Linux-specific files on mounted partitions
        # This provides stronger evidence of a Linux installation
        if partition.mountpoint and os.path.exists(partition.mountpoint):
            try:
                linux_indicators = [
                    'etc/fstab',           # Filesystem table - core Linux file
                    'etc/os-release',      # OS identification
                    'boot/grub/grub.cfg',  # GRUB bootloader config
                    'boot/grub2/grub.cfg', # GRUB2 variant
                    'boot/initramfs',      # Initial RAM filesystem (pattern)
                    'boot/vmlinuz',        # Linux kernel (pattern)
                    'usr/bin/bash',        # Common Linux shell
                    'lib/systemd',         # systemd init system
                ]
                
                for indicator in linux_indicators:
                    check_path = os.path.join(partition.mountpoint, indicator)
                    # For initramfs and vmlinuz, check if any file starts with that name
                    if 'initramfs' in indicator or 'vmlinuz' in indicator:
                        boot_dir = os.path.join(partition.mountpoint, 'boot')
                        if os.path.exists(boot_dir):
                            try:
                                for filename in os.listdir(boot_dir):
                                    if filename.startswith(os.path.basename(indicator)):
                                        return True
                            except (PermissionError, OSError):
                                pass
                    elif os.path.exists(check_path):
                        return True
                        
            except (PermissionError, OSError):
                pass
        
        return False
    
    def _get_wmi_partition_info(self, device: str) -> Optional[Dict]:
        """
        Get additional partition information from WMI with enhanced forensic metadata.
        
        Args:
            device: Device path (e.g., 'C:\\')
            
        Returns:
            Dictionary with WMI partition info or None
        """
        if not self.wmi_available or not self.wmi_connection:
            return None
        
        try:
            # Extract drive letter from device path
            drive_letter = device.rstrip('\\').rstrip(':')
            
            # Skip if not a valid drive letter
            if not drive_letter or len(drive_letter) != 1:
                return None
            
            # Query logical disk with error handling
            try:
                logical_disks = self.wmi_connection.Win32_LogicalDisk(DeviceID=f"{drive_letter}:")
            except Exception:
                return None
            
            if not logical_disks:
                return None
            
            logical_disk = logical_disks[0]
            
            # Get partition information using robust mapping instead of ASSOCIATORS OF
            partition = None
            disk_index = 0
            
            try:
                # Use Win32_LogicalDiskToPartition association if possible, but handle errors
                partitions = self.wmi_connection.query(
                    f"ASSOCIATORS OF {{Win32_LogicalDisk.DeviceID='{drive_letter}:'}} "
                    f"WHERE AssocClass=Win32_LogicalDiskToPartition"
                )
                if partitions:
                    partition = partitions[0]
            except Exception:
                pass
                
            if not partition:
                # Fallback: Try to get partition style from disk-level detection
                # Query all partitions to find which disk this logical drive belongs to
                partition_style_fallback = 'MBR'  # Default fallback
                disk_index_fallback = 0
                partition_fallback = None  # Initialize for later use by resolver
                
                try:
                    # Try to find the partition by querying all partitions
                    all_partitions = self.wmi_connection.Win32_DiskPartition()
                    for wpart in all_partitions:
                        try:
                            # Check if this partition has the logical disk
                            logical_disks_for_part = self.wmi_connection.query(
                                f"ASSOCIATORS OF {{Win32_DiskPartition.DeviceID='{wpart.DeviceID}'}} "
                                f"WHERE AssocClass=Win32_LogicalDiskToPartition"
                            )
                            for ld in logical_disks_for_part:
                                if ld.DeviceID == f"{drive_letter}:":
                                    # Found the partition! Get its disk index
                                    name = wpart.Name if hasattr(wpart, 'Name') else wpart.DeviceID
                                    if 'Disk #' in name:
                                        disk_index_fallback = int(name.split('Disk #')[1].split(',')[0])
                                    partition_fallback = wpart  # Save the partition for later use
                                    break
                        except:
                            continue
                    
                    # Get partition style from disk level
                    if disk_index_fallback >= 0:
                        partition_style_fallback, _, _ = self._get_disk_partition_style(disk_index_fallback)
                except Exception as e:
                    print(f"[Debug] Fallback disk detection failed for {drive_letter}: {e}")
                    # Even if this fails, default to MBR
                    partition_style_fallback = 'MBR'
                
                # Use comprehensive partition type resolver if we found the partition
                guid_fallback = ""
                if partition_fallback:
                    resolved = self._resolve_partition_type(partition_fallback)
                    part_type_fallback = resolved["type"]
                    fstype_fallback = resolved["fstype"]
                    guid_fallback = resolved["guid"]
                    
                    print(f"[Debug] Resolved fallback for {drive_letter}: Type={part_type_fallback}, GUID={guid_fallback}")
                    
                    # Update partition style if we have a GUID
                    if guid_fallback and guid_fallback != "TEXT-MAPPING":
                        partition_style_fallback = 'GPT'
                else:
                    # Fallback: Determine partition type based on filesystem
                    fs_type = getattr(logical_disk, 'FileSystem', '')
                    
                    part_type_fallback = 'Basic Data Partition'
                    fstype_fallback = fs_type
                    
                    # Map filesystem to partition type
                    if fs_type == 'NTFS':
                        part_type_fallback = 'Basic Data Partition (NTFS/exFAT)'
                        fstype_fallback = 'NTFS'
                    elif fs_type == 'FAT32':
                        part_type_fallback = 'FAT32 (LBA)'
                        fstype_fallback = 'FAT32'
                    elif fs_type == 'exFAT':
                        part_type_fallback = 'Basic Data Partition (NTFS/exFAT)'
                        fstype_fallback = 'exFAT'
                    elif fs_type in ['ext4', 'ext3', 'ext2']:
                        part_type_fallback = 'Linux Filesystem'
                        fstype_fallback = fs_type
                
                return {
                    'type': part_type_fallback,
                    'label': getattr(logical_disk, 'VolumeName', '') or '',
                    'disk_index': disk_index_fallback,
                    'partition_index': 0,
                    'guid': guid_fallback,
                    'partition_style': partition_style_fallback,
                    'is_hidden': False,
                    'is_active': False,
                    'is_efi_system': False,
                    'offset': 0,
                    'length': 0,
                    'disk_signature': '',
                    'volume_serial': getattr(logical_disk, 'VolumeSerialNumber', '') or ''
                }
            
            # Get disk index from partition name
            try:
                name = partition.Name if hasattr(partition, 'Name') else partition.DeviceID
                if 'Disk #' in name:
                    disk_index = int(name.split('Disk #')[1].split(',')[0])
            except:
                pass
            
            # Get disk signature (requires disk object)
            disk_signature = ''
            try:
                disks = self.wmi_connection.Win32_DiskDrive(Index=disk_index)
                if disks:
                    disk = disks[0]
                    if hasattr(disk, 'Signature') and disk.Signature is not None:
                        try:
                            disk_signature = hex(int(disk.Signature))
                        except:
                            pass
            except:
                pass
            
            # Determine partition style and get GUID using the comprehensive resolver
            resolved = self._resolve_partition_type(partition)
            part_type = resolved["type"]
            partition_guid = resolved["guid"]
            is_efi_system = resolved["is_efi"]
            
            # Determine partition style
            partition_style = 'Unknown'
            if partition_guid and partition_guid != "TEXT-MAPPING":
                partition_style = 'GPT'
            
            # If style is still unknown, try disk level
            if partition_style == 'Unknown':
                try:
                    partition_style, _, _ = self._get_disk_partition_style(disk_index)
                except:
                    partition_style = 'MBR'  # Ultimate fallback
            
            # Get partition attributes with safe getattr and None handling
            hidden_sectors = getattr(partition, 'HiddenSectors', None) if hasattr(partition, 'HiddenSectors') else None
            is_hidden = (hidden_sectors or 0) > 0
            
            bootable = getattr(partition, 'Bootable', None) if hasattr(partition, 'Bootable') else None
            is_active = bootable if bootable is not None else False
            
            partition_offset = 0
            if hasattr(partition, 'StartingOffset') and partition.StartingOffset is not None:
                try:
                    partition_offset = int(partition.StartingOffset)
                except:
                    pass
            
            partition_length = 0
            if hasattr(partition, 'Size') and partition.Size is not None:
                try:
                    partition_length = int(partition.Size)
                except:
                    pass
            
            # Get Volume Serial Number from Logical Disk
            volume_serial = getattr(logical_disk, 'VolumeSerialNumber', '') or ''
            # Format serial if it's a raw integer (sometimes WMI returns decimal)
            if volume_serial and str(volume_serial).isdigit() and len(str(volume_serial)) > 8:
                 try:
                     # Convert decimal to hex XXXX-XXXX format
                     hex_serial = hex(int(volume_serial))[2:].upper()
                     if len(hex_serial) >= 8:
                         volume_serial = f"{hex_serial[-8:-4]}-{hex_serial[-4:]}"
                 except:
                     pass

            return {
                'type': part_type,
                'label': getattr(logical_disk, 'VolumeName', '') or '',
                'disk_index': disk_index,
                'partition_index': getattr(partition, 'Index', 0) if hasattr(partition, 'Index') else 0,
                'guid': partition_guid,
                'partition_style': partition_style,
                'is_hidden': is_hidden,
                'is_active': is_active,
                'is_efi_system': is_efi_system,
                'offset': partition_offset,
                'length': partition_length,
                'disk_signature': disk_signature,
                'volume_serial': volume_serial
            }
            
        except Exception as e:
            # Silently handle errors - return None to use defaults
            return None

    def _detect_boot_mode(self) -> str:
        """
        Detect whether the system is using BIOS or UEFI boot mode.
        
        Uses multiple reliable methods:
        1. Check for EFI directory on any drive
        2. Check registry FirmwareBootDevice
        3. Check setupact.log for boot environment
        
        Returns:
            'UEFI' or 'BIOS' or 'Unknown'
        """
        try:
            # Method 1: Check for EFI directory on any mounted drive
            for drive_letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
                efi_path = f"{drive_letter}:\\EFI"
                if os.path.exists(efi_path):
                    return 'UEFI'
            
            # Method 2: Check Windows registry for firmware boot device
            if os.name == 'nt':
                try:
                    import winreg
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 
                                        r"SYSTEM\CurrentControlSet\Control", 
                                        0, winreg.KEY_READ)
                    try:
                        value, _ = winreg.QueryValueEx(key, "FirmwareBootDevice")
                        winreg.CloseKey(key)
                        if value:
                            return 'UEFI'
                    except:
                        winreg.CloseKey(key)
                except:
                    pass
                
                # Method 3: Check setupact.log for boot environment
                try:
                    setupact_paths = [
                        r"C:\Windows\Panther\setupact.log",
                        r"C:\Windows\System32\Panther\setupact.log"
                    ]
                    for log_path in setupact_paths:
                        if os.path.exists(log_path):
                            try:
                                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                                    content = f.read()
                                    if "Detected boot environment: UEFI" in content:
                                        return 'UEFI'
                                    elif "Detected boot environment: BIOS" in content:
                                        return 'BIOS'
                            except:
                                pass
                except:
                    pass
                
                # Method 4: Check for EFI partition via WMI
                if self.wmi_available and self.wmi_connection:
                    try:
                        partitions = self.wmi_connection.Win32_DiskPartition()
                        for partition in partitions:
                            if hasattr(partition, 'Type') and partition.Type:
                                type_str = str(partition.Type).upper()
                                if 'C12A7328-F81F-11D2-BA4B-00A0C93EC93B' in type_str:
                                    return 'UEFI'
                            if hasattr(partition, 'DiskPartitionType') and partition.DiskPartitionType:
                                guid = str(partition.DiskPartitionType).upper()
                                if 'C12A7328-F81F-11D2-BA4B-00A0C93EC93B' in guid:
                                    return 'UEFI'
                    except:
                        pass
            
            # Default to BIOS if no UEFI indicators found
            return 'BIOS'
            
        except Exception as e:
            print(f"[Partition Analyzer] Error detecting boot mode: {e}")
            return 'Unknown'
    
    def _get_disk_partition_style(self, disk_index: int) -> Tuple[str, str, str]:
        """
        Get the partition table style (MBR or GPT) for a specific disk.
        
        Args:
            disk_index: Index of the disk to check
            
        Returns:
            Tuple of (partition_style, disk_signature, disk_guid)
        """
        if not self.wmi_available or not self.wmi_connection:
            return ('Unknown', '', '')
        
        try:
            # Query the disk directly
            disks = self.wmi_connection.Win32_DiskDrive(Index=disk_index)
            if not disks:
                return ('Unknown', '', '')
            
            disk = disks[0]
            disk_signature = ''
            disk_guid = ''
            partition_style = 'Unknown'
            
            # Try to get signature from disk object
            if hasattr(disk, 'Signature') and disk.Signature is not None:
                try:
                    sig_val = disk.Signature
                    if sig_val:
                        disk_signature = hex(int(sig_val))
                except:
                    pass
            
            # Find partitions for this disk by parsing DeviceID/Name
            # This avoids the fragile ASSOCIATORS OF query
            partitions = []
            try:
                all_parts = self.wmi_connection.Win32_DiskPartition()
                for part in all_parts:
                    name = part.Name if hasattr(part, 'Name') else part.DeviceID
                    if f"Disk #{disk_index}," in name:
                        partitions.append(part)
            except:
                pass
            
            if not partitions:
                # Fallback: if no partitions found, we can't determine style easily
                # But we might have the signature
                if disk_signature:
                    return ('MBR', disk_signature, '')
                return ('Unknown', '', '')
            
            # Check first partition to determine style
            partition = partitions[0]
            
            # Check Type field first
            if hasattr(partition, 'Type') and partition.Type:
                type_str = str(partition.Type).upper()
                # If it contains a GUID, it's GPT
                for guid in PARTITION_TYPE_GUIDS.keys():
                    if guid.upper() in type_str:
                        partition_style = 'GPT'
                        # Don't clear disk_signature here - let the robust check at start handle it
                        if hasattr(disk, 'Signature') and disk.Signature:
                            # If signature looks like a GUID, use it as GUID
                            sig_str = str(disk.Signature)
                            if '{' in sig_str or '-' in sig_str:
                                disk_guid = sig_str
                        break
            
            # Check DiskPartitionType if Type didn't reveal GPT
            if partition_style == 'Unknown' and hasattr(partition, 'DiskPartitionType') and partition.DiskPartitionType:
                ptype = str(partition.DiskPartitionType)
                if '{' in ptype or '-' in ptype:
                    partition_style = 'GPT'
                    # Don't clear disk_signature here either
                    if hasattr(disk, 'Signature') and disk.Signature:
                        sig_str = str(disk.Signature)
                        if '{' in sig_str or '-' in sig_str:
                            disk_guid = sig_str
                else:
                    partition_style = 'MBR'
            
            # Final fallback
            if partition_style == 'Unknown':
                partition_style = 'MBR'
            
            return (partition_style, disk_signature, disk_guid)
            
        except Exception as e:
            print(f"[Partition Analyzer] Error getting partition style for disk {disk_index}: {e}")
            return ('Unknown', '', '')

    def _is_disk_bootable(self, wmi_disk, partitions: List[PartitionInfo]) -> bool:
        """
        Determine if a disk is bootable.
        
        Args:
            wmi_disk: WMI disk drive object
            partitions: List of partitions on this disk
            
        Returns:
            True if disk appears to be bootable
        """
        try:
            # Check if any partition is marked as boot or EFI
            for partition in partitions:
                if partition.is_boot or partition.is_efi_system or partition.is_active:
                    return True
            
            # Check for bootable indicators in WMI
            if hasattr(wmi_disk, 'Status') and wmi_disk.Status:
                if 'boot' in str(wmi_disk.Status).lower():
                    return True
            
            # For removable media, check if it has an active partition
            media_type = getattr(wmi_disk, 'MediaType', '') if hasattr(wmi_disk, 'MediaType') else ''
            if str(media_type).lower() == 'removable media':
                # Removable media with partitions could be bootable
                if len(partitions) > 0:
                    # Check for common bootable file systems
                    for partition in partitions:
                        if partition.fstype.upper() in ['FAT32', 'FAT', 'NTFS', 'exFAT']:
                            # Check for boot files
                            if partition.is_boot:
                                return True
                            if partition.mountpoint:
                                try:
                                    if os.path.exists(os.path.join(partition.mountpoint, 'bootmgr')):
                                        return True
                                except:
                                    pass
            
            return False
            
        except Exception as e:
            print(f"[Partition Analyzer] Error checking if disk is bootable: {e}")
            return False

    def format_size(self, size_bytes: int) -> str:
        """
        Format size in bytes to human-readable format.
        
        Args:
            size_bytes: Size in bytes
            
        Returns:
            Formatted string (e.g., "123.45 GB")
        """
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"

    def save_to_database(self, db_path: str, disks: List[DiskInfo] = None):
        """
        Save disk and partition information to a SQLite database.
        
        Args:
            db_path: Path to the SQLite database
            disks: Optional list of DiskInfo objects. If None, will run analysis.
        """
        if disks is None:
            disks = self.get_disks_with_partitions()
            
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Create tables
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS disks (
                disk_index INTEGER PRIMARY KEY,
                size INTEGER,
                model TEXT,
                interface_type TEXT,
                partition_style TEXT,
                boot_mode TEXT,
                disk_signature TEXT,
                disk_guid TEXT,
                serial_number TEXT,
                firmware_type TEXT,
                is_removable INTEGER,
                is_usb INTEGER,
                media_type TEXT,
                is_bootable INTEGER
            )
            ''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS partitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                disk_index INTEGER,
                partition_index INTEGER,
                device TEXT,
                mountpoint TEXT,
                fstype TEXT,
                total_size INTEGER,
                used_size INTEGER,
                free_size INTEGER,
                percent_used REAL,
                is_boot INTEGER,
                is_system INTEGER,
                is_swap INTEGER,
                is_linux INTEGER,
                partition_type TEXT,
                volume_label TEXT,
                partition_guid TEXT,
                partition_style TEXT,
                is_hidden INTEGER,
                is_active INTEGER,
                is_efi_system INTEGER,
                partition_offset INTEGER,
                partition_length INTEGER,
                disk_signature TEXT,
                volume_serial TEXT,
                is_removable INTEGER,
                is_usb INTEGER,
                FOREIGN KEY(disk_index) REFERENCES disks(disk_index)
            )
            ''')
            
            # Clear existing data for these disks to avoid duplicates
            cursor.execute("DELETE FROM disks")
            cursor.execute("DELETE FROM partitions")
            
            # Insert data
            for disk in disks:
                cursor.execute('''
                INSERT INTO disks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    disk.disk_index, disk.size, disk.model, disk.interface_type,
                    disk.partition_style, disk.boot_mode, disk.disk_signature,
                    disk.disk_guid, disk.serial_number, disk.firmware_type,
                    1 if disk.is_removable else 0, 1 if disk.is_usb else 0,
                    disk.media_type, 1 if disk.is_bootable else 0
                ))
                
                for part in disk.partitions:
                    cursor.execute('''
                    INSERT INTO partitions (
                        disk_index, partition_index, device, mountpoint, fstype,
                        total_size, used_size, free_size, percent_used,
                        is_boot, is_system, is_swap, is_linux, partition_type,
                        volume_label, partition_guid, partition_style,
                        is_hidden, is_active, is_efi_system, partition_offset,
                        partition_length, disk_signature, volume_serial,
                        is_removable, is_usb
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        part.disk_index, part.partition_index, part.device, part.mountpoint, part.fstype,
                        part.total_size, part.used_size, part.free_size, part.percent_used,
                        1 if part.is_boot else 0, 1 if part.is_system else 0,
                        1 if part.is_swap else 0, 1 if part.is_linux else 0, part.partition_type,
                        part.volume_label, part.partition_guid, part.partition_style,
                        1 if part.is_hidden else 0, 1 if part.is_active else 0,
                        1 if part.is_efi_system else 0, part.partition_offset,
                        part.partition_length, part.disk_signature, part.volume_serial,
                        1 if part.is_removable else 0, 1 if part.is_usb else 0
                    ))
            
            conn.commit()
            conn.close()
            print(f"[Partition Analyzer] Results saved to database: {db_path}")
            return True
            
        except Exception as e:
            print(f"[Partition Analyzer] Error saving to database: {e}")
            return False
    
    def load_from_database(self, db_path: str) -> List[DiskInfo]:
        """
        Load disk and partition information from a SQLite database.
        
        Args:
            db_path: Path to the SQLite database
            
        Returns:
            List of DiskInfo objects loaded from database, or empty list if error
        """
        if not os.path.exists(db_path):
            print(f"[Partition Analyzer] Database not found: {db_path}")
            return []
            
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Check if tables exist
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='disks'")
            if not cursor.fetchone():
                print("[Partition Analyzer] Database tables not found")
                conn.close()
                return []
            
            # Load disks
            cursor.execute("SELECT * FROM disks ORDER BY disk_index")
            disk_rows = cursor.fetchall()
            
            disks = []
            for disk_row in disk_rows:
                disk_index = disk_row[0]
                
                # Load partitions for this disk
                cursor.execute("SELECT * FROM partitions WHERE disk_index = ? ORDER BY partition_index", (disk_index,))
                partition_rows = cursor.fetchall()
                
                # Get disk signature from disk row (index 6) to propagate if needed
                disk_sig_from_disk = disk_row[6]

                partitions = []
                for part_row in partition_rows:
                    # Use partition's stored signature, or fallback to disk's signature
                    p_sig = part_row[23]
                    if not p_sig and disk_sig_from_disk:
                        p_sig = disk_sig_from_disk

                    partition = PartitionInfo(
                        device=part_row[3],
                        mountpoint=part_row[4],
                        fstype=part_row[5],
                        opts="",
                        total_size=part_row[6],
                        used_size=part_row[7],
                        free_size=part_row[8],
                        percent_used=part_row[9],
                        is_boot=bool(part_row[10]),
                        is_system=bool(part_row[11]),
                        is_swap=bool(part_row[12]),
                        is_linux=bool(part_row[13]),
                        partition_type=part_row[14],
                        disk_index=part_row[1],
                        partition_index=part_row[2],
                        volume_label=part_row[15],
                        partition_guid=part_row[16],
                        partition_style=part_row[17],
                        is_hidden=bool(part_row[18]),
                        is_active=bool(part_row[19]),
                        is_efi_system=bool(part_row[20]),
                        partition_offset=part_row[21],
                        partition_length=part_row[22],
                        disk_signature=p_sig,
                        volume_serial=part_row[24],
                        is_removable=bool(part_row[25]),
                        is_usb=bool(part_row[26])
                    )
                    partitions.append(partition)
                
                disk = DiskInfo(
                    disk_index=disk_row[0],
                    size=disk_row[1],
                    model=disk_row[2],
                    interface_type=disk_row[3],
                    partitions=partitions,
                    partition_style=disk_row[4],
                    boot_mode=disk_row[5],
                    disk_signature=disk_row[6],
                    disk_guid=disk_row[7],
                    serial_number=disk_row[8],
                    firmware_type=disk_row[9],
                    is_removable=bool(disk_row[10]),
                    is_usb=bool(disk_row[11]),
                    media_type=disk_row[12],
                    is_bootable=bool(disk_row[13])
                )
                disks.append(disk)
            
            conn.close()
            print(f"[Partition Analyzer] Loaded {len(disks)} disk(s) from database: {db_path}")
            return disks
            
        except Exception as e:
            print(f"[Partition Analyzer] Error loading from database: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def detect_windows_installation(self, partition_path: str) -> bool:
        """
        Detect if a partition contains a Windows installation.
        
        This method checks for the presence of Windows directory structure
        and verifies the installation by checking for critical system files.
        
        Args:
            partition_path: Path to partition root (e.g., "D:\\")
            
        Returns:
            bool: True if Windows installation found, False otherwise
        """
        # Ensure partition path ends with backslash
        if not partition_path.endswith('\\'):
            partition_path += '\\'
        
        # Check for Windows directory
        windows_dir = os.path.join(partition_path, "Windows")
        if not os.path.exists(windows_dir):
            return False
        
        # Check for System32 directory
        system32_dir = os.path.join(windows_dir, "System32")
        if not os.path.exists(system32_dir):
            return False
        
        # Verify by checking for critical system files
        critical_files = [
            os.path.join(system32_dir, "ntoskrnl.exe"),
            os.path.join(system32_dir, "kernel32.dll"),
            os.path.join(system32_dir, "ntdll.dll")
        ]
        
        found_files = sum(1 for f in critical_files if os.path.exists(f))
        
        # Require at least 2 out of 3 critical files
        return found_files >= 2
    
    def get_windows_partition_letter(self) -> Optional[str]:
        """
        Get the partition letter containing the Windows installation.
        
        Returns:
            str: Partition letter (e.g., "C:") or None if not found
        """
        # Try environment variable first (for live systems)
        system_root = os.getenv('SystemRoot')
        if system_root and ':' in system_root:
            partition_letter = system_root.split(':')[0] + ':'
            if self.detect_windows_installation(partition_letter + '\\'):
                return partition_letter
        
        # Scan all partitions
        partitions = self.get_all_partitions()
        for partition in partitions:
            if partition.mountpoint and partition.mountpoint.endswith(':\\'):
                if self.detect_windows_installation(partition.mountpoint):
                    partition_letter = partition.mountpoint.rstrip('\\')
                    return partition_letter
        
        return None



def main():
    """Test function to demonstrate partition analyzer functionality"""
    parser = argparse.ArgumentParser(description='Crow Eye - Enhanced Partition and Volume Analyzer')
    parser.add_argument('--json', type=str, help='Output results to JSON file')
    args = parser.parse_args()
    
    print("=" * 80)
    print("Crow Eye - Enhanced Partition and Volume Analyzer")
    print("=" * 80)
    
    analyzer = PartitionAnalyzer()
    
    print(f"\n[*] System Boot Mode: {analyzer.boot_mode}")
    print("\n[*] Analyzing physical disks...")
    disks = analyzer.get_disks_with_partitions()
    
    print(f"\n[+] Found {len(disks)} physical disk(s):\n")
    
    for disk in disks:
        print(f"{'='*80}")
        print(f"Disk {disk.disk_index}: {disk.model}")
        print(f"{'='*80}")
        print(f"  Size: {analyzer.format_size(disk.size)}")
        print(f"  Interface: {disk.interface_type}")
        print(f"  Partition Style: {disk.partition_style}")
        print(f"  Boot Mode: {disk.boot_mode}")
        if disk.serial_number:
            print(f"  Serial Number: {disk.serial_number}")
        if disk.disk_signature:
            print(f"  Disk Signature: {disk.disk_signature}")
        if disk.disk_guid:
            print(f"  Disk GUID: {disk.disk_guid}")
        if disk.is_removable:
            print(f"  Media Type: Removable")
        if disk.is_usb:
            print(f"  Interface: USB")
        if disk.is_bootable:
            print(f"  Bootable: Yes")
        
        print(f"\n  Partitions on this disk: {len(disk.partitions)}")
        print(f"  {'-'*76}")
        
        for part in disk.partitions:
            print(f"\n  Device: {part.device}")
            if part.mountpoint:
                print(f"    Mount Point: {part.mountpoint}")
            print(f"    File System: {part.fstype}")
            if part.volume_label:
                print(f"    Volume Label: {part.volume_label}")
            if part.volume_serial:
                print(f"    Volume Serial: {part.volume_serial}")
            print(f"    Total Size: {analyzer.format_size(part.total_size)}")
            if part.total_size > 0:
                print(f"    Used: {analyzer.format_size(part.used_size)} ({part.percent_used}%)")
                print(f"    Free: {analyzer.format_size(part.free_size)}")
            print(f"    Partition Style: {part.partition_style}")
            print(f"    Partition Type: {part.partition_type}")
            
            if part.partition_guid:
                print(f"    Partition GUID: {part.partition_guid}")
            if part.disk_signature:
                print(f"    Disk Signature: {part.disk_signature}")
            if part.partition_offset > 0:
                print(f"    Partition Offset: {analyzer.format_size(part.partition_offset)}")
            if part.partition_length > 0:
                print(f"    Partition Length: {analyzer.format_size(part.partition_length)}")
            
            flags = []
            if part.is_boot:
                flags.append("BOOT")
            if part.is_system:
                flags.append("SYSTEM")
            if part.is_swap:
                flags.append("SWAP")
            if part.is_linux:
                flags.append("LINUX")
            if part.is_efi_system:
                flags.append("EFI_SYSTEM")
            if part.is_active:
                flags.append("ACTIVE")
            if part.is_hidden:
                flags.append("HIDDEN")
            if part.is_removable:
                flags.append("REMOVABLE")
            if part.is_usb:
                flags.append("USB")
            
            if flags:
                print(f"    Flags: {', '.join(flags)}")
        
        print()  # Empty line between disks
    
    # JSON output if requested
    if args.json:
        output_data = {
            'boot_mode': analyzer.boot_mode,
            'disks': [disk.to_dict() for disk in disks]
        }
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2)
        print(f"\n[*] Results saved to {args.json}")


if __name__ == "__main__":
    main()
