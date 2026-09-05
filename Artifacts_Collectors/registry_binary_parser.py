"""
Binary parsing utilities for Windows registry forensic artifacts.

This module provides specialized parsing functions for complex binary structures
found in Windows registry keys such as OpenSaveMRU, LastSaveMRU, BAM, DAM, and RecentDocs.
"""

import re
import struct
import logging
from datetime import datetime, timedelta, timezone
from utils.time_utils import (format_forensic_timestamp, filetime_to_datetime,
                              systemtime_to_datetime, unix_timestamp_to_datetime)

# Configure logging
logger = logging.getLogger(__name__)


# MUICache stores one registry value per property of an executable, named
# "<path>.<PropertyName>". Longest first, so ".ApplicationCompany" is matched
# before any shorter suffix that could also match.
MUICACHE_PROPERTY_SUFFIXES = (
    '.ApplicationCompany',
    '.FriendlyAppName',
    '.FileDescription',
    '.ProductVersion',
    '.ApplicationName',
    '.ProductName',
    '.CompanyName',
    '.FileVersion',
)


# Shell items store localised folder names as a resource reference into a DLL
# rather than as text, so a decoded path reads
# "C:\shell32.dll,-21813\Ghass\shell32.dll,-21798" instead of
# "C:\Users\Ghass\Desktop".
#
# Resolved from a table, not through SHLoadIndirectString: the API answers about
# the machine running Crow-Eye, in its language, which is the same mistake
# user_identity exists to prevent - an image acquired from another machine would
# be described using the analyst's folder names. A table gives live and offline
# the same answer, and the raw reference is kept beside the resolved one.
MUI_RESOURCE_NAMES = {
    'shell32.dll,-21769': 'Documents',
    'shell32.dll,-21770': 'Music',
    'shell32.dll,-21779': 'Pictures',
    'shell32.dll,-21787': 'Videos',
    'shell32.dll,-21798': 'Desktop',
    'shell32.dll,-21813': 'Users',
    'shell32.dll,-21815': 'Downloads',
    'windows.storage.dll,-21769': 'Documents',
    'windows.storage.dll,-21770': 'Music',
    'windows.storage.dll,-21779': 'Pictures',
    'windows.storage.dll,-21787': 'Videos',
    'windows.storage.dll,-21798': 'Desktop',
    'windows.storage.dll,-21813': 'Users',
    'windows.storage.dll,-21815': 'Downloads',
    'windows.storage.dll,-21823': 'Screenshots',
}


def resolve_mui_reference(component: str) -> str:
    """Folder name for a MUI resource reference, or the component unchanged.

    Matching is case-insensitive and ignores any leading '@', which is how the
    reference appears in some shell items.
    """
    if not component:
        return component
    key = component.lstrip('@').strip().lower()
    for ref, name in MUI_RESOURCE_NAMES.items():
        if key == ref.lower():
            return name
    return component


def resolve_mui_path(path: str) -> str:
    """Apply resolve_mui_reference to every component of a backslash path."""
    if not path or ',' not in path:
        return path
    return '\\'.join(resolve_mui_reference(p) for p in path.split('\\'))


# Characters Windows does not allow in a file or folder name. A candidate
# containing one of these did not come from a name field.
_ILLEGAL_NAME_CHARS = set('<>:"/|?*') | {chr(c) for c in range(0x20)}


def is_plausible_mft_record(entry: int) -> bool:
    """Whether a shell item's file reference can be an NTFS MFT record number.

    A shell item carries this field whatever filesystem the volume uses. On
    exFAT - common on external and secondary drives - it holds a directory
    entry value, and reporting that as an MFT record gives the analyst a number
    that looks authoritative and resolves to nothing.

    NTFS addresses records in 1 KB units, so even a 4 TB volume stays well
    under 2**32. Values above that did not come from an MFT.
    """
    return 0 < entry < 2 ** 32


def is_plausible_name(candidate: str) -> bool:
    """Whether a decoded string can be a real file or folder name.

    Only the shell item types that define where their name lives are read
    structurally; everything else is a guess, and a guess that yields control
    bytes or `}D"pN` must be dropped rather than stored. An empty cell is an
    acknowledged gap; a fabricated folder name is a wrong answer an analyst
    cannot tell from a right one.
    """
    if not candidate:
        return False
    text = candidate.strip()
    if len(text) < 2:
        return False
    if any(ch in _ILLEGAL_NAME_CHARS for ch in text):
        return False
    # Real names are mostly letters, digits and the usual punctuation.
    ordinary = sum(1 for ch in text if ch.isalnum() or ch in " .-_()[]{}'&+,~#@!$%^=;")
    return ordinary / len(text) >= 0.8


def extract_unicode_string(binary_data: bytes, offset: int = 0) -> str:
    """
    Extract null-terminated Unicode (UTF-16-LE) string from binary data.
    
    Args:
        binary_data: The binary data containing the Unicode string
        offset: Starting offset in the binary data (default: 0)
    
    Returns:
        Extracted Unicode string without null terminator
        
    Raises:
        ValueError: If binary data is invalid or offset is out of bounds
    """
    try:
        if not binary_data or offset >= len(binary_data):
            logger.warning(f"Invalid binary data or offset: offset={offset}, data_len={len(binary_data) if binary_data else 0}")
            return ""
        
        # Find null terminator (0x0000 in UTF-16-LE)
        end_offset = offset
        while end_offset < len(binary_data) - 1:
            if binary_data[end_offset] == 0 and binary_data[end_offset + 1] == 0:
                break
            end_offset += 2
        
        # Extract and decode the string
        string_bytes = binary_data[offset:end_offset]
        if not string_bytes:
            return ""
            
        decoded_string = string_bytes.decode('utf-16-le', errors='ignore')
        return decoded_string.strip()
        
    except Exception as e:
        logger.error(f"Error extracting Unicode string: {e}")
        return ""


def parse_filetime(binary_data: bytes) -> str:
    """
    Convert 8-byte Windows FILETIME to ISO 8601 datetime string.
    
    Windows FILETIME is a 64-bit value representing the number of 
    100-nanosecond intervals since January 1, 1601 UTC.
    
    Args:
        binary_data: 8-byte binary data containing FILETIME value
    
    Returns:
        ISO 8601 formatted datetime string (YYYY-MM-DD HH:MM:SS)
        
    Raises:
        ValueError: If binary data is not exactly 8 bytes
    """
    try:
        if not binary_data or len(binary_data) < 8:
            logger.warning(f"Invalid FILETIME data: expected 8 bytes, got {len(binary_data) if binary_data else 0}")
            return ""
        
        # Unpack as 64-bit little-endian unsigned integer
        filetime = struct.unpack('<Q', binary_data[:8])[0]
        
        # Check for invalid/zero timestamp
        if filetime == 0:
            return ""
        
        # Convert to datetime using centralized utility
        dt = filetime_to_datetime(filetime)
        
        # Return standardized forensic format
        return format_forensic_timestamp(dt)
        
    except Exception as e:
        logger.error(f"Error parsing FILETIME: {e}")
        return ""


def parse_mru_list_ex(binary_data: bytes) -> list:
    """
    Parse MRUListEx DWORD array to get access order.
    
    MRUListEx is an array of 4-byte DWORD values indicating the order
    in which items were accessed. The array is terminated by 0xFFFFFFFF.
    
    Args:
        binary_data: Binary data containing MRUListEx DWORD array
    
    Returns:
        List of integers representing access order indices
        
    Raises:
        ValueError: If binary data is invalid
    """
    try:
        if not binary_data or len(binary_data) < 4:
            logger.warning(f"Invalid MRUListEx data: expected at least 4 bytes, got {len(binary_data) if binary_data else 0}")
            return []
        
        mru_list = []
        offset = 0
        
        while offset + 4 <= len(binary_data):
            # Unpack DWORD (4-byte little-endian unsigned integer)
            dword = struct.unpack('<I', binary_data[offset:offset + 4])[0]
            
            # Check for terminator
            if dword == 0xFFFFFFFF:
                break
            
            mru_list.append(dword)
            offset += 4
        
        return mru_list
        
    except Exception as e:
        logger.error(f"Error parsing MRUListEx: {e}")
        return []



def parse_shell_item_id(binary_data: bytes) -> dict:
    """
    Parse Shell Item ID to extract file/folder name and metadata.
    
    Note: This function extracts file/folder names from individual Shell Items
    but does NOT reconstruct full paths. Full path reconstruction will be
    handled through MFT correlation in a future enhancement.
    
    Shell Item IDs are variable-length binary structures used by Windows Explorer
    to represent file system objects. This enhanced version focuses on extracting
    metadata for forensic analysis.
    
    Args:
        binary_data: Binary data containing Shell Item ID structure(s)
    
    Returns:
        Dictionary containing:
            - 'file_name': Primary file/folder name (long name preferred)
            - 'short_name': 8.3 format name (if available)
            - 'long_name': Unicode long name (if available)
            - 'type': Type of shell item (filesystem, network, drive, etc.)
            - 'drive_letter': Drive letter (if applicable)
            - 'special_folder': Special folder name (if applicable)
            - 'mft_record': NTFS MFT record number (if available)
            - 'extension_blocks': Additional metadata from extension blocks
        
    Raises:
        ValueError: If binary data is invalid
    """
    try:
        if not binary_data or len(binary_data) < 2:
            logger.warning(f"Invalid Shell Item ID data: expected at least 2 bytes, got {len(binary_data) if binary_data else 0}")
            return {
                'file_name': '',
                'short_name': '',
                'long_name': '',
                'type': 'unknown',
                'drive_letter': '',
                'special_folder': '',
                'mft_record': 0,
                'extension_blocks': {}
            }
        
        # Initialize result dictionary
        result = {
            'file_name': '',
            'short_name': '',
            'long_name': '',
            'type': 'unknown',
            'drive_letter': '',
            'special_folder': '',
            'mft_record': 0,
            'extension_blocks': {}
        }
        
        # Process only the FIRST Shell Item (not full path reconstruction)
        offset = 0
        
        # Read size of first Shell Item ID (2 bytes, little-endian)
        if offset + 2 > len(binary_data):
            return result
            
        size = struct.unpack('<H', binary_data[offset:offset + 2])[0]
        
        # Size of 0 indicates end of list
        if size == 0:
            return result
        
        # Ensure we don't read beyond buffer
        if offset + size > len(binary_data):
            return result
        
        # Extract this Shell Item ID
        item_data = binary_data[offset:offset + size]
        
        # Parse the item based on type indicator (byte at offset 2)
        if len(item_data) > 2:
            type_indicator = item_data[2]
            
            # Special folder (GUID-based) - type 0x1F
            # Decode GUID and map to special folder name
            if type_indicator == 0x1F:
                result['type'] = 'special_folder'
                if len(item_data) >= 20:
                    guid_bytes = item_data[4:20]
                    guid_str = _format_guid(guid_bytes)
                    special_folder_name = _SPECIAL_FOLDER_GUIDS.get(guid_str, '')
                    result['special_folder'] = special_folder_name
                    # An unrecognised known-folder GUID is recorded as the GUID.
                    # It is a fact the analyst can look up, and it keeps the
                    # folder chain rooted; the previous fallback let a byte scan
                    # invent a name for it instead.
                    result['file_name'] = special_folder_name or '{%s}' % guid_str
            
            # File system object (0x30-0x3F range)
            elif 0x30 <= type_indicator <= 0x3F:
                result['type'] = 'filesystem'
                # Extract both short and long names
                names = _extract_filesystem_names(item_data)
                result['short_name'] = names.get('short_name', '')
                result['long_name'] = names.get('long_name', '')
                # Prioritize long name over short name
                result['file_name'] = result['long_name'] if result['long_name'] else result['short_name']
                # A localised folder is stored as a resource reference
                # ("windows.storage.dll,-21779"), which is not a usable name on
                # a report. Resolved from the static table; short_name still
                # carries what the registry literally held.
                result['file_name'] = resolve_mui_reference(result['file_name'])
                
                # Extract extension blocks if present
                if len(item_data) > 0x4E:
                    ext_blocks = _extract_extension_blocks(item_data)
                    result['extension_blocks'] = ext_blocks
                    result['mft_record'] = ext_blocks.get('mft_record', 0)
            
            # Network location (0x40-0x4F range)
            elif 0x40 <= type_indicator <= 0x4F:
                result['type'] = 'network'
                network_info = _parse_network_location(item_data)
                result['file_name'] = network_info.get('share_name', '')
                # Store full network path in extension_blocks for reference
                result['extension_blocks'] = {
                    'network_path': network_info.get('network_path', ''),
                    'server_name': network_info.get('server_name', ''),
                    'share_name': network_info.get('share_name', '')
                }
            
            # Drive letter (0x20-0x2F range)
            elif 0x20 <= type_indicator <= 0x2F:
                result['type'] = 'drive'
                drive_letter = _extract_drive_path(item_data)
                result['drive_letter'] = drive_letter
                result['file_name'] = drive_letter  # Use drive letter as file_name
            
            # Any other shell item type. The name is only taken when the item
            # actually carries one: a byte scan over an unrecognised structure
            # invents names like }D"pN and S"M, and a fabricated folder name is
            # worse evidence than an acknowledged gap.
            else:
                names = _extract_filesystem_names(item_data)
                candidate = names.get('long_name', '')
                if is_plausible_name(candidate):
                    result['short_name'] = names.get('short_name', '')
                    result['long_name'] = candidate
                    result['file_name'] = resolve_mui_reference(candidate)
        
        return result
        
    except Exception as e:
        logger.error(f"Error parsing Shell Item ID: {e}")
        return {
            'file_name': '',
            'short_name': '',
            'long_name': '',
            'type': 'unknown',
            'drive_letter': '',
            'special_folder': '',
            'mft_record': 0,
            'extension_blocks': {}
        }


def _extract_filesystem_path(item_data: bytes) -> str:
    """
    Extract path component from filesystem Shell Item ID.
    
    DEPRECATED: Use _extract_filesystem_names() instead for enhanced metadata.
    This function is kept for backward compatibility.
    
    Args:
        item_data: Binary data for a single Shell Item ID
    
    Returns:
        Path component string or empty string
    """
    try:
        names = _extract_filesystem_names(item_data)
        # Return long name if available, otherwise short name
        return names.get('long_name', '') or names.get('short_name', '')
    except Exception as e:
        logger.error(f"Error extracting filesystem path: {e}")
        return ""


def find_extension_block(item_data: bytes, signature: int = 0xBEEF0004):
    """Locate a Shell Item extension block by its signature.

    The last two bytes of a file-entry item hold the offset of its first
    extension block; each block starts [size:2][version:2][signature:4] and the
    blocks run consecutively from there.

    Returns (offset, size, version) or (None, 0, 0).

    Located by signature, never by an assumed offset. Assuming the layout is
    what produced the name bug this replaced: a shell item's fields move with
    its version and its name length, so a fixed offset is right only by luck.
    """
    try:
        if len(item_data) < 8:
            return (None, 0, 0)
        first = struct.unpack_from('<H', item_data, len(item_data) - 2)[0]
        offset = first
        # Walk the chain rather than trusting the first block to be the one we
        # want - 0xBEEF0026 (a date block) commonly precedes 0xBEEF0004.
        while 0 < offset < len(item_data) - 8:
            size, version, sig = struct.unpack_from('<HHI', item_data, offset)
            if size < 8:
                break
            if sig == signature:
                return (offset, size, version)
            offset += size
        return (None, 0, 0)
    except Exception as e:
        logger.debug(f"Extension block scan failed: {e}")
        return (None, 0, 0)


def _beef0004_name_offset(version: int) -> int:
    """Where the long name starts inside a 0xBEEF0004 block, by version.

    The header grows with the version, so the name offset is computed, not
    guessed. Verified against live data: a version 9 block puts the name at
    0x2E, which is where `4orensics.case2` actually sits.

        0x00 size, 0x02 version, 0x04 signature
        0x08 creation (FAT, 4), 0x0C last access (FAT, 4), 0x10 unknown (2)
        v >= 7: unknown (2) + file reference (8) + unknown (8)
        v >= 3: long string size (2)
        v >= 9: unknown (4)
        v >= 8: unknown (4)
        then the UTF-16 name
    """
    offset = 0x24 if version >= 7 else 0x12
    if version >= 3:
        offset += 2
    if version >= 9:
        offset += 4
    if version >= 8:
        offset += 4
    return offset


def _extract_filesystem_names(item_data: bytes) -> dict:
    """
    Extract both short and long names from a filesystem Shell Item ID.

    Args:
        item_data: Binary data for a single Shell Item ID

    Returns:
        Dictionary containing:
            - 'short_name': 8.3 format name (if available)
            - 'long_name': Unicode long name (if available)

    Both names are read from where the structure says they are. The previous
    implementation scanned from offset 0x40 in 2-byte steps, scored whatever
    looked filename-like, and kept the best guess - which produced names that
    did not match the disk. It could only start a candidate on A-Z/a-z, so
    `4orensics.case2` was stored as `orensics.case2`; a compensating "skip a
    character if it looks like xName" rule pushed other names the other way
    (`extracted_artifacts` gained a leading backtick), and raw structure bytes
    such as `S"M` and `}D"pN` could outscore the real name entirely.
    """
    try:
        result = {'short_name': '', 'long_name': ''}

        # Primary name at 0x0E, NUL-terminated. ASCII unless the item's
        # attribute flags mark it Unicode.
        if len(item_data) > 0x0E:
            unicode_name = bool(len(item_data) > 0x0D and (item_data[0x0C] & 0x04))
            body = item_data[0x0E:]
            if unicode_name:
                end = 0
                while end + 1 < len(body) and body[end:end + 2] != b'\x00\x00':
                    end += 2
                primary = body[:end].decode('utf-16-le', errors='ignore')
            else:
                primary = body.split(b'\x00')[0].decode('ascii', errors='ignore')
            primary = primary.strip()
            if primary:
                result['short_name'] = primary

        # Long name from the 0xBEEF0004 extension block.
        offset, size, version = find_extension_block(item_data, 0xBEEF0004)
        if offset is not None:
            block = item_data[offset:offset + size]
            name_at = _beef0004_name_offset(version)
            if 0 < name_at < len(block):
                raw = block[name_at:]
                end = 0
                while end + 1 < len(raw) and raw[end:end + 2] != b'\x00\x00':
                    end += 2
                long_name = raw[:end].decode('utf-16-le', errors='ignore').strip()
                if long_name:
                    result['long_name'] = long_name

        # No extension block (older items) - the primary name is the only name.
        if not result['long_name']:
            result['long_name'] = result['short_name']

        return result

    except Exception as e:
        logger.error(f"Error extracting filesystem names: {e}")
        return {'short_name': '', 'long_name': ''}


