"""
Live LLM <-> Eye conformance: does a REAL model actually drive the Eye?

Everything else in the suite proves the Eye's side of the contract against a
scripted model. This file proves the other half — that a real provider, over its
real API, completes the loop the Eye is built around:

    model emits query_database  ->  Eye normalizes the call  ->  the handler runs
    it against a real SQLite artifact  ->  the model synthesizes from the rows.

That round-trip had never been verified live on ANY backend. The pre-existing
live harness (test_gemini_live_integration.py) stubs it out: `tools=None` for the
plain generate, `_get_tool_definitions -> []` and `_parse_tool_calls -> []` for
the seal test, and an empty case dir for the GEP test. So transport, sealing and
GEP were covered; the agentic loop was not.

SKIPPED BY DEFAULT. Select backends with the EYE_LIVE_BACKENDS env var; a backend
is still skipped if its credential or endpoint is not actually available.

    # PowerShell
    $env:EYE_LIVE_BACKENDS="gemini,openai,anthropic,lm_studio"
    python -m pytest eye/tests/test_live_llm_conformance.py -q -s

    # bash
    EYE_LIVE_BACKENDS=gemini,openai,anthropic python -m pytest eye/tests/test_live_llm_conformance.py -q -s

Keys are read through the real CredentialManager (the same path the app uses), so
no key is ever written into this file. Costs a handful of small calls per provider
on the cheapest model available; LM Studio is free.
"""

import os
import sqlite3
import shutil
import tempfile
import unittest
from pathlib import Path

import requests

from eye.services.model_router import ModelRouter, is_transient_model_error

# ---------------------------------------------------------------------------
# Selection / gating
# ---------------------------------------------------------------------------

_SELECTED = {b.strip().lower() for b in os.environ.get("EYE_LIVE_BACKENDS", "").split(",") if b.strip()}

# Cheapest-capable-first preferences. The first live model matching a prefix wins,
# so the run stays cheap without hardcoding ids that may age out.
_MODEL_PREFERENCES = {
    # NOT gemini-2.5-flash-lite: the API lists it but 404s on generate
    # ("no longer available to new users") — the first thing this harness caught.
    "gemini": ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.5-pro"),
    "openai": ("gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"),
    "anthropic": ("claude-haiku-4-5", "claude-sonnet-4-6", "claude-3-5-haiku"),
    # Prefer a model that can hold a conversation. On this machine `gama-4b` is
    # present but fails to load in LM Studio itself ("Error loading model"),
    # which is a local install problem, not an Eye one.
    "lm_studio": ("phi-4-reasoning", "instruct", "phi"),
}

_LOCAL_ENDPOINTS = {
    "lm_studio": "http://localhost:1234",
    "ollama": "http://localhost:11434",
}

# A value that cannot plausibly appear in model pretraining, so finding it in the
# final answer proves the data came from OUR database and not from the model's
# memory or a hallucination.
SENTINEL_EXECUTABLE = "ZQXVBRUNNER7742.EXE"
SENTINEL_RUN_COUNT = 4291


def _credential_for(backend: str):
    """Read a provider key via the real CredentialManager (never printed)."""
    try:
        from eye.services.credential_manager import CredentialManager
        return CredentialManager().get_credential(f"{backend}_api_key")
    except Exception:
        return None


def _local_server_up(backend: str) -> bool:
    endpoint = _LOCAL_ENDPOINTS.get(backend)
    if not endpoint:
        return False
    probe = "/v1/models" if backend == "lm_studio" else "/api/tags"
    try:
        return requests.get(f"{endpoint}{probe}", timeout=3).status_code == 200
    except Exception:
        return False


def backend_available(backend: str) -> bool:
    """Selected AND actually reachable."""
    if backend not in _SELECTED:
        return False
    if backend in _LOCAL_ENDPOINTS:
        return _local_server_up(backend)
    return bool(_credential_for(backend))


def _skip_reason(backend: str) -> str:
    if backend not in _SELECTED:
        return f"Set EYE_LIVE_BACKENDS={backend} to run live {backend} conformance"
    if backend in _LOCAL_ENDPOINTS:
        return f"{backend} server not reachable at {_LOCAL_ENDPOINTS[backend]}"
    return f"No {backend} API key configured"


