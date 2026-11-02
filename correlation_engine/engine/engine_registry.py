"""
Engine Registry

One place that knows the correlation engines: their ids, names, run-name
prefixes, which Wing category each runs, how to build one, and which results
view shows its output. Code that used to compare engine strings by hand
("identity_based", "time_based", "time_window_scanning"...) asks here instead,
and an engine type nobody registered raises rather than silently becoming the
Time-Window engine.

Each Wing has one category (Time, Identity or Behaviour) and each category maps
to exactly one engine. ``check_wing`` is the single answer to "can this engine
run this Wing", and ``wing_skip_message`` is the single wording of why not:
the executor's SKIPPED row, the case log line and the Execution tab all show
that text.

Headless: nothing here imports Qt.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config.wing_config import (
    WING_CATEGORY_BEHAVIOUR, WING_CATEGORY_IDENTITY, WING_CATEGORY_TIME,
    normalize_wing_category,
)

TIME_WINDOW_SCANNING = "time_window_scanning"
IDENTITY_BASED = "identity_based"
BEHAVIOURAL = "behavioural"


class UnknownEngineError(ValueError):
    """An engine type no spec is registered for."""


class EngineNotBuiltError(RuntimeError):
    """A registered engine whose implementation does not exist yet."""


# Older names still found in saved pipelines and results databases.
_ALIASES = {
    "time_window_scanning": TIME_WINDOW_SCANNING,
    "time_based": TIME_WINDOW_SCANNING,
    "time-based": TIME_WINDOW_SCANNING,
    "time_window": TIME_WINDOW_SCANNING,
    "timewindow": TIME_WINDOW_SCANNING,
    "time": TIME_WINDOW_SCANNING,
    "identity_based": IDENTITY_BASED,
    "identity-based": IDENTITY_BASED,
    "identity": IDENTITY_BASED,
    "behavioural": BEHAVIOURAL,
    "behavioral": BEHAVIOURAL,
    "behaviour": BEHAVIOURAL,
    "behavior": BEHAVIOURAL,
}


def _create_time_window(config, filters=None, scoring_integration=None,
                        mapping_integration=None):
    from .time_based_engine import TimeWindowScanningEngine
    return TimeWindowScanningEngine(
        config=config,
        filters=filters,
        debug_mode=getattr(config, 'debug_mode', False),
        scoring_integration=scoring_integration,
        mapping_integration=mapping_integration,
    )


def _create_identity(config, filters=None, scoring_integration=None,
                     mapping_integration=None):
    from .identity_based_engine_adapter import IdentityBasedEngineAdapter
    return IdentityBasedEngineAdapter(
        config=config,
        filters=filters,
        mapping_integration=mapping_integration,
        scoring_integration=scoring_integration,
    )


def _create_behavioural(config, filters=None, scoring_integration=None,
                        mapping_integration=None):
    # Behaviour Wings read UBA's behaviour events, not feathers: there is no
    # scoring or feather mapping to hand over.
    from .behavioural_engine import BehaviouralEngine
    return BehaviouralEngine(config=config, filters=filters)


@dataclass(frozen=True)
class EngineSpec:
    """What the application needs to know about one engine."""
    type_id: str
    display_name: str           # in sentences: "the Identity engine"
    selector_name: str          # in the engine drop-down
    run_prefix: str             # run names: "<prefix>_<pipeline>_Run001_..."
    wing_category: str          # the one Wing category this engine runs
    results_view: str           # "timebased" | "identity" | "behaviour"
    item_unit: str              # what its progress counts
    supports_identity_filter: bool
    # Offered in the engine pickers (Execution tab, Pipeline Builder). An
    # engine whose results view does not exist yet stays False, so no run
    # lands in a database nothing can display.
    available: bool
    factory: Callable = field(compare=False, repr=False)
    built: bool = True          # False: the factory raises EngineNotBuiltError

    def create(self, config, filters=None, scoring_integration=None,
               mapping_integration=None):
        return self.factory(config, filters, scoring_integration, mapping_integration)

    def can_run(self, wing) -> Tuple[bool, str]:
        """(True, "") when this engine runs ``wing``, else (False, reason)."""
        return check_wing(wing, self.type_id)


_SPECS: Dict[str, EngineSpec] = {}


def register(spec: EngineSpec) -> None:
    _SPECS[spec.type_id] = spec


register(EngineSpec(
    type_id=TIME_WINDOW_SCANNING,
    display_name="Time-Window engine",
    selector_name="Time Engine",
    run_prefix="TimeWindow",
    wing_category=WING_CATEGORY_TIME,
    results_view="timebased",
    item_unit="windows",
    supports_identity_filter=False,
    available=True,
    factory=_create_time_window,
))
register(EngineSpec(
    type_id=IDENTITY_BASED,
    display_name="Identity engine",
    selector_name="Identity-Based",
    run_prefix="Identity",
    wing_category=WING_CATEGORY_IDENTITY,
    results_view="identity",
    item_unit="identities",
    supports_identity_filter=True,
    available=True,
    factory=_create_identity,
))
register(EngineSpec(
    type_id=BEHAVIOURAL,
    display_name="Behavioural engine",
    selector_name="Behavioural",
    run_prefix="Behavioural",
    wing_category=WING_CATEGORY_BEHAVIOUR,
    results_view="behaviour",
    item_unit="people",
    supports_identity_filter=False,
    available=True,
    factory=_create_behavioural,
    built=True,
))


def normalize_engine_type(engine_type) -> str:
    """The registered id for ``engine_type`` (legacy names accepted).

    Raises UnknownEngineError for anything else - an unknown engine used to be
    displayed and named as the Time-Window engine, which reports the wrong
    strategy for the findings.
    """
    if isinstance(engine_type, EngineSpec):
        return engine_type.type_id
    key = str(engine_type or "").strip().lower()
    type_id = _ALIASES.get(key)
    if type_id is None or type_id not in _SPECS:
        raise UnknownEngineError(
            f"Unknown correlation engine type {engine_type!r}. Registered: "
            f"{', '.join(sorted(_SPECS))}.")
    return type_id


def is_known_engine_type(engine_type) -> bool:
    try:
        normalize_engine_type(engine_type)
        return True
    except UnknownEngineError:
        return False


def get_spec(engine_type) -> EngineSpec:
    return _SPECS[normalize_engine_type(engine_type)]


def all_specs(include_unavailable: bool = False) -> List[EngineSpec]:
    return [s for s in _SPECS.values() if include_unavailable or s.available]


def spec_for_category(category) -> Optional[EngineSpec]:
    """The engine that runs Wings of ``category``; None if uncategorised."""
    cat = normalize_wing_category(category)
    for spec in _SPECS.values():
        if spec.wing_category == cat:
            return spec
    return None


def results_view_of(engine_type) -> str:
    return get_spec(engine_type).results_view


def results_view_or_none(engine_type) -> Optional[str]:
    """``results_view_of`` for display code reading stored runs: an engine type
    nobody registered is logged as an error and gets no view, rather than
    being drawn as a Time-Window run."""
    try:
        return results_view_of(engine_type)
    except UnknownEngineError as e:
        import logging
        logging.getLogger(__name__).error("%s These results are not shown.", e)
        return None


def display_name_or_raw(engine_type) -> str:
    """'Identity engine' etc.; an unregistered type is shown as stored."""
    try:
        return get_spec(engine_type).display_name
    except UnknownEngineError:
        return f"unknown engine '{engine_type}'"


def is_identity_engine(engine_type) -> bool:
    return normalize_engine_type(engine_type) == IDENTITY_BASED


def is_time_window_engine(engine_type) -> bool:
    return normalize_engine_type(engine_type) == TIME_WINDOW_SCANNING


def run_prefix(engine_type) -> str:
    return get_spec(engine_type).run_prefix


def engine_type_of(engine) -> str:
    """The registered type of a built engine object, read from its class's
    ``ENGINE_TYPE``. Raises UnknownEngineError when the class declares none."""
    declared = getattr(type(engine), 'ENGINE_TYPE', None) if engine is not None else None
    if not declared:
        raise UnknownEngineError(
            f"Engine object {type(engine).__name__} declares no ENGINE_TYPE; "
            f"register it in engine_registry and set ENGINE_TYPE on the class.")
    return normalize_engine_type(declared)


def create_engine(engine_type, config, filters=None, scoring_integration=None,
                  mapping_integration=None):
    return get_spec(engine_type).create(
        config, filters, scoring_integration=scoring_integration,
        mapping_integration=mapping_integration)


# ---------------------------------------------------------------- Wings ----

def _wing_attr(wing, name, default=None):
    if isinstance(wing, dict):
        return wing.get(name, default)
    return getattr(wing, name, default)


def wing_display_name(wing) -> str:
    return (_wing_attr(wing, 'wing_name') or _wing_attr(wing, 'config_name')
            or _wing_attr(wing, 'wing_id') or 'Unnamed Wing')


def wing_category_of(wing) -> Optional[str]:
    return normalize_wing_category(_wing_attr(wing, 'wing_category'))


def _article(label: str) -> str:
    return "an" if label[:1].lower() in "aeiou" else "a"


def _advanced_rule_names(wing) -> List[str]:
    from ..config.semantic_mapping import rule_is_advanced
    names = []
    for rule in _wing_attr(wing, 'semantic_rules', None) or []:
        if rule_is_advanced(rule):
            rid = rule.get('rule_id') if isinstance(rule, dict) else getattr(rule, 'rule_id', None)
            names.append(str(rid or 'unnamed rule'))
    return names


def wing_skip_message(wing, engine_type) -> Optional[str]:
    """Why ``engine_type`` will not run ``wing``, in one line; None if it will.

    The only wording of this: the executor's SKIPPED row and warning, the case
    log line and the Execution tab all show this text.
    """
    from ..config.wing_config import WING_CATEGORY_LABELS
    spec = get_spec(engine_type)
    name = wing_display_name(wing)
    category = wing_category_of(wing)
    if category is None:
        return (f"Wing '{name}' has no category; it was not run by the "
                f"{spec.display_name}. Open it in the Wing Creator and choose "
                f"Time, Identity or Behaviour.")
    if category != spec.wing_category:
        label = WING_CATEGORY_LABELS[category]
        needed = spec_for_category(category)
        needed_text = needed.display_name if needed else "its own engine"
        if needed is not None:
            needed_text += _availability_note(needed)
        return (f"Wing '{name}' is {_article(label)} {label}; it was not run by "
                f"the {spec.display_name}. Run it with the {needed_text}, or "
                f"change its category in the Wing Creator.")
    if category == WING_CATEGORY_TIME:
        advanced = _advanced_rule_names(wing)
        if advanced:
            return (f"Wing '{name}' is a Time Wing but carries advanced rules "
                    f"({', '.join(advanced)}) that only the Identity engine can "
                    f"evaluate; it was not run by the {spec.display_name}. Change "
                    f"its category to Identity in the Wing Creator, or remove "
                    f"those rules.")
    return None


def for_other_engine(wing, engine_type) -> bool:
    """True when ``wing`` is simply another engine's Wing - normal, not a problem.

    A pipeline holds Time, Identity and Behaviour Wings together and each engine runs its
    own; "24 Wings won't run with the Identity engine" read as a warning (Ghassan,
    2026-11-01). A Wing with no category, or a Time Wing carrying Identity-only rules, is
    a real problem and stays one."""
    category = wing_category_of(wing)
    return category is not None and category != get_spec(engine_type).wing_category


def check_wing(wing, engine_type) -> Tuple[bool, str]:
    """(True, "") when ``engine_type`` runs ``wing``, else (False, reason)."""
    message = wing_skip_message(wing, engine_type)
    return (message is None, message or "")


def needed_engine_label(wing) -> str:
    """Short text for a Wing listed under an engine that cannot run it."""
    category = wing_category_of(wing)
    if category is None:
        return "needs a category"
    spec = spec_for_category(category)
    if spec is None:
        return "needs a category"
    return f"needs the {spec.display_name}" + _availability_note(spec)


def _availability_note(spec: EngineSpec) -> str:
    """'' for an engine the analyst can pick; otherwise why not."""
    if not spec.built:
        return " (not built yet)"
    if not spec.available:
        return " (not in the engine list yet)"
    return ""
