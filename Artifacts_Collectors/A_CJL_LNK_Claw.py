import os
import sys
import sqlite3
from datetime import datetime, timezone, timedelta
import shutil
import struct
import uuid
import re
import string
import traceback
import json
from utils.time_utils import format_forensic_timestamp

try:
    import olefile
except ImportError:
    print(" [!] Please install olefile: pip install olefile")
    sys.exit(1)

# Constants for magic numbers
FILETIME_THRESHOLD = 10000000000000000  # Threshold for Windows FILETIME detection
UNIX_TIMESTAMP_LIMIT = 2147483647       # Unix timestamp limit for 32-bit systems
appid_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Known_AppIDs.csv')
guid_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Known_GUIDs.csv')

def read_KnownGuids(path):
    guids = {}
    if not os.path.exists(path):
        return guids
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        # Skip header
        next(f, None)
        for l in f:
            fields = l.rstrip().split(',')
            if len(fields) >= 2:
                # Key is GUID (uppercase for matching), Value is name
                guids[fields[0].strip().upper()] = fields[1].strip()
    return guids

def read_AppId(path):
    appid = {}
    if not os.path.exists(path):
        return appid
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for l in f:
            fields = l.rstrip().split(',')
            if len(fields) >= 3:
                appid[fields[1].strip().lower()] = (fields[0].strip(), fields[2].strip())
    return appid
def unpack_int(data, type_='int'):
    if len(data) == 0: return 0
    if type_ == 'int':
        if len(data) == 1: return struct.unpack('<B', data)[0]
        if len(data) == 2: return struct.unpack('<H', data)[0]
        if len(data) == 4: return struct.unpack('<I', data)[0]
        if len(data) == 8: return struct.unpack('<Q', data)[0]
    elif type_ == 'mac':
        if len(data) >= 6:
            return "%02x:%02x:%02x:%02x:%02x:%02x" % struct.unpack("BBBBBB", data[:6])
    elif type_ == 'uuid':
        if len(data) >= 16:
            return str(uuid.UUID(bytes_le=data[:16]))
    elif type_ == 'printable':
        s = data.decode('ascii', errors='ignore')
        return ''.join(filter(lambda x: x in string.printable, s)).strip('\0')
    elif type_ == 'guid':
        if len(data) >= 16:
            # GUID Format: {00000000-0000-0000-0000-000000000000}
            u = uuid.UUID(bytes_le=data[:16])
            return "{" + str(u).upper() + "}"
    elif type_ == 'hex':
        return '0x' + data.hex().upper()
    return 0

