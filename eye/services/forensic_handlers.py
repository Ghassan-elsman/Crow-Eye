"""
Forensic Tool Handlers for EYE AI Assistant.

This module contains the implementation of core forensic tools:
- Database querying (with TOON compression)
- Schema discovery
- Artifact searching
- Correlation analysis
- Case file navigation
- Internet forensic research
- Live Forensic Intelligence (LOLBAS, LOLDrivers, etc.)
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
import urllib.request
import urllib.parse
import requests

class ForensicHandlers:
    """
    Implementation of forensic investigative tools.
    """
    
    def __init__(self, context_manager):
        self.cm = context_manager
        self.logger = logging.getLogger(__name__)
        # Session-level intelligence cache to avoid repeated downloads
        self._intel_cache: Dict[str, List[Dict]] = {}
        self._intel_cache_time: Dict[str, float] = {}
        self._intel_urls = {
            "loldrivers": "https://www.loldrivers.io/api/drivers.json",
            "bootloaders": "https://www.bootloaders.io/api/bootloaders.json",
            "lolbas": "https://lolbas-project.github.io/api/lolbas.json",
            "lofl": "https://lofl-project.github.io/api/loflcab.json"
        }
        self._fetching_thread = None

    def handle_query_database(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute SQL SELECT query against forensic database."""
        db = params.get("database_name")
        sql = params.get("sql_query")
        
        if not db or not sql:
            return {"success": False, "error": "Missing database_name or sql_query"}
            
        res = self.cm.database_service.execute_query(db, sql)
        
        # Apply TOON compression if row count > 50 to protect AI context limits
        if res.get("row_count", 0) > 50:
            return self._apply_toon_compression(res)
        return res

    def _apply_toon_compression(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Compress large results for LLM consumption while keeping full data for UI."""
        full_rows = results.get("data", []) or results.get("rows", [])
        

        # AI sees first 10 and last 10
        sample_rows = full_rows[:10] + full_rows[-10:] if len(full_rows) > 20 else full_rows
        

        # but apply a safe hard limit for the AI's "back-of-napkin" memory if needed
        return {
            "columns": results.get("columns", []),
            "rows": sample_rows,             # The AI sees this in context
            "full_rows": full_rows,          # The UI Data Viewer (bridge) sees this
            "row_count": results.get("row_count"),
            "compressed": True,
            "toon_summary": f"Data compressed for context efficiency. Total rows: {results.get('row_count')}. Showing first/last 10 for AI analysis. Full data is available in the UI Data Viewer."
        }

    def handle_get_schema(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get table schema information for database discovery."""
        db = params.get("database_name")
        table = params.get("table_name")
        return self.cm.database_service.get_schema(db, table)

    def handle_search_artifacts(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Search across all forensic databases using text or regex."""
        from eye.services.search_service import SearchConfig
        term = params.get("search_term")
        use_regex = params.get("use_regex", False)
        
        config = SearchConfig(search_term=term, use_regex=use_regex)
        results = self.cm.search_service.search(config)
        matches = results.results
        
        # Truncate search results to protect AI context limits
        if len(matches) > 50:
            matches = matches[:50]
            
        return {
            "results": matches,
            "total_matches": results.total_matches,
            "success": True,
            "note": "Results truncated to 50 matches for context efficiency." if results.total_matches > 50 else ""
        }

    def handle_query_correlation_results(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Query the Crow-eye Correlation Engine output."""
        if not self.cm.correlation_service or not self.cm.correlation_service.database_exists():
            return {
                "success": False, 
                "error": "Correlation database not found. Run the Correlation Engine in Crow-eye first."
            }
            
        qtype = params.get("query_type")
        if qtype == "statistics":
            return self.cm.correlation_service.get_correlation_statistics()
        if qtype == "time":
            return self.cm.correlation_service.query_time_correlations(
                params.get("start_time"), 
                params.get("end_time")
            )
        if qtype == "identity":
            return self.cm.correlation_service.query_identity_correlations(
                params.get("identity_type"), 
                params.get("identity_value")
            )
        return {"success": False, "error": f"Unsupported correlation query type: {qtype}"}

    def handle_list_case_files(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Navigate and list files in the case directory."""
        if not self.cm.case_directory:
            return {"success": False, "error": "No case directory configured."}
            
        sub_path = params.get("sub_path", "")

        case_root = Path(self.cm.case_directory).resolve()
        target = (case_root / sub_path).resolve()
        
        # Security: Prevent path traversal using Path.relative_to (robust on Windows)
        try:
            target.relative_to(case_root)
        except ValueError:
            return {"success": False, "error": "Access denied: Path is outside case directory."}
            
        files = []
        total_files = 0
        if target.exists() and target.is_dir():
            for item in target.iterdir():
                try:
                    total_files += 1
                    if len(files) < 50:
                        stat = item.stat()
                        files.append({
                            "name": item.name,
                            "type": "directory" if item.is_dir() else "file",
                            "size": stat.st_size if item.is_file() else 0,
                            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                        })
                except Exception:
                    continue
                    
        result = {"success": True, "files": files}
        if total_files > 50:
            result["note"] = f"List truncated. Showing 50 of {total_files} items to protect context limits."
        return result

    def handle_internet_search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Perform internet forensic research using the dedicated service."""
        query = params.get("query")
        if not query:
            return {"success": False, "error": "Missing search query."}
            
        return self.cm.internet_search_service.search(query)

    def handle_switch_model(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Switch the active LLM model."""
        model_name = params.get("model_name")
        if not model_name:
            return {"success": False, "error": "Missing model_name parameter."}
            
        self.cm.model_router.switch_model(model_name)
        return {"success": True, "message": f"Successfully switched to model: {model_name}"}

    def handle_query_threat_intel(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Query external threat intelligence (VirusTotal) for indicator reputation."""
        indicator = params.get("indicator")
        indicator_type = params.get("indicator_type", "auto")
        
        if not indicator:
            return {"success": False, "error": "Missing indicator parameter."}
            
        return self.cm.threat_intel_service.query_threat_intel(indicator, indicator_type)

    def handle_query_living_off_the_land_intel(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Query live intel for binaries, scripts, or drivers."""
        binary_name = params.get("binary_name", "").upper()
        if not binary_name:
            return {"success": False, "error": "Missing binary_name parameter."}

        self._ensure_intel_fetched()
        matches = []

        # 1. Search LOLBAS
        for item in self._intel_cache.get("lolbas", []):
            if binary_name in item.get("Name", "").upper():
                matches.append({
                    "source": "LOLBAS",
                    "name": item.get("Name"),
                    "description": item.get("Description"),
                    "commands": [c.get("Category") for c in item.get("Commands", [])]
                })

        # 2. Search LOLDrivers
        for item in self._intel_cache.get("loldrivers", []):
            if binary_name in item.get("Name", "").upper():
                matches.append({
                    "source": "LOLDrivers",
                    "name": item.get("Name"),
                    "description": item.get("Overview"),
                    "tags": item.get("Tags", [])
                })

        # 3. Search Bootloaders
        for item in self._intel_cache.get("bootloaders", []):
            if binary_name in item.get("Name", "").upper():
                matches.append({
                    "source": "Bootloaders",
                    "name": item.get("Name"),
                    "description": item.get("Description")
                })

        # 4. Search LOFL
        for item in self._intel_cache.get("lofl", []):
            if binary_name in item.get("Name", "").upper():
                matches.append({
                    "source": "LOFL",
                    "name": item.get("Name"),
                    "description": item.get("Description")
                })

        if not matches:
            return {
                "success": True, 
                "message": f"No direct matches found for '{binary_name}' in the live intelligence databases.",
                "matches": []
            }

        return {
            "success": True,
            "message": f"Found {len(matches)} intelligence matches for '{binary_name}'.",
            "matches": matches
        }

    def _ensure_intel_fetched(self):
        """
        Fetch all intelligence feeds if not already in cache or if expired.
        Uses a background thread to prevent blocking the main investigator loop.
        """
        import time
        import threading
        
        current_time = time.time()
        expiry_seconds = 24 * 3600 # 24 hours
        
        needs_fetch = False
        for key in self._intel_urls:
            last_fetch = self._intel_cache_time.get(key, 0)
            if key not in self._intel_cache or (current_time - last_fetch) > expiry_seconds:
                needs_fetch = True
                break
        
        if needs_fetch and (self._fetching_thread is None or not self._fetching_thread.is_alive()):
            self.logger.info("Starting background intelligence refresh...")
            self._fetching_thread = threading.Thread(target=self._fetch_intel_worker, daemon=True)
            self._fetching_thread.start()

    def _fetch_intel_worker(self):
        """Worker thread to fetch intel without blocking."""
        import time
        for key, url in self._intel_urls.items():
            try:
                self.logger.info(f"Fetching live intelligence: {key}")
                response = requests.get(url, timeout=15)
                if response.status_code == 200:
                    self._intel_cache[key] = response.json()
                    self._intel_cache_time[key] = time.time()
            except Exception as e:
                self.logger.error(f"Failed to fetch {key} intelligence: {e}")
                if key not in self._intel_cache:
                    self._intel_cache[key] = []
