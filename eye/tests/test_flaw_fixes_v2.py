"""
Regression tests for flaw-hunt #2 (backends & tool handlers):
  - search_artifacts returns JSON-serializable dicts with the REAL SearchResult
    fields and caps by total match rows (never crashes the turn).
  - LOLBAS / live-intel returns real matches on a cold cache, or an explicit
    intel_unavailable status — never an authoritative false "no match".
  - Anthropic / Gemini surface a visible marker when output is length-truncated.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from eye.services.forensic_handlers import ForensicHandlers

try:
    from data.search_engine import SearchResult, SearchResults
    HAS_SEARCH = True
except Exception:
    HAS_SEARCH = False


@unittest.skipUnless(HAS_SEARCH, "data.search_engine unavailable")
class TestSearchArtifactsHandler(unittest.TestCase):
    def _handler_with_results(self, results):
        cm = MagicMock()
        cm.search_service.search.return_value = results
        return ForensicHandlers(cm)

    def test_results_are_json_serializable_and_real_fields(self):
        results = SearchResults()
        results.add_result(SearchResult(
            table_name="prefetch_data", row_id=1,
            matched_columns=["executable_name"],
            record_data={"executable_name": "evil.exe"},
        ))
        handler = self._handler_with_results(results)
        out = handler.handle_search_artifacts({"search_term": "evil"})

        self.assertTrue(out["success"])
        # The whole point: this must NOT raise (no default= needed).
        json.dumps(out)
        self.assertEqual(out["total_matches"], 1)
        row = out["results"][0]
        self.assertEqual(row["table"], "prefetch_data")
        self.assertEqual(row["record"], {"executable_name": "evil.exe"})
        self.assertIn("matched_columns", row)

    def test_caps_by_total_rows_not_tables(self):
        results = SearchResults()
        for i in range(60):
            results.add_result(SearchResult(
                table_name="prefetch_data", row_id=i,
                matched_columns=["c"], record_data={"i": i},
            ))
        handler = self._handler_with_results(results)
        out = handler.handle_search_artifacts({"search_term": "x"})
        self.assertEqual(len(out["results"]), 50)   # capped by ROWS
        self.assertEqual(out["total_matches"], 60)
        self.assertIn("50 of 60", out["note"])
        json.dumps(out)

    def test_missing_term(self):
        out = ForensicHandlers(MagicMock()).handle_search_artifacts({})
        self.assertFalse(out["success"])


class TestLiveIntelColdCache(unittest.TestCase):
    def setUp(self):
        self.handler = ForensicHandlers(MagicMock())

    def test_cold_cache_fetches_synchronously_and_matches(self):
        class FakeResp:
            status_code = 200
            def json(self_inner):
                return [{"Name": "Certutil.exe", "Description": "cert tool", "Commands": []}]

        with patch("eye.services.forensic_handlers.requests.get", return_value=FakeResp()):
            out = self.handler.handle_query_living_off_the_land_intel({"binary_name": "certutil.exe"})

        # Must find the LOLBIN on first use — not a false negative.
        self.assertTrue(out["success"])
        self.assertTrue(out["matches"])
        self.assertEqual(out["matches"][0]["source"], "LOLBAS")

    def test_unavailable_feeds_return_intel_unavailable_not_no_match(self):
        with patch("eye.services.forensic_handlers.requests.get", side_effect=Exception("offline")):
            out = self.handler.handle_query_living_off_the_land_intel({"binary_name": "certutil.exe"})

        # Critical: do NOT authoritatively clear the binary when feeds failed.
        self.assertFalse(out["success"])
        self.assertTrue(out.get("intel_unavailable"))
        self.assertEqual(out["matches"], [])


class TestOutputTruncationMarkers(unittest.TestCase):
    def _block(self, **kw):
        b = MagicMock()
        for k, v in kw.items():
            setattr(b, k, v)
        return b

    def test_anthropic_marks_length_truncation(self):
        from eye.backends.cloud_api.anthropic_backend import AnthropicBackend
        be = AnthropicBackend("claude-x", MagicMock())
        parsed = MagicMock()
        parsed.content = [self._block(type="text", text="a long synthesis")]
        parsed.stop_reason = "max_tokens"
        raw = MagicMock()
        raw.headers = {}
        raw.parse.return_value = parsed
        be._client = MagicMock()
        be._client.messages.with_raw_response.create.return_value = raw

        out = be.generate("sys", "msg")
        self.assertIn("Output truncated", out["content"])

    def test_gemini_marks_length_truncation(self):
        from eye.backends.cloud_api.gemini_backend import GeminiBackend
        be = GeminiBackend("gemini-x", MagicMock())
        resp = MagicMock()
        resp.text = "a long synthesis"
        resp.function_calls = []
        resp.candidates = [self._block(finish_reason="MAX_TOKENS")]
        be._client = MagicMock()
        be._client.models.generate_content.return_value = resp

        out = be.generate("sys", "msg")
        self.assertIn("Output truncated", out["content"])


if __name__ == "__main__":
    unittest.main()
