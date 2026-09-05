"""
Offline MITRE ATT&CK catalogue and coverage rollup.

Crow-Eye maps semantic rules to ATT&CK technique IDs so wings roll up to the
tactics/techniques they cover, and so Eye AI and reports can reason at the
technique level. This module is deliberately self-contained and offline — no
network calls, honouring the "0 ms data sent off-device" stance. It ships a
compact subset of techniques relevant to the default wings; unknown technique
IDs still work (they are surfaced with an "Unknown technique" label) so custom
wings are never blocked by a missing catalogue entry.
"""

from typing import Dict, List, Any, Iterable, Optional

# technique_id -> (name, tactic). Tactic uses ATT&CK tactic slugs.
TECHNIQUES: Dict[str, tuple] = {
    # Execution
    "T1059": ("Command and Scripting Interpreter", "execution"),
    "T1204": ("User Execution", "execution"),
    "T1569": ("System Services", "execution"),
    # Persistence
    "T1547": ("Boot or Logon Autostart Execution", "persistence"),
    "T1543": ("Create or Modify System Process", "persistence"),
    "T1053": ("Scheduled Task/Job", "persistence"),
    "T1546": ("Event Triggered Execution", "persistence"),
    # Privilege Escalation / Defense Evasion
    "T1055": ("Process Injection", "privilege-escalation"),
    "T1070": ("Indicator Removal", "defense-evasion"),
    "T1070.001": ("Indicator Removal: Clear Windows Event Logs", "defense-evasion"),
    "T1070.004": ("Indicator Removal: File Deletion", "defense-evasion"),
    "T1070.006": ("Indicator Removal: Timestomp", "defense-evasion"),
    "T1562": ("Impair Defenses", "defense-evasion"),
    "T1562.001": ("Impair Defenses: Disable or Modify Tools", "defense-evasion"),
    "T1036": ("Masquerading", "defense-evasion"),
    "T1036.005": ("Masquerading: Match Legitimate Name or Location", "defense-evasion"),
    # Credential Access
    "T1110": ("Brute Force", "credential-access"),
    "T1110.003": ("Brute Force: Password Spraying", "credential-access"),
    "T1003": ("OS Credential Dumping", "credential-access"),
    "T1078": ("Valid Accounts", "privilege-escalation"),
    # Discovery / Lateral Movement
    "T1021": ("Remote Services", "lateral-movement"),
    "T1021.001": ("Remote Services: Remote Desktop Protocol", "lateral-movement"),
    "T1021.002": ("Remote Services: SMB/Windows Admin Shares", "lateral-movement"),
    "T1570": ("Lateral Tool Transfer", "lateral-movement"),
    # Collection / Exfiltration
    "T1074": ("Data Staged", "collection"),
    "T1048": ("Exfiltration Over Alternative Protocol", "exfiltration"),
    "T1052": ("Exfiltration Over Physical Medium", "exfiltration"),
    "T1052.001": ("Exfiltration over USB", "exfiltration"),
    # Impact
    "T1485": ("Data Destruction", "impact"),
    "T1486": ("Data Encrypted for Impact", "impact"),
    "T1490": ("Inhibit System Recovery", "impact"),

    # ---- techniques the registry-key wings cite -------------------------
    # An unknown ID still works - it is labelled "Unknown technique" and the
    # rollup carries on - so nothing here was blocking a wing. But a coverage
    # rollup that cannot name half of what it covers is not much of a rollup,
    # and several of these were already cited by the shipped wings.
    "T1547.001": ("Boot or Logon Autostart Execution: Registry Run Keys / Startup Folder",
                  "persistence"),
    "T1547.014": ("Boot or Logon Autostart Execution: Active Setup", "persistence"),
    "T1053.005": ("Scheduled Task/Job: Scheduled Task", "persistence"),
    "T1546.012": ("Event Triggered Execution: Image File Execution Options Injection",
                  "persistence"),
    "T1562.002": ("Impair Defenses: Disable Windows Event Logging", "defense-evasion"),
    "T1562.009": ("Impair Defenses: Safe Mode Boot", "defense-evasion"),
    "T1553": ("Subvert Trust Controls", "defense-evasion"),
    "T1553.005": ("Subvert Trust Controls: Mark-of-the-Web Bypass", "defense-evasion"),
    "T1112": ("Modify Registry", "defense-evasion"),
    "T1557": ("Adversary-in-the-Middle", "credential-access"),
    "T1200": ("Hardware Additions", "initial-access"),
    "T1016": ("System Network Configuration Discovery", "discovery"),
    "T1123": ("Audio Capture", "collection"),
    "T1125": ("Video Capture", "collection"),

    # ---- techniques the behaviour and evasion semantic rules cite ---------
    # Those 22 rules shipped with no ATT&CK tags at all, so the coverage
    # rollup and the GUI's coverage bar were computed over an empty set and
    # read as "no techniques covered" on every case.
    "T1218": ("System Binary Proxy Execution", "defense-evasion"),
    "T1218.011": ("System Binary Proxy Execution: Rundll32", "defense-evasion"),
    "T1105": ("Ingress Tool Transfer", "command-and-control"),
    "T1071": ("Application Layer Protocol", "command-and-control"),
    "T1572": ("Protocol Tunneling", "command-and-control"),
    "T1046": ("Network Service Discovery", "discovery"),
    "T1087": ("Account Discovery", "discovery"),
    "T1548.002": ("Abuse Elevation Control Mechanism: Bypass User Account Control",
                  "privilege-escalation"),
    "T1110.002": ("Brute Force: Password Cracking", "credential-access"),
    "T1222": ("File and Directory Permissions Modification", "defense-evasion"),
    "T1036.007": ("Masquerading: Double File Extension", "defense-evasion"),
}