def _extract_network_path(item_data: bytes) -> str:
    """
    Extract path component from network Shell Item ID.
    
    Args:
        item_data: Binary data for a single Shell Item ID
    
    Returns:
        Network path component or empty string
    """
    try:
        # Network items typically contain UNC paths
        # Try to extract readable strings
        for offset in range(0x04, len(item_data) - 2):
            # Look for null-terminated ASCII strings
            if 0x20 <= item_data[offset] <= 0x7E:
                ascii_str = ""
                for i in range(offset, len(item_data)):
                    if item_data[i] == 0:
                        break
                    if 0x20 <= item_data[i] <= 0x7E:
                        ascii_str += chr(item_data[i])
                    else:
                        break
                
                if len(ascii_str) > 2:
                    return ascii_str
        
        return ""
        
    except Exception as e:
        logger.error(f"Error extracting network path: {e}")
        return ""


def _extract_drive_path(item_data: bytes) -> str:
    """
    Extract drive letter from drive Shell Item ID.
    
    Drive Shell Items (type 0x20-0x2F) contain drive letter information.
    Common patterns:
    - ASCII "C:\" at various offsets
    - Drive letter followed by colon (0x3A)
    - Sometimes in Unicode format
    
    Args:
        item_data: Binary data for a single Shell Item ID
    
    Returns:
        Drive letter (e.g., "C:") or empty string
    """
    try:
        if len(item_data) < 4:
            return ""
        
        # Method 1: Look for ASCII drive letter pattern "X:" anywhere in the first 32 bytes
        for offset in range(0x03, min(len(item_data) - 1, 0x30)):
            if (0x41 <= item_data[offset] <= 0x5A or  # A-Z
                0x61 <= item_data[offset] <= 0x7A):    # a-z
                if offset + 1 < len(item_data) and item_data[offset + 1] == 0x3A:  # ':'
                    drive_letter = chr(item_data[offset]).upper() + ":"
                    logger.debug(f"Found drive letter at offset {offset}: {drive_letter}")
                    return drive_letter
        
        # Method 2: Check common fixed offsets for drive letters
        # Offset 0x03 is common for drive Shell Items
        common_offsets = [0x03, 0x04, 0x05, 0x06, 0x0E, 0x0F]
        for offset in common_offsets:
            if offset < len(item_data):
                byte_val = item_data[offset]
                if 0x41 <= byte_val <= 0x5A or 0x61 <= byte_val <= 0x7A:  # A-Z or a-z
                    # Check if next byte is colon or if this looks like a drive letter
                    if offset + 1 < len(item_data) and item_data[offset + 1] == 0x3A:
                        drive_letter = chr(byte_val).upper() + ":"
                        logger.debug(f"Found drive letter at fixed offset {offset}: {drive_letter}")
                        return drive_letter
        
        # Method 3: Try to decode as string and look for drive pattern
        try:
            # Try ASCII decode
            ascii_str = item_data[3:min(len(item_data), 20)].decode('ascii', errors='ignore')
            for i, char in enumerate(ascii_str):
                if char.isalpha() and i + 1 < len(ascii_str) and ascii_str[i + 1] == ':':
                    drive_letter = char.upper() + ":"
                    logger.debug(f"Found drive letter in ASCII string: {drive_letter}")
                    return drive_letter
        except:
            pass
        
        # Method 4: Check for Unicode drive letter (UTF-16-LE)
        try:
            for offset in range(0x03, min(len(item_data) - 3, 0x20), 2):
                if item_data[offset + 1] == 0:  # High byte is 0 (ASCII in UTF-16-LE)
                    byte_val = item_data[offset]
                    if 0x41 <= byte_val <= 0x5A or 0x61 <= byte_val <= 0x7A:
                        if offset + 2 < len(item_data) and item_data[offset + 2] == 0x3A and item_data[offset + 3] == 0:
                            drive_letter = chr(byte_val).upper() + ":"
                            logger.debug(f"Found Unicode drive letter at offset {offset}: {drive_letter}")
                            return drive_letter
        except:
            pass
        
        logger.debug(f"No drive letter found in Shell Item (size={len(item_data)}, type={item_data[2] if len(item_data) > 2 else 'N/A'})")
        return ""
        
    except Exception as e:
        logger.error(f"Error extracting drive path: {e}")
        return ""


def _extract_generic_path(item_data: bytes) -> str:
    """
    Extract any readable string from Shell Item ID.
    
    Args:
        item_data: Binary data for a single Shell Item ID
    
    Returns:
        Extracted string or empty string
    """
    try:
        # Try to find any readable ASCII or Unicode strings
        
        # Try ASCII first
        for offset in range(0x03, len(item_data) - 2):
            if 0x20 <= item_data[offset] <= 0x7E:
                ascii_str = ""
                for i in range(offset, min(len(item_data), offset + 50)):
                    if item_data[i] == 0:
                        break
                    if 0x20 <= item_data[i] <= 0x7E:
                        ascii_str += chr(item_data[i])
                    else:
                        break
                
                if len(ascii_str) > 2:
                    return ascii_str
        
        # Try Unicode
        for offset in range(0x03, len(item_data) - 4, 2):
            if item_data[offset] != 0 and item_data[offset + 1] == 0:
                unicode_str = extract_unicode_string(item_data, offset)
                if unicode_str and len(unicode_str) > 2:
                    return unicode_str
        
        return ""
        
    except Exception as e:
        logger.error(f"Error extracting generic path: {e}")
        return ""


def parse_bam_entry(value_name: str, binary_data: bytes) -> dict:
    """
    Parse BAM binary entry to extract execution path and timestamp.
    
    BAM (Background Activity Moderator) entries track program execution:
    - Value name contains the full executable path
    - Binary data contains an 8-byte FILETIME timestamp (last execution time)
    
    Args:
        value_name: Registry value name containing the executable path
        binary_data: Binary data containing FILETIME timestamp
    
    Returns:
        Dictionary containing:
            - 'process_path': Full executable path from value name
            - 'last_execution': ISO 8601 formatted execution timestamp
            - 'raw_data': Original binary data (for fallback)
        
    Raises:
        ValueError: If binary data is invalid
    """
    try:
        if not value_name:
            logger.warning("Empty value name provided to parse_bam_entry")
            return {
                'process_path': '',
                'last_execution': '',
                'raw_data': binary_data
            }
        
        # Extract process path from value name
        # Value name typically contains the full executable path
        process_path = value_name.strip()
        
        # Extract FILETIME timestamp from binary data
        last_execution = ''
        if binary_data and len(binary_data) >= 8:
            # First 8 bytes contain the FILETIME timestamp
            last_execution = parse_filetime(binary_data[:8])
        else:
            logger.warning(f"Invalid BAM binary data: expected at least 8 bytes, got {len(binary_data) if binary_data else 0}")
        
        result = {
            'process_path': process_path,
            'last_execution': last_execution,
            'raw_data': binary_data
        }
        
        logger.debug(f"Parsed BAM entry: path={process_path}, execution={last_execution}")
        return result
        
    except Exception as e:
        logger.error(f"Error parsing BAM entry: {e}")
        return {
            'process_path': value_name if value_name else '',
            'last_execution': '',
            'raw_data': binary_data
        }


def parse_dam_entry(value_name: str, binary_data: bytes) -> dict:
    """
    Parse DAM binary entry to extract execution path and timestamp.
    
    DAM (Desktop Activity Moderator) entries track application execution:
    - Value name may contain the full executable path
    - Binary data contains an 8-byte FILETIME timestamp (last execution time)
    - Binary data may also contain UTF-16-LE encoded application paths
    
    Args:
        value_name: Registry value name (may contain executable path)
        binary_data: Binary data containing FILETIME timestamp and possibly application path
    
    Returns:
        Dictionary containing:
            - 'app_name': Application name extracted from path
            - 'process_path': Full executable path
            - 'last_execution': ISO 8601 formatted execution timestamp
            - 'raw_data': Original binary data (for fallback)
        
    Raises:
        ValueError: If binary data is invalid
    """
    try:
        if not value_name and not binary_data:
            logger.warning("Empty value name and binary data provided to parse_dam_entry")
            return {
                'app_name': '',
                'process_path': '',
                'last_execution': '',
                'raw_data': binary_data
            }
        
        # Initialize variables
        process_path = ''
        app_name = ''
        last_execution = ''
        
        # Extract FILETIME timestamp from binary data (first 8 bytes)
        if binary_data and len(binary_data) >= 8:
            last_execution = parse_filetime(binary_data[:8])
        else:
            logger.warning(f"Invalid DAM binary data: expected at least 8 bytes, got {len(binary_data) if binary_data else 0}")
        
        # Try to extract process path from value name first
        if value_name:
            process_path = value_name.strip()
            
            # Extract application name from the path
            # Get the filename without extension
            if '\\' in process_path:
                filename = process_path.split('\\')[-1]
            else:
                filename = process_path
            
            # Remove .exe extension if present
            if filename.lower().endswith('.exe'):
                app_name = filename[:-4]
            else:
                app_name = filename
        
        # If no path in value name, try to extract from binary data
        # Some DAM entries have UTF-16-LE encoded paths after the FILETIME
        if not process_path and binary_data and len(binary_data) > 8:
            # Try to extract Unicode string from binary data after FILETIME
            try:
                # Skip the first 8 bytes (FILETIME)
                path_data = binary_data[8:]
                
                # Check if there's enough data for a Unicode string
                if len(path_data) >= 4:
                    # Try to extract UTF-16-LE encoded path
                    extracted_path = extract_unicode_string(path_data, offset=0)
                    
                    if extracted_path and len(extracted_path) > 0:
                        process_path = extracted_path
                        
                        # Extract application name from the extracted path
                        if '\\' in process_path:
                            filename = process_path.split('\\')[-1]
                        else:
                            filename = process_path
                        
                        # Remove .exe extension if present
                        if filename.lower().endswith('.exe'):
                            app_name = filename[:-4]
                        else:
                            app_name = filename
            except Exception as e:
                logger.debug(f"Could not extract path from DAM binary data: {e}")
        
        result = {
            'app_name': app_name,
            'process_path': process_path,
            'last_execution': last_execution,
            'raw_data': binary_data
        }
        
        logger.debug(f"Parsed DAM entry: app={app_name}, path={process_path}, execution={last_execution}")
        return result
        
    except Exception as e:
        logger.error(f"Error parsing DAM entry: {e}")
        return {
            'app_name': '',
            'process_path': value_name if value_name else '',
            'last_execution': '',
            'raw_data': binary_data
        }


def parse_recentdocs_entry(binary_data: bytes) -> str:
    """
    Parse RecentDocs binary entry to extract filename.
    
    RecentDocs entries contain Unicode filenames in binary structures.
    The data may be:
    1. UTF-16-LE encoded filename strings
    2. Shell Item ID structures containing file information
    3. Mixed format with both Unicode strings and binary padding
    
    Args:
        binary_data: Binary data from RecentDocs registry value
    
    Returns:
        Clean filename string without binary padding or control characters
        
    Raises:
        ValueError: If binary data is invalid
    """
    try:
        if not binary_data:
            logger.warning("Empty binary data provided to parse_recentdocs_entry")
            return ""
        
        # Try to extract Unicode string first (most common format)
        # RecentDocs typically stores filenames as null-terminated UTF-16-LE strings
        filename = extract_unicode_string(binary_data, offset=0)
        
        # If we got a valid filename, clean it up and return
        if filename and len(filename) > 0:
            # Remove any control characters or binary artifacts
            cleaned_filename = ''.join(char for char in filename if char.isprintable())
            
            # Remove trailing/leading whitespace
            cleaned_filename = cleaned_filename.strip()
            
            if cleaned_filename:
                logger.debug(f"Parsed RecentDocs entry (Unicode): {cleaned_filename}")
                return cleaned_filename
        
        # If Unicode extraction failed, try parsing as Shell Item ID
        # Some RecentDocs entries use Shell Item ID structures
        shell_item_result = parse_shell_item_id(binary_data)
        shell_path = shell_item_result.get('path', '')
        
        if shell_path:
            # Extract just the filename from the full path
            if '\\' in shell_path:
                filename = shell_path.split('\\')[-1]
            else:
                filename = shell_path
            
            # Clean up the filename
            cleaned_filename = ''.join(char for char in filename if char.isprintable())
            cleaned_filename = cleaned_filename.strip()
            
            if cleaned_filename:
                logger.debug(f"Parsed RecentDocs entry (Shell Item ID): {cleaned_filename}")
                return cleaned_filename
        
        # If both methods failed, try to extract any readable ASCII/Unicode strings
        # Look for the longest readable string in the binary data
        best_string = ""
        
        # Try to find Unicode strings
        for offset in range(0, len(binary_data) - 4, 2):
            # Check if this looks like the start of a Unicode string
            if binary_data[offset] != 0 and (offset + 1 >= len(binary_data) or binary_data[offset + 1] == 0):
                try:
                    test_string = extract_unicode_string(binary_data, offset)
                    if test_string and len(test_string) > len(best_string):
                        # Check if it's mostly printable
                        printable_chars = sum(1 for c in test_string if c.isprintable())
                        if printable_chars > len(test_string) * 0.7:  # At least 70% printable
                            best_string = test_string
                except:
                    continue
        
        # Try to find ASCII strings
        for offset in range(0, len(binary_data) - 2):
            if 0x20 <= binary_data[offset] <= 0x7E:  # Printable ASCII
                ascii_string = ""
                for i in range(offset, min(len(binary_data), offset + 100)):
                    if 0x20 <= binary_data[i] <= 0x7E:
                        ascii_string += chr(binary_data[i])
                    else:
                        break
                
                if len(ascii_string) > len(best_string):
                    best_string = ascii_string
        
        if best_string:
            # Clean up the string
            cleaned_filename = ''.join(char for char in best_string if char.isprintable())
            cleaned_filename = cleaned_filename.strip()
            
            if cleaned_filename:
                logger.debug(f"Parsed RecentDocs entry (fallback): {cleaned_filename}")
                return cleaned_filename
        
        # If all parsing methods failed, return empty string
        logger.warning(f"Could not parse RecentDocs entry, binary data length: {len(binary_data)}")
        return ""
        
    except Exception as e:
        logger.error(f"Error parsing RecentDocs entry: {e}")
        return ""


def decode_rot13(encoded_str: str) -> str:
    """
    Decode ROT13-encoded string.
    
    ROT13 is a simple letter substitution cipher that rotates each letter
    by 13 positions in the alphabet. It's used by Windows UserAssist to
    obfuscate program execution paths.
    
    Args:
        encoded_str: ROT13-encoded string
    
    Returns:
        Decoded string with letters rotated back 13 positions
    """
    try:
        if not encoded_str:
            return ""
        
        decoded = []
        for char in encoded_str:
            if 'A' <= char <= 'Z':
                # Uppercase letters
                decoded.append(chr((ord(char) - ord('A') + 13) % 26 + ord('A')))
            elif 'a' <= char <= 'z':
                # Lowercase letters
                decoded.append(chr((ord(char) - ord('a') + 13) % 26 + ord('a')))
            else:
                # Non-letter characters remain unchanged
                decoded.append(char)
        
        return ''.join(decoded)
        
    except Exception as e:
        logger.error(f"Error decoding ROT13: {e}")
        return encoded_str


