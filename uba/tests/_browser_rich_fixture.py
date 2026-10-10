"""Round 11: a browser database shaped to exercise every site-category rule.

Each rule gets the case that must fire next to the case that must NOT, and
secrets are planted in every column the rules are forbidden to read.
"""
import pytest

_B = ("browser TEXT, vendor TEXT, user_name TEXT, sid TEXT, profile TEXT, source_path TEXT, "
      "parsed_at TEXT")
RICH_SID = "S-1-5-21-111-222-333-1001"
RICH_SECRETS = ["PLANTED_DISCORD_TOKEN_mfa.zz9", "PLANTED_VAULT_SEED_abandon",
                "PLANTED_FORM_TEXT_wire_the_money", "planted.cred.user@example.test",
                "PLANTED_AUTOFILL_VALUE", "PLANTED_FORMHISTORY_VALUE"]
DAY = "2026-06-10 "


def _row(**kw):
    base = {"browser": "Chrome", "vendor": "chromium", "user_name": "Alice", "sid": RICH_SID,
            "profile": "Default"}
    base.update(kw)
    return base


def _ff(**kw):
    return _row(browser="Firefox", vendor="gecko", **kw)


SCHEMA = """
    CREATE TABLE browser_history ({b}, url TEXT, title TEXT, visit_count INTEGER,
        typed_count INTEGER, last_visit_time TEXT, visit_time TEXT, transition TEXT,
        from_visit_url TEXT, visit_id TEXT);
    CREATE TABLE browser_gecko_history ({b}, url TEXT, title TEXT, visit_count INTEGER,
        typed INTEGER, last_visit_time TEXT, visit_time TEXT, visit_type INTEGER,
        from_visit_url TEXT);
    CREATE TABLE browser_shortcuts ({b}, text TEXT, fill_into_edit TEXT, url TEXT,
        contents TEXT, description TEXT, last_access_time TEXT, number_of_hits INTEGER);
    CREATE TABLE browser_downloads ({b}, target_path TEXT, source_url TEXT, referrer TEXT,
        tab_url TEXT, received_bytes INTEGER, total_bytes INTEGER, start_time TEXT,
        end_time TEXT, danger_type INTEGER, interrupt_reason TEXT, state INTEGER,
        opened INTEGER, mime_type TEXT, download_id TEXT);
    CREATE TABLE browser_gecko_downloads ({b}, url TEXT, target_path TEXT, start_time TEXT,
        end_time TEXT, state INTEGER);
    CREATE TABLE browser_metadata ({b}, version TEXT, os_crypt_key_b64 TEXT,
        key_scheme TEXT, profile_created TEXT);
    CREATE TABLE browser_files (browser TEXT, vendor TEXT, user_name TEXT, sid TEXT,
        profile TEXT, artifact TEXT, original_path TEXT, extracted_path TEXT, size INTEGER,
        sha1 TEXT, mtime TEXT, parsed_at TEXT);
    CREATE TABLE browser_local_storage ({b}, store_kind TEXT, origin TEXT, key TEXT,
        value TEXT, is_deleted INTEGER, seq INTEGER);
    CREATE TABLE browser_extensions ({b}, extension_id TEXT, name TEXT, version TEXT,
        description TEXT, permissions TEXT, install_time TEXT, from_webstore INTEGER,
        state INTEGER, manifest_path TEXT);
    CREATE TABLE browser_extension_storage ({b}, extension_id TEXT, store_kind TEXT,
        key TEXT, value TEXT, is_deleted INTEGER, seq INTEGER);
    CREATE TABLE browser_sessions ({b}, session_file TEXT, window_index INTEGER,
        tab_index INTEGER, url TEXT, title TEXT, referrer TEXT, form_text TEXT,
        entry_type TEXT);
    CREATE TABLE browser_media_history ({b}, origin TEXT, url TEXT,
        watch_time_seconds REAL, has_audio INTEGER, has_video INTEGER, last_updated TEXT,
        position_seconds REAL);
    CREATE TABLE browser_credentials ({b}, origin_url TEXT, action_url TEXT,
        username_element TEXT, username_value TEXT, password_element TEXT,
        password_encrypted_b64 TEXT, encryption_version TEXT, signon_realm TEXT,
        date_created TEXT, date_last_used TEXT, date_password_modified TEXT,
        times_used INTEGER, blacklisted INTEGER);
    CREATE TABLE browser_autofill ({b}, field_name TEXT, value TEXT, count INTEGER,
        date_created TEXT, date_last_used TEXT);
    CREATE TABLE browser_gecko_formhistory ({b}, field_name TEXT, value TEXT,
        times_used INTEGER, first_used TEXT, last_used TEXT);
""".format(b=_B)

