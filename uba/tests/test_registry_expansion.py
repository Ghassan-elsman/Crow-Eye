r"""The rules added for the artifacts the registry parsers already collected.

Thirteen tables held rows in a real case while the timeline showed nothing from
them - scheduled tasks (286 registrations), Defender exclusions, the per-user
device and document MRUs - and three of them were still listed in
`requires_collection` as things Crow-Eye had no parser for.

Every test here asserts an event was produced AND what it says. A test that
queries for events and finds none passes exactly as green as one that finds the
right ones, so each rule's fixture row exists to make the assertion real.

The negative cases matter as much: three of these rules would over-report
badly without a filter, and each of those filters is pinned by a row in the
fixture that must NOT produce an event.
"""
from uba.engine.behavior_engine import BehaviorEngine


def run(artifacts_dir):
    eng = BehaviorEngine(artifacts_dir)
    eng.run()
    return eng


def all_events(eng):
    timed = eng.store.query_events(page_size=5000)["events"]
    timeless = eng.store.query_events(filters={"timeless": True},
                                      page_size=5000)["events"]
    return timed + timeless


def by_rule(eng, rule_id):
    return [e for e in all_events(eng) if e.get("rule_id") == rule_id]


def text_of(events):
    return " || ".join(e.get("description") or "" for e in events)


# --- the rule that was wrong ---------------------------------------------- #

def test_disabled_autostart_is_not_reported_as_live_persistence(artifacts_dir):
    """Explorer switched it off; it does not run.

    This used to read "is set to run automatically at startup" and, because the
    command sits in AppData, was escalated to suspicious.
    """
    events = by_rule(run(artifacts_dir), "autostart_persistence")
    dormant = [e for e in events if "Dormant" in (e.get("description") or "")]
    assert len(dormant) == 1, text_of(events)
    said = dormant[0]["description"]
    assert "switched OFF" in said and "does not run" in said, said
    assert "2026-02-14 02:11:00" in said, said
    assert dormant[0]["severity"] != "suspicious", (
        "a program Windows will not launch is not live persistence")


def test_enabled_autostart_in_a_user_writable_path_is_still_escalated(artifacts_dir):
    """The fix must not blunt the real signal."""
    events = by_rule(run(artifacts_dir), "autostart_persistence")
    sketchy = [e for e in events if "Sketchy" in (e.get("description") or "")]
    assert len(sketchy) == 1
    assert sketchy[0]["severity"] == "suspicious", sketchy[0]


# --- scheduled tasks ------------------------------------------------------- #

def test_scheduled_task_registration_and_run_are_separate_events(artifacts_dir):
    eng = run(artifacts_dir)
    reg = by_rule(eng, "scheduled_task_registered")
    ran = by_rule(eng, "scheduled_task_run")
    assert len(reg) == 1, text_of(reg)
    assert len(ran) == 1, text_of(ran)
    assert reg[0]["ts_start"].startswith("2026-06-01")
    assert ran[0]["ts_start"].startswith("2026-06-02")
    assert "Updater" in reg[0]["description"]


def test_task_command_is_expanded_from_the_evidence_not_this_machine(artifacts_dir):
    r"""The fixture's windir is D:\Windows, which no test machine has.

    Expanding from os.environ would silently produce C:\Windows and look
    perfectly correct - on an image, that is somebody else's computer.
    """
    reg = by_rule(run(artifacts_dir), "scheduled_task_registered")
    said = reg[0]["description"]
    assert "D:\\Windows\\system32\\demo.exe" in said, said
    assert "%windir%" not in said, said


# --- bounded times --------------------------------------------------------- #

def test_a_key_write_time_is_stated_as_an_upper_bound(artifacts_dir):
    """`key upper bound` is the key's time, not the value's."""
    events = by_rule(run(artifacts_dir), "defender_exclusion")
    assert len(events) == 1, text_of(events)
    said = events[0]["description"]
    assert "at or before 2026-06-03 10:00:00" in said, said
    assert "upper bound" in (events[0].get("caveat") or "")