def parse_userassist_entry(value_name: str, binary_data: bytes) -> dict:
    """
    Parse UserAssist binary entry to extract program execution information.
    
    UserAssist entries track program execution with timestamps and run counts.
    The value name is ROT13-encoded and the binary data contains execution metadata.
    
    Binary Structure (Windows 7/8, Version 5):
        Offset  Size  Description
        ------  ----  -----------
        0x00    4     Version number (0x00000005)
        0x04    4     Run count (raw value, subtract 5 if > 5 for actual count)
        0x08    4     Application focus count
        0x0C    4     Application focus time (milliseconds)
        0x10    48    Reserved/padding
        0x3C    8     Last execution time (FILETIME) - offset 60
        
        Total: 72 bytes (0x48)
    
    Binary Structure (Windows 10/11, Version 63):
        Offset  Size  Description
        ------  ----  -----------
        0x00    4     Version number (0x0000003F / 63)
        0x04    4     Run count (direct value, no adjustment needed)
        0x08    4     Application focus count
        0x0C    4     Application focus time (milliseconds)
        0x10    44    Reserved/padding (contains float values)
        0x3C    8     Last execution time (FILETIME) - offset 60
        
        Total: 72 bytes (0x48)
    
    Binary Structure (Windows XP/Vista, Version 3):
        Offset  Size  Description
        ------  ----  -----------
        0x00    4     Version number (0x00000003)
        0x04    4     Run count
        0x08    8     Last execution time (FILETIME)
    
    Args:
        value_name: ROT13-encoded program path
        binary_data: Binary data containing execution metadata
    
    Returns:
        Dictionary containing:
            - 'program_path': Decoded program path
            - 'run_count': Number of times program was executed
            - 'last_execution': ISO 8601 formatted last execution timestamp
            - 'focus_count': Number of times program had focus (Version 5 only)
            - 'focus_time': Total focus time in milliseconds (Version 5 only)
    
    Raises:
        ValueError: If binary data is invalid
    """
    try:
        # Decode ROT13-encoded program path
        program_path = decode_rot13(value_name)
        
        # Initialize result with defaults
        result = {
            'program_path': program_path,
            'run_count': 0,
            'last_execution': '',
            'focus_count': 0,
            'focus_time': 0
        }
        
        # Validate binary data
        if not binary_data or len(binary_data) < 16:
            logger.warning(f"Invalid UserAssist binary data for {program_path}: expected at least 16 bytes, got {len(binary_data) if binary_data else 0}")
            return result
        
        # Parse version number (first 4 bytes)
        version = struct.unpack('<I', binary_data[0:4])[0]
        
        # Log full binary data for debugging
        logger.info(f"UserAssist entry {program_path}: version={version}, data_length={len(binary_data)}")
        logger.info(f"  First 72 bytes (hex): {binary_data[:72].hex() if len(binary_data) >= 72 else binary_data.hex()}")
        
        if version == 5:
            # Windows 7/8/10/11 format (72 bytes total)
            # The actual structure for Version 5 is more complex
            if len(binary_data) >= 72:
                # Offsets for Version 5 (based on actual Windows structure)
                raw_run_count = struct.unpack('<I', binary_data[4:8])[0]
                result['focus_count'] = struct.unpack('<I', binary_data[8:12])[0]
                result['focus_time'] = struct.unpack('<I', binary_data[12:16])[0]
                
                # For Version 5, run count needs adjustment (subtract 5 if > 5)
                result['run_count'] = max(0, raw_run_count - 5) if raw_run_count > 5 else raw_run_count
                
                # Last execution time is at offset 60 (0x3C) for Version 5, not offset 16
                result['last_execution'] = parse_filetime(binary_data[60:68])
                
                logger.info(f"  Parsed V5: raw_count={raw_run_count}, adjusted_count={result['run_count']}, focus_count={result['focus_count']}, focus_time={result['focus_time']}, last_exec={result['last_execution']}")
            else:
                logger.warning(f"UserAssist Version 5 data too short: expected 72 bytes, got {len(binary_data)}")
        
        elif version == 3:
            # Windows XP/Vista format (16 bytes)
            if len(binary_data) >= 16:
                result['run_count'] = struct.unpack('<I', binary_data[4:8])[0]
                result['last_execution'] = parse_filetime(binary_data[8:16])
                logger.info(f"  Parsed V3: count={result['run_count']}, last_exec={result['last_execution']}")
            else:
                logger.warning(f"UserAssist Version 3 data too short: expected 16 bytes, got {len(binary_data)}")
        
        elif version == 63 or version == 0x3F:
            # Windows 10/11 format (72 bytes) - Version 63 (0x3F)
            # This is the newer format used in Windows 10 and later
            if len(binary_data) >= 68:
                # Parse run count at offset 4
                result['run_count'] = struct.unpack('<I', binary_data[4:8])[0]
                
                # Parse focus count at offset 8
                result['focus_count'] = struct.unpack('<I', binary_data[8:12])[0]
                
                # Parse focus time at offset 12
                result['focus_time'] = struct.unpack('<I', binary_data[12:16])[0]
                
                # Last execution time is at offset 60 (0x3C) for Version 63
                result['last_execution'] = parse_filetime(binary_data[60:68])
                
                logger.info(f"  Parsed V63: count={result['run_count']}, focus_count={result['focus_count']}, focus_time={result['focus_time']}, last_exec={result['last_execution']}")
            else:
                logger.warning(f"UserAssist Version 63 data too short: expected 68 bytes, got {len(binary_data)}")
        
        elif version == 6:
            # Windows 11 format (72+ bytes) - Version 6
            # Similar structure to Version 5 but with extended data
            if len(binary_data) >= 72:
                # Parse run count at offset 4
                raw_run_count = struct.unpack('<I', binary_data[4:8])[0]
                
                # Parse focus count at offset 8
                result['focus_count'] = struct.unpack('<I', binary_data[8:12])[0]
                
                # Parse focus time at offset 12
                result['focus_time'] = struct.unpack('<I', binary_data[12:16])[0]
                
                # For Version 6, run count may need adjustment similar to Version 5
                result['run_count'] = max(0, raw_run_count - 5) if raw_run_count > 5 else raw_run_count
                
                # Last execution time is at offset 60 (0x3C) for Version 6
                result['last_execution'] = parse_filetime(binary_data[60:68])
                
                logger.info(f"  Parsed V6: raw_count={raw_run_count}, adjusted_count={result['run_count']}, focus_count={result['focus_count']}, focus_time={result['focus_time']}, last_exec={result['last_execution']}")
            else:
                logger.warning(f"UserAssist Version 6 data too short: expected 72 bytes, got {len(binary_data)}")
        
        elif len(binary_data) >= 68:
            # Any other version number, but the Windows 7+ record shape.
            #
            # The version DWORD was allow-listed against 3, 5, 6 and 63, so a
            # build reporting anything else fell through here and every field
            # was discarded - silently, because the entry still produced a row.
            # Windows 11 writes version 26 (0x1A) with the identical 72-byte
            # layout: run count at 0x04, focus count at 0x08, focus time at
            # 0x0C, float padding at 0x10, FILETIME at 0x3C. Verified against
            # 316 live entries, 234 of which carry a timestamp that lands in a
            # plausible range and matches observed use.
            #
            # Trust the record length, not the version number: a version we have
            # never seen is far more likely to share this shape than to be
            # unreadable, and reading it costs nothing if the values are zero.
            result['run_count'] = struct.unpack('<I', binary_data[4:8])[0]
            result['focus_count'] = struct.unpack('<I', binary_data[8:12])[0]
            result['focus_time'] = struct.unpack('<I', binary_data[12:16])[0]
            result['last_execution'] = parse_filetime(binary_data[60:68])
            logger.info(
                f"  Parsed UserAssist version {version} using the 72-byte "
                f"layout: count={result['run_count']}, "
                f"focus_count={result['focus_count']}, "
                f"last_exec={result['last_execution']}")

        else:
            logger.warning(
                f"Unknown UserAssist version {version} and unusable length "
                f"{len(binary_data)}")

        logger.debug(f"Parsed UserAssist entry: path={program_path}, count={result['run_count']}, execution={result['last_execution']}")
        return result
        
    except Exception as e:
        logger.error(f"Error parsing UserAssist entry: {e}")
        return {
            'program_path': decode_rot13(value_name) if value_name else '',
            'run_count': 0,
            'last_execution': '',
            'focus_count': 0,
            'focus_time': 0
        }



# The evidence machine's timezone bias, in signed minutes, for the DOS
# date/time readings that carry no zone of their own. Set once per parse by
# set_evidence_bias(); zero means "not known", and a DOS value is then left on
# the machine's own wall clock rather than shifted by a guess.
_dos_bias_minutes = 0


def set_evidence_bias(bias):
    """Record the evidence machine's UTC bias for this parse.

    Called once, after TimeZoneInfo has been read, and before any shell item is
    decoded. Returns the signed minutes it will use so the caller can record
    which offset was applied.
    """
    global _dos_bias_minutes
    _dos_bias_minutes = signed_bias(bias)
    return _dos_bias_minutes


def evidence_bias():
    """The bias in force, in signed minutes. Zero means not known."""
    return _dos_bias_minutes


def _convert_dos_datetime(dos_time: int, bias=None) -> str:
    """
    Convert DOS datetime format to ISO 8601 string.
    
    DOS datetime format (32-bit):
    - Bits 0-4: Day (1-31)
    - Bits 5-8: Month (1-12)
    - Bits 9-15: Year (relative to 1980)
    - Bits 16-20: Seconds/2 (0-29)
    - Bits 21-26: Minutes (0-59)
    - Bits 27-31: Hours (0-23)
    
    Args:
        dos_time: 32-bit DOS datetime value
    
    Returns:
        ISO 8601 formatted datetime string
    """
    try:
        if dos_time == 0 or dos_time == 0xFFFFFFFF:
            return ""
        
        date = dos_time & 0xFFFF
        time = (dos_time >> 16) & 0xFFFF
        
        day = date & 0x1F
        month = (date >> 5) & 0x0F
        year = ((date >> 9) & 0x7F) + 1980
        
        seconds = (time & 0x1F) * 2
        minutes = (time >> 5) & 0x3F
        hours = (time >> 11) & 0x1F
        
        # Validate values - basic range check
        if not (1 <= day <= 31 and 1 <= month <= 12 and 1980 <= year <= 2100):
            return ""
        if not (0 <= hours <= 23 and 0 <= minutes <= 59 and 0 <= seconds <= 59):
            return ""
        
        # Additional validation: Reject dates that are clearly garbage
        # Check if the date/time components make sense together
        # Reject if day=0 or month=0 (invalid)
        if day == 0 or month == 0:
            logger.debug(f"Rejecting invalid DOS datetime: day={day}, month={month}")
            return ""
        
        # Reject dates beyond 2035 as likely garbage (allows some future dates but not too far)
        if year > 2035:
            logger.debug(f"Rejecting suspicious DOS datetime: year={year} (likely garbage data)")
            return ""
        
        # A DOS date/time is the EVIDENCE machine's local wall clock. It has
        # no timezone in it and never had one, so stamping tzinfo=timezone.utc
        # here does not convert anything - it relabels a local reading as UTC
        # and every Shellbag timestamp in the case is then wrong by the
        # evidence machine's offset.
        #
        # Windows defines local = UTC + bias, so UTC = local + bias. With the
        # bias known the value becomes a real UTC moment; without it the local
        # reading is returned unchanged and the caller records that it is
        # local, because inventing a zone is the error being fixed.
        dt = datetime(year, month, day, hours, minutes, seconds,
                      tzinfo=timezone.utc)
        offset = _dos_bias_minutes if bias is None else signed_bias(bias)
        if offset:
            dt = dt + timedelta(minutes=offset)
        return format_forensic_timestamp(dt)
        
    except Exception as e:
        # Invalid date (e.g., Feb 30) or other error
        logger.debug(f"DOS datetime conversion failed: {e}")
        return ""


def _extract_extension_blocks(item_data: bytes) -> dict:
    """
    Extract metadata from Shell Item extension blocks.
    
    Extension blocks contain additional timestamps and NTFS metadata.
    They are present when the Shell Item size is greater than 0x4E bytes.
    
    Args:
        item_data: Shell Item binary data
    
    Returns:
        dict: {
            'creation_time': str,      # FILETIME at offset 0x18
            'access_time': str,        # FILETIME at offset 0x20
            'write_time': str,         # FILETIME at offset 0x28
            'mft_record': int,         # NTFS file reference
            'mft_sequence': int        # NTFS sequence number
        }
    """
    try:
        result = {
            'creation_time': '',
            'access_time': '',
            'write_time': '',
            'mft_record': 0,
            'mft_sequence': 0
        }
        
        # Check if extension blocks are present (size > 0x4E)
        if len(item_data) <= 0x4E:
            return result
        
        # Everything below comes from the LOCATED 0xBEEF0004 block, not from
        # assumed offsets into the item.
        #
        # The previous version read 8-byte FILETIMEs at item offsets 0x18/0x20/
        # 0x28. The block stores creation and last-access as 4-byte FAT
        # date-times at block offsets 0x08 and 0x0C, and the item's own fields
        # move with its name length - so those reads landed inside the filename
        # and the 1980-2100 sanity range then discarded the result. That is why
        # creation_time was empty on 750 of 750 Shellbags rows and access_time
        # on 748: the check was rejecting garbage rather than the parse working.
        blk_off, blk_size, blk_ver = find_extension_block(item_data, 0xBEEF0004)
        if blk_off is None:
            return result

        block = item_data[blk_off:blk_off + blk_size]

        # 0x08 creation (FAT), 0x0C last access (FAT)
        if len(block) >= 0x10:
            try:
                created = struct.unpack_from('<I', block, 0x08)[0]
                accessed = struct.unpack_from('<I', block, 0x0C)[0]
                result['creation_time'] = _convert_dos_datetime(created)
                result['access_time'] = _convert_dos_datetime(accessed)
            except Exception:
                pass

        # NTFS file reference: version 7 and later only, at block offset 0x14.
        # 6 bytes record number + 2 bytes sequence.
        #
        # Only recorded when it can actually BE an NTFS reference. The field is
        # present whatever the volume's filesystem, and on exFAT it holds a
        # directory-entry value instead - storing that as mft_record_number
        # labelled 22 of 618 Shellbags rows on this machine with a number that
        # is not an MFT record and cannot be looked up as one.
        if blk_ver >= 7 and len(block) >= 0x1C:
            try:
                mft_record = struct.unpack('<Q', block[0x14:0x1A] + b'\x00\x00')[0]
                mft_sequence = struct.unpack_from('<H', block, 0x1A)[0]
                if is_plausible_mft_record(mft_record):
                    result['mft_record'] = mft_record
                    result['mft_sequence'] = mft_sequence
            except Exception:
                pass
        
        return result
        
    except Exception as e:
        logger.error(f"Error extracting extension blocks: {e}")
        return {
            'creation_time': '',
            'access_time': '',
            'write_time': '',
            'mft_record': 0,
            'mft_sequence': 0
        }


def _parse_network_location(item_data: bytes) -> dict:
    """
    Parse network location Shell Item to extract UNC path components.
    
    Args:
        item_data: Network Shell Item binary data (type 0x40-0x4F)
    
    Returns:
        dict: {
            'network_path': str,   # Full UNC path (\\\\server\\share)
            'server_name': str,    # Server name
            'share_name': str      # Share name
        }
    """
    try:
        result = {
            'network_path': '',
            'server_name': '',
            'share_name': ''
        }
        
        # Network items typically contain UNC paths
        # Try to extract readable ASCII strings
        strings_found = []
        
        for offset in range(0x04, len(item_data) - 2):
            # Look for null-terminated ASCII strings
            if 0x20 <= item_data[offset] <= 0x7E:
                ascii_str = ""
                for i in range(offset, len(item_data)):
                    if item_data[i] == 0:
                        break
                    if 0x20 <= item_data[i] <= 0x7E:
                        ascii_str += chr(item_data[i])
                    else:
                        break
                
                if len(ascii_str) > 2:
                    strings_found.append(ascii_str)
        
        # Parse UNC path format (\\\\server\\share)
        if strings_found:
            # First string is often the server name
            if len(strings_found) >= 1:
                result['server_name'] = strings_found[0]
            
            # Second string is often the share name
            if len(strings_found) >= 2:
                result['share_name'] = strings_found[1]
            
            # Reconstruct full UNC path
            if result['server_name'] and result['share_name']:
                result['network_path'] = f"\\\\{result['server_name']}\\{result['share_name']}"
            elif result['server_name']:
                result['network_path'] = f"\\\\{result['server_name']}"
        
        return result
        
    except Exception as e:
        logger.error(f"Error parsing network location: {e}")
        return {
            'network_path': '',
            'server_name': '',
            'share_name': ''
        }


def _extract_folder_attributes(binary_data: bytes) -> dict:
    """
    Extract Windows folder attributes from Shell Item ID.
    
    Args:
        binary_data: Shell Item ID binary data
    
    Returns:
        Dictionary with attribute flags and human-readable list
    """
    try:
        if len(binary_data) < 5:
            return {'flags': 0, 'attributes': []}
        
        attr_flags = binary_data[4]
        attributes = []
        
        if attr_flags & 0x01:
            attributes.append('readonly')
        if attr_flags & 0x02:
            attributes.append('hidden')
        if attr_flags & 0x04:
            attributes.append('system')
        if attr_flags & 0x10:
            attributes.append('directory')
        if attr_flags & 0x20:
            attributes.append('archive')
        # Add compressed and encrypted flags
        if attr_flags & 0x40:
            attributes.append('compressed')
        if attr_flags & 0x80:
            attributes.append('encrypted')
        
        return {'flags': attr_flags, 'attributes': attributes}
        
    except Exception as e:
        logger.error(f"Error extracting attributes: {e}")
        return {'flags': 0, 'attributes': []}


def _format_guid(guid_bytes: bytes) -> str:
    """
    Format GUID bytes to standard GUID string format.
    
    Args:
        guid_bytes: 16 bytes representing a GUID
    
    Returns:
        GUID string in format: XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
    """
    try:
        if len(guid_bytes) != 16:
            return ""
        
        d1 = struct.unpack('<I', guid_bytes[0:4])[0]
        d2 = struct.unpack('<H', guid_bytes[4:6])[0]
        d3 = struct.unpack('<H', guid_bytes[6:8])[0]
        d4 = guid_bytes[8:10]
        d5 = guid_bytes[10:16]
        
        return f"{d1:08X}-{d2:04X}-{d3:04X}-{d4.hex().upper()}-{d5.hex().upper()}"
        
    except Exception:
        return ""


# Special Folder GUIDs
_SPECIAL_FOLDER_GUIDS = {
    '20D04FE0-3AEA-1069-A2D8-08002B30309D': 'My Computer',
    '450D8FBA-AD25-11D0-98A8-0800361B1103': 'My Documents',
    '208D2C60-3AEA-1069-A2D7-08002B30309D': 'My Network Places',
    '645FF040-5081-101B-9F08-00AA002F954E': 'Recycle Bin',
    '871C5380-42A0-1069-A2EA-08002B30309D': 'Internet Explorer',
    'F02C1A0D-BE21-4350-88B0-7367FC96EF3C': 'Network',
    # Known folders a BagMRU tree actually roots on. Without these the root
    # item resolved to nothing, the folder chain lost its absolute start, and
    # the name fell through to a byte scan that produced strings like }D"pN.
    'B4BFCC3A-DB2C-424C-B029-7FE99A87C641': 'Desktop',
    '59031A47-3F72-44A7-89C5-5595FE6B30EE': 'UsersFiles',
    '5E6C858F-0E22-4760-9AFE-EA3317B67173': 'User Profile',
    '374DE290-123F-4565-9164-39C4925E467B': 'Downloads',
    '088E3905-0323-4B02-9826-5D99428E115F': 'Downloads',
    '33E28130-4E1E-4676-835A-98395C3BC3BB': 'Pictures',
    '3ADD1653-EB32-4CB0-BBD7-DFA0ABB5ACCA': 'Pictures',
    'A0953C92-50DC-43BF-BE83-3742FED03C9C': 'Videos',
    'A65D0A4E-C3A0-4C60-8C21-1F9C1F0F1F2A': 'Videos',
    '4BD8D571-6D19-48D3-BE97-422220080E43': 'Music',
    '3DFDF296-DBEC-4FB4-81D1-6A3438BCF4DE': 'Music',
    'FDD39AD0-238F-46AF-ADB4-6C85480369C7': 'Documents',
    'D3162B92-9365-467A-956B-92703ACA08AF': 'Documents',
    '1CF1260C-4DD0-4EBB-811F-33C572699FDE': 'Music',
    '24AD3AD4-A569-4530-98E1-AB02F9417AA8': 'Pictures',
    'F86FA3AB-70D2-4FC7-9C99-FCBF05467F3A': 'Videos',
    '0762D272-C50A-4BB0-A382-697DCD729B80': 'Users',
    '6D809377-6AF0-444B-8957-A3773F02200E': 'Program Files (x64)',
    '7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E': 'Program Files (x86)',
    'F38BF404-1D43-42F2-9305-67DE0B28FC23': 'Windows',
    '1AC14E77-02E7-4E5D-B744-2EB1AE5198B7': 'System32',
    '9E3995AB-1F9C-4F13-B827-48B24B6C7174': 'User Pinned',
    '679F85CB-0220-4080-B29B-5540CC05AAB6': 'Quick Access',
    '18989B1D-99B5-455B-841C-AB7C74E4DDFC': 'Videos',
    'D34A6CA6-62C2-4C34-8A7C-14709C1AD938': 'Common Places',
    '5B934B42-522B-4C34-BBFE-37A3EF7B9C90': 'This Device',
}


