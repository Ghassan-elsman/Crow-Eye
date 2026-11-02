"""
Wing Configuration
Stores wing definitions with references to feather configs.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Optional

# Import centralized score configuration manager
from .score_configuration_manager import ScoreConfigurationManager
from .eye_authorship import EyeAuthorship

import logging
logger = logging.getLogger(__name__)


_SHIPPED_WINGS = None


def shipped_wings() -> Dict[str, dict]:
    """{wing_id: the shipped Wing's JSON}, parsed once per process. Loading a
    Wing used to open and parse all 24 shipped files to find its own."""
    global _SHIPPED_WINGS
    if _SHIPPED_WINGS is None:
        index = {}
        try:
            from ..integration.default_wings_loader import DefaultWingsLoader
            folder = DefaultWingsLoader.get_default_wings_directory()
            for name in DefaultWingsLoader.get_default_wing_files():
                try:
                    with open(folder / name, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    continue
                if data.get('wing_id'):
                    index[data['wing_id']] = data
        except Exception as e:
            logger.warning(f"[WingConfig] Shipped Wings not read: {e}")
        _SHIPPED_WINGS = index
    return _SHIPPED_WINGS


def rules_differ_from_shipped(wing_id: str, rules) -> bool:
    """True when `rules` are not the shipped Wing's own: an analyst's edit to a
    shipped Wing, which a reload must keep (see WingConfig.from_dict)."""
    shipped = shipped_wings().get(wing_id or '')
    if shipped is None:
        return False
    norm = lambda rs: json.dumps(rs or [], sort_keys=True, default=str)
    return norm(rules) != norm(shipped.get('semantic_rules'))


@dataclass
class WingFeatherReference:
    """Reference to a feather used in a wing"""
    feather_config_name: str # Name of the feather config
    feather_database_path: str # Path to the feather database
    artifact_type: str
    feather_id: str # ID used in the wing
    table_name: Optional[str] = None # Optional: Override table name
    artifact_type_override: Optional[str] = None # Optional: Override artifact type
    
    # Weighted scoring fields
    weight: float = 0.0 # Weight for weighted scoring (0.0 - 1.0)
    tier: int = 0 # Tier number for grouping (1-4)
    tier_name: str = "" # Human-readable tier name


WING_CATEGORY_TIME = "time"
WING_CATEGORY_IDENTITY = "identity"
WING_CATEGORY_BEHAVIOUR = "behaviour"
WING_CATEGORIES = (WING_CATEGORY_TIME, WING_CATEGORY_IDENTITY, WING_CATEGORY_BEHAVIOUR)

WING_CATEGORY_LABELS = {
    WING_CATEGORY_TIME: "Time Wing",
    WING_CATEGORY_IDENTITY: "Identity Wing",
    WING_CATEGORY_BEHAVIOUR: "Behaviour Wing",
}

_CATEGORY_ALIASES = {
    "time": WING_CATEGORY_TIME, "time_window": WING_CATEGORY_TIME,
    "timewindow": WING_CATEGORY_TIME, "time-window": WING_CATEGORY_TIME,
    "identity": WING_CATEGORY_IDENTITY, "identity_based": WING_CATEGORY_IDENTITY,
    "behaviour": WING_CATEGORY_BEHAVIOUR, "behavioural": WING_CATEGORY_BEHAVIOUR,
    "behavior": WING_CATEGORY_BEHAVIOUR, "behavioral": WING_CATEGORY_BEHAVIOUR,
}


def normalize_wing_category(value) -> Optional[str]:
    """The canonical category for ``value``, or None when it names none.

    None means "uncategorised": such a Wing cannot run until the analyst
    chooses Time, Identity or Behaviour in the Wing Creator.
    """
    if value is None:
        return None
    key = str(value).strip().lower()
    if not key:
        return None
    return _CATEGORY_ALIASES.get(key)


def wing_category_label(value) -> str:
    """'Time Wing' / 'Identity Wing' / 'Behaviour Wing', or 'Uncategorised Wing'."""
    return WING_CATEGORY_LABELS.get(normalize_wing_category(value), "Uncategorised Wing")


def category_problems(wing_category, semantic_rules, feathers,
                      behaviour: Optional[Dict] = None) -> List[str]:
    """Why a Wing with this category and content cannot be saved or run.

    One list for every place that creates or edits a Wing (Wing Creator,
    Eye's tools, the executor), so they refuse for the same reasons in the
    same words.

    ``behaviour`` is a Behaviour Wing's own fields (``behaviour_fields_of``:
    steps, ordered, within_minutes, max_gap_minutes, subject, alert). A caller
    that does not hold them passes None and those checks are skipped; a
    caller that does (WingConfig, Wing) always passes them.
    """
    from .semantic_mapping import rules_are_advanced
    category = normalize_wing_category(wing_category)
    problems: List[str] = []
    if category is None:
        problems.append(
            "This Wing has no category. Choose Time, Identity or Behaviour.")
        return problems
    if category == WING_CATEGORY_TIME and rules_are_advanced(semantic_rules):
        problems.append(
            "A Time Wing cannot carry advanced rules (absence, sequence, "
            "threshold, nested condition groups, negated or cross-feather "
            "conditions): the Time-Window engine sees one row per feather and "
            "cannot evaluate them. Make it an Identity Wing, or remove those rules.")
    if category == WING_CATEGORY_BEHAVIOUR and feathers:
        problems.append(
            "A Behaviour Wing names no Feathers: it reads the behaviour events "
            "UBA produces. Remove its Feathers, or make it a Time or Identity Wing.")
    if category == WING_CATEGORY_BEHAVIOUR and behaviour is not None:
        problems.extend(behaviour_problems(behaviour, semantic_rules))
    elif category != WING_CATEGORY_BEHAVIOUR and behaviour and behaviour.get('steps'):
        problems.append(
            "Only a Behaviour Wing has behaviour steps. Make it a Behaviour Wing, "
            "or remove its steps.")
    return problems


# ----------------------------------------------------------------------------
# Behaviour Wings
#
# A Behaviour Wing names no Feathers. It is a set of behaviour steps - each a
# UBA rule (built-in or analyst-created) or an activity, with optional extra
# conditions and a minimum count - that must all happen for ONE person, in
# order or in any order, inside ``within_minutes``. The Behavioural engine
# (engine/behavioural_engine.py) compiles the steps into the evaluator's
# ``sequence`` rule and runs it over UBA's behaviour events, keyed by SID.
#
#   "steps": [
#     {"rule_id": "privileged_logon"},                  # or "activity": "..."
#     {"rule_id": "log_cleared", "min_count": 1,
#      "conditions": [{"field_name": "severity", "operator": "equals",
#                      "value": "critical"}],
#      "actor": "person"}                               # person | machine | any
#   ],
#   "ordered": true,                 # false = any order
#   "within_minutes": 60,            # the whole set fits in this span
#   "max_gap_minutes": 30,           # ordered only, between consecutive steps
#   "subject": {"scope": "everyone", # everyone | accounts | sids | groups
#               "accounts": [], "sids": [], "groups": [],
#               "include_service_accounts": false},
#   "alert": {"severity": "high", "technique_id": ["T1070.001"],
#             "tactic": ["defense-evasion"]}
#
# A step's ``actor``: "person" (the default) takes only events attributed to
# the person being evaluated. "machine" takes events no person is recorded
# for (a service installed by the Service Control Manager, a program run
# known from Prefetch, a USB device plugged in): they are matched on the case
# as a whole, and a hit says so. "any" takes both. A hit always binds at least
# one of the person's own events unless every step is a machine step.
# ----------------------------------------------------------------------------

BEHAVIOUR_FIELDS = ("steps", "ordered", "within_minutes", "max_gap_minutes",
                    "subject", "alert")

STEP_ACTORS = ("person", "machine", "any")
SUBJECT_SCOPES = ("everyone", "accounts", "sids", "groups")
ALERT_SEVERITIES = ("info", "low", "medium", "high", "critical")
UBA_SEVERITIES = ("routine", "notable", "suspicious", "critical")
STEP_OPERATORS = ("equals", "not_equals", "contains", "regex", "wildcard",
                  "greater_than", "less_than", "greater_equal", "less_equal")

# The fields of a behaviour event a step condition may name; ``details.<key>``
# names one of the event's details. The engine gives every row each of these.
BEHAVIOUR_EVENT_FIELDS = (
    "rule_id", "activity", "behavior_class", "severity", "confidence",
    "actor_type", "actor_sid", "actor_name", "app_name", "host", "description",
    "ts_start", "ts_end", "session_context", "session_user", "hour_utc",
    "hour_local", "aggregate_count", "event_id",
)
# Feather ids a Behaviour Wing's own semantic_rules may name (the rows the
# engine hands the evaluator): the person's events, events with no person,
# or both.
BEHAVIOUR_FEATHERS = ("person", "machine", "any")


def behaviour_fields_of(obj) -> Dict:
    """A Wing's behaviour fields as one dict (WingConfig, Wing or a dict)."""
    get = obj.get if isinstance(obj, dict) else (lambda k, d=None: getattr(obj, k, d))
    return {k: get(k) for k in BEHAVIOUR_FIELDS}


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def behaviour_step_label(step, index: int) -> str:
    """'Step 2 (log_cleared)' - for messages."""
    what = ""
    if isinstance(step, dict):
        what = step.get('label') or step.get('rule_id') or step.get('activity') or ""
        if isinstance(what, (list, tuple)):
            what = ", ".join(str(w) for w in what)
    return f"Step {index + 1}" + (f" ({what})" if what else "")


def behaviour_problems(behaviour: Dict, semantic_rules=None) -> List[str]:
    """Why a Behaviour Wing's steps, time range, subject or alert cannot run."""
    b = behaviour or {}
    problems: List[str] = []
    steps = b.get('steps') or []
    if not isinstance(steps, list):
        return ["A Behaviour Wing's steps must be a list."]
    if not steps and not semantic_rules:
        problems.append("A Behaviour Wing needs at least one behaviour step.")
    for i, step in enumerate(steps):
        label = behaviour_step_label(step, i)
        if not isinstance(step, dict):
            problems.append(f"{label} is not a step.")
            continue
        names = [step.get('rule_id'), step.get('activity')]
        if not any(names):
            problems.append(f"{label} names no behaviour: give a UBA rule id or an activity.")
        if step.get('rule_id') and step.get('activity'):
            problems.append(f"{label} names both a rule and an activity; choose one.")
        min_count = step.get('min_count', 1)
        if isinstance(min_count, bool) or not isinstance(min_count, int) or min_count < 1:
            problems.append(f"{label}: the minimum count must be a whole number of 1 or more.")
        actor = step.get('actor', 'person')
        if actor not in STEP_ACTORS:
            problems.append(f"{label}: actor must be one of {', '.join(STEP_ACTORS)}.")
        min_sev = step.get('min_severity')
        if min_sev is not None and min_sev not in UBA_SEVERITIES:
            problems.append(f"{label}: minimum severity must be one of "
                            f"{', '.join(UBA_SEVERITIES)}.")
        for cond in step.get('conditions') or []:
            if not isinstance(cond, dict) or not cond.get('field_name') \
                    or 'value' not in cond:
                problems.append(f"{label}: every condition needs a field and a value.")
                continue
            field_name = str(cond.get('field_name'))
            if field_name not in BEHAVIOUR_EVENT_FIELDS and not field_name.startswith('details.'):
                problems.append(
                    f"{label}: '{field_name}' is not a behaviour event field. Use one of "
                    f"{', '.join(BEHAVIOUR_EVENT_FIELDS)}, or details.<name>.")
            if cond.get('operator', 'equals') not in STEP_OPERATORS:
                problems.append(f"{label}: unknown operator '{cond.get('operator')}'.")
    within = _number(b.get('within_minutes'))
    if steps and (within is None or within <= 0):
        problems.append("A Behaviour Wing needs a time range: within_minutes must be "
                        "a number of minutes greater than 0.")
    gap = b.get('max_gap_minutes')
    if gap is not None:
        gap_n = _number(gap)
        if gap_n is None or gap_n < 0:
            problems.append("max_gap_minutes must be a number of minutes, 0 or more.")
        elif b.get('ordered', True) is False:
            problems.append("max_gap_minutes applies to steps in order; this Wing's "
                            "steps may happen in any order. Remove it, or set ordered.")
        elif within is not None and gap_n > within:
            problems.append("max_gap_minutes is longer than within_minutes, the span "
                            "the whole set must fit in.")
    ordered = b.get('ordered', True)
    if ordered is not None and not isinstance(ordered, bool):
        problems.append("ordered must be true or false.")
    subject = b.get('subject') or {}
    if not isinstance(subject, dict):
        problems.append("subject must be an object.")
    else:
        scope = subject.get('scope', 'everyone')
        if scope not in SUBJECT_SCOPES:
            problems.append(f"subject scope must be one of {', '.join(SUBJECT_SCOPES)}.")
        elif scope != 'everyone' and not subject.get(scope):
            problems.append(f"subject scope '{scope}' names no {scope}.")
    alert = b.get('alert') or {}
    if not isinstance(alert, dict):
        problems.append("alert must be an object.")
    elif alert.get('severity') is not None and alert.get('severity') not in ALERT_SEVERITIES:
        problems.append(f"alert severity must be one of {', '.join(ALERT_SEVERITIES)}.")
    for rule in semantic_rules or []:
        rget = rule.get if isinstance(rule, dict) else (lambda k, d=None: getattr(rule, k, d))
        if str(rget('rule_type', 'match') or 'match').lower() == 'match':
            problems.append(
                f"Rule '{rget('rule_id', '')}' is a match rule; in a Behaviour Wing a single "
                f"behaviour is written as a step. Its own rules are absence, threshold or "
                f"sequence rules.")
            continue
        for fid in _rule_feather_ids(rule):
            if fid not in BEHAVIOUR_FEATHERS:
                rid = rule.get('rule_id') if isinstance(rule, dict) else getattr(rule, 'rule_id', '')
                problems.append(
                    f"Rule '{rid}' names feather '{fid}'; a Behaviour Wing's rules read "
                    f"behaviour events: use {', '.join(BEHAVIOUR_FEATHERS)}.")
                break
    return problems


def _rule_feather_ids(rule) -> List[str]:
    """Every feather_id a rule's conditions name (conditions, groups, and the
    absence / threshold / sequence blocks)."""
    get = rule.get if isinstance(rule, dict) else (lambda k, d=None: getattr(rule, k, d))
    out: List[str] = []

    def add(cond):
        if isinstance(cond, dict):
            if cond.get('feather_id'):
                out.append(str(cond['feather_id']))
            for c in cond.get('conditions') or []:
                add(c)
        elif cond is not None and getattr(cond, 'feather_id', None):
            out.append(str(cond.feather_id))

    for c in get('conditions', []) or []:
        add(c)
    for g in get('condition_groups', []) or []:
        add(g)
    absence = get('absence') or {}
    for key in ('expect_present', 'require_absent'):
        for c in absence.get(key, []) or []:
            add(c)
    threshold = get('threshold') or {}
    add(threshold.get('condition'))
    for c in threshold.get('conditions', []) or []:
        add(c)
    for st in (get('sequence') or {}).get('steps', []) or []:
        add(st)
    return out


def _get_anchor_priority_from_registry() -> List[str]:
    """Get anchor priority list from artifact type registry"""
    try:
        from .artifact_type_registry import get_registry
        return get_registry().get_anchor_priority_list()
    except Exception:
        # Fallback to hard-coded defaults if registry fails
        return [
            "Logs", "Prefetch", "SRUM", "AmCache", "ShimCache",
            "Jumplists", "LNK", "MFT", "USN"
        ]


@dataclass
class WingConfig:
    """Configuration for a wing (correlation rule)"""
    
    # Identification
    config_name: str
    wing_name: str
    wing_id: str
    
    # Wing definition
    description: str
    proves: str # What this wing proves
    author: str
    
    # Feathers used
    feathers: List[WingFeatherReference] = field(default_factory=list)
    
    # Correlation rules
    time_window_minutes: int = 180 # Default: 3 hours for better correlation accuracy
    minimum_matches: int = 1
    
    # Filters (wing-level)
    target_application: str = ""
    target_file_path: str = ""
    target_event_id: str = ""
    apply_to: str = "all" # "all" or "specific"
    
    # Anchor priority
    anchor_priority: List[str] = field(default_factory=lambda: _get_anchor_priority_from_registry())
    
    # Weighted scoring configuration - ENABLED BY DEFAULT
    use_weighted_scoring: bool = True # Default to True for better correlation accuracy
    # NOTE: Local scoring dict maintained for backward compatibility
    # New code should use get_score_thresholds() and get_tier_weights() methods
    scoring: Dict = field(default_factory=lambda: {
        'enabled': True,
        'thresholds': {
            'low': 0.3,
            'medium': 0.5,
            'high': 0.7,
            'critical': 0.9
        },
        'default_tier_weights': {
            'tier1': 1.0, # Primary evidence (Logs, Prefetch)
            'tier2': 0.8, # Secondary evidence (Registry, AmCache)
            'tier3': 0.6, # Supporting evidence (LNK, Jumplists)
            'tier4': 0.4 # Contextual evidence (MFT, USN)
        }
    })
    
    # Wing-specific semantic rules
    semantic_rules: List[Dict] = field(default_factory=list)
    
    # Metadata
    created_date: str = field(default_factory=lambda: datetime.now().isoformat())
    last_modified: str = field(default_factory=lambda: datetime.now().isoformat())
    version: str = "1.0"
    
    # Tags and categorization
    tags: List[str] = field(default_factory=list)
    case_types: List[str] = field(default_factory=list)

    # True when the analyst changed a shipped Wing's rules in the Wing Creator.
    # Unset, a copy of a shipped Wing takes the shipped rules at load (case
    # folders hold copies saved before the rules existed or changed); set, its
    # own rules are kept - they used to be replaced on every load.
    rules_edited: bool = False

    # EYE agent provenance — populated when EYE creates / edits the wing.
    # ``None`` for human-authored or built-in wings (back-compat). The
    # correlation_edit_wing handler refuses to mutate a wing whose
    # ``eye_authorship`` is ``None`` or whose ``created_by`` does not
    # start with ``"eye"``. See correlation_engine/config/eye_authorship.py.
    eye_authorship: Optional[EyeAuthorship] = None

    # Which engine runs this Wing: "time", "identity" or "behaviour", one each.
    # None = uncategorised (a Wing saved before categories existed); it does
    # not run until the analyst picks one in the Wing Creator.
    wing_category: Optional[str] = None

    # Behaviour Wings only (see BEHAVIOUR_FIELDS above): the behaviour steps,
    # whether they must happen in order, the span the whole set must fit in,
    # the gap allowed between ordered steps, whom the Wing watches, and the
    # alert it raises. Written to dict/JSON only when set, so Time and
    # Identity Wings save exactly as before.
    steps: List[Dict] = field(default_factory=list)
    ordered: bool = True
    within_minutes: Optional[float] = None
    max_gap_minutes: Optional[float] = None
    subject: Dict = field(default_factory=dict)
    alert: Dict = field(default_factory=dict)

    # Centralized score configuration manager (not serialized)
    _score_config_manager: Optional[ScoreConfigurationManager] = field(default=None, init=False, repr=False)
    
    def __post_init__(self):
        """Initialize score configuration manager after dataclass initialization"""
        self._score_config_manager = ScoreConfigurationManager()
        self.wing_category = normalize_wing_category(self.wing_category)
    
    def get_score_thresholds(self) -> Dict[str, float]:
        """
        Get score thresholds from centralized configuration.
        
        Returns:
            Dictionary of score thresholds (low, medium, high, critical)
        
        Requirements: 7.2, 8.2
        """
        if self._score_config_manager is None:
            self._score_config_manager = ScoreConfigurationManager()
        
        config = self._score_config_manager.get_configuration()
        return config.thresholds.copy()
    
    def get_tier_weights(self) -> Dict[str, float]:
        """
        Get tier weights from centralized configuration.
        
        Returns:
            Dictionary of tier weights (tier1, tier2, tier3, tier4)
        
        Requirements: 7.2, 8.2
        """
        if self._score_config_manager is None:
            self._score_config_manager = ScoreConfigurationManager()
        
        config = self._score_config_manager.get_configuration()
        return config.tier_weights.copy()
    
    @staticmethod
    def semantic_rules_are_advanced(semantic_rules: List[Dict]) -> bool:
        """True if any rule needs the Identity engine; see
        ``semantic_mapping.rule_is_advanced``, the one definition."""
        from .semantic_mapping import rules_are_advanced
        return rules_are_advanced(semantic_rules)

    def has_advanced_rules(self) -> bool:
        """Whether this wing contains any Identity-engine-only advanced rules."""
        return self.semantic_rules_are_advanced(self.semantic_rules)

    def category_problems(self) -> List[str]:
        """Why this Wing cannot be saved or run as it stands (empty = fine)."""
        return category_problems(self.wing_category, self.semantic_rules, self.feathers,
                                 behaviour=behaviour_fields_of(self))

    def is_behaviour_wing(self) -> bool:
        return self.wing_category == WING_CATEGORY_BEHAVIOUR

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        # Convert WingFeatherReference objects to dicts
        data['feathers'] = [asdict(f) for f in self.feathers]
        # Remove non-serializable fields
        data.pop('_score_config_manager', None)
        if not data.get('rules_edited'):
            data.pop('rules_edited', None)
        # Behaviour fields only where they say something: a Time or Identity
        # Wing round-trips with exactly the keys it had before they existed.
        if not self.is_behaviour_wing():
            defaults = {'steps': [], 'ordered': True, 'within_minutes': None,
                        'max_gap_minutes': None, 'subject': {}, 'alert': {}}
            for key, default in defaults.items():
                if data.get(key) == default:
                    data.pop(key, None)
        return data
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), indent=indent)
    
    def save_to_file(self, file_path: str):
        """Save configuration to JSON file"""
        with open(file_path, 'w') as f:
            f.write(self.to_json())
        try:
            from utils import custody
            custody.record_config(file_path, 'wing configuration')
        except Exception:
            pass
    
    @classmethod
    def from_dict(cls, data: dict) -> 'WingConfig':
        """Create from dictionary"""
        logger.debug(f"[WingConfig] Loading wing: {data.get('wing_name', 'Unknown')}")
        
        # Convert feather dicts to WingFeatherReference objects
        if 'feathers' in data:
            feather_refs = []
            for i, f in enumerate(data['feathers']):
                if isinstance(f, dict):
                    logger.debug(f"[WingConfig] Feather {i+1}: {f.get('feather_id', 'unknown')}")
                    
                    # Handle Wing Creator JSON format (uses database_filename)
                    if 'database_filename' in f and 'feather_database_path' not in f:
                        f = f.copy() # Don't modify original
                        f['feather_database_path'] = f.pop('database_filename')
                    
                    # Handle missing feather_config_name (use feather_id as fallback)
                    if 'feather_config_name' not in f and 'feather_id' in f:
                        f['feather_config_name'] = f['feather_id']
                    
                    # Ensure required fields exist
                    if 'feather_database_path' not in f:
                        logger.warning(f"[WingConfig] WARNING: Feather {i+1} missing feather_database_path!")
                    if 'artifact_type' not in f:
                        logger.warning(f"[WingConfig] WARNING: Feather {i+1} missing artifact_type!")
                    
                    # Filter out unexpected keys
                    valid_keys = {
                        'feather_config_name', 'feather_database_path', 'artifact_type',
                        'feather_id', 'table_name', 'artifact_type_override',
                        'weight', 'tier', 'tier_name' # Weighted scoring fields
                    }
                    filtered_f = {k: v for k, v in f.items() if k in valid_keys}
                    
                    feather_refs.append(WingFeatherReference(**filtered_f))
                else:
                    feather_refs.append(f)
            
            data['feathers'] = feather_refs
            logger.debug(f"[WingConfig] Created {len(feather_refs)} feather references")
        else:
            logger.warning(f"[WingConfig] WARNING: No 'feathers' key in wing data!")
        
        # Handle Wing Creator JSON format (nested correlation_rules)
        if 'correlation_rules' in data:
            rules = data.pop('correlation_rules')
            # Map correlation_rules fields to WingConfig fields
            if 'time_window_minutes' in rules:
                data['time_window_minutes'] = rules['time_window_minutes']
            if 'minimum_matches' in rules:
                data['minimum_matches'] = rules['minimum_matches']
            if 'target_application' in rules:
                data['target_application'] = rules['target_application']
            if 'target_file_path' in rules:
                data['target_file_path'] = rules['target_file_path']
            if 'target_event_id' in rules:
                data['target_event_id'] = rules['target_event_id']
            if 'apply_to' in rules:
                data['apply_to'] = rules['apply_to']
            if 'anchor_priority' in rules:
                data['anchor_priority'] = rules['anchor_priority']
            if 'use_weighted_scoring' in rules:
                data['use_weighted_scoring'] = rules['use_weighted_scoring']
        
        # Handle Wing Creator JSON format (nested metadata)
        if 'metadata' in data:
            metadata = data.pop('metadata')
            if 'tags' in metadata:
                data['tags'] = metadata['tags']
            if 'case_types' in metadata:
                data['case_types'] = metadata['case_types']
        
        # Backward compatibility: Apply default scoring config if not present
        if 'scoring' not in data or not data.get('scoring'):
            data['scoring'] = {
                'enabled': True,
                'thresholds': {
                    'low': 0.3,
                    'medium': 0.5,
                    'high': 0.7,
                    'critical': 0.9
                },
                'default_tier_weights': {
                    'tier1': 1.0,
                    'tier2': 0.8,
                    'tier3': 0.6,
                    'tier4': 0.4
                }
            }
            logger.debug(f"[WingConfig] Applied default scoring configuration")
        
        # Backward compatibility: Enable weighted scoring by default for wings without explicit setting
        if 'use_weighted_scoring' not in data:
            data['use_weighted_scoring'] = True
            logger.debug(f"[WingConfig] Enabled weighted scoring by default")
        
        # Load default semantic rules for any default wing — discovered by
        # matching wing_id against the wing_id embedded in every JSON file
        # under the default_wings folder. Previously this only fired for two
        # hardcoded wing IDs; new defaults would have silently received [].
        wing_id = data.get('wing_id', '')
        if wing_id:
            try:
                default_data = shipped_wings().get(wing_id)
                for default_data in ([default_data] if default_data else []):
                    # An analyst's edit to a shipped Wing's rules is kept; a
                    # copy that was only saved, never edited, takes the
                    # shipped rules (it may predate them).
                    if default_data.get('semantic_rules') and not data.get('rules_edited'):
                        data['semantic_rules'] = default_data['semantic_rules']
                        logger.debug(f"[WingConfig] Loaded {len(data['semantic_rules'])} default semantic rules for {wing_id}")
                    # A copy of a shipped Wing saved before categories existed
                    # (every case folder has them) takes the shipped category:
                    # it is the same Wing, not a user Wing to ask about.
                    if not normalize_wing_category(data.get('wing_category')) and \
                            normalize_wing_category(default_data.get('wing_category')):
                        data['wing_category'] = default_data['wing_category']
                    break
            except Exception as e:
                logger.warning(f"[WingConfig] Could not load default semantic rules: {e}")
        
        # Initialize empty semantic_rules if not present (for non-default wings)
        if 'semantic_rules' not in data:
            data['semantic_rules'] = []
        
        # Ensure required fields have defaults
        if 'config_name' not in data and 'wing_name' in data:
            data['config_name'] = data['wing_name'].lower().replace(' ', '_')

        # Rehydrate EYE authorship if present (legacy wings have no
        # eye_authorship key at all — from_dict returns None for that).
        if 'eye_authorship' in data:
            raw = data['eye_authorship']
            data['eye_authorship'] = (
                raw if isinstance(raw, EyeAuthorship) else EyeAuthorship.from_dict(raw)
            )

        # Drop any unexpected top-level keys to keep cls(**data) safe
        # against forward-compatible schema additions in saved files.
        valid = {f.name for f in cls.__dataclass_fields__.values() if f.init}
        data = {k: v for k, v in data.items() if k in valid}

        return cls(**data)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'WingConfig':
        """Create from JSON string"""
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    @classmethod
    def load_from_file(cls, file_path: str) -> 'WingConfig':
        """Load configuration from JSON file"""
        with open(file_path, 'r') as f:
            return cls.from_json(f.read())
