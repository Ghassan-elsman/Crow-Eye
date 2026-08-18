"""Fixtures: build miniature Target_Artifacts databases with the exact
schemas of a real case so extractor logic can be tested deterministically.
"""

import os
import sqlite3

import pytest


def _mk(path, schema, rows_by_table):
    conn = sqlite3.connect(path)
    conn.executescript(schema)
    for table, rows in rows_by_table.items():
        if not rows:
            continue
        cols = list(rows[0].keys())
        conn.executemany(
            "INSERT INTO {} ({}) VALUES ({})".format(
                table, ",".join(cols), ",".join("?" for _ in cols)),
            [[r[c] for c in cols] for r in rows])
    conn.commit()
    conn.close()


@pytest.fixture
def artifacts_dir(tmp_path):
    """A small but schema-accurate Target_Artifacts directory."""
    d = tmp_path / "Target_Artifacts"
    d.mkdir()

    # registry_data.db --------------------------------------------------
    _mk(str(d / "registry_data.db"), """
        CREATE TABLE UserProfiles (user_sid TEXT, username TEXT, profile_path TEXT,
            profile_image_path TEXT, profile_loaded TEXT, timestamp TEXT);
        CREATE TABLE UserAssist (program_path TEXT, run_count INTEGER,
            last_execution TEXT, focus_count INTEGER, focus_time INTEGER,
            user_sid TEXT, timestamp TEXT);
        CREATE TABLE BAM (subkey TEXT, name TEXT, row_data TEXT, type TEXT,
            app_name TEXT, process_path TEXT, sid TEXT, last_execution TEXT,
            execution_flags TEXT, parsed_at TEXT);
        CREATE TABLE Shellbags (file_name TEXT, parent_path TEXT,
            accessed_date TEXT, modified_date TEXT, created_date TEXT,
            registry_path TEXT);
        CREATE TABLE USBDevices (device_id TEXT, description TEXT,
            manufacturer TEXT, friendly_name TEXT, last_connected TEXT);
        CREATE TABLE InstalledSoftware (display_name TEXT, display_version TEXT,
            publisher TEXT, install_date TEXT, install_location TEXT,
            uninstall_string TEXT, timestamp TEXT);
        CREATE TABLE Network_list (subkey TEXT, name TEXT, data TEXT, type TEXT,
            network_name TEXT, connection_date TEXT, gateway_mac TEXT, is_hidden TEXT);
        CREATE TABLE MUICache (app_path TEXT, app_name TEXT, file_extension TEXT,
            parsed_at TEXT);
        CREATE TABLE TimeZoneInfo (time_zone_name TEXT, standard_name TEXT,
            daylight_name TEXT, bias TEXT, active_time_bias TEXT, timestamp TEXT);
        CREATE TABLE RecentDocs (subkey TEXT, name TEXT, data TEXT, type TEXT);
        CREATE TABLE AutoStartPrograms (location TEXT, program_name TEXT,
            command TEXT, timestamp TEXT);
        CREATE TABLE SystemServices (service_name TEXT, display_name TEXT,
            description TEXT, image_path TEXT, start_type TEXT, service_type TEXT,
            error_control TEXT, status TEXT, timestamp TEXT);
    """, {
        "UserProfiles": [
            {"user_sid": "S-1-5-21-111-222-333-1001", "username": "Alice",
             "profile_path": "", "profile_image_path": "", "profile_loaded": "1",
             "timestamp": ""}],
        "UserAssist": [
            {"program_path": "C:\\Apps\\notepad.exe", "run_count": 3,
             "last_execution": "2026-06-12 10:00:00", "focus_count": 0,
             "focus_time": 0, "user_sid": "S-1-5-21-111-222-333-1001", "timestamp": ""},
            {"program_path": "C:\\Apps\\ghost.exe", "run_count": 5,
             "last_execution": "", "focus_count": 0, "focus_time": 0,
             "user_sid": "S-1-5-21-111-222-333-1001", "timestamp": ""}],
        "BAM": [
            {"subkey": "", "name": "", "row_data": "", "type": "",
             "app_name": "Version", "process_path": "", "sid": "S-1-5-18",
             "last_execution": "", "execution_flags": "", "parsed_at": ""},
            {"subkey": "", "name": "", "row_data": "", "type": "",
             "app_name": "chrome.exe", "process_path": "C:\\Apps\\chrome.exe",
             "sid": "S-1-5-21-111-222-333-1001", "last_execution": "2026-06-12 11:30:00",
             "execution_flags": "", "parsed_at": ""}],
        "Shellbags": [
            {"file_name": "Secret", "parent_path": "C:\\Users\\Alice\\Documents",
             "accessed_date": "2026-06-12 13:30:00", "modified_date": "",
             "created_date": "", "registry_path": ""}],
        "USBDevices": [
            {"device_id": "USB\\VID_1234", "description": "Kingston",
             "manufacturer": "Kingston", "friendly_name": "Kingston DataTraveler",
             "last_connected": "2026-06-12 09:00:00"}],
        "InstalledSoftware": [
            {"display_name": "7-Zip", "display_version": "23.01",
             "publisher": "Igor Pavlov", "install_date": "20260601",
             "install_location": "", "uninstall_string": "", "timestamp": ""}],
        "Network_list": [
            {"subkey": "", "name": "", "data": "", "type": "",
             "network_name": "OfficeWiFi", "connection_date": "2026-06-12 08:00:00",
             "gateway_mac": "aa:bb", "is_hidden": "0"}],
        "MUICache": [
            {"app_path": "C:\\Apps\\paint.exe.FriendlyAppName", "app_name": "Paint",
             "file_extension": "", "parsed_at": ""},
            {"app_path": "C:\\Windows\\System32\\calc.exe", "app_name": "Calculator",
             "file_extension": "", "parsed_at": ""}],
        "TimeZoneInfo": [
            {"time_zone_name": "Egypt Standard Time", "standard_name": "",
             "daylight_name": "", "bias": "-120", "active_time_bias": "",
             "timestamp": ""}],
        "RecentDocs": [
            {"subkey": "main key", "name": "MRUListEx", "data": "b'\\x01\\x00'", "type": "REG_BINARY"},
            {"subkey": "main key", "name": "0", "data": "Budget.xlsx", "type": "REG_BINARY"},
            {"subkey": ".xlsx", "name": "0", "data": "Budget.xlsx", "type": "REG_BINARY"},
            {"subkey": "main key", "name": "1", "data": "Notes.txt", "type": "REG_BINARY"}],
        "AutoStartPrograms": [
            {"location": "HKCU Run", "program_name": "OneDrive",
             "command": "C:\\Users\\Alice\\AppData\\Local\\Microsoft\\OneDrive\\OneDrive.exe",
             "timestamp": ""},
            {"location": "HKLM Run", "program_name": "Sketchy",
             "command": "C:\\Users\\Alice\\AppData\\Roaming\\evil.exe", "timestamp": ""}],
        "SystemServices": [
            {"service_name": "Dnscache", "display_name": "DNS Client", "description": "",
             "image_path": "C:\\Windows\\System32\\svchost.exe", "start_type": "2",
             "service_type": "", "error_control": "", "status": "", "timestamp": ""},
            {"service_name": "EvilSvc", "display_name": "Evil Service", "description": "",
             "image_path": "C:\\Users\\Alice\\AppData\\Roaming\\evilsvc.exe", "start_type": "2",
             "service_type": "", "error_control": "", "status": "", "timestamp": ""},
            {"service_name": "ManualSvc", "display_name": "Manual Service", "description": "",
             "image_path": "C:\\Users\\Alice\\AppData\\Roaming\\manual.exe", "start_type": "3",
             "service_type": "", "error_control": "", "status": "", "timestamp": ""}],
    })

    # Log_Claw.db -------------------------------------------------------
    _mk(str(d / "Log_Claw.db"), """
        CREATE TABLE SecurityLogs (EventID INTEGER, Source TEXT, EventType TEXT,
            Category TEXT, EventTimestampUTC TEXT, ComputerName TEXT, User TEXT,
            Keywords TEXT, TaskCategory TEXT, EventDescription TEXT);
        CREATE TABLE SystemLogs (EventID INTEGER, Source TEXT, EventType TEXT,
            Category TEXT, EventTimestampUTC TEXT, ComputerName TEXT, User TEXT,
            Keywords TEXT, EventDescription TEXT);
        CREATE TABLE ApplicationLogs (EventID INTEGER, Source TEXT, EventType TEXT,
            Category TEXT, EventTimestampUTC TEXT, ComputerName TEXT, User TEXT,
            Keywords TEXT, EventDescription TEXT);
    """, {
        "SecurityLogs": [
            # interactive logon type 2 for Alice
            {"EventID": 4624, "Source": "", "EventType": "", "Category": "",
             "EventTimestampUTC": "2026-06-12 09:59:58", "ComputerName": "PC",
             "User": "Alice",
             "Keywords": "S-1-5-18,PC$,WG,0x3e7,S-1-5-21-111-222-333-1001,Alice,PC,0x5fc1d,2,User32,Negotiate,-,-,-,-,0,0x0,C:\\Windows\\System32\\winlogon.exe,-,-",
             "TaskCategory": "", "EventDescription": "An account was successfully logged on."},
            # process creation matching notepad within 5s of UserAssist
            {"EventID": 4688, "Source": "", "EventType": "", "Category": "",
             "EventTimestampUTC": "2026-06-12 10:00:02", "ComputerName": "PC",
             "User": "-",
             "Keywords": "S-1-5-21-111-222-333-1001,Alice,PC,0x5fc1d,0x111,C:\\Apps\\notepad.exe,%%1936,0x30c,,S-1-0-0,-,-,0x0,C:\\Windows\\explorer.exe,S-1-16-8192",
             "TaskCategory": "", "EventDescription": "A new process has been created."},
            # logoff
            {"EventID": 4634, "Source": "", "EventType": "", "Category": "",
             "EventTimestampUTC": "2026-06-12 17:00:00", "ComputerName": "PC",
             "User": "Alice", "Keywords": "S-1-5-21-111-222-333-1001,Alice,PC,0x5fc1d,2",
             "TaskCategory": "", "EventDescription": "An account was logged off."},
            # account created (Bob) by SYSTEM
            {"EventID": 4720, "Source": "", "EventType": "", "Category": "",
             "EventTimestampUTC": "2026-06-12 12:30:00", "ComputerName": "PC",
             "User": "SYSTEM",
             "Keywords": "Bob,PC,S-1-5-21-111-222-333-1002,S-1-5-18,PC$,WORKGROUP,0x3e7,-",
             "TaskCategory": "", "EventDescription": "A user account was created."},
            # Alice added to Administrators by SYSTEM (leading-dummy style member)
            {"EventID": 4732, "Source": "", "EventType": "", "Category": "",
             "EventTimestampUTC": "2026-06-12 12:31:00", "ComputerName": "PC",
             "User": "SYSTEM",
             "Keywords": "-,S-1-5-21-111-222-333-1001,Administrators,Builtin,S-1-5-32-544,S-1-5-18,PC$,WORKGROUP,0x3e7,-",
             "TaskCategory": "", "EventDescription": "A member was added to a security-enabled local group."},
            # account changed (4738, leading-dummy layout)
            {"EventID": 4738, "Source": "", "EventType": "", "Category": "",
             "EventTimestampUTC": "2026-06-12 12:32:00", "ComputerName": "PC",
             "User": "SYSTEM",
             "Keywords": "-,Alice,PC,S-1-5-21-111-222-333-1001,S-1-5-18,PC$,WORKGROUP,0x3e7,-,-",
             "TaskCategory": "", "EventDescription": "A user account was changed."},
            # user-initiated logoff (4647)
            {"EventID": 4647, "Source": "", "EventType": "", "Category": "",
             "EventTimestampUTC": "2026-06-12 16:59:00", "ComputerName": "PC",
             "User": "Alice", "Keywords": "S-1-5-21-111-222-333-1001,Alice,PC,0x5fc1d,2",
             "TaskCategory": "", "EventDescription": "User initiated logoff."},
        ],
        "SystemLogs": [
            {"EventID": 7045, "Source": "Service Control Manager", "EventType": "Information",
             "Category": "None", "EventTimestampUTC": "2026-06-12 08:30:00",
             "ComputerName": "PC", "User": "Dan", "Keywords": "N/A",
             "EventDescription": "A service was installed in the system."},
            {"EventID": 1, "Source": "Microsoft-Windows-Kernel-General", "EventType": "Information",
             "Category": "", "EventTimestampUTC": "2026-06-12 12:00:00",
             "ComputerName": "PC", "User": "", "Keywords": "",
             "EventDescription": "Description not available"},
            {"EventID": 7040, "Source": "Service Control Manager", "EventType": "Information",
             "Category": "None", "EventTimestampUTC": "2026-06-12 08:31:00",
             "ComputerName": "PC", "User": "Dan", "Keywords": "N/A",
             "EventDescription": "The start type of the service was changed."},
        ],
        "ApplicationLogs": [
            {"EventID": 1001, "Source": "Windows Error Reporting", "EventType": "Information",
             "Category": "", "EventTimestampUTC": "2026-06-12 15:10:00",
             "ComputerName": "PC", "User": "Alice",
             "Keywords": "1234,5,APPCRASH,Not available,0,winword.exe,16.0,,ntdll.dll",
             "EventDescription": "Fault bucket, application error."},
        ],
    })

    # prefetch_data.db --------------------------------------------------
    _mk(str(d / "prefetch_data.db"), """
        CREATE TABLE prefetch_data (filename TEXT, executable_name TEXT, hash TEXT,
            run_count INTEGER, last_executed TEXT, run_times TEXT, volumes TEXT,
            directories TEXT, resources TEXT, created_on TEXT, modified_on TEXT,
            accessed_on TEXT);
    """, {
        "prefetch_data": [
            {"filename": "NOTEPAD.EXE-123.pf", "executable_name": "NOTEPAD.EXE",
             "hash": "123", "run_count": 3, "last_executed": "2026-06-12 10:00:00",
             "run_times": '["2026-06-12 10:00:00", "2026-06-11 09:00:00"]',
             "volumes": "", "directories": "", "resources": "",
             "created_on": "", "modified_on": "", "accessed_on": ""}],
    })

    # USN_journal.db ----------------------------------------------------
    _mk(str(d / "USN_journal.db"), """
        CREATE TABLE journal_events (volume_letter TEXT, filename TEXT, usn INTEGER,
            major_version INTEGER, frn TEXT, parent_frn TEXT, timestamp TEXT,
            reason TEXT, source_info TEXT, security_id TEXT, file_attributes TEXT,
            record_length INTEGER, parsed_at TEXT);
    """, {
        "journal_events": _usn_rows(),
    })

    # mft_usn_correlated_analysis.db -----------------------------------
    _mk(str(d / "mft_usn_correlated_analysis.db"), """
        CREATE TABLE mft_usn_correlated (mft_record_number INTEGER, fn_filename TEXT,
            reconstructed_path TEXT, is_deleted INTEGER, usn_reason TEXT,
            usn_timestamp TEXT, si_creation_time TEXT, si_modification_time TEXT);
    """, {
        "mft_usn_correlated": [
            {"mft_record_number": 100, "fn_filename": "report.docx",
             "reconstructed_path": "./Users/Alice/Documents/report.docx",
             "is_deleted": 0, "usn_reason": "", "usn_timestamp": "",
             "si_creation_time": "", "si_modification_time": ""},
            {"mft_record_number": 200, "fn_filename": "kernel32.dll",
             "reconstructed_path": "./Windows/System32/kernel32.dll",
             "is_deleted": 0, "usn_reason": "", "usn_timestamp": "",
             "si_creation_time": "", "si_modification_time": ""},
            # copy signature IN a user document area -> should be detected
            {"mft_record_number": 300, "fn_filename": "movie.mp4",
             "reconstructed_path": "./Users/Alice/Downloads/movie.mp4",
             "is_deleted": 0, "usn_reason": "", "usn_timestamp": "",
             "si_creation_time": "2026-06-12 14:00:00",
             "si_modification_time": "2026-05-01 08:00:00"},
            # copy signature in WinSxS (system) -> must be EXCLUDED
            {"mft_record_number": 400, "fn_filename": "sys.dll",
             "reconstructed_path": "./Windows/WinSxS/x/sys.dll",
             "is_deleted": 0, "usn_reason": "", "usn_timestamp": "",
             "si_creation_time": "2026-06-12 14:00:00",
             "si_modification_time": "2026-05-01 08:00:00"},
            # rename-chain file (frn 500) in Alice's Documents
            {"mft_record_number": 500, "fn_filename": "c.txt",
             "reconstructed_path": "./Users/Alice/Documents/c.txt",
             "is_deleted": 0, "usn_reason": "", "usn_timestamp": "",
             "si_creation_time": "", "si_modification_time": ""},
        ],
    })

    # amcache.db --------------------------------------------------------
    _mk(str(d / "amcache.db"), """
        CREATE TABLE InventoryApplication (id TEXT, name TEXT, publisher TEXT,
            install_date TEXT, root_dir_path TEXT, parsed_at TEXT);
        CREATE TABLE InventoryApplicationFile (id TEXT, name TEXT,
            lower_case_long_path TEXT, publisher TEXT, version TEXT,
            link_date TEXT, parsed_at TEXT);
        CREATE TABLE InventoryApplicationShortcut (id TEXT, ShortcutPath TEXT,
            ShortcutTargetPath TEXT, parsed_at TEXT);
        CREATE TABLE InventoryDriverBinary (id TEXT, driver_name TEXT,
            driver_signed TEXT, driver_last_write_time TEXT, parsed_at TEXT);
        CREATE TABLE InventoryDevicePnp (id TEXT, class TEXT, model TEXT, parsed_at TEXT);
        CREATE TABLE InventoryMiscellaneousUser (id TEXT, user_name TEXT,
            user_sid TEXT, user_type TEXT, parsed_at TEXT);
    """, {
        "InventoryApplicationFile": [
            {"id": "1", "name": "sevenzip.exe",
             "lower_case_long_path": "c:\\program files\\7-zip\\7z.exe",
             "publisher": "Igor Pavlov", "version": "23", "link_date": "02/13/1977 00:06:50",
             "parsed_at": ""},
            {"id": "2", "name": "svc.exe",
             "lower_case_long_path": "c:\\windows\\system32\\svc.exe",
             "publisher": "MS", "version": "1", "link_date": "", "parsed_at": ""}],
        "InventoryApplicationShortcut": [
            {"id": "1", "ShortcutPath": "c:\\users\\alice\\desktop\\game.lnk",
             "ShortcutTargetPath": "c:\\games\\game.exe", "parsed_at": ""}],
        "InventoryDriverBinary": [
            {"id": "1", "driver_name": "nicedriver.sys", "driver_signed": "1",
             "driver_last_write_time": "2026-06-10 00:00:00", "parsed_at": ""},
            {"id": "2", "driver_name": "evil.sys", "driver_signed": "0",
             "driver_last_write_time": "2026-06-11 00:00:00", "parsed_at": ""}],
        "InventoryDevicePnp": [
            {"id": "1", "class": "USB", "model": "Kingston DT", "parsed_at": ""},
            {"id": "2", "class": "processor", "model": "Intel", "parsed_at": ""}],
        "InventoryMiscellaneousUser": [
            {"id": "1", "user_name": "Alice", "user_sid": "S-1-5-21-111-222-333-1001",
             "user_type": "", "parsed_at": ""}],
    })

    # LnkDB.db ----------------------------------------------------------
    _mk(str(d / "LnkDB.db"), """
        CREATE TABLE LNK_Files (Source_Name TEXT, Local_Path TEXT,
            Time_Access TEXT, Time_Modification TEXT);
        CREATE TABLE Automatic_JumpLists (AppDesc TEXT, Local_Path TEXT, Time_Access TEXT);
        CREATE TABLE Custom_JumpLists (entry_id INTEGER, Source_Name TEXT, AppDesc TEXT,
            Local_Path TEXT, Time_Access TEXT);
    """, {
        "LNK_Files": [
            {"Source_Name": "budget.lnk", "Local_Path": "C:\\Users\\Alice\\Documents\\budget.xlsx",
             "Time_Access": "2026-06-12 10:30:00", "Time_Modification": ""}],
        "Custom_JumpLists": [
            {"entry_id": 1, "Source_Name": "Windows Terminal", "AppDesc": "Windows Terminal",
             "Local_Path": "C:\\Users\\Alice\\project\\notes.txt",
             "Time_Access": "2026-06-12 11:00:00"}],
    })

    # srum_data.db ------------------------------------------------------
    _mk(str(d / "srum_data.db"), """
        CREATE TABLE srum_application_usage (id INTEGER, timestamp TEXT, app_name TEXT,
            app_path TEXT, user_sid TEXT, user_name TEXT, foreground_cycle_time INTEGER,
            background_cycle_time INTEGER, face_time INTEGER);
        CREATE TABLE srum_network_data_usage (id INTEGER, timestamp TEXT, app_name TEXT,
            app_path TEXT, user_sid TEXT, bytes_sent INTEGER, bytes_received INTEGER);
        CREATE TABLE srum_network_connectivity (id INTEGER, timestamp TEXT, app_name TEXT,
            app_path TEXT, user_sid TEXT, user_name TEXT, interface_luid TEXT,
            l2_profile_id TEXT, l2_profile_flags TEXT, connected_time TEXT,
            connect_start_time TEXT);
    """, {
        "srum_network_connectivity": [
            {"id": 1, "timestamp": "2026-06-12 08:00:00", "app_name": "System",
             "app_path": "", "user_sid": "S-1-5-18", "user_name": "NT AUTHORITY\\SYSTEM",
             "interface_luid": "", "l2_profile_id": "", "l2_profile_flags": "",
             "connected_time": "5m 12s", "connect_start_time": "2026-06-12 08:00:00"}],
    })
    return str(d)


