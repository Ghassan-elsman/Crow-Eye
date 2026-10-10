"""Round 11 browser rules: curated site categories, searches, downloads, tabs.

Every rule is pinned both ways - the row that must fire next to the row that
must not - because a category rule is only as good as what it leaves out:

* a frame, a redirect or a reload is not a visit (an advert embedding a
  file-sharing widget is not someone going to it);
* a login form on a file-sharing site is not an upload;
* a download from 127.0.0.1 is a local app, not a risky source - on a real
  case it was the only plain-http source there was;
* Chromium's Tabs_ file is the recently-CLOSED list, not open tabs;
* an Electron AI app is not a chat app; an ordinary extension is not a wallet.

And nothing the rules are forbidden to read may reach an event: tokens, vault
contents, typed form text, saved-login usernames, autofill values.
"""
import json

import pytest

from uba.engine.behavior_engine import BehaviorEngine
from uba.tests._browser_rich_fixture import RICH_SECRETS

NEW_RULES = [
    "browser_web_search", "browser_visit_file_sharing", "browser_visit_paste_site",
    "browser_visit_anonymiser", "browser_visit_crypto", "browser_visit_remote_access",
    "browser_visit_ai_chat", "browser_visit_hacking_resource", "browser_upload_inferred",
    "browser_download_executable", "browser_download_risky_source", "browser_download_opened",
    "browser_comm_app_present", "browser_crypto_wallet", "browser_open_tabs_at_exit",
    "browser_media_playback",
]


@pytest.fixture
def events(browser_rich_dir):
    eng = BehaviorEngine(browser_rich_dir)
    eng.run(progress_cb=lambda p, l: None)
    out, cursor = [], None
    while True:
        page = eng.store.query_events({"order": "asc"}, cursor=cursor, page_size=500)
        out += page.get("events") or []
        cursor = page.get("next_cursor")
        if not cursor:
            break
    out += eng.store.query_events({"timeless": 1}, page_size=500).get("events") or []
    for e in out:
        e["details"] = json.loads(e.get("details_json") or "{}") if "details" not in e else e["details"]
    return out


def _of(events, rule):
    return [e for e in events if e["rule_id"] == rule]


def _text(events):
    return " ".join(e["description"] + " " + json.dumps(e.get("details"), default=str)
                    + " " + str(e.get("details_json") or "") for e in events)


def test_sixteen_new_rules_are_loaded_and_active(browser_rich_dir):
    eng = BehaviorEngine(browser_rich_dir)
    eng.run(progress_cb=lambda p, l: None)
    cat = eng.rules_catalog()
    rows = cat["rules"] if isinstance(cat, dict) else cat
    status = {r["rule_id"]: r["status"] for r in rows}
    assert len(eng.rules_config["rules"]) == 81
    assert {r: status.get(r) for r in NEW_RULES if status.get(r) != "active"} == {}


def test_every_new_rule_fires(events):
    assert [r for r in NEW_RULES if not _of(events, r)] == []


def test_searches_are_grouped_and_reloads_ignored(events):
    s = _of(events, "browser_web_search")
    assert len(s) == 1                                   # one user, one browser, one day
    d = s[0]["description"]
    assert '"how to wipe a disk"' in d and '"tor browser"' in d and '"secret exfil method"' in d
    assert "reloaded query" not in d


def test_category_visits_count_only_a_persons_own_navigation(events):
    fs = _of(events, "browser_visit_file_sharing")
    chrome = [e for e in fs if e["app_name"] == "Chrome"]
    assert chrome and "mega.nz" in chrome[0]["description"]
    assert "wetransfer.com" not in _text(fs), "a subframe is not a visit"
    assert any("gofile.io" in e["description"] for e in fs), "Firefox typed visit missed"
    assert "ghostbin.com" not in _text(_of(events, "browser_visit_paste_site")), \
        "a Firefox redirect is not a visit"
    for rule, host in (("browser_visit_paste_site", "pastebin.com"),
                       ("browser_visit_anonymiser", "exampleonionaddr.onion"),
                       ("browser_visit_crypto", "binance.com"),
                       ("browser_visit_remote_access", "anydesk.com"),
                       ("browser_visit_ai_chat", "chatgpt.com"),
                       ("browser_visit_hacking_resource", "exploit-db.com")):
        assert any(host in e["description"] for e in _of(events, rule)), rule


def test_category_severities(events):
    assert {e["severity"] for e in _of(events, "browser_visit_anonymiser")} == {"suspicious"}
    assert {e["severity"] for e in _of(events, "browser_visit_ai_chat")} == {"routine"}
    assert {e["severity"] for e in _of(events, "browser_visit_file_sharing")} == {"notable"}


def test_upload_is_inferred_and_logins_are_not_uploads(events):
    up = _of(events, "browser_upload_inferred")
    assert len(up) == 1 and "mega.nz" in up[0]["description"]
    assert up[0]["confidence"] == "inference"
    assert "does not prove a file was attached" in up[0]["caveat"]
    assert "/login" not in _text(up)
    assert "news.example.test" not in _text(up), "a form on an ordinary site is not an upload"


