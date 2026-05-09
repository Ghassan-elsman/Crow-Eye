import logging
import requests
from typing import Dict, Any, Optional
from eye.services.credential_manager import CredentialManager

class ThreatIntelService:
    """
    Service for querying external threat intelligence.
    Prioritizes public web lookups (no key required) but supports VirusTotal API if configured.
    """
    
    VT_API_BASE = "https://www.virustotal.com/api/v3"
    
    def __init__(self, context_manager=None):
        self.cm_service = context_manager
        self.logger = logging.getLogger(self.__class__.__name__)
        self.credential_mgr = CredentialManager()
        self._api_key = None

    def _get_api_key(self) -> Optional[str]:
        """Lazy load the API key from the credential manager."""
        if not self._api_key:
            self._api_key = self.credential_mgr.get_credential("virustotal_api_key")
        return self._api_key

    def query_threat_intel(self, indicator: str, indicator_type: str = "auto") -> Dict[str, Any]:
        """
        Main entry point for intelligence lookups.
        Tries API first (if key exists), then falls back to public web search.
        """
        if indicator_type == "auto":
            indicator_type = self._detect_type(indicator)

        # 1. Try API Path (if key exists)
        api_key = self._get_api_key()
        if api_key:
            vt_result = self._query_virustotal_api(indicator, indicator_type, api_key)
            if vt_result.get("success"):
                return vt_result

        # 2. Main/Fallback: Public Web Intelligence Path (No Key)
        return self._query_public_web_intel(indicator, indicator_type)

    def _query_virustotal_api(self, indicator: str, indicator_type: str, api_key: str) -> Dict[str, Any]:
        """Queries VirusTotal via REST API."""
        endpoint_map = {
            "ip": f"{self.VT_API_BASE}/ip_addresses/{indicator}",
            "file": f"{self.VT_API_BASE}/files/{indicator}",
            "url": f"{self.VT_API_BASE}/urls/{self._encode_url(indicator)}"
        }
        
        url = endpoint_map.get(indicator_type)
        if not url:
            return {"success": False, "error": f"Unsupported indicator type: {indicator_type}"}

        headers = {"x-apikey": api_key, "accept": "application/json"}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "source": "VirusTotal API",
                    "indicator": indicator,
                    "type": indicator_type,
                    "data": self._sanitize_vt_results(data, indicator_type)
                }
        except:
            pass
        return {"success": False}

    def _query_public_web_intel(self, indicator: str, indicator_type: str) -> Dict[str, Any]:
        """
        Performs targeted web searches to gather reputation data from multiple sources.
        """
        if not self.cm_service or not self.cm_service.internet_search_service:
            return {"success": False, "error": "Internet Search Service unavailable."}

        # Construct a high-signal search query
        query = f'"{indicator}" reputation threat malware virustotal alienvault'
        
        self.logger.info(f"Performing Public Web Intel Lookup: {query}")
        search_res = self.cm_service.internet_search_service.search(query, max_results=5)
        
        if search_res.get("success") and search_res.get("results"):
            return {
                "success": True,
                "source": "Public Intelligence (Web)",
                "indicator": indicator,
                "type": indicator_type,
                "message": "Gathered reputation data from public intelligence sources.",
                "results": search_res["results"]
            }
        
        return {
            "success": False, 
            "error": "No public intelligence data found for this indicator.",
            "indicator": indicator
        }

    def _detect_type(self, indicator: str) -> str:
        """Simple heuristic to detect indicator type."""
        indicator = indicator.strip()
        if indicator.count('.') == 3 and all(p.isdigit() for p in indicator.split('.')):
            return "ip"
        if len(indicator) in [32, 40, 64] and all(c in "0123456789abcdefABCDEF" for c in indicator):
            return "file"
        if "://" in indicator or indicator.startswith("www."):
            return "url"
        return "file"

    def _encode_url(self, url: str) -> str:
        import base64
        return base64.urlsafe_b64encode(url.encode()).decode().strip("=")

    def _sanitize_vt_results(self, data: Dict, indicator_type: str) -> Dict:
        """Extracts high-level forensic metrics from raw VT response."""
        try:
            attr = data.get("data", {}).get("attributes", {})
            stats = attr.get("last_analysis_stats", {})
            malicious = stats.get("malicious", 0)
            total = sum(stats.values())
            
            results = {
                "reputation_score": f"{malicious}/{total} engines flagged as malicious",
                "last_analysis_date": attr.get("last_analysis_date"),
                "tags": attr.get("tags", []),
                "as_owner": attr.get("as_owner"),
                "country": attr.get("country")
            }
            if indicator_type == "file":
                results["names"] = attr.get("names", [])[:3]
            return {k: v for k, v in results.items() if v is not None}
        except:
            return {"summary": "Raw API data received"}
