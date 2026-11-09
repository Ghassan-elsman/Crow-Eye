"""Who drove an activity: a person, a person remotely, a program by itself, or
automation (a script or an AI agent) - from input, session and lineage evidence
only, said with its basis (2026-11-03)."""

import json
import re
from datetime import datetime

from uba.engine import who_drove as wd

INTENT = re.compile(r"\b(meant|tried|wanted|in order to|intended|attempted)\b", re.I)
SID = "S-1-5-21-1-2-3-1001"


def _w(app, start, end, kb=0, mouse=0, focus=0, sid=SID, user="analyst"):
    s = datetime.strptime(start, "%Y-%m-%d %H:%M")
    e = datetime.strptime(end, "%Y-%m-%d %H:%M")
    return {"rowid": 1, "start": s, "end": e, "app": app, "app_label": app, "sid": sid,
            "user": user, "focus": focus, "input": kb + mouse, "keyboard": kb, "mouse": mouse}


WINDOWS = wd.InputWindows([
    _w("winword.exe", "2026-06-12 09:00", "2026-06-12 10:00", kb=300, mouse=120, focus=1500),
    _w("onedrive.exe", "2026-06-12 09:00", "2026-06-12 10:00", focus=0),
    _w("chrome.exe", "2026-06-12 14:00", "2026-06-12 15:00", focus=0),
    _w("explorer.exe", "2026-06-12 14:00", "2026-06-12 15:00", focus=0),
])


def _row(rule="file_opened", cls="user", ts="2026-06-12 09:30:00", app="", sid=SID,
         activity=None, **details):
    return {"event_id": "e", "rule_id": rule, "behavior_class": cls, "actor_type": "User",
            "activity": activity or ("program_run" if app else "file_opened"),
            "actor_name": "analyst", "actor_sid": sid, "app_name": app, "ts_start": ts,
            "details_json": json.dumps(details)}


def test_input_in_the_program_is_a_person():
    op, kind, basis = wd.verdict(_row(app="WINWORD"), WINDOWS)
    assert op == "person"
    assert basis == "winword.exe had 300 s of keyboard and 120 s of mouse from analyst between 09:00 and 10:00"


def test_input_elsewhere_at_the_time_is_a_person_with_that_basis():
    op, _k, basis = wd.verdict(_row(app=""), WINDOWS)
    assert op == "person" and basis.startswith("analyst was using the keyboard or mouse (in winword.exe)")


def test_a_program_that_got_no_input_while_the_person_typed_elsewhere():
    op, _k, basis = wd.verdict(_row(app="SecurityHealthSystray"), WINDOWS)
    assert op == "program"
    assert basis == ("securityhealthsystray.exe received no keyboard or mouse input between 09:00 "
                     "and 10:00 (the input went to winword.exe)")


def test_a_file_event_is_not_judged_by_the_file_it_names():
    op, _k, basis = wd.verdict(_row(app="chrome", activity="file_opened"), WINDOWS)
    assert op == "person" and "(in winword.exe)" in basis


def test_a_program_with_no_focus_and_no_input_ran_by_itself():
    op, _k, basis = wd.verdict(_row(app="OneDrive.exe", cls="application"), WINDOWS)
    assert op == "program"
    assert basis == "onedrive.exe ran with no focus and no keyboard or mouse input between 09:00 and 10:00"


def test_no_input_for_the_account_at_all_is_a_program():
    op, _k, basis = wd.verdict(_row(ts="2026-06-12 14:20:00"), WINDOWS)
    assert op == "program"
    assert basis == "no keyboard or mouse input was recorded for analyst between 14:00 and 15:00"


def test_outside_the_input_record_nothing_is_said():
    assert wd.verdict(_row(ts="2026-05-01 09:00:00"), WINDOWS) == ("unknown", "", "")


def test_the_computers_own_activity_is_a_program():
    assert wd.verdict(_row(rule="windows_update", cls="system_app"), WINDOWS)[0] == "program"


def test_started_by_an_ai_agent():
    op, kind, basis = wd.verdict(_row(rule="process_created", cls="application",
                                      process_path="C:\\Windows\\notepad.exe",
                                      parent_process="C:\\Users\\analyst\\.local\\bin\\claude.exe"), WINDOWS)
    # the desktop names it automation; telling an AI agent apart is Sentinel's
    assert (op, kind) == ("automation", "script")
    assert basis == "started by claude.exe (an automation program)"