def parse_shellbag_entry(binary_data: bytes) -> dict:
    """
    Enhanced Shellbag parser with comprehensive metadata extraction.
    
    Shellbags use Shell Item ID structures to store folder access history,
    including deleted folders and folder view preferences. This enhanced
    version extracts additional forensic metadata.
    
    Args:
        binary_data: Binary data containing Shell Item ID structure(s)
    
    Returns:
        Dictionary containing:
            - 'file_name': Primary file/folder name
            - 'short_name': 8.3 format name
            - 'shell_item_type': Type of shell item (filesystem, network, drive, etc.)
            - 'created_date': Creation timestamp (if available)
            - 'modified_date': Modification timestamp (if available)
            - 'accessed_date': Access timestamp (if available)
            - 'attributes': Comma-separated file attributes (readonly, hidden, etc.)
            - 'file_size': File/folder size in bytes
            - 'special_folder': Special folder name (My Computer, etc.)
            - 'network_share': Network share path (if applicable)
            - 'server_name': Network server name (if applicable)
            - 'share_name': Network share name (if applicable)
            - 'drive_letter': Drive letter (if applicable)
            - 'mft_record_number': NTFS MFT record number for correlation
    
    Raises:
        ValueError: If binary data is invalid
    """
    try:
        if not binary_data:
            logger.warning("Empty binary data provided to parse_shellbag_entry")
            return {
                'file_name': '',
                'short_name': '',
                'shell_item_type': 'unknown',
                'created_date': '',
                'modified_date': '',
                'accessed_date': '',
                'attributes': '',
                'file_size': 0,
                'special_folder': '',
                'network_share': '',
                'server_name': '',
                'share_name': '',
                'drive_letter': '',
                'mft_record_number': 0
            }
        
        # Parse the Shell Item ID structure to extract file/folder information
        shell_item_result = parse_shell_item_id(binary_data)
        
        file_name = shell_item_result.get('file_name', '')
        short_name = shell_item_result.get('short_name', '')
        shell_item_type = shell_item_result.get('type', 'unknown')
        special_folder = shell_item_result.get('special_folder', '')
        drive_letter = shell_item_result.get('drive_letter', '')
        mft_record_number = shell_item_result.get('mft_record', 0)
        
        # Initialize enhanced metadata
        created_date = ''
        modified_date = ''
        accessed_date = ''
        attributes = []
        file_size = 0
        network_share = ''
        server_name = ''
        share_name = ''
        
        # Extract network information from extension_blocks if present
        ext_blocks = shell_item_result.get('extension_blocks', {})
        if ext_blocks:
            network_share = ext_blocks.get('network_path', '')
            server_name = ext_blocks.get('server_name', '')
            share_name = ext_blocks.get('share_name', '')
            
            # Extract timestamps from extension blocks
            if ext_blocks.get('creation_time'):
                created_date = ext_blocks['creation_time']
            if ext_blocks.get('access_time'):
                accessed_date = ext_blocks['access_time']
            if ext_blocks.get('write_time') and not modified_date:
                modified_date = ext_blocks['write_time']
        
        # Process first Shell Item for additional metadata
        if len(binary_data) >= 2:
            size = struct.unpack('<H', binary_data[0:2])[0]
            if size > 2 and len(binary_data) >= size:
                item_data = binary_data[0:size]
                
                if len(item_data) > 2:
                    type_indicator = item_data[2]
                    
                    # Filesystem object - extract attributes, timestamps, and file size
                    if 0x30 <= type_indicator <= 0x3F:
                        # Extract attributes (offset 0x04)
                        # Decode all attribute flags: readonly, hidden, system, directory, archive, compressed, encrypted
                        attr_info = _extract_folder_attributes(item_data)
                        attributes = attr_info['attributes']
                        
                        # Extract DOS timestamp (modified time at offset 0x08)
                        # DOS datetime format: 32-bit value with day, month, year, time
                        if len(item_data) >= 12:
                            dos_time = struct.unpack('<I', item_data[8:12])[0]
                            dos_modified = _convert_dos_datetime(dos_time)
                            # Only use DOS datetime if we don't have FILETIME
                            if dos_modified and not modified_date:
                                modified_date = dos_modified
                        
                        # Extract file size (at offset 0x0C)
                        if len(item_data) >= 16:
                            file_size = struct.unpack('<I', item_data[12:16])[0]
                        
                        # Prioritize FILETIME timestamps over DOS datetime for accuracy
                        # FILETIME format: 64-bit value representing 100-nanosecond intervals since 1601
                        # Common offsets: 0x18 (creation), 0x20 (access), 0x28 (write)
                        if len(item_data) >= 0x50:
                            # Try to extract FILETIME timestamps from extension blocks
                            # Offset 0x18: Creation time
                            # NOTE: Only extract from documented extension block offsets
                            # Validation: 1980-2100 range (reasonable for forensic analysis)
                            if not created_date and len(item_data) >= 0x20:
                                try:
                                    filetime_value = struct.unpack('<Q', item_data[0x18:0x20])[0]
                                    # Validate: not zero, not 0xFFFFFFFFFFFFFFFF, and in reasonable range
                                    if filetime_value > 0 and filetime_value != 0xFFFFFFFFFFFFFFFF:
                                        if 119600064000000000 < filetime_value < 159017088000000000:
                                            created_date = parse_filetime(item_data[0x18:0x20])
                                            logger.debug(f"Extracted creation time from offset 0x18: {created_date}")
                                except:
                                    pass
                            
                            # Offset 0x20: Access time
                            if not accessed_date and len(item_data) >= 0x28:
                                try:
                                    filetime_value = struct.unpack('<Q', item_data[0x20:0x28])[0]
                                    # Validate: not zero, not 0xFFFFFFFFFFFFFFFF, and in reasonable range
                                    if filetime_value > 0 and filetime_value != 0xFFFFFFFFFFFFFFFF:
                                        if 119600064000000000 < filetime_value < 159017088000000000:
                                            accessed_date = parse_filetime(item_data[0x20:0x28])
                                            logger.debug(f"Extracted access time from offset 0x20: {accessed_date}")
                                except:
                                    pass
                            
                            # Offset 0x28: Write/modification time
                            if not modified_date and len(item_data) >= 0x30:
                                try:
                                    filetime_value = struct.unpack('<Q', item_data[0x28:0x30])[0]
                                    # Validate: not zero, not 0xFFFFFFFFFFFFFFFF, and in reasonable range
                                    if filetime_value > 0 and filetime_value != 0xFFFFFFFFFFFFFFFF:
                                        if 119600064000000000 < filetime_value < 159017088000000000:
                                            modified_date = parse_filetime(item_data[0x28:0x30])
                                            logger.debug(f"Extracted modification time from offset 0x28: {modified_date}")
                                except:
                                    pass
        
        # NOTE: Removed fallback timestamp extraction as it causes false positives
        # Shellbags typically only have timestamps in extension blocks (offset 0x18, 0x20, 0x28)
        # or DOS datetime at offset 0x08. Random scanning picks up garbage data.
        # Most Shellbags don't actually contain access/creation times - this is normal.
        
        result = {
            'file_name': file_name,
            'short_name': short_name,
            'shell_item_type': shell_item_type,
            'created_date': created_date,
            'modified_date': modified_date,
            'accessed_date': accessed_date,
            'attributes': ', '.join(attributes) if attributes else '',
            'file_size': file_size,
            'special_folder': special_folder,
            'network_share': network_share,
            'server_name': server_name,
            'share_name': share_name,
            'drive_letter': drive_letter,
            'mft_record_number': mft_record_number
        }
        
        logger.debug(f"Parsed Shellbag entry: name={file_name}, type={shell_item_type}, mft_record={mft_record_number}")
        return result
        
    except Exception as e:
        logger.error(f"Error parsing Shellbag entry: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return {
            'file_name': '',
            'short_name': '',
            'shell_item_type': 'unknown',
            'created_date': '',
            'modified_date': '',
            'accessed_date': '',
            'attributes': '',
            'file_size': 0,
            'special_folder': '',
            'network_share': '',
            'server_name': '',
            'share_name': '',
            'drive_letter': '',
            'mft_record_number': 0
        }



def parse_runmru_entry(value_name: str, value_data: str, mru_list: str) -> dict:
    """
    Parse RunMRU entry to extract command execution information.
    
    RunMRU (Run Most Recently Used) tracks commands executed via the Windows
    Run dialog (Win+R). The MRUList value contains a character sequence that
    indicates the order in which commands were executed.
    
    Args:
        value_name: Registry value name (e.g., 'a', 'b', 'c')
        value_data: Command string (may include parameters)
        mru_list: MRUList string (e.g., 'acb') indicating execution order
    
    Returns:
        Dictionary containing:
            - 'command': Full command string with parameters
            - 'mru_position': Position in MRU list (0 = most recent)
            - 'timestamp': Timestamp (usually None for RunMRU)
    
    Raises:
        ValueError: If parameters are invalid
    """
    try:
        if not value_name or not value_data:
            logger.warning("Empty value name or data provided to parse_runmru_entry")
            return {
                'command': '',
                'mru_position': -1,
                'timestamp': None
            }
        
        # Clean up the command string
        # RunMRU commands may have trailing backslash and number (e.g., "cmd\1")
        command = value_data.strip()
        
        # Remove trailing backslash and number if present
        if '\\' in command and command[-1].isdigit():
            # Find the last backslash
            last_backslash = command.rfind('\\')
            # Check if everything after the backslash is a digit
            if command[last_backslash + 1:].isdigit():
                command = command[:last_backslash]
        
        # Determine MRU position from MRUList
        mru_position = -1
        if mru_list and value_name:
            # The MRUList is a string of characters (e.g., 'acb')
            # Each character corresponds to a value name
            # Position in the string indicates recency (0 = most recent)
            try:
                mru_position = mru_list.index(value_name)
            except ValueError:
                logger.warning(f"Value name '{value_name}' not found in MRUList '{mru_list}'")
                mru_position = -1
        
        result = {
            'command': command,
            'mru_position': mru_position,
            'timestamp': None  # RunMRU typically doesn't store timestamps
        }
        
        logger.debug(f"Parsed RunMRU entry: command={command}, position={mru_position}")
        return result
        
    except Exception as e:
        logger.error(f"Error parsing RunMRU entry: {e}")
        return {
            'command': value_data if value_data else '',
            'mru_position': -1,
            'timestamp': None
        }



def parse_muicache_entry(value_name: str, value_data: str) -> dict:
    """
    Parse MUICache entry to extract application information.
    
    MUICache (Multilingual User Interface Cache) stores application names
    and their full file paths. The value name contains the application path,
    and the value data contains the display name.
    
    Args:
        value_name: Full application path (e.g., "C:\\\\Windows\\\\System32\\\\notepad.exe")
        value_data: Application display name (e.g., "Notepad")
    
    Returns:
        Dictionary containing:
            - 'app_path': Full application file path
            - 'app_name': Application display name
            - 'file_extension': File extension (e.g., 'exe', 'dll')
    
    Raises:
        ValueError: If parameters are invalid
    """
    try:
        if not value_name:
            logger.warning("Empty value name provided to parse_muicache_entry")
            return {
                'app_path': '',
                'app_name': '',
                'file_extension': ''
            }
        
        # Extract application path (value name).
        #
        # A MUICache value name is "<path>.<PropertyName>", not a bare path -
        # Windows stores one value per property of the same executable. Leaving
        # the suffix on made every app_path point at a file that does not exist
        # (0 of 309 resolved on a live machine), turned file_extension into
        # "friendlyappname", stored each program twice, and left MUICache unable
        # to correlate with Prefetch, Amcache, ShimCache or BAM, all of which
        # record the real path.
        app_path = value_name.strip()
        muicache_property = ''
        for suffix in MUICACHE_PROPERTY_SUFFIXES:
            if app_path.lower().endswith(suffix.lower()):
                muicache_property = app_path[-len(suffix):].lstrip('.')
                app_path = app_path[:-len(suffix)]
                break

        # Extract application display name (value data)
        app_name = value_data.strip() if value_data else ''
        
        # If no display name provided, try to extract from path
        if not app_name and app_path:
            # Get the filename from the path
            if '\\' in app_path:
                filename = app_path.split('\\')[-1]
            else:
                filename = app_path
            
            # Remove extension to get app name
            if '.' in filename:
                app_name = filename.rsplit('.', 1)[0]
            else:
                app_name = filename
        
        # Extract file extension from the path
        file_extension = ''
        if app_path and '.' in app_path:
            # Get the last component after the last backslash
            filename = app_path.split('\\')[-1] if '\\' in app_path else app_path
            
            # Extract extension
            if '.' in filename:
                file_extension = filename.rsplit('.', 1)[1].lower()
        
        result = {
            'app_path': app_path,
            'app_name': app_name,
            'file_extension': file_extension,
            'muicache_property': muicache_property
        }

        logger.debug(f"Parsed MUICache entry: path={app_path}, name={app_name}, ext={file_extension}")
        return result

    except Exception as e:
        logger.error(f"Error parsing MUICache entry: {e}")
        return {
            'app_path': value_name if value_name else '',
            'app_name': value_data if value_data else '',
            'file_extension': '',
            'muicache_property': ''
        }



def parse_wordwheelquery_entry(value_name: str, binary_data: bytes, mru_list_ex: bytes = None) -> dict:
    """
    Enhanced WordWheelQuery parser with proper binary handling.
    
    WordWheelQuery stores Windows Explorer search terms. Search terms are
    stored as REG_BINARY data containing UTF-16-LE encoded strings, and
    the MRUListEx value contains a DWORD array indicating search order.
    
    Args:
        value_name: Registry value name (numeric, e.g., '0', '1', '2')
        binary_data: REG_BINARY data containing UTF-16-LE encoded search term
        mru_list_ex: Optional MRUListEx binary data (DWORD array) for ordering
    
    Returns:
        Dictionary containing:
            - 'search_term': Decoded search term string
            - 'search_type': Categorized search type ('File', 'Network', 'General')
            - 'mru_position': Position in MRU list (0 = most recent)
            - 'timestamp': Timestamp (usually None for WordWheelQuery)
    
    Raises:
        ValueError: If binary data is invalid
    """
    try:
        if not binary_data:
            logger.warning("Empty binary data provided to parse_wordwheelquery_entry")
            return {
                'search_term': '',
                'search_type': 'General',
                'mru_position': -1,
                'timestamp': None
            }
        
        # Extract search term from UTF-16-LE encoded binary data
        search_term = extract_unicode_string(binary_data, offset=0)
        
        if not search_term:
            logger.warning(f"Could not extract search term from binary data (length: {len(binary_data)})")
            return {
                'search_term': '',
                'search_type': 'General',
                'mru_position': -1,
                'timestamp': None
            }
        
        # Categorize search term
        search_type = _categorize_search_term(search_term)
        
        # Determine MRU position from MRUListEx
        mru_position = -1
        if mru_list_ex and value_name:
            try:
                # Parse MRUListEx DWORD array
                mru_list = parse_mru_list_ex(mru_list_ex)
                
                # Convert value name to integer
                value_index = int(value_name)
                
                # Find position in MRU list
                if value_index in mru_list:
                    mru_position = mru_list.index(value_index)
            except (ValueError, TypeError) as e:
                logger.warning(f"Could not determine MRU position: {e}")
                mru_position = -1
        
        result = {
            'search_term': search_term,
            'search_type': search_type,
            'mru_position': mru_position,
            'timestamp': None  # WordWheelQuery typically doesn't store timestamps
        }
        
        logger.debug(f"Parsed WordWheelQuery entry: term={search_term}, type={search_type}, position={mru_position}")
        return result
        
    except Exception as e:
        logger.error(f"Error parsing WordWheelQuery entry: {e}")
        return {
            'search_term': '',
            'search_type': 'General',
            'mru_position': -1,
            'timestamp': None
        }


def _categorize_search_term(search_term: str) -> str:
    """
    Categorize a search term based on its content.
    
    Args:
        search_term: The search term to categorize
    
    Returns:
        Category string: 'File', 'Network', or 'General'
    """
    try:
        if not search_term:
            return 'General'
        
        search_lower = search_term.lower()
        
        # Check for network-related searches
        network_indicators = ['\\\\', 'http://', 'https://', 'ftp://', '://', 'www.']
        if any(indicator in search_lower for indicator in network_indicators):
            return 'Network'
        
        # Check for file-related searches
        # Look for file extensions
        file_extensions = ['.txt', '.doc', '.docx', '.pdf', '.xls', '.xlsx', 
                          '.ppt', '.pptx', '.jpg', '.png', '.gif', '.mp3', 
                          '.mp4', '.avi', '.zip', '.rar', '.exe', '.dll']
        if any(ext in search_lower for ext in file_extensions):
            return 'File'
        
        # Check for drive letters (e.g., "C:\")
        if len(search_term) >= 2 and search_term[1] == ':':
            return 'File'
        
        # Check for file path indicators
        if '\\' in search_term or '/' in search_term:
            return 'File'
        
        # Default to General
        return 'General'
        
    except Exception as e:
        logger.error(f"Error categorizing search term: {e}")
        return 'General'


def parse_user_account_v_value(binary_data: bytes) -> dict:
    r"""
    Parse the SAM V value: the account's STRING fields.

    V (SAM\SAM\Domains\Account\Users\<RID>\V) is a descriptor table, not a flat
    record. It begins with a series of 12-byte entries, each holding
    (offset, length, unknown); the offset is relative to 0xCC, where the string
    data begins. Only the strings live here.

    | entry | at     | field     |
    |-------|--------|-----------|
    | 1     | 0x0C   | username  |
    | 2     | 0x18   | full name |
    | 3     | 0x24   | comment   |

    Timestamps, login counts and account flags are NOT in V - they are in F, via
    parse_user_account_f_value(). An earlier version of this function read them
    from V offsets 0x08/0x18/0x20/0x28/0x38/0x40, which are descriptor entries,
    and produced plausible-looking garbage (last_login = 1601-01-02 05:06:37 for
    every account) rather than raising.

    Args:
        binary_data: Binary data from the SAM V value

    Returns:
        Dictionary with 'username', 'full_name', 'comment' (empty strings when
        a field is absent, which is normal - most accounts have no full name).
    """
    empty = {'username': '', 'full_name': '', 'comment': ''}
    try:
        if not binary_data or len(binary_data) < 0x30:
            logger.warning(
                f"Invalid SAM V value: expected at least 48 bytes, got "
                f"{len(binary_data) if binary_data else 0}")
            return dict(empty)

        def _string_at(entry_offset):
            """Read the descriptor entry at entry_offset and return its string."""
            try:
                off = struct.unpack('<I', binary_data[entry_offset:entry_offset + 4])[0]
                ln = struct.unpack('<I', binary_data[entry_offset + 4:entry_offset + 8])[0]
                if ln <= 0:
                    return ''
                start = off + 0xCC
                end = start + ln
                if start < 0 or end > len(binary_data):
                    return ''
                return binary_data[start:end].decode('utf-16-le', errors='ignore').strip('\x00')
            except Exception as e:
                logger.debug(f"SAM V descriptor at 0x{entry_offset:02X}: {e}")
                return ''

        result = {
            'username': _string_at(0x0C),
            'full_name': _string_at(0x18),
            'comment': _string_at(0x24),
        }
        logger.debug(f"Parsed SAM V value: username={result['username']}")
        return result

    except Exception as e:
        logger.error(f"Error parsing SAM V value: {e}")
        return dict(empty)


