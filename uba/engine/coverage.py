"""
Coverage analysis — honest reporting of what the engine could and could not
detect for this case.

Statuses:
- active:               all required tables + log EIDs available
- degraded:             artifact tables available but the corroborating /
                        primary log EIDs are absent (auditing not enabled) —
                        detections run at reduced confidence
- unavailable:          required artifact tables missing from the case
- requires_collection:  master-matrix behaviors that need parsers/collections
                        Crow-Eye does not have yet (static list)
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

# Map rule 'requires' log tables to the logical logs DB
_LOG_TABLES = ("SecurityLogs", "SystemLogs", "ApplicationLogs")

# Friendly artifact-source names for the "what artifacts are used" list.
_SOURCE_LABEL = {
    "SecurityLogs": "Event Log — Security", "SystemLogs": "Event Log — System",
    "ApplicationLogs": "Event Log — Application", "journal_events": "USN Journal",
    "mft_usn_correlated": "MFT + USN (correlated)", "UserAssist": "UserAssist",
    "BAM": "Background Activity (BAM)", "prefetch_data": "Prefetch",
    "shimcache_entries": "ShimCache", "Shellbags": "ShellBags",
    "LNK_Files": "LNK Files", "Automatic_JumpLists": "Jump Lists",
    "Custom_JumpLists": "Jump Lists (custom)", "recycle_bin_entries": "Recycle Bin",
    "srum_application_usage": "SRUM — app usage",
    "srum_network_data_usage": "SRUM — network", "srum_network_connectivity": "SRUM — connectivity",
    "InventoryApplication": "AmCache — applications", "InventoryApplicationFile": "AmCache — files",
    "InventoryApplicationShortcut": "AmCache — shortcuts", "InventoryDriverBinary": "AmCache — drivers",
    "InventoryDevicePnp": "AmCache — devices", "MUICache": "MUICache",
    "USBDevices": "Registry — USB", "USBStorageDevices": "Registry — USB storage",
    "InstalledSoftware": "Registry — installed software", "SystemServices": "Registry — services",
    "AutoStartPrograms": "Registry — autostart", "Network_list": "Registry — networks",
    "BrowserHistory": "Registry — browser history", "RecentDocs": "Registry — recent docs",
    "OpenSaveMRU": "Registry — open/save history", "LastSaveMRU": "Registry — save history",
    "TypedPaths": "Registry — typed paths", "WordWheelQuery": "Registry — search terms",
    "RunMRU": "Registry — Run history", "TimeZoneInfo": "Registry — time zone",
}


def _rule_how(rule: dict, artifacts: List[str]) -> str:
    """The rule's explicit `how`, or a sensible sentence generated from its
    sources so every rule explains its detection method."""
    if rule.get("how"):
        return rule["how"]
    joins = rule.get("log_join") or rule.get("requires", {}).get("optional_log_eids")
    if not artifacts:
        return "Derived from parsed forensic artifacts."
    if joins and len(artifacts) > 1:
        return "Correlates {} within a short time window.".format(
            " with ".join(artifacts[:3]))
    if len(artifacts) > 1:
        return "Combines {}.".format(", ".join(artifacts[:4]))
    return "Read directly from {}.".format(artifacts[0])


def _rule_artifacts(rule: dict) -> List[str]:
    """Derive the friendly artifact-source list a rule reads from, from its
    `requires` (tables / any_tables) plus any log EIDs it joins on. When a log
    source also has specific Event IDs, the EID-annotated form replaces the
    bare one (e.g. 'Event Log — Security (4688)' not both)."""
    requires = rule.get("requires", {})
    base = []                            # ordered friendly base labels
    for grp in (requires.get("tables"), requires.get("any_tables")):
        for tbls in (grp or {}).values():
            for t in tbls:
                base.append(_SOURCE_LABEL.get(t, t))
    eid_of = {}                          # base label -> "(4688)" annotation
    for log_map in (requires.get("log_eids"), requires.get("optional_log_eids"),
                    {rule.get("log_join", {}).get("table"): rule.get("log_join", {}).get("event_ids")}
                    if rule.get("log_join") else {}):
        for log_tbl, eids in (log_map or {}).items():
            if not log_tbl:
                continue
            label = _SOURCE_LABEL.get(log_tbl, log_tbl)
            if eids:
                eid_of.setdefault(label, []).extend(str(e) for e in eids)
            elif label not in base:
                base.append(label)
    out, seen = [], set()
    for label in base:
        full = label
        if label in eid_of:
            full = "{} ({})".format(label, ", ".join(dict.fromkeys(eid_of[label])))
        if full not in seen and label not in seen:
            seen.add(full); seen.add(label)
            out.append(full)
    # log sources that only appeared via EIDs (no table requirement)
    for label, eids in eid_of.items():
        if label not in seen and not any(o.startswith(label) for o in out):
            out.append("{} ({})".format(label, ", ".join(dict.fromkeys(eids))))
    return out


class CoverageAnalyzer:
    def __init__(self, db_pool, rules_config: dict):
        self.db_pool = db_pool
        self.rules = rules_config["rules"]
        self.requires_collection = rules_config["requires_collection"]
        self._eid_presence_cache: Dict[str, bool] = {}

    # ------------------------------------------------------------------ #
    def _has_tables(self, table_map: Dict[str, List[str]], mode_all=True) -> bool:
        checks = []
        for db_name, tables in (table_map or {}).items():
            for table in tables:
                conn_ok = self.db_pool.has_table(db_name, table)
                checks.append(conn_ok)
        if not checks:
            return True
        return all(checks) if mode_all else any(checks)

    def _has_eid(self, log_table: str, eid: int) -> bool:
        key = "{}:{}".format(log_table, eid)
        if key in self._eid_presence_cache:
            return self._eid_presence_cache[key]
        present = False
        conn = self.db_pool.get("logs")
        if conn is not None and self.db_pool.has_table("logs", log_table):
            try:
                row = conn.execute(
                    'SELECT 1 FROM "{}" WHERE EventID = ? LIMIT 1'.format(log_table),
                    (eid,)).fetchone()
                present = row is not None
            except Exception as e:
                logger.debug("UBA coverage: EID probe failed %s/%s: %s",
                             log_table, eid, e)
        self._eid_presence_cache[key] = present
        return present

    def _eids_available(self, eid_map: Dict[str, List[int]], mode: str) -> bool:
        found = []
        for log_table, eids in (eid_map or {}).items():
            for eid in eids:
                found.append(self._has_eid(log_table, eid))
        if not found:
            return True
        return any(found) if mode == "any" else all(found)

    # ------------------------------------------------------------------ #
    def rule_status(self, rule: dict) -> dict:
        requires = rule.get("requires", {})
        entry = {
            "rule_id": rule["id"],
            "activity": rule["activity"],
            "title": rule["title"],
            "behavior_class": rule["behavior_class"],
            "status": "active",
            "note": rule.get("degrade_note", ""),
            "artifacts": _rule_artifacts(rule),
        }
        entry["how"] = _rule_how(rule, entry["artifacts"])

        tables_ok = self._has_tables(requires.get("tables"))
        any_tables = requires.get("any_tables")
        any_ok = self._has_tables(any_tables, mode_all=False) if any_tables else True
        if not (tables_ok and any_ok):
            entry["status"] = "unavailable"
            entry["note"] = entry["note"] or "Required artifact data was not parsed for this case."
            return entry

        mode = requires.get("log_eids_mode", "all")
        required_eids = requires.get("log_eids")
        if required_eids and not self._eids_available(required_eids, mode):
            entry["status"] = "degraded"
            entry["note"] = entry["note"] or (
                "The Windows log entries this detection relies on are not present "
                "(auditing may be disabled); nothing can be shown for it.")
            return entry

        optional_eids = requires.get("optional_log_eids")
        if optional_eids and not self._eids_available(optional_eids, "any"):
            entry["status"] = "degraded"
            entry["note"] = entry["note"] or (
                "Shown from disk artifacts only — the corroborating Windows log "
                "entries are not present (auditing is typically disabled by default).")
        return entry

    def report(self) -> dict:
        statuses = [self.rule_status(rule) for rule in self.rules]
        return {
            "rules": statuses,
            "requires_collection": self.requires_collection,
            "counts": {
                "active": sum(1 for s in statuses if s["status"] == "active"),
                "degraded": sum(1 for s in statuses if s["status"] == "degraded"),
                "unavailable": sum(1 for s in statuses if s["status"] == "unavailable"),
                "requires_collection": len(self.requires_collection),
            },
        }