def test_started_by_a_script_runtime():
    op, kind, basis = wd.verdict(_row(rule="process_created", cls="application",
                                      process_path="C:\\Windows\\notepad.exe",
                                      parent_process="C:\\Python312\\python.exe"), WINDOWS)
    assert (op, kind) == ("automation", "script") and basis == "started by python.exe (a script runtime)"


def test_a_browser_started_for_automation():
    op, kind, basis = wd.verdict(_row(
        rule="process_created", cls="application", process_path="C:\\x\\chrome.exe",
        parent_process="C:\\x\\node.exe",
        command_line='"chrome.exe" --headless --remote-debugging-port=9222'), WINDOWS)
    assert (op, kind) == ("automation", "script")
    assert "--remote-debugging-port" in basis


def test_an_ai_agent_library_on_the_command_line():
    op, kind, _b = wd.verdict(_row(rule="process_created", cls="application",
                                   process_path="C:\\Python312\\python.exe",
                                   parent_process="C:\\Windows\\explorer.exe",
                                   command_line="python -m browser_use run task.json"), WINDOWS)
    assert (op, kind) == ("automation", "script")


def test_started_by_a_remote_control_tool_is_a_remote_person():
    op, _k, basis = wd.verdict(_row(rule="process_created", cls="application",
                                    process_path="C:\\Windows\\cmd.exe",
                                    parent_process="C:\\Program Files\\AnyDesk\\AnyDesk.exe"), WINDOWS)
    assert op == "remote_person" and basis == "started by anydesk.exe (a remote-control program)"


def test_a_service_parent_is_a_program():
    assert wd.verdict(_row(rule="process_created", cls="application",
                           process_path="C:\\x\\update.exe",
                           parent_process="C:\\Windows\\System32\\svchost.exe"), WINDOWS)[0] == "program"


class _Session:
    logon_type = "10"


class _Sessions:
    def session_at(self, ts):
        return _Session()


def test_input_during_a_remote_desktop_sign_in_is_a_remote_person():
    op, _k, basis = wd.verdict(_row(app="WINWORD"), WINDOWS, sessions=_Sessions())
    assert op == "remote_person" and basis.endswith(", during a Remote Desktop sign-in")


def test_an_event_without_an_account_is_judged_by_its_program():
    op, _k, basis = wd.verdict(_row(app="OneDrive.exe", cls="application", sid=""), WINDOWS)
    assert op == "program" and basis.startswith("onedrive.exe ran with no focus")


def test_no_basis_says_intent():
    rows = [_row(app="WINWORD"), _row(app="OneDrive.exe"), _row(ts="2026-06-12 14:20:00"),
            _row(rule="process_created", parent_process="claude.exe")]
    assert not any(INTENT.search(wd.verdict(r, WINDOWS)[2]) for r in rows)


def test_the_engine_writes_the_verdict_on_every_event(artifacts_dir):
    from uba.engine.behavior_engine import BehaviorEngine
    eng = BehaviorEngine(artifacts_dir)
    eng.run(progress_cb=lambda p, l: None)
    ops = {r[0] for r in eng.store.conn.execute("SELECT DISTINCT operator FROM events")}
    assert ops and "" not in ops
    assert "program" in ops


def test_the_four_second_input_record_decodes_the_scripted_test():
    # 2026-11-03, this machine: 30 s typed / 30 s idle x3 from 13:55:55 UTC by
    # SendInput into pythonw.exe; SRUM row timeline_end 437918532,
    # keyboard_input_timeline 548698817534.
    end = wd.slot_end(437918532)
    assert end.strftime("%H:%M:%S") == "13:58:27"
    runs = [(a.strftime("%H:%M:%S"), b.strftime("%H:%M:%S"))
            for a, b in wd.input_runs(548698817534, end)]
    assert runs == [("13:55:47", "13:56:24"), ("13:56:48", "13:57:25"), ("13:57:46", "13:58:22")]


def test_input_near_an_activity_is_named_to_the_second():
    w = _w("winword.exe", "2026-06-12 09:00", "2026-06-12 10:00", kb=30, mouse=8, focus=60)
    w["runs"] = [(datetime(2026, 6, 12, 9, 29, 50), datetime(2026, 6, 12, 9, 30, 10))]
    windows = wd.InputWindows([w])
    op, _k, basis = wd.verdict(_row(app="WINWORD"), windows)
    assert op == "person"
    assert basis.startswith("winword.exe received keyboard or mouse input at 09:30:00")


