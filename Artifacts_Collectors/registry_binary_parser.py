"""
Binary parsing utilities for Windows registry forensic artifacts.

This module provides specialized parsing functions for complex binary structures
found in Windows registry keys such as OpenSaveMRU, LastSaveMRU, BAM, DAM, and RecentDocs.
"""

import struct
import logging
from datetime import datetime, timedelta

# Configure logging
logger = logging.getLogger(__name__)


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
        
        # Convert to datetime
        # FILETIME epoch: January 1, 1601
        # Unix epoch: January 1, 1970
        # Difference: 11644473600 seconds
        FILETIME_EPOCH_DIFF = 116444736000000000  # in 100-nanosecond intervals
        
        # Convert to microseconds (divide by 10)
        microseconds = (filetime - FILETIME_EPOCH_DIFF) / 10
        
        # Create datetime object
        dt = datetime(1970, 1, 1) + timedelta(microseconds=microseconds)
        
        # Return ISO 8601 format
        return dt.strftime('%Y-%m-%d %H:%M:%S')
        
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
    Parse Shell Item ID structure and extract file path information.
    
    Shell Item IDs are variable-length binary structures used by Windows Explorer
    to represent file system objects. This function extracts path components
    and reconstructs full paths from these structures.
    
    Args:
        binary_data: Binary data containing Shell Item ID structure(s)
    
    Returns:
        Dictionary containing:
            - 'path': Reconstructed file path
            - 'items': List of individual path components
            - 'type': Type of shell item (file, folder, network, etc.)
        
    Raises:
        ValueError: If binary data is invalid
    """
    try:
        if not binary_data or len(binary_data) < 2:
            logger.warning(f"Invalid Shell Item ID data: expected at least 2 bytes, got {len(binary_data) if binary_data else 0}")
            return {'path': '', 'items': [], 'type': 'unknown'}
        
        path_components = []
        offset = 0
        shell_type = 'unknown'
        
        while offset < len(binary_data) - 1:
            # Read size of this Shell Item ID (2 bytes, little-endian)
            if offset + 2 > len(binary_data):
                break
                
            size = struct.unpack('<H', binary_data[offset:offset + 2])[0]
            
            # Size of 0 indicates end of list
            if size == 0:
                break
            
            # Ensure we don't read beyond buffer
            if offset + size > len(binary_data):
                break
            
            # Extract this Shell Item ID
            item_data = binary_data[offset:offset + size]
            
            # Parse the item based on type indicator (byte at offset 2)
            if len(item_data) > 2:
                type_indicator = item_data[2]
                
                # Skip special GUID items (0x1F) - these represent special folders like
                # "My Computer", "Desktop", etc. and don't contain useful path information
                if type_indicator == 0x1F:
                    pass  # Skip this item
                
                # File system object (0x30-0x3F range)
                elif 0x30 <= type_indicator <= 0x3F:
                    shell_type = 'filesystem'
                    path_component = _extract_filesystem_path(item_data)
                    if path_component:
                        path_components.append(path_component)
                
                # Network location (0x40-0x4F range)
                elif 0x40 <= type_indicator <= 0x4F:
                    shell_type = 'network'
                    path_component = _extract_network_path(item_data)
                    if path_component:
                        path_components.append(path_component)
                
                # Drive letter (0x20-0x2F range)
                elif 0x20 <= type_indicator <= 0x2F:
                    shell_type = 'drive'
                    path_component = _extract_drive_path(item_data)
                    if path_component:
                        path_components.append(path_component)
                
                # Try to extract any readable string from other types
                else:
                    path_component = _extract_generic_path(item_data)
                    if path_component:
                        path_components.append(path_component)
            
            # Move to next Shell Item ID
            offset += size
        
        # Reconstruct full path
        if path_components:
            full_path = '\\'.join(path_components)
        else:
            full_path = ''
        
        return {
            'path': full_path,
            'items': path_components,
            'type': shell_type
        }
        
    except Exception as e:
        logger.error(f"Error parsing Shell Item ID: {e}")
        return {'path': '', 'items': [], 'type': 'unknown'}


def _extract_filesystem_path(item_data: bytes) -> str:
    """
    Extract path component from filesystem Shell Item ID.
    
    Args:
        item_data: Binary data for a single Shell Item ID
    
    Returns:
        Path component string or empty string
    """
    try:
        # File system items typically have name at offset 0x04 or later
        # Structure: [size:2][type:1][flags:1][...metadata...][short_name][...][long_name]
        
        # Look for short name (8.3 format) - usually ASCII at offset 0x0E
        short_name = ""
        if len(item_data) > 0x10:
            # Try to extract short name at offset 0x0E (common location)
            short_name_offset = 0x0E
            for i in range(short_name_offset, min(len(item_data), short_name_offset + 12)):
                if item_data[i] == 0:
                    break
                if 0x20 <= item_data[i] <= 0x7E:  # Printable ASCII
                    short_name += chr(item_data[i])
        
        # Try to find long name (Unicode) - usually after offset 0x40
        # The long name is typically preceded by a size marker
        best_unicode = ""
        best_score = 0
        
        for offset in range(0x40, len(item_data) - 8, 2):
            # Look for potential Unicode string start
            if item_data[offset] != 0 and item_data[offset + 1] == 0:
                # Check if this is a printable ASCII character (most filenames start with these)
                if 0x41 <= item_data[offset] <= 0x7A:  # A-Z or a-z
                    # Check if the previous 2 bytes are also a letter (might be part of the same string)
                    if offset >= 2:
                        prev_byte = item_data[offset - 2]
                        prev_null = item_data[offset - 1]
                        # If previous is also a letter in UTF-16-LE format, skip this offset
                        if prev_null == 0 and 0x41 <= prev_byte <= 0x7A:
                            continue
                    
                    # Potential Unicode string
                    unicode_str = extract_unicode_string(item_data, offset)
                    if unicode_str and len(unicode_str) > 3:  # Must be at least 4 chars to avoid single-char artifacts
                        # Check if this looks like "xName" pattern where x is lowercase and Name starts with uppercase
                        # This often indicates the first character is an artifact
                        if (len(unicode_str) > 1 and 
                            unicode_str[0].islower() and 
                            unicode_str[1].isupper()):
                            # Try extracting from 2 bytes later (skip the first character)
                            alt_offset = offset + 2
                            if alt_offset < len(item_data) - 4:
                                alt_str = extract_unicode_string(item_data, alt_offset)
                                if alt_str and len(alt_str) > 3:
                                    unicode_str = alt_str
                        
                        # Score this string based on how "filename-like" it is
                        # Higher score = more likely to be the actual filename
                        score = 0
                        
                        # Prefer strings that start with uppercase (more common for folder names)
                        if unicode_str[0].isupper():
                            score += 15
                        elif unicode_str[0].isalnum():
                            score += 10
                        
                        # Prefer longer strings
                        score += len(unicode_str)
                        
                        # Prefer strings with high ratio of valid filename characters
                        valid_chars = sum(1 for c in unicode_str if c.isalnum() or c in ' .-_()[]{}')
                        if len(unicode_str) > 0:
                            char_ratio = valid_chars / len(unicode_str)
                            score += int(char_ratio * 20)
                        
                        # Penalize strings with control characters
                        control_chars = sum(1 for c in unicode_str if ord(c) < 32)
                        score -= control_chars * 5
                        
                        if score > best_score:
                            best_score = score
                            best_unicode = unicode_str
        
        # Return the best match
        if best_unicode and best_score > 10:
            return best_unicode
        
        # Fallback to short name if we found one
        if short_name and len(short_name) > 1:
            return short_name
        
        return ""
        
    except Exception as e:
        logger.error(f"Error extracting filesystem path: {e}")
        return ""


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
    
    Args:
        item_data: Binary data for a single Shell Item ID
    
    Returns:
        Drive letter (e.g., "C:") or empty string
    """
    try:
        # Drive items typically have drive letter at a fixed offset
        # Look for pattern like "C:\" in ASCII
        for offset in range(0x03, min(len(item_data) - 2, 0x20)):
            if (0x41 <= item_data[offset] <= 0x5A or  # A-Z
                0x61 <= item_data[offset] <= 0x7A):    # a-z
                if offset + 1 < len(item_data) and item_data[offset + 1] == 0x3A:  # ':'
                    drive_letter = chr(item_data[offset]).upper() + ":"
                    return drive_letter
        
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