# SAM F value account-control bits (ACB_*). Documented in MS-SAMR.
SAM_ACCOUNT_FLAGS = (
    (0x0001, 'DISABLED'),
    (0x0002, 'HOME_DIR_REQUIRED'),
    (0x0004, 'PWD_NOT_REQUIRED'),
    (0x0008, 'TEMP_DUPLICATE'),
    (0x0010, 'NORMAL_ACCOUNT'),
    (0x0020, 'MNS_LOGON'),
    (0x0040, 'INTERDOMAIN_TRUST'),
    (0x0080, 'WORKSTATION_TRUST'),
    (0x0100, 'SERVER_TRUST'),
    (0x0200, 'PWD_NEVER_EXPIRES'),
    (0x0400, 'AUTO_LOCKED'),
)


def parse_user_account_f_value(binary_data: bytes) -> dict:
    r"""
    Parse the SAM F value: account timestamps, counters and control flags.

    F (SAM\SAM\Domains\Account\Users\<RID>\F) is a fixed 80-byte record:

    | offset | field                        |
    |--------|------------------------------|
    | 0x08   | last logon (FILETIME)        |
    | 0x18   | password last set (FILETIME) |
    | 0x20   | account expires (FILETIME)   |
    | 0x28   | last incorrect password      |
    | 0x30   | RID (DWORD)                  |
    | 0x38   | ACB account-control flags    |
    | 0x40   | bad password count (WORD)    |
    | 0x42   | logon count (WORD)           |

    The RID at 0x30 is the alignment check: it must equal the <RID> key name the
    value came from. If it does not, the offsets are wrong for this hive - every
    other field in this record should then be treated as unreliable.

    A previous version read 0x00 as "account created" (that range is reserved)
    and labelled 0x08 "last logoff" when it is in fact the last LOGON.

    Args:
        binary_data: Binary data from the SAM F value

    Returns:
        Dictionary with 'rid', 'last_logon', 'password_last_set',
        'account_expires', 'last_incorrect_password', 'login_count',
        'bad_password_count', 'account_flags', 'account_disabled',
        'account_locked', 'account_enabled'. Timestamps are '' when never set,
        which is a real finding - a built-in account that has never logged on.
    """
    empty = {
        'rid': 0, 'last_logon': '', 'password_last_set': '', 'account_expires': '',
        'last_incorrect_password': '', 'login_count': 0, 'bad_password_count': 0,
        'account_flags': '', 'account_disabled': 0, 'account_locked': 0,
        'account_enabled': 0,
    }
    try:
        if not binary_data or len(binary_data) < 0x44:
            logger.warning(
                f"Invalid SAM F value: expected at least 68 bytes, got "
                f"{len(binary_data) if binary_data else 0}")
            return dict(empty)

        def _ts(off):
            # Two sentinels, neither of which is a real date:
            #   0                  -> never happened (never logged on)
            #   0x7FFFFFFFFFFFFFFF -> never expires (the usual account_expires)
            # Rendering either would be wrong, and the second overflows datetime,
            # so parse_filetime logs "date value out of range" for every account.
            raw = binary_data[off:off + 8]
            if len(raw) < 8:
                return ''
            val = struct.unpack('<Q', raw)[0]
            if val == 0 or val == 0x7FFFFFFFFFFFFFFF:
                return ''
            return parse_filetime(raw)

        flags = struct.unpack('<I', binary_data[0x38:0x3C])[0]
        names = [n for bit, n in SAM_ACCOUNT_FLAGS if flags & bit]

        result = {
            'rid': struct.unpack('<I', binary_data[0x30:0x34])[0],
            'last_logon': _ts(0x08),
            'password_last_set': _ts(0x18),
            'account_expires': _ts(0x20),
            'last_incorrect_password': _ts(0x28),
            'bad_password_count': struct.unpack('<H', binary_data[0x40:0x42])[0],
            'login_count': struct.unpack('<H', binary_data[0x42:0x44])[0],
            'account_flags': '|'.join(names),
            'account_disabled': 1 if (flags & 0x0001) else 0,
            'account_locked': 1 if (flags & 0x0400) else 0,
        }
        result['account_enabled'] = 0 if result['account_disabled'] else 1

        logger.debug(f"Parsed SAM F value: rid={result['rid']} flags={result['account_flags']}")
        return result

    except Exception as e:
        logger.error(f"Error parsing SAM F value: {e}")
        return dict(empty)


def binary_sid_to_string(binary_data: bytes, offset: int = 0):
    """(S-1-5-21-... , bytes consumed) for a binary SID, or (None, 0).

    Sub-authorities are little-endian; the 6-byte identifier authority is
    big-endian. Getting that backwards yields a plausible-looking SID rather
    than an error, so both are explicit here.
    """
    try:
        if binary_data is None or len(binary_data) - offset < 8:
            return None, 0
        revision = binary_data[offset]
        sub_count = binary_data[offset + 1]
        size = 8 + 4 * sub_count
        if revision != 1 or sub_count > 15 or len(binary_data) - offset < size:
            return None, 0
        authority = int.from_bytes(binary_data[offset + 2:offset + 8], 'big')
        subs = [struct.unpack_from('<I', binary_data, offset + 8 + 4 * i)[0]
                for i in range(sub_count)]
        return 'S-%d-%d%s' % (revision, authority,
                              ''.join('-%d' % s for s in subs)), size
    except Exception as e:
        logger.debug(f"binary SID decode failed at offset {offset}: {e}")
        return None, 0


def parse_alias_c_value(binary_data: bytes) -> dict:
    """Decode a SAM alias (local group) C value.

    Layout, verified against `net localgroup` for both a Builtin alias
    (Administrators) and a machine-local one (docker-users):

        0x00  DWORD  RID
        0x10  DWORD  name offset      ] all offsets are relative to 0x34,
        0x14  DWORD  name length      ] not to the start of the value
        0x1C  DWORD  comment offset
        0x20  DWORD  comment length
        0x28  DWORD  member SID array offset
        0x2C  DWORD  member SID array length, in bytes
        0x30  DWORD  member count

    Lengths are byte counts, so a UTF-16 name of 28 bytes is 14 characters.
    The member array is a run of variable-length binary SIDs; walking it by a
    fixed stride would silently mis-read any group holding a well-known SID,
    which is shorter than a machine-relative one.

    Returns {} when the blob is too short or self-inconsistent, rather than a
    partly-filled record - an empty group and an unparsed one must not look
    the same.
    """
    empty: dict = {}
    try:
        if not isinstance(binary_data, (bytes, bytearray)) or len(binary_data) < 0x34:
            return dict(empty)
        b = bytes(binary_data)
        base = 0x34

        def _u32(off):
            return struct.unpack_from('<I', b, off)[0]

        def _text(off_field, len_field):
            off = base + _u32(off_field)
            ln = _u32(len_field)
            if ln == 0 or off < base or off + ln > len(b):
                return ''
            return b[off:off + ln].decode('utf-16-le', errors='replace').rstrip('\x00')

        rid = _u32(0x00)
        members_off = base + _u32(0x28)
        members_len = _u32(0x2C)
        member_count = _u32(0x30)

        members = []
        if members_len and members_off + members_len <= len(b):
            pos = members_off
            end = members_off + members_len
            while pos < end and len(members) < member_count:
                sid, consumed = binary_sid_to_string(b, pos)
                if not sid:
                    break
                members.append(sid)
                pos += consumed

        if len(members) != member_count:
            # Say so rather than returning a short list that reads as a
            # smaller group than the one that actually exists.
            logger.warning(
                "SAM alias RID %d declares %d members but %d SIDs parsed - "
                "offsets do not fit this hive", rid, member_count, len(members))

        return {
            'rid': rid,
            'name': _text(0x10, 0x14),
            'comment': _text(0x1C, 0x20),
            'member_count': member_count,
            'members': members,
            'members_parsed': len(members),
            'trusted': len(members) == member_count,
        }

    except Exception as e:
        logger.error(f"Error parsing SAM alias C value: {e}")
        return dict(empty)


def _reconstruct_pidl_path(binary_data: bytes) -> dict:
    """
    Reconstruct full path from PIDL (Pointer to Item IDentifier List) by traversing all Shell Items.
    
    Args:
        binary_data: Binary PIDL data containing multiple Shell Items
    
    Returns:
        Dictionary containing:
        - path: Full reconstructed path
        - drive_letter: Drive letter (if found)
        - components: List of path components
    """
    result = {
        'path': '',
        'drive_letter': '',
        'components': []
    }
    
    try:
        if not binary_data or len(binary_data) < 2:
            return result
        
        offset = 0
        path_components = []
        first_item = True
        
        # Traverse all Shell Items in the PIDL
        while offset < len(binary_data) - 1:
            # Read size of Shell Item (2 bytes, little-endian)
            if offset + 2 > len(binary_data):
                break
            
            size = struct.unpack('<H', binary_data[offset:offset + 2])[0]
            
            # Size of 0 indicates end of list
            if size == 0:
                break
            
            # Ensure we don't read beyond buffer
            if offset + size > len(binary_data):
                break
            
            # Extract this Shell Item
            item_data = binary_data[offset:offset + size]
            
            # Parse the item
            if len(item_data) > 2:
                type_indicator = item_data[2]
                
                logger.debug(f"Processing Shell Item at offset {offset}: type=0x{type_indicator:02X}, size={size}")
                
                # For the first item, always try to extract drive letter aggressively
                if first_item and not result['drive_letter']:
                    drive = _extract_drive_path(item_data)
                    if drive:
                        result['drive_letter'] = drive
                        logger.debug(f"Extracted drive from first item: {drive}")
                    first_item = False
                
                # Drive letter (0x20-0x2F range)
                if 0x20 <= type_indicator <= 0x2F:
                    drive = _extract_drive_path(item_data)
                    if drive:
                        result['drive_letter'] = drive
                        path_components.append(drive)
                        logger.debug(f"Added drive component: {drive}")
                
                # File system object (0x30-0x3F range)
                elif 0x30 <= type_indicator <= 0x3F:
                    names = _extract_filesystem_names(item_data)
                    # Prefer long name over short name
                    name = names.get('long_name') or names.get('short_name', '')
                    if name:
                        path_components.append(name)
                        logger.debug(f"Added filesystem component: {name}")
                    
                    # If no drive letter found yet, try to extract from this item
                    # Sometimes drive info is embedded in filesystem items
                    if not result['drive_letter']:
                        drive = _extract_drive_path(item_data)
                        if drive:
                            result['drive_letter'] = drive
                            logger.debug(f"Found embedded drive letter: {drive}")
                
                # Network location (0x40-0x4F range)
                elif 0x40 <= type_indicator <= 0x4F:
                    network_path = _extract_network_path(item_data)
                    if network_path:
                        path_components.append(network_path)
                        logger.debug(f"Added network component: {network_path}")
                
                # Unknown type - try generic extraction. Guarded, because this
                # is a byte scan: unguarded it contributed components like
                # `S"M` and `}D"pN` to otherwise correct paths.
                else:
                    generic_path = _extract_generic_path(item_data)
                    if generic_path and not is_plausible_name(generic_path.replace('\\', '')):
                        generic_path = ''
                    if generic_path and len(generic_path) > 1:
                        # Check if it contains a drive letter
                        if len(generic_path) >= 2 and generic_path[1] == ':' and generic_path[0].isalpha():
                            result['drive_letter'] = generic_path[:2].upper()
                            path_components.append(result['drive_letter'])
                            if len(generic_path) > 3:  # Has more than just "C:\"
                                remaining = generic_path[3:] if generic_path[2] == '\\' else generic_path[2:]
                                if remaining:
                                    path_components.append(remaining)
                            logger.debug(f"Extracted from generic: drive={result['drive_letter']}, path={generic_path}")
                        elif generic_path:
                            path_components.append(generic_path)
                            logger.debug(f"Added generic component: {generic_path}")
            
            # Move to next Shell Item
            offset += size
        
        # Clean up path components - remove invalid entries
        cleaned_components = []
        for component in path_components:
            # Skip empty components
            if not component or len(component) == 0:
                continue
            
            # Skip components that are just special characters or numbers
            # Valid components should have at least one letter or be a drive letter
            if component and len(component) >= 2:
                # Allow drive letters (C:, D:, etc.)
                if len(component) == 2 and component[1] == ':' and component[0].isalpha():
                    cleaned_components.append(component)
                    continue
                
                # Skip components that look like garbage (e.g., "+00", "++", etc.)
                # Valid path components should contain letters or be meaningful
                has_letter = any(c.isalpha() for c in component)
                has_digit = any(c.isdigit() for c in component)
                special_only = all(not c.isalnum() for c in component)
                
                # Skip if it's only special characters or looks like binary data
                if special_only or (not has_letter and len(component) < 3):
                    logger.debug(f"Skipping invalid component: {component}")
                    continue
                
                # Skip components that start with non-alphanumeric (except drive letters)
                if component[0] not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789':
                    logger.debug(f"Skipping component with invalid start: {component}")
                    continue
                
                cleaned_components.append(component)
        
        # Build the full path from cleaned components
        if cleaned_components:
            result['path'] = '\\'.join(cleaned_components)
            result['components'] = cleaned_components
            logger.debug(f"Reconstructed path: {result['path']}, drive: {result['drive_letter']}")
        else:
            logger.debug("No valid path components found in PIDL")
        
        return result
        
    except Exception as e:
        logger.error(f"Error reconstructing PIDL path: {e}")
        return result


def parse_opensavemru_entry(binary_data: bytes) -> dict:
    """
    Parse OpenSavePidlMRU registry entry containing Shell Item ID (PIDL) data.
    
    OpenSavePidlMRU stores file paths accessed through Open/Save dialogs.
    The binary data contains Shell Item IDs that encode file system paths.
    
    Args:
        binary_data: Binary data from OpenSavePidlMRU registry value
    
    Returns:
        Dictionary containing:
        - file_path: Full file path extracted from Shell Item
        - file_name: File or folder name
        - extension: File extension (if available)
        - access_date: Access timestamp (if available)
        - drive_letter: Drive letter (if available)
    """
    result = {
        'file_path': '',
        'file_name': '',
        'extension': '',
        'access_date': '',
        'drive_letter': ''
    }
    
    try:
        if not binary_data or len(binary_data) < 4:
            return result
        
        # Reconstruct full path from PIDL
        pidl_data = _reconstruct_pidl_path(binary_data)
        
        if pidl_data['path']:
            # Localised folders arrive as resource references; resolve every
            # component so the stored path reads as a path.
            result['file_path'] = resolve_mui_path(pidl_data['path'])
            result['drive_letter'] = pidl_data['drive_letter']
            
            # Extract file name (last component)
            if pidl_data['components']:
                result['file_name'] = pidl_data['components'][-1]
                
                # Extract extension from file name
                if '.' in result['file_name']:
                    result['extension'] = result['file_name'].split('.')[-1]
        
        # Parse first Shell Item for timestamps
        shell_item_data = parse_shell_item_id(binary_data)
        if shell_item_data.get('extension_blocks'):
            ext_blocks = shell_item_data['extension_blocks']
            if ext_blocks.get('write_time'):
                result['access_date'] = ext_blocks['write_time']
            elif ext_blocks.get('creation_time'):
                result['access_date'] = ext_blocks['creation_time']
        
        logger.debug(f"Parsed OpenSaveMRU entry: path={result['file_path']}, name={result['file_name']}")
        return result
        
    except Exception as e:
        logger.error(f"Error parsing OpenSaveMRU entry: {e}")
        return result


def parse_lastsavemru_entry(binary_data: bytes) -> dict:
    """
    Parse LastVisitedPidlMRU registry entry containing application and folder path.
    
    LastVisitedPidlMRU stores the last folder visited by each application.
    Format: [Application Name (UTF-16-LE)][NULL][Shell Item ID (PIDL)]
    
    Args:
        binary_data: Binary data from LastVisitedPidlMRU registry value
    
    Returns:
        Dictionary containing:
        - application: Application executable name (e.g., "notepad.exe")
        - folder_path: Last folder path accessed by the application
        - file_name: Folder name
        - drive_letter: Drive letter (if available)
    """
    result = {
        'application': '',
        'folder_path': '',
        'file_name': '',
        'drive_letter': ''
    }
    
    try:
        if not binary_data or len(binary_data) < 4:
            return result
        
        # Find the null terminator that separates application name from PIDL
        # Application name is UTF-16-LE, so null terminator is 0x0000
        null_pos = -1
        for i in range(0, len(binary_data) - 1, 2):
            if binary_data[i] == 0 and binary_data[i + 1] == 0:
                null_pos = i
                break
        
        if null_pos == -1:
            logger.warning("Could not find null terminator in LastSaveMRU entry")
            return result
        
        # Extract application name (UTF-16-LE before null terminator)
        try:
            app_name_bytes = binary_data[:null_pos]
            result['application'] = app_name_bytes.decode('utf-16-le', errors='ignore').strip()
            logger.debug(f"Extracted application name: {result['application']}")
        except Exception as e:
            logger.error(f"Error decoding application name: {e}")
        
        # Extract PIDL data (after null terminator)
        pidl_offset = null_pos + 2  # Skip the null terminator (2 bytes)
        if pidl_offset < len(binary_data):
            pidl_binary = binary_data[pidl_offset:]
            
            # Reconstruct full path from PIDL
            pidl_data = _reconstruct_pidl_path(pidl_binary)
            
            if pidl_data['path']:
                result['folder_path'] = pidl_data['path']
                result['drive_letter'] = pidl_data['drive_letter']
                
                # Extract folder name (last component)
                if pidl_data['components']:
                    result['file_name'] = pidl_data['components'][-1]
        
        logger.debug(f"Parsed LastSaveMRU entry: app={result['application']}, folder={result['folder_path']}")
        return result
        
    except Exception as e:
        logger.error(f"Error parsing LastSaveMRU entry: {e}")
        return result


def parse_systemtime(binary_data: bytes) -> str:
    """
    Convert 16-byte Windows SYSTEMTIME to standardized forensic string.
    
    Args:
        binary_data: 16-byte binary data containing SYSTEMTIME structure
        
    Returns:
        Standardized forensic timestamp string (YYYY-MM-DD HH:MM:SS)
    """
    try:
        if not binary_data or len(binary_data) < 16:
            return ""
        
        # Use centralized utility for parsing
        dt = systemtime_to_datetime(binary_data[:16])
        return format_forensic_timestamp(dt)
    except Exception as e:
        logger.error(f"Error parsing SYSTEMTIME: {e}")
        return ""


def format_mac_address(binary_data: bytes) -> str:
    """
    Format 6-byte binary MAC address as human-readable string.
    
    Args:
        binary_data: 6-byte binary data containing MAC address
        
    Returns:
        Formatted MAC address (e.g., 00:11:22:33:44:55)
    """
    try:
        if not binary_data or len(binary_data) < 6:
            return ""
        
        mac_bytes = binary_data[:6]
        return ':'.join(f'{b:02x}' for b in mac_bytes).upper()
    except Exception as e:
        logger.error(f"Error formatting MAC address: {e}")
        return str(binary_data)


