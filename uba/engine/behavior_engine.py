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
                logger.info("UBA: %s - %d event(s) from %d rule(s)", name, added or 0, len(rules))
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
        # The rest of the run's statistics (per-extractor counts, failures,
        # skipped rows), which reached the dashboard but never the case log.
        for key in sorted(k for k in self.stats
                          if k not in ("elapsed_seconds", "total_events")
                          and not k.startswith("events_")):
            value = self.stats[key]
            (logger.warning if key.startswith("failed_") else logger.info)(
                "UBA: %s = %s", key, value)
        try:
            states = {}
            for entry in self.coverage_report.get("rules", []):
                states[entry.get("status") or "?"] = states.get(entry.get("status") or "?", 0) + 1
            if states:
                logger.info("UBA: rule coverage - %s",
                            ", ".join("%s %d" % kv for kv in sorted(states.items())))
        except Exception:
            pass
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

    def rules_catalog(self) -> list:
        """Every rule with its coverage status and its event count.

        Counts are deliberately UNFILTERED: they drive the rule picker, and an
        option that disappeared as soon as it was deselected would be unusable.

        A rule that is 'active' and still has a count of 0 is worth seeing — it
        means the data was there and the rule found nothing in it, which is a
        different statement from "no data" and the only place it shows up.
        """
        counts = {}
        if self.store is not None:
            for rule_id, n, recs in self.store.conn.execute(
                    "SELECT rule_id, COUNT(*), SUM(aggregate_count) "
                    "FROM events GROUP BY rule_id"):
                counts[rule_id] = (n, recs or 0)

        severity_of = {r["id"]: r.get("severity", "routine")
                       for r in self.rules_config["rules"]}
        out = []
        for entry in (self.coverage_report or {}).get("rules", []):
            n, recs = counts.get(entry["rule_id"], (0, 0))
            out.append({
                "rule_id": entry["rule_id"],
                "title": entry["title"],
                "activity": entry["activity"],
                "behavior_class": entry["behavior_class"],
                "severity": severity_of.get(entry["rule_id"], "routine"),
                "status": entry["status"],
                "how": entry.get("how", ""),
                "artifacts": entry.get("artifacts", []),
                "note": entry.get("note", ""),
                "event_count": n,
                "records": recs,
            })
        out.sort(key=lambda r: (-r["event_count"], r["title"]))
        return out

    def sessions_report(self) -> dict:
        """Sign-in sessions, the accounts behind them, and machine uptime.

        Everything the Sign-ins view needs in one call. Sessions carry their own
        honesty flags (``end_basis``, ``duration_seconds`` of None when no
        sign-out was recorded) — see uba/engine/sessions.py.
        """
        sessions = self.sessions.to_list() if self.sessions is not None else []
        for session in sessions:
            session["event_count"] = self._events_in_window(
                session["start_ts"], session["end_ts"] or session["context_end_ts"])
            session["failed_before"] = self._failed_logons_before(
                session["username"], session["start_ts"])
        return {
            "sessions": sessions,
            "accounts": self._accounts(),
            "uptime": self._uptime_windows(),
            "auditing": self._auditing_note(),
        }

    # ------------------------------------------------------------------ #
    def _events_in_window(self, start, end) -> int:
        if self.store is None or not start:
            return 0
        if end:
            row = self.store.conn.execute(
                "SELECT COUNT(*) FROM events WHERE ts_start IS NOT NULL "
                "AND ts_start >= ? AND ts_start <= ?", (start, end)).fetchone()
        else:
            row = self.store.conn.execute(
                "SELECT COUNT(*) FROM events WHERE ts_start IS NOT NULL "
                "AND ts_start >= ?", (start,)).fetchone()
        return row[0] if row else 0

    def _failed_logons_before(self, username, start, window_seconds=3600) -> int:
        """Failed sign-ins for this account in the hour before it succeeded."""
        if self.store is None or not username or not start:
            return 0
        from uba.utils.timeparse import epoch_seconds
        start_epoch = epoch_seconds(start)
        if start_epoch is None:
            return 0
        total = 0
        for ts, count in self.store.conn.execute(
                "SELECT ts_start, aggregate_count FROM events "
                "WHERE activity = 'failed_logon' AND actor_name = ? "
                "AND ts_start IS NOT NULL", (username,)):
            epoch = epoch_seconds(ts)
            if epoch is not None and 0 <= start_epoch - epoch <= window_seconds:
                total += count or 1
        return total

    def _accounts(self) -> list:
        """Per-account sign-in history from the SAM/ProfileList UserAccounts table.

        This survives a Security log that has already rolled over, so it is often
        the only record that an account ever signed in at all. apply_identity()
        rewrites SID columns to "SID (MACHINE\\username)", so never match on a
        bare SID here — the values are read, not joined on.
        """
        if not self.db_pool.has_table("registry", "UserAccounts"):
            return []
        wanted = ["user_sid", "username", "account_type", "account_enabled",
                  "last_logon", "login_count", "bad_password_count",
                  "last_incorrect_password", "password_last_set", "source"]
        columns = [c for c in wanted
                   if self.db_pool.has_column("registry", "UserAccounts", c)]
        if "username" not in columns:
            return []
        conn = self.db_pool.get("registry")
        try:
            rows = conn.execute("SELECT {} FROM UserAccounts".format(
                ",".join('"{}"'.format(c) for c in columns))).fetchall()
        except Exception as e:
            logger.warning("UBA: UserAccounts read failed: %s", e)
            return []
        known = set((self.resolver.known_users if self.resolver else {}).values())
        out = []
        for row in rows:
            entry = {c: row[i] for i, c in enumerate(columns)}
            entry["has_profile"] = entry.get("username") in known
            out.append(entry)
        out.sort(key=lambda a: (a.get("last_logon") or "", a.get("username") or ""),
                 reverse=True)
        return out

    def _uptime_windows(self) -> list:
        """Pair machine start events with the next stop to give uptime spans.

        An unmatched start is reported with end=None rather than being closed at
        a guess — the same rule the sessions follow.
        """
        if self.store is None:
            return []
        rows = self.store.conn.execute(
            "SELECT ts_start, details_json FROM events "
            "WHERE activity = 'boot_shutdown' AND ts_start IS NOT NULL "
            "ORDER BY ts_start").fetchall()
        import json as _json
        windows, open_start = [], None
        for ts, details_json in rows:
            try:
                transition = (_json.loads(details_json or "{}")
                              .get("transition", "stop"))
            except ValueError:
                transition = "stop"
            if transition == "start":
                if open_start is not None:
                    windows.append({"start_ts": open_start, "end_ts": None})
                open_start = ts
            elif open_start is not None:
                windows.append({"start_ts": open_start, "end_ts": ts})
                open_start = None
        if open_start is not None:
            windows.append({"start_ts": open_start, "end_ts": None})
        return windows

    def _auditing_note(self) -> dict:
        """Whether logon/logoff auditing was configured on this machine.

        A thin session list must be readable as "auditing was off", not as
        "nobody signed in".
        """
        note = {"audit_policy_available": False, "entries": []}
        if not self.db_pool.has_table("registry", "audit_policy"):
            return note
        conn = self.db_pool.get("registry")
        try:
            rows = conn.execute(
                "SELECT name, decoded FROM audit_policy "
                "WHERE name LIKE '%ogon%' OR name LIKE '%ogoff%' "
                "OR name LIKE '%ccount%'").fetchall()
        except Exception as e:
            logger.debug("UBA: audit_policy read failed: %s", e)
            return note
        note["audit_policy_available"] = True
        note["entries"] = [{"name": r[0], "decoded": r[1]} for r in rows]
        return note

    def close(self):
        self.db_pool.close()