def parse_opensavemru_entry(binary_data: bytes) -> dict:
    """
    Parse OpenSaveMRU binary entry to extract file path and metadata.
    
    OpenSaveMRU entries contain PIDL (Pointer to Item IDentifier List) structures
    that encode file paths accessed through common Open/Save dialogs.
    
    Args:
        binary_data: Binary data from OpenSaveMRU registry value
    
    Returns:
        Dictionary containing:
            - 'file_path': Full file path extracted from PIDL
            - 'extension': File extension (if available)
            - 'access_date': Last access date (if available)
            - 'raw_data': Original binary data (for fallback)
        
    Raises:
        ValueError: If binary data is invalid
    """
    try:
        if not binary_data:
            logger.warning("Empty binary data provided to parse_opensavemru_entry")
            return {
                'file_path': '',
                'extension': '',
                'access_date': '',
                'raw_data': binary_data
            }
        
        # Parse the PIDL structure to extract file path
        shell_item_result = parse_shell_item_id(binary_data)
        file_path = shell_item_result.get('path', '')
        
        # Extract file extension from the path
        extension = ''
        if file_path and '.' in file_path:
            # Get the last component after the last backslash
            filename = file_path.split('\\')[-1]
            if '.' in filename:
                extension = filename.split('.')[-1].lower()
        
        # Try to extract timestamp if present in the binary data
        # Some OpenSaveMRU entries may contain FILETIME at the end
        access_date = ''
        if len(binary_data) >= 8:
            # Check last 8 bytes for potential FILETIME
            # FILETIME values are typically very large numbers
            try:
                potential_filetime = binary_data[-8:]
                filetime_value = struct.unpack('<Q', potential_filetime)[0]
                
                # Validate that it looks like a reasonable FILETIME
                # (between year 1980 and 2100)
                if 119600064000000000 < filetime_value < 159017088000000000:
                    access_date = parse_filetime(potential_filetime)
            except:
                pass  # Not a valid timestamp, ignore
        
        result = {
            'file_path': file_path,
            'extension': extension,
            'access_date': access_date,
            'raw_data': binary_data
        }
        
        logger.debug(f"Parsed OpenSaveMRU entry: path={file_path}, ext={extension}")
        return result
        
    except Exception as e:
        logger.error(f"Error parsing OpenSaveMRU entry: {e}")
        return {
            'file_path': '',
            'extension': '',
            'access_date': '',
            'raw_data': binary_data
        }


