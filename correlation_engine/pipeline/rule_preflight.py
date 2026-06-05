"""Pre-flight validation for wing semantic rules.

Runs before correlation execution to surface "rule references unsupported
operator" and "rule references a field that doesn't exist on the named
feather" — both of which previously got swallowed as `logger.warning` deep
inside `semantic_rule_evaluator.QueryBuilder.translate_condition` and never
reached the user.

The output is a structured list the executor attaches to its summary dict;
the GUI's execution log surfaces it after the wing completes. Validation is
non-fatal — a flagged rule still runs, it may just produce no matches.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set


# Source of truth: QueryBuilder.operator_map in semantic_rule_evaluator.py.
# Keep this in sync if a new operator ships there.
_SUPPORTED_OPERATORS: Set[str] = {
    'equals', 'contains', 'regex', 'wildcard',
    'greater_than', 'less_than', 'greater_equal', 'less_equal', 'not_equals',
}


def _normalize_field_name(name: str) -> str:
    """Loose match: ignore case, underscores, dashes — matches the smart
    field lookup the evaluator already does (EventID vs event_id vs eventid)."""
    return name.replace('_', '').replace('-', '').lower()


def _collect_feather_field_map(pipeline_config) -> Dict[str, Set[str]]:
    """Map feather identifier (config_name, feather_name, feather_id, all
    lowercased too) to the set of fields declared by that FeatherConfig."""
    by_id: Dict[str, Set[str]] = {}
    for fc in getattr(pipeline_config, 'feather_configs', []) or []:
        fields: Set[str] = set(getattr(fc, 'selected_columns', None) or [])
        mapping = getattr(fc, 'column_mapping', None) or {}
        for src, dst in mapping.items():
            if src:
                fields.add(src)
            if dst:
                fields.add(dst)
        for key in (
            getattr(fc, 'config_name', '') or '',
            getattr(fc, 'feather_name', '') or '',
            getattr(fc, 'feather_id', '') or '',
        ):
            if not key:
                continue
            by_id[key] = fields
            by_id[key.lower()] = fields
    return by_id


def validate_semantic_rules(pipeline_config) -> List[Dict[str, Any]]:
    """Walk every wing's semantic_rules and report unsupported operators and
    field-not-on-feather issues. Returns a list of dicts:
        {'wing': str, 'rule_id': str, 'kind': 'unsupported_operator' | 'missing_field',
         'detail': str}
    Empty list means clean. Never raises."""

    issues: List[Dict[str, Any]] = []
    feather_fields = _collect_feather_field_map(pipeline_config)

    for wing in getattr(pipeline_config, 'wing_configs', []) or []:
        wing_name = getattr(wing, 'wing_name', '<unnamed wing>')
        rules = getattr(wing, 'semantic_rules', None) or []
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            rule_id = (
                rule.get('rule_id')
                or rule.get('rule_name')
                or rule.get('semantic_value')
                or '<unnamed rule>'
            )
            for cond in rule.get('conditions', []) or []:
                if not isinstance(cond, dict):
                    continue
                op = cond.get('operator', 'equals')
                field_name = cond.get('field_name', '') or ''
                feather_id = cond.get('feather_id', '') or ''

                if op and op not in _SUPPORTED_OPERATORS:
                    issues.append({
                        'wing': wing_name,
                        'rule_id': rule_id,
                        'kind': 'unsupported_operator',
                        'detail': (
                            f"operator '{op}' on field '{field_name}' is not "
                            f"in the evaluator's operator_map; rule will be skipped"
                        ),
                    })

                if feather_id and field_name:
                    declared = (
                        feather_fields.get(feather_id)
                        or feather_fields.get(feather_id.lower())
                    )
                    # If we don't know the schema at all, don't flag — silence
                    # beats false positives. The runtime fallback handles it.
                    if declared:
                        target = _normalize_field_name(field_name)
                        if not any(_normalize_field_name(c) == target for c in declared):
                            issues.append({
                                'wing': wing_name,
                                'rule_id': rule_id,
                                'kind': 'missing_field',
                                'detail': (
                                    f"field '{field_name}' is not declared on "
                                    f"feather '{feather_id}' (selected_columns / "
                                    f"column_mapping); rule may silently match nothing"
                                ),
                            })
    return issues


def format_issues_for_log(issues: List[Dict[str, Any]]) -> str:
    """Render issues as a multi-line block for the execution log panel.

    Uses a bracketed text marker ``[WARN]`` rather than a unicode warning
    glyph so the log stays plain-text-portable (logs get copied into
    tickets, grepped from terminals, etc.). The execution log's
    diagnostics-filter sidebar recognizes the same marker."""
    if not issues:
        return ""
    lines = [f"[WARN] Pre-flight: {len(issues)} semantic-rule issue(s):"]
    for it in issues:
        lines.append(
            f" - [{it['wing']} / {it['rule_id']}] {it['kind']}: {it['detail']}"
        )
    return "\n".join(lines)


def format_evidence_accounting_for_panel(ea: Dict[str, Any]) -> Dict[str, List[str]]:
    """Group an `evidence_accounting` dict into pre-formatted human-readable
    lines, keyed by section heading. The execution log panel joins them
    into a single block; the Issues tab renders them as a tree.

    Single source of truth so both surfaces (log line block + UI tree)
    agree on what to show.

    Returned shape:
        {
            'Silent DB fallbacks': ['3 fired (feathers: mft_usn, shellbags)'],
            'Schema-detection errors': ['mft_usn [method_2_smart]: ...'],
            'Identity-grouping errors': ['mft_usn: ...'],
            'Timestamp parse failures': ['mft_usn: 5,032/100,500 ... (5.0%)'],
        }

    Sections with no findings are omitted. Empty input returns an empty dict.
    """
    out: Dict[str, List[str]] = {}
    if not ea:
        return out

    fallback_ops = ea.get('fallback_operations', 0) or 0
    if fallback_ops > 0:
        feathers = ea.get('feathers_with_errors', []) or []
        tail = f" (feathers: {', '.join(feathers)})" if feathers else ""
        out['Silent DB fallbacks'] = [f"{fallback_ops} fired{tail}"]

    sde = ea.get('schema_detection_errors', []) or []
    if sde:
        lines: List[str] = []
        for entry in sde:
            fid = entry.get('feather_id', '?')
            method = entry.get('method', '?')
            err = entry.get('error', '?')
            lines.append(f"{fid} [{method}]: {err}")
        out['Schema-detection errors'] = lines

    phase1 = ea.get('phase1_errors', {}) or {}
    ig_errors = phase1.get('identity_grouping_errors', []) or []
    if ig_errors:
        lines = []
        for entry in ig_errors:
            fid = entry.get('feather_id', '?')
            err = entry.get('error', '?')
            lines.append(f"{fid}: {err}")
        out['Identity-grouping errors'] = lines

    parse_stats = ea.get('parse_stats_per_feather', {}) or {}
    problematic = [
        (fid, s) for fid, s in parse_stats.items()
        if (s.get('failed', 0) or 0) > 0
    ]
    if problematic:
        lines = []
        for fid, s in problematic:
            rate = s.get('failure_rate_percent', 0.0) or 0.0
            failed = s.get('failed', 0) or 0
            attempts = s.get('attempts', 0) or 0
            lines.append(
                f"{fid}: {failed:,}/{attempts:,} timestamps unparseable ({rate:.1f}%)"
            )
        out['Timestamp parse failures'] = lines

    return out


def format_evidence_accounting_for_log(ea: Dict[str, Any]) -> str:
    """Convenience: render the grouped output as a single log-panel block.

    Used by gui/execution_control.py's `_emit_evidence_accounting`.
    Returns an empty string when there are no findings (so the log isn't
    cluttered with blank [WARN] headers)."""
    groups = format_evidence_accounting_for_panel(ea)
    if not groups:
        return ""
    out_lines: List[str] = []
    for heading, lines in groups.items():
        # Bracketed `[WARN]` text marker (no emoji) for log-friendly,
        # grep-friendly output. The diagnostics-filter sidebar matches
        # the same marker so these lines mirror into the dedicated panel.
        out_lines.append(f"[WARN] {heading}: {len(lines)} entr{'y' if len(lines) == 1 else 'ies'}")
        # Cap per-section at 5 lines in the log to avoid overwhelming
        # the panel; the Issues tab renders the full list.
        for line in lines[:5]:
            out_lines.append(f" - {line}")
        if len(lines) > 5:
            out_lines.append(f" ... and {len(lines) - 5} more")
    return "\n".join(out_lines)
