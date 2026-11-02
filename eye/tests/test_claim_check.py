"""Specific values in an answer are checked against what the tools returned."""

from eye.services.claim_check import check_claims, extract_claims, note_for

EVIDENCE = ['{"rows": [{"first_seen": "2026-02-05 17:55:00", '
            '"sid": "S-1-5-21-1837504242-3964489493-3378464631-1001", '
            '"path": "C:\\\\Users\\\\Analyst\\\\edb.chk", "device": "USB\\\\VID_2109&PID_0715"}]}']


def test_values_in_the_evidence_pass_in_any_time_format():
    answer = ("Seen 2026-02-05T17:55:00Z by S-1-5-21-1837504242-3964489493-3378464631-1001, "
              "file C:\\Users\\Analyst\\edb.chk, device VID_2109.")
    r = check_claims(answer, EVIDENCE)
    assert r["checked"] == 4 and r["unsupported"] == []
    assert note_for(r) == ""


def test_an_invented_time_and_device_are_listed():
    answer = "VID_0781 was first connected on 2026-02-03 09:12."
    r = check_claims(answer, EVIDENCE)
    assert {c["value"] for c in r["unsupported"]} == {"VID_0781", "2026-02-03 09:12"}
    note = note_for(r)
    assert "2 of 2" in note and "VID_0781" in note


def test_plain_prose_has_nothing_to_check():
    assert extract_claims("No USB storage device has a recorded connection time.") == []


def test_the_query_processor_appends_the_note():
    import logging
    from eye.services.query_processor import QueryProcessor

    class _HM:
        import threading
        _lock = threading.Lock()
        history = [{"role": "user", "content": "Investigation Tool Results: 2026-02-14 04:10:23",
                    "metadata": {"is_tool_result": True}}]

    class _CM:
        history_manager = _HM()

    qp = QueryProcessor.__new__(QueryProcessor)
    qp.cm = _CM()
    qp.logger = logging.getLogger("t")
    qp._audit_event = lambda *a, **k: None
    out = qp._apply_claim_check("Last event 2026-02-14 04:10; earlier 2026-01-01 10:00.", [])
    assert "2026-01-01 10:00" in out.split("---")[-1]
    assert "2026-02-14 04:10" not in out.split("---")[-1]


def test_an_iso_time_in_the_evidence_matches_a_spaced_time_in_the_answer():
    # The evidence was lowercased before times were normalised, so "T" became "t"
    # and no ISO time in a tool result ever matched (2026-11-02 eval).
    ev = ['{"timestamp": "2026-02-16T02:14:02.625216", "mft": "2026-02-15T06:23:40.225164+00:00"}']
    r = check_claims("Parsed 2026-02-16 02:14:02; MFT change 2026-02-15 06:23 UTC.", ev)
    assert r["unsupported"] == [] and r["shifted"] == []


def test_a_time_zone_shift_the_model_made_is_listed_apart_with_the_shift():
    ev = ['{"TimeCreated": "2026-02-15 07:10:38", "EventID": 4625}']
    r = check_claims("If the labels are UTC+2, the last failure is 2026-02-15 05:10:38 UTC.", ev)
    assert r["unsupported"] == []
    assert [(c["value"], c["shift_hours"]) for c in r["shifted"]] == [("2026-02-15 05:10:38", 2)]
    note = note_for(r)
    assert "`2026-02-15 05:10:38` (-2 h)" in note and "zone" in note


def test_a_shift_needs_the_seconds_to_count():
    ev = ['{"t": "2026-02-15 07:10:38"}']
    r = check_claims("Around 2026-02-15 05:10 it failed.", ev)
    assert [c["value"] for c in r["unsupported"]] == ["2026-02-15 05:10"] and r["shifted"] == []


def test_times_in_next_steps_are_plans_not_findings():
    ev = ['{"t": "2026-02-14 02:10:08"}']
    answer = ("Last shutdown 2026-02-14 02:10:08.\n\n**Next steps:**\n"
              "1. Query Kernel-Power 41 between 2026-02-14 02:00 and 04:30.\n\n"
              "**Limits**\n- Seen once at 2026-01-01 10:00.")
    r = check_claims(answer, ev)
    assert [c["value"] for c in r["unsupported"]] == ["2026-01-01 10:00"]
