"""
The Wing's own semantic rules, evaluated by the engine that runs the Wing.

Before this existed no production run evaluated a Wing's ``semantic_rules``:
the pipeline dropped them when it converted the Wing, and the Identity
engine's semantic phase only ran the global rules through the SQL mapper. The
five advanced Wings' absence / sequence / threshold rules therefore never
fired, whatever the evidence. The Time-Window engine had its own per-match
evaluator (``_apply_semantic_rules_to_matches``) that nothing called, so a
Time Wing's rules never ran either.

On the Time-Window engine (``engine='time'``) only match rules run, once per
match (``annotate_match``): a Time Wing cannot carry an advanced rule, and an
old uncategorised Wing's advanced rules are skipped and named in the log,
because a match holds one window's rows per feather. The hits are stored
twice in ``semantic_data``: under ``identity_semantic_results`` like the
Identity engine's, and under ``wing_rules`` in the ``semantic_mappings``
shape the Time-Window results views read.

How the rules are applied on the Identity engine:

* advanced rules (absence / sequence / threshold) once per IDENTITY, over all
  of its rows, through ``SemanticRuleEvaluator.evaluate_identity`` - those
  rule types carry their own time windows, and an absence ("executed, but no
  Prefetch") is a statement about the identity as a whole;
* match rules once per ANCHOR (the identity's records clustered in time),
  because a match rule says "these traces occur together", and an identity's
  whole lifetime is not "together".

A hit is an annotation, written into the matches' ``semantic_data`` under
``identity_semantic_results``; it never changes a score. An identity-level
hit annotates the anchors whose time span overlaps the rows that made it
fire. The SQL mapper overwrites ``semantic_data`` for the matches global rules
hit, so the annotations are merged back after that phase (``write_back``).

Cost: a cheap check on the identity's record references decides whether a
rule could fire at all before any row is looked at, and the rows evaluated are
the ones the anchors already read - no second read of the feathers.
"""

import json
import logging
import sqlite3
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from .semantic_rule_evaluator import SemanticRuleEvaluator

logger = logging.getLogger(__name__)

RESULTS_KEY = 'identity_semantic_results'
# The Time-Window results views read dict entries holding `semantic_mappings`.
VIEW_KEY = 'wing_rules'
_VIEW_FIELDS = ('rule_id', 'rule_name', 'semantic_value', 'category', 'severity',
                'confidence', 'technique_id', 'tactic')

_LOG_PREFIX = {'identity': '[Identity Engine]', 'time': '[Time-Window Engine]'}


def _conditions_of(spec) -> List[Dict[str, Any]]:
    if not isinstance(spec, dict):
        return []
    if 'conditions' in spec:
        return [c for c in spec.get('conditions') or [] if isinstance(c, dict)]
    if 'feather_id' in spec:
        return [spec]
    return []


class _RulePlan:
    """What a rule needs before it can possibly fire."""

    def __init__(self, rule: Dict[str, Any]):
        self.rule = rule
        self.rule_id = str(rule.get('rule_id') or rule.get('name') or '')
        self.rule_type = str(rule.get('rule_type') or 'match').lower()
        self.need_all = set()      # every one of these feathers must be present
        self.need_any = set()      # at least one of these
        self.min_rows = {}         # feather set -> rows needed (threshold)
        self.always = False        # cannot be pre-judged (e.g. only negations)

        if self.rule_type == 'threshold':
            spec = rule.get('threshold') or {}
            conds = _conditions_of(spec.get('condition')) or _conditions_of(spec)
            feathers = frozenset(c.get('feather_id') for c in conds if c.get('feather_id'))
            self.need_any = set(feathers)
            self.min_rows = {feathers: int(spec.get('min_count', 2) or 2)}
        elif self.rule_type == 'absence':
            spec = rule.get('absence') or {}
            self.need_all = {c.get('feather_id') for c in spec.get('expect_present') or []
                             if isinstance(c, dict) and c.get('feather_id')}
        elif self.rule_type == 'sequence':
            spec = rule.get('sequence') or {}
            for step in spec.get('steps') or []:
                fids = {c.get('feather_id') for c in _conditions_of(step) if c.get('feather_id')}
                if len(fids) == 1:
                    self.need_all |= fids
                self.need_any |= fids
        else:
            flat = [c for c in rule.get('conditions') or [] if isinstance(c, dict)]
            positive = [c for c in flat if not c.get('negate')]
            groups = rule.get('condition_groups') or []
            for c in flat:
                if c.get('feather_id'):
                    self.need_any.add(c['feather_id'])
            for g in groups:
                for c in (g.get('conditions') if isinstance(g, dict) else None) or []:
                    if isinstance(c, dict) and c.get('feather_id'):
                        self.need_any.add(c['feather_id'])
            if str(rule.get('logic_operator', 'AND')).upper() == 'AND' and not groups:
                self.need_all = {c['feather_id'] for c in positive if c.get('feather_id')}
            if not positive and not groups:
                self.always = True
        self.need_any.discard('_identity')
        self.need_all.discard('_identity')

    def could_fire(self, present: Counter) -> bool:
        if self.always:
            return True
        if any(present.get(f, 0) == 0 for f in self.need_all):
            return False
        if self.need_any and not any(present.get(f, 0) for f in self.need_any):
            return False
        for feathers, need in self.min_rows.items():
            if sum(present.get(f, 0) for f in feathers) < need:
                return False
        return True


