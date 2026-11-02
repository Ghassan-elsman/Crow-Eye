"""
BehaviorEngine — orchestrates a full UBA analysis of one case.

Pipeline: load rules -> build user map + interactive sessions -> run each
extractor (rules sharing an extractor run together, e.g. the five file
rules over one USN pass) -> store BehaviorEvents in the derived in-memory
store -> compute the coverage report.

The analyst's own rules (user_rules.py, uba_user_rules.json) join the
built-in ones: table rules run after every built-in extractor and derived
rules last, over the store (extractors/declarative.py); their events carry
user_rule. Rules turned off in Settings (rule_switches) are not run; coverage
reports them as 'off'. ``run_or_load()`` is what the UBA window and Eye call: it
reuses ``<case>/UBA/uba_events.db`` while that is fresh (persisted_store) and
otherwise runs and stores the result, so the case has one stored answer.

The engine is GUI-free (usable headless in tests); the bridge runs it in a
QThread and forwards ``progress_cb(percent, phase_label)`` to React.
"""

import logging
import os
import time
from typing import Callable, Optional

from uba.engine import persisted_store, rule_switches
from uba.engine import user_rules as user_rules_mod
from uba.engine.attribution import ActorResolver
from uba.engine.coverage import CoverageAnalyzer
from uba.engine.event_store import UBAEventStore
from uba.engine.extractors import EXTRACTORS
from uba.engine.extractors import declarative
from uba.engine.extractors.context import ExtractorContext
from uba.engine.models import ACTOR_USER
from uba.engine.rule_loader import load_rules
from uba.engine.sessions import SessionBuilder
from uba.utils.db_access import DbPool, data_status

logger = logging.getLogger(__name__)


class _StoredSessions:
    """The sign-in sessions of a stored analysis.

    ``to_list()`` answers from what was stored. Anything else a caller asks of
    a SessionIndex (``user_at``, ``context_for``...) rebuilds the real index
    from the evidence on first use - never an empty stand-in answer.
    """

    def __init__(self, stored_list, rebuild):
        self._list = list(stored_list or [])
        self._rebuild = rebuild
        self._real = None

    def to_list(self):
        return [dict(s) for s in self._list]

    def __getattr__(self, name):
        if self._real is None:
            self._real = self._rebuild()
        return getattr(self._real, name)