def parse_lastsavemru_entry(binary_data: bytes) -> dict:
    """
    Parse LastVisitedPidlMRU binary entry to extract application and folder path.
    
    LastVisitedPidlMRU entries contain:
    1. Application executable name (null-terminated Unicode string at the beginning)
    2. PIDL structure containing the folder path
    
    Args:
        binary_data: Binary data from LastVisitedPidlMRU registry value
    
    Returns:
        Dictionary containing:
            - 'application': Application executable name
            - 'folder_path': Folder path extracted from PIDL
            - 'raw_data': Original binary data (for fallback)
        
    Raises:
        ValueError: If binary data is invalid
    """
    try:
        if not binary_data:
            logger.warning("Empty binary data provided to parse_lastsavemru_entry")
            return {
                'application': '',
                'folder_path': '',
                'raw_data': binary_data
            }
        
        # Extract application name from the beginning (null-terminated Unicode)
        application = extract_unicode_string(binary_data, offset=0)
        
        # Calculate offset to PIDL structure
        # The PIDL starts after the null-terminated Unicode string
        # Each Unicode character is 2 bytes, plus 2 bytes for null terminator
        pidl_offset = 0
        if application:
            # Find the end of the null-terminated string
            # Unicode strings are UTF-16-LE, so null terminator is 0x0000 (2 bytes)
            while pidl_offset < len(binary_data) - 1:
                if binary_data[pidl_offset] == 0 and binary_data[pidl_offset + 1] == 0:
                    pidl_offset += 2  # Skip past the null terminator
                    break
                pidl_offset += 2
        
        # Extract folder path from PIDL structure
        folder_path = ''
        if pidl_offset < len(binary_data):
            pidl_data = binary_data[pidl_offset:]
            
            # Parse the PIDL structure
            shell_item_result = parse_shell_item_id(pidl_data)
            folder_path = shell_item_result.get('path', '')
        
        result = {
            'application': application,
            'folder_path': folder_path,
            'raw_data': binary_data
        }
        
        logger.debug(f"Parsed LastSaveMRU entry: app={application}, folder={folder_path}")
        return result
        
    except Exception as e:
        logger.error(f"Error parsing LastSaveMRU entry: {e}")
        return {
            'application': '',
            'folder_path': '',
            'raw_data': binary_data
        }


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
    
    Binary Structure (Windows 7+, Version 5):
        Offset  Size  Description
        ------  ----  -----------
        0x00    4     Version number (0x00000005)
        0x04    4     Run count
        0x08    4     Application focus count
        0x0C    4     Application focus time (milliseconds)
        0x10    8     Last execution time (FILETIME)
    
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
            logger.warning(f"Invalid UserAssist binary data: expected at least 16 bytes, got {len(binary_data) if binary_data else 0}")
            return result
        
        # Parse version number (first 4 bytes)
        version = struct.unpack('<I', binary_data[0:4])[0]
        
        if version == 5:
            # Windows 7/8/10/11 format
            if len(binary_data) >= 24:
                result['run_count'] = struct.unpack('<I', binary_data[4:8])[0]
                result['focus_count'] = struct.unpack('<I', binary_data[8:12])[0]
                result['focus_time'] = struct.unpack('<I', binary_data[12:16])[0]
                result['last_execution'] = parse_filetime(binary_data[16:24])
            else:
                logger.warning(f"UserAssist Version 5 data too short: expected 24 bytes, got {len(binary_data)}")
        
        elif version == 3:
            # Windows XP/Vista format
            if len(binary_data) >= 16:
                result['run_count'] = struct.unpack('<I', binary_data[4:8])[0]
                result['last_execution'] = parse_filetime(binary_data[8:16])
            else:
                logger.warning(f"UserAssist Version 3 data too short: expected 16 bytes, got {len(binary_data)}")
        
        else:
            logger.warning(f"Unknown UserAssist version: {version}")
        
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