def _usn_rows():
    rows = []
    usn = 1
    # 5 file creations in Alice's Documents (frn 100 -> record 100)
    for i in range(5):
        rows.append({"volume_letter": "C", "filename": "report{}.docx".format(i),
                     "usn": usn, "major_version": 2, "frn": "100", "parent_frn": "100",
                     "timestamp": "2026-06-12 13:00:0{}".format(i),
                     "reason": "FILE_CREATE | CLOSE", "source_info": "",
                     "security_id": "", "file_attributes": "", "record_length": 0,
                     "parsed_at": ""})
        usn += 1
    # a rename pair (old -> new)
    rows.append({"volume_letter": "C", "filename": "draft.txt", "usn": usn,
                 "major_version": 2, "frn": "100", "parent_frn": "100",
                 "timestamp": "2026-06-12 14:00:00", "reason": "RENAME_OLD_NAME",
                 "source_info": "", "security_id": "", "file_attributes": "",
                 "record_length": 0, "parsed_at": ""})
    usn += 1
    rows.append({"volume_letter": "C", "filename": "final.txt", "usn": usn,
                 "major_version": 2, "frn": "100", "parent_frn": "100",
                 "timestamp": "2026-06-12 14:00:01", "reason": "RENAME_NEW_NAME | CLOSE",
                 "source_info": "", "security_id": "", "file_attributes": "",
                 "record_length": 0, "parsed_at": ""})
    usn += 1
    # a soft delete: rename into $Recycle.Bin
    rows.append({"volume_letter": "C", "filename": "secret.doc", "usn": usn,
                 "major_version": 2, "frn": "300", "parent_frn": "300",
                 "timestamp": "2026-06-12 15:00:00", "reason": "RENAME_OLD_NAME",
                 "source_info": "", "security_id": "", "file_attributes": "",
                 "record_length": 0, "parsed_at": ""})
    usn += 1
    rows.append({"volume_letter": "C", "filename": "$R123456.doc", "usn": usn,
                 "major_version": 2, "frn": "300", "parent_frn": "300",
                 "timestamp": "2026-06-12 15:00:01", "reason": "RENAME_NEW_NAME | CLOSE",
                 "source_info": "", "security_id": "", "file_attributes": "",
                 "record_length": 0, "parsed_at": ""})
    usn += 1
    # pure noise row (should be skipped)
    rows.append({"volume_letter": "C", "filename": "x.tmp", "usn": usn,
                 "major_version": 2, "frn": "400", "parent_frn": "400",
                 "timestamp": "2026-06-12 16:00:00", "reason": "CLOSE",
                 "source_info": "", "security_id": "", "file_attributes": "",
                 "record_length": 0, "parsed_at": ""})
    usn += 1
    # a THREE-name rename chain for one file (frn 500 -> /Users/Alice/Documents)
    for old, new in (("a.txt", "b.txt"), ("b.txt", "c.txt")):
        rows.append({"volume_letter": "C", "filename": old, "usn": usn,
                     "major_version": 2, "frn": "500", "parent_frn": "500",
                     "timestamp": "2026-06-12 17:00:0{}".format(usn % 10),
                     "reason": "RENAME_OLD_NAME", "source_info": "",
                     "security_id": "", "file_attributes": "", "record_length": 0,
                     "parsed_at": ""})
        usn += 1
        rows.append({"volume_letter": "C", "filename": new, "usn": usn,
                     "major_version": 2, "frn": "500", "parent_frn": "500",
                     "timestamp": "2026-06-12 17:00:0{}".format(usn % 10),
                     "reason": "RENAME_NEW_NAME | CLOSE", "source_info": "",
                     "security_id": "", "file_attributes": "", "record_length": 0,
                     "parsed_at": ""})
        usn += 1
    return rows
