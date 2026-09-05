"""
Context Window Registry for the EYE AI Forensic Assistant.

Maps a backend model to its real context window (in tokens) so the
ContextManager can size `max_total_tokens` to whatever backend the Eye is
pointed at, instead of a flat 64K default. This is the *upward* half of the
adaptation story:

This registry is the **fallback** in a backend-driven resolution chain. The
ContextManager first asks the backend for its REAL window via
`ModelRouter.get_context_window()` (Gemini `input_token_limit`, Ollama /
LM Studio model info) and only falls back here when the backend can't self-report:

- Anthropic / OpenAI do NOT expose a context window over their `/v1/models`
  APIs, so their windows live in `CONTEXT_WINDOWS` below (matched by name prefix).
- Gemini / Ollama / LM Studio self-report at runtime, so they normally never
  reach this table; their entries here are a last-resort fallback. Local servers
  also keep the `n_ctx:` error probe in `query_processor.py`, which overrides
  downward at call time.
- Anything unknown resolves to `None`, and the caller keeps its 64K fallback.

No network calls. Values reflect each provider's documented default
context window. Keep this list ordered most-specific-first within a family so
prefix matching picks the tightest match.
"""

from typing import Optional

# Default window for an unknown model. The caller substitutes this when
# `resolve_context_window` returns None, but it is named here for clarity.
DEFAULT_CONTEXT_WINDOW = 64_000

# Backends whose real window is discovered at runtime (n_ctx probe) rather than
# from this static table. We deliberately do NOT guess a window for these.
_RUNTIME_PROBED_BACKENDS = {"ollama", "lm_studio", "vllm", "llama", "gemini_cli"}

# Ordered list of (model-name-prefix, context_window). Matching is
# case-insensitive and prefix-based on the normalized model name, longest /
# most-specific entries first so e.g. "gpt-4o" wins over "gpt-4".
_MODEL_WINDOWS = [
    # --- Anthropic Claude ---------------------------------------------------
    # Claude 4.x family, Fable, and Claude 3.x family all default to 200K.
    ("claude-opus-4", 200_000),
    ("claude-sonnet-4", 200_000),
    ("claude-haiku-4", 200_000),
    ("claude-fable", 200_000),
    ("claude-3-7", 200_000),
    ("claude-3-5", 200_000),
    ("claude-3", 200_000),
    ("claude-2", 200_000),
    ("claude", 200_000),

    # --- OpenAI -------------------------------------------------------------
    # GPT-4.1 family: 1M. o-series reasoning: 200K. GPT-4o / 4-turbo: 128K.
    # Legacy GPT-4: 8K, GPT-3.5: 16K.
    ("gpt-4.1", 1_000_000),
    ("gpt-4o", 128_000),
    ("gpt-4-turbo", 128_000),
    ("gpt-4-1106", 128_000),
    ("gpt-4-0125", 128_000),
    ("gpt-4-32k", 32_768),
    ("gpt-4", 8_192),
    ("gpt-3.5-turbo-16k", 16_385),
    ("gpt-3.5", 16_385),
    ("o4", 200_000),
    ("o3", 200_000),
    ("o1", 200_000),

    # --- Google Gemini ------------------------------------------------------
    # 2.5/2.0 and 1.5 Pro carry very large windows; Flash variants 1M.
    ("gemini-2.5-pro", 2_000_000),
    ("gemini-2.5", 1_000_000),
    ("gemini-2.0", 1_000_000),
    ("gemini-1.5-pro", 2_000_000),
    ("gemini-1.5-flash", 1_000_000),
    ("gemini-1.5", 1_000_000),
    ("gemini-1.0-pro", 32_768),
    ("gemini-pro", 32_768),
    ("gemini", 1_000_000),
    # DeepSeek (OpenAI-compatible). V3/R1 expose a 64K context window via the API.
    ("deepseek-reasoner", 65_536),
    ("deepseek-chat", 65_536),
    ("deepseek", 65_536),
    # Kimi / Moonshot (OpenAI-compatible). Window is encoded in the model id.
    ("moonshot-v1-128k", 131_072),
    ("moonshot-v1-32k", 32_768),
    ("moonshot-v1-8k", 8_192),
    ("kimi-k2", 131_072),
    ("kimi", 131_072),
    ("moonshot", 131_072),
    # xAI Grok.
    ("grok-4", 256_000),
    ("grok-3-mini", 131_072),
    ("grok-3", 131_072),
    ("grok", 131_072),
    # Mistral.
    ("mistral-large", 131_072),
    ("mistral-medium", 131_072),
    ("mistral-small", 32_768),
    ("codestral", 262_144),
    ("magistral", 40_960),
    ("mistral", 32_768),
    # Open-weight families used by NVIDIA / Groq / OpenRouter (matched by
    # `prefix in name`, so they also resolve namespaced ids like
    # `meta/llama-3.3-70b-instruct` and `moonshotai/kimi-k2-instruct`).
    ("llama-3.3", 131_072),
    ("llama-3.1", 131_072),
    ("llama-3", 8_192),
    ("nemotron", 131_072),
    ("qwen3", 131_072),
    ("qwen2.5", 131_072),
    ("qwen", 32_768),
    ("gpt-oss", 131_072),
]