class BehaviorEngine:
    def __init__(self, artifacts_dir: str, rules_path: Optional[str] = None,
                 disabled_rules=None, store_path: Optional[str] = None,
                 user_rules=None, user_rules_path: Optional[str] = None):
        """``user_rules``: analyst rules to use instead of the global file (a
        list of rule dicts; [] for none); ``user_rules_path``: another file."""
        self.artifacts_dir = artifacts_dir
        builtin = load_rules(rules_path)
        self.builtin_rules_config = builtin
        self.user_rules_path = user_rules_path
        self._fixed_user_rules = user_rules is not None
        if user_rules is None:
            loaded, self.user_rule_problems = user_rules_mod.load_user_rules(
                {r["id"] for r in builtin["rules"]}, path=user_rules_path)
        else:
            from uba.engine.rule_loader import validate_user_rule
            loaded, self.user_rule_problems = [], {}
            builtin_ids = {r["id"] for r in builtin["rules"]}
            for raw in user_rules:
                rule = dict(raw)
                found = validate_user_rule(rule, builtin_ids)
                if found:
                    rule["_problems"] = found
                    self.user_rule_problems[str(rule.get("id"))] = found
                loaded.append(rule)
        # Built-in rules followed by the analyst's (user_rules.merged_rules_config):
        # coverage, the catalog, the switches and the stamp all see both.
        self.rules_config = user_rules_mod.merged_rules_config(builtin, loaded)
        self.user_rules = loaded
        self.user_rules_hash = self.rules_config["user_rules_hash"]
        self.extra_sources = user_rules_mod.extra_sources(user_rules_mod.valid_rules(loaded))
        self.db_pool = DbPool(artifacts_dir)
        self.store: Optional[UBAEventStore] = None
        self.coverage_report: Optional[dict] = None
        self.sessions = None
        self.resolver: Optional[ActorResolver] = None
        self.stats = {}
        # Rules turned off in Settings; None reads the saved setting now.
        self.disabled_rules = frozenset(
            rule_switches.disabled_rule_ids() if disabled_rules is None
            else (str(r) for r in disabled_rules))
        self.store_path = store_path or persisted_store.store_path(artifacts_dir)
        self.stamp: Optional[dict] = None       # what the current store was built from
        self.loaded_from_store = False
        self.built_at_utc: Optional[str] = None
        self.host = ""

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
        self.loaded_from_store = False
        report(2, "Loading user profiles")
        self.resolver = ActorResolver(self.db_pool)
        self.host = self._case_host()

        report(6, "Reconstructing sign-in sessions")
        self.sessions = SessionBuilder(self.db_pool, self.resolver).build()

        report(10, "Checking detection coverage")
        coverage = CoverageAnalyzer(self.db_pool, self.rules_config,
                                    disabled=self.disabled_rules)
        self.coverage_report = coverage.report()
        status_by_rule = {s["rule_id"]: s["status"]
                          for s in self.coverage_report["rules"]}

        # Group runnable rules by extractor (shared extractors run once). A
        # rule turned off in Settings is not handed to its extractor, so an
        # extractor serving several rules still runs for the ones left on.
        by_extractor = {}
        table_rules, derived_rules = [], []
        for rule in self.rules_config["rules"]:
            if status_by_rule.get(rule["id"]) in ("unavailable", "off"):
                continue
            if rule.get("extractor") == user_rules_mod.EXTRACTOR_TABLE:
                table_rules.append(rule)
                continue
            if rule.get("extractor") == user_rules_mod.EXTRACTOR_DERIVED:
                derived_rules.append(rule)
                continue
            by_extractor.setdefault(rule["extractor"], []).append(rule)

        self.store = UBAEventStore()
        ctx = ExtractorContext(self.db_pool, self.resolver, self.sessions,
                               stats=self.stats)

        total = (len(by_extractor) + (1 if table_rules else 0)
                 + (1 if derived_rules else 0)) or 1
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
                # An extractor serving several rules may emit for all of them;
                # one that is off contributes nothing.
                if self.disabled_rules:
                    events = [e for e in events if e.rule_id not in self.disabled_rules]
                self._label_session_user(events)
                self._stamp_person_key(events)
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

        # The analyst's rules: table rules after every built-in extractor,
        # then derived rules over everything found so far (declarative.py).
        if table_rules:
            report(10 + int(85 * done / total), "Analyzing: your rules")
            for rule in table_rules:
                self._run_user_rule(rule, lambda spec: declarative.table_rule_events(ctx, spec))
            done += 1
        if derived_rules:
            report(10 + int(85 * done / total), "Analyzing: your rules built on behaviours")
            for rule in derived_rules:
                self._run_user_rule(rule, lambda spec: declarative.derived_rule_events(
                    self.store, spec))
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

    def _run_user_rule(self, rule, produce):
        """One analyst rule: its events into the store, or - when the case
        cannot run it - its coverage entry set to unavailable with the reason,
        in the log as well. One rule failing never stops the others."""
        spec = rule.get("spec") or {}
        key = "events_user:{}".format(rule["id"])
        try:
            events, info = produce(spec)
            if self.disabled_rules:
                events = [e for e in events if e.rule_id not in self.disabled_rules]
            self._label_session_user(events)
            self._stamp_person_key(events)
            added = self.store.add_events(events)
            self.stats[key] = added
            logger.info("UBA: your rule %s - %d event(s) from %d matching row(s)",
                        rule["id"], added or 0, info.get("matched_rows", 0))
            if info.get("capped"):
                self._set_rule_status(
                    rule["id"], None,
                    "Stopped at {:,} events: the conditions match more than can be read. "
                    "Narrow them, or aggregate per person per day.".format(len(events)))
        except declarative.RuleRefused as e:
            logger.warning("UBA: your rule %s was not run: %s", rule["id"], e)
            self.stats["refused_user:{}".format(rule["id"])] = str(e)
            self._set_rule_status(rule["id"], "unavailable", "Not run - {}".format(e))
        except Exception as e:
            logger.exception("UBA: your rule %s failed: %s", rule["id"], e)
            self.stats["failed_user:{}".format(rule["id"])] = str(e)
            self._set_rule_status(rule["id"], "unavailable",
                                  "Analysis failed: {} — see the application log.".format(e))

    def _set_rule_status(self, rule_id, status, note):
        counts = self.coverage_report.get("counts", {})
        for entry in self.coverage_report["rules"]:
            if entry["rule_id"] != rule_id:
                continue
            if status and status != entry["status"]:
                if entry["status"] in counts:
                    counts[entry["status"]] = max(0, counts[entry["status"]] - 1)
                counts[status] = counts.get(status, 0) + 1
                entry["status"] = status
            entry["note"] = note

    # ------------------------------------------------------------------ #
    def current_stamp(self) -> dict:
        """What a store built now would be built from (persisted_store)."""
        return persisted_store.compute_stamp(
            self.artifacts_dir, self.rules_config, self.disabled_rules,
            user_rules_hash=self.user_rules_hash, extra_sources=self.extra_sources)

    def _live_user_rules(self):
        """(hash, extra sources) of the analyst's rules as saved now."""
        if self._fixed_user_rules:
            return self.user_rules_hash, self.extra_sources
        loaded, _problems = user_rules_mod.load_user_rules(
            {r["id"] for r in self.builtin_rules_config["rules"]}, path=self.user_rules_path)
        return (user_rules_mod.user_rules_hash(loaded),
                user_rules_mod.extra_sources(user_rules_mod.valid_rules(loaded)))

    def run_or_load(self, progress_cb: Optional[Callable[[int, str], None]] = None,
                    force: bool = False) -> UBAEventStore:
        """The case's stored analysis when it is fresh, else a run that is
        then stored. One builder at a time per store file: a second caller
        waits, then finds the first one's result fresh and loads it."""
        def report(percent, label):
            if progress_cb:
                try:
                    progress_cb(percent, label)
                except Exception:
                    pass

        lock = persisted_store.path_lock(self.store_path)
        with lock:
            stamp = self.current_stamp()
            saved = persisted_store.PersistedStore(self.artifacts_dir, self.store_path)
            if not force:
                report(2, "Reading the stored analysis")
                store, meta = saved.load(stamp)
                if store is not None:
                    self._adopt_stored(store, meta, stamp)
                    report(100, "Analysis loaded")
                    return self.store
            self.run(progress_cb=progress_cb)
            self.stamp = stamp
            sessions = self.sessions.to_list() if self.sessions is not None else []
            if saved.save(self.store, stamp,
                          coverage_report=self.coverage_report,
                          stats=self.stats, sessions=sessions, host=self.host,
                          disabled_rules=sorted(self.disabled_rules),
                          artifacts_dir=os.path.abspath(self.artifacts_dir)):
                meta = saved.read_meta() or {}
                self.built_at_utc = meta.get("built_at_utc")
            return self.store

    def is_current(self) -> bool:
        """Whether the store in hand still matches the case and the switches
        as they are now (Eye asks before reusing its cached engine)."""
        if self.store is None or self.stamp is None:
            return False
        live_hash, live_extra = self._live_user_rules()
        live = persisted_store.compute_stamp(
            self.artifacts_dir, self.rules_config, rule_switches.disabled_rule_ids(),
            user_rules_hash=live_hash, extra_sources=live_extra)
        # rules_count follows the rules as loaded at start; a changed set of
        # user rules is caught by its hash.
        live["rules_count"] = self.stamp.get("rules_count")
        return persisted_store.stamp_matches(self.stamp, live)

    def user_rules_changed(self) -> bool:
        """Whether the analyst's rules were saved, edited or deleted since this
        engine loaded them (the window then offers "Re-run analysis")."""
        return self._live_user_rules()[0] != self.user_rules_hash

    def _adopt_stored(self, store, meta, stamp):
        self.store = store
        self.stamp = stamp
        self.loaded_from_store = True
        self.built_at_utc = meta.get("built_at_utc")
        self.coverage_report = meta.get("coverage_report") or {"rules": [], "counts": {}}
        self.stats = dict(meta.get("stats") or {})
        self.stats["loaded_from_store"] = True
        self.host = meta.get("host") or ""
        # Cheap (one UserProfiles read) and needed by users()/sessions_report().
        self.resolver = ActorResolver(self.db_pool)
        self.sessions = _StoredSessions(
            meta.get("sessions"),
            lambda: SessionBuilder(self.db_pool, self.resolver).build())
        logger.info("UBA: reused the stored analysis built %s (%s events) from %s",
                    self.built_at_utc, self.stats.get("total_events"), self.store_path)

    # ------------------------------------------------------------------ #
    def _case_host(self) -> str:
        """The case's computer name: the registry's ComputerName, else the
        name the machine's own System log records most often."""
        conn = self.db_pool.get("registry")
        if conn is not None and self.db_pool.has_column(
                "registry", "ComputerNameInfo", "computer_name"):
            try:
                for (name,) in conn.execute(
                        "SELECT computer_name FROM ComputerNameInfo "
                        "WHERE computer_name IS NOT NULL AND computer_name != ''"):
                    if str(name).strip() and str(name).strip().lower() != "none":
                        return str(name).strip()
            except Exception as e:
                logger.debug("UBA: ComputerNameInfo read failed: %s", e)
        conn = self.db_pool.get("logs")
        if conn is not None and self.db_pool.has_column("logs", "SystemLogs", "ComputerName"):
            try:
                row = conn.execute(
                    "SELECT ComputerName, COUNT(*) AS n FROM SystemLogs "
                    "WHERE ComputerName IS NOT NULL AND ComputerName NOT IN ('', 'N/A') "
                    "GROUP BY ComputerName ORDER BY n DESC LIMIT 1").fetchone()
                if row and row[0]:
                    return str(row[0]).strip()
            except Exception as e:
                logger.debug("UBA: SystemLogs ComputerName read failed: %s", e)
        return ""

    def _stamp_person_key(self, events):
        """Give every event the case's host, and every User event whose actor
        is a profile the SID of that profile.

        Extractors set ``actor_sid`` from the attribution ladder. This fills
        the ones that named a User without one - a profile name read from a
        path, say - through the same rule: the name must match exactly one
        profile (case-insensitive) or the SID stays empty."""
        for ev in events:
            if not ev.host:
                ev.host = self.host
            if ev.actor_type == ACTOR_USER and not ev.actor_sid and ev.actor_name:
                ev.actor_sid = self.resolver.sid_for_account(ev.actor_name)

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
                # By SID, the person key: one person under several names is
                # still one row here.
                row = self.store.conn.execute(
                    "SELECT COUNT(*), MIN(ts_start), MAX(ts_end) FROM events "
                    "WHERE (actor_sid = ? OR (actor_sid = '' AND actor_name = ?)) "
                    "AND ts_start IS NOT NULL",
                    (sid, username)).fetchone()
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
        disabled = self.disabled_rules
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
                "enabled": entry["rule_id"] not in disabled,
                "user_rule": bool(entry.get("user_rule")),
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