def test_an_exact_transaction_log_time_carries_no_hedge(artifacts_dir):
    """`value (txn log)` IS the moment that value changed."""
    events = by_rule(run(artifacts_dir), "security_posture_changed")
    assert len(events) == 1, text_of(events)
    said = events[0]["description"]
    assert "at 2026-06-04 11:00:00" in said, said
    assert "at or before" not in said, said
    assert not (events[0].get("caveat") or "")


# --- the three filters that stop over-reporting ---------------------------- #

def test_only_userchoice_counts_as_a_file_association(artifacts_dir):
    """OpenWithList is the "Open with" menu, not the handler in force.

    On the reference system 408 file_exts rows reduce to 181 UserChoice ones;
    counting both would more than double the reported associations.
    """
    events = by_rule(run(artifacts_dir), "file_association_choice")
    assert len(events) == 1, text_of(events)
    assert "Notepad.exe" in events[0]["description"]
    assert "wordpad" not in text_of(events).lower()


def test_threading_model_is_not_reported_as_a_loaded_library(artifacts_dir):
    """The same CLSID key stores ThreadingModel=Apartment, which is not a path."""
    events = by_rule(run(artifacts_dir), "com_inprocserver")
    assert len(events) == 1, text_of(events)
    assert "ext.dll" in events[0]["description"]
    assert "Apartment" not in text_of(events)


def test_a_default_security_setting_produces_no_event(artifacts_dir):
    """Only settings assessed as changed. A machine at its defaults is quiet."""
    events = by_rule(run(artifacts_dir), "security_posture_changed")
    assert len(events) == 1, text_of(events)
    assert "EnableLUA" in events[0]["description"]
    assert "SaveZoneInformation" not in text_of(events)


def test_a_per_user_com_registration_is_not_called_suspicious(artifacts_dir):
    """Every per-user COM object lives under AppData.

    Escalating on that alone flagged a WPS Office shell extension and the
    Python launcher on the reference system - two false positives out of two
    rows. The location is reported as a fact instead.
    """
    events = by_rule(run(artifacts_dir), "com_inprocserver")
    assert events[0]["severity"] != "suspicious", events[0]
    assert "per-user" in events[0]["description"]


# --- the remaining new rules all fire ------------------------------------- #

def test_every_new_rule_produces_its_event(artifacts_dir):
    """One assertion per rule, so a silently-dead extractor cannot hide.

    Named individually rather than looped, because the failure message has to
    say WHICH rule went quiet.
    """
    eng = run(artifacts_dir)
    expected = {
        "scheduled_task_registered": "Updater",
        "scheduled_task_run": "Updater",
        "defender_exclusion": "imager",
        "security_posture_changed": "EnableLUA",
        "file_association_choice": ".txt",
        "com_inprocserver": "ext.dll",
        "feature_usage": "notepad.exe",
        "compat_assistant_execution": "legacy.exe",
        "file_dialog_history": "notes.txt",
        "connected_device": "Headset",
        "mounted_volume": "E",
        "office_document": "report.docx",
        "taskbar_pinned": "Brave.lnk",
    }
    silent, wrong = [], []
    for rule_id, needle in sorted(expected.items()):
        events = by_rule(eng, rule_id)
        if not events:
            silent.append(rule_id)
        elif needle not in text_of(events):
            wrong.append("%s: %r not in %r" % (rule_id, needle,
                                               text_of(events)[:120]))
    assert not silent, "produced no events: %s" % silent
    assert not wrong, "\n  ".join(wrong)


def test_the_mru_time_carries_its_own_caveat(artifacts_dir):
    """An MRU list has no per-entry time; the key's time dates the newest."""
    events = by_rule(run(artifacts_dir), "file_dialog_history")
    assert len(events) == 1
    assert "no time per entry" in (events[0].get("caveat") or "")


def test_taskbar_text_does_not_repeat_the_word_pinned(artifacts_dir):
    """The decoded value already reads "N pinned: ...".

    Prefixing "pinned with" produced "was pinned with: 2 pinned: ...".
    """
    events = by_rule(run(artifacts_dir), "taskbar_pinned")
    assert len(events) == 1
    assert "pinned with" not in events[0]["description"]
