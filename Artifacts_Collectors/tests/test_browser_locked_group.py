"""Reading a browser database the browser is using (Sentinel 10.13, P1 and P3).

What a careless copy gets wrong:
- the database is taken by a plain copy and its WAL a moment later by the
  raw chain: two moments, read as one;
- a copy taken while the browser writes is read as whole - nothing compares
  two reads;
- a group that changes on every read is parsed anyway;
- a hot journal is read as it lay instead of rolled back on OUR copy;
- on the preserved route the rows record the collector's copy path, so the
  same evidence read live and preserved looks like two different sources.
"""
import os
import shutil
import sqlite3

import pytest

import Artifacts_Collectors.Browser_Claw as bc


def _wal_db(path, rows=3):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT)")
    conn.executemany("INSERT INTO urls (url) VALUES (?)", [("https://example.test/%d" % i,) for i in range(rows)])
    conn.commit()
    return conn          # kept open: the WAL stays beside the database, as in a running browser


@pytest.fixture(autouse=True)
def _reset():
    del bc._UNREAD[:]
    bc._COPY_SOURCE.clear()
    del bc._ORIGINAL_ROOTS[:]
    yield
    del bc._ORIGINAL_ROOTS[:]


def test_a_wal_database_is_one_verified_group(tmp_path):
    src = str(tmp_path / "History")
    keep = _wal_db(src)
    try:
        assert os.path.isfile(src + "-wal")
        dst = bc._copy_sqlite_with_sidecars(src, str(tmp_path))
        assert dst and os.path.isfile(dst + "-wal")
        assert bc._COPY_SOURCE[dst] == (src, "copy:shared_read")
        conn = bc._open_ro(dst)
        assert conn is not None
        assert conn.execute("SELECT count(*) FROM urls").fetchone()[0] == 3
        conn.close()
    finally:
        keep.close()


def test_a_group_that_changes_between_every_read_is_not_parsed(tmp_path, monkeypatch):
    src = str(tmp_path / "Cookies")
    _wal_db(src).close()
    counter = {"n": 0}

    def different(path):
        counter["n"] += 1
        return str(counter["n"])          # every read hashes differently: the browser is writing
    monkeypatch.setattr(bc, "_sha256_file", different)
    monkeypatch.setattr(bc, "_VERIFY_PAUSE_S", 0)
    assert bc._copy_sqlite_with_sidecars(src, str(tmp_path)) is None
    assert bc._UNREAD == [(src, "torn_after_retries", "copy:shared_read")]


def test_a_sidecar_that_refuses_the_plain_copy_moves_the_whole_group(tmp_path, monkeypatch):
    src = str(tmp_path / "Login Data")
    keep = _wal_db(src)
    real_copy2 = shutil.copy2
    locked_rungs = []

    def copy2(a, b, *k, **kw):
        if str(a).endswith("-wal"):
            raise PermissionError(32, "in use")
        return real_copy2(a, b, *k, **kw)

    def locked(a, b):
        locked_rungs.append(os.path.basename(a))
        real_copy2(a, b)
        return True
    monkeypatch.setattr(bc.shutil, "copy2", copy2)
    monkeypatch.setattr(bc, "_copy_locked", locked)
    try:
        dst = bc._copy_sqlite_with_sidecars(src, str(tmp_path))
        assert dst is not None
        assert bc._COPY_SOURCE[dst] == (src, "raw_disk:extents")
        # The database itself went through the same rung as its WAL.
        assert "Login Data" in locked_rungs and "Login Data-wal" in locked_rungs
    finally:
        keep.close()


def test_a_hot_journal_is_rolled_back_on_our_copy(tmp_path):
    # A rollback-journal database copied mid-transaction: the journal holds
    # the page before the change. Opening OUR copy read-write rolls it back.
    src = str(tmp_path / "Web Data")
    conn = sqlite3.connect(src)
    conn.execute("CREATE TABLE autofill (name TEXT)")
    conn.execute("INSERT INTO autofill VALUES ('kept')")
    conn.commit()
    conn.execute("PRAGMA cache_size=1")
    conn.execute("BEGIN")
    conn.execute("INSERT INTO autofill SELECT 'half-written-' || hex(randomblob(400)) FROM "
                 "(WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 400) SELECT x FROM c)")
    try:
        assert os.path.isfile(src + "-journal")
        dst = bc._copy_sqlite_with_sidecars(src, str(tmp_path))
    finally:
        conn.rollback()
        conn.close()
    got = bc._open_ro(dst)
    assert got is not None
    assert [r[0] for r in got.execute("SELECT name FROM autofill")] == ["kept"]
    got.close()


