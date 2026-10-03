"""Browser-database rules.

Until now UBA's only browser rule read **typed URLs out of the registry** and
said so in a degrade note. These read `browser_analysis.db` itself.

Three of the four rule families were designed against the schema and then
rebuilt against a real case, because the schema and the data disagreed:

* `from_webstore = 0` does **not** mean sideloaded - 34 of 39 extensions in a
  real three-browser case have it, because Edge and Brave extensions are not
  from the *Chrome* web store. The trigger is the permission set.
* `browser.clear_data.*` is the **state of the clear-data dialog**, not a
  record that anything was cleared, and `last_clear_browsing_data_time` does
  not exist. A clearance can only be inferred.
* `browser_search_engines` is inert (no `is_default`, no `date_created`, no
  `usage_count`), so no default-search rule is written at all.

The fixture exists partly because of the third fact about real data: the case
these were built against contained no history gap with corroborating activity,
so the gap rule correctly produced nothing - and a rule that has never been
seen to fire is not a rule anyone should trust.
"""
import json

import pytest

from uba.engine.behavior_engine import BehaviorEngine

BROWSER_RULES = [
    "browser_web_history", "browser_download", "browser_download_flagged",
    "browser_abnormal_exit", "browser_save_location", "browser_account_sync",
    "browser_risky_extension", "browser_stored_secrets", "browser_history_gap",
]

# Values planted in the fixture that must never reach a description or details.
PLANTED_SECRETS = [
    "alice.secret@example.test",                      # account e-mail + username
    "dGhpcy1pcy1jaXBoZXJ0ZXh0LW5vdC1hLXBhc3N3b3Jk",   # password ciphertext
    "Y2lwaGVydGV4dC1jYXJkLW51bWJlcg==",               # card ciphertext
    "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=",           # cookie ciphertext
    "A SECRET NAME",                                  # name on card
    "4242",                                           # card last four
]


def _events(eng, rule_id=None):
    out, cursor = [], None
    while True:
        page = eng.store.query_events({"order": "asc"}, cursor=cursor, page_size=500)
        rows = page.get("events") or []
        if not rows:
            break
        out += rows
        cursor = page.get("next_cursor")
        if not cursor:
            break
    out += (eng.store.query_events({"timeless": 1}, page_size=500).get("events") or [])
    if rule_id:
        return [e for e in out if e.get("rule_id") == rule_id]
    return [e for e in out if str(e.get("rule_id", "")).startswith("browser_")]


def test_no_browser_rule_is_unavailable(artifacts_dir):
    """The silent trap: a rule whose logical DB is not in DB_CANDIDATES is
    marked `unavailable` and its extractor is NEVER CALLED - a green run with
    no events and no error anywhere."""
    eng = BehaviorEngine(artifacts_dir)
    eng.run(progress_cb=lambda p, l: None)
    cat = eng.rules_catalog()
    rows = cat["rules"] if isinstance(cat, dict) else cat
    status = {r["rule_id"]: r["status"] for r in rows}
    missing = [r for r in BROWSER_RULES if r not in status]
    assert not missing, "rules never reached the catalog: %s" % missing
    dead = {r: status[r] for r in BROWSER_RULES if status[r] == "unavailable"}
    assert not dead, ("these can never fire - browser_analysis.db is not "
                      "reachable from DbPool: %s" % dead)


def test_the_browser_database_is_registered(artifacts_dir):
    """`DB_CANDIDATES` and `KEY_TABLES` both matter: the first makes the rules
    runnable, the second makes the case count as having parsed data."""
    from uba.utils.db_access import DB_CANDIDATES, KEY_TABLES, data_status
    assert "browser" in DB_CANDIDATES
    assert "browser" in KEY_TABLES
    status = data_status(artifacts_dir)
    assert status["databases"]["browser"]["present"]
    assert status["databases"]["browser"]["total_rows"] > 0, \
        "browser rows do not count towards parsed_data_available"


def test_history_is_grouped_not_one_event_per_visit(artifacts_dir):
    """13,730 visits in a real case. One event each would bury every other
    behaviour on the timeline."""
    eng = BehaviorEngine(artifacts_dir)
    eng.run(progress_cb=lambda p, l: None)
    events = _events(eng, "browser_web_history")
    assert events, "no browsing events"
    # Three visits across two days -> two events, not three.
    assert len(events) == 2, [e["description"] for e in events]
    assert sum(e["aggregate_count"] for e in events) == 3