class _KeyringCredentials:
    """Adapter so a backend reads only the key for the provider under test."""

    def __init__(self, backend):
        self._key_name = f"{backend}_api_key"
        self._value = _credential_for(backend)

    def get_credential(self, key, timeout: float = 2.0):
        return self._value if key == self._key_name else None


def _pick_model(router, backend: str) -> str:
    """Cheapest preferred model that the account actually has, else the first."""
    try:
        models = router.list_models() or []
    except Exception:
        models = []
    for pref in _MODEL_PREFERENCES.get(backend, ()):
        for m in models:
            if m == pref:
                return m
    for pref in _MODEL_PREFERENCES.get(backend, ()):
        for m in models:
            if pref in m:
                return m
    return models[0] if models else "unknown-model"


# ---------------------------------------------------------------------------
# Conformance matrix (printed at the end of the run)
# ---------------------------------------------------------------------------

RESULTS = {}


def record(backend: str, check: str, state: str, note: str = ""):
    RESULTS.setdefault(backend, {})[check] = (state, note)


def _print_matrix():
    if not RESULTS:
        return
    checks = ["connectivity", "generate", "capability_probe", "tool_round_trip",
              "context_window", "multi_turn", "error_surfacing"]
    print("\n\n=== Eye <-> LLM live conformance ===")
    for backend, results in RESULTS.items():
        model = results.get("_model", ("", ""))[1]
        print(f"\n  {backend}  ({model})")
        for check in checks:
            state, note = results.get(check, ("SKIP", ""))
            print(f"    {state:9} {check:18} {note}")
    print()


# ---------------------------------------------------------------------------
# A real case directory with a real artifact database
# ---------------------------------------------------------------------------

def _build_case(tmp: str) -> str:
    """A minimal but REAL case: Target_Artifacts/prefetch.db with a sentinel row.

    Mirrors the layout eye_window._init_services expects, so ForensicDatabaseService
    discovers the database exactly as it does in the app.
    """
    artifacts = Path(tmp) / "Target_Artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    db_path = artifacts / "prefetch.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE prefetch (executable_name TEXT, run_count INTEGER, last_run_time TEXT)"
    )
    conn.executemany(
        "INSERT INTO prefetch VALUES (?, ?, ?)",
        [
            ("NOTEPAD.EXE", 12, "2026-03-01T09:15:00Z"),
            (SENTINEL_EXECUTABLE, SENTINEL_RUN_COUNT, "2026-03-02T22:41:07Z"),
            ("CHROME.EXE", 88, "2026-03-02T08:02:11Z"),
        ],
    )
    conn.commit()
    conn.close()
    return str(artifacts)


def _build_context_manager(tmp: str, router):
    """A REAL ContextManager wired exactly like eye_window._init_services.

    Nothing is mocked: _get_tool_definitions, _parse_tool_calls and
    forensic_handlers.handle_query_database are all production code, which is the
    entire point — this test exists to prove those paths work with a real model.
    """
    from eye.services.context_manager import ContextManager
    from eye.services.database_service import ForensicDatabaseService
    from eye.services.search_service import ForensicSearchService
    from eye.services.rag_service import RAGService
    from eye.services.report_engine import ReportEngine
    from eye.services.case_context_manager import CaseContextManager

    artifacts = _build_case(tmp)
    return ContextManager(
        model_router=router,
        database_service=ForensicDatabaseService(artifacts),
        search_service=ForensicSearchService(artifacts),
        rag_service=RAGService(),
        report_engine=ReportEngine(tmp),
        case_directory=tmp,
        case_context_manager=CaseContextManager(tmp),
    )


# ---------------------------------------------------------------------------
# The conformance contract, run once per backend
# ---------------------------------------------------------------------------

