# Advanced Semantic Rules (Absence · Sequence · Threshold · ATT&CK)

Crow-Eye Wings historically expressed a rule as a flat list of `field <operator> literal`
conditions joined by a single-level `AND`/`OR`, evaluated over artifacts that co-occur
inside the Wing's `time_window_minutes`. That is enough for co-occurrence + tagging but
cannot express the things stealthy adversaries are defined by. The rule model has been
**extended, backward compatibly** — every existing Wing keeps working unchanged, and the
new power is opt-in via optional fields.

All new fields live on the existing `SemanticRule` / `SemanticCondition` and flow through
`WingConfig.semantic_rules`, the `SemanticRuleEvaluator`, and reports/Eye AI. A rule with
none of these fields behaves exactly as before.

## New condition capabilities

Available on any condition (including inside advanced rules):

| Field | Meaning |
|-------|---------|
| `operator: not_equals / greater_than / less_than / greater_equal / less_equal` | Ordered + negated comparison, numeric or ISO-8601 timestamp aware. `not_equals` is NULL-safe (a missing field counts as "not equal"). Now works identically on the SQL and in-memory paths. |
| `negate: true` | The condition matches only when the underlying comparison does **not** hold. |
| `compare_to_feather` + `compare_to_field` | Cross-feather / field-to-field comparison: the right-hand side is another record's field instead of `value`. Enables masquerade (`prefetch.sha1 != amcache.sha1`) and timestomp (`mft.si_created < mft.fn_created`). |

`condition_groups` on a rule adds nested boolean logic: each group has its own
`logic_operator` and is combined with the rule's top-level operator, giving
`(A AND B) OR (C AND D)` alongside the flat `conditions` list.

## Rule types (`rule_type`)

### `absence` — missing-evidence (the core stealth primitive)
Fires when expected evidence is present but required-absent evidence is missing.
```json
{
  "rule_id": "exec_no_prefetch", "name": "Execution With No Prefetch Trace",
  "semantic_value": "Prefetch Trace Suppressed", "rule_type": "absence",
  "severity": "high", "technique_id": ["T1070.004", "T1562.001"],
  "absence": {
    "expect_present": [{ "feather_id": "amcache", "field_name": "executable_name", "operator": "wildcard", "value": "*" }],
    "require_absent": [{ "feather_id": "prefetch", "field_name": "executable_name", "operator": "wildcard", "value": "*" }],
    "within_minutes": 30
  }
}
```

### `threshold` — occurrence count
Fires only on `>= min_count` matches, optionally within `within_minutes` and grouped by `group_by`.
```json
{
  "rule_id": "af_mass_delete", "name": "Mass Delete Burst", "semantic_value": "Mass File Deletion",
  "rule_type": "threshold", "severity": "high", "technique_id": ["T1070.004", "T1485"],
  "threshold": {
    "condition": { "feather_id": "mft_usn", "field_name": "reason", "operator": "contains", "value": "FILE_DELETE" },
    "min_count": 20, "within_minutes": 5
  }
}
```

### `sequence` — ordered kill-chain
Fires when the ordered steps occur in order, each consecutive gap within `max_gap_minutes`.
```json
{
  "rule_id": "lat_chain", "name": "Logon → Remote Tool → Admin-Share Drop",
  "semantic_value": "Ordered Lateral Movement", "rule_type": "sequence",
  "severity": "critical", "technique_id": ["T1021"],
  "sequence": {
    "max_gap_minutes": 30,
    "steps": [
      { "feather_id": "security_logs", "field_name": "EventID", "operator": "equals", "value": "4624" },
      { "feather_id": "prefetch", "field_name": "executable_name", "operator": "contains", "value": "psexec" },
      { "feather_id": "mft_usn", "field_name": "path", "operator": "contains", "value": "$" }
    ]
  }
}
```

## MITRE ATT&CK tagging
Rules may carry `technique_id` and `tactic` (arrays). Matched results carry these through,
and `correlation_engine/config/attack_catalog.py::compute_attack_coverage(results)` rolls
them up into per-tactic / per-technique coverage (with counts and max severity) for the
results view, reports, and Eye AI. The catalogue is fully offline (no network).

## Authoring in the Wing Creator
New wings default to **Simple** — identical to the historical behaviour. In the *Advanced
Semantic Rules* section, tick **"Enable advanced rules"** to opt in; the rule editor then
exposes the `rule_type` selector (match/absence/sequence/threshold), per-type spec editors,
the full operator set, per-condition **Negate** + **Compare→ (feather.field)** columns, a
nested **Condition Groups** builder, and **ATT&CK IDs / Tactic** fields. A wing that already
contains advanced rules re-opens with the toggle on so the rules stay editable.

## Engine support — Identity engine only
Advanced rules run on the **Identity-Based engine only**. The Time-Window Scanning engine
evaluates one representative row per feather per match and cannot express multi-row / ordered /
absence logic. `WingConfig.has_advanced_rules()` detects such wings; the execution screen
badges them ("⚡ Identity engine only") and, if you try to run one on the Time-Window engine,
prompts you to **switch to the Identity engine and continue**.

## Scoring
Weighted scoring is feather-tier/coverage based and **unchanged** — simple and advanced wings
score identically. Advanced matches are annotations (semantic value, severity, ATT&CK) surfaced
alongside results, plus the `compute_attack_coverage()` rollup; they do not move the score.

## Default advanced wings
`Execution_Without_Trace` (absence + timestomp), `Brute_Force_Spray` (threshold + sequence),
`Ransomware_Mass_Encryption` (threshold), the ordered `Lateral_Movement` chain (sequence), and
the Anti-Forensics mass-delete threshold. Other default wings carry ATT&CK tags but remain
Simple (Time-Window compatible).

## Evaluation notes
- Advanced rule types are dispatched to dedicated in-memory evaluators
  (`SemanticRuleEvaluator._evaluate_absence/threshold/sequence_rule`) that operate over the
  window-scoped rows attached to each identity (anchors + `evidence_rows`), so they respect
  the correlation engine's time window and carry per-row timestamps.
- `sequence`/`threshold` need per-row timestamps; when timing is unavailable they degrade to
  a raw count / presence check rather than under-report.
- The SQL `QueryBuilder` forces advanced conditions (negation / cross-feather) and advanced
  rule types onto the in-memory path so SQL and in-memory results stay identical.

See also: [Semantic Mapping Guide](SEMANTIC_MAPPING_GUIDE.md),
[Wings Documentation](../docs/wings/WINGS_DOCUMENTATION.md).
