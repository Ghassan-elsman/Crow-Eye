import os
import sqlite3
import struct
import json
from datetime import datetime, timedelta

def prefetch_claw(case_path=None, offline_mode=False):
    
    
    def format_size(size):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024

    def filetime_to_dt(ft):
        if ft == 0:
            return None
        return datetime(1601, 1, 1) + timedelta(microseconds=ft/10)

    def calculate_prefetch_hash(executable_name):
        try:
            executable_name = executable_name.upper().encode('utf-16le')
            hash_value = 0
            for byte in executable_name:
                hash_value = (37 * hash_value + byte) & 0xFFFFFFFF
            return hash_value
        except:
            return 0

    def safe_int_convert(value, max_value=9223372036854775807):
        """Safely convert integers for SQLite storage, avoiding overflow errors"""
        try:
            if isinstance(value, int):
                if value > max_value or value < -max_value:
                    return str(value)  # Store as TEXT if too large
                return value
            return value
        except:
            return 0

    def parse_prefetch_file(filepath):
        try:
            with open(filepath, 'rb') as f:
                data = f.read()
                
                if len(data) < 0x100:
                    print(f"File too small: {filepath}")
                    return None
                
                file_stat = os.stat(filepath)
                signature = data[:4]
                
                # Handle different prefetch formats
                if signature == b'MAM\x04':  # Windows 10/11
                    version = 30
                    name_offset = 0x10
                    name_length = 0x14
                    metrics_offset = 0x64
                    file_hash_offset = 0x4C
                    vol_offset = 0x68
                elif signature == b'MAM\x00':  # Older Windows
                    version = struct.unpack_from('<I', data, 4)[0]
                    name_offset = 0x10
                    name_length = 0x14
                    metrics_offset = 0x64
                    file_hash_offset = 0x4C
                    vol_offset = 0x68
                elif signature == b'SCCA':  # Windows 8
                    version = struct.unpack_from('<I', data, 4)[0]
                    name_offset = 0x10
                    name_length = 0x14
                    metrics_offset = 0x64
                    file_hash_offset = 0x4C
                    vol_offset = 0x68
                else:
                    print(f"Unsupported prefetch format in {filepath}: {signature}")
                    return None
                
                # Get executable name
                filename = os.path.basename(filepath)
                if '-' in filename:
                    fallback_name = filename.split('-')[0]
                else:
                    fallback_name = filename.replace('.pf', '')
                
                try:
                    name_offset_val = struct.unpack_from('<I', data, name_offset)[0]
                    name_length_val = struct.unpack_from('<I', data, name_length)[0]
                    
                    if (name_offset_val + name_length_val * 2) > len(data) or name_length_val == 0:
                        executable_name = fallback_name
                    else:
                        executable_name = data[name_offset_val:name_offset_val+name_length_val*2].decode('utf-16le', errors='replace').rstrip('\x00')
                except:
                    executable_name = fallback_name
                
                try:
                    metrics_offset_val = struct.unpack_from('<I', data, metrics_offset)[0]
                    file_hash = struct.unpack_from('<I', data, file_hash_offset)[0]
                except:
                    metrics_offset_val = 0
                    file_hash = 0
                
                # Parse execution metrics
                run_count = 0
                last_run_times = []
                duration_info = {'total_ms': 0, 'last_ms': 0}
                
                if metrics_offset_val + 0x30 < len(data):
                    try:
                        run_count = struct.unpack_from('<I', data, metrics_offset_val + 4)[0]
                        
                        time_offset = metrics_offset_val + 8
                        for _ in range(8):
                            try:
                                ft = struct.unpack_from('<Q', data, time_offset)[0]
                                dt = filetime_to_dt(ft)
                                if dt:
                                    last_run_times.append(dt.strftime('%Y-%m-%d %H:%M:%S'))
                            except:
                                pass
                            time_offset += 8
                        
                        duration_info = {
                            'total_ms': struct.unpack_from('<I', data, metrics_offset_val + 0x20)[0] if metrics_offset_val + 0x20 < len(data) else 0,
                            'last_ms': struct.unpack_from('<I', data, metrics_offset_val + 0x24)[0] if metrics_offset_val + 0x24 < len(data) else 0
                        }
                    except:
                        pass

                # =============================================
                # Enhanced Volume Information Parsing
                # =============================================
                volume_info = []
                volume_serial_numbers = set()
                
                try:
                    for vol_entry in range(4):  # Typically 4 volume entries in prefetch
                        try:
                            entry_offset = struct.unpack_from('<I', data, vol_offset)[0]
                            if entry_offset == 0:
                                vol_offset += 4
                                continue
                            
                            if entry_offset + 20 > len(data):
                                vol_offset += 4
                                continue
                                
                            # Extract volume metadata
                            vol_creation = struct.unpack_from('<Q', data, entry_offset)[0]
                            vol_serial = struct.unpack_from('<I', data, entry_offset + 8)[0]
                            vol_path_len = struct.unpack_from('<I', data, entry_offset + 12)[0]
                            
                            # Skip if we can't read the full path
                            if entry_offset + 16 + vol_path_len*2 > len(data):
                                vol_offset += 4
                                continue
                                
                            # Extract volume path
                            vol_path = data[entry_offset+16:entry_offset+16+vol_path_len*2].decode('utf-16le', errors='replace').rstrip('\x00')
                            
                            # Determine volume type and name
                            if vol_path.startswith('\\'):
                                vol_type = 'Network'
                                vol_name = vol_path.split('\\')[2] if len(vol_path.split('\\')) > 2 else vol_path
                            else:
                                vol_type = 'Local'
                                vol_name = os.path.splitdrive(vol_path)[0]
                            
                            # Skip duplicate volumes (same serial number)
                            if vol_serial in volume_serial_numbers:
                                vol_offset += 4
                                continue
                                
                            volume_serial_numbers.add(vol_serial)
                            
                            # Create detailed volume entry
                            volume_entry = {
                                'creation_time': filetime_to_dt(vol_creation).strftime('%Y-%m-%d %H:%M:%S') if vol_creation else None,
                                'serial_number': f"{vol_serial:08X}",
                                'serial_decimal': vol_serial,
                                'path': vol_path,
                                'type': vol_type,
                                'name': vol_name,
                                'device_type': None,
                                'suspicious': False,
                                'flags': []
                            }
                            
                            # Determine device type for local volumes
                            if vol_type == 'Local':
                                if vol_name.lower() == 'c:':
                                    volume_entry['device_type'] = 'System'
                                elif any(vol_name.lower().startswith(d) for d in ['a:', 'b:']):
                                    volume_entry['device_type'] = 'Floppy'
                                elif any(vol_name.lower().startswith(d) for d in ['d:', 'e:', 'f:']):
                                    volume_entry['device_type'] = 'Optical'
                                else:
                                    volume_entry['device_type'] = 'Storage'
                            
                            # Check for suspicious volume characteristics
                            if vol_type == 'Network':
                                if any(s in vol_path.lower() for s in ['temp', 'tmp', 'share']):
                                    volume_entry['flags'].append('suspicious_network_share')
                                    volume_entry['suspicious'] = True
                            
                            if vol_serial == 0:
                                volume_entry['flags'].append('null_serial_number')
                                volume_entry['suspicious'] = True
                            
                            if not vol_creation:
                                volume_entry['flags'].append('missing_creation_time')
                            
                            volume_info.append(volume_entry)
                            
                        except Exception as e:
                            print(f"Error parsing volume entry {vol_entry}: {str(e)}")
                        finally:
                            vol_offset += 4
                            
                except Exception as e:
                    print(f"Error during volume parsing: {str(e)}")

                # =============================================
                # Enhanced File References Parsing
                # =============================================
                all_file_references = []
                suspicious_files = []
                dll_loading = []
                directory_stats = {}

                # Define detection criteria
                SUSPICIOUS = {
                    'extensions': {'.dll', '.exe', '.vbs', '.ps1', '.js', '.bat', '.cmd', '.scr', '.jar', '.msi', '.com'},
                    'path_terms': {
                        'temp': ['temp', 'tmp', 'cache', '\\~'],
                        'appdata': ['appdata', 'localappdata', 'roaming'],
                        'system': ['system32', 'syswow64', 'drivers\\'],
                        'unusual': ['$recycle.bin', 'programdata', 'downloads', 'public\\']
                    },
                    'name_indicators': {
                        'spaces': [' '],
                        'special_chars': ['$', '@', '!', '#', '%'],
                        'patterns': ['update', 'install', 'patch']
                    }
                }

                try:
                    file_refs_offset_pos = metrics_offset_val + 0x48
                    if file_refs_offset_pos + 8 < len(data):
                        file_refs_offset = struct.unpack_from('<I', data, file_refs_offset_pos)[0]
                        file_refs_count = struct.unpack_from('<I', data, file_refs_offset_pos + 4)[0]
                        
                        if file_refs_offset > 0 and file_refs_count > 0:
                            for i in range(min(file_refs_count, 1000)):  # Safety limit
                                try:
                                    entry_offset = file_refs_offset + (i * 12)
                                    if entry_offset + 8 > len(data):
                                        continue
                                        
                                    filename_offset = struct.unpack_from('<I', data, entry_offset + 4)[0]
                                    if filename_offset + 4 > len(data):
                                        continue
                                    
                                    filename_len = struct.unpack_from('<I', data, filename_offset)[0]
                                    if filename_offset + 4 + filename_len*2 > len(data):
                                        continue
                                        
                                    filename = data[filename_offset+4:filename_offset+4+filename_len*2].decode('utf-16le', errors='replace').rstrip('\x00')
                                    
                                    # Create base file entry
                                    file_entry = {
                                        'path': filename,
                                        'name': os.path.basename(filename),
                                        'directory': os.path.dirname(filename),
                                        'extension': os.path.splitext(filename)[1].lower(),
                                        'order': i+1,
                                        'suspicious': False,
                                        'flags': []
                                    }

                                    # Check for suspicious indicators
                                    # 1. Extension check
                                    if file_entry['extension'] in SUSPICIOUS['extensions']:
                                        file_entry['flags'].append(f"suspicious_extension:{file_entry['extension']}")
                                    
                                    # 2. Path check
                                    lower_path = filename.lower()
                                    for category, terms in SUSPICIOUS['path_terms'].items():
                                        for term in terms:
                                            if term in lower_path:
                                                file_entry['flags'].append(f"suspicious_path:{category}:{term}")
                                                break
                                    
                                    # 3. Filename check
                                    lower_name = file_entry['name'].lower()
                                    # Check for special characters
                                    for char in SUSPICIOUS['name_indicators']['special_chars']:
                                        if char in file_entry['name']:
                                            file_entry['flags'].append(f"suspicious_char:{char}")
                                            break
                                    
                                    # Check for spaces
                                    if ' ' in file_entry['name']:
                                        file_entry['flags'].append("suspicious_space_in_name")
                                    
                                    # Check for long names
                                    if len(file_entry['name']) > 50:
                                        file_entry['flags'].append("suspicious_long_name")
                                    
                                    # Check for suspicious patterns
                                    for pattern in SUSPICIOUS['name_indicators']['patterns']:
                                        if pattern in lower_name:
                                            file_entry['flags'].append(f"suspicious_pattern:{pattern}")
                                    
                                    # Mark as suspicious if any flags were raised
                                    if file_entry['flags']:
                                        file_entry['suspicious'] = True
                                        suspicious_files.append(file_entry.copy())
                                    
                                    # Track all files
                                    all_file_references.append(file_entry)
                                    
                                    # Track DLLs separately
                                    if file_entry['extension'] == '.dll':
                                        dll_entry = file_entry.copy()
                                        dll_entry['load_order'] = len(dll_loading) + 1
                                        dll_loading.append(dll_entry)
                                        
                                    # Update directory stats
                                    dirname = file_entry['directory']
                                    if dirname in directory_stats:
                                        directory_stats[dirname]['count'] += 1
                                        if file_entry['suspicious']:
                                            directory_stats[dirname]['suspicious_count'] += 1
                                    else:
                                        directory_stats[dirname] = {
                                            'count': 1,
                                            'suspicious_count': 1 if file_entry['suspicious'] else 0
                                        }
                                        
                                except Exception as e:
                                    print(f"Error processing file reference {i}: {str(e)}")
                                    continue
                except Exception as e:
                    print(f"Error parsing file references: {str(e)}")
                
                # Prepare directory analysis
                directory_analysis = []
                for dirname, stats in directory_stats.items():
                    dir_analysis = {
                        'path': dirname,
                        'total_files': stats['count'],
                        'suspicious_files': stats['suspicious_count'],
                        'suspicious_ratio': (stats['suspicious_count'] / stats['count']) * 100 if stats['count'] > 0 else 0
                    }
                    directory_analysis.append(dir_analysis)
                
                # Sort directories by suspicious ratio
                directory_analysis.sort(key=lambda x: x['suspicious_ratio'], reverse=True)

                # Add forensic flags
                forensic_flags = {
                    'high_run_count': run_count > 100,
                    'temp_files': any(('temp' in f['path'].lower() or 'tmp' in f['path'].lower()) for f in all_file_references),
                    'scripts_loaded': any(f['extension'] in {'.vbs', '.ps1', '.js', '.bat', '.cmd'} for f in all_file_references),
                    'suspicious_paths': any(('appdata' in f['path'].lower() or 'temp' in f['path'].lower()) for f in all_file_references),
                    'unusual_name': ' ' in executable_name or len(executable_name) > 50,
                    'multiple_volumes': len(volume_serial_numbers) > 1,
                    'network_volumes': any(v['type'] == 'Network' for v in volume_info),
                    'suspicious_volumes': any(v['suspicious'] for v in volume_info)
                }
                
                # Prepare metadata fields with safe integer conversion
                metadata = {
                    'size': format_size(file_stat.st_size),
                    'modified': datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    'created': datetime.fromtimestamp(file_stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S'),
                    'accessed': datetime.fromtimestamp(file_stat.st_atime).strftime('%Y-%m-%d %H:%M:%S'),
                    'mode': oct(file_stat.st_mode),
                    'inode': safe_int_convert(file_stat.st_ino),
                    'device': safe_int_convert(file_stat.st_dev),
                    'nlink': safe_int_convert(file_stat.st_nlink),
                    'uid': safe_int_convert(file_stat.st_uid),
                    'gid': safe_int_convert(file_stat.st_gid)
                }
                
                # Prepare execution info fields
                execution_info = {
                    'count': run_count,
                    'last_runs': json.dumps(last_run_times),
                    'durations_total_ms': duration_info['total_ms'],
                    'durations_last_ms': duration_info['last_ms'],
                    'calculated_hash': hex(calculate_prefetch_hash(executable_name)),
                    'stored_hash': hex(file_hash),
                    'hash_match': calculate_prefetch_hash(executable_name) == file_hash
                }
                
                return {
                    'executable': executable_name,
                    'filepath': filepath,
                    'version': version,
                    'metadata': metadata,
                    'execution_info': execution_info,
                    'volumes': {
                        'all': volume_info,
                        'suspicious': [v for v in volume_info if v['suspicious']],
                        'stats': {
                            'total': len(volume_info),
                            'local': len([v for v in volume_info if v['type'] == 'Local']),
                            'network': len([v for v in volume_info if v['type'] == 'Network']),
                            'suspicious': len([v for v in volume_info if v['suspicious']])
                        }
                    },
                    'files': {
                        'all_references': all_file_references,
                        'suspicious_references': suspicious_files,
                        'dll_loading_order': dll_loading,
                        'directory_analysis': directory_analysis,
                        'stats': {
                            'total_files': len(all_file_references),
                            'suspicious_files': len(suspicious_files),
                            'suspicious_ratio': (len(suspicious_files) / len(all_file_references)) * 100 if all_file_references else 0,
                            'dll_count': len(dll_loading)
                        }
                    },
                    'forensic_flags': forensic_flags
                }
                
        except Exception as e:
            print(f"Error processing {filepath}: {str(e)}")
            return None

    try:
        # Set the database path based on case_path if provided
        db_path = 'prefetch.db'  # Default path
        if case_path:
            # If a case path is provided, use it for the database
            artifacts_dir = os.path.join(case_path, 'Target_Artifacts')
            if not os.path.exists(artifacts_dir):
                os.makedirs(artifacts_dir, exist_ok=True)
            db_path = os.path.join(artifacts_dir, 'prefetch.db')
            print(f"Using case path for database: {db_path}")
            
        # Initialize database
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        
        # Process prefetch files
        if offline_mode and case_path:
            # Use the prefetch directory from the case path for offline analysis
            prefetch_dir = os.path.join(case_path, 'Target_Artifacts', 'Prefetch')
            print(f"Offline mode: Using prefetch files from {prefetch_dir}")
        else:
            # Use the local Windows prefetch directory
            prefetch_dir = 'C:\\Windows\\Prefetch'
        
        # Create table with enhanced schema - Updated column types to handle large integers
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS prefetch_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                executable TEXT NOT NULL, 
                filepath TEXT UNIQUE NOT NULL,
                version INTEGER,
                
                -- Metadata columns (changed problematic INTEGER columns to TEXT for large values)
                size TEXT,
                modified TEXT,
                created TEXT,
                accessed TEXT,
                mode TEXT,
                inode_number TEXT,  -- Changed from INTEGER to TEXT
                device TEXT,        -- Changed from INTEGER to TEXT  
                nlink TEXT,         -- Changed from INTEGER to TEXT
                uid TEXT,           -- Changed from INTEGER to TEXT
                gid TEXT,           -- Changed from INTEGER to TEXT
                
                -- Execution info columns
                run_count INTEGER,
                last_runs TEXT,
                durations_total_ms INTEGER,
                durations_last_ms INTEGER,
                calculated_hash TEXT,
                stored_hash TEXT,
                hash_match INTEGER,
                
                -- Volume data (as JSON)
                volume_info TEXT,
                suspicious_volumes TEXT,
                volume_stats TEXT,
                
                -- File reference data (as JSON)
                all_file_references TEXT,
                suspicious_files TEXT,
                dll_loading TEXT,
                directory_stats TEXT,
                file_stats TEXT,
                
                -- Forensic flags
                forensic_flags TEXT,
                processed_time TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Process prefetch files
        if not os.path.exists(prefetch_dir):
            print(f"Prefetch directory not found: {prefetch_dir}")
            return
            
        files = [f for f in os.listdir(prefetch_dir) if f.endswith('.pf')]
        total_files = len(files)
        processed_count = 0
        inserted_count = 0
        failed_files = []

        for filename in files:
            filepath = os.path.join(prefetch_dir, filename)
            data = parse_prefetch_file(filepath)
            
            if data:
                try:
                    cursor.execute('''
                        INSERT OR IGNORE INTO prefetch_data (
                            executable, filepath, version,
                            size, modified, created, accessed, mode, inode_number, device, nlink, uid, gid,
                            run_count, last_runs, durations_total_ms, durations_last_ms, calculated_hash, stored_hash, hash_match,
                            volume_info, suspicious_volumes, volume_stats,
                            all_file_references, suspicious_files, dll_loading, directory_stats, file_stats,
                            forensic_flags, processed_time
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        data['executable'],
                        data['filepath'],
                        data['version'],

                        # Metadata (now safely converted)
                        data['metadata']['size'],
                        data['metadata']['modified'],
                        data['metadata']['created'],
                        data['metadata']['accessed'],
                        data['metadata']['mode'],
                        str(data['metadata']['inode']),    # Convert to string
                        str(data['metadata']['device']),   # Convert to string
                        str(data['metadata']['nlink']),    # Convert to string
                        str(data['metadata']['uid']),      # Convert to string
                        str(data['metadata']['gid']),      # Convert to string

                        # Execution info
                        data['execution_info']['count'],
                        data['execution_info']['last_runs'],
                        data['execution_info']['durations_total_ms'],
                        data['execution_info']['durations_last_ms'],
                        data['execution_info']['calculated_hash'],
                        data['execution_info']['stored_hash'],
                        int(data['execution_info']['hash_match']),

                        # Volume data
                        json.dumps(data['volumes']['all']),
                        json.dumps(data['volumes']['suspicious']),
                        json.dumps(data['volumes']['stats']),

                        # File reference data
                        json.dumps(data['files']['all_references']),
                        json.dumps(data['files']['suspicious_references']),
                        json.dumps(data['files']['dll_loading_order']),
                        json.dumps(data['files']['directory_analysis']),
                        json.dumps(data['files']['stats']),

                        # Forensic flags
                        json.dumps(data['forensic_flags']),

                        # Explicit processed_time value
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    ))
                    if cursor.rowcount > 0:
                        inserted_count += 1
                    conn.commit()
                except sqlite3.Error as e:
                    print(f"Database error for {filename}: {str(e)}")
                    conn.rollback()
                    failed_files.append(filename)
            else:
                failed_files.append(filename)

            processed_count += 1
            if processed_count % 10 == 0 or processed_count == total_files:
                progress = (processed_count / total_files) * 100
                print(f"\rProcessing: {processed_count}/{total_files} ({progress:.1f}%)", end='')

        print("\n")
        print(f"Successfully processed {inserted_count}/{total_files} prefetch files")
        if failed_files:
            print(f"Failed to process {len(failed_files)} files")
            failed_log_path = os.path.join(os.path.dirname(db_path), 'failed_prefetch_files.txt')
            with open(failed_log_path, 'w') as f:
                for file in failed_files:
                    f.write(f"{file}\n")
            print(f"List of failed files saved to {failed_log_path}")
        print(f"\033[92mPrefetch forensic analysis completed!\nDatabase saved to: {db_path}\033[0m")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    prefetch_claw()