class LiveConformanceContract:
    """Mixin holding the checks. Subclasses set BACKEND and are gated per-backend.

    Not a TestCase itself, so unittest does not collect it standalone.
    """

    BACKEND = None
    READ_TIMEOUT = 120

    @classmethod
    def setUpClass(cls):
        cls.creds = _KeyringCredentials(cls.BACKEND)
        cls.config = cls._base_config()
        probe = ModelRouter(dict(cls.config), credential_manager=cls.creds)
        cls.model_name = _pick_model(probe, cls.BACKEND)
        cls.config["model_name"] = cls.model_name
        cls.router = ModelRouter(dict(cls.config), credential_manager=cls.creds)
        record(cls.BACKEND, "_model", "", cls.model_name)

    @classmethod
    def _base_config(cls):
        if cls.BACKEND in _LOCAL_ENDPOINTS:
            return {
                "backend": cls.BACKEND,
                "model_name": "default",
                "integration_type": "local_server",
                "api_endpoint": _LOCAL_ENDPOINTS[cls.BACKEND],
            }
        return {
            "backend": cls.BACKEND,
            "model_name": "default",
            "integration_type": "cloud_api",
        }

    # -- 1. connectivity ---------------------------------------------------
    def test_1_connectivity_and_discovery(self):
        connected = self.router.validate_connectivity()
        models = self.router.list_models()
        record(self.BACKEND, "connectivity",
               "PASS" if connected and models else "FAIL",
               f"{len(models)} models")
        self.assertTrue(connected, f"{self.BACKEND}: connectivity failed")
        self.assertTrue(models, f"{self.BACKEND}: no models discovered")

    # -- 2. plain generation ------------------------------------------------
    def test_2_plain_generate(self):
        resp = self.router.generate(
            system_prompt="You are a terse forensic assistant. Answer in one short sentence.",
            user_message="Reply with exactly the word: ACKNOWLEDGED",
        )
        content = (resp.get("content") or "").strip()
        record(self.BACKEND, "generate", "PASS" if content else "FAIL",
               repr(content[:48]))
        self.assertTrue(content, f"{self.BACKEND}: empty content")

    # -- 2b. capability detection -------------------------------------------
    def test_2b_capability_probe_matches_reality(self):
        """The detection ladder's verdict must agree with what the model does.

        This is the check that makes capability detection trustworthy: a verdict
        nobody cross-examines is just a nicer-looking guess. The probe runs
        forced (ignoring any cached answer) and is then compared against the
        observed tool round-trip in test_3.
        """
        import tempfile as _tf
        with _tf.TemporaryDirectory() as tmp:
            from eye.services.tool_capability import ToolCapabilityProbe
            probe = ToolCapabilityProbe(self.router, cache_path=Path(tmp) / "cap.json")
            verdict = probe.probe(force=True)

            # Cache must prevent a second round of model calls.
            before = dict(verdict)
            again = probe.probe()
            self.assertEqual(again.get("support"), before.get("support"))
            self.assertEqual(again.get("source"), "cache")

        type(self)._capability = verdict
        record(self.BACKEND, "capability_probe", "PASS",
               f"{verdict['support']} ({verdict['confidence']}/{verdict['source']})")
        self.assertIn(verdict["support"], ("native", "text_protocol", "none", "unknown"))

    # -- 3. THE tool round-trip --------------------------------------------
    def test_3_tool_round_trip(self):
        """A real model must call query_database and answer from the real rows."""
        tmp = tempfile.mkdtemp()
        try:
            cm = _build_context_manager(tmp, self.router)
            tools = cm._get_tool_definitions()
            self.assertTrue(tools, "No tool definitions built")

            tool_support = self.router.get_tool_support()
            question = (
                "Using the forensic tools, query the prefetch database and tell me the "
                f"run_count of the executable named {SENTINEL_EXECUTABLE}. "
                "The database file is named 'prefetch.db' and the table is 'prefetch'. "
                "Call the query_database tool - do not guess."
            )

            # The REAL system prompt — it carries the live DB schema manifest, so
            # the model learns the actual table/column names from production code.
            resp = self.router.generate(
                system_prompt=cm._build_system_prompt("", []),
                user_message=question,
                tools=tools,
            )

            calls = cm._parse_tool_calls(resp)
            mode = "native"

            if not calls:
                # No native call. Before declaring failure, try the path the Eye
                # itself falls back to for models that cannot function-call
                # (Gemma on the Gemini API, most small local models): the TEXT
                # tool-call protocol, parsed by _parse_text_tool_calls. A model
                # that works this way is DEGRADED, not broken — and that is a
                # real, reportable state rather than a test failure.
                text_resp = self.router.generate(
                    system_prompt=(
                        "You are EYE, a forensic assistant. To run a tool, reply with ONLY a "
                        "fenced block:\n```tool_call\n"
                        '{"name": "query_database", "parameters": '
                        '{"database_name": "prefetch.db", "sql_query": "SELECT ..."}}\n```\n'
                        "No prose, no explanation, no thinking - output the fenced block only."
                    ),
                    user_message=question,
                    gen_params={"temperature": 0.0, "max_output_tokens": 512},
                )
                calls = cm._parse_tool_calls(text_resp)
                mode = "text_protocol"

            if not calls:
                # Diagnose rather than just fail: the actionable cause is almost
                # always either "the model cannot function-call" or "the model
                # had no room left to answer". An empty reply on a small window
                # is the classic reasoning-model symptom — the <think> block
                # consumes the entire remaining budget.
                window = self.router.get_context_window()
                empty = not (resp.get("content") or "").strip()
                if empty and window and window <= 8192:
                    why = (f"empty reply on a {window:,}-token window — the model has no "
                           f"room to answer after its prompt; reload it with a larger context")
                else:
                    why = f"model does not emit tool calls in either mode (window={window})"
                record(self.BACKEND, "tool_round_trip", "FAIL", why)
                self.fail(f"{self.BACKEND} cannot drive the agentic loop: {why}. "
                          f"native content={(resp.get('content') or '')[:160]!r}")

            # Normalization contract: every backend's arg shape (OpenAI JSON
            # strings, Anthropic dicts, Ollama dicts, text-protocol JSON) must
            # arrive here as {"name": str, "parameters": dict}.
            call = next((c for c in calls if c.get("name") == "query_database"), calls[0])
            self.assertIsInstance(call.get("parameters"), dict,
                                  f"{self.BACKEND}: parameters not normalized to a dict")
            self.assertEqual(call.get("name"), "query_database",
                             f"{self.BACKEND}: model called {call.get('name')} instead")

            # Execute it for real.
            result = cm._execute_tool(call)
            self.assertTrue(result.get("success"), f"Tool execution failed: {result}")
            payload = str(result.get("result"))
            self.assertIn(str(SENTINEL_RUN_COUNT), payload,
                          f"{self.BACKEND}: query returned no sentinel row: {payload[:300]}")

            # Feed the result back and require synthesis from the REAL data.
            final = self.router.generate(
                system_prompt="You are EYE, a forensic assistant. Answer from the tool result only.",
                user_message=(f"Tool result:\n{payload}\n\n"
                              f"State the run_count of {SENTINEL_EXECUTABLE} as a number."),
            )
            answer = (final.get("content") or "")
            grounded = str(SENTINEL_RUN_COUNT) in answer
            if grounded:
                state = "PASS" if mode == "native" else "DEGRADED"
            else:
                state = "PARTIAL"
            record(self.BACKEND, "tool_round_trip", state,
                   f"{mode} tool call; synthesis "
                   f"{'grounded in real rows' if grounded else 'missed sentinel'}")

            # Cross-examine the capability verdict against what actually happened.
            # A predicted "native" that then needs the text protocol (or vice
            # versa) means the detector is lying to the investigator.
            predicted = (getattr(type(self), "_capability", {}) or {}).get("support")
            if predicted and predicted != "unknown":
                self.assertEqual(
                    predicted, mode,
                    f"{self.BACKEND}: capability probe predicted '{predicted}' but the "
                    f"real round-trip used '{mode}' — the detector disagrees with reality")
            self.assertTrue(grounded,
                            f"{self.BACKEND}: final answer did not carry the real value. "
                            f"answer={answer[:200]!r}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # -- 4. context window --------------------------------------------------
    def test_4_context_window_resolution(self):
        window = self.router.get_context_window()
        if window is not None:
            self.assertIsInstance(window, int)
            self.assertGreater(window, 1000, "Implausible context window")
            record(self.BACKEND, "context_window", "PASS", f"backend reports {window:,}")
        else:
            from eye.services.context_window_registry import resolve_context_window
            fallback = resolve_context_window(self.BACKEND, self.model_name)
            record(self.BACKEND, "context_window", "PASS",
                   f"registry fallback {fallback:,}" if fallback else "64K default")

    # -- 5. multi-turn history ----------------------------------------------
    def test_5_multi_turn_history(self):
        """History must survive _sanitize_messages' strict role alternation."""
        history = [
            {"role": "user", "content": "The case number is CASE-88231."},
            {"role": "assistant", "content": "Noted, CASE-88231."},
            {"role": "user", "content": "The examiner is Ghassan."},
            {"role": "assistant", "content": "Noted."},
        ]
        resp = self.router.generate(
            system_prompt="You are a terse assistant. Answer in one short sentence.",
            user_message="What is the case number I gave you? Reply with just the number.",
            history=history,
        )
        content = (resp.get("content") or "")
        ok = "88231" in content
        record(self.BACKEND, "multi_turn", "PASS" if ok else "PARTIAL",
               repr(content.strip()[:48]))
        self.assertTrue(content.strip(), f"{self.BACKEND}: empty multi-turn response")

    # -- 6. error surfacing --------------------------------------------------
    def test_6_bogus_model_surfaces_a_clear_error(self):
        """A typo'd model must fail fast and permanently, not hang or retry 3x."""
        config = dict(self.config)
        config["model_name"] = "definitely-not-a-real-model-xyz"
        router = ModelRouter(config, credential_manager=self.creds)
        try:
            resp = router.generate(system_prompt="s", user_message="hi")
            # Some servers (LM Studio) answer an unknown model id with whatever
            # is loaded, HTTP 200. The backend now flags that rather than letting
            # an answer be attributed to a model that never produced it.
            if resp.get("model_substituted"):
                record(self.BACKEND, "error_surfacing", "DEGRADED",
                       f"server substituted '{resp.get('model')}' (flagged, not silent)")
            else:
                record(self.BACKEND, "error_surfacing", "PARTIAL",
                       "bogus model did not raise")
        except Exception as exc:
            transient = is_transient_model_error(exc)
            record(self.BACKEND, "error_surfacing",
                   "PASS" if not transient else "PARTIAL",
                   "classified permanent" if not transient
                   else "misclassified transient (retried)")
            self.assertFalse(
                transient,
                f"{self.BACKEND}: a bad model name was classified transient and retried: {exc}")


@unittest.skipUnless(backend_available("gemini"), _skip_reason("gemini"))
class TestGeminiConformance(LiveConformanceContract, unittest.TestCase):
    BACKEND = "gemini"


@unittest.skipUnless(backend_available("openai"), _skip_reason("openai"))
class TestOpenAIConformance(LiveConformanceContract, unittest.TestCase):
    BACKEND = "openai"

    def test_7_reasoning_model_completes_live(self):
        """o-series models rejected `max_tokens` and any temperature, so every
        query 400'd. The offline test asserts the fix against a mock; this proves
        it against the API that actually rejected the old parameters."""
        models = self.router.list_models()
        target = next((m for m in ("o4-mini", "o3-mini", "o3") if m in models), None)
        if not target:
            self.skipTest("No o-series model available on this account")

        config = dict(self.config)
        config["model_name"] = target
        router = ModelRouter(config, credential_manager=self.creds)
        resp = router.generate(
            system_prompt="Answer in one word.",
            user_message="Reply with exactly: ACKNOWLEDGED",
            gen_params={"temperature": 0.2, "max_output_tokens": 2048},
        )
        content = (resp.get("content") or "").strip()
        record(self.BACKEND, "reasoning_model", "PASS" if content else "FAIL",
               f"{target}: {content[:32]!r}")
        self.assertTrue(content, f"o-series model {target} returned nothing")


@unittest.skipUnless(backend_available("anthropic"), _skip_reason("anthropic"))
class TestAnthropicConformance(LiveConformanceContract, unittest.TestCase):
    BACKEND = "anthropic"


@unittest.skipUnless(backend_available("lm_studio"), _skip_reason("lm_studio"))
class TestLMStudioConformance(LiveConformanceContract, unittest.TestCase):
    BACKEND = "lm_studio"
    # LM Studio JIT-loads a model on the first call; that can take minutes.
    READ_TIMEOUT = 600

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Give the JIT load room; the default 120s read timeout trips on a cold
        # model load and would look like a backend failure.
        try:
            cls.router.backend.read_timeout = cls.READ_TIMEOUT
        except Exception:
            pass


def tearDownModule():
    _print_matrix()


if __name__ == "__main__":
    unittest.main()
