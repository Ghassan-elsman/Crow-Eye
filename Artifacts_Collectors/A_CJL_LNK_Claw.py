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
        
        if filetime > 0:
            windows_epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
            # Use integer division to prevent float errors
            dt = windows_epoch + timedelta(microseconds=filetime // 10)
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

def safe_sqlite_int(value):
    try:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            value = int(value)
        return value if abs(value) <= 2**63-1 else None
    except (ValueError, TypeError):
        return None

# Parsers
def parse_DestList(data):
    if len(data) < 32: return []
    try:
        header = {
            'Version_Number': unpack_int(data[:4]),
            'Total_Current_Entries': unpack_int(data[4:8]),
            'Total_Pinned_Entries': unpack_int(data[8:12]),
            'Last_Issued_ID_Num': unpack_int(data[16:24]),
            'Number_of_Actions': unpack_int(data[24:32])
        }
    except Exception: return []

    entries = []
    offset = 32
    for _ in range(min(header['Total_Current_Entries'], 2000)): # Safety cap
        if offset >= len(data): break
        entry_data = data[offset:]
        
        # Version 1 (Win 7/8) usually 114 bytes fixed
        # Version 3/4 (Win 10/11) usually 128 bytes fixed
        is_modern = header['Version_Number'] in [3, 4]
        min_header = 128 if is_modern else 114
        
        if len(entry_data) < min_header: break
        
        try:
            entry = {
                'Checksum': hex(unpack_int(entry_data[0:8])),
                'New_Volume_ID': unpack_int(entry_data[8:24], 'uuid'),
                'New_Object_ID': unpack_int(entry_data[24:40], 'uuid'),
                'New_Object_ID_Timestamp': ad_timestamp(unpack_int(entry_data[24:32]), isObject=True),
                'New_Object_ID_MAC_Addr': unpack_int(entry_data[34:40], 'mac'),
                'Birth_Volume_ID': unpack_int(entry_data[40:56], 'uuid'),
                'Birth_Object_ID': unpack_int(entry_data[56:72], 'uuid'),
                'Birth_Object_ID_MAC_Addr': unpack_int(entry_data[66:72], 'mac'),
                'NetBIOS': unpack_int(entry_data[72:88], 'printable'),
                'Last_Recorded_Access': ad_timestamp(unpack_int(entry_data[100:108])),
                'Pin_Status_Counter': 'unpinned' if unpack_int(entry_data[108:112]) == 0xFFFFFFFF else str(unpack_int(entry_data[108:112]))
            }
            
            if is_modern:
                entry['Entry_ID_Number'] = str(unpack_int(entry_data[88:92]))
                entry['Access_Counter'] = unpack_int(entry_data[116:120])
                # String data starts at offset 128
                data_len = unpack_int(entry_data[128:130]) * 2
                entry['Data'] = unpack_int(entry_data[130:130+data_len], 'uni')
                offset += 128 + 2 + data_len + 4 # 128 fixed + 2 len + string + 4 trailing zero? Usually 128 + 2 + data_len is enough but some have 4 bytes extra
            else:
                entry['Entry_ID_Number'] = str(unpack_int(entry_data[88:96]))
                # Access counter is a float in Version 1
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
    elif type == 0x0040: # VT_FILETIME
        return ad_timestamp(unpack_int(v_body[:8]))
    elif v_type == 0x0003: # VT_I4
        return unpack_int(v_body[:4])
    elif v_type == 0x000B: # VT_BOOL
        return unpack_int(v_body[:2]) != 0
    return None

def parse_property_store(data):
    props = {}
    if len(data) < 8: return props
    
    # FORMATID GUIDs
    SHELL_PROPS = "{B725F130-47EF-101A-A5F1-02608C9EEBAC}"
    SUMMARY_PROPS = "{F29F85E0-4FF9-1068-AB91-08002B27B3D9}"
    DOC_PROPS = "{D5CDD502-2E9C-101B-9397-08002B2CF9AE}"
    
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
                    mapping = {2: "Author", 3: "Title", 4: "Subject", 12: "Created_Time"}
                    if prop_id in mapping: key = mapping[prop_id]
                elif format_id == SUMMARY_PROPS:
                    mapping = {2: "Label", 3: "Subject", 4: "Comments"}
                    if prop_id in mapping: key = mapping[prop_id]
                elif format_id == DOC_PROPS:
                    mapping = {2: "Category", 3: "Company", 4: "Manager"}
                    if prop_id in mapping: key = mapping[prop_id]
                
                props[key] = str(val)
                
            s_offset += prop_size
            
        offset += storage_size
    return props

class LnkStreamParser:
    def __init__(self, stream):
        self.stream = stream
        self.offset = 0
        self.parsed_data = {
            'MFT_Entry_Number': '',
            'MFT_Sequence_Number': '',
            'Property_Metadata': {},
            'Volume_Type': '',
            'Volume_Serial': '',
            'Volume_Label': '',
            'Command_Line_Arguments': '',
            'Darwin_ID': '',
            'Environment_Variables': '',
            'Known_Folder_GUID': ''
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

    def parse(self):
        if len(self.stream) < 76: return
        header_size = unpack_int(self.read(4))
        if header_size != 0x4C: return

        clsid = self.read(16)
        self.parsed_data['LNK_Class_ID'] = "{" + unpack_int(clsid, 'uuid') + "}"
        link_flags = unpack_int(self.read(4))
        file_attrs = unpack_int(self.read(4))
        ctime = unpack_int(self.read(8))
        atime = unpack_int(self.read(8))
        mtime = unpack_int(self.read(8))
        file_size = unpack_int(self.read(4))
        icon_index = struct.unpack('<i', self.read(4))[0]
        show_window = unpack_int(self.read(4))
        self.read(12) # HotKey(2) + Reserved1(2) + Reserved2(4) + Reserved3(4) = 12

        self.parsed_data['Time_Creation'] = ad_timestamp(ctime)
        self.parsed_data['Time_Access'] = ad_timestamp(atime)
        self.parsed_data['Time_Modification'] = ad_timestamp(mtime)
        self.parsed_data['FileSize'] = file_size
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
                        l_start = v_start + vol_label_offset
                        raw_label = self.stream[l_start:v_start+v_size].split(b'\0')[0]
                        self.parsed_data['Volume_Label'] = raw_label.decode('cp1252', errors='ignore')

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

        if has_name: self.parsed_data['Description'] = read_string()
        if has_rel_path: self.parsed_data['Relative_Path'] = read_string()
        if has_working_dir: self.parsed_data['Working_Directory'] = read_string()
        if has_arguments: self.parsed_data['Command_Line_Arguments'] = read_string()
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
                    self.read(64) # Skip droids
                    mac_bytes = self.stream[block_end-6:block_end]
                    if len(mac_bytes) == 6:
                        self.parsed_data['Tracker_MAC'] = "%02x:%02x:%02x:%02x:%02x:%02x" % struct.unpack("BBBBBB", mac_bytes)
                except Exception: pass
            elif signature == 0xA0000009: # Property Store
                try:
                    ps_data = self.stream[block_start+8:block_end]
                    self.parsed_data['Property_Metadata'] = parse_property_store(ps_data)
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
                except Exception: pass
                
            # Always jump to the definitive end of this block
            self.offset = block_end

    def parse_idlist(self, data):
        i_offset = 0
        while i_offset < len(data):
            item_size = unpack_int(data[i_offset:i_offset+2])
            if item_size == 0: break
            item_data = data[i_offset:i_offset+item_size]
            
            # Forensic Check: Search for 0xBEEF0004 extension block
            beef_idx = item_data.find(b'\x04\x00\xEF\xBE')
            if beef_idx != -1:
                # Found FileSystem extension! MFT Reference is at offset + 8
                mft_ref_data = item_data[beef_idx+8:beef_idx+16]
                if len(mft_ref_data) == 8:
                    val = unpack_int(mft_ref_data, 'int')
                    self.parsed_data['MFT_Entry_Number'] = str(val & 0xFFFFFFFFFFFF) # 48 bits index
                    self.parsed_data['MFT_Sequence_Number'] = str(val >> 48) # 16 bits sequence
            
            i_offset += item_size

def extract_artifacts_from_file(filepath, appids=None):
    if appids is None: appids = {}
    filename = os.path.basename(filepath)
    results = []
    
    clean_entry = {
        'LNK_Class_ID': '', 'Time_Creation': '', 'Time_Access': '', 'Time_Modification': '',
        'FileSize': '', 'IconIndex': '', 'Local_Path': '', 'Network_Share_Name': '',
        'Description': '', 'Relative_Path': '', 'Working_Directory': '', 'Command_Line_Arguments': '',
        'Icon_Location': '', 'Tracker_MAC': '', 'Tracker_NetBIOS': '',
        'AppID': '', 'AppType': '', 'AppDesc': '', 'Source_Name': filename, 'Source_Path': filepath,
        'entry_number': '', 'Artifact': ''
    }
    
    try:
        # 1. Automatic JumpLists
        if "automaticdestinations-ms" in filename.lower():
            appid_hex = filename.split('.')[0]
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
                    lnk_parser = LnkStreamParser(stream_data)
                    entry = clean_entry.copy()
                    entry.update(lnk_parser.parsed_data)
                    entry['Artifact'] = 'Automatic JumpList'
                    entry['AppID'] = appid_hex
                    entry['AppType'] = app_info[0]
                    entry['AppDesc'] = app_info[1]
                    entry['DestList_Last_ID'] = dest_header.get('Last_Issued_ID_Num', '')
                    entry['DestList_Actions_Count'] = dest_header.get('Number_of_Actions', '')
                    
                    try:
                        entry_id_int = str(int(ole_dir[0], 16))
                        entry['entry_number'] = entry_id_int
                        if entry_id_int in dest_dict:
                            dl_info = dest_dict[entry_id_int]
                            if dl_info.get('Last_Recorded_Access'): entry['Time_Access'] = dl_info['Last_Recorded_Access']
                            if dl_info.get('NetBIOS'): entry['Tracker_NetBIOS'] = dl_info['NetBIOS']
                            if dl_info.get('New_Object_ID_MAC_Addr'): entry['Tracker_MAC'] = dl_info['New_Object_ID_MAC_Addr']
                    except ValueError:
                        pass
                    results.append(entry)
                    
        # 2. Custom JumpLists
        elif "customdestinations-ms" in filename.lower():
            appid_hex = filename.split('.')[0]
            app_info = appids.get(appid_hex, ("Unknown", "Unknown"))
            try:
                with open(filepath, 'rb') as f:
                    data = f.read()
                
                # Custom JumpList signature for embedded LNK:
                # 0x4C, 0x00, 0x00, 0x00, 0x01, 0x14, 0x02, 0x00...
                magic = b'\x4C\x00\x00\x00\x01\x14\x02\x00\x00\x00\x00\x00\xC0\x00\x00\x00\x00\x00\x00\x46'
                
                p_offset = 0
                max_entries = 500
                entry_count = 0
                while p_offset < len(data) and entry_count < max_entries:
                    magic_idx = data.find(magic, p_offset)
                    if magic_idx == -1: break
                    
                    # Category mapping (4-byte header before MAGIC)
                    # Common values: 0x0 (Pinned), 0x1 (Recent), 0x2 (Frequent), 0x3 (Tasks)
                    category = "Unknown"
                    if magic_idx >= 4:
                        cat_header = unpack_int(data[magic_idx-4:magic_idx])
                        if cat_header == 0: category = "Pinned"
                        elif cat_header == 1: category = "Recent"
                        elif cat_header == 2: category = "Frequent"
                        elif cat_header == 3: category = "Tasks"

                    lnk_parser = LnkStreamParser(data[magic_idx:])
                    entry = clean_entry.copy()
                    entry.update(lnk_parser.parsed_data)
                    entry['Artifact'] = 'Custom JumpList'
                    entry['AppID'] = appid_hex
                    entry['AppType'] = app_info[0]
                    entry['AppDesc'] = app_info[1]
                    entry['Category'] = category
                    results.append(entry)
                    entry_count += 1
                    
                    # Ensure progress: skip ahead based on the parser offset
                    p_offset = magic_idx + (lnk_parser.offset if lnk_parser.offset > len(magic) else len(magic))
            except Exception: pass
                
        # 3. LNK Files
        elif filename.lower().endswith(".lnk"):
            with open(filepath, 'rb') as f:
                data = f.read()
            lnk_parser = LnkStreamParser(data)
            entry = clean_entry.copy()
            entry.update(lnk_parser.parsed_data)
            entry['Artifact'] = 'LNK_File'
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
        for entry in os.listdir(USER_PROFILES_PATH):
            user_path = os.path.join(USER_PROFILES_PATH, entry)
            if (os.path.isdir(user_path) and 
                entry not in ["Public", "Default", "Default User", "All Users"] and
                not entry.startswith('.')):
                users.append(entry)
        return users
    except Exception as e:
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

def categorize_files_by_type(folder_path):
    lnk_files, automatic_jump_lists, custom_jump_lists = [], [], []
    for root, _, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            art_type = detect_artifact(file_path)
            if art_type == "lnk": lnk_files.append(file_path)
            elif art_type == "Custom JumpList": custom_jump_lists.append(file_path)
            elif art_type == "Automatic JumpList": automatic_jump_lists.append(file_path)
    return lnk_files, automatic_jump_lists, custom_jump_lists

def create_database(case_path=None):
    db_path = 'LnkDB.db'
    if case_path:
        artifacts_dir = os.path.join(case_path, 'Target_Artifacts')
        if os.path.exists(artifacts_dir):
            db_path = os.path.join(artifacts_dir, 'LnkDB.db')
    
    with sqlite3.connect(db_path) as conn:
        C = conn.cursor()
        
        # Table 1: JLCE (Merged LNK and Automatic JumpList, Extended)
        # Matches Crow Eye.py header order (first 36 columns) for base compatibility.
        C.execute("""
        CREATE TABLE IF NOT EXISTS JLCE (
            -- Base 36 columns (Aligned with Crow Eye.py headers)
            Source_Name TEXT, Source_Path TEXT, Owner_UID INTEGER, Owner_GID INTEGER,
            Time_Access TEXT, Time_Creation TEXT, Time_Modification TEXT,
            AppType TEXT, AppID TEXT, Artifact TEXT, Data_Flags TEXT, 
            Local_Path TEXT, Common_Path TEXT, Location_Flags TEXT,
            Volume_Label TEXT, Local_Base_Path TEXT, Relative_Path TEXT, Working_Dir TEXT,
            Command_Line_Arguments TEXT, Icon_Location TEXT, Show_Window_Command TEXT,
            Hot_Key_Flags TEXT, Hot_Key_Value TEXT, File_Attributes_Flags TEXT,
            File_Size TEXT, Drive_Type TEXT, Drive_Serial_Number TEXT, Volume_Name TEXT,
            Network_Providers TEXT, Network_share_Flags TEXT, Network_Share_Name TEXT,
            Network_Share_Name_UNI TEXT, File_Permission TEXT,
            Num_Hard_Links INTEGER, Device_ID INTEGER, Inode_Number INTEGER,
            
            -- Extended Forensic Columns (Indices 36-47)
            Volume_Type_Ext TEXT, Volume_Serial_Ext TEXT, Volume_Label_Ext TEXT,
            Forensic_CLI_Args TEXT, MFT_Entry_Number TEXT, MFT_Sequence_Number TEXT,
            Property_Metadata TEXT, Darwin_ID TEXT, Environment_Variables TEXT,
            Known_Folder_GUID TEXT, DestList_Last_ID TEXT, DestList_Actions_Count INTEGER
        );
        """)
        
        # Table 2: Custom_JLCE (Custom JumpList table, Extended)
        # Matches Crow Eye.py Clj_table headers (first 14 columns).
        C.execute("""
        CREATE TABLE IF NOT EXISTS Custom_JLCE (
            -- Base 14 columns (Aligned with Clj_table headers)
            Source_Name TEXT, Source_Path TEXT, Owner_UID INTEGER, Owner_GID INTEGER,
            Time_Access TEXT, Time_Creation TEXT, Time_Modification TEXT,
            FileSize TEXT, File_Permissions TEXT, FileType TEXT,
            Num_Hard_Links INTEGER, Device_ID INTEGER, Inode_Number INTEGER, Artifact TEXT,
            
            -- Extended Forensic Columns
            Category TEXT, Local_Path_Ext TEXT, LNK_Class_ID_Ext TEXT,
            Volume_Type_Ext TEXT, Volume_Serial_Ext TEXT, Volume_Label_Ext TEXT,
            CLI_Arguments TEXT, MFT_Entry_Number TEXT, MFT_Sequence_Number TEXT,
            Property_Metadata TEXT, Darwin_ID TEXT, Environment_Variables TEXT,
            Known_Folder_GUID TEXT
        );
        """)
        
        conn.commit()
    return db_path

def insert_lnk_data_to_db(cursor, source_path, item, stat_info):
    try:
        cursor.execute("""
        INSERT INTO JLCE (
            -- Base 36
            Source_Name, Source_Path, Owner_UID, Owner_GID, 
            Time_Access, Time_Creation, Time_Modification, 
            AppType, AppID, Artifact, Data_Flags, 
            Local_Path, Common_Path, Location_Flags,
            Volume_Label, Local_Base_Path, Relative_Path, Working_Dir,
            Command_Line_Arguments, Icon_Location, Show_Window_Command,
            Hot_Key_Flags, Hot_Key_Value, File_Attributes_Flags,
            File_Size, Drive_Type, Drive_Serial_Number, Volume_Name,
            Network_Providers, Network_share_Flags, Network_Share_Name,
            Network_Share_Name_UNI, File_Permission,
            Num_Hard_Links, Device_ID, Inode_Number,
            
            -- Extensions
            Volume_Type_Ext, Volume_Serial_Ext, Volume_Label_Ext,
            Forensic_CLI_Args, MFT_Entry_Number, MFT_Sequence_Number,
            Property_Metadata, Darwin_ID, Environment_Variables,
            Known_Folder_GUID, DestList_Last_ID, DestList_Actions_Count
        )
        VALUES (
            :Source_Name, :Source_Path, :Owner_UID, :Owner_GID, 
            :Time_Access, :Time_Creation, :Time_Modification, 
            :AppType, :AppID, :Artifact, :Data_Flags, 
            :Local_Path, :Common_Path, :Location_Flags,
            :Volume_Label, :Local_Base_Path, :Relative_Path, :Working_Dir,
            :Command_Line_Arguments, :Icon_Location, :Show_Window_Command,
            :Hot_Key_Flags, :Hot_Key_Value, :File_Attributes_Flags,
            :File_Size, :Drive_Type, :Drive_Serial_Number, :Volume_Name,
            :Network_Providers, :Network_share_Flags, :Network_Share_Name,
            :Network_Share_Name_UNI, :File_Permission,
            :Num_Hard_Links, :Device_ID, :Inode_Number,
            
            :Volume_Type_Ext, :Volume_Serial_Ext, :Volume_Label_Ext,
            :Forensic_CLI_Args, :MFT_Entry_Number, :MFT_Sequence_Number,
            :Property_Metadata, :Darwin_ID, :Environment_Variables,
            :Known_Folder_GUID, :DestList_Last_ID, :DestList_Actions_Count
        )
        """, {
            "Source_Name": os.path.basename(source_path),
            "Source_Path": source_path,
            "Owner_UID": safe_sqlite_int(stat_info.st_uid),
            "Owner_GID": safe_sqlite_int(stat_info.st_gid),
            "Time_Access": format_time(item.get("Time_Access")),
            "Time_Creation": format_time(item.get("Time_Creation")),
            "Time_Modification": format_time(item.get("Time_Modification")),
            "AppType": item.get("AppType", ""),
            "AppID": item.get("AppID", ""),
            "Artifact": "lnk",
            "Data_Flags": item.get("Data_Flags", ""),
            "Local_Path": item.get("Local_Path", ""),
            "Common_Path": item.get("Common_Path", ""),
            "Location_Flags": item.get("Location_Flags", ""),
            "Volume_Label": item.get("Volume_Label", ""),
            "Local_Base_Path": item.get("Local_Base_Path", ""),
            "Relative_Path": item.get("Relative_Path", ""),
            "Working_Dir": item.get("Working_Directory", ""),
            "Command_Line_Arguments": item.get("Command_Line_Arguments", ""),
            "Icon_Location": item.get("Icon_Location", ""),
            "Show_Window_Command": item.get("ShowWindow", ""),
            "Hot_Key_Flags": item.get("Hot_Key_Flags", ""),
            "Hot_Key_Value": item.get("Hot_Key_Value", ""),
            "File_Attributes_Flags": item.get("File_Attributes", ""),
            "File_Size": item.get("FileSize", ""),
            "Drive_Type": item.get("Drive_Type", ""),
            "Drive_Serial_Number": item.get("Volume_Serial", ""),
            "Volume_Name": item.get("Volume_Label", ""),
            "Network_Providers": item.get("Network_Providers", ""),
            "Network_share_Flags": item.get("Network_Share_Flags", ""),
            "Network_Share_Name": item.get("Network_Share_Name", ""),
            "Network_Share_Name_UNI": item.get("Network_Share_Name_uni", ""),
            "File_Permission": oct(stat_info.st_mode),
            "Num_Hard_Links": safe_sqlite_int(stat_info.st_nlink),
            "Device_ID": safe_sqlite_int(stat_info.st_dev),
            "Inode_Number": safe_sqlite_int(stat_info.st_ino),
            
            "Volume_Type_Ext": item.get("Volume_Type", ""),
            "Volume_Serial_Ext": item.get("Volume_Serial", ""),
            "Volume_Label_Ext": item.get("Volume_Label", ""),
            "Forensic_CLI_Args": item.get("Command_Line_Arguments", ""),
            "MFT_Entry_Number": item.get("MFT_Entry_Number", ""),
            "MFT_Sequence_Number": item.get("MFT_Sequence_Number", ""),
            "Property_Metadata": json.dumps(item.get("Property_Metadata", {})),
            "Darwin_ID": item.get("Darwin_ID", ""),
            "Environment_Variables": item.get("Environment_Variables", ""),
            "Known_Folder_GUID": item.get("Known_Folder_GUID", ""),
            "DestList_Last_ID": item.get("DestList_Last_ID", ""),
            "DestList_Actions_Count": safe_sqlite_int(item.get("DestList_Actions_Count"))
        })
        return True
    except Exception as e:
        print(f"Error inserting LNK data: {e}")
        return False

def insert_automatic_jl_to_db(cursor, source_path, item, stat_info):
    try:
        cursor.execute("""
        INSERT INTO JLCE (
            -- Base 36
            Source_Name, Source_Path, Owner_UID, Owner_GID, 
            Time_Access, Time_Creation, Time_Modification, 
            AppType, AppID, Artifact, Data_Flags, 
            Local_Path, Common_Path, Location_Flags,
            Volume_Label, Local_Base_Path, Relative_Path, Working_Dir,
            Command_Line_Arguments, Icon_Location, Show_Window_Command,
            Hot_Key_Flags, Hot_Key_Value, File_Attributes_Flags,
            File_Size, Drive_Type, Drive_Serial_Number, Volume_Name,
            Network_Providers, Network_share_Flags, Network_Share_Name,
            Network_Share_Name_UNI, File_Permission,
            Num_Hard_Links, Device_ID, Inode_Number,
            
            -- Extensions
            Volume_Type_Ext, Volume_Serial_Ext, Volume_Label_Ext,
            Forensic_CLI_Args, MFT_Entry_Number, MFT_Sequence_Number,
            Property_Metadata, Darwin_ID, Environment_Variables,
            Known_Folder_GUID, DestList_Last_ID, DestList_Actions_Count
        )
        VALUES (
            :Source_Name, :Source_Path, :Owner_UID, :Owner_GID, 
            :Time_Access, :Time_Creation, :Time_Modification, 
            :AppType, :AppID, :Artifact, :Data_Flags, 
            :Local_Path, :Common_Path, :Location_Flags,
            :Volume_Label, :Local_Base_Path, :Relative_Path, :Working_Dir,
            :Command_Line_Arguments, :Icon_Location, :Show_Window_Command,
            :Hot_Key_Flags, :Hot_Key_Value, :File_Attributes_Flags,
            :File_Size, :Drive_Type, :Drive_Serial_Number, :Volume_Name,
            :Network_Providers, :Network_share_Flags, :Network_Share_Name,
            :Network_Share_Name_UNI, :File_Permission,
            :Num_Hard_Links, :Device_ID, :Inode_Number,
            
            :Volume_Type_Ext, :Volume_Serial_Ext, :Volume_Label_Ext,
            :Forensic_CLI_Args, :MFT_Entry_Number, :MFT_Sequence_Number,
            :Property_Metadata, :Darwin_ID, :Environment_Variables,
            :Known_Folder_GUID, :DestList_Last_ID, :DestList_Actions_Count
        )
        """, {
            "Source_Name": os.path.basename(source_path),
            "Source_Path": source_path,
            "Owner_UID": safe_sqlite_int(stat_info.st_uid),
            "Owner_GID": safe_sqlite_int(stat_info.st_gid),
            "Time_Access": format_time(item.get("Time_Access")),
            "Time_Creation": format_time(item.get("Time_Creation")),
            "Time_Modification": format_time(item.get("Time_Modification")),
            "AppType": item.get("AppType", ""),
            "AppID": item.get("AppID", ""),
            "Artifact": "Automatic JumpList",
            "Data_Flags": item.get("Data_Flags", ""),
            "Local_Path": item.get("Local_Path", ""),
            "Common_Path": item.get("Common_Path", ""),
            "Location_Flags": item.get("Location_Flags", ""),
            "Volume_Label": item.get("Volume_Label", ""),
            "Local_Base_Path": item.get("Local_Base_Path", ""),
            "Relative_Path": item.get("Relative_Path", ""),
            "Working_Dir": item.get("Working_Directory", ""),
            "Command_Line_Arguments": item.get("Command_Line_Arguments", ""),
            "Icon_Location": item.get("Icon_Location", ""),
            "Show_Window_Command": item.get("ShowWindow", ""),
            "Hot_Key_Flags": item.get("Hot_Key_Flags", ""),
            "Hot_Key_Value": item.get("Hot_Key_Value", ""),
            "File_Attributes_Flags": item.get("File_Attributes", ""),
            "File_Size": item.get("FileSize", ""),
            "Drive_Type": item.get("Drive_Type", ""),
            "Drive_Serial_Number": item.get("Volume_Serial", ""),
            "Volume_Name": item.get("Volume_Label", ""),
            "Network_Providers": item.get("Network_Providers", ""),
            "Network_share_Flags": item.get("Network_Share_Flags", ""),
            "Network_Share_Name": item.get("Network_Share_Name", ""),
            "Network_Share_Name_UNI": item.get("Network_Share_Name_uni", ""),
            "File_Permission": oct(stat_info.st_mode),
            "Num_Hard_Links": safe_sqlite_int(stat_info.st_nlink),
            "Device_ID": safe_sqlite_int(stat_info.st_dev),
            "Inode_Number": safe_sqlite_int(stat_info.st_ino),
            
            "Volume_Type_Ext": item.get("Volume_Type", ""),
            "Volume_Serial_Ext": item.get("Volume_Serial", ""),
            "Volume_Label_Ext": item.get("Volume_Label", ""),
            "Forensic_CLI_Args": item.get("Command_Line_Arguments", ""),
            "MFT_Entry_Number": item.get("MFT_Entry_Number", ""),
            "MFT_Sequence_Number": item.get("MFT_Sequence_Number", ""),
            "Property_Metadata": json.dumps(item.get("Property_Metadata", {})),
            "Darwin_ID": item.get("Darwin_ID", ""),
            "Environment_Variables": item.get("Environment_Variables", ""),
            "Known_Folder_GUID": item.get("Known_Folder_GUID", ""),
            "DestList_Last_ID": item.get("DestList_Last_ID", ""),
            "DestList_Actions_Count": safe_sqlite_int(item.get("DestList_Actions_Count"))
        })
        return True
    except Exception as e:
        print(f"Error inserting Automatic JumpList data into JLCE: {e}")
        return False

def insert_custom_jl_to_db(cursor, source_path, item, stat_info):
    try:
        cursor.execute("""
        INSERT INTO Custom_JLCE (
            Source_Name, Source_Path, Owner_UID, Owner_GID, 
            Time_Access, Time_Creation, Time_Modification, 
            FileSize, File_Permissions, FileType,
            Num_Hard_Links, Device_ID, Inode_Number, Artifact,
            
            Category, Local_Path_Ext, LNK_Class_ID_Ext,
            Volume_Type_Ext, Volume_Serial_Ext, Volume_Label_Ext,
            CLI_Arguments, MFT_Entry_Number, MFT_Sequence_Number,
            Property_Metadata, Darwin_ID, Environment_Variables,
            Known_Folder_GUID
        )
        VALUES (
            :Source_Name, :Source_Path, :Owner_UID, :Owner_GID, 
            :Time_Access, :Time_Creation, :Time_Modification, 
            :FileSize, :File_Permissions, :FileType,
            :Num_Hard_Links, :Device_ID, :Inode_Number, :Artifact,
            
            :Category, :Local_Path_Ext, :LNK_Class_ID_Ext,
            :Volume_Type_Ext, :Volume_Serial_Ext, :Volume_Label_Ext,
            :CLI_Arguments, :MFT_Entry_Number, :MFT_Sequence_Number,
            :Property_Metadata, :Darwin_ID, :Environment_Variables,
            :Known_Folder_GUID
        )
        """, {
            "Source_Name": os.path.basename(source_path),
            "Source_Path": source_path,
            "Owner_UID": safe_sqlite_int(stat_info.st_uid),
            "Owner_GID": safe_sqlite_int(stat_info.st_gid),
            "Time_Access": format_time(item.get("Time_Access")),
            "Time_Creation": format_time(item.get("Time_Creation")),
            "Time_Modification": format_time(item.get("Time_Modification")),
            "FileSize": item.get("FileSize", ""),
            "File_Permissions": oct(stat_info.st_mode),
            "FileType": "Custom DestList",
            "Num_Hard_Links": safe_sqlite_int(stat_info.st_nlink),
            "Device_ID": safe_sqlite_int(stat_info.st_dev),
            "Inode_Number": safe_sqlite_int(stat_info.st_ino),
            "Artifact": "Custom JumpList",
            
            "Category": item.get("Category", "Unknown"),
            "Local_Path_Ext": item.get("Local_Path", ""),
            "LNK_Class_ID_Ext": item.get("LNK_Class_ID", ""),
            "Volume_Type_Ext": item.get("Volume_Type", ""),
            "Volume_Serial_Ext": item.get("Volume_Serial", ""),
            "Volume_Label_Ext": item.get("Volume_Label", ""),
            "CLI_Arguments": item.get("Command_Line_Arguments", ""),
            "MFT_Entry_Number": item.get("MFT_Entry_Number", ""),
            "MFT_Sequence_Number": item.get("MFT_Sequence_Number", ""),
            "Property_Metadata": json.dumps(item.get("Property_Metadata", {})),
            "Darwin_ID": item.get("Darwin_ID", ""),
            "Environment_Variables": item.get("Environment_Variables", ""),
            "Known_Folder_GUID": item.get("Known_Folder_GUID", "")
        })
        return True
    except Exception as e:
        print(f"Error inserting Custom JumpList data into Custom_JLCE: {e}")
        return False

def parse_artifacts_directly(source_path, db_path, user=None):
    artifacts = {'recent': [], 'automatic': [], 'custom': []}
    unparsed_files = []
    
    if not os.path.exists(source_path):
        return artifacts, unparsed_files
        
    try:
        appids = read_AppId(appid_path)
        with sqlite3.connect(db_path) as conn:
            C = conn.cursor()
            lnk_files, automatic_jump_lists, custom_jump_lists = categorize_files_by_type(source_path)
            
            for file in lnk_files + automatic_jump_lists + custom_jump_lists:
                artifact_type = detect_artifact(file)
                if not artifact_type: continue
                dir_key = 'recent' if artifact_type == 'lnk' else 'automatic' if 'Automatic' in artifact_type else 'custom'
                
                try:
                    stat_info = os.stat(file)
                    items = extract_artifacts_from_file(file, appids)
                    if not items:
                        unparsed_files.append(file)
                    else:
                        for item in items:
                            inserted = False
                            if dir_key == 'recent':
                                inserted = insert_lnk_data_to_db(C, file, item, stat_info)
                            elif dir_key == 'automatic':
                                inserted = insert_automatic_jl_to_db(C, file, item, stat_info)
                            elif dir_key == 'custom':
                                inserted = insert_custom_jl_to_db(C, file, item, stat_info)
                                
                            if inserted:
                                artifacts[dir_key].append(file)
                            else:
                                unparsed_files.append(file)
                                
                except Exception:
                    unparsed_files.append(file)
            conn.commit()
    except Exception as e:
        print(f" [!] Error scanning {source_path}: {e}")
    
    return artifacts, unparsed_files

def parse_user_artifacts_directly(user, db_path):
    print(f"\n=== Parsing artifacts for user: {user} ===")
    artifacts = {'recent': [], 'automatic': [], 'custom': []}
    unparsed_files = []
    
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
            data, unparsed = parse_artifacts_directly(path, db_path, user)
            artifacts['recent'].extend(data['recent'])
            artifacts['automatic'].extend(data['automatic'])
            artifacts['custom'].extend(data['custom'])
            unparsed_files.extend(unparsed)
            
    return artifacts, unparsed_files

def parse_system_artifacts_directly(db_path):
    artifacts = {'recent': [], 'automatic': [], 'custom': []}
    unparsed_files = []
    
    public_desktop_path = os.path.join(SYSTEM_DRIVE, "Users", "Public", "Desktop")
    data, unparsed = parse_artifacts_directly(public_desktop_path, db_path, "Public")
    artifacts['recent'].extend(data['recent'])
    unparsed_files.extend(unparsed)
    
    recycle_bin_path = os.path.join(SYSTEM_DRIVE, "$Recycle.Bin")
    if os.path.exists(recycle_bin_path):
        for sid_folder in os.listdir(recycle_bin_path):
            sid_path = os.path.join(recycle_bin_path, sid_folder)
            if os.path.isdir(sid_path):
                data, unparsed = parse_artifacts_directly(sid_path, db_path, f"RecycleBin_{sid_folder}")
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
    unparsed_files = []
    lnk_files, automatic_jump_lists, custom_jump_lists = categorize_files_by_type(folder_path)
    
    with sqlite3.connect(db_path) as conn:
        C = conn.cursor()
        for file in lnk_files + automatic_jump_lists + custom_jump_lists:
            artifact_type = detect_artifact(file)
            try:
                stat_info = os.stat(file)
                items = extract_artifacts_from_file(file, appids)
                if not items:
                    unparsed_files.append(file)
                else:
                    for item in items:
                        dir_key = 'recent' if artifact_type == 'lnk' else 'automatic' if 'Automatic' in artifact_type else 'custom'
                        inserted = False
                        if dir_key == 'recent':
                            inserted = insert_lnk_data_to_db(C, file, item, stat_info)
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

def collect_user_artifacts(user):
    artifacts = {'recent': [], 'automatic': [], 'custom': []}
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

def collect_system_artifacts():
    artifacts = {'recent': [], 'automatic': [], 'custom': []}
    public_path = os.path.join(USER_PROFILES_PATH, "Public", "Desktop")
    public_data = collect_artifacts(public_path)
    artifacts['recent'].extend(public_data['recent'])
    
    recycle_path = os.path.join(SYSTEM_DRIVE, "$Recycle.Bin")
    recycle_data = collect_artifacts(recycle_path)
    artifacts['recent'].extend(recycle_data['recent'])
    
    return artifacts

def collect_forensic_artifacts():
    print("=== Windows LNK Forensic Collector ===")
    if not create_target_directories(): return
    users = get_user_profiles()
    stats = {'users_processed': 0, 'total_recent': 0, 'total_automatic': 0, 'total_custom': 0}
    
    for user in users:
        user_data = collect_user_artifacts(user)
        stats['users_processed'] += 1
        stats['total_recent'] += len(user_data['recent'])
        stats['total_automatic'] += len(user_data['automatic'])
        stats['total_custom'] += len(user_data['custom'])
        
    system_data = collect_system_artifacts()
    stats['total_recent'] += len(system_data['recent'])
    stats['total_automatic'] += len(system_data['automatic'])
    stats['total_custom'] += len(system_data['custom'])
    return stats

def A_CJL_LNK_Claw(case_path=None, offline_mode=False, direct_parse=True):
    db_path = None
    try:
        update_target_directories(case_path)
        db_path = create_database(case_path)
        
        if direct_parse:
            print("\n=== DIRECT PARSING MODE ===")
            users = get_user_profiles()
            all_unparsed_files = []
            stats = {'users_processed': 0, 'total_recent': 0, 'total_automatic': 0, 'total_custom': 0}
            
            for user in users:
                user_artifacts, user_unparsed = parse_user_artifacts_directly(user, db_path)
                all_unparsed_files.extend(user_unparsed)
                stats['users_processed'] += 1
                stats['total_recent'] += len(user_artifacts['recent'])
                stats['total_automatic'] += len(user_artifacts['automatic'])
                stats['total_custom'] += len(user_artifacts['custom'])
            
            system_artifacts, system_unparsed = parse_system_artifacts_directly(db_path)
            all_unparsed_files.extend(system_unparsed)
            stats['total_recent'] += len(system_artifacts['recent'])
            stats['total_automatic'] += len(system_artifacts['automatic'])
            stats['total_custom'] += len(system_artifacts['custom'])
            
            print(f"\nParsed LNKs: {stats['total_recent']}, Auto JLs: {stats['total_automatic']}, Custom JLs: {stats['total_custom']}")
            total_records = sum([stats['total_recent'], stats['total_automatic'], stats['total_custom']])
            
        elif not offline_mode:
            print("\n=== NORMAL COLLECTION MODE ===")
            collection_stats = collect_forensic_artifacts()
            folder_path = TARGET_BASE_DIR
            unparsed_count = process_lnk_and_jump_list_files(folder_path, db_path)
            total_records = collection_stats['total_recent'] + collection_stats['total_automatic'] + collection_stats['total_custom'] if collection_stats else 0
            
        else:
            print("\n=== OFFLINE MODE ===")
            folder_path = os.path.join(case_path, "live_acquisition", "C_AJL_Lnk") if case_path else TARGET_BASE_DIR
            if not os.path.exists(folder_path): folder_path = TARGET_BASE_DIR
            unparsed_count = process_lnk_and_jump_list_files(folder_path, db_path)
            total_records = 1 # Approximation
            
    except KeyboardInterrupt:
        return {'success': False, 'records': 0, 'error': 'Collection aborted by user'}
    except Exception as e:
        traceback.print_exc()
        return {'success': False, 'records': 0, 'error': str(e)}

    print(f"\033[92m\nParsing completed by Crow Eye\nDatabase saved to: {db_path}\033[0m")
    return {'success': True, 'records': total_records, 'output_path': db_path}

if __name__ == "__main__":
    # USER CONFIGURATION: Set specialized paths here instead of using command-line arguments
    CASE_PATH = r"C:\Users\Ghass\Downloads\test 1" 
    OFFLINE = True # Set to True to parse files in case_path\live_acquisition\C_AJL_Lnk
    DIRECT_PARSE = True # Set to True to parse live system artifacts directly
    
    A_CJL_LNK_Claw(case_path=CASE_PATH, offline_mode=OFFLINE, direct_parse=DIRECT_PARSE)