def parse_susclientid_validation(binary_data: bytes) -> str:
    """
    Extract readable strings from SusClientIdValidation binary blob.
    
    This validation data often contains hardware/system IDs encoded as 
    UTF-16-LE strings mixed with binary metadata.
    
    Args:
        binary_data: Binary data from SusClientIdValidation registry value
        
    Returns:
        Concatenated readable strings found in the blob
    """
    if not binary_data:
        return ""
    
    try:
        import re
        # Decode as UTF-16-LE with error ignoring to handle binary parts
        decoded = binary_data.decode('utf-16-le', errors='ignore')
        
        # Extract sequences of printable characters at least 3 chars long
        # This captures the various IDs often found in this blob
        found_strings = re.findall(r'[\x20-\x7E]{3,}', decoded)
        
        # Filter and clean strings
        cleaned_strings = [s.strip() for s in found_strings if s.strip()]
        
        if not cleaned_strings:
            # Fallback to ASCII if UTF-16 didn't yield results
            ascii_decoded = binary_data.decode('ascii', errors='ignore')
            found_ascii = re.findall(r'[\x20-\x7E]{4,}', ascii_decoded)
            cleaned_strings = [s.strip() for s in found_ascii if s.strip()]
            
        return ' | '.join(cleaned_strings)
        
    except Exception as e:
        logger.error(f"Error parsing SusClientIdValidation: {e}")
        return str(binary_data)[:100]


# ---------------------------------------------------------------------------
# Scheduled Tasks (TaskCache)
#
# SOFTWARE\Microsoft\Windows NT\CurrentVersion\Schedule\TaskCache\Tasks\{GUID}
# holds two binary values worth decoding. Note the hive: there IS a
# SYSTEM\CurrentControlSet\Services\Schedule key, but it carries no TaskCache,
# so aiming there returns nothing at all rather than an error.
# ---------------------------------------------------------------------------

# Action blob magics. 0x6666 (exec) is the one that carries a command line;
# the rest are named so an unexpected one is reported instead of silently
# dropped. 0x0000 is trailing padding, not an action.
TASK_ACTION_EXEC = 0x6666
TASK_ACTION_NAMES = {
    TASK_ACTION_EXEC: "exec",
    0x7777: "com-handler",
    0x8888: "email",
    0x9999: "message-box",
}


def _task_filetime(raw: bytes):
    """8 bytes of FILETIME -> forensic UTC string, or None for 'never'.

    A zero FILETIME means the event has not happened; rendering it as
    1601-01-01 would invent an event that never occurred.
    """
    if len(raw) < 8:
        return None
    (value,) = struct.unpack('<Q', raw[:8])
    if value == 0:
        return None
    try:
        return format_forensic_timestamp(filetime_to_datetime(value))
    except (OverflowError, OSError, ValueError):
        return None


def parse_taskcache_dynamic_info(binary_data: bytes) -> dict:
    """Decode a TaskCache DynamicInfo blob: registration and run history.

    The structure grew across Windows versions (0x1c, 0x24 and 0x2c are all
    seen in the wild), so each field past the first three is read only when the
    blob is long enough rather than assuming one fixed size.

    Returns keys: version, task_registered, last_run, last_result,
    last_completed. Missing fields are simply absent.
    """
    out = {}
    try:
        if not binary_data or len(binary_data) < 0x14:
            return out
        out['version'] = struct.unpack_from('<I', binary_data, 0x00)[0]
        out['task_registered'] = _task_filetime(binary_data[0x04:0x0C])
        out['last_run'] = _task_filetime(binary_data[0x0C:0x14])
        if len(binary_data) >= 0x1C:
            # 0x18, NOT 0x14. Verified across 285 live tasks: the DWORD at 0x14
            # is zero on every one of them, while 0x18 carries real HRESULTs
            # (0x80070002 file-not-found, 0x8007045B shutdown-in-progress) that
            # match Get-ScheduledTaskInfo's LastTaskResult exactly.
            # 0 is success; anything else is the task's last result code.
            out['last_result'] = struct.unpack_from('<I', binary_data, 0x18)[0]
        if len(binary_data) >= 0x24:
            # 0x1C, NOT 0x18. Reading this off the 0x18 DWORD boundary decodes
            # as a valid-looking but absurd FILETIME (year 6916), which is the
            # kind of wrong that survives a smoke test - verified against real
            # blobs, where this equals the run time for tasks that completed.
            out['last_completed'] = _task_filetime(binary_data[0x1C:0x24])
    except Exception as e:
        logger.error(f"Error parsing TaskCache DynamicInfo: {e}")
    return out


def _task_lpwstr(blob: bytes, pos: int):
    """Read a DWORD-length-prefixed UTF-16LE string. Returns (text, new_pos)."""
    if pos + 4 > len(blob):
        return '', len(blob)
    (nbytes,) = struct.unpack_from('<I', blob, pos)
    pos += 4
    if nbytes == 0 or pos + nbytes > len(blob):
        return '', pos
    text = blob[pos:pos + nbytes].decode('utf-16-le', errors='replace').rstrip('\x00')
    return text, pos + nbytes


def parse_taskcache_actions(binary_data: bytes) -> dict:
    """Decode a TaskCache Actions blob: what the task actually runs.

    Layout: WORD version, a length-prefixed context string, then one or more
    actions each introduced by a magic WORD. Only the exec action carries a
    command line, which is the part that matters for triage.

    Returns {'context': str, 'actions': [{'type','id','command','arguments',
    'working_dir'}], 'unknown_magics': [...]}.
    """
    out = {'context': '', 'actions': []}
    try:
        if not binary_data or len(binary_data) < 6:
            return out
        pos = 0
        out['version'] = struct.unpack_from('<H', binary_data, pos)[0]
        pos += 2
        out['context'], pos = _task_lpwstr(binary_data, pos)

        while pos + 2 <= len(binary_data):
            (magic,) = struct.unpack_from('<H', binary_data, pos)
            pos += 2
            if magic == 0x0000:
                break  # trailing padding / terminator
            name = TASK_ACTION_NAMES.get(magic)
            if name is None:
                out.setdefault('unknown_magics', []).append(hex(magic))
                break
            if magic != TASK_ACTION_EXEC:
                out['actions'].append({'type': name})
                break  # only the exec layout is decoded field by field
            action_id, pos = _task_lpwstr(binary_data, pos)
            command, pos = _task_lpwstr(binary_data, pos)
            arguments, pos = _task_lpwstr(binary_data, pos)
            working_dir, pos = _task_lpwstr(binary_data, pos)
            out['actions'].append({
                'type': name, 'id': action_id, 'command': command,
                'arguments': arguments, 'working_dir': working_dir,
            })
    except Exception as e:
        logger.error(f"Error parsing TaskCache Actions: {e}")
    return out


def parse_security_descriptor(binary_data: bytes) -> dict:
    """Owner, group and ACE count from a self-relative security descriptor.

    The registry stores one descriptor per DISTINCT set of permissions, shared
    by every key that uses it, which is why a 23 MB hive can hold 69,624 keys
    without tens of megabytes of duplicated ACLs. What matters forensically is
    less the ACL itself than how many keys share it: a key with a descriptor of
    its own, where its siblings share one, has had its permissions changed.

    Layout (self-relative form): revision, sbz1, control word, then four
    offsets - owner, group, SACL, DACL - each relative to the START of the
    descriptor, and zero when absent. The ACL header is revision, size, and an
    ACE count.

    Returns {} rather than raising: a descriptor read out of a hive may be from
    a freed cell and need not be well formed.
    """
    out = {}
    try:
        if not binary_data or len(binary_data) < 20:
            return out
        revision = binary_data[0]
        if revision != 1:
            return out
        control = struct.unpack_from('<H', binary_data, 2)[0]
        off_owner, off_group, off_sacl, off_dacl = struct.unpack_from(
            '<IIII', binary_data, 4)

        out['revision'] = revision
        out['control'] = control

        for label, offset in (('owner_sid', off_owner), ('group_sid', off_group)):
            if 0 < offset < len(binary_data):
                sid, _ = binary_sid_to_string(binary_data, offset)
                if sid:
                    out[label] = sid

        # An ACL present but empty is not the same as no ACL at all: the first
        # means "nobody", the second means "no restriction expressed here".
        for label, offset in (('dacl_ace_count', off_dacl),
                              ('sacl_ace_count', off_sacl)):
            if 0 < offset and offset + 8 <= len(binary_data):
                _rev, _size, count = struct.unpack_from('<HHH', binary_data, offset)
                out[label] = count
            elif offset == 0:
                out[label] = None

        out['size'] = len(binary_data)
    except Exception as e:
        logger.debug(f"security descriptor decode failed: {e}")
    return out


def normalise_install_date(value):
    """An Uninstall key's InstallDate, as a timestamp or as nothing.

    The value arrives in two unrelated shapes and neither is a timestamp:

        "20250908"    a YYYYMMDD string, which is what most installers write
        1784409493    a Unix epoch, which some write instead

    Both were being stored verbatim, side by side in one column, so nothing
    downstream could sort or compare it - and a raw epoch beside a real
    timestamp is the exact "formatted string in a numeric column" failure that
    stops a column meaning anything.

    A date-only value becomes midnight because the registry records no time of
    day. That is the conventional reading and it keeps the column sortable; the
    column's own name says the granularity is a date.

    Anything that is neither shape returns "" - an empty cell is a true
    statement, and a garbage value in a time column is not.
    """
    if value in (None, ""):
        return ""
    text = str(value).strip()
    if not text:
        return ""

    # Already ours - leave it alone.
    if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", text):
        return text

    digits = text.strip()
    if not digits.isdigit():
        return ""

    if len(digits) == 8:
        try:
            when = datetime.strptime(digits, "%Y%m%d")
        except ValueError:
            return ""
        if not (1990 <= when.year <= 2100):
            return ""
        return format_forensic_timestamp(when.replace(tzinfo=timezone.utc))

    # A Unix epoch. Bounded so a version number or a size cannot be read as one.
    try:
        seconds = int(digits)
    except ValueError:
        return ""
    if not (631152000 <= seconds <= 4102444800):        # 1990 .. 2100
        return ""
    return format_forensic_timestamp(unix_timestamp_to_datetime(seconds))


def signed_bias(value):
    """A timezone bias as signed minutes.

    REG_DWORD is unsigned, and a UTC offset is not. Egypt Standard Time is
    UTC+2 and its Bias is -120, which read unsigned is 4,294,967,176 - the
    number that was being stored. Anything comparing bias > 0 got the sign
    backwards, and the value could not be used to correct a local timestamp at
    all.

    Windows computes local time as UTC + bias, so a NEGATIVE bias is a zone
    ahead of UTC. Returns 0 for anything that is not a plausible offset rather
    than passing nonsense through.
    """
    if value in (None, ""):
        return 0
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return 0
    if raw > 0x7FFFFFFF:
        raw -= 0x100000000
    # No real zone is more than a day from UTC.
    return raw if abs(raw) <= 24 * 60 else 0


def utc_offset_label(bias):
    """The bias as the offset a person reads, for example "+02:00".

    Named the way a reader expects rather than the way Windows stores it: the
    sign is inverted, because local = UTC + bias means a bias of -120 is UTC+2.
    """
    minutes = -signed_bias(bias)
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    return "%s%02d:%02d" % (sign, minutes // 60, minutes % 60)


TIMEZONE_KEY = "\\".join(("System", "CurrentControlSet", "Control",
                              "TimeZoneInformation"))


def read_evidence_bias(read_values, hive, key_path=None):
    """Set the evidence bias from a SYSTEM hive, early, and return the minutes.

    This exists because of an ordering trap. The TimeZoneInfo table is written
    late in a parse, and shell items are decoded long before it - so setting
    the bias where the table is written applies it to nothing at all, while
    looking entirely correct in the diff.

    `read_values` is the parser's own value reader, so this makes no assumption
    about how the hive is opened.
    """
    path = key_path or TIMEZONE_KEY
    try:
        values = read_values(hive, path) or {}
    except Exception as exc:
        logger.debug("evidence bias: cannot read %s: %s", path, exc)
        return set_evidence_bias(0)
    raw = 0
    for name, item in values.items():
        if str(name).lower() == "bias":
            raw = item[0] if isinstance(item, (tuple, list)) else item
            break
    return set_evidence_bias(raw)


# The network adapter class. Each numbered subkey under it is one adapter, and
# NetCfgInstanceId is the interface GUID that ties it to the Tcpip interface
# key of the same name.
ADAPTER_CLASS_GUID = "{4d36e972-e325-11ce-bfc1-08002be10318}"


def normalise_mac(text):
    r"""A NetworkAddress override as a readable MAC, or "" if it is not one.

    NetworkAddress is the ONLY MAC the registry holds, and it exists only when
    somebody has overridden the adapter's burned-in address. The value that was
    being read instead - MacAddress under Tcpip\Parameters\Interfaces - does
    not exist at all: checked against a real hive, ten interfaces and not one
    of them had it. The live parser named the column in its INSERT and filled
    it from a branch that never fired, so it looked like a working column and
    was empty on every row.

    Stored without separators, twelve hex digits, so this puts them back.
    """
    if not text:
        return ""
    raw = "".join(ch for ch in str(text) if ch.isalnum()).upper()
    if len(raw) != 12 or any(ch not in "0123456789ABCDEF" for ch in raw):
        return ""
    return ":".join(raw[i:i + 2] for i in range(0, 12, 2))


def parse_startup_approved(binary_data):
    r"""One StartupApproved entry: is this autostart enabled, and since when.

    Explorer records here whether each Run / Run32 / StartupFolder entry is
    actually allowed to launch. Without it a persistence table lists everything
    the Run key holds as though it all ran - on the reference system six of ten
    HKCU Run entries are disabled and were being reported as live.

    The value is always 12 bytes: a state byte, three bytes of padding, and a
    FILETIME. The rule is even-enabled, odd-disabled, and the data says so
    rather than a document: across every entry on the reference system the
    states are 0x02, 0x03, 0x04 and 0x06, and **only 0x03 carries a timestamp**
    - the other three are zero. A time only exists once something has been
    switched off, which is exactly what a disabled-at field should look like.

    The raw byte is returned alongside so nobody has to take the mapping on
    trust.

    Returns {state, state_byte, disabled_at} - disabled_at is "" unless the
    entry is disabled and the timestamp is a plausible one.
    """
    out = {"state": "unknown", "state_byte": None, "disabled_at": ""}
    if not binary_data or len(binary_data) < 1:
        return out
    try:
        raw = bytes(binary_data)
    except Exception:
        return out

    first = raw[0]
    out["state_byte"] = "0x%02X" % first
    out["state"] = "disabled" if (first & 1) else "enabled"

    if len(raw) >= 12 and out["state"] == "disabled":
        try:
            when = struct.unpack_from("<Q", raw, 4)[0]
        except Exception:
            when = 0
        if when:
            # parse_filetime range-checks it, so a zero or a misread stays "".
            out["disabled_at"] = parse_filetime(raw[4:12])
    return out


# ---------------------------------------------------------------------------
# Rendering a raw registry value so a person can read it
#
# Five tables store one row per registry value with the data as text, and that
# text was `str(data)` - so a REG_BINARY landed in the database as a Python
# bytes repr, `b'\x00\x00\n\x00...'`, and a REG_DWORD holding a signed number
# landed as its unsigned reading. Each value needs its OWN decode: under one
# key alone, Bias is signed minutes, StandardStart is a transition rule,
# StandardName is a resource reference and DynamicDaylightTimeDisabled is a
# flag. That is what these rules are.
#
# The raw text is never overwritten. A decode has to be checkable against the
# original, which is also why every decoder here returns the bytes it read.
# ---------------------------------------------------------------------------

REG_SZ_TYPES = (1, 2, 7)          # REG_SZ, REG_EXPAND_SZ, REG_MULTI_SZ


def _as_bytes(data):
    """The value's data as bytes, or None if it is not binary."""
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    return None


def bytes_as_hex(data, limit=256):
    """Binary data as spaced hex - what a raw column should hold.

    Hex rather than a Python repr: `b'\\x00\\x00\\n\\x00'` hides that the third
    byte is 0x0A behind an escape, and it cannot be pasted into anything that
    reads bytes.
    """
    raw = _as_bytes(data)
    if raw is None:
        return ""
    return " ".join("%02X" % b for b in raw[:limit])


# --- time zone -------------------------------------------------------------

_DOW_NAMES = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday",
              "Friday", "Saturday")
_MONTH_NAMES = ("", "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November",
                "December")
_OCCURRENCE = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "last"}


def parse_tz_transition_rule(binary_data):
    r"""A StandardStart / DaylightStart value: when the clocks change.

    **This is not a SYSTEMTIME, and reading it as one produces a plausible
    wrong answer rather than an error.** The 16 bytes under
    `Control\TimeZoneInformation` carry SYSTEMTIME's fields with wDayOfWeek
    moved to the END:

        wYear, wMonth, wDay, wHour, wMinute, wSecond, wMilliseconds, wDayOfWeek

    Measured, not assumed. The same rule is stored in the documented order in
    the `TZI` blob under `Time Zones\<TimeZoneKeyName>`, and the two agree
    field for field on both values of the reference system:

        StandardStart    00 00 | 0a 00 | 05 00 | 17 00 | 3b 00 | 3b 00 | e7 03 | 04 00
        TZI StandardDate 00 00 | 0a 00 | 04 00 | 05 00 | 17 00 | 3b 00 | 3b 00 | e7 03

    Read as a plain SYSTEMTIME the first gives "23 Friday of October at
    59:59:999" - hour 59 and second 999, both impossible, and neither of them
    an error a caller would notice.

    wYear is 0 and wDay is an occurrence 1-5 where 5 means "last", because this
    is a recurring rule and not a point in time. A month of 0 means the zone
    does not change its clocks.

    Returns {month, day_of_week, occurrence, hour, minute, second,
    millisecond, rule, raw_hex, valid}.
    """
    out = {"month": None, "day_of_week": None, "occurrence": None,
           "hour": None, "minute": None, "second": None, "millisecond": None,
           "rule": "", "raw_hex": "", "valid": False}
    raw = _as_bytes(binary_data)
    if not raw or len(raw) < 16:
        return out
    out["raw_hex"] = bytes_as_hex(raw, 16)
    try:
        year, month, day, hour, minute, second, ms, dow = struct.unpack_from(
            "<8H", raw, 0)
    except Exception:
        return out

    out.update({"month": month, "day_of_week": dow, "occurrence": day,
                "hour": hour, "minute": minute, "second": second,
                "millisecond": ms})

    if month == 0:
        out["rule"] = "no seasonal change"
        out["valid"] = True
        return out

    out["valid"] = (1 <= month <= 12 and dow <= 6 and 1 <= day <= 5
                    and hour <= 23 and minute <= 59 and second <= 59
                    and ms <= 999 and year == 0)
    if not out["valid"]:
        # Say so rather than printing a sentence built out of impossible
        # numbers. An undecoded value is safer than a confident wrong one.
        out["rule"] = "unrecognised transition rule"
        return out

    out["rule"] = "%s %s of %s at %02d:%02d:%02d.%03d" % (
        _OCCURRENCE.get(day, str(day)), _DOW_NAMES[dow], _MONTH_NAMES[month],
        hour, minute, second, ms)
    return out


