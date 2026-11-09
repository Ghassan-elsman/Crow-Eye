"""What the Eye window reads after every answer stays the size of an answer.

After each answer the chat asked for the context stats, which read the whole
truncation audit log to fill two fields that live in memory, and for the
whole conversation history (every message with its transcript) only to line
up the ids of the newest messages. Both ran on Crow-Eye's GUI thread and
grew with the conversation.
"""
import json
import tempfile
from unittest import mock

from eye.services.truncation_auditor import TruncationAuditor


def test_the_custody_status_reads_no_log():
    auditor = TruncationAuditor(tempfile.mkdtemp())
    with open(auditor.log_path, "w", encoding="utf-8") as fh:
        fh.write("[2026-11-04T00:00:00] SUMMARIZED x\n" * 1000)
    with mock.patch("builtins.open", side_effect=AssertionError("read the audit log")):
        status = auditor.custody_status()
    assert status == {"failed_writes_count": 0, "chain_of_custody_at_risk": False}
    auditor.failed_writes_buffer.append("lost line")
    assert auditor.custody_status()["chain_of_custody_at_risk"] is True


def test_recent_message_ids_are_the_tail_without_transcripts():
    from eye.bridge.eye_bridge import EYEBridge
    bridge = EYEBridge.__new__(EYEBridge)
    history = [{"id": "m%d" % i, "role": "user" if i % 2 else "assistant",
                "content": "x" * 5000,
                "metadata": {"pinned": i == 98, "transcript": ["t"] * 100}}
               for i in range(100)]
    bridge.context_manager = mock.Mock(conversation_history=history)
    out = json.loads(bridge.get_recent_message_ids(3))
    assert out["success"]
    assert [m["id"] for m in out["data"]] == ["m97", "m98", "m99"]
    assert out["data"][1]["metadata"] == {"pinned": True}
    assert all("content" not in m for m in out["data"])
    # a silly count is bounded, never the whole list
    assert len(json.loads(bridge.get_recent_message_ids(10 ** 6))["data"]) == 100
    assert len(json.loads(bridge.get_recent_message_ids(0))["data"]) == 1
