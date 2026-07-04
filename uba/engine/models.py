"""Core data model of the UBA engine."""

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional

# Behavior classes (who/what layer of the master matrix)
CLASS_USER = "user"
CLASS_APPLICATION = "application"
CLASS_SYSTEM_APP = "system_app"
CLASS_SYSTEM = "system"

# Severity ladder (manager-readable)
SEV_ROUTINE = "routine"
SEV_NOTABLE = "notable"
SEV_SUSPICIOUS = "suspicious"
SEV_CRITICAL = "critical"

# Confidence tiers (forensic honesty)
CONF_CORROBORATED = "corroborated"   # artifact + event log within delta
CONF_ARTIFACT_ONLY = "artifact-only"
CONF_LOG_ONLY = "log-only"
CONF_PRESENCE = "presence"           # shimcache-style existence evidence
CONF_INFERENCE = "inference"         # heuristic (e.g. copy detection)

# Actor types. EMPTY string = uncertain — shown as "Unattributed" in the UI.
ACTOR_USER = "User"
ACTOR_APPLICATION = "Application"
ACTOR_SYSTEM = "System"
ACTOR_EMPTY = ""


@dataclass
class EvidenceRef:
    """Pointer to source rows backing a BehaviorEvent.

    Either a concrete rowid list (small evidence) or a rowid range plus
    count (bursts). ``role`` is 'primary' (the artifact that generated the
    event) or 'corroborating' (the matched event-log rows).
    """
    db: str                       # logical db name (see db_access.DB_CANDIDATES)
    table: str
    role: str = "primary"
    rowids: List[int] = field(default_factory=list)
    rowid_range: Optional[List[int]] = None   # [min, max] for bursts
    count: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        if not d.get("rowid_range"):
            d.pop("rowid_range", None)
        return d


@dataclass
class BehaviorEvent:
    """One manager-readable activity, fully sourced."""
    rule_id: str
    behavior_class: str
    activity: str
    ts_start: Optional[str]       # UTC 'YYYY-MM-DD HH:MM:SS'; None = timeless
    ts_end: Optional[str]
    actor_type: str               # 'User' | 'Application' | 'System' | ''
    actor_name: str
    actor_basis: str              # why the attribution holds ('' when actor empty)
    description: str              # plain English for HR/managers
    severity: str
    confidence: str
    session_context: str = ""     # annotation only, never attribution
    caveat: str = ""              # evidentiary limit of the artifact (e.g. can be app-generated)
    session_user: str = ""        # interactive user logged on at ts_start — labelled, NOT proof
    app_name: str = ""            # the specific program this activity concerns (for the app filter)
    aggregate_count: int = 1
    details: dict = field(default_factory=dict)   # small extras for the card
    evidence: List[EvidenceRef] = field(default_factory=list)
    event_id: str = ""            # stable hash, filled in __post_init__

    def __post_init__(self):
        if not self.event_id:
            basis = json.dumps([
                self.rule_id, self.ts_start, self.ts_end, self.activity,
                self.actor_name, self.description,
                [(e.db, e.table, e.rowids[:5], e.rowid_range) for e in self.evidence],
            ], default=str, sort_keys=True)
            self.event_id = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]

    def to_row(self) -> dict:
        """Flatten for the derived SQLite event store."""
        return {
            "event_id": self.event_id,
            "rule_id": self.rule_id,
            "behavior_class": self.behavior_class,
            "activity": self.activity,
            "ts_start": self.ts_start,
            "ts_end": self.ts_end or self.ts_start,
            "actor_type": self.actor_type,
            "actor_name": self.actor_name,
            "actor_basis": self.actor_basis,
            "description": self.description,
            "severity": self.severity,
            "confidence": self.confidence,
            "session_context": self.session_context,
            "caveat": self.caveat,
            "session_user": self.session_user,
            "app_name": self.app_name,
            "aggregate_count": self.aggregate_count,
            "details_json": json.dumps(self.details, default=str),
            "evidence_json": json.dumps([e.to_dict() for e in self.evidence]),
        }