def test_history_is_attributed_from_the_row_sid(artifacts_dir):
    """Stronger than the registry rule it replaces, which could only say
    "a user of this profile" because a user hive names nobody."""
    eng = BehaviorEngine(artifacts_dir)
    eng.run(progress_cb=lambda p, l: None)
    events = _events(eng, "browser_web_history")
    assert events
    # The NAME alone proves nothing: the account-name fallback yields "Alice"
    # too. `actor_basis` records which rung of the attribution ladder answered,
    # and from_sid() is the only one that cites the SID.
    bases = [e.get("actor_basis") or "" for e in events]
    assert all("S-1-5-21-111-222-333-1001" in b for b in bases), \
        "attribution did not come from the row's own SID: %s" % bases
    assert any("Alice" in (e.get("actor_name") or "") for e in events)


def test_a_flagged_download_is_separated_from_an_ordinary_one(artifacts_dir):
    eng = BehaviorEngine(artifacts_dir)
    eng.run(progress_cb=lambda p, l: None)
    plain = _events(eng, "browser_download")
    flagged = _events(eng, "browser_download_flagged")
    assert len(plain) == 1, [e["description"] for e in plain]
    assert len(flagged) == 1, [e["description"] for e in flagged]
    assert flagged[0]["severity"] == "notable"
    assert "tool.exe" in flagged[0]["description"]


def test_an_extension_is_flagged_for_permissions_not_for_its_store(artifacts_dir):
    """The fixture holds two extensions, both `from_webstore = 0`. Only the one
    with far-reaching permissions may be flagged - otherwise the rule marks
    nearly every extension on a machine that runs Edge or Brave."""
    eng = BehaviorEngine(artifacts_dir)
    eng.run(progress_cb=lambda p, l: None)
    events = _events(eng, "browser_risky_extension")
    assert len(events) == 1, [e["description"] for e in events]
    assert "Wide Reach" in events[0]["description"]
    assert "Harmless" not in json.dumps(events)


def test_the_history_gap_fires_only_when_contradicted(artifacts_dir):
    """A gap on its own is not a finding; a gap while other browser state was
    still being written is. The fixture plants a cookie inside the silence."""
    eng = BehaviorEngine(artifacts_dir)
    eng.run(progress_cb=lambda p, l: None)
    events = _events(eng, "browser_history_gap")
    assert len(events) == 1, [e["description"] for e in events]
    e = events[0]
    assert e["confidence"] == "inference", \
        "a clearance cannot be observed, only inferred - say so"
    assert e["caveat"], "an inference with no caveat overclaims"


def test_the_clear_data_dialog_is_context_not_a_claim(artifacts_dir):
    """`browser.clear_data.browsing_history = True` says a checkbox is ticked.
    It must never be reported as evidence that history was cleared."""
    eng = BehaviorEngine(artifacts_dir)
    eng.run(progress_cb=lambda p, l: None)
    events = _events(eng)
    for e in events:
        text = (e.get("description") or "").lower()
        assert "cleared" not in text or e.get("confidence") == "inference", \
            "claimed a clearance outside an inference: %s" % e["description"]


def test_no_planted_secret_reaches_an_event(artifacts_dir):
    """Credentials, card data and account identity live in these databases.
    A rule reports that they exist and how they were used - never the value.
    Both `description` and `details` travel to the React card and into reports.
    """
    eng = BehaviorEngine(artifacts_dir)
    eng.run(progress_cb=lambda p, l: None)
    blob = json.dumps(_events(eng))
    leaked = [s for s in PLANTED_SECRETS if s in blob]
    assert not leaked, "secret or identity values reached the events: %s" % [
        s[:12] + "..." for s in leaked]
    assert "@" not in " ".join(e.get("description") or "" for e in _events(eng)), \
        "an e-mail-shaped value reached a description"


def test_stored_secrets_are_reported_as_counts(artifacts_dir):
    eng = BehaviorEngine(artifacts_dir)
    eng.run(progress_cb=lambda p, l: None)
    events = _events(eng, "browser_stored_secrets")
    assert len(events) == 1
    details = events[0]["details"]
    assert details["logins"] == 1 and details["logins_used"] == 1
    assert details["payment_instruments"] == 1


def test_the_registry_stub_says_it_is_superseded(artifacts_dir):
    """Two rules both claiming "visited a website" would be confusing; the
    registry one now says where the full history lives."""
    from uba.engine.rule_loader import load_rules
    rules = {r["id"]: r for r in load_rules()["rules"]}
    assert "browser_web_history" in rules
    stub = rules["web_browsing"]
    assert "browser_web_history" in (stub.get("degrade_note") or ""), \
        "the registry stub does not point at the real history rule"