ROWS = {
    "browser_history": [
        _row(url="https://www.google.com/search?q=how+to+wipe+a+disk", visit_time=DAY + "09:00:00", transition="link"),
        _row(url="https://www.bing.com/search?q=tor+browser", visit_time=DAY + "09:01:00", transition="generated"),
        _row(url="https://www.google.com/search?q=reloaded+query", visit_time=DAY + "09:02:00", transition="reload"),
        _row(url="https://mega.nz/folder/abc", visit_time=DAY + "10:00:00", transition="typed"),
        _row(url="https://mega.nz/file/def", visit_time=DAY + "10:05:00", transition="link"),
        _row(url="https://wetransfer.com/embed", visit_time=DAY + "10:06:00", transition="manual_subframe"),
        _row(url="https://pastebin.com/xyz", visit_time=DAY + "11:00:00", transition="link"),
        _row(url="http://exampleonionaddr.onion/", visit_time=DAY + "12:00:00", transition="typed"),
        _row(url="https://www.binance.com/en", visit_time=DAY + "12:30:00", transition="link"),
        _row(url="https://anydesk.com/en/downloads", visit_time=DAY + "13:00:00", transition="typed"),
        _row(url="https://chatgpt.com/c/1", visit_time=DAY + "13:30:00", transition="link"),
        _row(url="https://www.exploit-db.com/exploits/1", visit_time=DAY + "14:00:00", transition="link"),
        _row(url="https://mega.nz/upload", visit_time=DAY + "15:00:00", transition="form_submit"),
        _row(url="https://mega.nz/login", visit_time=DAY + "15:01:00", transition="form_submit"),
        _row(url="https://news.example.test/a", visit_time=DAY + "15:30:00", transition="form_submit"),
    ],
    "browser_gecko_history": [
        _ff(url="https://gofile.io/d/x", visit_time=DAY + "16:00:00", visit_type=2),
        _ff(url="https://ghostbin.com/redirect", visit_time=DAY + "16:01:00", visit_type=5),
    ],
    "browser_shortcuts": [
        _row(text="secret exfil method", url="https://duckduckgo.com/?q=secret+exfil+method",
             last_access_time=DAY + "09:05:00", number_of_hits=1),
    ],
    "browser_downloads": [
        _row(target_path="C:\\Users\\Alice\\Downloads\\payload.exe", source_url="http://203.0.113.5/payload.exe",
             start_time=DAY + "17:00:00", danger_type=0, interrupt_reason="", state=1, opened=1),
        _row(target_path="C:\\Users\\Alice\\Downloads\\archive.zip", source_url="https://mega.nz/file/zzz",
             start_time=DAY + "17:05:00", danger_type=0, interrupt_reason="", state=1, opened=0),
        _row(target_path="C:\\Users\\Alice\\Downloads\\invoice.pdf.exe",
             source_url="https://shop.example.test/invoice.pdf.exe",
             start_time=DAY + "17:10:00", danger_type=0, interrupt_reason="", state=1, opened=0),
        _row(target_path="C:\\Users\\Alice\\Downloads\\setup.msi", source_url="https://vendor.example.test/setup.msi",
             start_time=DAY + "17:15:00", danger_type=0, interrupt_reason="", state=1, opened=1),
        _row(target_path="C:\\Users\\Alice\\Downloads\\out.png", source_url="http://127.0.0.1:7860/file=out.png",
             start_time=DAY + "17:20:00", danger_type=0, interrupt_reason="", state=1, opened=0),
        _row(target_path="C:\\Users\\Alice\\Downloads\\bad.exe", source_url="http://203.0.113.9/bad.exe",
             start_time=DAY + "17:25:00", danger_type=3, interrupt_reason="", state=1, opened=0),
    ],
    "browser_gecko_downloads": [
        _ff(url="http://files.example.org/tool.ps1", target_path="C:\\Users\\Alice\\Downloads\\tool.ps1",
            start_time=DAY + "18:00:00", state=1),
    ],
    "browser_metadata": [
        _row(browser="Discord", vendor="electron"),
        _row(browser="Claude", vendor="electron"),
    ],
    "browser_files": [
        _row(browser="Discord", vendor="electron", artifact="local_storage", original_path="x",
             mtime=DAY + "20:00:00"),
    ],
    "browser_local_storage": [
        _row(browser="Discord", vendor="electron", origin="https://discord.com", key="token",
             value=RICH_SECRETS[0], store_kind="leveldb"),
        _row(origin="chrome-extension://nkbihfbeogaeaoehlefnkodbefgpgknn", key="vault",
             value=RICH_SECRETS[1], store_kind="leveldb"),
    ],
    "browser_extensions": [
        _row(extension_id="nkbihfbeogaeaoehlefnkodbefgpgknn", name="MetaMask", version="11.0",
             permissions='["storage"]', install_time="2026-06-01 08:00:00"),
        _row(extension_id="cccccccccccccccccccccccccccccccc", name="Dark Reader", version="4.9",
             permissions='["storage"]', install_time="2026-06-01 08:05:00"),
    ],
    "browser_extension_storage": [
        _row(extension_id="nkbihfbeogaeaoehlefnkodbefgpgknn", store_kind="local_ext_settings",
             key="data", value=RICH_SECRETS[1]),
    ],
    "browser_sessions": [
        _row(session_file="Session_13435000000000000", window_index=0, tab_index=0,
             url="https://old.example.test/", form_text="", entry_type="navigation"),
        _row(session_file="Session_13435472078321240", window_index=0, tab_index=0,
             url="https://news.example.test/", form_text=RICH_SECRETS[2], entry_type="navigation"),
        _row(session_file="Session_13435472078321240", window_index=0, tab_index=1,
             url="https://news.example.test/start", form_text="", entry_type="navigation"),
        _row(session_file="Session_13435472078321240", window_index=0, tab_index=1,
             url="https://mega.nz/file/live", form_text="", entry_type="navigation"),
        _row(session_file="Tabs_13435472078399999", window_index=0, tab_index=0,
             url="https://closed.example.test/", form_text="", entry_type="navigation"),
    ],
    "browser_media_history": [
        _row(origin="https://www.youtube.com", url="https://www.youtube.com/watch?v=1",
             watch_time_seconds=600, has_audio=1, has_video=1, last_updated=DAY + "21:00:00"),
        _row(origin="https://open.spotify.com", url="https://open.spotify.com/track/1",
             watch_time_seconds=1200, has_audio=1, has_video=0, last_updated=DAY + "21:30:00"),
    ],
    "browser_credentials": [
        _row(origin_url="https://mega.nz/", signon_realm="https://mega.nz/",
             username_value=RICH_SECRETS[3], password_encrypted_b64="Y2lwaGVy",
             date_last_used=DAY + "10:00:00", times_used=2, blacklisted=0),
    ],
    "browser_autofill": [_row(field_name="email", value=RICH_SECRETS[4], count=3)],
    "browser_gecko_formhistory": [_ff(field_name="q", value=RICH_SECRETS[5], times_used=1)],
}


@pytest.fixture
def browser_rich_dir(tmp_path):
    from uba.tests.conftest import _mk
    d = tmp_path / "Target_Artifacts"
    d.mkdir()
    rows = {t: [dict(r) for r in rs] for t, rs in ROWS.items()}
    # _mk takes its column list from each table's first row: give every row
    # of a table the same keys.
    for t, rs in rows.items():
        keys = set()
        for r in rs:
            keys |= set(r)
        for r in rs:
            for k in keys:
                r.setdefault(k, None)
    _mk(str(d / "browser_analysis.db"), SCHEMA, rows)
    return str(d)
