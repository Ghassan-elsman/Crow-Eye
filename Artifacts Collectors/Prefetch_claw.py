import os
import sqlite3
from datetime import datetime
from windowsprefetch import Prefetch

def format_size(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024

def format_time(timestamp):
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

# Function to parse a single prefetch file and return the data
def parse_prefetch_file(prefetch_file):
    # Get the file status
    file_stat = os.stat(prefetch_file)

    # Parse the prefetch file
    p = Prefetch(prefetch_file)

    # Extract the required information
    data = {
        "executable_name": p.executableName,
        "run_count": p.runCount,
        "file_size": format_size(file_stat.st_size),
        "last_modified": format_time(file_stat.st_mtime),
        "last_accessed": format_time(file_stat.st_atime),
        "creation_time": format_time(file_stat.st_ctime),
        "file_mode": oct(file_stat.st_mode),
        "inode_number": file_stat.st_ino,
        "device": file_stat.st_dev,
        "number_of_hard_links": file_stat.st_nlink,
        "user_id": file_stat.st_uid,
        "group_id": file_stat.st_gid
    }

    return data

# Function to parse all prefetch files in a given directory and store the data in a database
def parse_prefetch_directory(directory):
    # Connect to the SQLite database (or create it if it doesn't exist)
    conn = sqlite3.connect('prefetch.db')
    cursor = conn.cursor()

    # Create the table if it doesn't exist
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS prefetch_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            executable_name TEXT,
            run_count INTEGER,
            file_size TEXT,
            last_modified TEXT,
            last_accessed TEXT,
            creation_time TEXT,
            file_mode TEXT,
            inode_number INTEGER,
            device INTEGER,
            number_of_hard_links INTEGER,
            user_id INTEGER,
            group_id INTEGER
        )
    ''')

    # Iterate over all files in the directory
    for filename in os.listdir(directory):
        if filename.endswith('.pf'):
            prefetch_file = os.path.join(directory, filename)
            data = parse_prefetch_file(prefetch_file)

            # Insert the data into the database
            cursor.execute('''
                INSERT INTO prefetch_files (
                    executable_name, run_count, file_size, last_modified, last_accessed, creation_time, 
                    file_mode, inode_number, device, number_of_hard_links, user_id, group_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data['executable_name'], data['run_count'], data['file_size'], data['last_modified'], 
                data['last_accessed'], data['creation_time'], data['file_mode'], data['inode_number'], 
                data['device'], data['number_of_hard_links'], data['user_id'], data['group_id']
            ))

    # Commit the changes and close the connection
    conn.commit()
    conn.close()

# Specify the directory containing the prefetch files
directory = r'C:\Windows\Prefetch'

# Parse all prefetch files in the directory and store the data in the database
parse_prefetch_directory(directory)