def ad_timestamp(filetime, isObject=False):
    if filetime == 0 or filetime is None: return ""
    try:
        # If it's an ObjectID timestamp, it's often 100ns since Oct 15, 1582
        if isObject:
            # Shift from 1582 to 1601 epoch
            filetime -= 5748192000000000
        
        # Filter out invalid timestamps that are too small (< 1 year from epoch)
        # 1 year in 100-nanosecond units = 365.25 * 24 * 60 * 60 * 10,000,000 = 315,576,000,000,000
        MIN_VALID_FILETIME = 315576000000000  # ~1 year from 1601-01-01
        
        if filetime > MIN_VALID_FILETIME:
            windows_epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
            # Use integer division to prevent float errors
            dt = windows_epoch + timedelta(microseconds=filetime // 10)
            
            # Additional validation: timestamp should be between 1602 and 2100
            if datetime(1602, 1, 1, tzinfo=timezone.utc) <= dt <= datetime(2100, 1, 1, tzinfo=timezone.utc):
                return format_forensic_timestamp(dt)
    except Exception:
        pass
    return ""

def windows_filetime_to_unix(filetime):
    try:
        FILETIME_EPOCH_DIFF = 11644473600
        if isinstance(filetime, int):
            return (filetime / 10000000.0) - FILETIME_EPOCH_DIFF
        return None
    except (ValueError, TypeError, OverflowError):
        return None

def format_time(timestamp):
    try:
        if timestamp is None or timestamp == "":
            return "N/A"
        if isinstance(timestamp, str):
            try:
                dt = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S')
                return format_forensic_timestamp(dt)
            except ValueError:
                try:
                    timestamp = int(timestamp)
                except ValueError:
                    return timestamp
        if isinstance(timestamp, int):
            if timestamp > FILETIME_THRESHOLD:
                unix_timestamp = windows_filetime_to_unix(timestamp)
                if unix_timestamp:
                    timestamp = unix_timestamp
                else:
                    return "Invalid FILETIME"
            if timestamp > UNIX_TIMESTAMP_LIMIT:
                try:
                    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                    return format_forensic_timestamp(dt)
                except (ValueError, OSError, OverflowError):
                    for divisor in [1000, 1000000, 1000000000]:
                        try:
                            adjusted_timestamp = timestamp / divisor
                            if 0 < adjusted_timestamp < UNIX_TIMESTAMP_LIMIT:
                                dt = datetime.fromtimestamp(adjusted_timestamp, tz=timezone.utc)
                                return format_forensic_timestamp(dt)
                        except (ValueError, OSError, OverflowError):
                            continue
                    return f"Timestamp too large: {timestamp}"
            else:
                dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                return format_forensic_timestamp(dt)
        if isinstance(timestamp, float):
            try:
                dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                return format_forensic_timestamp(dt)
            except (ValueError, OSError, OverflowError):
                return f"Invalid timestamp: {timestamp}"
        return str(timestamp)
    except Exception as e:
        return f"Error: {timestamp}"

def format_size(size):
    try:
        size = float(size)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"
    except (ValueError, TypeError):
        return str(size)

def format_duration(duration_value):
    """
    Format duration from 100-nanosecond units to human-readable format.
    
    Args:
        duration_value: Duration in 100-nanosecond units (Windows FILETIME format)
                       or seconds (integer)
    
    Returns:
        Human-readable duration string (e.g., "1h 23m 45s")
    """
    try:
        if duration_value is None or duration_value == "" or duration_value == 0:
            return "0s"
        
        # Convert to integer
        duration = int(duration_value)
        
        # If value is very large, assume it's in 100-nanosecond units
        # 100ns units: 10,000,000 = 1 second
        # So anything > 100,000,000 (10 seconds in 100ns) is likely in 100ns units
        if duration > 100000000:  # > 10 seconds in 100ns units
            seconds = duration / 10000000
        else:
            # Already in seconds
            seconds = duration
        
        # Convert to hours, minutes, seconds
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        # Format output
        parts = []
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if secs > 0 or len(parts) == 0:
            parts.append(f"{secs}s")
        
        return " ".join(parts)
    except (ValueError, TypeError):
        return str(duration_value)

def safe_sqlite_int(value):
    try:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            value = int(value)
        return value if abs(value) <= 2**63-1 else None
    except (ValueError, TypeError):
        return None

# Validation Functions (Requirement 22)

def validate_timestamp(timestamp):
    """
    Validate timestamp is within reasonable range (1601-2100).
    
    Requirement 22: Validate timestamp is within reasonable range (1601-2100).
    Return False if timestamp is 0 or out of range.
    
    Args:
        timestamp: Can be int (FILETIME), float (Unix timestamp), or datetime object
        
    Returns:
        bool: True if timestamp is valid, False otherwise
    """
    try:
        # Handle None or empty
        if timestamp is None or timestamp == "" or timestamp == 0:
            return False
        
        # Convert to datetime for validation
        dt = None
        
        if isinstance(timestamp, datetime):
            dt = timestamp
        elif isinstance(timestamp, int):
            # Check if it's a Windows FILETIME (large number)
            if timestamp > FILETIME_THRESHOLD:
                unix_ts = windows_filetime_to_unix(timestamp)
                if unix_ts is None:
                    return False
                dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
            else:
                # Unix timestamp
                dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        elif isinstance(timestamp, float):
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        elif isinstance(timestamp, str):
            # Try parsing ISO format
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except ValueError:
                return False
        else:
            return False
        
        # Validate range: 1601-01-01 to 2100-01-01
        min_date = datetime(1601, 1, 1, tzinfo=timezone.utc)
        max_date = datetime(2100, 1, 1, tzinfo=timezone.utc)
        
        return min_date <= dt <= max_date
        
    except (ValueError, OSError, OverflowError, TypeError):
        return False

def validate_mac_address(mac_data):
    """
    Validate MAC address is exactly 6 bytes and not all zeros.
    
    Requirement 22: Validate MAC address is exactly 6 bytes and not all zeros.
    
    Args:
        mac_data: Can be bytes (6 bytes) or string (colon-separated format)
        
    Returns:
        bool: True if MAC address is valid, False otherwise
    """
    try:
        # Handle None or empty
        if mac_data is None or mac_data == "":
            return False
        
        # If it's a string, parse it
        if isinstance(mac_data, str):
            # Remove colons and convert to bytes
            mac_hex = mac_data.replace(':', '').replace('-', '')
            if len(mac_hex) != 12:
                return False
            try:
                mac_bytes = bytes.fromhex(mac_hex)
            except ValueError:
                return False
        elif isinstance(mac_data, bytes):
            mac_bytes = mac_data
        else:
            return False
        
        # Validate exactly 6 bytes
        if len(mac_bytes) != 6:
            return False
        
        # Validate not all zeros
        if mac_bytes == b'\x00\x00\x00\x00\x00\x00':
            return False
        
        return True
        
    except (ValueError, TypeError):
        return False

def validate_uuid(uuid_data):
    """
    Validate UUID is exactly 16 bytes.
    
    Requirement 22: Validate UUID is exactly 16 bytes.
    
    Args:
        uuid_data: Can be bytes (16 bytes) or string (UUID format)
        
    Returns:
        bool: True if UUID is valid, False otherwise
    """
    try:
        # Handle None or empty
        if uuid_data is None or uuid_data == "":
            return False
        
        # If it's a string, parse it
        if isinstance(uuid_data, str):
            # Remove braces and dashes
            uuid_str = uuid_data.strip('{}').replace('-', '')
            if len(uuid_str) != 32:
                return False
            try:
                uuid_bytes = bytes.fromhex(uuid_str)
            except ValueError:
                return False
        elif isinstance(uuid_data, bytes):
            uuid_bytes = uuid_data
        else:
            return False
        
        # Validate exactly 16 bytes
        if len(uuid_bytes) != 16:
            return False
        
        return True
        
    except (ValueError, TypeError):
        return False

def validate_clsid(clsid_data):
    """
    Validate CLSID matches expected Shell Link CLSID.
    
    Requirement 22: Validate CLSID matches expected Shell Link CLSID.
    Return True if matches {00021401-0000-0000-C000-000000000046}.
    
    Args:
        clsid_data: Can be bytes (16 bytes) or string (GUID format)
        
    Returns:
        bool: True if CLSID matches Shell Link CLSID, False otherwise
    """
    # Expected Shell Link CLSID
    EXPECTED_CLSID = "{00021401-0000-0000-C000-000000000046}"
    
    try:
        # Handle None or empty
        if clsid_data is None or clsid_data == "":
            return False
        
        # If it's bytes, convert to GUID string
        if isinstance(clsid_data, bytes):
            if len(clsid_data) != 16:
                return False
            clsid_str = "{" + str(uuid.UUID(bytes_le=clsid_data)).upper() + "}"
        elif isinstance(clsid_data, str):
            # Normalize format
            clsid_str = clsid_data.strip().upper()
            if not clsid_str.startswith('{'):
                clsid_str = '{' + clsid_str
            if not clsid_str.endswith('}'):
                clsid_str = clsid_str + '}'
        else:
            return False
        
        # Compare with expected CLSID
        return clsid_str == EXPECTED_CLSID
        
    except (ValueError, TypeError):
        return False

# Parsers
def parse_DestList(data):
    """
    Parse DestList header and entries from AutomaticDestinations.
    
    Enhanced to extract all DestList metadata including header fields and entry details.
    Requirements: 4-12, 28-31
    
    Returns:
        (entries, header) tuple where:
            entries: list of dicts with entry metadata
            header: dict with header metadata
    """
    if len(data) < 32: return [], {}
    try:
        # Extract header fields (Requirements 11, 12, 31)
        header = {
            'Version_Number': unpack_int(data[:4]),
            'Total_Current_Entries': unpack_int(data[4:8]),
            'Total_Pinned_Entries': unpack_int(data[8:12]),
            'Last_Issued_ID_Num': unpack_int(data[16:24]),
            'Number_of_Actions': unpack_int(data[24:32])
        }
        
        # Map version to OS (Requirement 12)
        # Version 6 appears to be Windows 11 24H2 or later
        version_map = {1: "Windows 7/8", 3: "Windows 10", 4: "Windows 11", 6: "Windows 11 (24H2+)"}
        header['OS_Version'] = version_map.get(header['Version_Number'], f"Unknown (Version {header['Version_Number']})")
        
    except Exception: 
        return [], {}

    entries = []
    offset = 32
    for _ in range(min(header['Total_Current_Entries'], 2000)): # Safety cap
        if offset >= len(data): break
        entry_data = data[offset:]
        
        # Version 1 (Win 7/8) usually 114 bytes fixed
        # Version 3/4/6 (Win 10/11) usually 128 bytes fixed
        is_modern = header['Version_Number'] in [3, 4, 6]
        min_header = 128 if is_modern else 114
        
        if len(entry_data) < min_header: break
        
        try:
            entry = {}
            
            # Requirement 28: Extract Checksum from bytes [0:8]
            entry['Checksum'] = hex(unpack_int(entry_data[0:8]))
            
            # Requirement 29: Extract New_Volume_ID from bytes [8:24]
            entry['New_Volume_ID'] = unpack_int(entry_data[8:24], 'uuid')
            
            # Requirement 30: Extract New_Object_ID from bytes [24:40]
            entry['New_Object_ID'] = unpack_int(entry_data[24:40], 'uuid')
            
            # Requirement 9: Extract Object ID timestamp from bytes [24:32]
            entry['New_Object_ID_Timestamp'] = ad_timestamp(unpack_int(entry_data[24:32]), isObject=True)
            
            # Requirement 8: Extract MAC address from New_Object_ID bytes [34:40]
            entry['New_Object_ID_MAC_Addr'] = unpack_int(entry_data[34:40], 'mac')
            
            # Requirement 10: Extract Birth_Volume_ID from bytes [40:56]
            entry['Birth_Volume_ID'] = unpack_int(entry_data[40:56], 'uuid')
            
            # Requirement 10: Extract Birth_Object_ID from bytes [56:72]
            entry['Birth_Object_ID'] = unpack_int(entry_data[56:72], 'uuid')
            
            # Requirement 10: Extract MAC address from Birth_Object_ID bytes [66:72]
            entry['Birth_Object_ID_MAC_Addr'] = unpack_int(entry_data[66:72], 'mac')
            
            # Requirement 7: Extract NetBIOS name from bytes [72:88]
            entry['NetBIOS'] = unpack_int(entry_data[72:88], 'printable')
            
            # Requirement 4: Extract Last_Recorded_Access timestamp
            entry['Last_Recorded_Access'] = ad_timestamp(unpack_int(entry_data[100:108]))
            
            # Requirement 6: Extract Pin_Status from bytes [108:112]
            pin_status_val = unpack_int(entry_data[108:112])
            entry['Pin_Status_Counter'] = 'unpinned' if pin_status_val == 0xFFFFFFFF else str(pin_status_val)
            
            if is_modern:
                # Windows 10/11 format
                entry['Entry_ID_Number'] = str(unpack_int(entry_data[88:92]))
                # Requirement 5: Extract Access_Counter from bytes [116:120]
                entry['Access_Counter'] = unpack_int(entry_data[116:120])
                # String data starts at offset 128
                data_len = unpack_int(entry_data[128:130]) * 2
                entry['Data'] = unpack_int(entry_data[130:130+data_len], 'uni')
                offset += 128 + 2 + data_len + 4 # 128 fixed + 2 len + string + 4 trailing zero? Usually 128 + 2 + data_len is enough but some have 4 bytes extra
            else:
                # Windows 7/8 format
                entry['Entry_ID_Number'] = str(unpack_int(entry_data[88:96]))
                # Requirement 5: Extract Access counter as float in Version 1 from bytes [96:100]
                entry['Access_Counter'] = int(struct.unpack('<f', entry_data[96:100])[0]) if len(entry_data[96:100])==4 else 0
                data_len = unpack_int(entry_data[112:114]) * 2
                entry['Data'] = unpack_int(entry_data[114:114+data_len], 'uni')
                offset += 114 + data_len
                
            entries.append(entry)
        except Exception:
            break
            
    return entries, header

def parse_typed_value(data):
    if len(data) < 2: return None
    v_type = unpack_int(data[:2])
    v_body = data[2:]
    
    if v_type == 0x001F: # VT_LPWSTR
        if len(v_body) < 4: return None
        s_len = unpack_int(v_body[:4])
        return v_body[4:4+(s_len*2)].decode('utf-16-le', errors='ignore').strip('\0')
    elif v_type == 0x001E: # VT_LPSTR
        if len(v_body) < 4: return None
        s_len = unpack_int(v_body[:4])
        return v_body[4:4+s_len].decode('ascii', errors='ignore').strip('\0')
    elif v_type == 0x0040: # VT_FILETIME
        return ad_timestamp(unpack_int(v_body[:8]))
    elif v_type in [0x0003, 0x0013]: # VT_I4 or VT_UI4
        return unpack_int(v_body[:4])
    elif v_type in [0x0014, 0x0015]: # VT_I8 or VT_UI8
        return unpack_int(v_body[:8])
    elif v_type == 0x0012: # VT_UI2
        return unpack_int(v_body[:2])
    elif v_type == 0x000B: # VT_BOOL
        return unpack_int(v_body[:2]) != 0
    elif v_type == 0x0048: # VT_CLSID
        return unpack_int(v_body[:16], 'guid')
    return None

def parse_property_store(data):
    props = {}
    if len(data) < 8: return props
    
    # FORMATID GUIDs
    SHELL_PROPS = "{B725F130-47EF-101A-A5F1-02608C9EEBAC}"
    SUMMARY_PROPS = "{F29F85E0-4FF9-1068-AB91-08002B27B3D9}"
    DOC_PROPS = "{D5CDD502-2E9C-101B-9397-08002B2CF9AE}"
    IMAGE_PROPS = "{14B81DA1-0135-4214-9673-399599A80502}"
    MEDIA_PROPS = "{64440490-4C8B-11D1-8B70-080036B11A03}"
    USER_PROPS = "{446D584D-1814-42C0-BEB1-33B9B93B7A76}"
    
    offset = 4 # Skip total size
    while offset < len(data):
        if len(data) - offset < 24: break
        storage_size = unpack_int(data[offset:offset+4])
        if storage_size < 24: break
        
        format_id = unpack_int(data[offset+8:offset+24], 'guid')
        storage_body = data[offset+24:offset+storage_size]
        
        s_offset = 0
        while s_offset < len(storage_body):
            if len(storage_body) - s_offset < 8: break
            prop_size = unpack_int(storage_body[s_offset:s_offset+4])
            if prop_size < 8: break
            
            prop_id = unpack_int(storage_body[s_offset+4:s_offset+8])
            prop_data = storage_body[s_offset+8:s_offset+prop_size]
            
            val = parse_typed_value(prop_data)
            if val:
                key = f"{format_id}/{prop_id}"
                # Human-readable mapping
                if format_id == SHELL_PROPS:
                    mapping = {2: "Author", 3: "Title", 4: "Subject", 10: "Item_Path", 12: "Created_Time", 14: "Modified_Time", 15: "Size"}
                    if prop_id in mapping: key = mapping[prop_id]
                elif format_id == SUMMARY_PROPS:
                    mapping = {2: "Label", 3: "Subject", 4: "Comments", 5: "Keywords", 9: "Last_Author"}
                    if prop_id in mapping: key = mapping[prop_id]
                elif format_id == DOC_PROPS:
                    mapping = {2: "Category", 3: "Company", 4: "Manager", 13: "Content_Status"}
                    if prop_id in mapping: key = mapping[prop_id]
                elif format_id == IMAGE_PROPS:
                    mapping = {2: "Camera_Model", 4: "ISO", 7: "Flash", 3: "Date_Taken"}
                    if prop_id in mapping: key = mapping[prop_id]
                elif format_id == MEDIA_PROPS:
                    mapping = {2: "Artist", 3: "Album", 13: "Duration", 20: "Genre"}
                    if prop_id in mapping: 
                        key = mapping[prop_id]
                        # Format Duration as human-readable
                        if prop_id == 13:  # Duration
                            val = format_duration(val)
                
                props[key] = str(val)
                
            s_offset += prop_size
            
        offset += storage_size
    return props

def parse_custom_destinations_global_header(data):
    """
    Parse CustomDestinations Global Header (12 bytes at offset 0x00).
    
    Requirement 13A: Extract Version, Categories Count, and Reserved fields.
    
    Args:
        data: Raw CustomDestinations file bytes (at least 12 bytes)
        
    Returns:
        dict with keys:
            - CustDest_Global_Version: int (1=Win7, 2=Win8/10/11)
            - CustDest_Global_Version_Name: str (mapped Windows version)
            - CustDest_Global_Categories_Count: int (number of category groupings)
            - CustDest_Global_Reserved: int (should be 0x00000000)
            - CustDest_Global_Reserved_Valid: bool (True if Reserved == 0)
    """
    result = {}
    
    # Requirement 13A.1: Validate data length >= 12 bytes
    if len(data) < 12:
        return result
    
    try:
        # Requirement 13A.1: Extract Version from bytes [0:4]
        version = unpack_int(data[0:4])
        result['CustDest_Global_Version'] = version
        
        # Requirement 13A.5: Map Version to Windows versions
        version_map = {1: "Windows 7", 2: "Windows 8/10/11"}
        result['CustDest_Global_Version_Name'] = version_map.get(version, f"Unknown (Version {version})")
        
        # Requirement 13A.2: Extract Categories Count from bytes [4:8]
        categories_count = unpack_int(data[4:8])
        result['CustDest_Global_Categories_Count'] = categories_count
        
        # Requirement 13A.3: Extract Reserved from bytes [8:12]
        reserved = unpack_int(data[8:12])
        result['CustDest_Global_Reserved'] = reserved
        
        # Requirement 13A.4: Validate Reserved field equals 0x00000000
        result['CustDest_Global_Reserved_Valid'] = (reserved == 0)
        
        # Requirement 13A.7: Flag non-zero Reserved as potentially non-standard
        if reserved != 0:
            import logging
            logger = logging.getLogger('A_CJL_LNK_Claw')
            logger.warning(f"CustomDestinations Global Header has non-zero Reserved field: 0x{reserved:08X}")
            
    except Exception as e:
        import logging
        logger = logging.getLogger('A_CJL_LNK_Claw')
        logger.error(f"Failed to parse CustomDestinations Global Header: {str(e)}")
    
    return result

def parse_custom_destinations_category_header(data, offset=0x0C):
    """
    Parse CustomDestinations Category Header (variable length starting at offset 0x0C).
    
    Requirement 13B: Extract Category Type, Name Length, Category Name, and Entry Count.
    
    Args:
        data: Raw CustomDestinations file bytes
        offset: Starting offset of category header (default 0x0C)
        
    Returns:
        dict with keys:
            - CustDest_Category_Type: int (0x00-0x03)
            - CustDest_Category_Type_Name: str (Pinned/Recent/Frequent/Tasks)
            - CustDest_Category_Name_Length: int (UTF-16 character count)
            - CustDest_Category_Name: str (UTF-16LE decoded name)
            - CustDest_Entry_Count: int (number of LNK entries in category)
            - CustDest_Entry_Count_Offset: int (byte offset of Entry Count field)
            - Next_Category_Offset: int (offset of next category header, if any)
    """
    result = {}
    
    try:
        # Requirement 13B.1: Extract Category Type from bytes [offset:offset+4]
        if offset + 4 > len(data):
            return result
        category_type = unpack_int(data[offset:offset+4])
        result['CustDest_Category_Type'] = category_type
        
        # Requirement 13B.2: Map Category Type values
        type_map = {0x00: "Pinned", 0x01: "Recent", 0x02: "Frequent", 0x03: "Tasks"}
        result['CustDest_Category_Type_Name'] = type_map.get(category_type, f"Unknown (0x{category_type:08X})")
        
        # Requirement 13B.3: Extract Name Length from bytes [offset+4:offset+6]
        if offset + 6 > len(data):
            return result
        name_length = unpack_int(data[offset+4:offset+6])
        result['CustDest_Category_Name_Length'] = name_length
        
        # Requirement 13B.4: Extract Category Name as UTF-16LE
        name_byte_length = name_length * 2
        if offset + 6 + name_byte_length > len(data):
            return result
        
        category_name_bytes = data[offset+6:offset+6+name_byte_length]
        try:
            category_name = category_name_bytes.decode('utf-16-le', errors='ignore')
            result['CustDest_Category_Name'] = category_name
        except Exception:
            result['CustDest_Category_Name'] = ""
        
        # Requirement 13B.5: Calculate Entry Count offset
        entry_count_offset = offset + 6 + name_byte_length
        result['CustDest_Entry_Count_Offset'] = entry_count_offset
        
        # Requirement 13B.5: Extract Entry Count
        if entry_count_offset + 4 <= len(data):
            entry_count = unpack_int(data[entry_count_offset:entry_count_offset+4])
            result['CustDest_Entry_Count'] = entry_count
            
            # Calculate next category header offset (Requirement 13B.10)
            result['Next_Category_Offset'] = entry_count_offset + 4
        else:
            result['CustDest_Entry_Count'] = 0
            
    except Exception as e:
        import logging
        logger = logging.getLogger('A_CJL_LNK_Claw')
        logger.error(f"Failed to parse CustomDestinations Category Header: {str(e)}")
    
    return result

def parse_all_custom_destinations_category_headers(data, categories_count):
    """
    Parse all CustomDestinations Category Headers.
    
    Requirement 13B.10: Handle multiple Category Headers if Categories Count > 1.
    
    Args:
        data: Raw CustomDestinations file bytes
        categories_count: Number of category headers to parse (from Global Header)
        
    Returns:
        list of dicts, one for each category header
    """
    category_headers = []
    offset = 0x0C  # First category header starts at offset 0x0C
    
    for i in range(categories_count):
        if offset >= len(data):
            break
        
        category_header = parse_custom_destinations_category_header(data, offset)
        if not category_header:
            break
        
        category_headers.append(category_header)
        
        # Move to next category header
        next_offset = category_header.get('Next_Category_Offset')
        if next_offset and next_offset > offset:
            offset = next_offset
        else:
            break
    
    return category_headers

class LnkStreamParser:
    def __init__(self, stream, known_guids=None):
        self.stream = stream
        self.offset = 0
        self.known_guids = known_guids if known_guids else {}
        self.parsed_data = {
            'MFT_Entry_Number': '',
            'MFT_Sequence_Number': '',
            'Property_Metadata': {},
            'Volume_Type': '',
            'Volume_Serial': '',
            'Volume_Label': 'Not Labeled',
            'Command_Line_Arguments': '',
            'Darwin_ID': '',
            'Environment_Variables': '',
            'Known_Folder_GUID': '',
            'Hot_Key_Flags': '',
            'Hot_Key_Value': '',
            'Link_Flags': '',
            'File_Attributes_Flags': '',
            'Show_Window_Command': ''
        }
        self.parse()

    def read(self, size):
        if size <= 0: return b''
        start = self.offset
        end = min(start + size, len(self.stream))
        data = self.stream[start:end]
        # Pad if requested size exceeds stream but don't advance offset beyond file
        if len(data) < size:
            data += b'\x00' * (size - len(data))
        self.offset = end # Capped advancement
        return data
    
    def decode_hot_key(self, hot_key_bytes):
        """
        Decode hot key from 2-byte value.
        Requirement 25: Extract and decode hot key.
        
        Returns:
            (raw_hex, decoded_string) tuple
        """
        if len(hot_key_bytes) < 2:
            return ("0x0000", "None")
        
        key_code = hot_key_bytes[0]
        modifiers = hot_key_bytes[1]
        
        # Format raw hex
        raw_hex = f"0x{modifiers:02X}{key_code:02X}"
        
        # Decode if non-zero
        if key_code == 0 and modifiers == 0:
            return (raw_hex, "None")
        
        # Decode modifiers
        mod_parts = []
        if modifiers & 0x01: mod_parts.append("SHIFT")
        if modifiers & 0x02: mod_parts.append("CTRL")
        if modifiers & 0x04: mod_parts.append("ALT")
        
        # Decode key code (simplified mapping)
        key_map = {
            0x70: "F1", 0x71: "F2", 0x72: "F3", 0x73: "F4", 0x74: "F5", 0x75: "F6",
            0x76: "F7", 0x77: "F8", 0x78: "F9", 0x79: "F10", 0x7A: "F11", 0x7B: "F12"
        }
        
        if key_code in key_map:
            key_str = key_map[key_code]
        elif 0x41 <= key_code <= 0x5A:  # A-Z
            key_str = chr(key_code)
        elif 0x30 <= key_code <= 0x39:  # 0-9
            key_str = chr(key_code)
        else:
            key_str = f"VK_{key_code:02X}"
        
        if mod_parts:
            decoded = "+".join(mod_parts) + "+" + key_str
        else:
            decoded = key_str
        
        return (raw_hex, decoded)
    
    def decode_link_flags(self, flags):
        """
        Decode Link Flags bitmask to human-readable string.
        Requirement 38: Decode Link Flags bitmask.
        
        Returns:
            Comma-separated flag names
        """
        flag_names = []
        if flags & 0x01: flag_names.append("HasLinkTargetIDList")
        if flags & 0x02: flag_names.append("HasLinkInfo")
        if flags & 0x04: flag_names.append("HasName")
        if flags & 0x08: flag_names.append("HasRelativePath")
        if flags & 0x10: flag_names.append("HasWorkingDir")
        if flags & 0x20: flag_names.append("HasArguments")
        if flags & 0x40: flag_names.append("HasIconLocation")
        if flags & 0x80: flag_names.append("IsUnicode")
        if flags & 0x100: flag_names.append("ForceNoLinkInfo")
        if flags & 0x200: flag_names.append("HasExpString")
        if flags & 0x400: flag_names.append("RunInSeparateProcess")
        if flags & 0x800: flag_names.append("HasLogo3ID")
        if flags & 0x1000: flag_names.append("HasDarwinID")
        if flags & 0x2000: flag_names.append("RunAsUser")
        if flags & 0x4000: flag_names.append("HasExpIcon")
        if flags & 0x8000: flag_names.append("NoPidlAlias")
        if flags & 0x10000: flag_names.append("RunWithShimLayer")
        if flags & 0x20000: flag_names.append("ForceNoLinkTrack")
        if flags & 0x40000: flag_names.append("EnableTargetMetadata")
        if flags & 0x80000: flag_names.append("DisableLinkPathTracking")
        if flags & 0x100000: flag_names.append("DisableKnownFolderTracking")
        if flags & 0x200000: flag_names.append("DisableKnownFolderAlias")
        if flags & 0x400000: flag_names.append("AllowLinkToLink")
        if flags & 0x800000: flag_names.append("UnaliasOnSave")
        if flags & 0x1000000: flag_names.append("PreferEnvironmentPath")
        if flags & 0x2000000: flag_names.append("KeepLocalIDListForUNCTarget")
        
        return ",".join(flag_names) if flag_names else "None"
    
    def decode_file_attributes(self, attrs):
        """
        Decode File Attributes flags to human-readable string.
        Requirement 14: Extract file attributes.
        
        Returns:
            Comma-separated attribute names
        """
        attr_names = []
        if attrs & 0x01: attr_names.append("READONLY")
        if attrs & 0x02: attr_names.append("HIDDEN")
        if attrs & 0x04: attr_names.append("SYSTEM")
        if attrs & 0x10: attr_names.append("DIRECTORY")
        if attrs & 0x20: attr_names.append("ARCHIVE")
        if attrs & 0x40: attr_names.append("DEVICE")
        if attrs & 0x80: attr_names.append("NORMAL")
        if attrs & 0x100: attr_names.append("TEMPORARY")
        if attrs & 0x200: attr_names.append("SPARSE_FILE")
        if attrs & 0x400: attr_names.append("REPARSE_POINT")
        if attrs & 0x800: attr_names.append("COMPRESSED")
        if attrs & 0x1000: attr_names.append("OFFLINE")
        if attrs & 0x2000: attr_names.append("NOT_CONTENT_INDEXED")
        if attrs & 0x4000: attr_names.append("ENCRYPTED")
        
        return ",".join(attr_names) if attr_names else "None"
    
    def decode_show_window(self, show_cmd):
        """
        Decode Show Window Command to human-readable string.
        Requirement 15: Extract show window command.
        
        Returns:
            Window state name
        """
        show_map = {
            0: "Hidden",
            1: "Normal",
            2: "Minimized",
            3: "Maximized",
            4: "ShowNoActivate",
            5: "Show",
            6: "Minimize",
            7: "ShowMinNoActive",
            8: "ShowNA",
            9: "Restore",
            10: "ShowDefault",
            11: "ForceMinimize"
        }
        return show_map.get(show_cmd, f"Unknown ({show_cmd})")
    
    def parse_console_data_block(self, block_bytes):
        """
        Parse Console Data Block (0xA0000002) to extract terminal configuration.
        
        Requirement 32: Extract font size, font family, screen buffer size, and window size
        from Console Data Block. Flag suspicious window sizes (1×1 or very small) as
        potentially indicating hidden console execution.
        
        Args:
            block_bytes: Raw bytes of the Console Data Block (including size and signature)
            
        Returns:
            dict with keys:
                - Console_Font_Size: int (font size in pixels)
                - Console_Font_Family: int (font family identifier)
                - Console_Screen_Buffer: str (width×height format)
                - Console_Window_Size: str (width×height format)
                - Console_Window_Suspicious: bool (True if window size is 1×1 or very small)
        """
        result = {}
        
        try:
            # Validate minimum block size
            if len(block_bytes) < 32:
                return result
            
            # Requirement 32.1: Extract font size from block bytes [12:16]
            font_size = unpack_int(block_bytes[12:16])
            result['Console_Font_Size'] = font_size
            
            # Requirement 32.2: Extract font family from block bytes [16:20]
            font_family = unpack_int(block_bytes[16:20])
            result['Console_Font_Family'] = font_family
            
            # Requirement 32.3: Extract screen buffer size from block bytes [24:28] as width×height
            buffer_width = unpack_int(block_bytes[24:26])
            buffer_height = unpack_int(block_bytes[26:28])
            result['Console_Screen_Buffer'] = f"{buffer_width}x{buffer_height}"
            
            # Requirement 32.4: Extract window size from block bytes [28:32] as width×height
            window_width = unpack_int(block_bytes[28:30])
            window_height = unpack_int(block_bytes[30:32])
            result['Console_Window_Size'] = f"{window_width}x{window_height}"
            
            # Requirement 32.6: Flag window size 1×1 or very small as potentially suspicious
            # Consider window sizes <= 5×5 as suspicious (hidden execution indicator)
            if (window_width <= 5 and window_height <= 5) or (window_width == 1 and window_height == 1):
                result['Console_Window_Suspicious'] = True
                
        except Exception as e:
            # Requirement 32.7: Handle parsing errors gracefully
            import logging
            logger = logging.getLogger('A_CJL_LNK_Claw')
            logger.warning(f"Failed to parse Console Data Block: {str(e)}")
        
        return result
    
    def parse_console_fe_data_block(self, block_bytes):
        """
        Parse Console FE Data Block (0xA0000004) to extract code page information.
        
        Requirement 33: Extract code page from Console FE Data Block to identify
        regional settings and potential geolocation indicators.
        
        Args:
            block_bytes: Raw bytes of the Console FE Data Block (including size and signature)
            
        Returns:
            dict with keys:
                - Console_CodePage: int (numeric code page value)
                - Console_CodePage_Name: str (mapped code page name, if known)
        """
        result = {}
        
        try:
            # Validate minimum block size (12 bytes: 4 size + 4 signature + 4 code page)
            if len(block_bytes) < 12:
                return result
            
            # Requirement 33.1: Extract code page from block bytes [8:12] as 32-bit unsigned integer
            code_page = unpack_int(block_bytes[8:12])
            result['Console_CodePage'] = code_page
            
            # Requirement 33.2: Map common code page values to their names
            cp_map = {
                932: "Japanese",
                936: "Chinese",
                65001: "UTF-8",
                1252: "Western European"
            }
            
            # Requirement 33.3: Store mapped name in result if code page is known
            if code_page in cp_map:
                result['Console_CodePage_Name'] = cp_map[code_page]
                
        except Exception as e:
            # Handle parsing errors gracefully
            import logging
            logger = logging.getLogger('A_CJL_LNK_Claw')
            logger.warning(f"Failed to parse Console FE Data Block: {str(e)}")
        
        return result
    
    def parse_special_folder_block(self, block_bytes):
        """
        Parse Special Folder Data Block (0xA0000005) to extract CSIDL information.
        
        Requirement 34: Extract CSIDL from Special Folder Data Block to identify
        legacy special folder references and detect persistence indicators.
        
        Args:
            block_bytes: Raw bytes of the Special Folder Data Block (including size and signature)
            
        Returns:
            dict with keys:
                - Special_Folder_ID: int (numeric CSIDL value)
                - Special_Folder_Name: str (mapped folder name, if known)
                - Persistence_Indicator: bool (True if CSIDL is 0x0007 Startup folder)
        """
        result = {}
        
        try:
            # Validate minimum block size (16 bytes: 4 size + 4 signature + 4 CSIDL + 4 offset)
            if len(block_bytes) < 12:
                return result
            
            # Requirement 34.1: Extract CSIDL from block bytes [8:12] as 32-bit unsigned integer
            csidl = unpack_int(block_bytes[8:12])
            result['Special_Folder_ID'] = csidl
            
            # Requirement 34.2: Map CSIDL values to folder names
            csidl_map = {
                0x0000: "Desktop",
                0x0007: "Startup",
                0x001A: "AppData",
                0x0025: "System32",
                0x0026: "ProgramFiles"
            }
            
            # Requirement 34.3: Store mapped folder name if CSIDL is known
            if csidl in csidl_map:
                result['Special_Folder_Name'] = csidl_map[csidl]
            
            # Requirement 34.4: Flag CSIDL 0x0007 (Startup) as persistence indicator
            if csidl == 0x0007:
                result['Persistence_Indicator'] = True
                
        except Exception as e:
            # Handle parsing errors gracefully
            import logging
            logger = logging.getLogger('A_CJL_LNK_Claw')
            logger.warning(f"Failed to parse Special Folder Data Block: {str(e)}")
        
        return result
    
    def parse_vista_idlist_block(self, block_bytes):
        """
        Parse Vista and Above IDList Data Block (0xA000000C).
        
        Requirement 35: Extract modern IDList from Vista and Above IDList Data Blocks
        to parse targets in modern Windows virtual folders.
        
        This method:
        1. Extracts IDList data from block bytes [8:end]
        2. Recursively parses the modern IDList using parse_idlist()
        3. Merges extracted MFT references, timestamps, and path components
        4. Sets Modern_IDList_Present=True flag in Property_Metadata
        
        Args:
            block_bytes: Raw bytes of the Vista IDList Data Block (including size and signature)
            
        Returns:
            dict with key:
                - Modern_IDList_Present: bool (True if block was successfully parsed)
        """
        result = {}
        
        try:
            # Requirement 35.1: Extract IDList data from block bytes [8:end]
            if len(block_bytes) < 8:
                return result
            
            modern_idlist = block_bytes[8:]
            
            # Requirement 35.2: Recursively parse the modern IDList using parse_idlist()
            # Requirement 35.3: parse_idlist() will merge extracted MFT references, 
            # timestamps, and path components with existing parsed_data
            # Requirement 35.5: Extract all available shell items
            self.parse_idlist(modern_idlist)
            
            # Requirement 35.4: Set Modern_IDList_Present=True flag in Property_Metadata
            result['Modern_IDList_Present'] = True
            
        except Exception as e:
            # Handle parsing errors gracefully
            import logging
            logger = logging.getLogger('A_CJL_LNK_Claw')
            logger.warning(f"Failed to parse Vista IDList Data Block: {str(e)}")
        
        return result
    
    def parse_tracker_droids(self, block_data):
        """
        Parse Droid GUIDs from Tracker Data Block (0xA0000003).
        
        Requirement 36: Extract Volume Droid and Object Droid GUIDs from Tracker Data Blocks
        to track file movement history across volumes.
        
        This method extracts 4 GUIDs from the Tracker Data Block:
        - Volume Droid Current: bytes [32:48] (16 bytes)
        - Volume Droid Birth: bytes [48:64] (16 bytes)
        - Object Droid Current: bytes [64:80] (16 bytes)
        - Object Droid Birth: bytes [80:96] (16 bytes)
        
        Args:
            block_data: Raw bytes of the Tracker Data Block (including size and signature)
            
        Returns:
            dict with keys:
                - Volume_Droid_Current: str (UUID format)
                - Volume_Droid_Birth: str (UUID format)
                - Object_Droid_Current: str (UUID format)
                - Object_Droid_Birth: str (UUID format)
                - File_Moved: bool (True if current != birth, indicating file movement)
        """
        result = {}
        
        try:
            # Requirement 36.1: Validate block has sufficient data (need at least 96 bytes)
            if len(block_data) < 96:
                return result
            
            # Requirement 36.1 & 36.2: Extract Volume Droid Current from bytes [32:48]
            vol_droid_current_bytes = block_data[32:48]
            if len(vol_droid_current_bytes) == 16:
                vol_droid_current = "{" + str(uuid.UUID(bytes_le=vol_droid_current_bytes)).upper() + "}"
                result['Volume_Droid_Current'] = vol_droid_current
            
            # Requirement 36.1 & 36.2: Extract Volume Droid Birth from bytes [48:64]
            vol_droid_birth_bytes = block_data[48:64]
            if len(vol_droid_birth_bytes) == 16:
                vol_droid_birth = "{" + str(uuid.UUID(bytes_le=vol_droid_birth_bytes)).upper() + "}"
                result['Volume_Droid_Birth'] = vol_droid_birth
            
            # Requirement 36.1 & 36.2: Extract Object Droid Current from bytes [64:80]
            obj_droid_current_bytes = block_data[64:80]
            if len(obj_droid_current_bytes) == 16:
                obj_droid_current = "{" + str(uuid.UUID(bytes_le=obj_droid_current_bytes)).upper() + "}"
                result['Object_Droid_Current'] = obj_droid_current
            
            # Requirement 36.1 & 36.2: Extract Object Droid Birth from bytes [80:96]
            obj_droid_birth_bytes = block_data[80:96]
            if len(obj_droid_birth_bytes) == 16:
                obj_droid_birth = "{" + str(uuid.UUID(bytes_le=obj_droid_birth_bytes)).upper() + "}"
                result['Object_Droid_Birth'] = obj_droid_birth
            
            # Requirement 36.5: Compare current vs birth GUIDs to detect file movement
            if 'Volume_Droid_Current' in result and 'Volume_Droid_Birth' in result:
                if result['Volume_Droid_Current'] != result['Volume_Droid_Birth']:
                    result['File_Moved'] = True
                elif 'Object_Droid_Current' in result and 'Object_Droid_Birth' in result:
                    if result['Object_Droid_Current'] != result['Object_Droid_Birth']:
                        result['File_Moved'] = True
            
        except Exception as e:
            # Requirement 36.6: Handle parsing errors gracefully
            import logging
            logger = logging.getLogger('A_CJL_LNK_Claw')
            logger.warning(f"Failed to parse Tracker Droids: {str(e)}")
        
        return result

    def parse(self):
        if len(self.stream) < 76: return
        header_size = unpack_int(self.read(4))
        if header_size != 0x4C: return

        # Requirement 24: Extract CLSID from bytes [4:20]
        clsid = self.read(16)
        clsid_str = "{" + str(uuid.UUID(bytes_le=clsid)).upper() + "}"
        self.parsed_data['LNK_Class_ID'] = clsid_str
        
        # Requirement 24: Validate CLSID matches expected Shell Link CLSID
        if not validate_clsid(clsid):
            # Flag non-standard CLSID in Property_Metadata
            if 'Property_Metadata' not in self.parsed_data:
                self.parsed_data['Property_Metadata'] = {}
            if isinstance(self.parsed_data['Property_Metadata'], str):
                try:
                    self.parsed_data['Property_Metadata'] = json.loads(self.parsed_data['Property_Metadata'])
                except:
                    self.parsed_data['Property_Metadata'] = {}
            self.parsed_data['Property_Metadata']['Non_Standard_CLSID'] = True
            self.parsed_data['Property_Metadata']['CLSID_Validation_Failed'] = True
        
        # Requirement 38: Extract Link Flags from bytes [20:24]
        link_flags = unpack_int(self.read(4))
        self.parsed_data['Link_Flags'] = self.decode_link_flags(link_flags)
        
        # Requirement 14: Extract File Attributes from bytes [24:28]
        file_attrs = unpack_int(self.read(4))
        self.parsed_data['File_Attributes_Flags'] = self.decode_file_attributes(file_attrs)
        
        # Extract timestamps
        ctime = unpack_int(self.read(8))
        atime = unpack_int(self.read(8))
        mtime = unpack_int(self.read(8))
        
        # Extract file size and icon index
        file_size = unpack_int(self.read(4))
        icon_index = struct.unpack('<i', self.read(4))[0]
        
        # Requirement 15: Extract Show Window Command from bytes [60:64]
        show_window = unpack_int(self.read(4))
        self.parsed_data['Show_Window_Command'] = self.decode_show_window(show_window)
        
        # Requirement 25: Extract Hot Key from bytes [64:66]
        hot_key_bytes = self.read(2)
        hot_key_hex, hot_key_decoded = self.decode_hot_key(hot_key_bytes)
        self.parsed_data['Hot_Key_Flags'] = hot_key_hex
        self.parsed_data['Hot_Key_Value'] = hot_key_decoded
        
        # Skip Reserved fields (10 bytes: Reserved1(2) + Reserved2(4) + Reserved3(4))
        self.read(10)

        self.parsed_data['Time_Creation'] = ad_timestamp(ctime)
        self.parsed_data['Time_Access'] = ad_timestamp(atime)
        self.parsed_data['Time_Modification'] = ad_timestamp(mtime)
        self.parsed_data['FileSize'] = format_size(file_size)  # Convert to human-readable format
        self.parsed_data['IconIndex'] = icon_index
        
        has_target_id_list = bool(link_flags & 0x01)
        has_link_info = bool(link_flags & 0x02)
        has_name = bool(link_flags & 0x04)
        has_rel_path = bool(link_flags & 0x08)
        has_working_dir = bool(link_flags & 0x10)
        has_arguments = bool(link_flags & 0x20)
        has_icon_loc = bool(link_flags & 0x40)
        is_unicode = bool(link_flags & 0x80)

        # 1. Target ID List
        if has_target_id_list:
            idlist_size = unpack_int(self.read(2))
            idlist_data = self.read(idlist_size)
            self.parse_idlist(idlist_data)
            
        # 2. Link Info
        if has_link_info:
            link_info_start = self.offset
            link_info_size = unpack_int(self.read(4))
            if link_info_size >= 28:
                li_header_size = unpack_int(self.read(4))
                li_flags = unpack_int(self.read(4))
                vol_id_offset = unpack_int(self.read(4))
                local_base_path_offset = unpack_int(self.read(4))
                net_share_offset = unpack_int(self.read(4))
                common_path_suffix_offset = unpack_int(self.read(4))
                
                # Check for Unicode (optional header fields)
                local_base_path_uni_offset = 0
                common_path_suffix_uni_offset = 0
                if li_header_size >= 36:
                    local_base_path_uni_offset = unpack_int(self.read(4))
                    common_path_suffix_uni_offset = unpack_int(self.read(4))

                if vol_id_offset > 0:
                    v_start = link_info_start + vol_id_offset
                    v_size = unpack_int(self.stream[v_start:v_start+4])
                    if v_size >= 16:
                        drive_type = unpack_int(self.stream[v_start+4:v_start+8])
                        drive_serial = unpack_int(self.stream[v_start+8:v_start+12])
                        vol_label_offset = unpack_int(self.stream[v_start+12:v_start+16])
                        
                        # Map Drive Type
                        type_map = {0: "Unknown", 1: "No Root Directory", 2: "Removable", 3: "Fixed", 4: "Remote", 5: "CD-ROM", 6: "RAM Disk"}
                        self.parsed_data['Volume_Type'] = type_map.get(drive_type, f"Unknown ({drive_type})")
                        self.parsed_data['Volume_Serial'] = "%08X" % drive_serial
                        
                        # Extract Volume Label
                        # vol_label_offset is relative to the start of VolumeID structure
                        if vol_label_offset > 0 and vol_label_offset < v_size:
                            l_start = v_start + vol_label_offset
                            # Read until null terminator or end of VolumeID structure
                            label_end = v_start + v_size
                            raw_label = self.stream[l_start:label_end]
                            # Split at null terminator
                            if b'\0' in raw_label:
                                raw_label = raw_label.split(b'\0')[0]
                            label_str = raw_label.decode('cp1252', errors='ignore').strip()
                            # If label is empty, mark as "Not Labeled"
                            self.parsed_data['Volume_Label'] = label_str if label_str else 'Not Labeled'
                        else:
                            self.parsed_data['Volume_Label'] = 'Not Labeled'

                # Extract Local Path
                if (li_flags & 0x01):
                    # Prefer Unicode if available
                    if local_base_path_uni_offset > 0:
                        p = link_info_start + local_base_path_uni_offset
                        raw_path = self.stream[p:link_info_start+link_info_size].split(b'\0\0')[0]
                        self.parsed_data['Local_Path'] = raw_path.decode('utf-16-le', errors='ignore')
                    elif local_base_path_offset > 0:
                        p = link_info_start + local_base_path_offset
                        raw_path = self.stream[p:link_info_start+link_info_size].split(b'\0')[0]
                        self.parsed_data['Local_Path'] = raw_path.decode('ascii', errors='ignore')
                
                # Requirement 39: Extract Common Path Suffix
                if common_path_suffix_offset > 0:
                    # Prefer Unicode if available
                    if common_path_suffix_uni_offset > 0:
                        p = link_info_start + common_path_suffix_uni_offset
                        raw_suffix = self.stream[p:link_info_start+link_info_size].split(b'\0\0')[0]
                        common_suffix = raw_suffix.decode('utf-16-le', errors='ignore')
                    else:
                        p = link_info_start + common_path_suffix_offset
                        raw_suffix = self.stream[p:link_info_start+link_info_size].split(b'\0')[0]
                        common_suffix = raw_suffix.decode('ascii', errors='ignore')
                    
                    if common_suffix:
                        self.parsed_data['Common_Path'] = common_suffix
                
                if (li_flags & 0x02) and net_share_offset > 0:
                    n_offset = link_info_start + net_share_offset
                    if n_offset + 8 <= len(self.stream):
                        n_size = unpack_int(self.stream[n_offset:n_offset+4])
                        share_name_offset = unpack_int(self.stream[n_offset+8:n_offset+12])
                        if share_name_offset > 0:
                            sn_start = n_offset + share_name_offset
                            raw_share = self.stream[sn_start:n_offset+n_size].split(b'\0')[0]
                            self.parsed_data['Network_Share_Name'] = raw_share.decode('ascii', errors='ignore')
            
            # Definitive jump to end of LinkInfo
            self.offset = link_info_start + link_info_size 
            
        # 3. String Data
        def read_string():
            char_count = unpack_int(self.read(2))
            if is_unicode:
                data = self.read(char_count * 2)
                return data.decode('utf-16le', errors='ignore').strip('\0')
            else:
                data = self.read(char_count)
                return data.decode('cp1252', errors='ignore').strip('\0')

        # Requirement 27: Extract Description
        if has_name: self.parsed_data['Description'] = read_string()
        if has_rel_path: self.parsed_data['Relative_Path'] = read_string()
        if has_working_dir: self.parsed_data['Working_Directory'] = read_string()
        if has_arguments: self.parsed_data['Command_Line_Arguments'] = read_string()
        # Requirement 26: Extract Icon Location
        if has_icon_loc: self.parsed_data['Icon_Location'] = read_string()

        # 4. Extra Data Blocks
        while self.offset < len(self.stream):
            if len(self.stream) - self.offset < 8: break
            block_start = self.offset
            block_size = unpack_int(self.read(4))
            if block_size < 8: break
            block_end = block_start + block_size  # absolute end — advance here no matter what
            signature = unpack_int(self.read(4))
            
            if signature == 0xA0000003:  # Tracker Data Block (96 bytes)
                try:
                    self.read(8) # Skip version/reserved
                    netbios_name = self.read(16).decode('ascii', errors='ignore').strip('\0')
                    self.parsed_data['Tracker_NetBIOS'] = netbios_name
                    
                    # Requirement 36: Extract Droid GUIDs using parse_tracker_droids()
                    droid_data = self.parse_tracker_droids(self.stream[block_start:block_end])
                    self.parsed_data['Property_Metadata'].update(droid_data)
                    
                    # Extract MAC from last 6 bytes (if available)
                    self.offset = block_end - 6
                    mac_bytes = self.stream[self.offset:block_end]
                    if len(mac_bytes) == 6:
                        self.parsed_data['Tracker_MAC'] = "%02x:%02x:%02x:%02x:%02x:%02x" % struct.unpack("BBBBBB", mac_bytes)
                except Exception: pass
                
            elif signature == 0xA0000009: # Property Store
                try:
                    ps_data = self.stream[block_start+8:block_end]
                    self.parsed_data['Property_Metadata'].update(parse_property_store(ps_data))
                except Exception: pass
                
            elif signature == 0xA0000001: # Environment Variable Data Block
                try:
                    # ANSI at +8 (260 bytes), Unicode at +268 (520 bytes)
                    env_val = self.stream[block_start+268:block_end].decode('utf-16-le', errors='ignore').split('\0')[0]
                    if not env_val:
                        env_val = self.stream[block_start+8:block_start+268].decode('ascii', errors='ignore').split('\0')[0]
                    self.parsed_data['Environment_Variables'] = env_val
                except Exception: pass
                
            elif signature == 0xA0000006: # Darwin Data Block
                try:
                    # Similar structure to Environment block
                    darwin_val = self.stream[block_start+268:block_end].decode('utf-16-le', errors='ignore').split('\0')[0]
                    if not darwin_val:
                        darwin_val = self.stream[block_start+8:block_start+268].decode('ascii', errors='ignore').split('\0')[0]
                    self.parsed_data['Darwin_ID'] = darwin_val
                except Exception: pass
                
            elif signature == 0xA000000B: # Known Folder Data Block
                try:
                    kf_guid = unpack_int(self.stream[block_start+8:block_start+24], 'guid')
                    self.parsed_data['Known_Folder_GUID'] = kf_guid
                    # Map name using external CSV data
                    if kf_guid.upper() in self.known_guids:
                        self.parsed_data['Property_Metadata']['Known_Folder_Name'] = self.known_guids[kf_guid.upper()]
                except Exception: pass
                
            elif signature == 0xA0000002: # Console Data Block
                # Requirement 32: Parse Console Data Block
                try:
                    c_props = self.parse_console_data_block(self.stream[block_start:block_end])
                    self.parsed_data['Property_Metadata'].update(c_props)
                except Exception: pass
                
            elif signature == 0xA0000004: # Console FE Data Block
                # Requirement 33: Parse Console FE Data Block
                try:
                    cp_props = self.parse_console_fe_data_block(self.stream[block_start:block_end])
                    self.parsed_data['Property_Metadata'].update(cp_props)
                except Exception: pass
                
            elif signature == 0xA0000005: # Special Folder Data Block
                # Requirement 34: Parse Special Folder Data Block
                try:
                    sf_props = self.parse_special_folder_block(self.stream[block_start:block_end])
                    self.parsed_data['Property_Metadata'].update(sf_props)
                except Exception: pass
                
            elif signature == 0xA0000008: # Shim Data Block
                try:
                    shim_val = self.stream[block_start+8:block_end].decode('utf-16-le', errors='ignore').split('\0')[0]
                    self.parsed_data['Property_Metadata']['Shim_Layer'] = shim_val
                except Exception: pass
                
            elif signature == 0xA000000C: # Vista And Above IDList Data Block
                # Requirement 35: Parse Vista IDList Data Block
                try:
                    vista_props = self.parse_vista_idlist_block(self.stream[block_start:block_end])
                    self.parsed_data['Property_Metadata'].update(vista_props)
                except Exception: pass
                
            # Always jump to the definitive end of this block
            self.offset = block_end

    def parse_idlist(self, data):
        """
        Enhanced shell item parser with version detection and comprehensive field extraction.
        
        Implements Requirements 1.1-1.9:
        - Shell item type detection (0x00, 0x1F, 0x20-0x2F, 0x31-0x3F, 0x41-0x4F, 0x61-0x6F, 0x71-0x7F)
        - File entry parsing (types 0x31-0x3F)
        - Folder entry parsing (types 0x41-0x4F)
        - Extension block parsing (0xBEEF signature)
        - Path reconstruction from shell item sequences
        - Error handling for malformed items
        """
        i_offset = 0
        idlist_details = []
        
        while i_offset < len(data):
            # Requirement 1.8: Validate item size >= 2 bytes before parsing
            if i_offset + 2 > len(data):
                break
            
            item_size = unpack_int(data[i_offset:i_offset+2])
            if item_size == 0:
                break
            
            # Requirement 1.8: Check sufficient data before reading each field
            if i_offset + item_size > len(data):
                # Log warning for malformed item
                import logging
                logger = logging.getLogger('A_CJL_LNK_Claw')
                logger.warning(f"Malformed shell item: size {item_size} exceeds available data")
                break
            
            item_data = data[i_offset:i_offset+item_size]
            
            # Requirement 1.1: Read item type byte at offset [2]
            item_type = item_data[2] if len(item_data) > 2 else 0
            
            # Parse shell item based on type dispatch logic (Requirement 1.2)
            try:
                if item_type == 0x00 or item_type == 0x1F:
                    # Root folder items
                    self._parse_root_folder_item(item_data, item_type, idlist_details)
                elif 0x20 <= item_type <= 0x2F:
                    # Volume/Drive items
                    self._parse_volume_item(item_data, idlist_details)
                elif 0x31 <= item_type <= 0x3F:
                    # File entry items (Requirement 1.3)
                    self._parse_file_entry_item(item_data, idlist_details)
                elif 0x41 <= item_type <= 0x4F:
                    # Folder entry items (Requirement 1.4)
                    self._parse_folder_entry_item(item_data, idlist_details)
                elif 0x61 <= item_type <= 0x6F:
                    # Network location items
                    self._parse_network_location_item(item_data, idlist_details)
                elif 0x71 <= item_type <= 0x7F:
                    # Compressed folder items
                    self._parse_compressed_folder_item(item_data, idlist_details)
                else:
                    # Unknown type - attempt generic name extraction
                    self._parse_generic_item(item_data, idlist_details)
            except Exception as e:
                # Requirement 1.8: Skip corrupted items and continue with next
                import logging
                logger = logging.getLogger('A_CJL_LNK_Claw')
                logger.warning(f"Failed to parse shell item type 0x{item_type:02X}: {str(e)}")
            
            # Parse extension block if present (applies to all item types)
            self._parse_extension_block(item_data)
            
            i_offset += item_size
        
        # Requirement 1.9: Store reconstructed path
        if idlist_details:
            self.parsed_data['Property_Metadata']['IDList_Path'] = "\\".join(idlist_details)
    
    def _parse_root_folder_item(self, item_data, item_type, idlist_details):
        """Parse root folder shell items (0x00, 0x1F)."""
        try:
            if item_type == 0x1F and len(item_data) >= 18:
                # Root folder with GUID (Control Panel, Recycle Bin, etc.)
                guid_data = item_data[3:19]
                guid = unpack_int(guid_data, 'guid')
                if guid:
                    idlist_details.append(f"[{guid}]")
            elif item_type == 0x00:
                # My Computer, Network, etc.
                idlist_details.append("[Root]")
        except Exception:
            pass
    
    def _parse_volume_item(self, item_data, idlist_details):
        """Parse volume/drive shell items (0x20-0x2F)."""
        try:
            # Volume name typically starts at offset 3
            raw_name = item_data[3:].split(b'\0')[0]
            if raw_name:
                name_str = raw_name.decode('ascii', errors='ignore')
                if name_str:
                    idlist_details.append(name_str)
        except Exception:
            pass
    
    def _parse_file_entry_item(self, item_data, idlist_details):
        """
        Parse file entry shell items (0x31-0x3F).
        
        Requirement 1.3: Extract file size, attributes, short name, primary name, extension block.
        """
        try:
            # Requirement 1.3: Extract file size from offset [4:8]
            if len(item_data) >= 8:
                file_size = unpack_int(item_data[4:8])
                if file_size > 0:
                    self.parsed_data['Property_Metadata']['ShellItem_FileSize'] = format_size(file_size)  # Convert to human-readable format
            
            # Requirement 1.3: Extract file attributes from offset [8:12]
            if len(item_data) >= 12:
                file_attrs = unpack_int(item_data[8:12])
                self.parsed_data['Property_Metadata']['ShellItem_FileAttributes'] = f"0x{file_attrs:08X}"
            
            # Requirement 1.3: Extract short name from offset [14:]
            if len(item_data) >= 14:
                short_name = item_data[14:].split(b'\0')[0]
                if short_name:
                    short_name_str = short_name.decode('ascii', errors='ignore')
                    if short_name_str:
                        idlist_details.append(short_name_str)
                        
                        # Requirement 1.3: Extract primary name after short name
                        # Primary name follows short name + null terminator
                        primary_name_offset = 14 + len(short_name) + 1
                        if primary_name_offset < len(item_data):
                            primary_name = item_data[primary_name_offset:].split(b'\0')[0]
                            if primary_name and primary_name != short_name:
                                primary_name_str = primary_name.decode('ascii', errors='ignore')
                                if primary_name_str:
                                    self.parsed_data['Property_Metadata']['ShellItem_PrimaryName'] = primary_name_str
        except Exception:
            pass
    
    def _parse_folder_entry_item(self, item_data, idlist_details):
        """
        Parse folder entry shell items (0x41-0x4F).
        
        Requirement 1.4: Extract folder attributes, folder name, extension block.
        """
        try:
            # Requirement 1.4: Extract folder attributes from offset [8:12]
            if len(item_data) >= 12:
                folder_attrs = unpack_int(item_data[8:12])
                self.parsed_data['Property_Metadata']['ShellItem_FolderAttributes'] = f"0x{folder_attrs:08X}"
            
            # Requirement 1.4: Extract folder name from offset [14:]
            if len(item_data) >= 14:
                folder_name = item_data[14:].split(b'\0')[0]
                if folder_name:
                    folder_name_str = folder_name.decode('ascii', errors='ignore')
                    if folder_name_str:
                        idlist_details.append(folder_name_str)
        except Exception:
            pass
    
    def _parse_network_location_item(self, item_data, idlist_details):
        """Parse network location shell items (0x61-0x6F)."""
        try:
            # Network location name typically at offset 14
            if len(item_data) >= 14:
                net_name = item_data[14:].split(b'\0')[0]
                if net_name:
                    net_name_str = net_name.decode('ascii', errors='ignore')
                    if net_name_str:
                        idlist_details.append(net_name_str)
        except Exception:
            pass
    
    def _parse_compressed_folder_item(self, item_data, idlist_details):
        """Parse compressed folder shell items (0x71-0x7F)."""
        try:
            # Compressed folder name typically at offset 14
            if len(item_data) >= 14:
                zip_name = item_data[14:].split(b'\0')[0]
                if zip_name:
                    zip_name_str = zip_name.decode('ascii', errors='ignore')
                    if zip_name_str:
                        idlist_details.append(zip_name_str)
        except Exception:
            pass
    
    def _parse_generic_item(self, item_data, idlist_details):
        """Parse unknown shell item types with generic name extraction."""
        try:
            # Attempt name extraction from offset 14 (common location)
            if len(item_data) >= 14:
                generic_name = item_data[14:].split(b'\0')[0]
                if generic_name:
                    generic_name_str = generic_name.decode('ascii', errors='ignore')
                    if generic_name_str:
                        idlist_details.append(generic_name_str)
        except Exception:
            pass
    
    def _parse_extension_block(self, item_data):
        """
        Parse extension block (0xBEEF signature).
        
        Requirement 1.5: Parse extension block structure
        Requirement 1.6: Handle version-specific formats
        Requirement 1.7: Extract localized names
        
        Extension block structure:
        - Offset [0:2]: Size (16-bit)
        - Offset [2:4]: Version (16-bit) - 0x0003, 0x0004, 0x0007, 0x0008, 0x0009
        - Offset [4:6]: Signature (16-bit) - must be 0xBEEF
        - Offset [6:8]: Unknown/Reserved
        - Offset [8:16]: MFT Reference (64-bit: 48-bit entry + 16-bit sequence)
        - Offset [16:24]: Creation Time (FILETIME, version >= 0x0004)
        - Offset [24:32]: Access Time (FILETIME, version >= 0x0004)
        - Offset [32:40]: Write Time (FILETIME, version >= 0x0004)
        - Offset [40:]: Long Name (Unicode, version >= 0x0007)
        """
        # Search for 0xBEEF signature (little-endian: 0xEF 0xBE)
        # The signature is at offset [4:6] in the extension block
        # So we need to find it and then back up 4 bytes to get the start
        beef_sig = b'\xEF\xBE'
        search_offset = 0
        
        while search_offset < len(item_data):
            beef_idx = item_data.find(beef_sig, search_offset)
            if beef_idx == -1:
                return
            
            # Extension block starts 4 bytes before the signature
            ext_start = beef_idx - 4
            if ext_start < 0:
                search_offset = beef_idx + 1
                continue
            
            try:
                # Requirement 1.5: Parse extension block size (offset [0:2])
                if ext_start + 2 > len(item_data):
                    return
                ext_size = unpack_int(item_data[ext_start:ext_start+2])
                
                # Validate size is reasonable
                # Note: Size can be as small as 8 bytes for basic extension blocks
                # The size field includes the size and version fields themselves
                if ext_size < 8 or ext_size > 1024:
                    search_offset = beef_idx + 1
                    continue
                
                # Requirement 1.5: Parse extension block version (offset [2:4])
                if ext_start + 4 > len(item_data):
                    return
                ext_version = unpack_int(item_data[ext_start+2:ext_start+4])
                
                # Validate version is one of the known versions
                if ext_version not in [0x0003, 0x0004, 0x0007, 0x0008, 0x0009]:
                    search_offset = beef_idx + 1
                    continue
                
                self.parsed_data['Property_Metadata']['ShellItem_ExtensionVersion'] = f"0x{ext_version:04X}"
                
                # Requirement 1.5: Validate signature (offset [4:6] must be 0xBEEF)
                if ext_start + 6 > len(item_data):
                    return
                signature = unpack_int(item_data[ext_start+4:ext_start+6])
                if signature != 0xBEEF:
                    search_offset = beef_idx + 1
                    continue
                
                # Requirement 1.5: Extract MFT reference (offset [8:16])
                # This is the critical field for MFT Entry Number extraction
                if ext_start + 16 <= len(item_data):
                    mft_ref_data = item_data[ext_start+8:ext_start+16]
                    mft_ref_val = unpack_int(mft_ref_data, 'int')
                    
                    # MFT Reference is 64-bit: 48-bit entry number + 16-bit sequence
                    mft_entry = mft_ref_val & 0xFFFFFFFFFFFF  # Lower 48 bits
                    mft_sequence = mft_ref_val >> 48  # Upper 16 bits
                    
                    # Only set if non-zero (zero means not available)
                    if mft_entry > 0:
                        self.parsed_data['MFT_Entry_Number'] = str(mft_entry)
                        self.parsed_data['MFT_Sequence_Number'] = str(mft_sequence)
                        self.parsed_data['Property_Metadata']['ShellItem_MFT_Entry'] = str(mft_entry)
                        self.parsed_data['Property_Metadata']['ShellItem_MFT_Sequence'] = str(mft_sequence)
                
                # Requirement 1.5: Extract timestamps (offset [16:40]) for version >= 0x0004
                if ext_version >= 0x0004 and ext_start + 40 <= len(item_data):
                    c_t = ad_timestamp(unpack_int(item_data[ext_start+16:ext_start+24]))
                    a_t = ad_timestamp(unpack_int(item_data[ext_start+24:ext_start+32]))
                    m_t = ad_timestamp(unpack_int(item_data[ext_start+32:ext_start+40]))
                    if c_t:
                        self.parsed_data['Property_Metadata']['ShellItem_Creation'] = c_t
                    if a_t:
                        self.parsed_data['Property_Metadata']['ShellItem_Access'] = a_t
                    if m_t:
                        self.parsed_data['Property_Metadata']['ShellItem_Modification'] = m_t
                
                # Requirement 1.6 & 1.7: Extract long name for version >= 0x0007
                if ext_version >= 0x0007 and ext_start + 40 < len(item_data):
                    # Long name starts at offset [40:] as null-terminated Unicode
                    long_name_data = item_data[ext_start+40:]
                    # Find null terminator (2 bytes for Unicode)
                    null_idx = long_name_data.find(b'\x00\x00')
                    if null_idx != -1 and null_idx > 0:
                        try:
                            long_name = long_name_data[:null_idx].decode('utf-16-le', errors='ignore')
                            if long_name:
                                self.parsed_data['Property_Metadata']['ShellItem_LongName'] = long_name
                        except Exception:
                            pass
                
                # Successfully parsed extension block, return
                return
                
            except Exception as e:
                # Requirement 1.8: Log warnings for malformed extension blocks
                import logging
                logger = logging.getLogger('A_CJL_LNK_Claw')
                logger.debug(f"Failed to parse extension block at offset {ext_start}: {str(e)}")
                search_offset = beef_idx + 1
                continue

def extract_artifacts_from_file(filepath, appids=None, known_guids=None):
    """
    Extract artifacts from LNK files, AutomaticDestinations, and CustomDestinations.
    
    Enhanced to include:
    - JSON serialization of embedded LNK data (Requirement 3)
    - CustomDestinations Global and Category Header parsing (Requirements 13A, 13B)
    - All DestList metadata extraction (Requirements 4-12, 28-31)
    """
    if appids is None: appids = {}
    if known_guids is None: known_guids = {}
    filename = os.path.basename(filepath)
    results = []
    
    clean_entry = {
        'LNK_Class_ID': '', 'Time_Creation': '', 'Time_Access': '', 'Time_Modification': '',
        'FileSize': '', 'IconIndex': '', 'Local_Path': '', 'Network_Share_Name': '',
        'Description': '', 'Relative_Path': '', 'Working_Directory': '', 'Command_Line_Arguments': '',
        'Icon_Location': '', 'Tracker_MAC': '', 'Tracker_NetBIOS': '',
        'AppID': '', 'AppType': '', 'AppDesc': '', 'Source_Name': filename, 'Source_Path': filepath,
        'entry_number': '', 'Embedded_LNK': '',
        'Hot_Key_Flags': '', 'Hot_Key_Value': '', 'Link_Flags': '', 'File_Attributes_Flags': '',
        'Show_Window_Command': '', 'Common_Path': '',
        # DestList fields
        'DestList_Version_Number': '', 'DestList_OS_Version': '', 'DestList_Total_Current_Entries': '',
        'DestList_Total_Pinned_Entries': '', 'DestList_Last_ID': '', 'DestList_Actions_Count': '',
        'DestList_Checksum': '', 'DestList_New_Volume_ID': '', 'DestList_New_Object_ID': '',
        'Birth_Volume_ID': '', 'Birth_Object_ID': '', 'Birth_Object_ID_MAC': '',
        'DestList_Access_Counter': '', 'DestList_Pin_Status': '',
        # Custom JumpList fields
        'Category': '', 'Footer_Signature_Valid': ''
    }
    
    try:
        # 1. Automatic JumpLists
        if "automaticdestinations-ms" in filename.lower():
            appid_hex = filename.split('.')[0].lower()
            app_info = appids.get(appid_hex, ("Unknown", "Unknown"))
            if olefile.isOleFile(filepath):
                ole = olefile.OleFileIO(filepath)
                destlist_entries = []
                dest_header = {}
                if ole.exists('DestList'):
                    dest_stream = ole.openstream('DestList').read()
                    destlist_entries, dest_header = parse_DestList(dest_stream)
                
                dest_dict = {str(e.get('Entry_ID_Number', '')): e for e in destlist_entries}
                
                for ole_dir in ole.listdir():
                    if ole_dir[0] == 'DestList': continue
                    stream_data = ole.openstream(ole_dir[0]).read()
                    lnk_parser = LnkStreamParser(stream_data, known_guids=known_guids)
                    entry = clean_entry.copy()
                    entry.update(lnk_parser.parsed_data)
                    entry['AppID'] = appid_hex
                    entry['AppType'] = app_info[0]
                    entry['AppDesc'] = app_info[1]
                    
                    # Requirement 3.2: Serialize embedded LNK to JSON
                    try:
                        entry['Embedded_LNK'] = json.dumps(lnk_parser.parsed_data, ensure_ascii=False)
                    except Exception:
                        entry['Embedded_LNK'] = ''
                    
                    # Add DestList header fields
                    entry['DestList_Version_Number'] = dest_header.get('Version_Number', '')
                    entry['DestList_OS_Version'] = dest_header.get('OS_Version', '')
                    entry['DestList_Total_Current_Entries'] = dest_header.get('Total_Current_Entries', '')
                    entry['DestList_Total_Pinned_Entries'] = dest_header.get('Total_Pinned_Entries', '')
                    entry['DestList_Last_ID'] = dest_header.get('Last_Issued_ID_Num', '')
                    entry['DestList_Actions_Count'] = dest_header.get('Number_of_Actions', '')
                    
                    try:
                        entry_id_int = str(int(ole_dir[0], 16))
                        entry['entry_number'] = entry_id_int
                        if entry_id_int in dest_dict:
                            dl_info = dest_dict[entry_id_int]
                            # Merge DestList entry fields
                            if dl_info.get('Last_Recorded_Access'): 
                                entry['Time_Access'] = dl_info['Last_Recorded_Access']
                            if dl_info.get('NetBIOS'): 
                                entry['Tracker_NetBIOS'] = dl_info['NetBIOS']
                            if dl_info.get('New_Object_ID_MAC_Addr'): 
                                entry['Tracker_MAC'] = dl_info['New_Object_ID_MAC_Addr']
                            
                            # Add all DestList entry fields
                            entry['DestList_Checksum'] = dl_info.get('Checksum', '')
                            entry['DestList_New_Volume_ID'] = dl_info.get('New_Volume_ID', '')
                            entry['DestList_New_Object_ID'] = dl_info.get('New_Object_ID', '')
                            entry['Birth_Volume_ID'] = dl_info.get('Birth_Volume_ID', '')
                            entry['Birth_Object_ID'] = dl_info.get('Birth_Object_ID', '')
                            entry['Birth_Object_ID_MAC'] = dl_info.get('Birth_Object_ID_MAC_Addr', '')
                            entry['DestList_Access_Counter'] = dl_info.get('Access_Counter', '')
                            entry['DestList_Pin_Status'] = dl_info.get('Pin_Status_Counter', '')
                    except ValueError:
                        pass
                    results.append(entry)
                    
        # 2. Custom JumpLists
        elif "customdestinations-ms" in filename.lower():
            appid_hex = filename.split('.')[0].lower()
            app_info = appids.get(appid_hex, ("Unknown", "Unknown"))
            try:
                with open(filepath, 'rb') as f:
                    data = f.read()
                
                # Requirement 13A: Parse CustomDestinations Global Header
                global_header = parse_custom_destinations_global_header(data)
                
                # Requirement 13B: Parse CustomDestinations Category Headers
                # Requirement 13B.10: Handle multiple Category Headers if Categories Count > 1
                categories_count = global_header.get('CustDest_Global_Categories_Count', 1)
                category_headers = parse_all_custom_destinations_category_headers(data, categories_count)
                
                # Merge all category headers into a single dict for Property_Metadata
                # If multiple categories exist, store them as a list
                if len(category_headers) == 1:
                    category_header = category_headers[0]
                elif len(category_headers) > 1:
                    category_header = {'CustDest_Category_Headers': category_headers}
                else:
                    category_header = {}
                
                # Custom JumpList signature for embedded LNK:
                # 0x4C, 0x00, 0x00, 0x00, 0x01, 0x14, 0x02, 0x00...
                magic = b'\x4C\x00\x00\x00\x01\x14\x02\x00\x00\x00\x00\x00\xC0\x00\x00\x00\x00\x00\x00\x46'
                
                # Requirement 37: Validate footer signature
                footer_valid = False
                if len(data) >= 4:
                    footer_sig = unpack_int(data[-4:])
                    footer_valid = (footer_sig == 0xBABFFBAB)
                
                # Build category assignment map based on parsed category headers
                # Each category has an entry count, so we assign categories sequentially
                category_assignments = []
                for cat_header in category_headers:
                    cat_name = cat_header.get('CustDest_Category_Type_Name', 'Unknown')
                    cat_count = cat_header.get('CustDest_Entry_Count', 0)
                    # Add this category name for each entry in this category
                    # Prevent memory exhaustion from corrupted headers by capping at 500
                    category_assignments.extend([cat_name] * min(cat_count, 500))
                
                p_offset = 0
                max_entries = 500
                entry_count = 0
                while p_offset < len(data) and entry_count < max_entries:
                    magic_idx = data.find(magic, p_offset)
                    if magic_idx == -1: break
                    
                    # Assign category based on entry index and parsed category headers
                    # If we have category assignments, use them; otherwise default to "Unknown"
                    if entry_count < len(category_assignments):
                        category = category_assignments[entry_count]
                    else:
                        # Fallback: try to read category from 4 bytes before magic
                        category = "Unknown"
                        if magic_idx >= 4:
                            cat_header = unpack_int(data[magic_idx-4:magic_idx])
                            if cat_header == 0: category = "Pinned"
                            elif cat_header == 1: category = "Recent"
                            elif cat_header == 2: category = "Frequent"
                            elif cat_header == 3: category = "Tasks"

                    lnk_parser = LnkStreamParser(data[magic_idx:], known_guids=known_guids)
                    entry = clean_entry.copy()
                    entry.update(lnk_parser.parsed_data)
                    entry['AppID'] = appid_hex
                    entry['AppType'] = app_info[0]
                    entry['AppDesc'] = app_info[1]
                    entry['Category'] = category
                    entry['Footer_Signature_Valid'] = 1 if footer_valid else 0
                    
                    # Requirement 3.3: Serialize embedded LNK to JSON
                    try:
                        entry['Embedded_LNK'] = json.dumps(lnk_parser.parsed_data, ensure_ascii=False)
                    except Exception:
                        entry['Embedded_LNK'] = ''
                    
                    # Add CustomDestinations header metadata to Property_Metadata
                    if not entry.get('Property_Metadata'):
                        entry['Property_Metadata'] = {}
                    if isinstance(entry['Property_Metadata'], str):
                        try:
                            entry['Property_Metadata'] = json.loads(entry['Property_Metadata'])
                        except:
                            entry['Property_Metadata'] = {}
                    
                    entry['Property_Metadata'].update(global_header)
                    entry['Property_Metadata'].update(category_header)
                    
                    results.append(entry)
                    entry_count += 1
                    
                    # Ensure progress: skip ahead based on the parser offset
                    p_offset = magic_idx + (lnk_parser.offset if lnk_parser.offset > len(magic) else len(magic))
                
                # Requirement 13B.8: Validate Entry Count matches actual entries found
                # For single category, validate against the category header
                if len(category_headers) == 1:
                    expected_entry_count = category_headers[0].get('CustDest_Entry_Count', 0)
                    if expected_entry_count > 0 and entry_count != expected_entry_count:
                        import logging
                        logger = logging.getLogger('A_CJL_LNK_Claw')
                        logger.warning(f"CustomDestinations Entry Count mismatch: Expected {expected_entry_count}, Found {entry_count}")
                        # Flag mismatch in Property_Metadata for all entries
                        for entry in results:
                            if isinstance(entry.get('Property_Metadata'), dict):
                                entry['Property_Metadata']['CustDest_Entry_Count_Mismatch'] = True
                                entry['Property_Metadata']['CustDest_Actual_Entry_Count'] = entry_count
            except Exception: 
                pass
                
        # 3. LNK Files
        elif filename.lower().endswith(".lnk"):
            with open(filepath, 'rb') as f:
                data = f.read()
            lnk_parser = LnkStreamParser(data, known_guids=known_guids)
            entry = clean_entry.copy()
            entry.update(lnk_parser.parsed_data)
            results.append(entry)
            
    except Exception as e:
        pass # Silently return empty or partial results on error
        
    return results

# Environment Constants
TARGET_BASE_DIR = os.path.join("Artifacts_Collectors", "Target Artifacts", "C,AJL and LNK")
TARGET_DIRS = {
    'recent': os.path.join(TARGET_BASE_DIR, "Recent"), 
    'automatic': os.path.join(TARGET_BASE_DIR, "Recent", "AutomaticDestinations"),
    'custom': os.path.join(TARGET_BASE_DIR, "Recent", "CustomDestinations")
}
SYSTEM_DRIVE = os.environ.get("SystemDrive", "C:") + "\\"  
USER_PROFILES_PATH = os.path.join(SYSTEM_DRIVE, "Users")

def update_target_directories(case_path=None):
    global TARGET_BASE_DIR, TARGET_DIRS
    if case_path:
        TARGET_BASE_DIR = os.path.join(case_path, "Target_Artifacts", "C_AJL_Lnk")
    else:
        TARGET_BASE_DIR = os.path.join("Artifacts_Collectors", "Target Artifacts", "C,AJL and LNK")
    
    TARGET_DIRS = {
        'recent': os.path.join(TARGET_BASE_DIR, "Recent"),
        'automatic': os.path.join(TARGET_BASE_DIR, "Recent", "AutomaticDestinations"),
        'custom': os.path.join(TARGET_BASE_DIR, "Recent", "CustomDestinations")
    }
    return TARGET_DIRS

def create_target_directories():
    try:
        os.makedirs(TARGET_DIRS['recent'], exist_ok=True)
        os.makedirs(TARGET_DIRS['automatic'], exist_ok=True)
        os.makedirs(TARGET_DIRS['custom'], exist_ok=True)
        return True
    except Exception as e:
        print(f" [!] Failed to create target directories: {str(e)}")
        return False

def get_user_profiles():
    users = []
    try:
        if not os.path.exists(USER_PROFILES_PATH):
            return users
        
        for entry in os.listdir(USER_PROFILES_PATH):
            user_path = os.path.join(USER_PROFILES_PATH, entry)
            is_dir = os.path.isdir(user_path)
            is_excluded = entry in ["Public", "Default", "Default User", "All Users"]
            starts_with_dot = entry.startswith('.')
            
            if is_dir and not is_excluded and not starts_with_dot:
                users.append(entry)
        return users
    except Exception:
        return []

def safe_copy(src, dst):
    try:
        if not os.path.exists(src) or os.path.exists(dst): return False
        shutil.copy2(src, dst)
        return os.path.exists(dst)
    except Exception:
        return False

def detect_artifact(file_path):
    filename = os.path.basename(file_path).lower()
    if filename.endswith('.lnk'): return "lnk"
    elif "automaticdestinations-ms" in filename: return "Automatic JumpList"
    elif "customdestinations-ms" in filename: return "Custom JumpList"
    return None

def is_important_path(source_path):
    return any(p in source_path for p in ["Recent", "Desktop", "Start Menu", "Explorer"])

def categorize_files_by_type(folder_path, progress_callback=None, counters=None):
    """
    Categorize files by type - NO progress updates during scanning.
    Only returns the categorized file lists.
    
    Args:
        folder_path: Path to scan for artifacts
        progress_callback: Optional callback (not used during scanning per user request)
        counters: Optional dict with 'lnk', 'auto', 'custom' keys (not updated during scanning)
    """
    lnk_files, automatic_jump_lists, custom_jump_lists = [], [], []
    
    # Scan all files without progress updates (per user request)
    for root, _, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            art_type = detect_artifact(file_path)
            if art_type == "lnk": 
                lnk_files.append(file_path)
            elif art_type == "Custom JumpList": 
                custom_jump_lists.append(file_path)
            elif art_type == "Automatic JumpList": 
                automatic_jump_lists.append(file_path)
    
    # NO progress updates during scanning - user wants only final processed count
    return lnk_files, automatic_jump_lists, custom_jump_lists

def create_database(case_path=None):
    db_path = 'LnkDB.db'
    if case_path:
        artifacts_dir = os.path.join(case_path, 'Target_Artifacts')
        if os.path.exists(artifacts_dir):
            db_path = os.path.join(artifacts_dir, 'LnkDB.db')
    
    with sqlite3.connect(db_path) as conn:
        C = conn.cursor()
        
        # Table 1: LNK_Files - for standalone .lnk files
        C.execute("""
        CREATE TABLE IF NOT EXISTS LNK_Files (
            -- Identity
            Source_Name TEXT,
            Source_Path TEXT PRIMARY KEY,
            
            -- Filesystem Metadata
            Owner_UID INTEGER,
            Owner_GID INTEGER,
            File_Permission TEXT,
            Num_Hard_Links INTEGER,
            Device_ID INTEGER,
            Inode_Number INTEGER,
            
            -- Timestamps
            Time_Access TEXT,
            Time_Creation TEXT,
            Time_Modification TEXT,
            
            -- LNK Header Fields
            LNK_Class_ID TEXT,
            Link_Flags TEXT,
            File_Attributes_Flags TEXT,
            FileSize TEXT,
            IconIndex INTEGER,
            Show_Window_Command TEXT,
            Hot_Key_Flags TEXT,
            Hot_Key_Value TEXT,
            
            -- Target Information
            Local_Path TEXT,
            Network_Share_Name TEXT,
            Common_Path TEXT,
            Relative_Path TEXT,
            Working_Directory TEXT,
            Command_Line_Arguments TEXT,
            Icon_Location TEXT,
            Description TEXT,
            
            -- Volume Information
            Volume_Type TEXT,
            Volume_Serial TEXT,
            Volume_Label TEXT,
            
            -- NTFS Metadata
            MFT_Entry_Number TEXT,
            MFT_Sequence_Number TEXT,
            
            -- Tracker Information
            Tracker_NetBIOS TEXT,
            Tracker_MAC TEXT,
            
            -- Extended Metadata (JSON)
            Property_Metadata TEXT,
            Darwin_ID TEXT,
            Environment_Variables TEXT,
            Known_Folder_GUID TEXT
        );
        """)
        
        # Create indexes for LNK_Files
        C.execute("CREATE INDEX IF NOT EXISTS idx_lnk_source_path ON LNK_Files(Source_Path);")
        C.execute("CREATE INDEX IF NOT EXISTS idx_lnk_local_path ON LNK_Files(Local_Path);")
        C.execute("CREATE INDEX IF NOT EXISTS idx_lnk_time_access ON LNK_Files(Time_Access);")
        C.execute("CREATE INDEX IF NOT EXISTS idx_lnk_mft_entry ON LNK_Files(MFT_Entry_Number);")
        
        # Table 2: Automatic_JumpLists - for AutomaticDestinations entries
        C.execute("""
        CREATE TABLE IF NOT EXISTS Automatic_JumpLists (
            -- Identity
            Source_Name TEXT,
            Source_Path TEXT,
            entry_number TEXT,
            
            -- Filesystem Metadata
            Owner_UID INTEGER,
            Owner_GID INTEGER,
            File_Permission TEXT,
            Num_Hard_Links INTEGER,
            Device_ID INTEGER,
            Inode_Number INTEGER,
            
            -- Application Context
            AppID TEXT,
            AppType TEXT,
            AppDesc TEXT,
            
            -- Timestamps
            Time_Access TEXT,
            Time_Creation TEXT,
            Time_Modification TEXT,
            
            -- LNK Header Fields (from embedded LNK)
            LNK_Class_ID TEXT,
            Link_Flags TEXT,
            File_Attributes_Flags TEXT,
            FileSize TEXT,
            IconIndex INTEGER,
            Show_Window_Command TEXT,
            Hot_Key_Flags TEXT,
            Hot_Key_Value TEXT,
            
            -- Target Information (from embedded LNK)
            Local_Path TEXT,
            Network_Share_Name TEXT,
            Common_Path TEXT,
            Relative_Path TEXT,
            Working_Directory TEXT,
            Command_Line_Arguments TEXT,
            Icon_Location TEXT,
            Description TEXT,
            
            -- Volume Information (from embedded LNK)
            Volume_Type TEXT,
            Volume_Serial TEXT,
            Volume_Label TEXT,
            
            -- NTFS Metadata (from embedded LNK)
            MFT_Entry_Number TEXT,
            MFT_Sequence_Number TEXT,
            
            -- Tracker Information (from embedded LNK)
            Tracker_NetBIOS TEXT,
            Tracker_MAC TEXT,
            
            -- DestList Header Fields
            DestList_Version_Number INTEGER,
            DestList_OS_Version TEXT,
            DestList_Total_Current_Entries INTEGER,
            DestList_Total_Pinned_Entries INTEGER,
            DestList_Last_ID INTEGER,
            DestList_Actions_Count INTEGER,
            
            -- DestList Entry Fields
            DestList_Checksum TEXT,
            DestList_New_Volume_ID TEXT,
            DestList_New_Object_ID TEXT,
            Birth_Volume_ID TEXT,
            Birth_Object_ID TEXT,
            Birth_Object_ID_MAC TEXT,
            DestList_Access_Counter INTEGER,
            DestList_Pin_Status TEXT,
            
            -- Embedded LNK Data (JSON)
            Embedded_LNK TEXT,
            
            -- Extended Metadata (JSON)
            Property_Metadata TEXT,
            Darwin_ID TEXT,
            Environment_Variables TEXT,
            Known_Folder_GUID TEXT,
            
            -- Composite Primary Key
            PRIMARY KEY (Source_Path, entry_number)
        );
        """)
        
        # Create indexes for Automatic_JumpLists
        C.execute("CREATE INDEX IF NOT EXISTS idx_ajl_source_path ON Automatic_JumpLists(Source_Path);")
        C.execute("CREATE INDEX IF NOT EXISTS idx_ajl_local_path ON Automatic_JumpLists(Local_Path);")
        C.execute("CREATE INDEX IF NOT EXISTS idx_ajl_appid ON Automatic_JumpLists(AppID);")
        C.execute("CREATE INDEX IF NOT EXISTS idx_ajl_time_access ON Automatic_JumpLists(Time_Access);")
        C.execute("CREATE INDEX IF NOT EXISTS idx_ajl_mft_entry ON Automatic_JumpLists(MFT_Entry_Number);")
        
        # Table 3: Custom_JumpLists - for CustomDestinations entries
        C.execute("""
        CREATE TABLE IF NOT EXISTS Custom_JumpLists (
            -- Identity
            entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
            Source_Name TEXT,
            Source_Path TEXT,
            
            -- Filesystem Metadata
            Owner_UID INTEGER,
            Owner_GID INTEGER,
            File_Permission TEXT,
            Num_Hard_Links INTEGER,
            Device_ID INTEGER,
            Inode_Number INTEGER,
            
            -- Application Context
            AppID TEXT,
            AppType TEXT,
            AppDesc TEXT,
            
            -- Custom JumpList Specific
            Category TEXT,
            Footer_Signature_Valid INTEGER,
            
            -- Timestamps
            Time_Access TEXT,
            Time_Creation TEXT,
            Time_Modification TEXT,
            
            -- LNK Header Fields (from embedded LNK)
            LNK_Class_ID TEXT,
            Link_Flags TEXT,
            File_Attributes_Flags TEXT,
            FileSize TEXT,
            IconIndex INTEGER,
            Show_Window_Command TEXT,
            Hot_Key_Flags TEXT,
            Hot_Key_Value TEXT,
            
            -- Target Information (from embedded LNK)
            Local_Path TEXT,
            Network_Share_Name TEXT,
            Common_Path TEXT,
            Relative_Path TEXT,
            Working_Directory TEXT,
            Command_Line_Arguments TEXT,
            Icon_Location TEXT,
            Description TEXT,
            
            -- Volume Information (from embedded LNK)
            Volume_Type TEXT,
            Volume_Serial TEXT,
            Volume_Label TEXT,
            
            -- NTFS Metadata (from embedded LNK)
            MFT_Entry_Number TEXT,
            MFT_Sequence_Number TEXT,
            
            -- Tracker Information (from embedded LNK)
            Tracker_NetBIOS TEXT,
            Tracker_MAC TEXT,
            
            -- Embedded LNK Data (JSON)
            Embedded_LNK TEXT,
            
            -- Extended Metadata (JSON)
            Property_Metadata TEXT,
            Darwin_ID TEXT,
            Environment_Variables TEXT,
            Known_Folder_GUID TEXT
        );
        """)
        
        # Create indexes for Custom_JumpLists
        C.execute("CREATE INDEX IF NOT EXISTS idx_cjl_source_path ON Custom_JumpLists(Source_Path);")
        C.execute("CREATE INDEX IF NOT EXISTS idx_cjl_local_path ON Custom_JumpLists(Local_Path);")
        C.execute("CREATE INDEX IF NOT EXISTS idx_cjl_appid ON Custom_JumpLists(AppID);")
        C.execute("CREATE INDEX IF NOT EXISTS idx_cjl_category ON Custom_JumpLists(Category);")
        C.execute("CREATE INDEX IF NOT EXISTS idx_cjl_time_access ON Custom_JumpLists(Time_Access);")
        
        conn.commit()
    return db_path

def insert_lnk_file_to_db(cursor, source_path, item, stat_info):
    """
    Insert standalone LNK file records into LNK_Files table.
    Requirement 9.1: Insert with all new columns.
    
    Returns:
        'inserted': Record was newly inserted
        'skipped': Record already exists (skipped)
        'error': Error occurred during insertion
    """
    try:
        # Check if record already exists
        cursor.execute("""
        SELECT COUNT(*) FROM LNK_Files WHERE Source_Path = ?
        """, (source_path,))
        
        if cursor.fetchone()[0] > 0:
            # Record already exists, skip insertion
            return 'skipped'
        
        cursor.execute("""
        INSERT INTO LNK_Files (
            Source_Name, Source_Path,
            Owner_UID, Owner_GID, File_Permission, Num_Hard_Links, Device_ID, Inode_Number,
            Time_Access, Time_Creation, Time_Modification,
            LNK_Class_ID, Link_Flags, File_Attributes_Flags, FileSize, IconIndex,
            Show_Window_Command, Hot_Key_Flags, Hot_Key_Value,
            Local_Path, Network_Share_Name, Common_Path, Relative_Path, Working_Directory,
            Command_Line_Arguments, Icon_Location, Description,
            Volume_Type, Volume_Serial, Volume_Label,
            MFT_Entry_Number, MFT_Sequence_Number,
            Tracker_NetBIOS, Tracker_MAC,
            Property_Metadata, Darwin_ID, Environment_Variables, Known_Folder_GUID
        )
        VALUES (
            :Source_Name, :Source_Path,
            :Owner_UID, :Owner_GID, :File_Permission, :Num_Hard_Links, :Device_ID, :Inode_Number,
            :Time_Access, :Time_Creation, :Time_Modification,
            :LNK_Class_ID, :Link_Flags, :File_Attributes_Flags, :FileSize, :IconIndex,
            :Show_Window_Command, :Hot_Key_Flags, :Hot_Key_Value,
            :Local_Path, :Network_Share_Name, :Common_Path, :Relative_Path, :Working_Directory,
            :Command_Line_Arguments, :Icon_Location, :Description,
            :Volume_Type, :Volume_Serial, :Volume_Label,
            :MFT_Entry_Number, :MFT_Sequence_Number,
            :Tracker_NetBIOS, :Tracker_MAC,
            :Property_Metadata, :Darwin_ID, :Environment_Variables, :Known_Folder_GUID
        )
        """, {
            "Source_Name": os.path.basename(source_path),
            "Source_Path": source_path,
            "Owner_UID": safe_sqlite_int(stat_info.st_uid),
            "Owner_GID": safe_sqlite_int(stat_info.st_gid),
            "File_Permission": oct(stat_info.st_mode),
            "Num_Hard_Links": safe_sqlite_int(stat_info.st_nlink),
            "Device_ID": safe_sqlite_int(stat_info.st_dev),
            "Inode_Number": safe_sqlite_int(stat_info.st_ino),
            "Time_Access": item.get("Time_Access", ""),
            "Time_Creation": item.get("Time_Creation", ""),
            "Time_Modification": item.get("Time_Modification", ""),
            "LNK_Class_ID": item.get("LNK_Class_ID", ""),
            "Link_Flags": item.get("Link_Flags", ""),
            "File_Attributes_Flags": item.get("File_Attributes_Flags", ""),
            "FileSize": item.get("FileSize", ""),
            "IconIndex": safe_sqlite_int(item.get("IconIndex")),
            "Show_Window_Command": item.get("Show_Window_Command", ""),
            "Hot_Key_Flags": item.get("Hot_Key_Flags", ""),
            "Hot_Key_Value": item.get("Hot_Key_Value", ""),
            "Local_Path": item.get("Local_Path", ""),
            "Network_Share_Name": item.get("Network_Share_Name", ""),
            "Common_Path": item.get("Common_Path", ""),
            "Relative_Path": item.get("Relative_Path", ""),
            "Working_Directory": item.get("Working_Directory", ""),
            "Command_Line_Arguments": item.get("Command_Line_Arguments", ""),
            "Icon_Location": item.get("Icon_Location", ""),
            "Description": item.get("Description", ""),
            "Volume_Type": item.get("Volume_Type", ""),
            "Volume_Serial": item.get("Volume_Serial", ""),
            "Volume_Label": item.get("Volume_Label", ""),
            "MFT_Entry_Number": item.get("MFT_Entry_Number", ""),
            "MFT_Sequence_Number": item.get("MFT_Sequence_Number", ""),
            "Tracker_NetBIOS": item.get("Tracker_NetBIOS", ""),
            "Tracker_MAC": item.get("Tracker_MAC", ""),
            "Property_Metadata": json.dumps(item.get("Property_Metadata", {}), ensure_ascii=False),
            "Darwin_ID": item.get("Darwin_ID", ""),
            "Environment_Variables": item.get("Environment_Variables", ""),
            "Known_Folder_GUID": item.get("Known_Folder_GUID", "")
        })
        return 'inserted'
    except Exception:
        return 'error'

def insert_automatic_jl_to_db(cursor, source_path, item, stat_info):
    """
    Insert AutomaticDestinations entries into Automatic_JumpLists table.
    Requirement 9.2: Insert with all LNK fields plus DestList fields and Embedded_LNK JSON.
    
    Returns:
        'inserted': Record was newly inserted
        'skipped': Record already exists (skipped)
        'error': Error occurred during insertion
    """
    try:
        # Check if record already exists (composite primary key: Source_Path + entry_number)
        cursor.execute("""
        SELECT COUNT(*) FROM Automatic_JumpLists 
        WHERE Source_Path = ? AND entry_number = ?
        """, (source_path, item.get("entry_number", "")))
        
        if cursor.fetchone()[0] > 0:
            # Record already exists, skip insertion
            return 'skipped'
        
        cursor.execute("""
        INSERT INTO Automatic_JumpLists (
            Source_Name, Source_Path, entry_number,
            Owner_UID, Owner_GID, File_Permission, Num_Hard_Links, Device_ID, Inode_Number,
            AppID, AppType, AppDesc,
            Time_Access, Time_Creation, Time_Modification,
            LNK_Class_ID, Link_Flags, File_Attributes_Flags, FileSize, IconIndex,
            Show_Window_Command, Hot_Key_Flags, Hot_Key_Value,
            Local_Path, Network_Share_Name, Common_Path, Relative_Path, Working_Directory,
            Command_Line_Arguments, Icon_Location, Description,
            Volume_Type, Volume_Serial, Volume_Label,
            MFT_Entry_Number, MFT_Sequence_Number,
            Tracker_NetBIOS, Tracker_MAC,
            DestList_Version_Number, DestList_OS_Version, DestList_Total_Current_Entries,
            DestList_Total_Pinned_Entries, DestList_Last_ID, DestList_Actions_Count,
            DestList_Checksum, DestList_New_Volume_ID, DestList_New_Object_ID,
            Birth_Volume_ID, Birth_Object_ID, Birth_Object_ID_MAC,
            DestList_Access_Counter, DestList_Pin_Status,
            Embedded_LNK,
            Property_Metadata, Darwin_ID, Environment_Variables, Known_Folder_GUID
        )
        VALUES (
            :Source_Name, :Source_Path, :entry_number,
            :Owner_UID, :Owner_GID, :File_Permission, :Num_Hard_Links, :Device_ID, :Inode_Number,
            :AppID, :AppType, :AppDesc,
            :Time_Access, :Time_Creation, :Time_Modification,
            :LNK_Class_ID, :Link_Flags, :File_Attributes_Flags, :FileSize, :IconIndex,
            :Show_Window_Command, :Hot_Key_Flags, :Hot_Key_Value,
            :Local_Path, :Network_Share_Name, :Common_Path, :Relative_Path, :Working_Directory,
            :Command_Line_Arguments, :Icon_Location, :Description,
            :Volume_Type, :Volume_Serial, :Volume_Label,
            :MFT_Entry_Number, :MFT_Sequence_Number,
            :Tracker_NetBIOS, :Tracker_MAC,
            :DestList_Version_Number, :DestList_OS_Version, :DestList_Total_Current_Entries,
            :DestList_Total_Pinned_Entries, :DestList_Last_ID, :DestList_Actions_Count,
            :DestList_Checksum, :DestList_New_Volume_ID, :DestList_New_Object_ID,
            :Birth_Volume_ID, :Birth_Object_ID, :Birth_Object_ID_MAC,
            :DestList_Access_Counter, :DestList_Pin_Status,
            :Embedded_LNK,
            :Property_Metadata, :Darwin_ID, :Environment_Variables, :Known_Folder_GUID
        )
        """, {
            "Source_Name": os.path.basename(source_path),
            "Source_Path": source_path,
            "entry_number": item.get("entry_number", ""),
            "Owner_UID": safe_sqlite_int(stat_info.st_uid),
            "Owner_GID": safe_sqlite_int(stat_info.st_gid),
            "File_Permission": oct(stat_info.st_mode),
            "Num_Hard_Links": safe_sqlite_int(stat_info.st_nlink),
            "Device_ID": safe_sqlite_int(stat_info.st_dev),
            "Inode_Number": safe_sqlite_int(stat_info.st_ino),
            "AppID": item.get("AppID", ""),
            "AppType": item.get("AppType", ""),
            "AppDesc": item.get("AppDesc", ""),
            "Time_Access": item.get("Time_Access", ""),
            "Time_Creation": item.get("Time_Creation", ""),
            "Time_Modification": item.get("Time_Modification", ""),
            "LNK_Class_ID": item.get("LNK_Class_ID", ""),
            "Link_Flags": item.get("Link_Flags", ""),
            "File_Attributes_Flags": item.get("File_Attributes_Flags", ""),
            "FileSize": item.get("FileSize", ""),
            "IconIndex": safe_sqlite_int(item.get("IconIndex")),
            "Show_Window_Command": item.get("Show_Window_Command", ""),
            "Hot_Key_Flags": item.get("Hot_Key_Flags", ""),
            "Hot_Key_Value": item.get("Hot_Key_Value", ""),
            "Local_Path": item.get("Local_Path", ""),
            "Network_Share_Name": item.get("Network_Share_Name", ""),
            "Common_Path": item.get("Common_Path", ""),
            "Relative_Path": item.get("Relative_Path", ""),
            "Working_Directory": item.get("Working_Directory", ""),
            "Command_Line_Arguments": item.get("Command_Line_Arguments", ""),
            "Icon_Location": item.get("Icon_Location", ""),
            "Description": item.get("Description", ""),
            "Volume_Type": item.get("Volume_Type", ""),
            "Volume_Serial": item.get("Volume_Serial", ""),
            "Volume_Label": item.get("Volume_Label", ""),
            "MFT_Entry_Number": item.get("MFT_Entry_Number", ""),
            "MFT_Sequence_Number": item.get("MFT_Sequence_Number", ""),
            "Tracker_NetBIOS": item.get("Tracker_NetBIOS", ""),
            "Tracker_MAC": item.get("Tracker_MAC", ""),
            "DestList_Version_Number": safe_sqlite_int(item.get("DestList_Version_Number")),
            "DestList_OS_Version": item.get("DestList_OS_Version", ""),
            "DestList_Total_Current_Entries": safe_sqlite_int(item.get("DestList_Total_Current_Entries")),
            "DestList_Total_Pinned_Entries": safe_sqlite_int(item.get("DestList_Total_Pinned_Entries")),
            "DestList_Last_ID": safe_sqlite_int(item.get("DestList_Last_ID")),
            "DestList_Actions_Count": safe_sqlite_int(item.get("DestList_Actions_Count")),
            "DestList_Checksum": item.get("DestList_Checksum", ""),
            "DestList_New_Volume_ID": item.get("DestList_New_Volume_ID", ""),
            "DestList_New_Object_ID": item.get("DestList_New_Object_ID", ""),
            "Birth_Volume_ID": item.get("Birth_Volume_ID", ""),
            "Birth_Object_ID": item.get("Birth_Object_ID", ""),
            "Birth_Object_ID_MAC": item.get("Birth_Object_ID_MAC", ""),
            "DestList_Access_Counter": safe_sqlite_int(item.get("DestList_Access_Counter")),
            "DestList_Pin_Status": item.get("DestList_Pin_Status", ""),
            "Embedded_LNK": item.get("Embedded_LNK", ""),
            "Property_Metadata": json.dumps(item.get("Property_Metadata", {}), ensure_ascii=False),
            "Darwin_ID": item.get("Darwin_ID", ""),
            "Environment_Variables": item.get("Environment_Variables", ""),
            "Known_Folder_GUID": item.get("Known_Folder_GUID", "")
        })
        return 'inserted'
    except Exception:
        return 'error'

def insert_custom_jl_to_db(cursor, source_path, item, stat_info):
    """
    Insert CustomDestinations entries into Custom_JumpLists table.
    Requirement 9.3: Insert with all LNK fields plus Custom fields and Embedded_LNK JSON.
    
    Returns:
        'inserted': Record was newly inserted
        'skipped': Record already exists (skipped)
        'error': Error occurred during insertion
    """
    try:
        # Check if record already exists
        cursor.execute("""
        SELECT COUNT(*) FROM Custom_JumpLists WHERE Source_Path = ?
        """, (source_path,))
        
        if cursor.fetchone()[0] > 0:
            # Record already exists, skip insertion
            return 'skipped'
        
        cursor.execute("""
        INSERT INTO Custom_JumpLists (
            Source_Name, Source_Path,
            Owner_UID, Owner_GID, File_Permission, Num_Hard_Links, Device_ID, Inode_Number,
            AppID, AppType, AppDesc,
            Category, Footer_Signature_Valid,
            Time_Access, Time_Creation, Time_Modification,
            LNK_Class_ID, Link_Flags, File_Attributes_Flags, FileSize, IconIndex,
            Show_Window_Command, Hot_Key_Flags, Hot_Key_Value,
            Local_Path, Network_Share_Name, Common_Path, Relative_Path, Working_Directory,
            Command_Line_Arguments, Icon_Location, Description,
            Volume_Type, Volume_Serial, Volume_Label,
            MFT_Entry_Number, MFT_Sequence_Number,
            Tracker_NetBIOS, Tracker_MAC,
            Embedded_LNK,
            Property_Metadata, Darwin_ID, Environment_Variables, Known_Folder_GUID
        )
        VALUES (
            :Source_Name, :Source_Path,
            :Owner_UID, :Owner_GID, :File_Permission, :Num_Hard_Links, :Device_ID, :Inode_Number,
            :AppID, :AppType, :AppDesc,
            :Category, :Footer_Signature_Valid,
            :Time_Access, :Time_Creation, :Time_Modification,
            :LNK_Class_ID, :Link_Flags, :File_Attributes_Flags, :FileSize, :IconIndex,
            :Show_Window_Command, :Hot_Key_Flags, :Hot_Key_Value,
            :Local_Path, :Network_Share_Name, :Common_Path, :Relative_Path, :Working_Directory,
            :Command_Line_Arguments, :Icon_Location, :Description,
            :Volume_Type, :Volume_Serial, :Volume_Label,
            :MFT_Entry_Number, :MFT_Sequence_Number,
            :Tracker_NetBIOS, :Tracker_MAC,
            :Embedded_LNK,
            :Property_Metadata, :Darwin_ID, :Environment_Variables, :Known_Folder_GUID
        )
        """, {
            "Source_Name": os.path.basename(source_path),
            "Source_Path": source_path,
            "Owner_UID": safe_sqlite_int(stat_info.st_uid),
            "Owner_GID": safe_sqlite_int(stat_info.st_gid),
            "File_Permission": oct(stat_info.st_mode),
            "Num_Hard_Links": safe_sqlite_int(stat_info.st_nlink),
            "Device_ID": safe_sqlite_int(stat_info.st_dev),
            "Inode_Number": safe_sqlite_int(stat_info.st_ino),
            "AppID": item.get("AppID", ""),
            "AppType": item.get("AppType", ""),
            "AppDesc": item.get("AppDesc", ""),
            "Category": item.get("Category", ""),
            "Footer_Signature_Valid": safe_sqlite_int(item.get("Footer_Signature_Valid")),
            "Time_Access": item.get("Time_Access", ""),
            "Time_Creation": item.get("Time_Creation", ""),
            "Time_Modification": item.get("Time_Modification", ""),
            "LNK_Class_ID": item.get("LNK_Class_ID", ""),
            "Link_Flags": item.get("Link_Flags", ""),
            "File_Attributes_Flags": item.get("File_Attributes_Flags", ""),
            "FileSize": item.get("FileSize", ""),
            "IconIndex": safe_sqlite_int(item.get("IconIndex")),
            "Show_Window_Command": item.get("Show_Window_Command", ""),
            "Hot_Key_Flags": item.get("Hot_Key_Flags", ""),
            "Hot_Key_Value": item.get("Hot_Key_Value", ""),
            "Local_Path": item.get("Local_Path", ""),
            "Network_Share_Name": item.get("Network_Share_Name", ""),
            "Common_Path": item.get("Common_Path", ""),
            "Relative_Path": item.get("Relative_Path", ""),
            "Working_Directory": item.get("Working_Directory", ""),
            "Command_Line_Arguments": item.get("Command_Line_Arguments", ""),
            "Icon_Location": item.get("Icon_Location", ""),
            "Description": item.get("Description", ""),
            "Volume_Type": item.get("Volume_Type", ""),
            "Volume_Serial": item.get("Volume_Serial", ""),
            "Volume_Label": item.get("Volume_Label", ""),
            "MFT_Entry_Number": item.get("MFT_Entry_Number", ""),
            "MFT_Sequence_Number": item.get("MFT_Sequence_Number", ""),
            "Tracker_NetBIOS": item.get("Tracker_NetBIOS", ""),
            "Tracker_MAC": item.get("Tracker_MAC", ""),
            "Embedded_LNK": item.get("Embedded_LNK", ""),
            "Property_Metadata": json.dumps(item.get("Property_Metadata", {}), ensure_ascii=False),
            "Darwin_ID": item.get("Darwin_ID", ""),
            "Environment_Variables": item.get("Environment_Variables", ""),
            "Known_Folder_GUID": item.get("Known_Folder_GUID", "")
        })
        return 'inserted'
    except Exception:
        return 'error'

def parse_artifacts_directly(source_path, db_path, user=None, progress_callback=None, counters=None):
    """
    Parse artifacts directly from source path and insert into database.
    
    Args:
        source_path: Path to scan for artifacts
        db_path: Database path
        user: Username for context
        progress_callback: Optional callback(lnk_count, auto_count, custom_count, message)
        counters: Optional dict with 'lnk', 'auto', 'custom' keys to track cumulative counts
    """
    artifacts = {'recent': [], 'automatic': [], 'custom': []}
    unparsed_files = []
    
    if not os.path.exists(source_path):
        return artifacts, unparsed_files
    
    # Initialize counters if not provided
    if counters is None:
        counters = {'lnk': 0, 'auto': 0, 'custom': 0}
        
    try:
        appids = read_AppId(appid_path)
        known_guids = read_KnownGuids(guid_path)
        
        # Send initial progress update
        if progress_callback:
            progress_callback(counters['lnk'], counters['auto'], counters['custom'], 
                            f"Scanning: {os.path.basename(source_path) or source_path}")
        
        with sqlite3.connect(db_path) as conn:
            C = conn.cursor()
            
            # Categorize files (NO progress updates during scanning per user request)
            lnk_files, automatic_jump_lists, custom_jump_lists = categorize_files_by_type(
                source_path, progress_callback=None, counters=None
            )
            
            # Calculate total files and progress thresholds
            all_files = lnk_files + automatic_jump_lists + custom_jump_lists
            total_files = len(all_files)
            
            if total_files == 0:
                if progress_callback:
                    progress_callback(counters['lnk'], counters['auto'], counters['custom'], 
                                    f"No artifacts found in: {os.path.basename(source_path) or source_path}")
                return artifacts, unparsed_files
            
            # Update progress every 10% (or at least every 10 files, whichever is larger)
            progress_threshold = max(10, total_files // 10)
            files_processed = 0
            last_progress_update = 0
            
            # Send initial parsing progress update
            if progress_callback:
                progress_callback(counters['lnk'], counters['auto'], counters['custom'], 
                                f"Parsing {total_files} files...")
            
            for file in all_files:
                artifact_type = detect_artifact(file)
                if not artifact_type: 
                    files_processed += 1
                    continue
                    
                dir_key = 'recent' if artifact_type == 'lnk' else 'automatic' if 'Automatic' in artifact_type else 'custom'
                
                try:
                    stat_info = os.stat(file)
                    items = extract_artifacts_from_file(file, appids, known_guids)
                    if not items:
                        unparsed_files.append(file)
                        # Still count the file as processed even if no items extracted
                        files_processed += 1
                        continue
                    else:
                        for item in items:
                            result = None
                            if dir_key == 'recent':
                                result = insert_lnk_file_to_db(C, file, item, stat_info)
                                if result in ('inserted', 'skipped'):
                                    counters['lnk'] += 1
                                    artifacts[dir_key].append(file)
                            elif dir_key == 'automatic':
                                result = insert_automatic_jl_to_db(C, file, item, stat_info)
                                if result in ('inserted', 'skipped'):
                                    counters['auto'] += 1
                                    artifacts[dir_key].append(file)
                            elif dir_key == 'custom':
                                result = insert_custom_jl_to_db(C, file, item, stat_info)
                                if result in ('inserted', 'skipped'):
                                    counters['custom'] += 1
                                    artifacts[dir_key].append(file)
                                    
                            # Track errors
                            if result == 'error':
                                unparsed_files.append(file)
                                
                except Exception:
                    unparsed_files.append(file)
                
                # Increment files processed counter
                files_processed += 1
                
                # Update progress callback every 10% (or at the end) - reduced frequency to prevent freezing
                if progress_callback:
                    should_update = (files_processed - last_progress_update >= progress_threshold) or (files_processed == total_files)
                    
                    if should_update:
                        last_progress_update = files_processed
                        percentage = int((files_processed / total_files) * 100)
                        # Use simpler progress message without filename to reduce UI overhead
                        progress_callback(counters['lnk'], counters['auto'], counters['custom'], 
                                        f"Parsing: {percentage}% ({files_processed}/{total_files})")
                        
            conn.commit()
            
            # Send FINAL progress update with TOTAL PROCESSED FILES (per user request)
            if progress_callback:
                total_processed = counters['lnk'] + counters['auto'] + counters['custom']
                progress_callback(counters['lnk'], counters['auto'], counters['custom'], 
                                f"✓ Processed {total_processed} files from {os.path.basename(source_path) or source_path}")
                
    except Exception:
        if progress_callback:
            progress_callback(counters['lnk'], counters['auto'], counters['custom'], 
                            f"Error scanning: {os.path.basename(source_path) or source_path}")
    
    return artifacts, unparsed_files

def parse_user_artifacts_directly(user, db_path, full_scan=True, progress_callback=None):
    """
    Parse LNK artifacts directly for a specific user.
    
    Args:
        user: Username to parse artifacts for
        db_path: Path to database
        full_scan: If True (default), scan entire user profile. If False, scan only known locations.
        progress_callback: Optional callback(lnk_count, auto_count, custom_count, message)
    """
    artifacts = {'recent': [], 'automatic': [], 'custom': []}
    unparsed_files = []
    
    # Shared counters for this user
    counters = {'lnk': 0, 'auto': 0, 'custom': 0}
    
    if full_scan:
        # Full scan mode: Scan entire user profile directory
        user_profile_path = os.path.join(USER_PROFILES_PATH, user)
        if os.path.exists(user_profile_path):
            if progress_callback:
                progress_callback(counters['lnk'], counters['auto'], counters['custom'], f"Scanning user: {user}")
            data, unparsed = parse_artifacts_directly(user_profile_path, db_path, user, progress_callback, counters)
            artifacts['recent'].extend(data['recent'])
            artifacts['automatic'].extend(data['automatic'])
            artifacts['custom'].extend(data['custom'])
            unparsed_files.extend(unparsed)
    else:
        # Legacy mode: Scan only known locations
        base_path = os.path.join(USER_PROFILES_PATH, user, "AppData")
        paths = [
            os.path.join(base_path, "Roaming", "Microsoft", "Windows", "Recent"),
            os.path.join(base_path, "Roaming", "Microsoft", "Office", "Recent"),
            os.path.join(USER_PROFILES_PATH, user, "Desktop"),
            os.path.join(base_path, "Roaming", "Microsoft", "Windows", "Start Menu"),
            os.path.join(SYSTEM_DRIVE, "ProgramData", "Microsoft", "Windows", "Start Menu"),
            os.path.join(base_path, "Roaming", "Microsoft", "Internet Explorer", "Quick Launch", "User Pinned", "TaskBar"),
            os.path.join(base_path, "Local", "Microsoft", "Windows", "Explorer")
        ]
        
        for path in paths:
            if os.path.exists(path):
                data, unparsed = parse_artifacts_directly(path, db_path, user, progress_callback, counters)
                artifacts['recent'].extend(data['recent'])
                artifacts['automatic'].extend(data['automatic'])
                artifacts['custom'].extend(data['custom'])
                unparsed_files.extend(unparsed)
            
    return artifacts, unparsed_files

def parse_system_artifacts_directly(db_path, full_scan=True, progress_callback=None):
    """
    Parse system-wide LNK artifacts directly.
    
    Args:
        db_path: Path to database
        full_scan: If True (default), scan entire system. If False, scan only known locations.
        progress_callback: Optional callback(lnk_count, auto_count, custom_count, message)
    """
    artifacts = {'recent': [], 'automatic': [], 'custom': []}
    unparsed_files = []
    
    # Shared counters for system artifacts
    counters = {'lnk': 0, 'auto': 0, 'custom': 0}
    
    if full_scan:
        # Full scan mode: Scan system-wide locations
        
        # Scan ProgramData
        programdata_path = os.path.join(SYSTEM_DRIVE, "ProgramData")
        if os.path.exists(programdata_path):
            if progress_callback:
                progress_callback(counters['lnk'], counters['auto'], counters['custom'], "Scanning ProgramData...")
            data, unparsed = parse_artifacts_directly(programdata_path, db_path, "System", progress_callback, counters)
            artifacts['recent'].extend(data['recent'])
            artifacts['automatic'].extend(data['automatic'])
            artifacts['custom'].extend(data['custom'])
            unparsed_files.extend(unparsed)
        
        # Scan Public folder
        public_path = os.path.join(USER_PROFILES_PATH, "Public")
        if os.path.exists(public_path):
            if progress_callback:
                progress_callback(counters['lnk'], counters['auto'], counters['custom'], "Scanning Public folder...")
            data, unparsed = parse_artifacts_directly(public_path, db_path, "Public", progress_callback, counters)
            artifacts['recent'].extend(data['recent'])
            artifacts['automatic'].extend(data['automatic'])
            artifacts['custom'].extend(data['custom'])
            unparsed_files.extend(unparsed)
        
        # Scan Recycle Bin
        recycle_bin_path = os.path.join(SYSTEM_DRIVE, "$Recycle.Bin")
        if os.path.exists(recycle_bin_path):
            if progress_callback:
                progress_callback(counters['lnk'], counters['auto'], counters['custom'], "Scanning Recycle Bin...")
            for sid_folder in os.listdir(recycle_bin_path):
                sid_path = os.path.join(recycle_bin_path, sid_folder)
                if os.path.isdir(sid_path):
                    data, unparsed = parse_artifacts_directly(sid_path, db_path, f"RecycleBin_{sid_folder}", progress_callback, counters)
                    artifacts['recent'].extend(data['recent'])
                    unparsed_files.extend(unparsed)
    else:
        # Legacy mode: Scan only known locations
        public_desktop_path = os.path.join(SYSTEM_DRIVE, "Users", "Public", "Desktop")
        data, unparsed = parse_artifacts_directly(public_desktop_path, db_path, "Public", progress_callback, counters)
        artifacts['recent'].extend(data['recent'])
        unparsed_files.extend(unparsed)
        
        recycle_bin_path = os.path.join(SYSTEM_DRIVE, "$Recycle.Bin")
        if os.path.exists(recycle_bin_path):
            for sid_folder in os.listdir(recycle_bin_path):
                sid_path = os.path.join(recycle_bin_path, sid_folder)
                if os.path.isdir(sid_path):
                    data, unparsed = parse_artifacts_directly(sid_path, db_path, f"RecycleBin_{sid_folder}", progress_callback, counters)
                    artifacts['recent'].extend(data['recent'])
                    unparsed_files.extend(unparsed)
                
    return artifacts, unparsed_files

def collect_artifacts(source_path, user=None):
    artifacts = {'recent': [], 'automatic': [], 'custom': []}
    if not os.path.exists(source_path): return artifacts
        
    try:
        lnk_files, automatic_jump_lists, custom_jump_lists = categorize_files_by_type(source_path)
        all_files = [(lnk_files, "recent"), (automatic_jump_lists, "automatic"), (custom_jump_lists, "custom")]
        
        for file_list, dir_key in all_files:
            for file in file_list:
                artifact_type = detect_artifact(file)
                if artifact_type:
                    prefix = f"{user}_" if user else ""
                    dst = os.path.join(TARGET_DIRS[dir_key], f"{prefix}{os.path.basename(file)}")
                    if safe_copy(file, dst):
                        artifacts[dir_key].append(dst)
    except Exception as e:
        pass
    return artifacts

def process_lnk_and_jump_list_files(folder_path, db_path='LnkDB.db'):
    appids = read_AppId(appid_path)
    known_guids = read_KnownGuids(guid_path)
    unparsed_files = []
    lnk_files, automatic_jump_lists, custom_jump_lists = categorize_files_by_type(folder_path)
    
    with sqlite3.connect(db_path) as conn:
        C = conn.cursor()
        for file in lnk_files + automatic_jump_lists + custom_jump_lists:
            artifact_type = detect_artifact(file)
            try:
                stat_info = os.stat(file)
                items = extract_artifacts_from_file(file, appids, known_guids)
                if not items:
                    unparsed_files.append(file)
                else:
                    for item in items:
                        dir_key = 'recent' if artifact_type == 'lnk' else 'automatic' if 'Automatic' in artifact_type else 'custom'
                        inserted = False
                        if dir_key == 'recent':
                            inserted = insert_lnk_file_to_db(C, file, item, stat_info)
                        elif dir_key == 'automatic':
                            inserted = insert_automatic_jl_to_db(C, file, item, stat_info)
                        elif dir_key == 'custom':
                            inserted = insert_custom_jl_to_db(C, file, item, stat_info)
                            
                        if not inserted:
                            unparsed_files.append(file)
            except Exception:
                unparsed_files.append(file)
        conn.commit()
    return len(unparsed_files)

def collect_user_artifacts(user, full_scan=True):
    """
    Collect LNK artifacts for a specific user.
    
    Args:
        user: Username to collect artifacts for
        full_scan: If True, scan entire user profile. If False, scan only known locations.
    """
    artifacts = {'recent': [], 'automatic': [], 'custom': []}
    
    if full_scan:
        # Full scan mode: Scan entire user profile directory
        user_profile_path = os.path.join(USER_PROFILES_PATH, user)
        if os.path.exists(user_profile_path):
            data = collect_artifacts(user_profile_path, user)
            artifacts['recent'].extend(data['recent'])
            artifacts['automatic'].extend(data['automatic'])
            artifacts['custom'].extend(data['custom'])
    else:
        # Legacy mode: Scan only known locations
        base_path = os.path.join(USER_PROFILES_PATH, user, "AppData")
        
        paths = [
            os.path.join(base_path, "Roaming", "Microsoft", "Windows", "Recent"),
            os.path.join(USER_PROFILES_PATH, user, "Desktop"),
            os.path.join(USER_PROFILES_PATH, user, "Downloads"),
            os.path.join(base_path, "Roaming", "Microsoft", "Windows", "Start Menu"),
            os.path.join(SYSTEM_DRIVE, "ProgramData", "Microsoft", "Windows", "Start Menu"),
            os.path.join(base_path, "Roaming", "Microsoft", "Internet Explorer", "Quick Launch", "User Pinned", "TaskBar"),
            os.path.join(base_path, "Local", "Microsoft", "Windows", "Explorer")
        ]
        
        for path in paths:
            data = collect_artifacts(path, user)
            artifacts['recent'].extend(data['recent'])
            artifacts['automatic'].extend(data['automatic'])
            artifacts['custom'].extend(data['custom'])
    
    return artifacts

def collect_system_artifacts(full_scan=True):
    """
    Collect system-wide LNK artifacts.
    
    Args:
        full_scan: If True, scan entire system drive. If False, scan only known locations.
    """
    artifacts = {'recent': [], 'automatic': [], 'custom': []}
    
    if full_scan:
        # Full scan mode: Scan entire system drive (excluding user profiles to avoid duplication)
        
        # Scan ProgramData
        programdata_path = os.path.join(SYSTEM_DRIVE, "ProgramData")
        if os.path.exists(programdata_path):
            data = collect_artifacts(programdata_path)
            artifacts['recent'].extend(data['recent'])
            artifacts['automatic'].extend(data['automatic'])
            artifacts['custom'].extend(data['custom'])
        
        # Scan Public folder
        public_path = os.path.join(USER_PROFILES_PATH, "Public")
        if os.path.exists(public_path):
            print(f"[Full Scan] Scanning Public folder...")
            data = collect_artifacts(public_path)
            artifacts['recent'].extend(data['recent'])
            artifacts['automatic'].extend(data['automatic'])
            artifacts['custom'].extend(data['custom'])
        
        # Scan Recycle Bin
        recycle_path = os.path.join(SYSTEM_DRIVE, "$Recycle.Bin")
        if os.path.exists(recycle_path):
            print(f"[Full Scan] Scanning Recycle Bin...")
            data = collect_artifacts(recycle_path)
            artifacts['recent'].extend(data['recent'])
            artifacts['automatic'].extend(data['automatic'])
            artifacts['custom'].extend(data['custom'])
        
        # Scan Windows directory (excluding system32 and other large folders)
        windows_path = os.path.join(SYSTEM_DRIVE, "Windows")
        if os.path.exists(windows_path):
            print(f"[Full Scan] Scanning Windows directory...")
            # Only scan specific subdirectories to avoid scanning entire Windows folder
            windows_subdirs = [
                os.path.join(windows_path, "System32", "config", "systemprofile"),
                os.path.join(windows_path, "ServiceProfiles"),
            ]
            for subdir in windows_subdirs:
                if os.path.exists(subdir):
                    data = collect_artifacts(subdir)
                    artifacts['recent'].extend(data['recent'])
                    artifacts['automatic'].extend(data['automatic'])
                    artifacts['custom'].extend(data['custom'])
        
        # Scan root of system drive (excluding large system folders)
        print(f"[Full Scan] Scanning system drive root...")
        try:
            for item in os.listdir(SYSTEM_DRIVE):
                item_path = os.path.join(SYSTEM_DRIVE, item)
                # Skip user profiles (already scanned), Windows, ProgramData, and system folders
                skip_folders = ['Users', 'Windows', 'ProgramData', '$Recycle.Bin', 'System Volume Information', 
                               'Recovery', 'PerfLogs', 'Program Files', 'Program Files (x86)']
                if os.path.isdir(item_path) and item not in skip_folders:
                    data = collect_artifacts(item_path)
                    artifacts['recent'].extend(data['recent'])
                    artifacts['automatic'].extend(data['automatic'])
                    artifacts['custom'].extend(data['custom'])
        except Exception as e:
            print(f"[Full Scan] Error scanning system drive root: {e}")
    else:
        # Legacy mode: Scan only known locations
        public_path = os.path.join(USER_PROFILES_PATH, "Public", "Desktop")
        public_data = collect_artifacts(public_path)
        artifacts['recent'].extend(public_data['recent'])
        
        recycle_path = os.path.join(SYSTEM_DRIVE, "$Recycle.Bin")
        recycle_data = collect_artifacts(recycle_path)
        artifacts['recent'].extend(recycle_data['recent'])
    
    return artifacts

def collect_forensic_artifacts(full_scan=True):
    """
    Collect LNK artifacts from the system.
    
    Args:
        full_scan: If True (default), scan entire system. If False, scan only known locations.
    """
    print("=== Windows LNK Forensic Collector ===")
    if full_scan:
        print("[Mode] Full System Scan - Scanning entire system for LNK files")
    else:
        print("[Mode] Quick Scan - Scanning only known locations")
    
    if not create_target_directories(): return
    users = get_user_profiles()
    stats = {'users_processed': 0, 'total_recent': 0, 'total_automatic': 0, 'total_custom': 0}
    
    for user in users:
        user_data = collect_user_artifacts(user, full_scan=full_scan)
        stats['users_processed'] += 1
        stats['total_recent'] += len(user_data['recent'])
        stats['total_automatic'] += len(user_data['automatic'])
        stats['total_custom'] += len(user_data['custom'])
        
    system_data = collect_system_artifacts(full_scan=full_scan)
    stats['total_recent'] += len(system_data['recent'])
    stats['total_automatic'] += len(system_data['automatic'])
    stats['total_custom'] += len(system_data['custom'])
    return stats

def A_CJL_LNK_Claw(case_path=None, offline_mode=False, direct_parse=True, full_scan=True, progress_callback=None):
    """
    Main LNK/JumpList collection and parsing function.
    
    Args:
        case_path: Path to case directory
        offline_mode: If True, parse files from case_path
        direct_parse: If True, parse live system artifacts directly
        full_scan: If True (default), scan entire system. If False, scan only known locations.
        progress_callback: Optional callback function(lnk_count, auto_count, custom_count, message) for progress updates
    """
    db_path = None
    try:
        update_target_directories(case_path)
        db_path = create_database(case_path)
        
        if direct_parse:
            # print("\n=== DIRECT PARSING MODE ===")  # Removed - shown in progress dialog
            # if full_scan:
            #     print("[Mode] Full System Scan - Scanning entire system for LNK files")
            # else:
            #     print("[Mode] Quick Scan - Scanning only known locations")
            
            users = get_user_profiles()
            all_unparsed_files = []
            stats = {'users_processed': 0, 'total_recent': 0, 'total_automatic': 0, 'total_custom': 0}
            
            for user in users:
                user_artifacts, user_unparsed = parse_user_artifacts_directly(user, db_path, full_scan=full_scan, progress_callback=progress_callback)
                all_unparsed_files.extend(user_unparsed)
                stats['users_processed'] += 1
                stats['total_recent'] += len(user_artifacts['recent'])
                stats['total_automatic'] += len(user_artifacts['automatic'])
                stats['total_custom'] += len(user_artifacts['custom'])
                
                # Update progress after each user
                if progress_callback:
                    progress_callback(stats['total_recent'], stats['total_automatic'], stats['total_custom'], f"Processing user: {user}")
            
            system_artifacts, system_unparsed = parse_system_artifacts_directly(db_path, full_scan=full_scan, progress_callback=progress_callback)
            all_unparsed_files.extend(system_unparsed)
            stats['total_recent'] += len(system_artifacts['recent'])
            stats['total_automatic'] += len(system_artifacts['automatic'])
            stats['total_custom'] += len(system_artifacts['custom'])
            
            # Final progress update
            if progress_callback:
                progress_callback(stats['total_recent'], stats['total_automatic'], stats['total_custom'], "Parsing completed")
            
            # print(f"\nParsed LNKs: {stats['total_recent']}, Auto JLs: {stats['total_automatic']}, Custom JLs: {stats['total_custom']}")  # Removed - shown in progress dialog
            total_records = sum([stats['total_recent'], stats['total_automatic'], stats['total_custom']])
            
        elif not offline_mode:
            print("\n=== NORMAL COLLECTION MODE ===")
            collection_stats = collect_forensic_artifacts(full_scan=full_scan)
            folder_path = TARGET_BASE_DIR
            unparsed_count = process_lnk_and_jump_list_files(folder_path, db_path, progress_callback=progress_callback)
            total_records = collection_stats['total_recent'] + collection_stats['total_automatic'] + collection_stats['total_custom'] if collection_stats else 0
            
        else:
            print("\n=== OFFLINE MODE ===")
            folder_path = os.path.join(case_path, "live_acquisition", "C_AJL_Lnk") if case_path else TARGET_BASE_DIR
            if not os.path.exists(folder_path): folder_path = TARGET_BASE_DIR
            unparsed_count = process_lnk_and_jump_list_files(folder_path, db_path, progress_callback=progress_callback)
            total_records = 1 # Approximation
            
    except KeyboardInterrupt:
        return {'success': False, 'records': 0, 'error': 'Collection aborted by user'}
    except Exception as e:
        traceback.print_exc()
        return {'success': False, 'records': 0, 'error': str(e)}

    # Suppress print when running from GUI (captured by loading dialog)
    # print(f"\033[92m\nParsing completed by Crow Eye\nDatabase saved to: {db_path}\033[0m")
    return {'success': True, 'records': total_records, 'output_path': db_path}

if __name__ == "__main__":
    # USER CONFIGURATION: Set specialized paths here instead of using command-line arguments
    CASE_PATH = r"C:\Users\Ghass\Downloads\test 1" 
    OFFLINE = True # Set to True to parse files in case_path\live_acquisition\C_AJL_Lnk
    DIRECT_PARSE = True # Set to True to parse live system artifacts directly
    
    A_CJL_LNK_Claw(case_path=CASE_PATH, offline_mode=OFFLINE, direct_parse=DIRECT_PARSE)