def test_the_preserved_route_reports_live_paths(tmp_path):
    collected = tmp_path / "tables" / "run1" / "Users" / "ann" / "Chrome" / "Default"
    collected.mkdir(parents=True)
    live = r"C:\Users\ann\AppData\Local\Google\Chrome\User Data\Default"
    bc._ORIGINAL_ROOTS.append((os.path.normcase(os.path.abspath(str(collected))), live))
    assert bc._original_path(str(collected / "History")) == live + "\\History"
    assert bc._original_path(str(collected)) == live
    assert bc._original_path(r"C:\elsewhere\History") == r"C:\elsewhere\History"
    ps = bc.ProfileSource(browser="Chrome", vendor="chromium", user_name="ann", sid="S-1-5-21-1",
                          profile="Default", root_dir=str(collected), original_root=live)
    prov = bc._prov_tuple(ps, str(collected / "History"), "now")
    assert prov[3] == "S-1-5-21-1" and prov[5] == live + "\\History"


class _Rows:
    """A writer that keeps what it was handed (browser_metadata only)."""

    def __init__(self):
        self.rows = []

    def add(self, table, cols, rows):
        if table == "browser_metadata":
            self.rows.extend(dict(zip(cols, r)) for r in rows)


def _metadata(ps, tmp_path):
    del bc._ORIGINAL_ROOTS[:]
    bc._ORIGINAL_ROOTS.extend(bc._original_roots(ps))
    try:
        out = _Rows()
        if ps.vendor == "chromium":
            bc._parse_chromium_metadata(ps, out, "now")
        else:
            bc._parse_gecko_metadata(ps, out, "now", str(tmp_path / "extract"))
        return out.rows[0]["source_path"]
    finally:
        del bc._ORIGINAL_ROOTS[:]


def _chromium(tmp_path, base):
    profile = tmp_path / base / "User Data" / "Default"
    profile.mkdir(parents=True)
    (profile.parent / "Local State").write_text('{"os_crypt": {}}', encoding="utf-8")
    return profile


LIVE_PROFILE = r"C:\Users\ann\AppData\Local\Google\Chrome\User Data\Default"
LIVE_STATE = r"C:\Users\ann\AppData\Local\Google\Chrome\User Data\Local State"


def test_p3b_chromium_metadata_names_the_live_local_state(tmp_path):
    copy = _chromium(tmp_path, "collected")
    ps = bc.ProfileSource(browser="Chrome", vendor="chromium", user_name="ann", sid="S-1-5-21-1",
                          profile="Default", root_dir=str(copy),
                          local_state_path=str(copy.parent / "Local State"),
                          original_root=LIVE_PROFILE)
    # Chromium's layout kept: Local State is the live profile's sibling.
    assert _metadata(ps, tmp_path) == LIVE_STATE
    # Named outright, it wins over the layout.
    ps.original_local_state_path = r"D:\elsewhere\Local State"
    assert _metadata(ps, tmp_path) == r"D:\elsewhere\Local State"


def test_p3b_a_copied_local_state_away_from_the_profile_is_not_guessed(tmp_path):
    copy = _chromium(tmp_path, "collected")
    moved = tmp_path / "keys" / "Local State"
    moved.parent.mkdir()
    shutil.copy(str(copy.parent / "Local State"), str(moved))
    ps = bc.ProfileSource(browser="Chrome", vendor="chromium", user_name="ann", sid="S-1-5-21-1",
                          profile="Default", root_dir=str(copy), local_state_path=str(moved),
                          original_root=LIVE_PROFILE)
    assert _metadata(ps, tmp_path) == str(moved)


def test_p3b_gecko_metadata_names_the_live_profile(tmp_path):
    copy = tmp_path / "collected" / "Profiles" / "abc.default"
    copy.mkdir(parents=True)
    live = r"C:\Users\ann\AppData\Roaming\Mozilla\Firefox\Profiles\abc.default"
    ps = bc.ProfileSource(browser="Firefox", vendor="gecko", user_name="ann", sid="S-1-5-21-1",
                          profile="abc.default", root_dir=str(copy), original_root=live)
    assert _metadata(ps, tmp_path) == live


def test_p3b_the_live_route_is_unchanged(tmp_path):
    live = _chromium(tmp_path, "live")
    ps = bc.ProfileSource(browser="Chrome", vendor="chromium", user_name="ann", sid="S-1-5-21-1",
                          profile="Default", root_dir=str(live),
                          local_state_path=str(live.parent / "Local State"))
    assert bc._original_roots(ps) == []
    assert _metadata(ps, tmp_path) == str(live.parent / "Local State")
    gecko = tmp_path / "live" / "Profiles" / "abc.default"
    gecko.mkdir(parents=True)
    ps = bc.ProfileSource(browser="Firefox", vendor="gecko", user_name="ann", sid="S-1-5-21-1",
                          profile="abc.default", root_dir=str(gecko))
    assert _metadata(ps, tmp_path) == str(gecko)
