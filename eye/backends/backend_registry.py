"""
Backend Registry: the ONE list of backend ids the Eye understands.

Every place that needs to know "is this a real backend?" reads from here:
the ModelRouter factory, the onboarding wizard, the bridge's model switch, and
``configs/eye_config_schema.json`` (asserted in sync by
``eye/tests/test_backend_registry.py``).

Why this module exists: the provider catalogue grew from 8 to 17 backends, but the
config schema's ``backend`` enum was a hand-typed literal that nobody updated. The
result was silent — connectivity validated fine, then ``save_config`` raised and the
choice was never persisted. A single source of truth makes that class of drift a
test failure instead of a support ticket.

Deliberately dependency-light (only ``cli_profiles``) so the schema test and
ConfigManager can import it without pulling in any provider SDK.
"""

from typing import List

from eye.backends.local_cli.cli_profiles import list_supported_backends

# --- APPROACH 1: LOCAL CLI ------------------------------------------------
# Sourced from CLI_PROFILES so adding a profile automatically makes it a valid,
# persistable backend id.
LOCAL_CLI_BACKENDS: List[str] = list(list_supported_backends())

# --- APPROACH 2: DIRECT LOCAL SERVERS -------------------------------------
LOCAL_SERVER_BACKENDS: List[str] = ["ollama", "lm_studio", "vllm"]

# --- APPROACH 3: CLOUD API AGENTS -----------------------------------------
# Native SDKs first, then the OpenAI-compatible providers that reuse OpenAIBackend
# with their own base_url + credential key. ``moonshot`` and ``grok`` are accepted
# aliases of ``kimi`` and ``xai`` (see ModelRouter._initialize_backend).
CLOUD_API_BACKENDS: List[str] = [
    "openai", "anthropic", "gemini",
    "openrouter", "nvidia", "deepseek", "kimi", "moonshot",
    "groq", "mistral", "xai", "grok",
]

# Every backend id ModelRouter can route, in schema-enum order.
SUPPORTED_BACKENDS: List[str] = (
    LOCAL_CLI_BACKENDS + LOCAL_SERVER_BACKENDS + CLOUD_API_BACKENDS
)

# ``local_server`` is the id the router and the bridge actually write;
# ``local_api`` is the historical spelling kept for configs written by older
# builds. Both are accepted everywhere.
INTEGRATION_TYPES: List[str] = ["local_cli", "local_api", "local_server", "cloud_api"]

# Integration types that talk to a REST endpoint and therefore require
# ``api_endpoint`` in the config.
LOCAL_SERVER_INTEGRATION_TYPES: List[str] = ["local_api", "local_server"]


def integration_type_for(backend: str) -> str:
    """Return the integration type a backend id belongs to.

    This is the same inference ModelRouter._initialize_backend performs; it lives
    here so the bridge and the wizard don't each keep their own copy (the bridge's
    hand-maintained map is what missed the newer providers).
    """
    bk = (backend or "").strip().lower()
    if bk in LOCAL_CLI_BACKENDS:
        return "local_cli"
    if bk in LOCAL_SERVER_BACKENDS:
        return "local_server"
    return "cloud_api"
