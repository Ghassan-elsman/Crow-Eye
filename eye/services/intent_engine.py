"""
Intent Detection Engine for EYE AI Assistant.

This module maps natural language investigator queries to forensic artifact keywords,
triggering the retrieval of appropriate knowledge base context.
"""

from typing import List
import logging

class IntentEngine:
    """
    Analyzes investigator queries to determine forensic intent and artifacts.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Mapping of natural language intents to artifact keywords
        self.intent_mapping = {
            "login": ["eventlog", "registry"],
            "logon": ["eventlog", "registry"],
            "authentication": ["eventlog", "registry"],
            "run": ["prefetch", "amcache", "shimcache", "srum"],
            "execute": ["prefetch", "amcache", "shimcache", "srum"],
            "execution": ["prefetch", "amcache", "shimcache", "srum"],
            "open": ["jumplist", "registry"],
            "opened": ["jumplist", "registry"],
            "access": ["jumplist", "registry"],
            "accessed": ["jumplist", "registry"],
            "delete": ["recyclebin", "usn"],
            "deleted": ["recyclebin", "usn"],
            "create": ["mft", "usn"],
            "created": ["mft", "usn"],
            "modify": ["mft", "usn"],
            "modified": ["mft", "usn"],
            "network": ["srum", "eventlog"],
            "connection": ["srum", "eventlog"],
            "ip": ["srum", "eventlog"],
            "port": ["srum", "eventlog"],
            "persistence": ["registry", "eventlog"],
            "startup": ["registry", "eventlog"],
            "autorun": ["registry", "eventlog"],
            "activity": ["eventlog", "prefetch", "jumplist", "registry", "usn"],
            "recent": ["eventlog", "prefetch", "jumplist", "registry", "usn"],
            "last": ["eventlog", "prefetch", "jumplist", "registry", "usn"],
            "happened": ["eventlog", "prefetch", "jumplist", "registry", "usn"],
            "schema": ["Global_schema_databse_Refrence"],
            "structure": ["Global_schema_databse_Refrence"],
            "layout": ["Global_schema_databse_Refrence"],
            "database": ["Global_schema_databse_Refrence"],
            "table": ["Global_schema_databse_Refrence"],
            "column": ["Global_schema_databse_Refrence"],
            # Technical Reasoning & Intelligence
            "why": ["forensic_methodology", "evidence_intelligence"],
            "how": ["forensic_methodology", "evidence_intelligence"],
            "clarify": ["forensic_methodology", "evidence_intelligence"],
            "explain": ["forensic_methodology", "evidence_intelligence"],
            "meaning": ["forensic_methodology", "evidence_intelligence"],
            "guidance": ["forensic_methodology"],
            "protocol": ["forensic_methodology"],
            "artifact": ["evidence_intelligence"],
            "evidence": ["evidence_intelligence"],
            "proof": ["evidence_intelligence"],
            "significance": ["evidence_intelligence", "forensic_methodology"],
            "purpose": ["evidence_intelligence", "forensic_methodology"],
            "interpretation": ["forensic_methodology"]
        }

    def detect_keywords(self, query: str) -> List[str]:
        """
        Scans a query for forensic artifact keywords and intents.
        """
        # Hardcoded artifact keywords
        artifact_keywords = [
            "prefetch", "mft", "amcache", "shimcache", "registry",
            "usn", "jumplist", "recyclebin", "srum", "eventlog",
            "lnk", "shortcut"
        ]
        
        detected = []
        q_lower = query.lower()
        
        # 1. Direct artifact matching (using word boundaries)
        import re
        for kw in artifact_keywords:
            pattern = r'\b' + re.escape(kw) + r'\b'
            if re.search(pattern, q_lower):
                # Normalize aliases
                norm = "jumplist" if kw in ["lnk", "shortcut"] else kw
                if norm not in detected:
                    detected.append(norm)
                    
        # 2. Intent-based matching (using word boundaries)
        import re
        for intent, artifacts in self.intent_mapping.items():
            # Use regex for word boundaries to handle punctuation (e.g. "logon?")
            pattern = r'\b' + re.escape(intent) + r'\b'
            if re.search(pattern, q_lower):
                for art in artifacts:
                    if art not in detected:
                        detected.append(art)
                        
        if detected:
            self.logger.info(f"Forensic intent detected: {detected}")
            
        return detected