def _normalize(model_name: str) -> str:
    """Lowercase and strip a leading 'models/' (Gemini) or vendor prefix."""
    name = (model_name or "").strip().lower()
    if name.startswith("models/"):
        name = name[len("models/"):]
    return name


def resolve_context_window(backend: Optional[str], model_name: Optional[str]) -> Optional[int]:
    """Return the real context window (tokens) for a backend model, or None.

    None means "unknown — caller should keep its own fallback (or, for local
    backends, let the runtime n_ctx probe decide)". A returned int is the
    model's full advertised window with no safety cap applied here; the
    10% output reserve is applied downstream in guarded_generate.

    Args:
        backend: backend id (e.g. "anthropic", "openai", "gemini", "ollama").
        model_name: the configured model name (may carry version/date suffix).

    Returns:
        The context window in tokens, or None if it is unknown / runtime-probed.
    """
    bk = (backend or "").strip().lower()

    # Local backends are discovered at runtime, not from this table.
    if bk in _RUNTIME_PROBED_BACKENDS:
        return None

    name = _normalize(model_name)
    if not name:
        return None

    for prefix, window in _MODEL_WINDOWS:
        if name.startswith(prefix) or prefix in name:
            return window

    return None


# ---------------------------------------------------------------------------
# Curated model catalog
#
# A small, hand-maintained list of current cloud model IDs so the onboarding
# wizard and the GUI model menu can offer a sensible selection WITHOUT a live
# API round-trip. This is a convenience layer only — live ``list_models()``
# (the account's real entitlements) always takes precedence and is merged on
# top of these. We curate Anthropic/Claude here; openai/gemini are intentionally
# left empty so we don't ship IDs that may be stale (callers fall back to live
# detection for those).
#
# Order matters: most-capable first within a family. RECOMMENDED is the subset
# the UI highlights as the suggested choices (mapped to the Eye's deployment
# story: deep analysis / balanced default / fast triage).
#
# These are an OFFLINE convenience so "Common Models" works without an API round
# trip. The account's live ``list_models()`` is always merged on top, so brand-new
# IDs still appear even if this list lags; a stale entry is harmless (the user can
# pick a live one). Providers that are OpenAI-compatible (DeepSeek, Kimi/Moonshot)
# are keyed by their backend id.
# ---------------------------------------------------------------------------
CURATED_MODELS: dict = {
    "anthropic": [
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
        "claude-fable-5",
    ],
    "openai": [
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4o",
        "gpt-4o-mini",
        "o3",
        "o4-mini",
        "gpt-4-turbo",
    ],
    # gemini-1.5-* were removed: they are retired and 404 on generate, so
    # offering them in the menu handed the investigator a broken selection.
    # Live list_models() is merged on top, so newer ids still appear.
    "gemini": [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
    ],
    "deepseek": [
        "deepseek-chat",
        "deepseek-reasoner",
    ],
    "kimi": [
        "kimi-k2-0711-preview",
        "kimi-latest",
        "moonshot-v1-128k",
        "moonshot-v1-32k",
        "moonshot-v1-8k",
    ],
    # OpenRouter fans out to every model behind one key (namespaced ids). Live
    # list_models() returns the full catalog; this is just a common-picks seed.
    "openrouter": [
        "anthropic/claude-opus-4",
        "openai/gpt-4.1",
        "google/gemini-2.5-pro",
        "deepseek/deepseek-chat",
        "moonshotai/kimi-k2",
        "meta-llama/llama-3.3-70b-instruct",
        "x-ai/grok-4",
        "qwen/qwen-2.5-72b-instruct",
    ],
    # NVIDIA NIM (build.nvidia.com). Namespaced ids; live list_models() authoritative.
    "nvidia": [
        "meta/llama-3.3-70b-instruct",
        "deepseek-ai/deepseek-v3",
        "nvidia/llama-3.1-nemotron-70b-instruct",
        "qwen/qwen2.5-coder-32b-instruct",
        "mistralai/mistral-large-2-instruct",
    ],
    "groq": [
        "llama-3.3-70b-versatile",
        "moonshotai/kimi-k2-instruct",
        "openai/gpt-oss-120b",
        "qwen/qwen3-32b",
        "llama-3.1-8b-instant",
    ],
    "mistral": [
        "mistral-large-latest",
        "mistral-medium-latest",
        "mistral-small-latest",
        "codestral-latest",
    ],
    "xai": [
        "grok-4",
        "grok-3",
        "grok-3-mini",
    ],
}