# Ordered tactics for stable, kill-chain-ordered rollup display.
TACTIC_ORDER: List[str] = [
    "reconnaissance", "resource-development", "initial-access", "execution",
    "persistence", "privilege-escalation", "defense-evasion", "credential-access",
    "discovery", "lateral-movement", "collection", "command-and-control",
    "exfiltration", "impact",
]

_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def technique_name(technique_id: str) -> str:
    """Human-readable technique name, or a safe label for unknown IDs."""
    entry = TECHNIQUES.get(technique_id)
    if entry:
        return entry[0]
    # Fall back to the parent technique for sub-techniques (T1070.001 -> T1070)
    parent = technique_id.split(".")[0]
    if parent in TECHNIQUES:
        return TECHNIQUES[parent][0]
    return f"Unknown technique ({technique_id})"


def technique_tactic(technique_id: str) -> Optional[str]:
    """ATT&CK tactic slug for a technique, resolving sub-techniques to parents."""
    entry = TECHNIQUES.get(technique_id)
    if entry:
        return entry[1]
    parent = technique_id.split(".")[0]
    if parent in TECHNIQUES:
        return TECHNIQUES[parent][1]
    return None


def _result_fields(result: Any) -> tuple:
    """Extract (technique_ids, severity) from a SemanticMatchResult or dict."""
    if isinstance(result, dict):
        return (result.get("technique_id", []) or [], result.get("severity", "info"))
    return (list(getattr(result, "technique_id", []) or []),
            getattr(result, "severity", "info"))


def compute_attack_coverage(results: Iterable[Any]) -> Dict[str, Any]:
    """
    Roll up matched semantic results into an ATT&CK coverage summary.

    Accepts SemanticMatchResult objects or their dicts. Returns:
        {
          "techniques": [{"technique_id", "name", "tactic", "count", "max_severity"}],
          "tactics": [{"tactic", "technique_ids": [...], "count", "max_severity"}],
          "technique_count": int,
          "tactic_count": int,
        }
    Techniques are sorted by tactic kill-chain order then id; unknown-tactic
    techniques sort last.
    """
    tech_agg: Dict[str, Dict[str, Any]] = {}

    for result in results:
        technique_ids, severity = _result_fields(result)
        sev_rank = _SEVERITY_RANK.get(str(severity).lower(), 0)
        for tid in technique_ids:
            if not tid:
                continue
            agg = tech_agg.setdefault(tid, {
                "technique_id": tid,
                "name": technique_name(tid),
                "tactic": technique_tactic(tid) or "unknown",
                "count": 0,
                "_sev_rank": 0,
            })
            agg["count"] += 1
            agg["_sev_rank"] = max(agg["_sev_rank"], sev_rank)

    def _tactic_sort_key(tactic: str) -> int:
        return TACTIC_ORDER.index(tactic) if tactic in TACTIC_ORDER else len(TACTIC_ORDER)

    rank_to_sev = {v: k for k, v in _SEVERITY_RANK.items()}
    techniques = []
    for agg in tech_agg.values():
        agg["max_severity"] = rank_to_sev.get(agg.pop("_sev_rank"), "info")
        techniques.append(agg)
    techniques.sort(key=lambda t: (_tactic_sort_key(t["tactic"]), t["technique_id"]))

    # Tactic rollup
    tactics: Dict[str, Dict[str, Any]] = {}
    for t in techniques:
        tac = tactics.setdefault(t["tactic"], {
            "tactic": t["tactic"], "technique_ids": [], "count": 0, "_sev_rank": 0,
        })
        tac["technique_ids"].append(t["technique_id"])
        tac["count"] += t["count"]
        tac["_sev_rank"] = max(tac["_sev_rank"], _SEVERITY_RANK.get(t["max_severity"], 0))
    tactic_list = []
    for tac in tactics.values():
        tac["max_severity"] = rank_to_sev.get(tac.pop("_sev_rank"), "info")
        tactic_list.append(tac)
    tactic_list.sort(key=lambda t: _tactic_sort_key(t["tactic"]))

    return {
        "techniques": techniques,
        "tactics": tactic_list,
        "technique_count": len(techniques),
        "tactic_count": len(tactic_list),
    }