def test_each_download_produces_exactly_one_primary_event(events):
    primary = ("browser_download", "browser_download_flagged",
               "browser_download_risky_source", "browser_download_executable")
    by_file = {}
    for e in events:
        if e["rule_id"] in primary:
            by_file.setdefault(e["details"].get("file"), []).append(e["rule_id"])
    assert all(len(v) == 1 for v in by_file.values()), by_file
    assert by_file == {
        "bad.exe": ["browser_download_flagged"],          # flagged beats a raw IP
        "payload.exe": ["browser_download_risky_source"],  # raw IP beats executable
        "archive.zip": ["browser_download_risky_source"],  # file-sharing source
        "tool.ps1": ["browser_download_risky_source"],     # Firefox, plain http
        "invoice.pdf.exe": ["browser_download_executable"],
        "setup.msi": ["browser_download_executable"],
        "out.png": ["browser_download"],                   # 127.0.0.1 is not risky
    }


def test_download_severities_and_double_extension(events):
    sev = {e["details"]["file"]: e["severity"] for e in events
           if e["rule_id"] in ("browser_download_risky_source", "browser_download_executable")}
    assert sev["payload.exe"] == "suspicious"       # risky source + executable
    assert sev["tool.ps1"] == "suspicious"          # risky source + script
    assert sev["archive.zip"] == "notable"          # risky source, not executable
    assert sev["invoice.pdf.exe"] == "suspicious"   # double extension
    assert sev["setup.msi"] == "notable"
    dbl = [e for e in events if e["details"].get("file") == "invoice.pdf.exe"][0]
    assert dbl["details"].get("double_extension") is True


def test_opened_is_its_own_event_with_its_caveat(events):
    op = _of(events, "browser_download_opened")
    assert sorted(e["details"]["file"] for e in op) == ["payload.exe", "setup.msi"]
    assert all("not when" in e["caveat"] for e in op)
    assert {e["severity"] for e in op} == {"notable"}   # both are programs/installers


def test_chat_apps_and_wallets(events):
    chat = _of(events, "browser_comm_app_present")
    assert [e["details"]["app"] for e in chat] == ["Discord"]     # not Claude
    assert chat[0]["ts_start"] is None
    w = _of(events, "browser_crypto_wallet")
    assert len(w) == 1 and w[0]["details"]["wallet"] == "MetaMask"
    assert w[0]["details"]["storage_records"] == 2        # counted, never read
    assert "Dark Reader" not in _text(w)


def test_open_tabs_use_only_the_newest_session(events):
    tabs = _of(events, "browser_open_tabs_at_exit")
    assert len(tabs) == 1
    t = tabs[0]
    assert t["details"]["tabs"] == 2                      # tab 1's LAST navigation counts once
    assert "mega.nz" in t["description"] and t["severity"] == "notable"
    text = _text(tabs)
    assert "old.example.test" not in text, "an older session is not the last one"
    assert "closed.example.test" not in text, "Tabs_ is the closed-tabs list"
    assert t["ts_start"] is None


def test_media_playback(events):
    m = _of(events, "browser_media_playback")
    assert len(m) == 1 and m[0]["details"]["watch_seconds"] == 1800
    assert "youtube.com" in m[0]["description"] and "spotify.com" in m[0]["description"]


def test_stored_secrets_reports_categories_not_accounts(events):
    s = _of(events, "browser_stored_secrets")
    assert s and s[0]["details"]["logins_by_category"] == {"file_sharing": 1}
    assert "file-sharing site" in s[0]["description"]


def test_planted_secrets_never_reach_an_event(events):
    text = _text(events)
    leaked = [s for s in RICH_SECRETS if s in text]
    assert not leaked, leaked


def test_site_categories_file_validates_and_catches_mistakes():
    from uba.engine import site_categories as sc
    assert sc.validate(sc.load()) == []
    bad = {"categories": {"a_b": {"domains": ["x.com"]}, "c_d": {"domains": ["x.com", "Y.com"]}},
           "wallet_extensions": {"short": "X"}}
    problems = " | ".join(sc.validate(bad))
    assert "x.com" in problems and "Y.com" in problems and "short" in problems


def test_categorize_edge_cases():
    from uba.engine import site_categories as sc
    assert sc.categorize("https://drive.google.com/x") == "file_sharing"
    assert sc.categorize("https://www.google.com/") is None
    assert sc.categorize("https://contoso.sharepoint.com/") is None
    assert sc.categorize("abc.onion") == "anonymiser" and sc.categorize("onion") is None
    assert sc.categorize("https://huggingface.co/chat/x") == "ai_chat"
    assert sc.categorize("https://huggingface.co/models") is None
    assert sc.search_term("https://www.google.co.uk/search?q=a+b") == ("Google", "a b")
    assert sc.search_term("https://www.google.com/maps?q=x") is None