# RECOMMENDED = the subset the wizard/menu highlights (starred, floated to top).
# The Eye is AGENTIC — every recommended id must SUPPORT TOOL CALLING, and the
# FIRST entry is the most powerful tool-calling model for that provider. Models
# that cannot call tools (e.g. DeepSeek-Reasoner/R1) are deliberately excluded
# from recommendations even when they are otherwise strong.
RECOMMENDED_MODELS: dict = {
    "anthropic": [
        "claude-opus-4-8",    # deep / complex threat analysis
        "claude-sonnet-4-6",  # balanced default
        "claude-haiku-4-5",   # fast triage
    ],
    "openai": [
        "gpt-4.1",            # most powerful general tool-caller
        "gpt-4o",             # balanced default
        "o4-mini",            # fast reasoning + tools
    ],
    "gemini": [
        "gemini-2.5-pro",     # deep analysis
        "gemini-2.5-flash",   # balanced default
        "gemini-2.0-flash",   # fast triage
    ],
    "deepseek": [
        # deepseek-reasoner (R1) is intentionally NOT recommended — it cannot call
        # tools, and the Eye needs tools. deepseek-chat (V3) supports function calling.
        "deepseek-chat",      # V3 — supports tool calling
    ],
    "kimi": [
        "kimi-k2-0711-preview",  # strongest agentic tool-use
        "moonshot-v1-128k",      # long-context default
        "moonshot-v1-32k",       # balanced
    ],
    "openrouter": [
        "anthropic/claude-opus-4",  # most powerful tool-caller
        "openai/gpt-4.1",           # strong default
        "google/gemini-2.5-pro",    # long-context
    ],
    "nvidia": [
        "meta/llama-3.3-70b-instruct",             # tool-capable default
        "deepseek-ai/deepseek-v3",                 # strong tool-caller
        "nvidia/llama-3.1-nemotron-70b-instruct",  # NVIDIA-tuned
    ],
    "groq": [
        "llama-3.3-70b-versatile",     # tool-capable, very fast
        "moonshotai/kimi-k2-instruct", # strong agentic tool-use
        "openai/gpt-oss-120b",         # powerful open model
    ],
    "mistral": [
        "mistral-large-latest",   # most powerful tool-caller
        "mistral-medium-latest",  # balanced
    ],
    "xai": [
        "grok-4",   # most powerful tool-caller
        "grok-3",   # balanced
    ],
}


def curated_models(backend: Optional[str]) -> list:
    """Return the curated model IDs for a backend (``[]`` if none/unknown).

    Convenience catalog for offline selection in the wizard / GUI; live
    discovery is merged on top by the callers."""
    return list(CURATED_MODELS.get((backend or "").strip().lower(), []))


def recommended_models(backend: Optional[str]) -> list:
    """Return the subset of curated models the UI should highlight as
    recommended (``[]`` if none/unknown)."""
    return list(RECOMMENDED_MODELS.get((backend or "").strip().lower(), []))