class WingRulePass:
    """One Wing's rules over one engine run of that Wing.

    ``engine`` is 'identity' (match rules per anchor, advanced rules per
    identity) or 'time' (match rules per match; advanced rules skipped).
    """

    def __init__(self, wing: Any, semantic_manager=None, engine: str = 'identity'):
        self.engine = 'time' if engine == 'time' else 'identity'
        self.log_prefix = _LOG_PREFIX[self.engine]
        self.wing_id = getattr(wing, 'wing_id', None)
        self.wing_name = getattr(wing, 'wing_name', '') or ''
        rules = [r for r in (getattr(wing, 'semantic_rules', None) or [])
                 if isinstance(r, dict) and not r.get('disabled')]
        self.advanced_skipped: List[str] = []
        if self.engine == 'time':
            from ..config.semantic_mapping import rule_is_advanced
            self.advanced_skipped = [str(r.get('rule_id') or r.get('name') or '')
                                     for r in rules if rule_is_advanced(r)]
            rules = [r for r in rules if not rule_is_advanced(r)]
        plans = [_RulePlan(r) for r in rules]
        self.match_plans = [p for p in plans if p.rule_type == 'match']
        self.identity_plans = [p for p in plans if p.rule_type != 'match']
        self.enabled = bool(plans) and _wing_rules_enabled()
        self.matches_evaluated = 0
        self.evaluator = None
        if self.enabled:
            self.evaluator = SemanticRuleEvaluator(
                semantic_manager=semantic_manager, enable_parallel=False)
        self.pending: Dict[str, List[Dict[str, Any]]] = {}
        self.names: Dict[str, str] = {}   # match_id -> matched_application (Time-Window)
        self.written = 0                  # annotated matches already stored
        self.hits_by_rule: Counter = Counter()
        self.identities_checked = 0
        self.identities_evaluated = 0
        self.anchors_evaluated = 0
        self.errors = 0

    # ------------------------------------------------------------------ run --

    def annotate(self, identity_data: Dict[str, Any], refs: List[tuple], anchors: List[Any]) -> None:
        """Evaluate the Wing's rules for one identity and annotate its anchors."""
        if not self.enabled or not anchors:
            return
        self.identities_checked += 1
        try:
            present = Counter(r[0] for r in refs)
            name = identity_data.get('base_name') or identity_data.get('name') or ''
            base = {'identity_type': 'name', 'identity_value': name, 'identity_name': name}

            identity_rules = [p.rule for p in self.identity_plans if p.could_fire(present)]
            if identity_rules:
                self.identities_evaluated += 1
                data = dict(base)
                data['evidence'] = [
                    {'feather_id': fid, 'data': rec}
                    for anchor in anchors
                    for fid, recs in (getattr(anchor, 'feather_records', None) or {}).items()
                    for rec in (recs if isinstance(recs, list) else [recs])
                    if isinstance(rec, dict)
                ]
                for result in self._evaluate(data, identity_rules):
                    self._attach(result, anchors, 'identity')

            if self.match_plans:
                for anchor in anchors:
                    if self._annotate_one(base, anchor, 'anchor'):
                        self.anchors_evaluated += 1
        except Exception as e:
            self.errors += 1
            if self.errors <= 5:
                logger.warning(f"{self.log_prefix} Wing rule evaluation failed for an "
                               f"identity of '{self.wing_name}': {e}")

    def annotate_match(self, match: Any) -> None:
        """Time-Window engine: evaluate the Wing's match rules on one match."""
        if not self.enabled or not self.match_plans or match is None:
            return
        try:
            name = getattr(match, 'matched_application', None) or ''
            base = {'identity_type': 'name', 'identity_value': name, 'identity_name': name}
            if self._annotate_one(base, match, 'match'):
                self.matches_evaluated += 1
        except Exception as e:
            self.errors += 1
            if self.errors <= 5:
                logger.warning(f"{self.log_prefix} Wing rule evaluation failed for a "
                               f"match of '{self.wing_name}': {e}")

    def _annotate_one(self, base: Dict[str, Any], target: Any, scope: str) -> bool:
        """Match rules over one anchor / match; False when no rule could fire."""
        feather_records = getattr(target, 'feather_records', None) or {}
        present = Counter({fid: len(recs) if isinstance(recs, list) else 1
                           for fid, recs in feather_records.items()})
        rules = [p.rule for p in self.match_plans if p.could_fire(present)]
        if not rules:
            return False
        # Each row, tagged with its feather, as an 'anchor'. Not the
        # {'feather_id', 'data'} 'evidence' wrapper: when every feather holds a
        # single row the evaluator judges its one-row-per-feather record set,
        # which keeps the wrapper itself as the row, so no condition ever
        # found its field and a match rule could not fire on such a match.
        data = dict(base)
        data['anchors'] = [
            dict(rec, feather_id=fid)
            for fid, recs in feather_records.items()
            for rec in (recs if isinstance(recs, list) else [recs])
            if isinstance(rec, dict)
        ]
        for result in self._evaluate(data, rules):
            self._attach(result, [target], scope)
        return True

    def _evaluate(self, identity_data, rules) -> List[Any]:
        return self.evaluator.evaluate_identity(
            identity_data, wing_id=self.wing_id, wing_rules=rules,
            allow_advanced=self.engine != 'time', wing_rules_only=True)

    def _attach(self, result, anchors, scope: str) -> None:
        entry = result.to_dict()
        entry['evaluated_on'] = scope
        entry['wing_id'] = self.wing_id
        targets = anchors
        if scope == 'identity' and len(anchors) > 1:
            overlapping = [a for a in anchors if _overlaps(a, entry)]
            targets = overlapping or anchors
            # No anchor falls in the hit's time span: it is stamped on every
            # anchor, and says so, so the results do not present a finding
            # about the identity as one about this anchor's hours.
            if not overlapping:
                entry['identity_wide'] = True
        for anchor in targets:
            sd = getattr(anchor, 'semantic_data', None)
            if not isinstance(sd, dict):
                sd = {}
            listed = [r for r in sd.get(RESULTS_KEY) or [] if isinstance(r, dict)
                      and r.get('rule_id') != entry['rule_id']]
            listed.append(entry)
            self._store(sd, listed, getattr(anchor, 'matched_application', None))
            anchor.semantic_data = sd
            match_id = getattr(anchor, 'match_id', None)
            if match_id:
                self.pending[match_id] = listed
                if self.engine == 'time':
                    self.names[match_id] = getattr(anchor, 'matched_application', None) or ''
        self.hits_by_rule[entry['rule_id']] += 1

    # -------------------------------------------------------------- results --

    def write_back(self, database_path: Optional[str]) -> int:
        """Merge the annotations into the stored matches; returns rows updated.

        Run after the SQL semantic phase, which replaces ``semantic_data`` on
        every match a global rule hit. Matches not yet in the database stay
        pending, so a second call after they are saved stores them; a stored
        match is not written again.
        """
        if not self.pending or not database_path:
            return 0
        updated = 0
        done: List[str] = []
        conn = sqlite3.connect(database_path, timeout=30.0)
        try:
            ids = list(self.pending)
            for start in range(0, len(ids), 500):
                chunk = ids[start:start + 500]
                rows = conn.execute(
                    "SELECT match_id, semantic_data FROM matches WHERE match_id IN (%s)"
                    % ",".join("?" * len(chunk)), chunk).fetchall()
                batch = []
                for match_id, raw in rows:
                    try:
                        sd = json.loads(raw) if raw else {}
                    except (ValueError, TypeError):
                        sd = {}
                    if not isinstance(sd, dict):
                        sd = {}
                    wanted = self.pending[match_id]
                    keep = [r for r in sd.get(RESULTS_KEY) or [] if isinstance(r, dict)
                            and r.get('rule_id') not in {w['rule_id'] for w in wanted}]
                    self._store(sd, keep + wanted, self.names.get(match_id))
                    batch.append((json.dumps(sd, default=str), match_id))
                    done.append(match_id)
                conn.executemany("UPDATE matches SET semantic_data = ? WHERE match_id = ?", batch)
                conn.commit()
                updated += len(batch)
        finally:
            conn.close()
        for match_id in done:
            self.pending.pop(match_id, None)
            self.names.pop(match_id, None)
        self.written += len(done)
        return updated

    def _store(self, sd: Dict[str, Any], listed: List[Dict[str, Any]], name: Optional[str]) -> None:
        """Put the hits into ``semantic_data``.

        Time-Window: the ``wing_rules`` entry goes BEFORE the list, because
        the Time-Window results table shows the first entry of the dict and
        prints a list it meets first as raw text.
        """
        if self.engine != 'time':
            sd[RESULTS_KEY] = listed
            return
        sd.pop(VIEW_KEY, None)
        sd.pop(RESULTS_KEY, None)
        sd[VIEW_KEY] = self._view_entry(listed, name)
        sd[RESULTS_KEY] = listed

    @staticmethod
    def _view_entry(results: List[Dict[str, Any]], name: Optional[str]) -> Dict[str, Any]:
        """The hits in the shape the Time-Window results views read."""
        return {
            'identity_type': 'Wing rule',
            'identity_value': name or '',
            'semantic_mappings': [{k: r.get(k) for k in _VIEW_FIELDS if k in r}
                                  for r in results if isinstance(r, dict)],
        }

    def summary(self) -> Dict[str, Any]:
        return {
            'rules': len(self.match_plans) + len(self.identity_plans),
            'advanced_rules': len(self.identity_plans),
            'identities_checked': self.identities_checked,
            'identities_evaluated': self.identities_evaluated,
            'anchors_evaluated': self.anchors_evaluated,
            'engine': self.engine,
            'matches_evaluated': self.matches_evaluated,
            'advanced_skipped': list(self.advanced_skipped),
            'matches_annotated': len(self.pending) + self.written,
            'hits_by_rule': dict(self.hits_by_rule),
            'errors': self.errors,
        }

    def log_summary(self) -> None:
        p = self.log_prefix
        if self.advanced_skipped:
            logger.warning(
                f"{p} Wing '{self.wing_name}': {len(self.advanced_skipped)} advanced rule(s) "
                f"not evaluated ({', '.join(self.advanced_skipped)}); the Time-Window engine "
                f"runs match rules only. Run this Wing as an Identity Wing to evaluate them.")
        if not (self.match_plans or self.identity_plans):
            return
        s = self.summary()
        if not self.enabled:
            logger.info(f"{p} Wing rules of '{self.wing_name}' not evaluated: "
                        f"Wings Semantic Mapping is off in Settings")
            return
        hits = ", ".join(f"{k}={v}" for k, v in sorted(s['hits_by_rule'].items())) or "none"
        if self.engine == 'time':
            scope = f"{s['matches_evaluated']:,} matches evaluated"
            failed = "matches"
        else:
            scope = (f"{s['identities_evaluated']:,} identities and "
                     f"{s['anchors_evaluated']:,} anchors evaluated")
            failed = "identities"
        logger.info(
            f"{p} Wing rules of '{self.wing_name}': {s['rules']} rule(s) "
            f"({s['advanced_rules']} advanced); {scope}; {s['matches_annotated']:,} matches "
            f"annotated; hits: {hits}"
            + (f"; evaluation FAILED for {s['errors']:,} {failed} (first errors above)"
               if s['errors'] else ""))


def _wing_rules_enabled() -> bool:
    """The Settings > General > Wings Semantic Mapping switch (default on)."""
    try:
        from config.case_history_manager import CaseHistoryManager
        return bool(getattr(CaseHistoryManager().global_config,
                            'wings_semantic_mapping_enabled', True))
    except Exception:
        return True


def _overlaps(anchor, entry) -> bool:
    first = SemanticRuleEvaluator._parse_ts(entry.get('first_seen'))
    last = SemanticRuleEvaluator._parse_ts(entry.get('last_seen')) or first
    if first is None:
        return True
    start = SemanticRuleEvaluator._parse_ts(getattr(anchor, 'anchor_start_time', None)
                                            or getattr(anchor, 'timestamp', None))
    end = SemanticRuleEvaluator._parse_ts(getattr(anchor, 'anchor_end_time', None)) or start
    if start is None:
        return False
    if end < start:
        start, end = end, start
    return start <= last and end >= first