# ---- foreground vs background (2026-11-03) -------------------------------
# The two rows SRUM wrote for the scripted pythonw.exe run on this machine: a
# foreground record (Flags 0x100, focus 152 s) and a background record.
def _fg_rows():
    end = datetime(2026, 11, 3, 13, 59)
    from datetime import timedelta
    fg = {"rowid": 1, "start": end - timedelta(milliseconds=239999), "end": end, "app": "pythonw.exe",
          "app_label": "pythonw.exe", "sid": SID, "user": "analyst", "focus": 152, "input": 84,
          "keyboard": 84, "mouse": 0, "runs": [], "fg": True,
          "focus_end": wd.slot_end(437918532), "focus_bits": 549755813887,
          "focus_runs": wd.input_runs(549755813887, wd.slot_end(437918532))}
    bg = dict(fg, rowid=2, focus=0, input=0, keyboard=0, fg=False, focus_bits=0, focus_runs=[])
    return wd.InputWindows([fg, bg])


def test_the_window_in_front_at_that_moment_is_foreground():
    state, basis = wd.app_state("pythonw.exe", SID, datetime(2026, 11, 3, 13, 57, 0), _fg_rows())
    assert state == "foreground"
    assert basis == "pythonw.exe was the window in front at 13:57:00 (Windows' 4-second focus record)"


def test_a_moment_the_focus_record_shows_another_window_in_front_is_background():
    # focus in the older slots, not in the newest six (another window in front)
    w = _fg_rows()
    bits = int("1" * 33 + "0" * 6, 2)
    for r in w.rows:
        if r["fg"]:
            r["focus_bits"] = bits
            r["focus_runs"] = wd.input_runs(bits, r["focus_end"])
    state, basis = wd.app_state("pythonw.exe", SID, datetime(2026, 11, 3, 13, 58, 15), w)
    assert state == "background" and "was not the window in front at 13:58:15" in basis


def test_a_program_with_only_a_background_record_ran_in_the_background():
    w = _w("onedrive.exe", "2026-06-12 09:00", "2026-06-12 10:00", focus=0)
    w.update(fg=False, focus_runs=[], focus_end=None, focus_bits=0)
    state, basis = wd.app_state("onedrive.exe", SID, datetime(2026, 6, 12, 9, 30), wd.InputWindows([w]))
    assert state == "background"
    assert basis == "onedrive.exe ran only in the background between 09:00 and 10:00 (never the window in front)"


def test_a_background_program_is_not_called_a_person_whatever_was_typed_elsewhere():
    from uba.engine.event_store import UBAEventStore
    from uba.engine.models import BehaviorEvent
    store = UBAEventStore()
    store.add_events([BehaviorEvent(
        rule_id="program_run", behavior_class="application", activity="program_run",
        ts_start="2026-06-12 09:30:00", ts_end="2026-06-12 09:30:00", actor_type="User",
        actor_name="analyst", actor_basis="", actor_sid=SID, description="OneDrive ran",
        severity="routine", confidence="artifact-only", app_name="OneDrive.exe")])
    word = _w("winword.exe", "2026-06-12 09:00", "2026-06-12 10:00", kb=300, mouse=100, focus=1500)
    word.update(fg=True, focus_runs=[], focus_end=None, focus_bits=0)
    od = _w("onedrive.exe", "2026-06-12 09:00", "2026-06-12 10:00", focus=0)
    od.update(fg=False, focus_runs=[], focus_end=None, focus_bits=0)

    class _Pool:
        pass
    import uba.engine.who_drove as mod
    orig = mod.InputWindows.load
    mod.InputWindows.load = classmethod(lambda cls, pool: wd.InputWindows([word, od]))
    try:
        wd.apply(store, _Pool())
    finally:
        mod.InputWindows.load = orig
    op, state, basis = store.conn.execute(
        "SELECT operator, app_state, operator_basis FROM events").fetchone()
    assert (op, state) == ("program", "background")
    assert basis.startswith("onedrive.exe ran with no focus")



# ---- SRUM filler is never read as input ------------------------------------
def test_srum_filler_is_not_read_as_input():
    assert wd.is_filler(3038287259199220266) and wd.is_filler(707406378)
    assert wd.input_runs(3038287259199220266, wd.slot_end(437918532)) == []
    assert not wd.is_filler(548698817534)


def test_the_desktop_engine_holds_no_agent_signals():
    # keyboard-without-mouse, rhythm and AI-agent naming are Crow-Eye Sentinel's
    assert not hasattr(wd, "software_typing") and not hasattr(wd, "rhythm")
