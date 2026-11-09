"""The Activity Story as a day: repeats folded, a summary on top (2026-11-03)."""

import json
import re

from uba.engine import story_digest as sd

INTENT = re.compile(r"\b(meant|tried|wanted|in order to|intended|attempted)\b", re.I)


def _row(eid, rule, ts, who="Alice", cls="user", act=None, sev="routine", desc=None, **details):
    return {"event_id": eid, "rule_id": rule, "activity": act or rule, "behavior_class": cls,
            "ts_start": ts, "ts_end": ts, "actor_name": who, "actor_sid": "S-1-5-21-9-%s" % who,
            "description": desc or "%s %s" % (who, rule), "severity": sev,
            "aggregate_count": 1, "app_name": details.pop("app", ""),
            "details_json": json.dumps(details)}


def test_alike_activity_folds_and_keeps_every_id():
    rows = [_row("e%d" % i, "file_opened", "2026-06-12 09:%02d:00" % (10 + i * 10),
                 folder="C:\\Users\\Alice\\Documents\\Projects") for i in range(4)]
    rows.append(_row("x", "program_run", "2026-06-12 09:15:00", app="Word"))
    out = sd.group_repeats(rows)
    assert [o["kind"] for o in out] == ["group", "event"]
    g = out[0]
    assert g["event_ids"] == ["e0", "e1", "e2", "e3"]
    assert g["text"].startswith("Alice opened 4 files in ")
    assert g["text"].endswith("between 09:10 and 09:40")
    assert not INTENT.search(g["text"])


def test_two_alike_or_a_long_gap_or_another_person_do_not_fold():
    rows = [_row("a", "file_opened", "2026-06-12 09:00:00", folder="C:\\X"),
            _row("b", "file_opened", "2026-06-12 09:05:00", folder="C:\\X"),
            _row("c", "file_opened", "2026-06-12 15:00:00", folder="C:\\X"),
            _row("d", "file_opened", "2026-06-12 15:01:00", folder="C:\\X", who="Bob")]
    assert all(o["kind"] == "event" for o in sd.group_repeats(rows))


def test_a_timeless_row_is_never_folded():
    rows = [_row("t%d" % i, "program_presence", None, app="7z") for i in range(5)]
    assert all(o["kind"] == "event" for o in sd.group_repeats(rows))


def test_the_day_summary_names_signins_firsts_and_the_computer():
    rows = [
        _row("in", "interactive_logon", "2026-06-12 08:02:00", logon_type=2),
        _row("usb", "usb_file_copy", "2026-06-12 11:00:00", sev="notable",
             desc="Alice used the USB drive F: on 2026-06-12: 12 files written to the USB drive F:"),
        _row("out", "logoff", "2026-06-12 17:40:00"),
        _row("upd", "windows_update", "2026-06-12 03:00:00", who="", cls="system_app"),
        _row("svc", "service_state_changed", "2026-06-12 03:10:00", who="", cls="system",
             sev="notable", desc="The service X now starts automatically"),
        _row("other", "file_opened", "2026-06-13 09:00:00"),
    ]
    s = sd.day_summary(rows, "2026-06-12")
    texts = [l["text"] for l in s["lines"]]
    assert texts[0] == "Alice: 3 activities; first signed in at 08:02, last signed out at 17:40"
    assert s["lines"][0]["event_ids"] == ["in", "out"]
    assert "12 files written to the USB drive F:" in texts[1]
    assert "The service X now starts automatically" in texts
    assert texts[-1].startswith("The computer itself recorded 2 activities")
    assert s["counts"] == {"person": 3, "computer": 2, "needs_review": 2}
    assert not any(INTENT.search(t) for t in texts)


def test_alike_items_needing_review_are_one_line():
    rows = [_row("d%d" % i, "defender_exclusion", "2026-06-12 05:10:38", who="", cls="system",
                 sev="suspicious", desc="Defender was set to ignore item %d" % i) for i in range(4)]
    lines = sd.day_summary(rows, "2026-06-12")["lines"]
    assert lines[0]["text"] == "Defender was set to ignore item 0 (and 3 more like it)"
    assert lines[0]["event_ids"] == ["d0", "d1", "d2", "d3"]


def test_a_program_named_as_actor_is_not_a_person():
    rows = [_row("p", "program_run", "2026-06-12 09:00:00", who="TIMEOUT", cls="application")]
    rows[0]["actor_sid"] = ""
    rows[0]["actor_type"] = "Application"
    assert sd.day_summary(rows, "2026-06-12")["people"] == []


def test_remote_desktop_sign_in_is_said():
    rows = [_row("in", "interactive_logon", "2026-06-12 22:15:00", logon_type=10)]
    assert sd.day_summary(rows, "2026-06-12")["lines"][0]["text"].endswith(
        "first signed in at 22:15 (over Remote Desktop)")


def test_a_person_filter_keeps_only_their_rows():
    rows = [_row("a", "file_opened", "2026-06-12 09:00:00"),
            _row("b", "file_opened", "2026-06-12 09:00:00", who="Bob")]
    s = sd.day_summary(rows, "2026-06-12", person="S-1-5-21-9-Bob")
    assert s["people"] == ["Bob"]
