"""
Query Processor for EYE AI Assistant.

This module acts as the "Central Nervous System" of the EYE Assistant. It 
orchestrates the complete investigative pipeline, transforming a raw natural 
language query into a verified forensic conclusion.

PIPELINE STAGES:
1. Intent Detection: Parsing the query for specific forensic targets.
2. RAG Retrieval: Pulling relevant knowledge-base articles about artifacts.
3. Prompt Construction: Merging case context, RAG results, and history.
4. AI Consultation: Calling the configured LLM (Cloud or Local).
5. Tool Execution: Running SQL/Search handlers based on AI requests.
6. Forensic Synthesis: Final validation and reporting using the 
   'Forensic Evidence Protocol' for technical evidence.

UI FEEDBACK:
The processor uses a 'ThinkingStep' JSON protocol to provide real-time updates 
to the React frontend, allowing the investigator to see the AI's logic trail.
"""

import json
import logging
import sqlite3
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable

class QueryProcessor:
    """
    Main Orchestrator for the Forensic Investigation Pipeline.
    
    This class is state-agnostic and relies on the provided ContextManager 
    to interact with the case database, history, and AI backends.
    """
    
    def __init__(self, context_manager):
        """
        Args:
            context_manager: Instance of eye.services.context_manager.ContextManager
        """
        self.cm = context_manager
        self.logger = logging.getLogger(self.__class__.__name__)

    def _run_python_triage(self, emit_step, check_report_sync, initial_report_state):
        """
        Comprehensive automated forensic triage.
        Extracts key artifacts across all major categories to build a high-fidelity living report.
        """
        emit_step("tool_call", "Discovering Forensic Databases...", "active")
        

        primary_data_dir = os.path.join(self.cm.case_directory, "Target_Artifacts")
        
        # --- ENHANCED DATABASE RESOLVER ---
        def resolve_db(filename: str, required_table: str) -> Optional[str]:
            """Robustly resolve database file path and verify table existence."""
            # 1. Check primary data directory (Target_Artifacts) explicitly
            target_sub = os.path.join(primary_data_dir, filename)
            if os.path.exists(target_sub):
                self.cm.database_service.db_manager.disconnect(filename)
                self.cm.database_service.db_manager.resolved_paths[filename] = Path(target_sub)
                if self.cm.database_service.db_manager.table_exists(filename, required_table):
                    return filename

            # 2. Recursive search fallback from case root
            case_path = Path(self.cm.case_directory)
            for path in case_path.rglob(filename):
                try:
                    path_str = str(path.absolute())
                    conn = sqlite3.connect(path_str, timeout=1.0)
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (required_table,))
                    exists = cur.fetchone()
                    conn.close()
                    if exists:
                        self.cm.database_service.db_manager.disconnect(filename)
                        self.cm.database_service.db_manager.resolved_paths[filename] = path
                        return filename
                except Exception: continue
            return None

        # Resolve core data sources (Done before any query to prevent noise)
        reg_db = resolve_db("registry_data.db", "UserProfiles")
        pref_db = resolve_db("prefetch_data.db", "prefetch_data")
        mft_db = resolve_db("mft_usn_correlated_analysis.db", "mft_usn_correlated")
        log_db = resolve_db("Log_Claw.db", "SecurityLogs")
        bin_db = resolve_db("recyclebin_analysis.db", "recycle_bin_entries")
        am_db = resolve_db("amcache.db", "InventoryApplication")
        shim_db = resolve_db("shimcache.db", "shimcache_entries")
        srum_db = resolve_db("srum_data.db", "srum_application_usage")
        lnk_db = resolve_db("LnkDB.db", "LNK_Files")
        
        # Refresh discovery based on new paths
        self.cm.database_service.discover_databases()

        def safe_add_table(db, query, title, limit=30):
            """Helper to execute query and only add to report if data exists."""
            if not db: return False
            res = self.cm.database_service.execute_query(db, f"{query} LIMIT {limit}")
            if res.get("success") and res.get("data"):
                # Use compact spacing for triage tables to avoid 'collapsed' look
                self.cm.report_engine.add_data_table(query, list(res["data"][0].keys()), res["data"], title, compact_spacing=True)
                return True
            return False

        # --- 1. SYSTEM IDENTITY & CONFIGURATION ---
        emit_step("tool_call", "Profiling System Identity...", "active")
        sys_info_md = "### System Overview\n"
        
        # Hostname
        comp_name = "Unknown"
        if reg_db:
             name_res = self.cm.database_service.execute_query(reg_db, "SELECT computer_name FROM ComputerNameInfo LIMIT 1")
             if name_res.get("success") and name_res.get("data"):
                  comp_name = name_res["data"][0].get("computer_name", "Unknown")
        sys_info_md += f"- **Computer Name:** {comp_name}\n"
        
        # Users
        users = []
        if reg_db:
            users_res = self.cm.database_service.execute_query(reg_db, "SELECT username FROM UserProfiles")
            users = [u.get("username", "Unknown") for u in users_res.get("data", []) if u.get("username")]
        
        if users:
            sys_info_md += f"- **Identified Users:** {', '.join(users[:10])}{'...' if len(users) > 10 else ''}\n"
        
        # Timezone
        timezone = "N/A"
        if reg_db:
            tz_res = self.cm.database_service.execute_query(reg_db, "SELECT time_zone_name FROM TimeZoneInfo LIMIT 1")
            if tz_res.get("success") and tz_res.get("data"):
                timezone = tz_res["data"][0].get("time_zone_name", "N/A")
        sys_info_md += f"- **Timezone Info:** {timezone}\n"

        self.cm.report_engine.append_section("System Identity", sys_info_md)

        # --- 2. SECURITY & AUTHENTICATION ---
        emit_step("tool_call", "Auditing Security Logs...", "active")
        s_count, f_count, a_count, e_count, r_count, v_count = 0, 0, 0, 0, 0, 0
        if log_db:
            # 4624: Success, 4625: Failure, 4672: Admin Logon, 4648: Explicit Credentials, 4776: Credential Validation
            s_res = self.cm.database_service.execute_query(log_db, "SELECT COUNT(*) as c FROM SecurityLogs WHERE EventID=4624")
            f_res = self.cm.database_service.execute_query(log_db, "SELECT COUNT(*) as c FROM SecurityLogs WHERE EventID=4625")
            a_res = self.cm.database_service.execute_query(log_db, "SELECT COUNT(*) as c FROM SecurityLogs WHERE EventID=4672")
            e_res = self.cm.database_service.execute_query(log_db, "SELECT COUNT(*) as c FROM SecurityLogs WHERE EventID=4648")
            v_res = self.cm.database_service.execute_query(log_db, "SELECT COUNT(*) as c FROM SecurityLogs WHERE EventID=4776")
            
            # Detect Remote Desktop / Network logons (Logon Type 3 or 10 in description)
            r_res = self.cm.database_service.execute_query(log_db, "SELECT COUNT(*) as c FROM SecurityLogs WHERE EventID=4624 AND (EventDescription LIKE '%Logon Type: 3%' OR EventDescription LIKE '%Logon Type: 10%')")
            
            s_count = s_res.get("data", [{}])[0].get("c", 0) if s_res.get("success") and s_res.get("data") else 0
            f_count = f_res.get("data", [{}])[0].get("c", 0) if f_res.get("success") and f_res.get("data") else 0
            a_count = a_res.get("data", [{}])[0].get("c", 0) if a_res.get("success") and a_res.get("data") else 0
            e_count = e_res.get("data", [{}])[0].get("c", 0) if e_res.get("success") and e_res.get("data") else 0
            v_count = v_res.get("data", [{}])[0].get("c", 0) if v_res.get("success") and v_res.get("data") else 0
            r_count = r_res.get("data", [{}])[0].get("c", 0) if r_res.get("success") and r_res.get("data") else 0
            
            if sum([s_count, f_count, a_count, e_count, r_count, v_count]) > 0:
                # Use a specific high-visibility forensic palette
                # Avoid index 0 if it's black/dark
                login_palette = self.cm.report_engine.color_manager.get_palette("forensic")
                # Ensure visibility: Success(Greenish), Failure(Reddish), Admin(Purple/Gold), Explicit(Cyan), Remote(Orange)
                self.cm.report_engine.add_chart(
                    "Authentication Patterns",
                    ["Success (4624)", "Failure (4625)", "Admin Logon (4672)", "Explicit Creds (4648)", "Remote Access (RDP/Net)"],
                    [{"label": "Events", "data": [s_count, f_count, a_count, e_count, r_count], 
                      "backgroundColor": ["#4CAF50", "#F44336", "#FFD700", "#00BCD4", "#FF9800"]}],
                    "bar"
                )
                
                # Table with detailed remote connections
                remote_query = "SELECT EventTimestampUTC, EventID, User, ComputerName, EventDescription FROM SecurityLogs WHERE EventID=4624 AND (EventDescription LIKE '%Logon Type: 3%' OR EventDescription LIKE '%Logon Type: 10%') ORDER BY EventTimestampUTC DESC"
                safe_add_table(log_db, remote_query, "Remote Access & Network Logons (Type 3/10)")
                
                # --- ENHANCED 4648 PARSING ---
                if e_count > 0:
                    emit_step("tool_call", "Extracting Explicit Credential Details...", "active")
                    e_res = self.cm.database_service.execute_query(log_db, "SELECT EventTimestampUTC, User, Keywords FROM SecurityLogs WHERE EventID=4648 ORDER BY EventTimestampUTC DESC LIMIT 10")
                    if e_res.get("success") and e_res.get("data"):
                        parsed_4648 = []
                        for row in e_res["data"]:
                            k = row.get("Keywords", "")
                            parts = k.split(",")
                            # Field Map: 5:TargetUser, 6:TargetDomain, 8:TargetServer, 11:ProcessName
                            target_user = parts[5] if len(parts) > 5 else "N/A"
                            target_server = parts[8] if len(parts) > 8 else "N/A"
                            process = parts[11] if len(parts) > 11 else "N/A"
                            
                            parsed_4648.append({
                                "Timestamp": row["EventTimestampUTC"],
                                "Subject (Who)": row["User"],
                                "Used Credential": target_user,
                                "Target Server": target_server,
                                "Via Process": process
                            })
                        
                        if parsed_4648:
                            self.cm.report_engine.add_data_table("Internal 4648 Details", list(parsed_4648[0].keys()), parsed_4648, "Explicit Credential Logons (EID 4648 Details)")

                # High-priority security list - enriched with Keywords for better parsing
                safe_add_table(log_db, "SELECT EventTimestampUTC, EventID, User, ComputerName, Keywords, EventDescription FROM SecurityLogs WHERE EventID IN (4624, 4625, 4672, 4648, 4776, 4719, 1102) ORDER BY EventTimestampUTC DESC", "High-Priority Security & Authentication Events")

        # --- 3. EXECUTION INTELLIGENCE ---
        emit_step("tool_call", "Mapping Execution Artifacts...", "active")
        
        # Top Apps (Prefetch)
        if pref_db:
            app_res = self.cm.database_service.execute_query(pref_db, "SELECT executable_name, run_count FROM prefetch_data ORDER BY CAST(run_count AS INTEGER) DESC LIMIT 5")
            if app_res.get("success") and app_res.get("data"):
                forensic_palette = self.cm.report_engine.color_manager.get_palette("forensic")
                self.cm.report_engine.add_chart(
                    "Top 5 Applications (Prefetch)",
                    [a["executable_name"] for a in app_res["data"]],
                    [{"label": "Run Count", "data": [int(a["run_count"]) for a in app_res["data"]], "backgroundColor": forensic_palette}],
                    "pie"
                )
        
        safe_add_table(pref_db, "SELECT executable_name, run_count, last_executed, (SELECT source_path FROM prefetch_data pd2 WHERE pd2.executable_name = prefetch_data.executable_name LIMIT 1) as full_path FROM prefetch_data ORDER BY last_executed DESC", "Recent Prefetch Executions (App Names & Paths)")
        safe_add_table(am_db, "SELECT name, version, publisher, install_date, path FROM InventoryApplication ORDER BY install_date DESC", "Amcache: Installed Applications & Binary Paths")
        
        # SRUM (Long-term activity)
        if srum_db:
             emit_step("tool_call", "Processing SRUM Resource Intelligence...", "active")
             
             # 1. Network Usage Aggregation
             net_res = self.cm.database_service.execute_query(srum_db, "SELECT app_name, bytes_sent, bytes_received, timestamp FROM srum_network_data_usage")
             if net_res.get("success") and net_res.get("data"):
                 def parse_bytes(val):
                     """Convert various SRUM byte strings/ints to raw bytes."""
                     if not val: return 0
                     if isinstance(val, (int, float)): return float(val)
                     v = str(val).lower().strip()
                     try:
                         parts = v.split()
                         num = float(parts[0])
                         if len(parts) > 1:
                             unit = parts[1]
                             if "tb" in unit: return num * 1024**4
                             if "gb" in unit: return num * 1024**3
                             if "mb" in unit: return num * 1024**2
                             if "kb" in unit: return num * 1024
                         return num
                     except: return 0

                 def format_bytes(b):
                     """Convert bytes to human-readable string (e.g., 1.2 GB)."""
                     if b <= 0: return "0 B"
                     for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                         if b < 1024:
                             return f"{round(b, 2)} {unit}"
                         b /= 1024
                     return f"{round(b, 2)} PB"

                 net_stats = {}
                 for row in net_res["data"]:
                     app = row["app_name"] or "Unknown"
                     total = parse_bytes(row["bytes_sent"]) + parse_bytes(row["bytes_received"])
                     ts = row["timestamp"]
                     if app not in net_stats: net_stats[app] = {"total": 0, "first": ts, "last": ts}
                     net_stats[app]["total"] += total
                     if ts < net_stats[app]["first"]: net_stats[app]["first"] = ts
                     if ts > net_stats[app]["last"]: net_stats[app]["last"] = ts
                 
                 sorted_net = sorted(net_stats.items(), key=lambda x: x[1]["total"], reverse=True)[:10]
                 if sorted_net:
                     # Chart labels (Top 5)
                     chart_labels = [x[0] for x in sorted_net[:5]]
                     chart_data = [round(x[1]["total"] / (1024*1024), 2) for x in sorted_net[:5]] # Keep MB for charts to have consistent scale
                     
                     self.cm.report_engine.add_chart(
                         "Top Apps: Network Data Usage",
                         chart_labels,
                         [{"label": "Total MB", "data": chart_data, "backgroundColor": "#2196F3"}],
                         "bar"
                     )
                     
                     # Table data (Readable format)
                     table_data = [{
                         "App Name": k, 
                         "Total Data": format_bytes(v["total"]), 
                         "First Active": v["first"], 
                         "Last Active": v["last"]
                     } for k, v in sorted_net]
                     
                     self.cm.report_engine.add_data_table("Network Activity Ranges", ["App Name", "Total Data", "First Active", "Last Active"], table_data, "App Network Usage & Time Ranges")

             # 2. CPU Cycle / Energy Usage Aggregation
             cpu_res = self.cm.database_service.execute_query(srum_db, "SELECT app_name, foreground_cycle_time, timestamp FROM srum_application_usage")
             if cpu_res.get("success") and cpu_res.get("data"):
                 def parse_time(val):
                     """Convert SRUM time strings/ints to raw seconds."""
                     if not val: return 0
                     if isinstance(val, (int, float)): return float(val)
                     v = str(val).lower().strip()
                     try:
                         parts = v.split()
                         num = float(parts[0])
                         if len(parts) > 1:
                             unit = parts[1]
                             if "hour" in unit or "hr" in unit: return num * 3600
                             if "min" in unit: return num * 60
                         return num # seconds
                     except: return 0

                 def format_duration(seconds):
                     """Convert seconds to human-readable duration (e.g., 2h 15m)."""
                     if seconds <= 0: return "0s"
                     
                     days = int(seconds // 86400)
                     hours = int((seconds % 86400) // 3600)
                     minutes = int((seconds % 3600) // 60)
                     secs = int(seconds % 60)
                     
                     parts = []
                     if days > 0: parts.append(f"{days}d")
                     if hours > 0: parts.append(f"{hours}h")
                     if minutes > 0: parts.append(f"{minutes}m")
                     if secs > 0 or not parts: parts.append(f"{secs}s")
                     
                     return " ".join(parts[:2]) # Keep it concise
                 
                 cpu_stats = {}
                 for row in cpu_res["data"]:
                     app = row["app_name"] or "Unknown"
                     seconds = parse_time(row["foreground_cycle_time"])
                     ts = row["timestamp"]
                     if app not in cpu_stats: cpu_stats[app] = {"total_sec": 0, "first": ts, "last": ts}
                     cpu_stats[app]["total_sec"] += seconds
                     if ts < cpu_stats[app]["first"]: cpu_stats[app]["first"] = ts
                     if ts > cpu_stats[app]["last"]: cpu_stats[app]["last"] = ts
                 
                 sorted_cpu = sorted(cpu_stats.items(), key=lambda x: x[1]["total_sec"], reverse=True)[:10]
                 if sorted_cpu:
                     # Chart labels (Top 5)
                     chart_labels = [x[0][:30] + "..." if len(x[0]) > 30 else x[0] for x in sorted_cpu[:5]]
                     chart_data = [round(x[1]["total_sec"] / 60, 2) for x in sorted_cpu[:5]] # Minutes for chart
                     
                     self.cm.report_engine.add_chart(
                         "Top Apps: CPU Cycle Time (Energy Proxy)",
                         chart_labels,
                         [{"label": "Active Minutes", "data": chart_data, "backgroundColor": "#FFC107"}],
                         "bar"
                     )

                     # Table data (Readable format)
                     table_data = [{
                         "App Name": k, 
                         "Total CPU Time": format_duration(v["total_sec"]), 
                         "First Active": v["first"], 
                         "Last Active": v["last"]
                     } for k, v in sorted_cpu]

                     self.cm.report_engine.add_data_table("CPU Activity Ranges", ["App Name", "Total CPU Time", "First Active", "Last Active"], table_data, "App CPU Usage & Time Ranges")
                     

        # --- 4. PERSISTENCE & REMOTE CONTROL ---
        emit_step("tool_call", "Scanning Persistence & Remote Access Protocols...", "active")
        
        # Remote Control Software Detection
        remote_sw = []
        if reg_db and self.cm.database_service.db_manager.table_exists(reg_db, "SystemServices"):
            # Manual expansion of conditions for SQLite
            svc_conditions = " OR ".join([f"service_name LIKE '%{k}%' OR display_name LIKE '%{k}%'" for k in ['teamviewer', 'anydesk', 'vnc', 'rdp', 'ssh', 'winrm']])
            svc_res = self.cm.database_service.execute_query(reg_db, f"SELECT display_name, service_name, status FROM SystemServices WHERE {svc_conditions}")
            if svc_res.get("success") and svc_res.get("data"):
                remote_sw.extend([{"Type": "Service", "Name": r["display_name"], "Details": r["service_name"], "Status": r["status"]} for r in svc_res["data"]])
                
            # Search Run keys
            run_conditions = " OR ".join([f"name LIKE '%{k}%' OR row_data LIKE '%{k}%'" for k in ['teamviewer', 'anydesk', 'vnc', 'rdp', 'ssh']])
            run_res = self.cm.database_service.execute_query(reg_db, f"SELECT name, row_data FROM machine_run WHERE {run_conditions} UNION SELECT name, row_data FROM user_run WHERE {run_conditions}")
            if run_res.get("success") and run_res.get("data"):
                remote_sw.extend([{"Type": "Startup", "Name": r["name"], "Details": r["row_data"][:100], "Status": "Enabled"} for r in run_res["data"]])

        if remote_sw:
             self.cm.report_engine.add_data_table("Internal Protocol List", ["Type", "Name", "Details", "Status"], remote_sw, "Detected Remote Control & Communication Protocols")

        if reg_db:
            safe_add_table(reg_db, "SELECT name, row_data as data, type, key_path FROM machine_run UNION SELECT name, row_data as data, type, key_path FROM user_run", "Active Persistence Keys (Run/RunOnce)")
            safe_add_table(reg_db, "SELECT display_name, service_name, status, image_path, start_type FROM SystemServices WHERE start_type IN (2, 3)", "Critical System Services (Auto & Manual Start)")

        # --- 5. USER ACTIVITY & INTENT ---
        emit_step("tool_call", "Analyzing User Intent...", "active")
        if reg_db:
            safe_add_table(reg_db, "SELECT command, access_date FROM RunMRU ORDER BY access_date DESC", "Recent Win+R Commands (RunMRU)")
            safe_add_table(reg_db, "SELECT name as filename, data as folder FROM RecentDocs ORDER BY data DESC", "Recently Accessed Documents (RecentDocs)")
            safe_add_table(reg_db, "SELECT url, title, visit_count, last_visit FROM BrowserHistory ORDER BY last_visit DESC", "Extracted Browser History")
        
        # LNK & JumpLists
        if lnk_db:
             safe_add_table(lnk_db, "SELECT Source_Name, Local_Path, Working_Directory, Time_Access FROM LNK_Files ORDER BY Time_Access DESC", "Recent LNK File Access")
             safe_add_table(lnk_db, "SELECT AppID, Local_Path, Time_Access FROM Automatic_JumpLists ORDER BY Time_Access DESC", "Recent JumpList Entries")

        # --- 6. HARDWARE & NETWORK ---
        emit_step("tool_call", "Mapping Hardware & Network History...", "active")
        
        # Enhanced USB Triage
        if reg_db:
            usb_query = "SELECT friendly_name, manufacturer, last_connected, device_id FROM USBDevices ORDER BY last_connected DESC"
            usb_res = self.cm.database_service.execute_query(reg_db, usb_query)
            if usb_res.get("success") and usb_res.get("data"):
                 self.cm.report_engine.add_data_table(usb_query, ["friendly_name", "manufacturer", "last_connected", "device_id"], usb_res["data"], "Comprehensive USB Hardware History")

        # Enhanced Network Triage (Pivoted & Merged Profiles)
        net_data = []
        if reg_db and self.cm.database_service.db_manager.table_exists(reg_db, "Network_list"):
             net_raw = self.cm.database_service.execute_query(reg_db, "SELECT subkey, name, data FROM Network_list")
             if net_raw.get("success") and net_raw.get("data"):
                 profiles = {}
                 for row in net_raw["data"]:
                     sk = row["subkey"]
                     if sk not in profiles: profiles[sk] = {"ProfileID": sk}
                     profiles[sk][row["name"]] = row["data"]
                 
                 merged_networks = {}
                 for sk, p in profiles.items():
                     ssid = p.get("ProfileName") or p.get("Description") or p.get("network_name", "Unknown")
                     created = p.get("DateCreated", "N/A")
                     last = p.get("DateLastConnected", "N/A")
                     mac = p.get("DefaultGatewayMac", "N/A")
                     
                     if ssid not in merged_networks:
                         merged_networks[ssid] = {"SSID": ssid, "Created": created, "LastConnected": last, "GatewayMAC": mac}
                     else:
                         if last != "N/A" and (merged_networks[ssid]["LastConnected"] == "N/A" or last > merged_networks[ssid]["LastConnected"]):
                             merged_networks[ssid]["LastConnected"] = last
                             merged_networks[ssid]["GatewayMAC"] = mac
                 
                 net_data = list(merged_networks.values())
                 net_data.sort(key=lambda x: (x["LastConnected"] == "N/A", x["LastConnected"]), reverse=True)
                 if net_data:
                     self.cm.report_engine.add_data_table("Merged Network Profiles", ["SSID", "Created", "LastConnected", "GatewayMAC"], net_data, "Network Connectivity Profiles (Merged)")

        # --- 7. FILE SYSTEM PULSE ---
        emit_step("tool_call", "Analyzing File Lifecycle...", "active")
        safe_add_table(mft_db, "SELECT fn_filename, si_modification_time, mft_flags, reconstructed_path FROM mft_usn_correlated ORDER BY si_modification_time DESC", "10 Most Recent File Modifications (MFT/USN)")
        safe_add_table(bin_db, "SELECT original_filename, original_path, deletion_time FROM recycle_bin_entries ORDER BY deletion_time DESC", "Recently Deleted Files (Recycle Bin)")

        # --- FINAL SYNTHESIS ---
        emit_step("synthesis", "Finalizing Comprehensive Triage Report...", "active")
        
        # Safe counts for summary
        total_auth = (s_count or 0) + (f_count or 0) + (a_count or 0) + (e_count or 0) + (v_count or 0)
        user_count = len(users)
        usb_count = 0
        if reg_db and self.cm.database_service.db_manager.table_exists(reg_db, "USBDevices"):
             u_count_res = self.cm.database_service.execute_query(reg_db, "SELECT COUNT(*) as c FROM USBDevices")
             usb_count = u_count_res.get("data", [{}])[0].get("c", 0) if u_count_res.get("success") and u_count_res.get("data") else 0

        # Refactor Summary into a real TableBlock for professional 'Uncollapsed' look
        summary_data = [
            {"Category": "Identity", "Finding": f"Found {user_count} user profiles and system metadata."},
            {"Category": "Security", "Finding": f"Audited {total_auth} security events; detected {r_count} remote access attempts."},
            {"Category": "Execution", "Finding": "Aggregated Prefetch, Amcache, and SRUM (Top apps mapped)."},
            {"Category": "Persistence", "Finding": f"Scanned Run keys and {len(remote_sw)} remote protocols identified."},
            {"Category": "User Intent", "Finding": "RecentDocs, RunMRU, and LNK/JumpList activity indexed."},
            {"Category": "Hardware", "Finding": f"Found {usb_count} USB devices and {len(net_data)} network profiles."},
            {"Category": "FileSystem", "Finding": "Correlated MFT/USN Journal for recent pulse."}
        ]
        
        self.cm.report_engine.add_data_table(
            "Triage Summary Table", 
            ["Category", "Finding"], 
            summary_data, 
            "🏛️ Triage Executive Summary Dashboard",
            column_widths={"Category": "25%", "Finding": "75%"}
        )
        
        # Immediate Observations as a TextBlock
        observations_md = f"""
### 🛡️ Immediate Technical Observations
- **System Owner**: {comp_name}
- **Active Users**: {', '.join(users[:5])}{'...' if len(users) > 5 else ''}
- **Remote Protocols**: {', '.join([s['Name'] for s in remote_sw[:3]]) if remote_sw else 'None detected'}

*This report follows the Ghassan Elsman Protocol v2.0 for automated forensic triage.*
"""
        self.cm.report_engine.append_section("🛡️ Immediate Technical Observations", observations_md)
        self.cm.report_engine.save_report()
        
        # Log this triage as a milestone in the Case Summary
        self.cm.case_context_manager.log_investigation_step(
            query="Initialize Case Triage",
            response_summary=f"Completed automated triage for {comp_name}. Indexed users, auth events, and execution artifacts.",
            evidence_found=True,
            suggested_next_steps="Review the Triage Report and investigate detected remote access events.",
            artifacts_queried=["Registry", "SecurityLogs", "Prefetch", "Amcache", "SRUM", "MFT"],
            query_type="triage"
        )
        
        # Final Sync to GUI
        check_report_sync(initial_report_state)
        
        emit_step("synthesis", "Forensic Triage Complete.", "done")
        
        response = f"Automated Forensic Triage for **{comp_name}** is complete.\n\n" \
                  f"I have successfully indexed findings across 7 forensic categories into the Living Report. " \
                  f"No AI resources were consumed for this initial extraction pass.\n\n" \
                  f"**Ready for investigation.** What would you like to analyze first?"
                  
        self.cm.history_manager.add_message("assistant", response)
        
        return {
            "response": response,
            "action_chips": [
                {"id": "triage_ai", "label": "Ask AI to Analyze Findings", "query": "Based on the triage report, identify any suspicious execution patterns or unauthorized persistence.", "icon": "brain"},
                {"id": "timeline_view", "label": "View Master Timeline", "query": "Generate a chronological timeline of the most significant security and execution events.", "icon": "history"}
            ],
            "metadata": {
                "protocol": "Ghassan Elsman Protocol v2.0",
                "pillar": 0,
                "pillar_name": "Case Awareness (The Triage)"
            },
            "error": None,
            "context_stats": self.cm.get_context_stats()
        }

    def process_query(
        self, 
        user_query: str, 
        status_callback: Optional[Callable[[str], None]] = None,
        hitl_callback: Optional[Callable] = None,
        report_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """
        Executes the full forensic pipeline.
        """
        import uuid
        step_counter = [0]

        def emit_step(step_type: str, label: str, status: str,
                      tool: Optional[str] = None,
                      params: Optional[Dict] = None,
                      detail: Optional[str] = None) -> str:
            """
            Internal helper to notify the UI about a pipeline milestone.
            """
            step_counter[0] += 1
            step = {
                "step_id": f"s{step_counter[0]}",
                "type": step_type,          # "thinking" | "rag" | "tool_call" | "synthesis"
                "label": label,
                "status": status,           # "active" | "done" | "error"
                "timestamp": datetime.now().isoformat()
            }
            if tool:
                step["tool"] = tool
            if params:
                # Truncate large param values to prevent UI bloat
                step["params"] = {
                    k: (str(v)[:120] + "...") if len(str(v)) > 120 else v
                    for k, v in params.items()
                }
            if detail:
                step["detail"] = detail
            if status_callback:
                status_callback(json.dumps(step))
            return step["step_id"]

        def check_report_sync(prev_state):
            """Helper to emit update signal if report blocks were changed (added/edited/deleted)."""
            if not report_callback:
                return prev_state
            current_state = self.cm.report_engine.get_report_json()
            

            has_changed = (
                current_state["metadata"]["block_count"] != prev_state["metadata"]["block_count"] or
                current_state["metadata"]["last_modified"] != prev_state["metadata"]["last_modified"]
            )
            
            if has_changed:
                report_callback(json.dumps(current_state))
            return current_state # Return new state for next comparison

        try:
            # --- STAGE 1: Intent Interception & Ingestion ---
            q_lower = user_query.strip().lower()
            
            # A. Special Case: Triage Initialization
            is_initial_triage = q_lower == "initialize_case_report"
            if is_initial_triage:
                # Triage is fast, but we'll use a snapshot for the initial state
                initial_report_state = self.cm.report_engine.get_report_json()
                return self._run_python_triage(emit_step, check_report_sync, initial_report_state)

            # B. Special Case: Analyze Context (Triggered after backend/model switch)
            elif q_lower == "analyze_case_context":
                emit_step("thinking", "Analyzing current case context and report structure...", "active")

                # Fetch current report state to feed the model
                current_report_state = self.cm.report_engine.get_report_json()

                # Create a concise analysis prompt
                analysis_prompt = (
                    "SYSTEM TASK: You have just been loaded into this case (or your model was switched). "
                    "Quickly review the current forensic report workspace structure below. "
                    "Acknowledge the current state of the investigation in 1-2 brief sentences and tell the investigator you are ready to continue. "
                    "DO NOT perform any tool calls or extensive analysis yet.\n\n"
                    f"Report Workspace:\n{json.dumps(current_report_state, indent=2)[:4000]}" # Limit size
                )

                try:
                    system_prompt = self.cm._build_system_prompt("", []) # Just get the base prompt

                    analysis_answer = self.cm.model_router.generate(
                        system_prompt=system_prompt,
                        user_message=analysis_prompt,
                        tools=None,
                        history=list(self.cm.history_manager.history)[-5:] # Give it minor history context
                    )

                    ai_content = analysis_answer.get("content", "The case context has been analyzed. I am ready to assist.")

                    # Add only the assistant's acknowledgement to history to keep it clean
                    self.cm.history_manager.add_message("assistant", ai_content)
                    emit_step("synthesis", "Context analysis complete", "done")

                    if self.cm.case_directory:
                        self.cm.history_manager.save_history()

                    return {
                        "response": ai_content,
                        "error": None,
                        "context_stats": self.cm.get_context_stats()
                    }
                except Exception as e:
                    emit_step("synthesis", "Context analysis failed", "error", detail=str(e))
                    return self._handle_generation_failure(e, status_callback)

            # C. Special Case: Switch Model
            elif q_lower == "switch model" or q_lower.startswith("switch model to"):
                target_model = user_query.strip()[16:].strip() if q_lower.startswith("switch model to") else None
                
                emit_step("thinking", "Fetching available models from active agent", "active")
                available_models = self.cm.model_router.list_models()
                
                if not available_models:
                    available_models = ["default"]

                # Case A: User specified a model name directly
                if target_model and any(m.lower() == target_model.lower() for m in available_models):
                    self.cm.model_router.switch_model(target_model)
                    
                    # RESET BUDGET: When switching models, we reset to default budgets (32k)
                    # to prevent "ghost" context limits from the previous model from persisting.
                    self.cm.max_total_tokens = 32000
                    self.cm.token_budget = {
                        "conversation_history": 8000,
                        "system_prompt": 4000,
                        "rag_context": 2000,
                        "tool_results": 4000
                    }
                    self.logger.info(f"Context budget reset to default (32k) following model switch to {target_model}")

                    emit_step("thinking", f"Switched to {target_model}", "done")
                    response = f"Successfully switched active model to **{target_model}**."
                    self.cm.history_manager.add_message("assistant", response)
                    return {"response": response, "error": None, "context_stats": self.cm.get_context_stats()}

                # Case B: User requested the list/menu
                emit_step("thinking", "Model list retrieved", "done")
                model_chips = [{
                    "id": f"switch_{m}", "label": f"Use {m}", "query": f"Switch model to {m}", "icon": "switch"
                } for m in available_models[:5]]
                
                response = "Please select which model you would like to switch to for this agent:"
                return {
                    "response": response, "action_chips": model_chips, "error": None, "context_stats": self.cm.get_context_stats()
                }

            # Regular Query Path
            self.cm.history_manager.add_message("user", user_query)
            
            # --- STAGE 2: Forensic Keyword Analysis ---
            emit_step("thinking", "Scanning query for forensic intents ", "active")
            keywords = self.cm.intent_engine.detect_keywords(user_query)
            emit_step("thinking", f"Detected keywords: {', '.join(keywords) if keywords else 'none'}", "done")
            
            # --- STAGE 3: Knowledge Base (RAG) Lookup ---
            emit_step("rag", "Retrieving artifact knowledge from knowledge base ", "active")
            rag_budget = self.cm.token_budget.get("rag_context", 2000)
            rag_context = self.cm.rag_service.retrieve_context(keywords=keywords, user_query=user_query, max_tokens=rag_budget)
            emit_step("rag", "Forensic knowledge context loaded", "done")
            
            # --- STAGE 4: Prompt Engineering ---
            # Snapshot history and report for stable prompt construction
            with self.cm.history_manager._lock:
                history_snapshot = list(self.cm.history_manager.history)
            
            emit_step("thinking", "Building investigative system prompt ", "active")
            system_prompt = self.cm._build_system_prompt(rag_context, history_snapshot)
            emit_step("thinking", "System prompt ready", "done")
            
            # --- STAGE 5: AI Reasoning & Tool Traceability ---
            MAX_ITERATIONS = 4
            iteration = 0
            
            # Pop the user message added in STAGE 1 so we can manage it dynamically
            self.cm.history_manager.pop_last_message()
            
            current_user_message = user_query
            # Initial state for result aggregation
            initial_report_state = self.cm.report_engine.get_report_json()
            final_option_menu = None
            llm_response = {}
            ai_content = ""
            all_tool_results = []
            tool_call_history = []
            
            active_keywords = set(keywords)
            active_keywords.add("Global_schema_databse_Refrence")
            
            while iteration < MAX_ITERATIONS:
                iteration += 1
                
                if iteration > 1:
                    emit_step("rag", "Updating forensic knowledge context...", "active")
                    rag_budget = self.cm.token_budget.get("rag_context", 2000)
                    rag_context = self.cm.rag_service.retrieve_context(keywords=list(active_keywords), user_query=user_query, max_tokens=rag_budget)
                    
                    with self.cm.history_manager._lock:
                        history_snapshot = list(self.cm.history_manager.history)
                    system_prompt = self.cm._build_system_prompt(rag_context, history_snapshot)
                    emit_step("rag", "Forensic knowledge refreshed", "done")

                model_name = self.cm.model_router.config.get('model_name', 'LLM')
                emit_step("thinking", f"Consulting model: {model_name} (Step {iteration}) ", "active")
                
                try:
                    # AI GENERATION IS NOW OUTSIDE ANY LOCKS - Prevents UI from freezing
                    step_message = current_user_message
                    if iteration > 1:
                        step_message = f"[ORIGINAL GOAL: {user_query}]\n\n{current_user_message}"
                        

                    # Model receives history_snapshot AND step_message. 
                    # If the newest message is already in snapshot, remove it to save tokens.
                    clean_history = history_snapshot
                    if clean_history and clean_history[-1].get("content") == step_message:
                        clean_history = clean_history[:-1]

                    llm_response = self.cm.model_router.generate(
                        system_prompt=system_prompt,
                        user_message=step_message,
                        tools=self.cm._get_tool_definitions(),
                        history=clean_history
                    )
                    emit_step("thinking", "Model response received", "done")
                    
                    self.cm.history_manager.add_message("user", current_user_message)
                    
                    ai_content = llm_response.get("content", "")
                    new_kws = self.cm.intent_engine.detect_keywords(ai_content)
                    for kw in new_kws:
                        active_keywords.add(kw)

                    if "option_menu" in llm_response:
                        final_option_menu = llm_response.get("option_menu")
                    
                    self.cm.history_manager.add_message("assistant", ai_content, {
                        "tool_calls": llm_response.get("tool_calls")
                    })
                        
                except Exception as e:
                    emit_step("thinking", "Model connection failed", "error", detail=str(e))
                    return self._handle_generation_failure(e, status_callback)

                tool_calls = self.cm._parse_tool_calls(llm_response)
                if not tool_calls:
                    emit_step("thinking", "Investigation complete", "done")
                    break
                
                current_calls_signature = [(tc.get("name"), json.dumps(tc.get("parameters", {}), sort_keys=True)) for tc in tool_calls]
                

                # Detects cycles like A -> B -> A by checking last 3 unique turns
                if any(sig == current_calls_signature for sig in tool_call_history[-3:]):
                    emit_step("thinking", "Detected tool call cycle. Breaking cycle.", "done")
                    ai_content += "\n\n*(Detected repetitive tool calls. Providing partial synthesis based on available data.)*"
                    break
                
                tool_call_history.append(current_calls_signature)
                previous_tool_calls = current_calls_signature
                    
                # --- STAGE 6: Tool Execution & Evidence Anchoring ---
                emit_step("thinking", f"Executing {len(tool_calls)} forensic tool(s) ", "active")
                iteration_tool_results = []
                for i, call in enumerate(tool_calls):
                    tool_name = call.get("name", "unknown")
                    emit_step("tool_call", f"Calling tool: {tool_name} ({i+1}/{len(tool_calls)})", "active", tool=tool_name, params=call.get("parameters"))
                    
                    result = self.cm._execute_tool(call, hitl_callback=hitl_callback)
                    iteration_tool_results.append(result)
                    all_tool_results.append(result)
                    
                    status = "done" if result.get("success") else "error"
                    emit_step("tool_call", f"Tool complete: {tool_name}", status, tool=tool_name, detail=result.get("error"))
                
                # Sync report changes to GUI
                initial_report_state = check_report_sync(initial_report_state)

                tool_output_str = json.dumps(iteration_tool_results, indent=2)

                history_tool_output = tool_output_str if len(tool_output_str) <= 10000 else tool_output_str[:10000] + "\n\n... [TRUNCATED IN MEMORY TO 10,000 CHARACTERS. AI MAY NEED TO QUERY SPECIFIC SUBSETS IF EVIDENCE IS MISSING] ..."
                
                new_kws_from_tools = self.cm.intent_engine.detect_keywords(tool_output_str)
                for kw in new_kws_from_tools: active_keywords.add(kw)

                self.cm.history_manager.add_message(
                    "system", f"Investigation Tool Results:\n{history_tool_output}",
                    {"is_tool_result": True, "tool_names": [r.get("tool_name") for r in iteration_tool_results], "iteration": iteration}
                )
                current_user_message = "Analyze the tool results above. If you have enough evidence, provide your final synthesis. If you need more evidence, call another tool."
                
                # Update history snapshot for next turn
                with self.cm.history_manager._lock:
                    history_snapshot = list(self.cm.history_manager.history)

            # --- STAGE 7: Final Forensic Synthesis & Completion ---
            if tool_calls and iteration >= MAX_ITERATIONS:
                emit_step("synthesis", "Max steps reached. Forcing synthesis.", "active")
                synthesis_prompt = self._build_synthesis_prompt(user_query, all_tool_results)
                
                try:
                    final_answer = self.cm.model_router.generate(
                        system_prompt=system_prompt,
                        user_message=synthesis_prompt,
                        tools=[t for t in self.cm._get_tool_definitions() if "report_" in t['name']],
                        history=history_snapshot
                    )
                    ai_content = final_answer.get("content", "")
                    self.cm.history_manager.add_message("user", synthesis_prompt)
                    self.cm.history_manager.add_message("assistant", ai_content)
                    emit_step("synthesis", "Forensic synthesis complete ", "done")
                    check_report_sync(initial_report_state)
                except Exception as e:
                    emit_step("synthesis", "Synthesis failed", "error", detail=str(e))
                    return self._handle_generation_failure(e, status_callback)

            if self.cm.case_directory:
                self.cm.history_manager.save_history()
                
                # Log this investigation step for the Summary Dialog
                try:
                    summary_text = ai_content[:200] + "..." if len(ai_content) > 200 else ai_content
                    # Try to detect if evidence was found based on tool results or keywords
                    evidence_found = any(r.get("success") and len(str(r.get("data", ""))) > 100 for r in all_tool_results)
                    
                    self.cm.case_context_manager.log_investigation_step(
                        query=user_query,
                        response_summary=summary_text,
                        evidence_found=evidence_found,
                        suggested_next_steps="Continue investigation based on AI recommendations." if not final_option_menu else "Select a suggested next step from the menu.",
                        artifacts_queried=list(set([r.get("tool_name") for r in all_tool_results if r.get("tool_name")])),
                        query_type="analysis"
                    )
                except Exception as e:
                    self.logger.error(f"Failed to log investigation step: {e}")
            
            return {
                "response": ai_content,
                "data_viewer": self.cm._extract_data_viewer(all_tool_results),
                "action_chips": self.cm._generate_action_chips(user_query, llm_response, all_tool_results),
                "option_menu": final_option_menu,
                "error": None,
                "context_stats": self.cm.get_context_stats()
            }
            
        except Exception as e:
            self.logger.error(f"Investigation pipeline failed: {e}", exc_info=True)
            emit_step("thinking", "Investigation failed", "error", detail=str(e))
            return {
                "response": "", "error": f"Internal investigation error: {str(e)}", "context_stats": self.cm.get_context_stats()
            }

    def _build_synthesis_prompt(self, query: str, results: List[Dict]) -> str:
        """
        Enforces the 'Forensic Evidence Protocol' for forensic reporting.
        Forces the AI to be technical, chronological, and specific.
        """
        return (
            f"Synthesize findings for investigator query: {query}\n\n"
            f"Tool execution results:\n{json.dumps(results, indent=2)}\n\n"
            "CRITICAL REPORTING MANDATE: THE 7-STEP FORENSIC EVIDENCE PROTOCOL\n"
            "You MUST follow these 7 strict steps in your response and report generation:\n"
            "Step 1: Extract Exact Timestamps (EventTimestampUTC, last_run, or modified).\n"
            "Step 2: Identify Usernames & Domain names involved.\n"
            "Step 3: Extract Process Details (Full file paths, process names, and PIDs).\n"
            "Step 4: Capture Event Descriptions (including success codes and error messages).\n"
            "Step 5: Construct a clear, chronological TIMELINE of the events discovered.\n"
            "Step 6: Explain the forensic significance of each event in the context of the investigation.\n"
            "Step 7: Provide a Direct Answer. You MUST directly and explicitly answer the investigator's query right now. NEVER refer the investigator to a 'SUMMARY OF PREVIOUS ACTIVITY'. DO NOT summarize out technical details.\n\n"
            "PROACTIVE REPORTING: You have reporting tools enabled (`report_append_section`, `report_add_data_table`, `report_add_chart`). "
            "You SHOULD proactively use these tools during this synthesis to build a professional forensic report in the workspace. "
            "If the user asks to 'add to report', use these tools to document your findings."
        )

    def _handle_generation_failure(self, error, status_callback):
        """
        Recovery logic for AI failures.
        Presents the user with alternative model chips to resume the session.
        """
        err_str = str(error)
        is_quota_error = any(msg in err_str.lower() for msg in ["quota", "429", "exhausted", "capacity", "limit"])
        current_model = self.cm.model_router.config.get("model_name")
        
        # Discover fallback options
        model_chips = []
        try:
            available = self.cm.model_router.list_models()
            model_chips = [{
                "id": f"switch_{m}", "label": f"Try {m}", "query": f"Switch model to {m}", "icon": "brain"
            } for m in available if m != current_model]
        except: pass

        # Check for context window limit error
        import re
        context_match = re.search(r"n_ctx:\s*(\d+)", err_str)
        if context_match:
            try:
                # 1. Parse the detected context limit
                detected_limit = int(context_match.group(1))
                if detected_limit > 0:
                    # 2. Apply a SAFETY MARGIN (90%) to account for tokenizer differences
                    # and prevent "off-by-one" token errors.
                    safe_limit = int(detected_limit * 0.9)
                    
                    # 3. Reserve an OUTPUT BUFFER (e.g., 512 tokens) so the model can actually answer.
                    # If the context is tiny, reserve at least 20%.
                    output_buffer = max(512, int(safe_limit * 0.2))
                    available_for_prompt = safe_limit - output_buffer
                    
                    if available_for_prompt < 1000:
                         # Extremely constrained environment (e.g. 2048 ctx)
                         sys_prompt = 800
                         hist = 600
                         rag = 200
                         tools = max(200, available_for_prompt - (sys_prompt + hist + rag))
                    else:
                         # Balanced split for standard context (4096+)
                         sys_prompt = int(available_for_prompt * 0.35)
                         hist = int(available_for_prompt * 0.35)
                         rag = int(available_for_prompt * 0.15)
                         tools = available_for_prompt - (sys_prompt + hist + rag)
                    
                    self.cm.max_total_tokens = detected_limit
                    self.cm.token_budget = {
                        "system_prompt": sys_prompt,
                        "rag_context": rag,
                        "conversation_history": hist,
                        "tool_results": tools
                    }
                    
                    self.logger.warning(f"Auto-adapted token budget for {detected_limit} ctx (Prompt Budget: {available_for_prompt})")
                    
                    response = (
                        f"### ⚙️ Context Window Automatically Adapted\n"
                        f"I detected that your local model has a smaller context limit ({detected_limit} tokens) than expected.\n\n"
                        f"I have automatically optimized my internal forensic budget to fit your model while leaving space for responses. **Please try your query again!**\n\n"
                        f"*(Tip: For better forensic analysis, consider loading the model with a larger context window in LM Studio's settings)*"
                    )
                    
                    return {
                        "response": response, "error": None, "action_chips": model_chips, "context_stats": self.cm.get_context_stats()
                    }
            except Exception as ex:
                self.logger.error(f"Failed to auto-adapt context: {ex}")

        response = (
            f"### ⚠️ Model Connection Failed\n"
            f"The forensic model encountered an error:\n`{err_str}`\n\n"
        )
        if is_quota_error:
            response += (
                "Your current model has exhausted its rate limit. Please wait or "
                "select an alternative model below:"
            )
        else:
            response += (
                "Please verify your API key or server status, or "
                "select an alternative model below:"
            )
        return {
            "success": False, "error": f"Connection failed: {err_str}",
            "data": { "response": response, "action_chips": model_chips[:5] }
        }