def tz_rule_from_tzi(binary_data, daylight=False):
    """The same rule out of a `TZI` blob, in the DOCUMENTED SYSTEMTIME order.

    REG_TZI_FORMAT is three LONGs then two SYSTEMTIMEs: StandardDate at 12,
    DaylightDate at 28. Used to cross-check parse_tz_transition_rule against a
    second copy of the same fact rather than trusting one reading of one blob.
    """
    raw = _as_bytes(binary_data)
    if not raw or len(raw) < 44:
        return None
    off = 28 if daylight else 12
    try:
        year, month, dow, day, hour, minute, second, ms = struct.unpack_from(
            "<8H", raw, off)
    except Exception:
        return None
    return {"month": month, "day_of_week": dow, "occurrence": day,
            "hour": hour, "minute": minute, "second": second,
            "millisecond": ms}


def tz_rules_agree(rule, tzi_rule):
    """Whether a decoded Start value matches the TZI copy of the same rule."""
    if not rule or not tzi_rule:
        return None
    keys = ("month", "day_of_week", "occurrence", "hour", "minute", "second",
            "millisecond")
    return all(rule.get(k) == tzi_rule.get(k) for k in keys)


TIME_ZONES_KEY = "\\".join(("SOFTWARE", "Microsoft", "Windows NT",
                            "CurrentVersion", "Time Zones"))


def resolve_time_zone_names(read_values, time_zone_key_name):
    r"""The plain-English zone names, out of the evidence's own SOFTWARE hive.

    `Control\TimeZoneInformation` stores StandardName and DaylightName as MUI
    resource references - `@tzres.dll,-342` - which is what was being recorded
    and is not a name anybody can read. The text sits under
    `Time Zones\<TimeZoneKeyName>` as `Std`, `Dlt` and `Display`, in the hive
    being examined.

    Read from the evidence rather than resolved through SHLoadIndirectString,
    for the reason MUI_RESOURCE_NAMES already gives: the API answers about the
    machine running Crow-Eye, in its language, so an image acquired elsewhere
    would be described using the analyst's locale. A hive lookup gives live and
    offline the same answer.

    `read_values` is a callable taking a key path and returning {name: data},
    so the two parsers pass their own reader and this stays shared.

    Returns {standard_name, daylight_name, display_name} - empty strings when
    the key is not readable, never a guess.
    """
    out = {"standard_name": "", "daylight_name": "", "display_name": ""}
    if not read_values or not time_zone_key_name:
        return out
    try:
        values = read_values("%s\\%s" % (TIME_ZONES_KEY, time_zone_key_name))
    except Exception:
        return out
    if not values:
        return out
    for name, data in values.items():
        low = name.lower()
        if low == "std":
            out["standard_name"] = str(data)
        elif low == "dlt":
            out["daylight_name"] = str(data)
        elif low == "display":
            out["display_name"] = str(data)
    return out


# --- BAM / DAM -------------------------------------------------------------

# What the last uint32 of a BAM entry says, derived from the data and not from
# a document. On the reference system the field at offset 16 is 0 on all 53
# entries whose value name is an NT device path to an executable and 1 on all
# 60 whose name is a package family name - a 113/113 split, confirmed a second
# time by reading the live registry directly (112 entries, no exceptions).
#
# It is recorded with the raw number beside it, because one machine agreeing
# with itself twice is evidence and not proof.
BAM_NAME_KINDS = {0: "device path", 1: "package family name"}


def parse_bam_blob(binary_data):
    r"""One BAM / DAM value: 24 bytes, and only 12 of them were being read.

        [0:8]   FILETIME - the last execution
        [8:16]  zero on every entry seen
        [16:20] uint32 - see BAM_NAME_KINDS
        [20:24] uint32 - 2 on every entry seen

    The field at 16 is the only one that discriminates, and it was discarded.
    The column that claimed to hold flags read a value named `Flags` that these
    keys do not have, so it was 0 on all 113 rows - a constant presented as a
    finding.

    The trailing uint32 is recorded as the number it is. It is 2 everywhere on
    the reference system, which is not enough to name it, so it is named for
    where it sits and left undescribed rather than given an invented meaning.

    Returns {last_execution, name_kind, name_kind_raw, trailing_value,
    reserved_is_zero, raw_hex}.
    """
    out = {"last_execution": "", "name_kind": "", "name_kind_raw": None,
           "trailing_value": None, "reserved_is_zero": None, "raw_hex": ""}
    raw = _as_bytes(binary_data)
    if not raw:
        return out
    out["raw_hex"] = bytes_as_hex(raw, 24)
    if len(raw) >= 8:
        out["last_execution"] = parse_filetime(raw[:8])
    if len(raw) >= 16:
        out["reserved_is_zero"] = (raw[8:16] == b"\x00" * 8)
    if len(raw) >= 20:
        try:
            kind = struct.unpack_from("<I", raw, 16)[0]
            out["name_kind_raw"] = kind
            out["name_kind"] = BAM_NAME_KINDS.get(kind, "")
        except Exception:
            pass
    if len(raw) >= 24:
        try:
            out["trailing_value"] = struct.unpack_from("<I", raw, 20)[0]
        except Exception:
            pass
    return out


# BAM's own bookkeeping values. They are not programs, and writing them as
# though they were gave two rows an app_name and a process_path of "Version"
# and "SequenceNumber" - paths that do not exist on any machine.
BAM_METADATA_VALUES = {"version", "sequencenumber"}


def is_bam_metadata(value_name):
    return str(value_name or "").strip().lower() in BAM_METADATA_VALUES


# --- NetworkList -----------------------------------------------------------

# Documented enumerations. A code that is not here renders as its number: an
# unrecognised category is a number this does not know, not a category it can
# name.
NETWORK_CATEGORIES = {0: "Public", 1: "Private", 2: "Domain"}
NETWORK_NAME_TYPES = {
    0x06: "wired",
    0x17: "VPN",
    0x47: "wireless",
    0x53: "mobile broadband",
}
NETWORK_MANAGED = {0: "not domain-managed", 1: "domain-managed"}


def _enum_label(table, value):
    """`<label> (<n>)`, or just the number when the code is not known."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return str(value)
    name = table.get(n)
    return "%s (%d)" % (name, n) if name else str(n)


def network_category_label(value):
    return _enum_label(NETWORK_CATEGORIES, value)


def network_name_type_label(value):
    """What kind of network this is.

    Replaces an `is_hidden` column that was derived from `NameType == 6`. 6 is
    a WIRED network; the reference system's 0x47 is wireless, so the column
    said "not hidden" for a reason that had nothing to do with hiding. It was
    also a verdict where the registry only offers a fact.
    """
    return _enum_label(NETWORK_NAME_TYPES, value)


def network_managed_label(value):
    return _enum_label(NETWORK_MANAGED, value)


# --- Tcpip interfaces ------------------------------------------------------

def parse_dhcp_gateway_hardware(binary_data):
    r"""`DhcpGatewayHardware`: the gateway's address and its MAC.

        [0:4]  gateway IPv4, in order
        [4:8]  uint32 hardware address length (6)
        [8:..] the hardware address

    Worth decoding because it is a second, independent record of the same fact
    NetworkList keeps: on the reference system this yields 192.168.100.1 and
    04:8C:16:1C:64:9B, and `NetworkList\Signatures\Unmanaged` records that same
    MAC as the DefaultGatewayMac of the network named "emad". Two keys written
    by different components agreeing is worth more than either alone.

    Returns {gateway_ip, gateway_mac, raw_hex}. The MAC belongs to the GATEWAY -
    it is not this interface's own hardware address, and must not be recorded
    as one.
    """
    out = {"gateway_ip": "", "gateway_mac": "", "raw_hex": ""}
    raw = _as_bytes(binary_data)
    if not raw or len(raw) < 8:
        return out
    out["raw_hex"] = bytes_as_hex(raw, 32)
    try:
        out["gateway_ip"] = ".".join(str(b) for b in raw[0:4])
        length = struct.unpack_from("<I", raw, 4)[0]
        if 0 < length <= 8 and len(raw) >= 8 + length:
            out["gateway_mac"] = ":".join("%02X" % b
                                          for b in raw[8:8 + length])
    except Exception:
        pass
    return out


def unix_seconds_label(value):
    """A DHCP lease time as a UTC timestamp.

    LeaseObtainedTime, LeaseTerminatesTime, T1 and T2 are Unix epoch seconds.
    They were stored as bare integers, so a lease obtained in September 2025
    read as 1757332381 and sorted as text.
    """
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    try:
        return format_forensic_timestamp(unix_timestamp_to_datetime(seconds))
    except Exception:
        return ""


# --- the renderer the raw tables use ---------------------------------------
#
# Keyed on (context, value name). A value with no rule falls through to the
# generic rendering, which is the same shape Regclaw's _carved_data_text
# already uses: text decoded, everything else hex.

def _tz_bias(data, _type):
    """Bias and ActiveTimeBias ARE the offset from UTC."""
    minutes = signed_bias(data)
    return "%d minutes  (UTC%s)" % (minutes, utc_offset_label(minutes))


def _tz_season_bias(data, _type):
    """StandardBias and DaylightBias are ADDED to Bias, not offsets themselves.

    Rendering them as "UTC+01:00" said Egypt was an hour ahead of Greenwich in
    summer, when what DaylightBias -60 means is that another hour is added to
    the standing -120 while daylight time is in force. A number that is right
    and a label that is wrong is worse than the number on its own.
    """
    minutes = signed_bias(data)
    if minutes == 0:
        return "0 minutes  -  no additional shift"
    return "%d minutes  -  clocks move %s %d:%02d while this season is in force" % (
        minutes, "forward" if minutes < 0 else "back",
        abs(minutes) // 60, abs(minutes) % 60)


def _tz_rule(data, _type):
    return parse_tz_transition_rule(data)["rule"]


def _yes_no(data, _type):
    """One vocabulary for switches, everywhere.

    This said "Yes"/"No" while system_configuration said "enabled"/"disabled"
    and the timezone rule wrote a sentence - the same 1, three different words,
    depending only on which table the analyst happened to be looking at.
    """
    return decode_switch(data) or str(data)

# ---------------------------------------------------------------------------
#  Registry value decoding: locales, switches, flag fields, shell item lists
#
#  These live here, beside the timezone and networklist rules, because this is
#  the file that decodes registry values. They spent a while in
#  registry_extra_keys.py where nothing else could reach them, which is how
#  `system_configuration` came to decode a locale while `network_interfaces`
#  next door rendered the same kind of value as raw text.
#
#  Everything here is name-driven and context-free: an LCID is an LCID whatever
#  key it sits under, so `render_registry_value` can fall back to these for any
#  artifact rather than needing a rule per table.
# ---------------------------------------------------------------------------

# Every locale Windows itself names, read out of the OS with GetLocaleInfoEx /
# GetLocaleInfoW rather than typed by hand - 207 of the 208 in Python's
# `locale.windows_locale`, plus the two legacy Bhutan ids modern Windows has
# dropped. Embedded as a table rather than called at runtime so an offline
# image decodes the same way on any examiner's machine.
LCIDS = {
    "0004": "Chinese (Simplified, Mainland China)",
    "0401": "Arabic (Saudi Arabia)",
    "0402": "Bulgarian (Bulgaria)",
    "0403": "Catalan (Catalan)",
    "0404": "Chinese (Traditional, Taiwan)",
    "0405": "Czech (Czechia)",
    "0406": "Danish (Denmark)",
    "0407": "German (Germany)",
    "0408": "Greek (Greece)",
    "0409": "English (United States)",
    "040A": "Spanish (Spain, International Sort)",
    "040B": "Finnish (Finland)",
    "040C": "French (France)",
    "040D": "Hebrew (Israel)",
    "040E": "Hungarian (Hungary)",
    "040F": "Icelandic (Iceland)",
    "0410": "Italian (Italy)",
    "0411": "Japanese (Japan)",
    "0412": "Korean (Korea)",
    "0413": "Dutch (Netherlands)",
    "0414": "Norwegian Bokm?l (Norway)",
    "0415": "Polish (Poland)",
    "0416": "Portuguese (Brazil)",
    "0417": "Romansh (Switzerland)",
    "0418": "Romanian (Romania)",
    "0419": "Russian (Russia)",
    "041A": "Croatian (Croatia)",
    "041B": "Slovak (Slovakia)",
    "041C": "Albanian (Albania)",
    "041D": "Swedish (Sweden)",
    "041E": "Thai (Thailand)",
    "041F": "Turkish (T?rkiye)",
    "0420": "Urdu (Pakistan)",
    "0421": "Indonesian (Indonesia)",
    "0422": "Ukrainian (Ukraine)",
    "0423": "Belarusian (Belarus)",
    "0424": "Slovenian (Slovenia)",
    "0425": "Estonian (Estonia)",
    "0426": "Latvian (Latvia)",
    "0427": "Lithuanian (Lithuania)",
    "0428": "Tajik (Cyrillic, Tajikistan)",
    "0429": "Persian (Iran)",
    "042A": "Vietnamese (Vietnam)",
    "042B": "Armenian (Armenia)",
    "042C": "Azerbaijani (Latin, Azerbaijan)",
    "042D": "Basque (Basque)",
    "042E": "Upper Sorbian (Germany)",
    "042F": "Macedonian (North Macedonia)",
    "0432": "Setswana (South Africa)",
    "0434": "isiXhosa (South Africa)",
    "0435": "isiZulu (South Africa)",
    "0436": "Afrikaans (South Africa)",
    "0437": "Georgian (Georgia)",
    "0438": "Faroese (Faroe Islands)",
    "0439": "Hindi (India)",
    "043A": "Maltese (Malta)",
    "043B": "Sami, Northern (Norway)",
    "043E": "Malay (Malaysia)",
    "043F": "Kazakh (Kazakhstan)",
    "0440": "Kyrgyz (Kyrgyzstan)",
    "0441": "Kiswahili (Kenya)",
    "0442": "Turkmen (Turkmenistan)",
    "0443": "Uzbek (Latin, Uzbekistan)",
    "0444": "Tatar (Russia)",
    "0445": "Bengali (India)",
    "0446": "Punjabi (India)",
    "0447": "Gujarati (India)",
    "0448": "Odia (India)",
    "0449": "Tamil (India)",
    "044A": "Telugu (India)",
    "044B": "Kannada (India)",
    "044C": "Malayalam (India)",
    "044D": "Assamese (India)",
    "044E": "Marathi (India)",
    "044F": "Sanskrit (India)",
    "0450": "Mongolian (Mongolia)",
    "0451": "Tibetan (China)",
    "0452": "Welsh (United Kingdom)",
    "0453": "Khmer (Cambodia)",
    "0454": "Lao (Laos)",
    "0456": "Galician (Galician)",
    "0457": "Konkani (India)",
    "045A": "Syriac (Syria)",
    "045B": "Sinhala (Sri Lanka)",
    "045D": "Inuktitut (Syllabics, Canada)",
    "045E": "Amharic (Ethiopia)",
    "0461": "Nepali (Nepal)",
    "0462": "Western Frisian (Netherlands)",
    "0463": "Pashto (Afghanistan)",
    "0464": "Filipino (Philippines)",
    "0465": "Divehi (Maldives)",
    "0468": "Hausa (Latin, Nigeria)",
    "046A": "Yoruba (Nigeria)",
    "046B": "Quechua (Bolivia)",
    "046C": "Sesotho sa Leboa (South Africa)",
    "046D": "Bashkir (Russia)",
    "046E": "Luxembourgish (Luxembourg)",
    "046F": "Kalaallisut (Greenland)",
    "0478": "Yi (China)",
    "047A": "Mapuche (Chile)",
    "047C": "Mohawk (Canada)",
    "047E": "Breton (France)",
    "0480": "Uyghur (China)",
    "0481": "M?ori (New Zealand)",
    "0482": "Occitan (France)",
    "0483": "Corsican (France)",
    "0484": "Alsatian (France)",
    "0485": "Sakha (Russia)",
    "0486": "K?iche? (Latin, Guatemala)",
    "0487": "Kinyarwanda (Rwanda)",
    "0488": "Wolof (Senegal)",
    "048C": "Persian (Afghanistan)",
    "0801": "Arabic (Iraq)",
    "0804": "Chinese (Simplified, Mainland China)",
    "0807": "German (Switzerland)",
    "0809": "English (United Kingdom)",
    "080A": "Spanish (Mexico)",
    "080C": "French (Belgium)",
    "0810": "Italian (Switzerland)",
    "0813": "Dutch (Belgium)",
    "0814": "Norwegian Nynorsk (Norway)",
    "0816": "Portuguese (Portugal)",
    "081A": "Serbian (Latin, Serbia and Montenegro (Former))",
    "081D": "Swedish (Finland)",
    "0820": "Urdu (India)",
    "082C": "Azerbaijani (Cyrillic, Azerbaijan)",
    "082E": "Lower Sorbian (Germany)",
    "083B": "Sami, Northern (Sweden)",
    "083C": "Irish (Ireland)",
    "083E": "Malay (Brunei)",
    "0843": "Uzbek (Cyrillic, Uzbekistan)",
    "0850": "Mongolian (Traditional Mongolian, China)",
    "0851": "Dzongkha (Bhutan)",
    "085D": "Inuktitut (Latin, Canada)",
    "085F": "Central Atlas Tamazight (Latin, Algeria)",
    "086B": "Quechua (Ecuador)",
    "0C01": "Arabic (Egypt)",
    "0C04": "Chinese (Traditional, Hong Kong SAR)",
    "0C07": "German (Austria)",
    "0C09": "English (Australia)",
    "0C0A": "Spanish (Spain, International Sort)",
    "0C0C": "French (Canada)",
    "0C1A": "Serbian (Cyrillic, Serbia and Montenegro (Former))",
    "0C3B": "Sami, Northern (Finland)",
    "0C6B": "Quechua (Peru)",
    "1001": "Arabic (Libya)",
    "1004": "Chinese (Simplified, Singapore)",
    "1007": "German (Luxembourg)",
    "1009": "English (Canada)",
    "100A": "Spanish (Guatemala)",
    "100C": "French (Switzerland)",
    "101A": "Croatian (Bosnia & Herzegovina)",
    "103B": "Sami, Lule (Norway)",
    "1401": "Arabic (Algeria)",
    "1404": "Chinese (Traditional, Macao SAR)",
    "1407": "German (Liechtenstein)",
    "1409": "English (New Zealand)",
    "140A": "Spanish (Costa Rica)",
    "140C": "French (Luxembourg)",
    "141A": "Bosnian (Latin, Bosnia & Herzegovina)",
    "143B": "Sami, Lule (Sweden)",
    "1801": "Arabic (Morocco)",
    "1809": "English (Ireland)",
    "180A": "Spanish (Panama)",
    "180C": "French (Monaco)",
    "181A": "Serbian (Latin, Bosnia & Herzegovina)",
    "183B": "Sami, Southern (Norway)",
    "1C01": "Arabic (Tunisia)",
    "1C09": "English (South Africa)",
    "1C0A": "Spanish (Dominican Republic)",
    "1C1A": "Serbian (Cyrillic, Bosnia and Herzegovina)",
    "1C3B": "Sami, Southern (Sweden)",
    "2001": "Arabic (Oman)",
    "2009": "English (Jamaica)",
    "200A": "Spanish (Venezuela)",
    "201A": "Bosnian (Cyrillic, Bosnia and Herzegovina)",
    "203B": "Sami, Skolt (Finland)",
    "2129": "Tibetan (Bhutan)",
    "2401": "Arabic (Yemen)",
    "2409": "English (Caribbean)",
    "240A": "Spanish (Colombia)",
    "243B": "Sami, Inari (Finland)",
    "2801": "Arabic (Syria)",
    "2809": "English (Belize)",
    "280A": "Spanish (Peru)",
    "2C01": "Arabic (Jordan)",
    "2C09": "English (Trinidad & Tobago)",
    "2C0A": "Spanish (Argentina)",
    "3001": "Arabic (Lebanon)",
    "3009": "English (Zimbabwe)",
    "300A": "Spanish (Ecuador)",
    "3401": "Arabic (Kuwait)",
    "3409": "English (Philippines)",
    "340A": "Spanish (Chile)",
    "3801": "Arabic (United Arab Emirates)",
    "380A": "Spanish (Uruguay)",
    "3C01": "Arabic (Bahrain)",
    "3C0A": "Spanish (Paraguay)",
    "4001": "Arabic (Qatar)",
    "4009": "English (India)",
    "400A": "Spanish (Bolivia)",
    "4409": "English (Malaysia)",
    "440A": "Spanish (El Salvador)",
    "4809": "English (India)",
    "480A": "Spanish (Honduras)",
    "4C0A": "Spanish (Nicaragua)",
    "500A": "Spanish (Puerto Rico)",
    "540A": "Spanish (United States)",
    "7C04": "Chinese (Traditional, Hong Kong SAR)",
}

# Value names that hold a 0/1 switch. An explicit list, never a name pattern:
# the pattern tried while scoping this matched `Version` (it ends in "on"), and
# in a case where Version happens to be 1 that renders as "enabled".
#
# Curated, not harvested. Eighty-one value names in a real case hold only 0 or
# 1, and most are NOT switches - TcbLoaderStartTimestamp and ResumeChecksumTime
# are timestamps that happen to be zero, LowDiskMinimumMBytes is a megabyte
# count that happens to be one, StandardBias is minutes, and Category, SetupType
# and ErrorMode are enumerations whose 0 means something specific. A wrong
# decode is worse than none, so a name earns its place here by being a
# documented switch.
SWITCH_SETTINGS = frozenset((
    # Explorer / shell
    "AlwaysShowExt", "Hidden", "HideFileExt", "ShowSuperHidden",
    "HideDrivesWithNoMedia", "SeparateProcess", "AlwaysUnloadDLL",
    "DisableThumbnailCache", "DisableThumbsDBOnNetworkFolders",
    "ShellErrorMode", "SilentTerminate",
    # UAC and logon
    "EnableLUA", "EnableInstallerDetection", "EnableSecureUIAPaths",
    "EnableUIADesktopToggle", "PromptOnSecureDesktop",
    "ValidateAdminCodeSignatures", "FilterAdministratorToken",
    "LocalAccountTokenFilterPolicy", "AutoAdminLogon", "ForceAutoLogon",
    "DontDisplayLastUserName", "DisableCAD", "EnableFirstLogonAnimation",
    # Network identity and TCP/IP
    "EnableDHCP", "IPEnableRouter", "ForwardBroadcasts",
    "SyncDomainWithMembership", "StrictTimeWaitSeqCheck", "IsServerNapAware",
    "DhcpConnForceBroadcastFlag", "EnableLinkedConnections",
    "AllowRemoteRPC", "EnableSecuritySignature", "RequireSecuritySignature",
    "AllowInsecureGuestAuth", "RequireSignOrSeal", "SealSecureChannel",
    "SignSecureChannel", "DisablePasswordChange", "RefusePasswordChange",
    "SMB1", "SMB2", "RestrictNullSessAccess",
    # Remote Desktop
    "fDenyTSConnections", "UserAuthentication", "fDisableCdm",
    "fAllowToGetHelp", "fSingleSessionPerUser", "fPromptForPassword",
    "fDisableClip", "fDisableLPT", "fDisableCcm",
    # Credentials and LSA
    "UseLogonCredential", "AllowProtectedCreds", "DisableDomainCreds",
    "EveryoneIncludesAnonymous", "NoLMHash", "RestrictAnonymous",
    "RestrictAnonymousSAM", "LimitBlankPasswordUse",
    "EnableVirtualizationBasedSecurity", "RunAsPPL",
    # Defender / SmartScreen / attachments
    "DisableAntiSpyware", "DisableRealtimeMonitoring",
    "DisableBehaviorMonitoring", "DisableScriptScanning",
    "DisableIOAVProtection", "SaveZoneInformation", "EnableSmartScreen",
    "SpyNetReporting",
    # Policy lockdowns
    "DisableTaskMgr", "DisableRegistryTools", "DisableCMD", "NoRun",
    "NoControlPanel", "NoFolderOptions",
    # Zone policy
    "AutoDetect", "IntranetName", "UNCAsIntranet", "ProxyByPass",
    "ProxyEnable",
    # Power and boot
    "HiberbootEnabled", "HibernateEnabled", "HBFlagsSwitch",
    "HypervisorLaunchTypeReflect", "Preshutdown", "NoInteractiveServices",
    # Scripting hosts
    "UseWINSAFER", "ActiveDebugging", "DisplayLogo",
    # Time and locale
    "DynamicDaylightTimeDisabled", "ServiceDllUnloadOnStop",
    # Search / indexing / servicing
    "DebugTranFiles", "AcceleratedInstallRequired", "IsOOBEInProgress",
    "OOBEInProgress", "SystemSetupInProgress", "RestartSetup",
    "RemoveWindowsOld", "SetupSupported", "FlightPendingCommit",
    "UpdateDesiredVisibility", "ComponentizedBuild",
    "CoreWorkerSupportsPrivateNamespaces", "StartWorkerOnServiceStart",
    "MidisrvTransferComplete", "LoadAppInit_DLLs",
    "RequireSignedAppInit_DLLs",
))

# Value names that look like switches and are NOT. Listed explicitly so a later
# widening of SWITCH_SETTINGS cannot quietly swallow one of them.
NEVER_A_SWITCH = frozenset((
    "Version", "Type", "Start", "State", "Count", "Size", "Order", "Index",
    "Category", "Managed", "NameType", "AddressType", "SetupType",
    "SetupPhase", "ErrorMode", "DefaultColor", "CSDVersion", "CSDReleaseType",
    "StandardBias", "DaylightBias", "Bias", "ActiveTimeBias",
    "LowDiskMinimumMBytes", "DhcpGatewayHardwareCount", "PowerSettingProfile",
    "ConsentPromptBehaviorAdmin", "ConsentPromptBehaviorUser",
    "ScRemoveOption", "NoDriveTypeAutoRun", "LastIpuStatus", "LsaCfgFlags",
))

# W32Time NtpServer trailing flags, e.g. "time.windows.com,0x9".
NTP_SERVER_FLAGS = (
    (0x01, "special interval"),
    (0x02, "use as fallback only"),
    (0x04, "symmetric active"),
    (0x08, "client"),
)

# A .lnk begins with a 76-byte header whose second field is this GUID.
_LNK_HEADER = bytes.fromhex("4C000000") + bytes.fromhex(
    "0114020000000000C000000000000046")


def decode_lcid(raw):
    """`0409` -> `English (United States) [LCID 0x0409]`, or "" if unknown."""
    code = str(raw or "").strip().upper().lstrip("0").rjust(4, "0")
    name = LCIDS.get(code)
    return "%s [LCID 0x%s]" % (name, code) if name else ""


def decode_switch(value):
    """A 0/1 switch as words. "" for anything that is not exactly 0 or 1."""
    text = str("" if value is None else value).strip()
    if text == "0":
        return "disabled"
    if text == "1":
        return "enabled"
    return ""


def decode_ntp_server(raw):
    """`time.windows.com,0x9` -> the host plus what the flag byte asks for."""
    text = str(raw or "")
    if "," not in text:
        return ""
    host, _, flags = text.rpartition(",")
    flags = flags.strip()
    try:
        bits = int(flags, 16) if flags.lower().startswith("0x") else int(flags)
    except ValueError:
        return ""
    named = [label for bit, label in NTP_SERVER_FLAGS if bits & bit]
    if not named:
        return ""
    return "%s (%s)" % (host.strip(), ", ".join(named))


def decode_filetime_at(data, offset):
    """A FILETIME embedded at a known offset inside a blob."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < offset + 8:
        return ""
    try:
        return parse_filetime(bytes(data[offset:offset + 8])) or ""
    except Exception:
        return ""


