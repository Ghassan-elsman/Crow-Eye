"""
BehaviorEngine — orchestrates a full UBA analysis of one case.

Pipeline: load rules -> build user map + interactive sessions -> run each
extractor (rules sharing an extractor run together, e.g. the five file
rules over one USN pass) -> store BehaviorEvents in the derived in-memory
store -> compute the coverage report.

The engine is GUI-free (usable headless in tests); the bridge runs it in a
QThread and forwards ``progress_cb(percent, phase_label)`` to React.
"""

import logging
import time
from typing import Callable, Optional

from uba.engine.attribution import ActorResolver
from uba.engine.coverage import CoverageAnalyzer
from uba.engine.event_store import UBAEventStore
from uba.engine.extractors import EXTRACTORS
from uba.engine.extractors.context import ExtractorContext
from uba.engine.rule_loader import load_rules
from uba.engine.sessions import SessionBuilder
from uba.utils.db_access import DbPool, data_status

logger = logging.getLogger(__name__)


class BehaviorEngine:
    def __init__(self, artifacts_dir: str, rules_path: Optional[str] = None):
        self.artifacts_dir = artifacts_dir
        self.rules_config = load_rules(rules_path)
        self.db_pool = DbPool(artifacts_dir)
        self.store: Optional[UBAEventStore] = None
        self.coverage_report: Optional[dict] = None
        self.sessions = None
        self.resolver: Optional[ActorResolver] = None
        self.stats = {}

    # ------------------------------------------------------------------ #
    def data_available(self) -> dict:
        return data_status(self.artifacts_dir)

    # ------------------------------------------------------------------ #
    def run(self, progress_cb: Optional[Callable[[int, str], None]] = None
            ) -> UBAEventStore:
        def report(percent, label):
            if progress_cb:
                try:
                    progress_cb(percent, label)
                except Exception:
                    pass

        started = time.time()
        report(2, "Loading user profiles")
        self.resolver = ActorResolver(self.db_pool)

        report(6, "Reconstructing sign-in sessions")
        self.sessions = SessionBuilder(self.db_pool, self.resolver).build()

        report(10, "Checking detection coverage")
        coverage = CoverageAnalyzer(self.db_pool, self.rules_config)
        self.coverage_report = coverage.report()
        status_by_rule = {s["rule_id"]: s["status"]
                          for s in self.coverage_report["rules"]}

        # Group runnable rules by extractor (shared extractors run once).
        by_extractor = {}
        for rule in self.rules_config["rules"]:
            if status_by_rule.get(rule["id"]) == "unavailable":
                continue
            by_extractor.setdefault(rule["extractor"], []).append(rule)

        self.store = UBAEventStore()
        ctx = ExtractorContext(self.db_pool, self.resolver, self.sessions,
                               stats=self.stats)

        total = len(by_extractor) or 1
        done = 0
        for name, rules in by_extractor.items():
            extractor = EXTRACTORS.get(name)
            label = rules[0].get("title", name)
            report(10 + int(85 * done / total), "Analyzing: {}".format(label))
            if extractor is None:
                logger.error("UBA: unknown extractor %r", name)
                done += 1
                continue
            try:
                events = extractor(ctx, rules)
                self._label_session_user(events)
                added = self.store.add_events(events)
                self.stats["events_{}".format(name)] = added
            except Exception as e:
                logger.exception("UBA: extractor %s failed: %s", name, e)
                self.stats["failed_{}".format(name)] = str(e)
                for rule in rules:
                    for entry in self.coverage_report["rules"]:
                        if entry["rule_id"] == rule["id"]:
                            entry["status"] = "unavailable"
                            entry["note"] = ("Analysis failed: {} — see the "
                                             "application log.".format(e))
            done += 1

        self.stats["elapsed_seconds"] = round(time.time() - started, 2)
        total_events = self.store.conn.execute(
            "SELECT COUNT(*) FROM events").fetchone()[0]
        self.stats["total_events"] = total_events
        logger.info("UBA: analysis complete — %d events in %.1fs",
                    total_events, self.stats["elapsed_seconds"])
        report(100, "Analysis complete")
        return self.store

    # ------------------------------------------------------------------ #
    def _label_session_user(self, events):
        """Attach the interactive user logged on at each timed event's time.

        This is a *label* (who was signed in), never attribution — it is kept
        in its own field and is only surfaced as "logged-in user". Events that
        already resolve to a definitive User keep that; we never overwrite the
        forensic actor with the session user."""
        from uba.utils.timeparse import epoch_seconds
        for ev in events:
            if not ev.session_user and ev.ts_start:
                ev.session_user = self.sessions.user_at(epoch_seconds(ev.ts_start))

    def users(self) -> list:
        resolver = self.resolver or ActorResolver(self.db_pool)
        out = []
        for sid, username in resolver.known_users.items():
            entry = {"sid": sid, "username": username, "source": "UserProfiles"}
            if self.store is not None:
                row = self.store.conn.execute(
                    "SELECT COUNT(*), MIN(ts_start), MAX(ts_end) FROM events "
                    "WHERE actor_name = ? AND ts_start IS NOT NULL",
                    (username,)).fetchone()
                entry.update({"event_count": row[0], "first_seen": row[1],
                              "last_seen": row[2]})
            out.append(entry)
        return out

    def apps(self) -> list:
        """Distinct application names seen, with event counts (for the app
        filter). Mirrors users()."""
        if self.store is None:
            return []
        rows = self.store.conn.execute(
            "SELECT app_name, COUNT(*) AS n, SUM(aggregate_count) AS total "
            "FROM events WHERE app_name != '' GROUP BY app_name ORDER BY n DESC")
        return [{"app": r[0], "event_count": r[1], "records": r[2] or 0}
                for r in rows]

    def close(self):
        self.db_pool.close()
