"""What one Dynamic Linking run did, rule by rule - for the statistics dialog
and for dynamic_linking.log.

Before this, every rule reported one number: every mapping ``add_mapping``
accepted. A value already in the intelligence database with the same key
counted again on every run, a new key appended to an existing value counted
the same as a new value, a rule whose database was missing printed a line to
the console and left nothing anywhere, and a custom rule that failed read as
"success, 0 mappings". The numbers here separate those cases.
"""

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("dynamic_mapping.run")

# What add_mapping can do with one (value, key) pair.
INSERTED = "inserted"     # a value the database did not have
MERGED = "merged"         # a known value gained another key
DUPLICATE = "duplicate"   # the value already had this key: nothing new
REJECTED = "rejected"     # empty value or key, or a placeholder description
OUTCOMES = (INSERTED, MERGED, DUPLICATE, REJECTED)


@dataclass
class RuleResult:
    """One rule's part of a run."""
    rule: str
    rule_type: str                      # default / custom / internal / manual / ioc
    category: str = ""
    description: str = ""
    source_db: str = ""
    source_table: str = ""
    value_column: str = ""
    key_column: str = ""
    status: str = "ok"                  # ok / skipped / failed
    reason: str = ""                    # why skipped or failed
    rows_read: int = 0
    inserted: int = 0
    merged: int = 0
    duplicate: int = 0
    rejected: int = 0
    duration_ms: int = 0

    @property
    def new_links(self) -> int:
        """What this rule added to the intelligence database."""
        return self.inserted + self.merged

    def count(self, outcome: str) -> None:
        if outcome in OUTCOMES:
            setattr(self, outcome, getattr(self, outcome) + 1)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["new_links"] = self.new_links
        return d


@dataclass
class LinkRun:
    """A whole Link Gathering / Run Dynamic Linking pass."""
    run_id: str = field(default_factory=lambda: time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
                        + "-" + uuid.uuid4().hex[:6])
    kind: str = "gather"                # gather / link
    started: float = field(default_factory=time.time)
    finished: Optional[float] = None
    rules: List[RuleResult] = field(default_factory=list)
    # Filled by the main window after the tables are re-enriched:
    # [{"table": ..., "column": ..., "rows": n, "enriched": n,
    #   "sources": {source: n}, "note": ...}]
    enriched_tables: List[Dict] = field(default_factory=list)
    mappings_total: int = 0             # rows in the Mapping table afterwards
    cancelled: bool = False
    # A Run Dynamic Linking that did not gather shows the rules of the Link
    # Gathering its mappings came from: {"run_id", "kind", "started"}.
    rules_from: Optional[Dict] = None

    def add(self, result: RuleResult) -> RuleResult:
        self.rules.append(result)
        return result

    def adopt_rules(self, other: "LinkRun") -> "LinkRun":
        """Take `other`'s rules as this run's own "where the links came from".

        Run Dynamic Linking after a Link Gathering links with the mappings
        that gathering made; built empty, its By source / By category tabs
        said nothing at all.
        """
        self.rules = list(other.rules)
        self.rules_from = {"run_id": other.run_id, "kind": other.kind, "started": other.started}
        return self

    def totals(self) -> Dict[str, int]:
        t = {k: 0 for k in OUTCOMES}
        t.update(rules_ok=0, rules_skipped=0, rules_failed=0, rows_read=0)
        for r in self.rules:
            for k in OUTCOMES:
                t[k] += getattr(r, k)
            t["rows_read"] += r.rows_read
            t["rules_" + {"ok": "ok", "skipped": "skipped"}.get(r.status, "failed")] += 1
        t["new_links"] = t[INSERTED] + t[MERGED]
        t["enriched_rows"] = sum(int(e.get("enriched") or 0) for e in self.enriched_tables)
        return t

    @property
    def duration(self) -> float:
        return (self.finished or time.time()) - self.started

    def to_dict(self) -> Dict:
        return {"run_id": self.run_id, "kind": self.kind, "started": self.started,
                "finished": self.finished, "cancelled": self.cancelled,
                "rules_from": self.rules_from,
                "mappings_total": self.mappings_total, "totals": self.totals(),
                "rules": [r.to_dict() for r in self.rules],
                "enriched_tables": list(self.enriched_tables)}


def log_rule(result: RuleResult) -> None:
    """One line per rule in dynamic_linking.log."""
    where = "%s > %s" % (result.source_db or "-", result.source_table or "-")
    if result.status == "ok":
        logger.info("%s [%s] from %s: %d row(s) read, %d new, %d merged, %d already known, "
                    "%d rejected (%d ms)", result.rule, result.category or result.rule_type, where,
                    result.rows_read, result.inserted, result.merged, result.duplicate,
                    result.rejected, result.duration_ms)
    elif result.status == "skipped":
        logger.info("%s skipped (%s): %s", result.rule, where, result.reason)
    else:
        logger.warning("%s FAILED (%s): %s", result.rule, where, result.reason)


def log_run(run: LinkRun) -> None:
    """The run's summary line, and the enrichment it produced."""
    t = run.totals()
    logger.info("Dynamic Linking %s %s %s: %d rule(s) ok, %d skipped, %d failed; %d new link(s) "
                "(%d new values, %d merged), %d already known, %d rejected; %d mapping(s) in the "
                "database; %.1fs", run.kind, run.run_id, "CANCELLED" if run.cancelled else "finished",
                t["rules_ok"], t["rules_skipped"], t["rules_failed"], t["new_links"], t[INSERTED],
                t[MERGED], t[DUPLICATE], t[REJECTED], run.mappings_total, run.duration)
    if run.rules_from:
        logger.info("  rules counted above are those of %s %s (not run again)",
                    run.rules_from.get("kind"), run.rules_from.get("run_id"))
    for e in run.enriched_tables:
        sources = ", ".join("%s %d" % kv for kv in sorted((e.get("sources") or {}).items(),
                                                           key=lambda kv: -kv[1]))
        logger.info("  enriched %s.%s: %s of %s row(s)%s%s", e.get("table"), e.get("column"),
                    e.get("enriched"), e.get("rows"), (" from " + sources) if sources else "",
                    (" - " + e["note"]) if e.get("note") else "")