def expand_environment_strings(text, env):
    r"""Expand %VARIABLES% using values read from the EVIDENCE, not this machine.

    `os.path.expandvars` would reach for the analyst's own environment, and on
    an offline image that is somebody else's computer: a machine installed to
    D:\Windows would be reported as C:\Windows because that is where the
    examiner's Windows lives. The caller supplies what it read from the hive,
    and a variable that is not in there is left standing rather than guessed.
    """
    if not env or not text:
        return ""
    out = str(text)
    for name, value in env.items():
        if not value:
            continue
        token = ("%" + str(name) + "%").lower()
        lowered = out.lower()
        start = lowered.find(token)
        while start != -1:
            out = out[:start] + str(value) + out[start + len(token):]
            lowered = out.lower()
            start = lowered.find(token)
    return out if out != str(text) else ""


def shell_item_lists(data):
    """The ItemIDLists inside a Taskband Favorites blob.

    Layout, read off the bytes rather than assumed: each record is a 0x00 byte,
    a 4-byte little-endian length, then that many bytes of a standard shell
    ItemIDList; the sequence ends at 0xFF. On the reference system all eleven
    records account for every one of the 11,036 bytes.

    Bounded on every axis - a record header that is not 0x00, a length running
    past the buffer, or more than 512 records ends the walk. A blob this cannot
    read returns nothing, and the caller keeps the hex.
    """
    out, offset = [], 0
    if not isinstance(data, (bytes, bytearray)):
        return out
    data = bytes(data)
    while offset + 5 <= len(data) and len(out) < 512:
        if data[offset] != 0x00:
            break                                   # 0xFF terminator, or junk
        size = int.from_bytes(data[offset + 1:offset + 5], "little")
        end = offset + 5 + size
        if size <= 0 or end > len(data):
            break
        out.append(data[offset + 5:end])
        offset = end
    return out


def shell_item_names(idlist):
    """The names in one ItemIDList, outermost first.

    `parse_shell_item_id` reads the 2-byte size at offset 0 and the type at
    offset 2, so each item is passed WITH its size prefix. Stripping it shifts
    every field by two and quietly returns a name two characters short -
    "ave.lnk" for "Brave.lnk".
    """
    names, offset, seen = [], 0, 0
    while offset + 2 <= len(idlist) and seen < 64:
        size = int.from_bytes(idlist[offset:offset + 2], "little")
        if size == 0:
            break
        if size < 3 or offset + size > len(idlist):
            break
        try:
            parsed = parse_shell_item_id(idlist[offset:offset + size]) or {}
        except Exception:
            parsed = {}
        name = (parsed.get("file_name") or parsed.get("special_folder")
                or parsed.get("drive_letter") or "")
        if name:
            names.append(str(name))
        offset += size
        seen += 1
    return names


def decode_taskband(data):
    r"""The pinned taskbar items, in the order Explorer stores them.

    Verified against the reference system: the five filesystem records decode
    to exactly the five .lnk files in `User Pinned\TaskBar`, and the other six
    are the Applications folder GUID - Store apps pinned by AUMID, which have
    no .lnk at all. That is why the count is larger than that folder's.
    """
    lists = shell_item_lists(data)
    if not lists:
        return ""
    pinned, apps = [], 0
    for idlist in lists:
        names = shell_item_names(idlist)
        leaf = names[-1] if names else ""
        if leaf and not leaf.startswith("{"):
            pinned.append(leaf)
        else:
            apps += 1
    parts = []
    if pinned:
        parts.append("%d pinned: %s" % (len(pinned), ", ".join(pinned)))
    if apps:
        parts.append("%d by app id (no shortcut)" % apps)
    return "; ".join(parts)


def decode_favorites_resolve(data):
    """How many shortcuts Taskband kept beside the pins, and their sizes.

    FavoritesResolve is NOT the same layout as Favorites: it is a run of
    `<4-byte length><.lnk file>` records. Each embedded shortcut carries the
    target path, so a full decode belongs to the LNK parser rather than here -
    what this reports is the count, checked against the shortcut signature so
    the number means something rather than being a guess at the framing.
    """
    if not isinstance(data, (bytes, bytearray)):
        return ""
    data = bytes(data)
    offset, records, total = 0, 0, 0
    while offset + 4 <= len(data) and records < 512:
        size = int.from_bytes(data[offset:offset + 4], "little")
        body = data[offset + 4:offset + 4 + size]
        if size <= 0 or offset + 4 + size > len(data):
            break
        if not body.startswith(_LNK_HEADER):
            break                                   # not the framing we think
        records += 1
        total += size
        offset += 4 + size
    if not records:
        return ""
    return ("%d resolved shortcut(s), %d bytes - target paths are in the "
            "shortcuts themselves" % (records, total))


def decode_by_name(value_name, data, value_type=None, env=None):
    r"""The decoders that hold whatever key the value came from.

    This is the fallback layer: a locale, a switch, an NTP flag field or an
    unexpanded %VARIABLE% means the same thing under any key, so every artifact
    gets them without needing a rule of its own.
    """
    name = str(value_name or "").strip()

    if name in ("Default", "InstallLanguage", "InstallLanguageFallback"):
        return decode_lcid(data)

    if name == "NtpServer":
        return decode_ntp_server(data)

    if name in NEVER_A_SWITCH:
        return ""
    if name in SWITCH_SETTINGS:
        return decode_switch(data)

    if isinstance(data, str) and "%" in data:
        expandable = (value_type in (2, "REG_EXPAND_SZ")
                      or data.count("%") >= 2)
        if expandable:
            return expand_environment_strings(data, env)
    return ""


REGISTRY_VALUE_RULES = {
    "timezone": {
        "bias": _tz_bias,
        "activetimebias": _tz_bias,
        "standardbias": _tz_season_bias,
        "daylightbias": _tz_season_bias,
        "standardstart": _tz_rule,
        "daylightstart": _tz_rule,
        "dynamicdaylighttimedisabled":
            lambda d, t: "enabled - the clocks are held fixed" if _truthy(d)
            else "disabled - seasonal changes apply",
    },
    # The flat configuration keys. Only the values that need a rule of their
    # own are here; locales, switches and %VARIABLE% expansion are handled by
    # the name-driven fallback in render_registry_value, which serves every
    # context rather than this one.
    "system_configuration": {
        "health": lambda d, t: (
            "last state change %s" % decode_filetime_at(d, 8))
            if decode_filetime_at(d, 8) else "",
        "favorites": lambda d, t: decode_taskband(d),
        "favoritesresolve": lambda d, t: decode_favorites_resolve(d),
    },
    "networklist": {
        "defaultgatewaymac": lambda d, t: format_mac_address(d),
        "category": lambda d, t: network_category_label(d),
        "nametype": lambda d, t: network_name_type_label(d),
        "managed": lambda d, t: network_managed_label(d),
        "datecreated": lambda d, t: parse_systemtime(d),
        "datelastconnected": lambda d, t: parse_systemtime(d),
    },
    "bam": {},          # every binary value is an entry; handled below
    "network_interfaces": {
        "leaseobtainedtime": lambda d, t: unix_seconds_label(d),
        "leaseterminatestime": lambda d, t: unix_seconds_label(d),
        "t1": lambda d, t: unix_seconds_label(d),
        "t2": lambda d, t: unix_seconds_label(d),
        "dhcpgatewayhardware": lambda d, t: _gateway_hardware_label(d),
        "enabledhcp": _yes_no,
        "isservernapaware": _yes_no,
        "dhcpconnforcebroadcastflag": _yes_no,
    },
}


def _truthy(value):
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        return bool(value)


def _gateway_hardware_label(data):
    got = parse_dhcp_gateway_hardware(data)
    if not got["gateway_ip"]:
        return ""
    if got["gateway_mac"]:
        return "gateway %s at %s" % (got["gateway_ip"], got["gateway_mac"])
    return "gateway %s" % got["gateway_ip"]


def _bam_label(value_name, data):
    if is_bam_metadata(value_name):
        return "BAM bookkeeping, not a program"
    got = parse_bam_blob(data)
    if not got["last_execution"]:
        return ""
    bits = [got["last_execution"]]
    if got["name_kind"]:
        bits.append("name is a %s" % got["name_kind"])
    return "  -  ".join(bits)


def render_registry_value(context, value_name, data, value_type=None, env=None):
    """The readable form of one raw registry value.

    `context` names the artifact, because the same value name means different
    things under different keys - which is the whole reason this is a table of
    rules and not one function with a long if.

    Three layers, in order:

      1. the context's own rule, for values that mean something particular
         under that key;
      2. `decode_by_name`, for the things that mean the same under ANY key - a
         locale, a 0/1 switch, an NTP flag field, an unexpanded %VARIABLE%.
         This layer is why one move made twenty tables decodable instead of
         one: without it every artifact would need its own copy of the same
         four rules;
      3. hex, for bytes nothing above could read.

    `env` is the expansion environment read from the EVIDENCE; without it no
    %VARIABLE% is expanded, which is the correct answer for an offline image
    whose SystemRoot is not the examiner's.

    Never raises: a value it cannot decode comes back as text or hex, which is
    still better than the Python bytes repr that was being stored.
    """
    try:
        name = str(value_name or "").strip().lower()
        if context == "bam":
            return _bam_label(value_name, data)
        rule = REGISTRY_VALUE_RULES.get(context, {}).get(name)
        if rule is not None:
            got = rule(data, value_type)
            if got:
                return got
        got = decode_by_name(value_name, data, value_type, env)
        if got:
            return got
        raw = _as_bytes(data)
        if raw is None:
            return ""          # text values are already readable as stored
        return bytes_as_hex(raw)
    except Exception as exc:               # pragma: no cover
        logger.debug("render_registry_value(%s/%s): %s", context, value_name, exc)
        return ""
