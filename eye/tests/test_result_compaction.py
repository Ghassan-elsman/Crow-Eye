"""Older tool results go out as digests, stay compacted (cache-stable prefix), and
can be read back in full with recall_result."""

import json
import threading

from eye.services.result_compaction import (
    RESULTS_MARKER, ResultCompactor, digest_message, find_result, result_id)


def _tool_msg(i, rows=50):
    results = [{"tool_name": "query_database", "success": True,
                "parameters": {"database_name": "registry_data.db", "sql_query": "SELECT %d" % i},
                "result": {"success": True, "rows": [{"n": i, "pad": "x" * 200}] * rows, "row_count": rows}}]
    return {"role": "user", "content": "[Tool 1/1: query_database, iteration %d]\n%s%s"
                                       % (i, RESULTS_MARKER, json.dumps(results, separators=(",", ":"))),
            "metadata": {"is_tool_result": True}}


def _history(n):
    h = [{"role": "user", "content": "Which USB devices?"}]
    for i in range(n):
        h += [{"role": "assistant", "content": ""}, _tool_msg(i)]
    return h


def test_nothing_changes_below_the_trigger():
    c = ResultCompactor(trigger_chars=10_000_000)
    h = _history(4)
    assert c.apply(h) == h and c.last_event is None


def test_older_results_become_digests_and_the_newest_stay_whole():
    c = ResultCompactor(trigger_chars=20_000, keep_last=2)
    h = _history(5)
    out = c.apply(h)
    tool_out = [m for m in out if (m.get("metadata") or {}).get("is_tool_result")]
    assert [m["content"].startswith("[Earlier tool results") for m in tool_out] == [True, True, True, False, False]
    assert sum(len(m["content"]) for m in out) < 0.6 * sum(len(m["content"]) for m in h)
    assert c.last_event["messages"] == 3
    assert "SELECT 0" in tool_out[0]["content"] and "50 rows" in tool_out[0]["content"]
    assert h[2]["content"].startswith("[Tool 1/1")            # the stored history is untouched


def test_compaction_is_sticky_so_the_prefix_stays_stable():
    c = ResultCompactor(trigger_chars=35_000, keep_last=2)
    first = c.apply(_history(5))                  # 5 raw results (~52K) -> 3 compacted
    assert c.last_event["messages"] == 3
    second = c.apply(_history(6))                 # 3 raw (~31K): under the trigger, nothing new
    assert c.last_event is None
    assert second[:len(first) - 2] == first[:len(first) - 2]


def test_recall_returns_the_full_result_by_its_digest_id():
    h = _history(3)
    full = json.loads(h[2]["content"].split(RESULTS_MARKER, 1)[1])[0]
    rid = result_id(full)
    assert "[%s]" % rid in digest_message(h[2]["content"])
    assert find_result(h, rid) == full
    assert find_result(h, "rdeadbeef") is None


def test_the_recall_tool_handler():
    from eye.services.context_manager import ContextManager

    class _HM:
        _lock = threading.Lock()
        history = _history(2)

    cm = ContextManager.__new__(ContextManager)
    cm.history_manager = _HM()
    full = json.loads(_HM.history[2]["content"].split(RESULTS_MARKER, 1)[1])[0]
    out = cm._handle_recall_result({"result_id": "[%s]" % result_id(full)})
    assert out["success"] and out["result"] == full
    assert not cm._handle_recall_result({"result_id": "rnope"})["success"]
