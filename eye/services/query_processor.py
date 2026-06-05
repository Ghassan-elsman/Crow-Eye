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
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable

from eye.services.evidence_seal import EvidenceSeal


_TRANSIENT_ERROR_MARKERS = (
    "500", "502", "503", "504",
    "INTERNAL", "UNAVAILABLE", "DEADLINE_EXCEEDED",
    "timeout", "timed out", "temporarily unavailable",
    "connection reset", "connection aborted",
)


def _is_transient_model_error(exc: Exception) -> bool:
    """A model-call exception is treated as transient (and therefore retryable
    exactly once) only when it looks like a server-side hiccup. Quota / auth /
    bad-request failures are NOT transient and must surface immediately so the
    user can act on them."""
    s = str(exc)
    if any(m in s for m in ("401", "403", "429", "INVALID_ARGUMENT", "PERMISSION_DENIED", "RESOURCE_EXHAUSTED", "quota")):
        return False
    return any(m in s for m in _TRANSIENT_ERROR_MARKERS)


class ContextOverflowError(Exception):
    """Raised when an assembled LLM payload exceeds the model's context window.

    The pipeline REFUSES to proceed (rather than silently truncating evidence)
    so the chain of custody is never quietly broken — the investigator is told
    to narrow the query or use map-reduce analysis.
    """
    def __init__(self, payload_tokens: int, max_context: int, reserve: int):
        self.payload_tokens = payload_tokens
        self.max_context = max_context
        self.reserve = reserve
        super().__init__(
            f"Payload {payload_tokens} tokens exceeds the usable context window "
            f"({max_context} - {reserve} reserved = {max_context - reserve} tokens)."
        )


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

    def _tool_output_char_limit(self) -> int:
        """Max chars of a single tool output kept in memory/history.

        Scales with the window: the ``tool_results`` TOKEN budget (~4 chars/token,
        and itself scaled by ``_scale_token_budget``) sets a ceiling that the
        configured ``max_tool_output_chars`` floors — so a large window is not
        truncated more aggressively than the token budget allows (audit P3 #11).
        Never exceeds ~50% of the usable window for any one tool output, and never
        below a 4000-char minimum.
        """
        max_ctx = int(getattr(self.cm, "max_total_tokens", 8192) or 8192)
        reserve = min(max(512, int(max_ctx * 0.1)), max(1, max_ctx // 2))
        usable = max_ctx - reserve
        configured_char_floor = int(getattr(self.cm, "max_tool_output_chars", 100000) or 100000)
        try:
            tool_results_tokens = int((getattr(self.cm, "token_budget", {}) or {}).get("tool_results", 0))
        except (TypeError, ValueError):
            tool_results_tokens = 0
        token_aware_ceiling = max(configured_char_floor, tool_results_tokens * 4)
        adaptive_char_limit = int(usable * 0.5 * 4)
        return max(4000, min(token_aware_ceiling, adaptive_char_limit))

    def _run_python_triage(self, emit_step, check_report_sync, initial_report_state):
        """
        Comprehensive automated forensic triage.
        Extracts key artifacts across all major categories to build a high-fidelity living report.
        """
        emit_step("tool_call", "Discovering Forensic Databases...", "active")

        # Provenance: triage blocks are machine-generated, not from an investigator
        # question. Stamp a clear source so each block's "From question" card reads
        # meaningfully instead of the raw "initialize_case_report" trigger token
        # (process_query set current_source_query to that token before delegating here).
        if getattr(self.cm, "report_engine", None) is not None:
            self.cm.report_engine.current_source_query = "Eye Automated Triage"

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
            
            # Fallback for schema mismatches (e.g. missing columns in older/newer collectors)
            if not res.get("success") and "no such column" in str(res.get("error", "")).lower():
                # Extract table name from query: "SELECT ... FROM TableName ..."
                table_match = re.search(r"FROM\s+[\"']?(\w+)[\"']?", query, re.IGNORECASE)
                if table_match:
                    table_name = table_match.group(1)
                    self.logger.warning(f"Schema mismatch for {table_name} in {db}. Falling back to SELECT *")
                    res = self.cm.database_service.execute_query(db, f"SELECT * FROM {table_name} LIMIT {limit}")
            
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
             name_res = self.cm.database_service.execute_query(reg_db, "SELECT * FROM ComputerNameInfo LIMIT 1")
             if name_res.get("success") and name_res.get("data"):
                  row = name_res["data"][0]
                  comp_name = row.get("computer_name") or row.get("hostname") or next(iter(row.values()), "Unknown")
        sys_info_md += f"- **Computer Name:** {comp_name}\n"
        
        # Users
        users = []
        if reg_db:
            users_res = self.cm.database_service.execute_query(reg_db, "SELECT * FROM UserProfiles")
            if users_res.get("success") and users_res.get("data"):
                for u in users_res["data"]:
                    val = u.get("username") or u.get("user") or u.get("Name")
                    if val: users.append(str(val))
        
        if users:
            sys_info_md += f"- **Identified Users:** {', '.join(users[:10])}{'...' if len(users) > 10 else ''}\n"
        
        # Timezone
        timezone = "N/A"
        if reg_db:
            tz_res = self.cm.database_service.execute_query(reg_db, "SELECT * FROM TimeZoneInfo LIMIT 1")
            if tz_res.get("success") and tz_res.get("data"):
                row = tz_res["data"][0]
                timezone = row.get("time_zone_name") or row.get("TimeZone") or "N/A"
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
            "Triage Executive Summary Dashboard",
            column_widths={"Category": "25%", "Finding": "75%"},
            category="Automated Triage",
        )

        # Immediate Observations as a TextBlock
        observations_md = f"""
### Immediate Technical Observations
- **System Owner**: {comp_name}
- **Active Users**: {', '.join(users[:5])}{'...' if len(users) > 5 else ''}
- **Remote Protocols**: {', '.join([s['Name'] for s in remote_sw[:3]]) if remote_sw else 'None detected'}

*This report follows the Ghassan Elsman Protocol v2.0 for automated forensic triage.*
"""
        self.cm.report_engine.append_section(
            "Immediate Technical Observations",
            observations_md,
            category="Automated Triage",
        )
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
        report_callback: Optional[Callable[[str], None]] = None,
        dialogue_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """
        Executes the full forensic pipeline.
        """
        self.cm.last_user_query = user_query
        # Stamp the originating question on the report engine so every block
        # created during this query inherits its provenance (see _stamp_and_append).
        if getattr(self.cm, "report_engine", None) is not None:
            self.cm.report_engine.current_source_query = user_query
        import uuid
        step_counter = [0]
        # Pre-bound so the guarded_generate closure can always read it (the
        # analyze_case_context branch calls the model before the main loop's
        # own initialization). The regular path rebinds this list.
        all_tool_results = []
        tool_truncations = []
        # High-water mark: how many tool_truncations have already been folded into
        # a seal. Each tool-output cap is sealed exactly once (in the first seal
        # after it occurred) instead of being re-attached to every subsequent
        # per-iteration seal in this turn.
        tool_trunc_hwm = [0]

        # Eye <-> LLM conversation transcript. Captured per turn (full prompts,
        # the model's reasoning, the tool calls it requested + their results)
        # so the investigator can watch the Eye think live and review the
        # exchange afterward. Streamed via dialogue_callback; also returned.
        conversation: List[Dict[str, Any]] = []
        dialogue_counter = [0]

        def emit_dialogue(entry: Dict[str, Any]) -> None:
            """Record one Eye<->LLM exchange entry and stream it to the UI."""
            dialogue_counter[0] += 1
            entry = dict(entry)
            entry["seq"] = dialogue_counter[0]
            entry["timestamp"] = datetime.now().isoformat()
            conversation.append(entry)
            if dialogue_callback:
                try:
                    dialogue_callback(json.dumps(entry, ensure_ascii=False, default=str))
                except Exception as dlg_exc:
                    self.logger.debug(f"dialogue_callback failed: {dlg_exc}")
            # Persist so the full Eye<->LLM exchange (prompts, reasoning, tool
            # calls + results) is reviewable later in the Compliance panel.
            try:
                self._persist_dialogue(entry, user_query)
            except Exception as persist_exc:
                self.logger.debug(f"Dialogue persistence skipped: {persist_exc}")

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
            # Persist the step so the Compliance panel can show a per-step
            # execution history (grouped by step, one entry per run) with
            # timestamps. Logging must never break the investigation pipeline.
            try:
                self._persist_step(step, user_query)
            except Exception as persist_exc:
                self.logger.debug(f"Step persistence skipped: {persist_exc}")
            return step["step_id"]

        # Chain-of-custody seal for every payload sent to the model this turn.
        # Single persistent writer owned by the ContextManager (one writer per
        # case dir — see ContextManager.__init__) so the hash chain isn't forked
        # or re-read from disk every turn.
        evidence_seal = self.cm.evidence_seal

        def audit_rag_trunc(rag_context, iteration):
            """If RAGService trimmed the knowledge context to fit its budget,
            surface it (step + chain-of-custody audit) instead of letting it be
            silently dropped. RAG knowledge is non-evidence, so this is a
            visibility measure, not an evidence-integrity block."""
            if not rag_context or "RAG Context Truncated" not in rag_context:
                return
            emit_step("rag", "RAG knowledge trimmed to fit its token budget", "error")
            try:
                if getattr(self.cm, "truncation_auditor", None):
                    self.cm.truncation_auditor.log_event(
                        action="TRUNCATED",
                        message_id=f"rag-{iteration}",
                        token_count=self.cm.token_counter.count_tokens(rag_context),
                        reason="rag_context_budget",
                        message_hash=EvidenceSeal._sha256(rag_context),
                        metadata={"iteration": iteration},
                    )
            except Exception:
                pass

        def guarded_generate(system_prompt, user_message, history, tools, *, phase, iteration):
            """Single choke point for every LLM call:
            (1) SELF-HEAL: if the assembled payload exceeds the model's context
                window, automatically shrink it — summarize, then drop — but ONLY
                non-evidence context (never pinned / evidence / tool-result
                messages), logging every reduction. The persistent on-disk
                history is untouched; only this outgoing payload is slimmed.
            (2) FAIL HARD: refuse only when the irreducible evidence core still
                overflows — evidence is never silently dropped.
            (3) SEAL the exact payload sent (hash + provenance) for chain of
                custody, then call the model with one transient-error retry.
            """
            tc = self.cm.token_counter
            try:
                tools_str = json.dumps(tools, default=str) if tools else ""
            except Exception:
                tools_str = str(tools)
            max_ctx = int(getattr(self.cm, "max_total_tokens", 8192) or 8192)
            # Output reserve: 10% (min 512), but never more than half the window
            # so a tiny configured context can't drive `usable` to <= 0. This is
            # the SAME formula as ContextManager.usable_context_tokens() (which
            # HistoryManager.manage_history uses), so the per-call gate and the
            # persistent-history compaction agree on the same window.
            reserve = min(max(512, int(max_ctx * 0.1)), max(1, max_ctx // 2))
            usable = max_ctx - reserve

            base_tokens = tc.count_tokens(system_prompt or "") + tc.count_tokens(user_message or "") + tc.count_tokens(tools_str)

            def payload_tokens(hist):
                return base_tokens + sum(tc.count_tokens(m.get("content") or "") for m in (hist or []))

            def is_protected(m):
                md = m.get("metadata") or {}
                return bool(md.get("pinned") or md.get("preserve_evidence") or md.get("is_tool_result") or md.get("is_summary"))

            working = list(history or [])
            healed = False
            cut_details = []

            # ---- SELF-HEAL: summarize old non-evidence context, then drop ----
            if payload_tokens(working) > usable:
                # Summarize pass (once): collapse non-protected messages.
                non_protected = [m for m in working if not is_protected(m)]
                if len(non_protected) >= 2:
                    try:
                        summary_text = self.cm.history_manager._summarize_chunk(non_protected)
                        if summary_text:
                            summary_msg = {
                                "role": "system",
                                "content": summary_text,
                                "metadata": {"is_summary": True, "self_heal": True},
                            }
                            # Rebuild: keep protected in order; insert the summary
                            # at the position of the first non-protected message.
                            first_np_idx = next((i for i, m in enumerate(working) if not is_protected(m)), len(working))
                            working = [m for m in working if is_protected(m)]
                            working.insert(min(first_np_idx, len(working)), summary_msg)
                            healed = True
                            emit_step("thinking", f"Self-healing: summarized {len(non_protected)} old non-evidence messages to fit context", "active")
                            for m in non_protected:
                                msg_content = m.get("content") or ""
                                cut_details.append(evidence_seal.build_cut_detail(
                                    action="SUMMARIZED",
                                    message_id=m.get("id"),
                                    role=m.get("role"),
                                    original_text=msg_content,
                                    processed_text=summary_text,
                                    dropped_text=msg_content,
                                    token_count=tc.count_tokens(msg_content),
                                ))
                            if getattr(self.cm, "truncation_auditor", None):
                                aggregate_dropped = "\n".join(m.get("content", "") for m in non_protected)
                                agg_detail = evidence_seal.build_cut_detail(
                                    action="SUMMARIZED",
                                    message_id=f"selfheal-{phase}-{iteration}",
                                    role="system",
                                    original_text=aggregate_dropped,
                                    processed_text=summary_text,
                                    dropped_text=aggregate_dropped,
                                    token_count=sum(tc.count_tokens(m.get("content") or "") for m in non_protected),
                                )
                                self.cm.truncation_auditor.log_event(
                                    action="SUMMARIZED",
                                    message_id=f"selfheal-{phase}-{iteration}",
                                    token_count=sum(tc.count_tokens(m.get("content") or "") for m in non_protected),
                                    reason="self_heal_context_fit",
                                    message_hash=EvidenceSeal._sha256(summary_text),
                                    metadata={
                                        "summarized_count": len(non_protected),
                                        "phase": phase,
                                        **agg_detail,
                                    },
                                )
                    except Exception as sum_exc:
                        self.logger.debug(f"Self-heal summarize failed, will drop instead: {sum_exc}")

                # Drop pass: remove oldest non-protected messages until it fits.
                dropped = 0
                while payload_tokens(working) > usable:
                    drop_idx = next((i for i, m in enumerate(working) if not is_protected(m)), None)
                    if drop_idx is None:
                        break  # only protected/evidence left — cannot shrink further
                    removed = working.pop(drop_idx)
                    dropped += 1
                    healed = True
                    removed_content = removed.get("content") or ""
                    drop_detail = evidence_seal.build_cut_detail(
                        action="TRUNCATED",
                        message_id=removed.get("id"),
                        role=removed.get("role"),
                        original_text=removed_content,
                        processed_text="",
                        dropped_text=removed_content,
                        token_count=tc.count_tokens(removed_content),
                    )
                    cut_details.append(drop_detail)
                    if getattr(self.cm, "truncation_auditor", None):
                        try:
                            self.cm.truncation_auditor.log_event(
                                action="TRUNCATED",
                                message_id=removed.get("id", f"selfheal-drop-{phase}-{iteration}"),
                                token_count=tc.count_tokens(removed_content),
                                reason="self_heal_context_fit",
                                message_hash=EvidenceSeal._sha256(removed_content),
                                metadata={"phase": phase, **drop_detail},
                            )
                        except Exception:
                            pass
                if dropped:
                    emit_step("thinking", f"Self-healing: dropped {dropped} oldest non-evidence message(s) to fit context", "active")

            final_tokens = payload_tokens(working)

            # Built once here so the success path and the refusal path below seal
            # the EXACT same payload representation.
            model_name = self.cm.model_router.config.get("model_name", "LLM")

            def _build_full_payload():
                return (
                    f"<<SYSTEM>>\n{system_prompt}\n<<HISTORY>>\n"
                    + "\n".join(f"{m.get('role')}: {m.get('content')}" for m in working)
                    + f"\n<<USER>>\n{user_message}\n<<TOOLS>>\n{tools_str}"
                )

            def _seal_exact_payload(*, token_count, phase_label, sent_to_model):
                """Seal one exact payload + its self-heal cut details and advance
                the tool-truncation high-water mark. Best-effort: a write failure
                is recorded as a visible SEAL_FAILED marker, never swallowed.

                Used for BOTH payloads the model sees (sent_to_model=True) and
                refused over-limit payloads (sent_to_model=False) so the chain of
                custody records refusals and the cuts that occurred before them —
                not only what was actually sent.
                """
                full_payload = _build_full_payload()
                try:
                    # tool_truncations is bound in the enclosing process_query scope.
                    # Fold in only the tool-output caps not yet sealed, so each is
                    # recorded exactly once across this turn's per-iteration seals.
                    combined_cut_details = list(cut_details)
                    combined_cut_details.extend(tool_truncations[tool_trunc_hwm[0]:])
                    evidence_seal.seal(
                        full_payload,
                        phase=phase_label, iteration=iteration, query=user_query,
                        model=model_name, max_context=max_ctx, token_count=token_count,
                        evidence_refs=EvidenceSeal.extract_evidence_refs(all_tool_results),
                        truncated=healed or not sent_to_model,
                        cut_details=combined_cut_details,
                        sent_to_model=sent_to_model,
                        # A refusal is exceptional evidence — always persist the
                        # original message, even if routine full-payload storage is off.
                        force_full_payload=not sent_to_model,
                    )
                    # Advance only after a successful seal so a failed write doesn't
                    # silently drop these truncations from the record.
                    tool_trunc_hwm[0] = len(tool_truncations)
                except Exception as seal_exc:
                    # A skipped seal is a chain-of-custody gap — never swallow it
                    # silently. Record a tamper-evident marker and surface an error
                    # step so the gap is itself provable.
                    self.logger.error(f"Evidence seal FAILED for {phase_label} iter {iteration}: {seal_exc}", exc_info=True)
                    try:
                        if getattr(self.cm, "truncation_auditor", None):
                            self.cm.truncation_auditor.log_event(
                                action="SEAL_FAILED",
                                message_id=f"seal-{phase_label}-{iteration}",
                                token_count=token_count,
                                reason="evidence_seal_write_error",
                                message_hash=EvidenceSeal._sha256(full_payload),
                                metadata={"phase": phase_label, "error": str(seal_exc)},
                            )
                    except Exception:
                        pass
                    emit_step(
                        "thinking",
                        "Evidence seal could not be written — chain-of-custody gap recorded in audit trail",
                        "error",
                        detail=str(seal_exc),
                    )

            # ---- FAIL HARD: irreducible evidence core still overflows ----
            if final_tokens > usable:
                # Bounded preview of the ORIGINAL message we refused, so Context
                # Events shows what was refused (full bytes live in the seal sidecar).
                _refused_payload = _build_full_payload()
                _refused_preview = _refused_payload[:4000]
                try:
                    if getattr(self.cm, "truncation_auditor", None):
                        self.cm.truncation_auditor.log_event(
                            action="REFUSED_OVERFLOW",
                            message_id=f"turn-{iteration}",
                            token_count=final_tokens,
                            reason="evidence_core_exceeds_context_after_self_heal",
                            message_hash=EvidenceSeal._sha256(_refused_payload),
                            metadata={
                                "max_context": max_ctx, "reserve": reserve, "phase": phase,
                                "self_healed": healed,
                                # The original message (bounded) + its hash for full recovery.
                                "cut_content": _refused_preview,
                                "payload_sha256": EvidenceSeal._sha256(_refused_payload),
                            },
                        )
                except Exception:
                    pass
                emit_step(
                    "thinking",
                    "Evidence core exceeds context window even after auto-compaction — refusing to truncate evidence",
                    "error",
                    detail=f"{final_tokens} tokens > usable {usable} (model limit {max_ctx})",
                )
                # Seal the refused over-limit payload (flagged sent_to_model=False)
                # so the Compliance panels show WHAT we refused to send and the
                # self-heal cuts that occurred — instead of nothing at all.
                _seal_exact_payload(
                    token_count=final_tokens,
                    phase_label=f"{phase}:REFUSED_OVERFLOW",
                    sent_to_model=False,
                )
                raise ContextOverflowError(final_tokens, max_ctx, reserve)

            # Seal the EXACT (possibly slimmed) payload the model will see.
            _seal_exact_payload(token_count=final_tokens, phase_label=phase, sent_to_model=True)

            try:
                return self.cm.model_router.generate(
                    system_prompt=system_prompt, user_message=user_message,
                    tools=tools, history=working,
                )
            except Exception as gen_exc:
                if _is_transient_model_error(gen_exc):
                    self.logger.warning(f"Transient model error, retrying once: {gen_exc}")
                    emit_step("thinking", "Model returned a transient error — retrying", "active")
                    time.sleep(1.5)
                    # Retry with `working` (the slimmed, self-healed history that
                    # was SEALED above) — never the original `history`, which may
                    # exceed the window and would not match the evidence seal.
                    return self.cm.model_router.generate(
                        system_prompt=system_prompt, user_message=user_message,
                        tools=tools, history=working,
                    )
                raise

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

                    _ctx_history = list(self.cm.history_manager.history)[-5:]  # minor history context
                    # Record this Eye<->LLM exchange so it appears in the
                    # Compliance conversation log like every other turn.
                    emit_dialogue({
                        "phase": "request",
                        "iteration": None,
                        "system_prompt": system_prompt,
                        "user_message": analysis_prompt,
                        "tools_offered": [],
                        "history_count": len(_ctx_history),
                    })

                    analysis_answer = guarded_generate(
                        system_prompt, analysis_prompt, _ctx_history, None,
                        phase="request", iteration=None,
                    )

                    ai_content = analysis_answer.get("content", "The case context has been analyzed. I am ready to assist.")

                    emit_dialogue({
                        "phase": "response",
                        "iteration": None,
                        "content": ai_content,
                        "tool_calls": [],
                    })

                    # Add only the assistant's acknowledgement to history to keep it clean
                    self.cm.history_manager.add_message("assistant", ai_content)
                    emit_step("synthesis", "Context analysis complete", "done")

                    if self.cm.case_directory:
                        self.cm.history_manager.save_history()

                    return {
                        "response": ai_content,
                        "eye_llm_conversation": conversation,
                        "error": None,
                        "context_stats": self.cm.get_context_stats()
                    }
                except ContextOverflowError:
                    raise  # fail hard — handled by the outer refusal handler
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
                    
                    # RE-RESOLVE WINDOW: clear the previous model's "ghost" context
                    # limit, then size max_total_tokens to the NEW model's real
                    # window (registry for cloud; 32k fallback for unknown, with the
                    # local n_ctx probe still able to override downward at call time).
                    self.cm.max_total_tokens = self.cm._resolve_context_window(
                        getattr(self.cm, "default_max_total_tokens", 64000)
                    )
                    self.cm.token_budget = self.cm._resolve_token_budget()
                    self.logger.info(
                        f"Context window re-resolved to {self.cm.max_total_tokens:,} tokens "
                        f"(budget {self.cm.token_budget}) following model switch to {target_model}"
                    )

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
            audit_rag_trunc(rag_context, 1)
            _rag_sections = rag_context.count("## ") if rag_context else 0
            emit_step(
                "rag",
                f"Loaded {_rag_sections} knowledge section(s)" if _rag_sections
                else "No matching knowledge base entries",
                "done",
            )
            
            # --- STAGE 4: Prompt Engineering ---
            # Snapshot history and report for stable prompt construction
            with self.cm.history_manager._lock:
                history_snapshot = list(self.cm.history_manager.history)
            
            emit_step("thinking", "Building investigative system prompt ", "active")
            system_prompt = self.cm._build_system_prompt(rag_context, history_snapshot)
            emit_step("thinking", "System prompt ready", "done")
            
            # --- STAGE 5: AI Reasoning & Tool Traceability ---
            # Budget sized so the Eye can keep going until it has gathered the
            # evidence it needs: up to MAX_CONTINUE_NUDGES "keep going" prods plus
            # the actual tool rounds of a full multi-database sweep. Each nudge
            # consumes an iteration, so MAX_ITERATIONS must exceed the nudge cap.
            MAX_ITERATIONS = 20
            MAX_CONTINUE_NUDGES = 10
            continue_nudges = 0
            failing_cycle_hinted = False
            iteration = 0
            
            # Pop the user message added in STAGE 1 so we can manage it dynamically
            popped_user_msg = self.cm.history_manager.pop_last_message()
            
            current_user_message = user_query
            # Initial state for result aggregation
            initial_report_state = self.cm.report_engine.get_report_json()
            final_option_menu = None
            llm_response = {}
            ai_content = ""
            all_tool_results = []
            ledger_entries = []  # compact per-iteration index for cross-source correlation
            tool_call_history = []
            
            active_keywords = set(keywords)
            active_keywords.add("Global_schema_database_Reference")
            
            while iteration < MAX_ITERATIONS:
                iteration += 1
                
                # RE-INSERT USER QUERY: If we just started and tools were run, 
                # we must ensure the original question is back in the persistent log.
                if iteration == 1 and popped_user_msg:
                    self.cm.history_manager.add_message(
                        popped_user_msg["role"], 
                        popped_user_msg["content"], 
                        popped_user_msg.get("metadata")
                    )
                
                if iteration > 1:
                    emit_step("rag", "Updating forensic knowledge context...", "active")
                    rag_budget = self.cm.token_budget.get("rag_context", 2000)
                    rag_context = self.cm.rag_service.retrieve_context(keywords=list(active_keywords), user_query=user_query, max_tokens=rag_budget)
                    audit_rag_trunc(rag_context, iteration)

                    with self.cm.history_manager._lock:
                        history_snapshot = list(self.cm.history_manager.history)
                    system_prompt = self.cm._build_system_prompt(rag_context, history_snapshot)
                    _rag_sections = rag_context.count("## ") if rag_context else 0
                    emit_step(
                        "rag",
                        f"Knowledge refreshed: {_rag_sections} section(s)" if _rag_sections
                        else "Knowledge refreshed: no matching entries",
                        "done",
                    )

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

                    # Cross-iteration evidence ledger: prepend the compact per-step
                    # index to the OUTGOING message so the model can correlate
                    # across every tool/database it has run — without bloating the
                    # persisted history (only step_message is stored, below).
                    ledger_text = self._build_evidence_ledger(ledger_entries)
                    outgoing_message = (ledger_text + "\n\n" + step_message) if ledger_text else step_message

                    _tool_defs = self.cm._get_tool_definitions()
                    # Record what the Eye SENT to the model this turn (full prompt).
                    emit_dialogue({
                        "phase": "request",
                        "iteration": iteration,
                        "system_prompt": system_prompt,
                        "user_message": outgoing_message,
                        "tools_offered": [t.get("name") for t in _tool_defs],
                        "history_count": len(clean_history),
                    })
                    # Guarded: fail-hard on context overflow + seal the payload.
                    llm_response = guarded_generate(
                        system_prompt, outgoing_message, clean_history, _tool_defs,
                        phase="request", iteration=iteration,
                    )

                    # Record what the model REPLIED (reasoning + requested tools),
                    # and make the milestone label reflect the real outcome.
                    _resp_content = (llm_response.get("content") or "").strip()
                    _resp_tcs = self.cm._parse_tool_calls(llm_response)
                    emit_dialogue({
                        "phase": "response",
                        "iteration": iteration,
                        "content": _resp_content,
                        "tool_calls": [
                            {"name": tc.get("name"), "arguments": tc.get("parameters", {})}
                            for tc in _resp_tcs
                        ],
                    })
                    if _resp_content and _resp_tcs:
                        _resp_label = f"Model replied: reasoning + {len(_resp_tcs)} tool call(s)"
                    elif _resp_content:
                        _resp_label = "Model replied (text only)"
                    elif _resp_tcs:
                        _resp_label = f"Model requested {len(_resp_tcs)} tool call(s), no text"
                    else:
                        _resp_label = "Model returned an empty response"
                    emit_step("thinking", _resp_label, "done")

                    if iteration > 1:
                        self.cm.history_manager.add_message("user", step_message, {"internal": True})
                    
                    ai_content = llm_response.get("content", "")
                    new_kws = self.cm.intent_engine.detect_keywords(ai_content)
                    for kw in new_kws:
                        active_keywords.add(kw)

                    if "option_menu" in llm_response:
                        final_option_menu = llm_response.get("option_menu")
                    
                    self.cm.history_manager.add_message("assistant", ai_content, {
                        "tool_calls": llm_response.get("tool_calls")
                    })
                        
                except ContextOverflowError:
                    raise  # fail hard — handled by the outer refusal handler
                except Exception as e:
                    emit_step("thinking", "Model connection failed", "error", detail=str(e))
                    return self._handle_generation_failure(e, status_callback)

                tool_calls = self.cm._parse_tool_calls(llm_response)
                if not tool_calls:
                    # The model produced text but no tool call. If it signaled it
                    # would keep going (e.g. "I will now check prefetch…"), it has
                    # NOT finished — nudge it to actually act instead of ending the
                    # turn and waiting for the user. Bounded to avoid runaway.
                    _lc = (ai_content or "").lower()
                    _intent = any(p in _lc for p in (
                        "i will now", "i'll now", "i will next", "next, i", "next i",
                        "let me", "proceed to", "i will search", "i will check",
                        "i will query", "i will examine", "i will investigate",
                        "now investigate", "to further investigate", "i will look",
                        "i'm going to", "i am going to", "let's", "i will proceed",
                    ))
                    if _intent and continue_nudges < MAX_CONTINUE_NUDGES:
                        continue_nudges += 1
                        emit_step("thinking", f"Model narrated next steps without acting — continuing the investigation (nudge {continue_nudges})", "active")
                        current_user_message = (
                            "You stated a next step but did NOT call any tool. Do NOT stop or wait "
                            "for the user. Emit the tool call(s) for that next step now, and keep "
                            "checking every relevant database in sequence until you have actually "
                            "answered the question."
                        )
                        self.cm.history_manager.add_message("user", current_user_message, {"internal": True})
                        with self.cm.history_manager._lock:
                            history_snapshot = list(self.cm.history_manager.history)
                        continue
                    emit_step("thinking", "Investigation complete", "done")
                    break

                current_calls_signature = [(tc.get("name"), json.dumps(tc.get("parameters", {}), sort_keys=True)) for tc in tool_calls]


                # Detects cycles like A -> B -> A by checking last 3 unique turns
                if any(sig == current_calls_signature for sig in tool_call_history[-3:]):
                    # If the repeated calls were FAILING, give one corrective hint
                    # (use the schema reference / query directly / move on) before
                    # breaking — repeating a failing get_schema shouldn't end the run.
                    _recent_failed = any(
                        (not r.get("success")) for r in all_tool_results[-len(tool_calls):]
                    ) if all_tool_results else False
                    if _recent_failed and not failing_cycle_hinted:
                        failing_cycle_hinted = True
                        emit_step("thinking", "Repeated failing tool call — steering to an alternative", "active")
                        current_user_message = (
                            "That tool call keeps FAILING — do NOT repeat it identically. Use the "
                            "Global Schema Reference for the table's columns, or query the table "
                            "directly with a known column, or move on to the next relevant database. "
                            "Continue the investigation."
                        )
                        self.cm.history_manager.add_message("user", current_user_message, {"internal": True})
                        with self.cm.history_manager._lock:
                            history_snapshot = list(self.cm.history_manager.history)
                        continue
                    emit_step("thinking", "Detected tool call cycle. Breaking cycle.", "done")
                    ai_content += "\n\n*(Detected repetitive tool calls. Providing partial synthesis based on available data.)*"
                    break

                tool_call_history.append(current_calls_signature)

                # --- STAGE 6: Tool Execution & Evidence Anchoring ---
                emit_step("thinking", f"Executing {len(tool_calls)} forensic tool(s) ", "active")
                iteration_tool_results = []
                for i, call in enumerate(tool_calls):
                    tool_name = call.get("name", "unknown")
                    emit_step("tool_call", f"Calling tool: {tool_name} ({i+1}/{len(tool_calls)})", "active", tool=tool_name, params=call.get("parameters"))
                    
                    result = self.cm._execute_tool(call, hitl_callback=hitl_callback)
                    iteration_tool_results.append(result)
                    all_tool_results.append(result)
                    # Compact ledger entry (cross-iteration correlation index).
                    ledger_entries.append({
                        "iteration": iteration,
                        "tool": tool_name,
                        "params": call.get("parameters"),
                        "result": result.get("result") if isinstance(result.get("result"), dict) else result,
                    })

                    status = "done" if result.get("success") else "error"
                    emit_step("tool_call", f"Tool complete: {tool_name}", status, tool=tool_name, detail=result.get("error"))

                    # Record the tool result fed back to the model.
                    try:
                        _result_str = json.dumps(result, ensure_ascii=False, default=str)
                    except Exception:
                        _result_str = str(result)
                    emit_dialogue({
                        "phase": "tool_result",
                        "iteration": iteration,
                        "tool_name": tool_name,
                        "parameters": call.get("parameters", {}),
                        "success": bool(result.get("success")),
                        "result": _result_str[:4000] + (" …[truncated]" if len(_result_str) > 4000 else ""),
                    })
                
                # Sync report changes to GUI
                initial_report_state = check_report_sync(initial_report_state)

                tool_output_str = json.dumps(iteration_tool_results, indent=2)

                # Token-aware, window-scaled cap on a single tool output (P3 #11).
                tool_output_limit = self._tool_output_char_limit()

                if len(tool_output_str) <= tool_output_limit:
                    history_tool_output = tool_output_str
                else:
                    # Never trim evidence silently: surface it as a step and log
                    # it to the chain-of-custody audit trail.
                    history_tool_output = tool_output_str[:tool_output_limit] + f"\n\n... [TRUNCATED IN MEMORY TO {tool_output_limit:,} CHARACTERS. AI MAY NEED TO QUERY SPECIFIC SUBSETS IF EVIDENCE IS MISSING] ..."
                    emit_step(
                        "tool_call",
                        f"Tool output trimmed in memory ({len(tool_output_str):,}→{tool_output_limit:,} chars) — query a narrower subset if evidence is missing",
                        "error",
                    )
                    try:
                        tool_detail = evidence_seal.build_cut_detail(
                            action="TRUNCATED_TOOL_OUTPUT",
                            message_id=f"tool-output-iter-{iteration}",
                            role="tool",
                            original_text=tool_output_str,
                            processed_text=tool_output_str[:tool_output_limit],
                            dropped_text=tool_output_str[tool_output_limit:],
                            token_count=len(tool_output_str),
                            iteration=iteration,
                            processed_is_prefix=True,  # kept head is a literal prefix of the output
                        )
                        tool_truncations.append(tool_detail)
                        if getattr(self.cm, "truncation_auditor", None):
                            self.cm.truncation_auditor.log_event(
                                action="TRUNCATED",
                                message_id=f"tool-output-iter-{iteration}",
                                token_count=len(tool_output_str),
                                reason=f"tool_output_memory_cap_{tool_output_limit}_chars",
                                message_hash=EvidenceSeal._sha256(tool_output_str),
                                metadata={"kept_chars": tool_output_limit, **tool_detail},
                            )
                    except Exception:
                        pass

                new_kws_from_tools = self.cm.intent_engine.detect_keywords(tool_output_str)
                for kw in new_kws_from_tools: active_keywords.add(kw)

                # GEP Rule 6 (Tool Traceability): prepend an LLM-visible header
                # listing every tool call in this iteration with its name + iteration
                # index BEFORE the JSON payload, so the next model turn sees the trace
                # literally in the message content (not just in metadata).
                N = len(iteration_tool_results)
                trace_header = "\n".join(
                    f"[Tool {i + 1}/{N}: {r.get('tool_name', 'unknown')}, iteration {iteration}]"
                    for i, r in enumerate(iteration_tool_results)
                )

                # Stored as a "user"-role turn (not "system") so it stays in
                # chronological order after the assistant's tool call: the
                # backend message sanitizer hoists ALL system messages into one
                # leading block, which would otherwise flatten the
                # tool-call -> tool-result sequence the model needs to reason
                # across iterations. The is_tool_result metadata still drives
                # the Activity audit and GEP Rule 6 (both key on metadata).
                self.cm.history_manager.add_message(
                    "user",
                    f"{trace_header}\nInvestigation Tool Results:\n{history_tool_output}",
                    {"is_tool_result": True, "tool_names": [r.get("tool_name") for r in iteration_tool_results], "iteration": iteration}
                )
                current_user_message = (
                    "Analyze the tool results above. If the question asks whether something "
                    "exists / was installed / was run, you are NOT finished until you have "
                    "checked EVERY relevant database in sequence (Amcache, Prefetch, Registry "
                    "Uninstall keys, ShimCache, SRUM, MFT) — do not stop after one database "
                    "returns nothing, and do not hand back to the investigator mid-sweep. "
                    "If you have genuinely enough evidence, provide your final synthesis; "
                    "otherwise call the next tool now."
                )
                
                # Update history snapshot for next turn
                with self.cm.history_manager._lock:
                    history_snapshot = list(self.cm.history_manager.history)

            # --- STAGE 7: Final Forensic Synthesis & Completion ---
            # Force a synthesis pass whenever the iteration loop exited without
            # a usable text answer. Three triggers:
            #   1. Hit MAX_ITERATIONS while still calling tools (original case).
            #   2. Model returned empty text content on the breaking turn — Gemini
            #      often does this after tool calls, leaving ai_content = "".
            #   3. Tools were run earlier but no synthesis text was produced — the
            #      investigator deserves an answer AND the report needs the findings.
            hit_max_iter = bool(tool_calls and iteration >= MAX_ITERATIONS)
            empty_response = not (ai_content or "").strip()
            tools_were_run_but_no_synthesis = bool(all_tool_results) and empty_response
            needs_synthesis = hit_max_iter or empty_response or tools_were_run_but_no_synthesis

            if needs_synthesis:
                if hit_max_iter:
                    reason = "Max steps reached"
                elif tools_were_run_but_no_synthesis:
                    reason = "Tools executed but model returned no synthesis"
                else:
                    reason = "Model returned empty text — forcing synthesis"
                emit_step("synthesis", f"{reason}. Forcing synthesis.", "active")
                synthesis_prompt = self._build_synthesis_prompt(
                    user_query, all_tool_results,
                    ledger_text=self._build_evidence_ledger(ledger_entries),
                )
                _synth_tools = [t for t in self.cm._get_tool_definitions() if "report_" in t['name']]
                emit_dialogue({
                    "phase": "synthesis_request",
                    "iteration": iteration,
                    "system_prompt": system_prompt,
                    "user_message": synthesis_prompt,
                    "tools_offered": [t.get("name") for t in _synth_tools],
                    "history_count": len(history_snapshot),
                })

                try:
                    final_answer = guarded_generate(
                        system_prompt, synthesis_prompt, history_snapshot, _synth_tools,
                        phase="synthesis_request", iteration=iteration,
                    )
                    synthesis_content = (final_answer.get("content") or "").strip()

                    synthesis_tool_calls = self.cm._parse_tool_calls(final_answer)

                    emit_dialogue({
                        "phase": "synthesis_response",
                        "iteration": iteration,
                        "content": synthesis_content,
                        "tool_calls": [
                            {"name": tc.get("name"), "arguments": tc.get("parameters", {})}
                            for tc in synthesis_tool_calls
                        ],
                    })

                    # Execute the report_* tool calls FIRST so we know whether the
                    # write actually succeeded before we make any claim about it in
                    # chat. Failures are recorded (not swallowed) so the truthful-claim
                    # logic below and the audit trail both see them.
                    report_persisted = False
                    report_attempted = False
                    for call in synthesis_tool_calls:
                        if (call.get("name") or "").startswith("report_"):
                            report_attempted = True
                            try:
                                tool_result = self.cm._execute_tool(call, hitl_callback=hitl_callback)
                                all_tool_results.append(tool_result)
                                if tool_result.get("success"):
                                    report_persisted = True
                            except Exception as exec_exc:
                                self.logger.error(f"Synthesis-time report tool failed: {exec_exc}")
                                all_tool_results.append({
                                    "tool_name": call.get("name"),
                                    "success": False,
                                    "error": str(exec_exc),
                                })

                    if synthesis_content:
                        ai_content = synthesis_content
                    else:
                        # The model documented to the report but gave us no chat text.
                        # The investigator reads chat first, so force a dedicated
                        # text-only pass that MUST answer conversationally (no tools).
                        emit_step("synthesis", "No chat answer returned — generating direct answer", "active")
                        text_prompt = self._build_synthesis_prompt(
                            user_query, all_tool_results, text_only=True,
                            ledger_text=self._build_evidence_ledger(ledger_entries),
                        )
                        emit_dialogue({
                            "phase": "synthesis_request",
                            "iteration": iteration,
                            "system_prompt": system_prompt,
                            "user_message": text_prompt,
                            "tools_offered": [],
                            "history_count": len(history_snapshot),
                        })
                        text_answer = {}
                        try:
                            text_answer = guarded_generate(
                                system_prompt, text_prompt, history_snapshot, [],
                                phase="synthesis_request", iteration=iteration,
                            )
                        except ContextOverflowError:
                            raise  # fail hard — handled by the outer refusal handler
                        except Exception as text_exc:
                            self.logger.error(f"Text-only synthesis pass failed: {text_exc}")

                        ai_content = (text_answer.get("content") or "").strip()
                        emit_dialogue({
                            "phase": "synthesis_response",
                            "iteration": iteration,
                            "content": ai_content,
                            "tool_calls": [],
                        })

                        if not ai_content:
                            # Last-resort placeholder — kept HONEST. Base the report
                            # claim on whether ANY report_* write actually succeeded
                            # across the WHOLE turn (not just this synthesis pass).
                            def _is_report(r):
                                return (r.get("tool_name") or r.get("name") or "").startswith("report_")
                            turn_report_attempted = report_attempted or any(_is_report(r) for r in all_tool_results)
                            turn_report_persisted = report_persisted or any(_is_report(r) and r.get("success") for r in all_tool_results)
                            successful = [r.get("tool_name") for r in all_tool_results if r.get("success")]
                            unique = sorted({n for n in successful if n})
                            unique_str = ', '.join(unique) if unique else 'the requested tools'
                            ai_content = (
                                "Investigator, I have completed the analysis using the following tools: "
                                f"**{unique_str}**. "
                            )
                            if turn_report_persisted:
                                ai_content += "The findings have been documented in the Forensic Report pane for your review. How would you like to proceed?"
                            elif turn_report_attempted:
                                ai_content += "I attempted to document the findings to the Forensic Report, but the write did not succeed — please review the evidence in this conversation. How would you like to proceed?"
                            else:
                                ai_content += "How would you like to proceed?"

                    self.cm.history_manager.add_message("user", synthesis_prompt, {"internal": True})
                    self.cm.history_manager.add_message("assistant", ai_content)
                    emit_step("synthesis", "Forensic synthesis complete ", "done")
                    check_report_sync(initial_report_state)
                except ContextOverflowError:
                    raise  # fail hard — handled by the outer refusal handler
                except Exception as e:
                    emit_step("synthesis", "Synthesis failed", "error", detail=str(e))
                    return self._handle_generation_failure(e, status_callback)

            # Guarantee the Forensic Report is never empty when the Eye actually
            # investigated: if tools ran and we produced a substantive answer but
            # the model did NOT persist a report_* block this turn, auto-document
            # the findings. Covers both exit paths (forced synthesis and a plain
            # final answer) and both surfaces (Case Summary + live report pane).
            try:
                _report_written = any(
                    (r.get("tool_name") or r.get("name") or "").startswith("report_") and r.get("success")
                    for r in all_tool_results
                )
                if all_tool_results and (ai_content or "").strip() and not _report_written \
                        and getattr(self.cm, "report_engine", None):
                    self.cm.report_engine.append_section(
                        f"Investigation Findings: {user_query[:80]}",
                        ai_content,
                        author="ai",
                        category="Investigation Findings",
                    )
                    self.cm.report_engine.save_report()
                    check_report_sync(initial_report_state)
                    emit_step("synthesis", "Findings auto-documented to the Forensic Report", "done")
            except Exception as e:
                self.logger.error(f"Auto-persist findings failed: {e}")

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

            # Per-answer GEP compliance: evaluate the behavioral rules for this
            # turn and persist so the Compliance panel can show, per question,
            # whether the Eye actually followed the protocol.
            gep_turn = None
            try:
                gep_turn = self._evaluate_gep_turn(user_query, ai_content, all_tool_results)
                self._persist_gep_turn(gep_turn)
            except Exception as e:
                self.logger.debug(f"GEP turn evaluation skipped: {e}")

            return {
                "response": ai_content,
                "data_viewer": self.cm._extract_data_viewer(all_tool_results),
                "action_chips": self.cm._generate_action_chips(user_query, llm_response, all_tool_results),
                "option_menu": final_option_menu,
                "eye_llm_conversation": conversation,
                "gep_turn": gep_turn,
                "error": None,
                "context_stats": self.cm.get_context_stats()
            }
            
        except ContextOverflowError as oe:
            # FAIL HARD, never silently truncate. Refuse and tell the
            # investigator how to proceed so the chain of custody stays intact.
            self.logger.warning(f"Refused over-context payload: {oe}")
            usable = oe.max_context - oe.reserve
            refusal = (
                "**The evidence is too large to read in one pass — even after automatic compaction.**\n\n"
                f"The irreducible evidence core ({oe.payload_tokens:,} tokens) still exceeds what this "
                f"model can safely read ({usable:,} usable of {oe.max_context:,}). I auto-summarized and "
                "trimmed the non-evidence context but will **not** silently drop the evidence itself.\n\n"
                "**Recommended:** re-run this as **`analyze_large_dataset`** (map-reduce) — it analyzes the "
                "full artifact in sealed, token-sized chunks so nothing is dropped.\n"
                "Alternatively: narrow the query (tighter time range / specific user or path / a `LIMIT`), "
                "or switch to a model with a larger context window."
            )
            return {
                "response": refusal,
                "error": "context_overflow",
                "context_stats": self.cm.get_context_stats(),
            }
        except Exception as e:
            self.logger.error(f"Investigation pipeline failed: {e}", exc_info=True)
            emit_step("thinking", "Investigation failed", "error", detail=str(e))
            return {
                "response": "", "error": f"Internal investigation error: {str(e)}", "context_stats": self.cm.get_context_stats()
            }

    def _persist_step(self, step: Dict[str, Any], user_query: str) -> None:
        """Append a pipeline step to the per-case step log so the Compliance
        panel can render a grouped, timestamped execution history.

        Written as JSON-lines to ``<case>/EYE_Logs/eye_step_log.jsonl`` (same
        EYE_Logs convention used by ReportEngine.save_report). No-ops silently
        when there is no active case directory.
        """
        case_dir = getattr(self.cm, "case_directory", None)
        if not case_dir:
            return
        logs_dir = os.path.join(str(case_dir), "EYE_Logs")
        os.makedirs(logs_dir, exist_ok=True)
        log_path = os.path.join(logs_dir, "eye_step_log.jsonl")
        entry = dict(step)
        entry["query"] = user_query
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _persist_dialogue(self, entry: Dict[str, Any], user_query: str) -> None:
        """Append one Eye<->LLM conversation entry to the per-case dialogue log
        so the full exchange (prompts, reasoning, tool calls + results) can be
        reviewed in the Compliance panel.

        Written as JSON-lines to ``<case>/EYE_Logs/eye_dialogue_log.jsonl``.
        No-ops silently when there is no active case directory.
        """
        case_dir = getattr(self.cm, "case_directory", None)
        if not case_dir:
            return
        logs_dir = os.path.join(str(case_dir), "EYE_Logs")
        os.makedirs(logs_dir, exist_ok=True)
        log_path = os.path.join(logs_dir, "eye_dialogue_log.jsonl")
        record = dict(entry)
        record["query"] = user_query
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    # Investigative (read) tools whose use signals proactive investigation.
    _INVESTIGATIVE_TOOLS = {
        "query_database", "search_artifacts", "query_correlation_results",
        "list_case_files", "get_schema", "query_threat_intel",
        "query_living_off_the_land_intel",
    }
    _TIMESTAMP_RE = re.compile(
        r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}"          # ISO-ish 2024-03-12 14:02
        r"|\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|UTC)"  # 10:42 PM / 14:02 UTC
    )

    @staticmethod
    def _tool_succeeded(r: Dict[str, Any]) -> bool:
        """A tool result counts as successful when neither the executor wrapper
        nor the handler payload reported failure."""
        if not r.get("success", False):
            return False
        inner = r.get("result")
        if isinstance(inner, dict) and inner.get("success") is False:
            return False
        return True

    def _evaluate_gep_turn(self, user_query, ai_content, all_tool_results):
        """Evaluate the objectively-checkable BEHAVIORAL GEP rules for one
        answered turn so the investigator can confirm, per answer, that the Eye
        followed the protocol. Returns a record with per-rule PASS/FAIL/N-A.
        """
        ai_content = ai_content or ""
        investigative = [r for r in all_tool_results
                         if (r.get("tool_name") or "") in self._INVESTIGATIVE_TOOLS]
        investigative_ok = [r for r in investigative if self._tool_succeeded(r)]
        report_ok = [r for r in all_tool_results
                     if (r.get("tool_name") or "").startswith("report_") and self._tool_succeeded(r)]
        evidence_present = bool(investigative_ok)

        checks = []

        # R13 — Direct Answer Protocol: a substantive chat answer must exist.
        substantive = len(ai_content.strip()) >= 40
        checks.append({
            "id": 13, "name": "Direct Answer (R13)",
            "status": "PASS" if substantive else "FAIL",
            "detail": f"chat answer is {len(ai_content.strip())} chars"
                      if substantive else "no substantive chat answer produced",
        })

        # R17 — Dual Output: an evidence-bearing turn must also persist a report_* block.
        if not evidence_present:
            checks.append({"id": 17, "name": "Dual Output (R17)", "status": "N-A",
                           "detail": "no forensic evidence produced this turn"})
        elif report_ok:
            checks.append({"id": 17, "name": "Dual Output (R17)", "status": "PASS",
                           "detail": f"evidence answered in chat AND {len(report_ok)} report block(s) persisted"})
        else:
            checks.append({"id": 17, "name": "Dual Output (R17)", "status": "FAIL",
                           "detail": "evidence produced but no report_* block was persisted"})

        # R12 — Timestamp Priority: an evidence turn's answer/tool output cites timestamps.
        if not evidence_present:
            checks.append({"id": 12, "name": "Timestamp Priority (R12)", "status": "N-A",
                           "detail": "no evidence requiring timestamps this turn"})
        else:
            blob = ai_content + " " + " ".join(str(r.get("result", "")) for r in investigative_ok)
            has_ts = bool(self._TIMESTAMP_RE.search(blob))
            checks.append({"id": 12, "name": "Timestamp Priority (R12)",
                           "status": "PASS" if has_ts else "PARTIAL",
                           "detail": "timestamps present in answer/evidence" if has_ts
                                     else "evidence present but no explicit timestamp detected"})

        # R2 — Proactive Investigation: at least one investigative tool was run.
        if investigative:
            checks.append({"id": 2, "name": "Proactive Investigation (R2)", "status": "PASS",
                           "detail": f"{len(investigative)} investigative tool call(s): "
                                     + ", ".join(sorted({r.get('tool_name') for r in investigative}))})
        else:
            checks.append({"id": 2, "name": "Proactive Investigation (R2)", "status": "N-A",
                           "detail": "conversational/no-evidence turn; no database search required"})

        passed = sum(1 for c in checks if c["status"] == "PASS")
        gradable = sum(1 for c in checks if c["status"] in ("PASS", "FAIL", "PARTIAL"))
        return {
            "query": user_query,
            "timestamp": datetime.now().isoformat(),
            "checks": checks,
            "summary": f"{passed}/{gradable} behavioral GEP rules PASS" if gradable else "no gradable rules this turn",
        }

    def _persist_gep_turn(self, record: Dict[str, Any]) -> None:
        """Append a per-answer GEP evaluation to EYE_Logs/eye_gep_turns.jsonl so
        the Compliance panel can show, per question, whether GEP was followed."""
        case_dir = getattr(self.cm, "case_directory", None)
        if not case_dir:
            return
        logs_dir = os.path.join(str(case_dir), "EYE_Logs")
        os.makedirs(logs_dir, exist_ok=True)
        log_path = os.path.join(logs_dir, "eye_gep_turns.jsonl")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def _build_evidence_ledger(self, entries: List[Dict]) -> str:
        """Compact, one-line-per-tool-call index of what every iteration produced,
        so the model can CORRELATE across tools/databases (it survives even when a
        raw tool output was compressed/truncated). Not persisted to history.

        Each entry is {iteration, tool, params, result}."""
        if not entries:
            return ""

        def _summ(tool, params, res):
            params = params or {}
            res = res or {}
            db = res.get("database_name") or params.get("database_name") or ""
            if not res.get("success", False):
                err = str(res.get("error") or "unknown error")
                return f"{db + ' ' if db else ''}→ FAILED: {err[:120]}"
            if tool == "get_schema":
                tbls = res.get("all_tables") or list((res.get("schema") or {}).keys())
                head = ", ".join(tbls[:6]) + (" …" if len(tbls) > 6 else "")
                return f"{db} → {len(tbls)} table(s)" + (f" ({head})" if head else "")
            if tool in ("query_database", "analyze_large_dataset"):
                table = ""
                sql = res.get("sql_query") or params.get("sql_query") or ""
                m = re.search(r'(?:FROM|JOIN)\s+["\'`]?([A-Za-z_][A-Za-z0-9_]*)', sql, re.IGNORECASE)
                if m:
                    table = "/" + m.group(1)
                n = res.get("row_count")
                if n is None:
                    n = len(res.get("data") or res.get("rows") or [])
                note = " (compressed sample)" if res.get("compressed") else ""
                summ = res.get("summary")
                return f"{db}{table} → {n} row(s){note}" + (f" — {str(summ)[:80]}" if summ else "")
            if tool == "search_artifacts":
                return f"→ {res.get('total_matches', 0)} match(es)"
            if tool == "list_case_files":
                files = res.get("files") or []
                return f"→ {len(files)} item(s)"
            if tool == "query_correlation_results":
                results = res.get("results")
                cnt = len(results) if isinstance(results, list) else res.get("results_count", "?")
                return f"→ {cnt} correlation result(s)"
            if (tool or "").startswith("report_"):
                return "→ documented to report"
            return "→ ok"

        lines = ["## Evidence Gathered So Far (per step — correlate across these)"]
        for e in entries:
            tool = e.get("tool", "?")
            line = f"[{e.get('iteration', '?')}] {tool} {_summ(tool, e.get('params'), e.get('result'))}"
            lines.append(line[:300])
        return "\n".join(lines)

    def _build_synthesis_prompt(self, query: str, results: List[Dict], text_only: bool = False, ledger_text: str = None) -> str:
        """
        Enforces the 'Forensic Evidence Protocol' for forensic reporting.
        Forces the AI to be technical, chronological, and specific.

        When ``text_only`` is True the model has already documented the evidence
        to the report but returned no chat text. This pass must produce ONLY a
        conversational answer to the investigator and must NOT call any tools.
        """
        any_successful_results = any(r.get("success") for r in results)

        if text_only:
            report_mandate = (
                "The technical evidence has ALREADY been documented in the Forensic Report. "
                "Your ONLY task now is to speak directly to the investigator in chat: write a "
                "complete, natural, conversational answer to their question as a human forensic "
                "assistant would — summarise what you found, the timeline, and its significance. "
                "DO NOT call any tools. DO NOT return an empty response. Just answer."
            )
        else:
            report_mandate = (
            "CRITICAL: You MUST perform TWO actions in this turn:\n"
            "1. PRIMARY TASK: Write a detailed, conversational TEXT narrative answering the investigator's query directly in the chat bubble. Explain your findings naturally as a human forensic assistant would.\n"
            "2. SUPPORTING TASK: Call a `report_*` tool (e.g., `report_append_section`, `report_add_data_table`) to document the technical evidence for the formal record.\n"
            "DO NOT return an empty response. You MUST talk to the investigator and provide a direct answer."
        ) if any_successful_results else (
            "CRITICAL: You MUST write a detailed, conversational TEXT narrative answering the investigator's query. "
            "Explain why the evidence was missing or what was checked. NEVER return an empty response."
        )

        try:
            results_str = json.dumps(results, indent=2)
            if len(results_str) > 40000:
                results_str = results_str[:40000] + "\n... [TRUNCATED DUE TO SIZE. SYNTHESIZE AVAILABLE DATA] ..."
        except Exception:
            results_str = str(results)

        ledger_block = (ledger_text + "\n\n") if ledger_text else ""

        return (
            f"Synthesize findings for investigator query: {query}\n\n"
            f"{ledger_block}"
            f"Tool execution results:\n{results_str}\n\n"
            "FORENSIC EVIDENCE PROTOCOL:\n"
            "1. Conversational Delivery: Speak directly to the investigator as a helpful forensic peer.\n"
            "2. Extract Exact Timestamps, Usernames, and Process Details.\n"
            "3. Construct a clear, chronological TIMELINE of events.\n"
            "4. Explain the forensic significance of each event.\n"
            "5. CROSS-SOURCE CORRELATION: Do NOT report each database/tool in isolation. "
            "Cross-reference the findings above: state where multiple sources CORROBORATE the "
            "same fact (e.g. an application present in Amcache that ALSO has Prefetch execution "
            "and an MFT file record), where a source is SILENT, and where sources CONFLICT. Your "
            "conclusion MUST rest on the combined, cross-referenced evidence — not a single source.\n"
            "6. DIRECT ANSWER: You MUST explicitly answer the query right now. NEVER return an empty response.\n\n"
            f"{report_mandate}"
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
                        f"### Context Window Automatically Adapted\n"
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
            f"### Model Connection Failed\n"
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
