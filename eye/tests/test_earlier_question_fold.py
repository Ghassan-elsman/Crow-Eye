"""Earlier questions go to the model folded; tool results with evidence anchors stay readable.

2026-11-03 cost review: on one conversation the cost per question grew from $0.18 to
about $2 by question 12, because every earlier question went out whole (tool results,
step messages, the ~45K-character synthesis prompt). And HistoryManager appends
`<evidence anchor=...>` lines after a tool result's JSON, which json.loads rejected:
nearly every result compacted to "(unparsed)" with no id, and recall_result found nothing.
"""
import json

from eye.services.result_compaction import (
    FOLD_HEAD, RESULTS_MARKER, digest_message, find_result, fold_earlier_questions,
    is_question, parse_results, result_id)


def _tool_msg(i, anchors=True):
    results = [{"tool_name": "query_database", "success": True,
                "parameters": {"database_name": "registry_data.db", "sql_query": "SELECT %d" % i},
                "result": {"success": True, "rows": [{"n": i, "path": "C:\\Users\\a\\f%d.txt" % i}] * 30,
                           "row_count": 30}}]
    content = "[Tool 1/1: query_database, iteration %d]\n%s%s" % (
        i, RESULTS_MARKER, json.dumps(results, separators=(",", ":")))
    if anchors:   # what HistoryManager.add_message appends to a flagged message
        content += '\n\n<evidence anchor="file_path">C:\\Users\\a\\f%d.txt</evidence>' % i
    return {"role": "user", "content": content,
            "metadata": {"is_tool_result": True, "preserve_evidence": True}}


def _question(n, q):
    return [
        {"role": "user", "content": q, "metadata": {"question_start": True}},
        {"role": "user", "content": "Step 1: look", "metadata": {"internal": True}},
        {"role": "assistant", "content": "Querying."},
        _tool_msg(n * 10),
        {"role": "assistant", "content": ""},
        _tool_msg(n * 10 + 1),
        {"role": "user", "content": "[Write-up step]", "metadata": {"internal": True, "synthesis_marker": True}},
        {"role": "assistant", "content": "Answer %d" % n},
    ]


def test_results_with_trailing_evidence_anchors_parse_and_are_recalled():
    m = _tool_msg(7)
    results = parse_results(m["content"])
    assert results and results[0]["parameters"]["sql_query"] == "SELECT 7"
    rid = result_id(results[0])
    assert "(unparsed)" not in digest_message(m["content"])
    assert "[%s]" % rid in digest_message(m["content"])
    assert find_result([m], rid) == results[0]


def test_one_question_is_not_folded():
    h = _question(1, "Which USB devices?")
    assert fold_earlier_questions(h) == h


def test_earlier_questions_go_out_as_question_digest_answer():
    h = _question(1, "Which USB devices?") + _question(2, "And the last shutdown?")
    out = fold_earlier_questions(h)
    first = out[:3]
    assert first[0]["content"] == "Which USB devices?"
    assert first[1]["content"].startswith(FOLD_HEAD)
    for i in (10, 11):    # both tool results of question 1 are in the digest, with their ids
        rid = result_id(parse_results(_tool_msg(i)["content"])[0])
        assert "[%s]" % rid in first[1]["content"]
    assert first[2]["content"] == "Answer 1"
    assert out[3:] == _question(2, "And the last shutdown?")       # the current question is whole
    assert sum(len(m["content"]) for m in out[:3]) < 0.5 * sum(len(m["content"]) for m in h[:8])
    assert len(h) == 16                                              # the stored history is untouched


def test_the_fold_is_stable_across_calls():
    h = _question(1, "Q1") + _question(2, "Q2")
    a = fold_earlier_questions(h)
    b = fold_earlier_questions(h + [_tool_msg(99)])
    assert b[:len(a)] == a


def test_older_histories_without_the_marker_still_fold():
    h = _question(1, "Q1") + _question(2, "Q2")
    for m in h:
        (m.get("metadata") or {}).pop("question_start", None)
    assert is_question(h[0]) and not is_question(h[3]) and not is_question(h[1])
    assert len(fold_earlier_questions(h)) == 3 + 8


def test_pinned_and_summary_messages_of_an_earlier_question_are_kept():
    h = _question(1, "Q1")
    h.insert(3, {"role": "assistant", "content": "Key fact", "metadata": {"pinned": True}})
    h.insert(4, {"role": "system", "content": "[Summary of earlier conversation]"})
    out = fold_earlier_questions(h + _question(2, "Q2"))
    assert "Key fact" in [m["content"] for m in out[:5]]
    assert "[Summary of earlier conversation]" in [m["content"] for m in out[:5]]


def test_reasoning_config_knobs_are_read():
    from eye.services.context_manager import ContextManager
    d = ContextManager.DEFAULT_REASONING_CONFIG
    assert d["fold_earlier_questions"] is True
    assert d["compact_tool_results_over_chars"] == 120000 and d["compact_keep_last"] == 2
    from config import eye_ai_settings as s
    for k in ("fold_earlier_questions", "compact_tool_results_over_chars", "compact_keep_last"):
        assert k in s.DEFAULTS


def test_the_synthesis_prompt_is_not_stored_whole():
    import os
    src = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "services", "query_processor.py"),
               encoding="utf-8").read()
    assert 'add_message("user", synthesis_prompt' not in src
    assert '"synthesis_marker": True' in src