def _convert_dos_datetime(dos_time: int) -> str:
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
        if dos_time == 0:
            return ""
        
        date = dos_time & 0xFFFF
        time = (dos_time >> 16) & 0xFFFF
        
        day = date & 0x1F
        month = (date >> 5) & 0x0F
        year = ((date >> 9) & 0x7F) + 1980
        
        seconds = (time & 0x1F) * 2
        minutes = (time >> 5) & 0x3F
        hours = (time >> 11) & 0x1F
        
        # Validate values
        if not (1 <= day <= 31 and 1 <= month <= 12 and 1980 <= year <= 2100):
            return ""
        if not (0 <= hours <= 23 and 0 <= minutes <= 59 and 0 <= seconds <= 59):
            return ""
        
        dt = datetime(year, month, day, hours, minutes, seconds)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
        
    except Exception:
        return ""


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
            - 'folder_path': Full folder path extracted from Shell Item ID
            - 'folder_name': Last component of the folder path (folder name)
            - 'shell_item_type': Type of shell item (filesystem, network, drive, etc.)
            - 'created_date': Creation timestamp (if available)
            - 'modified_date': Modification timestamp (if available)
            - 'accessed_date': Access timestamp (if available)
            - 'attributes': Comma-separated file attributes (readonly, hidden, etc.)
            - 'file_size': File/folder size in bytes
            - 'special_folder': Special folder name (My Computer, etc.)
            - 'network_share': Network share path (if applicable)
    
    Raises:
        ValueError: If binary data is invalid
    """
    try:
        if not binary_data:
            logger.warning("Empty binary data provided to parse_shellbag_entry")
            return {
                'folder_path': '',
                'folder_name': '',
                'shell_item_type': 'unknown',
                'created_date': '',
                'modified_date': '',
                'accessed_date': '',
                'attributes': '',
                'file_size': 0,
                'special_folder': '',
                'network_share': ''
            }
        
        # Parse the Shell Item ID structure to extract folder information
        shell_item_result = parse_shell_item_id(binary_data)
        
        folder_path = shell_item_result.get('path', '')
        shell_item_type = shell_item_result.get('type', 'unknown')
        
        # Extract folder name from the full path
        folder_name = ''
        if folder_path:
            if '\\' in folder_path:
                folder_name = folder_path.split('\\')[-1]
            else:
                folder_name = folder_path
        
        # Initialize enhanced metadata
        created_date = ''
        modified_date = ''
        accessed_date = ''
        attributes = []
        file_size = 0
        special_folder = ''
        network_share = ''
        
        # Process first Shell Item for enhanced metadata
        if len(binary_data) >= 2:
            size = struct.unpack('<H', binary_data[0:2])[0]
            if size > 2 and len(binary_data) >= size:
                item_data = binary_data[0:size]
                
                if len(item_data) > 2:
                    type_indicator = item_data[2]
                    
                    # Special folder (GUID-based)
                    if type_indicator == 0x1F and len(item_data) >= 20:
                        guid_bytes = item_data[4:20]
                        guid_str = _format_guid(guid_bytes)
                        special_folder = _SPECIAL_FOLDER_GUIDS.get(guid_str, '')
                    
                    # Filesystem object
                    elif 0x30 <= type_indicator <= 0x3F:
                        # Extract attributes
                        attr_info = _extract_folder_attributes(item_data)
                        attributes = attr_info['attributes']
                        
                        # Extract DOS timestamp (modified time at offset 0x08)
                        if len(item_data) >= 12:
                            dos_time = struct.unpack('<I', item_data[8:12])[0]
                            modified_date = _convert_dos_datetime(dos_time)
                        
                        # Extract file size (at offset 0x0C)
                        if len(item_data) >= 16:
                            file_size = struct.unpack('<I', item_data[12:16])[0]
                        
                        # Try to extract FILETIME timestamps from extension blocks
                        if len(item_data) >= 0x50:
                            for ts_offset in [0x18, 0x20, 0x28, 0x30, 0x38]:
                                if ts_offset + 8 <= len(item_data):
                                    try:
                                        filetime_value = struct.unpack('<Q', item_data[ts_offset:ts_offset + 8])[0]
                                        if 119600064000000000 < filetime_value < 159017088000000000:
                                            timestamp = parse_filetime(item_data[ts_offset:ts_offset + 8])
                                            if timestamp and not created_date:
                                                created_date = timestamp
                                            elif timestamp and not accessed_date:
                                                accessed_date = timestamp
                                    except:
                                        continue
                    
                    # Network location
                    elif 0x40 <= type_indicator <= 0x4F:
                        # Extract network share path
                        if folder_path and ('\\\\' in folder_path or folder_path.startswith('\\\\')):
                            network_share = folder_path
        
        # Fallback: Try to find FILETIME values in the entire binary data
        if not modified_date and not accessed_date and len(binary_data) >= 16:
            for offset in [8, 16, 24, 32, 40]:
                if offset + 8 <= len(binary_data):
                    try:
                        filetime_value = struct.unpack('<Q', binary_data[offset:offset + 8])[0]
                        if 119600064000000000 < filetime_value < 159017088000000000:
                            timestamp = parse_filetime(binary_data[offset:offset + 8])
                            if timestamp and not modified_date:
                                modified_date = timestamp
                            elif timestamp and not accessed_date:
                                accessed_date = timestamp
                    except:
                        continue
        
        result = {
            'folder_path': folder_path,
            'folder_name': folder_name,
            'shell_item_type': shell_item_type,
            'created_date': created_date,
            'modified_date': modified_date,
            'accessed_date': accessed_date,
            'attributes': ', '.join(attributes) if attributes else '',
            'file_size': file_size,
            'special_folder': special_folder,
            'network_share': network_share
        }
        
        logger.debug(f"Parsed Shellbag entry: path={folder_path}, name={folder_name}, type={shell_item_type}")
        return result
        
    except Exception as e:
        logger.error(f"Error parsing Shellbag entry: {e}")
        return {
            'folder_path': '',
            'folder_name': '',
            'shell_item_type': 'unknown',
            'created_date': '',
            'modified_date': '',
            'accessed_date': ''
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
        value_name: Full application path (e.g., "C:\\Windows\\System32\\notepad.exe")
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
        
        # Extract application path (value name)
        app_path = value_name.strip()
        
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
            'file_extension': file_extension
        }
        
        logger.debug(f"Parsed MUICache entry: path={app_path}, name={app_name}, ext={file_extension}")
        return result
        
    except Exception as e:
        logger.error(f"Error parsing MUICache entry: {e}")
        return {
            'app_path': value_name if value_name else '',
            'app_name': value_data if value_data else '',
            'file_extension': ''
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
