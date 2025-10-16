import win32evtlog
import sqlite3
import os
import sys
from datetime import datetime

# Add the parent directory to sys.path to import utils
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.time_utils import ensure_utc, format_timestamp

# Create the database and tables
def create_database(case_path=None):
    db_path = 'Log_Claw.db'
    if case_path:
        # If a case path is provided, use it for the database
        artifacts_dir = os.path.join(case_path, 'Target_Artifacts')
        if os.path.exists(artifacts_dir):
            db_path = os.path.join(artifacts_dir, 'Log_Claw.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('DROP TABLE IF EXISTS SystemLogs')
    cursor.execute('DROP TABLE IF EXISTS ApplicationLogs')
    cursor.execute('DROP TABLE IF EXISTS SecurityLogs')
    # Create tables for System, Application, and Security logs with UTC timestamps
    cursor.execute('''CREATE TABLE IF NOT EXISTS SystemLogs (
                        EventID INTEGER,
                        Source TEXT,
                        EventType TEXT,
                        Category TEXT,
                        EventTimestampUTC TEXT,  -- Stored in YYYY-MM-DD HH:MM:SS format (UTC)
                        ComputerName TEXT,
                        User TEXT,
                        Keywords TEXT,
                        EventDescription TEXT
                      )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS ApplicationLogs (
                        EventID INTEGER,
                        Source TEXT,
                        EventType TEXT,
                        Category TEXT,
                        EventTimestampUTC TEXT,  -- Stored in YYYY-MM-DD HH:MM:SS format (UTC)
                        ComputerName TEXT,
                        User TEXT,
                        Keywords TEXT,
                        EventDescription TEXT
                      )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS SecurityLogs (
                        EventID INTEGER,
                        Source TEXT,
                        EventType TEXT,
                        Category TEXT,
                        EventTimestampUTC TEXT,  -- Stored in YYYY-MM-DD HH:MM:SS format (UTC)
                        ComputerName TEXT,
                        User TEXT,
                        Keywords TEXT,
                        TaskCategory TEXT,
                        EventDescription TEXT
                      )''')
    conn.commit()
    return conn, cursor, db_path


# Map event types to readable text
def get_event_type(event_type):
    event_type_dict = {
        1: "Error",
        2: "Warning",
        4: "Information",
        8: "Success Audit",
        16: "Failure Audit"
    }
    return event_type_dict.get(event_type, "Unknown")

# Map event categories to readable text
def get_event_category(category):
    category_dict = {
        0: "None",
        1: "Application",
        2: "System",
        3: "Security"
    }
    return category_dict.get(category, "Other")

# Map event IDs to descriptions
def get_event_description(event_id):
    event_description_dict = {
       # Security Event IDs
        4624: "An account was successfully logged on.", 
        4625: "An account failed to log on.", 
        4634: "An account was logged off.", 
        4648: "A logon was attempted using explicit credentials.", 
        4656: "A handle to an object was requested.", 
        4663: "An attempt was made to access an object.", 
        4670: "Special privileges assigned to new logon.", 
        4672: "Special privileges assigned to new logon.", 
        4688: "A new process has been created.", 
        4697: "A service was installed in the system.", 
        4700: "A scheduled task was enabled.", 
        4701: "A scheduled task was disabled.", 
        4702: "A scheduled task was updated.", 
        4719: "System audit policy was changed.", 
        4720: "A user account was created.", 
        4722: "A user account was enabled.", 
        4725: "A user account was disabled.", 
        4726: "A user account was deleted.", 
        4738: "A user account was changed.", 
        4740: "A user account was locked out.", 
        4768: "A Kerberos authentication ticket (TGT) was requested.", 
        4769: "A Kerberos service ticket was requested.", 
        4771: "Kerberos pre-authentication failed.", 
        4776: "The domain controller attempted to validate the credentials for an account.", 
        4798: "A user's local group membership was enumerated.", 
        4799: "A security-enabled local group membership was enumerated.", 
        4800: "The workstation was locked.", 
        4801: "The workstation was unlocked.", 
        5038: "Code integrity determined that the image hash of a file is not valid.", 
        5140: "A network share object was accessed" ,
       # Application Event IDs
        1000: "Application error.",
        1001: "Application hang.",
        1002: "Application crash.",
        1004: "Application error caused by an unhandled exception.",
        1005: "Windows Installer reconfiguration.",
        1006: "Windows Installer error.",
        1008: "Performance issues detected in the application.",
        1010: "Application started.",
        1011: "Application stopped.",
        1013: "Application shut down unexpectedly.",
        1014: "Application encountered a network error.",
        1020: "Application encountered a database error.",
        1022: "Application configuration changed.",
        1025: "Application license expired.",
        1026: "Application memory leak detected.",
        1030: "Application update failed.",
        1031: "Application update succeeded.",
        1032: "Application patched successfully.",
        1033: "Application performance monitoring started.",
        1034: "Application performance monitoring stopped.",
        1040: "Application encountered a system error.",
        1041: "Application encountered a security violation.",
        1042: "Application encountered a hardware failure.",
        1043: "Application encountered an I/O error.",
        1044: "Application encountered a configuration error.",
       # System Event IDs
        6005: "The event log service was started.",
        6006: "The event log service was stopped.",
        6008: "The previous system shutdown was unexpected.",
        6009: "Operating system version information.",
        6013: "The system uptime.",
        7000: "The service did not start due to a logon failure.",
        7001: "The service started successfully.",
        7009: "Timeout waiting for a service to start.",
        7011: "A timeout (30000 milliseconds) was reached while waiting for a service to connect.",
        7016: "The service has reported an invalid current state.",
        7022: "The service hung on starting.",
        7023: "The service terminated with the following error.",
        7024: "The service terminated with service-specific error.",
        7026: "The following boot-start or system-start driver(s) failed to load.",
        7031: "The service terminated unexpectedly.",
        7034: "The service terminated unexpectedly.",
        7035: "The service control manager successfully sent a start control.",
        7036: "The service entered the stopped state.",
        7040: "The start type of the service was changed.",
        7045: "A service was installed in the system.",
        7027: "The service did not respond to the start or control request in a timely fashion.",
        7032: "The Service Control Manager did not handle the specific error code.",
        7038: "The Account used for the service is invalid.",
        7042: "A service was marked for deletion.",
        7043: "The service did not shut down properly after receiving a pre-shutdown control."
        
    }
    return event_description_dict.get(event_id, "Description not available")

# Read event logs and insert into the database
def read_event_logs(log_type, cursor):
    server = 'localhost'
    log_handle = win32evtlog.OpenEventLog(server, log_type)
    flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
    
    while True:
        events = win32evtlog.ReadEventLog(log_handle, flags, 0)
        if not events:
            break

        for event in events:
            try:
                event_id = event.EventID & 0xFFFF
                source = event.SourceName
                event_type = get_event_type(event.EventType)
                category = get_event_category(event.EventCategory)
                
                # Get the original time string
                original_time = event.TimeGenerated.Format()
                
                # Convert to datetime and ensure it's in UTC
                try:
                    # Try multiple possible formats
                    formats_to_try = [
                        "%a %b %d %H:%M:%S %Y",  # 'Fri Sep  5 17:10:02 2025'
                        "%Y-%m-%d %H:%M:%S",     # '2023-01-01 12:00:00'
                        "%Y/%m/%d %H:%M:%S",     # '2023/01/01 12:00:00'
                        "%d/%m/%Y %H:%M:%S"      # '01/01/2023 12:00:00'
                    ]
                    
                    dt = None
                    for fmt in formats_to_try:
                        try:
                            dt = datetime.strptime(original_time.strip(), fmt)
                            break
                        except ValueError:
                            continue
                    
                    if dt is None:
                        raise ValueError(f"Time format not recognized: {original_time}")
                        
                    # Convert to UTC and format as YYYY-MM-DD HH:MM:SS
                    utc_dt = ensure_utc(dt)
                    utc_time = utc_dt.strftime('%Y-%m-%d %H:%M:%S')
                    
                except Exception as e:
                    # If conversion fails, use current UTC time and log the error
                    print(f"Error converting time '{original_time}': {str(e)}")
                    utc_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                
                computer = event.ComputerName
                user = "N/A"
                keywords = "N/A"
                event_description = get_event_description(event_id)
                
                if log_type == 'Security':
                    if event.StringInserts:
                        user = event.StringInserts[1] if len(event.StringInserts) > 1 else "N/A"
                        keywords = ",".join(event.StringInserts)
                    task_category = event.EventCategory

                    cursor.execute('''INSERT INTO SecurityLogs 
                                    (EventID, Source, EventType, Category, EventTimestampUTC, 
                                     ComputerName, User, Keywords, TaskCategory, EventDescription)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                 (event_id, source, event_type, category, utc_time,
                                  computer, user, keywords, task_category, event_description))
                
                elif log_type == 'Application':
                    if event.StringInserts:
                        user = event.StringInserts[1] if len(event.StringInserts) > 1 else "N/A"
                        keywords = ",".join(event.StringInserts)

                    cursor.execute('''INSERT INTO ApplicationLogs 
                                    (EventID, Source, EventType, Category, EventTimestampUTC, 
                                     ComputerName, User, Keywords, EventDescription)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                 (event_id, source, event_type, category, utc_time,
                                  computer, user, keywords, event_description))
                
                else:  # System logs
                    cursor.execute('''INSERT INTO SystemLogs 
                                    (EventID, Source, EventType, Category, EventTimestampUTC, 
                                     ComputerName, User, Keywords, EventDescription)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                 (event_id, source, event_type, category, utc_time,
                                  computer, user, keywords, event_description))
                                 
            except Exception as e:
                print(f"Error processing event: {str(e)}")
                continue
    
    win32evtlog.CloseEventLog(log_handle)

# Main function to create database and read logs
def main(case_path=None):
    conn, cursor, db_path = create_database(case_path)
    
    print("Reading System Logs...")
    read_event_logs('System', cursor)
    
    print("\nReading Application Logs...")
    read_event_logs('Application', cursor)
    
    print("\nReading Security Logs...")
    read_event_logs('Security', cursor)

    conn.commit()
    conn.close()
    
    print(f"\033[92m\nParsing logs has been completed by Crow Eye\nDatabase saved to: {db_path}\033[0m")

if __name__ == "__main__":
    main()
