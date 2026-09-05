"""
Tool-calling capability detection — for ANY model, including ones we've never seen.

The Eye is agentic: everything it does for an investigator flows through forensic
tool calls. So "can this model call tools?" is the single most consequential fact
about a backend — and until now the Eye answered it with a hardcoded name match on
``gemma*``, optimistically assuming every other model could. A new GGUF dropped
into LM Studio, a fine-tune, a fresh OpenRouter id: all were assumed capable, the
full tool payload was sent, and the failure surfaced as an opaque 500 mid-query
(which is exactly how the recurring Gemma 500 INTERNAL used to present).

This module answers the question properly, via a ladder of increasingly expensive
signals, and records HOW it knew. The provenance matters: a forensic tool should
be able to state that the model it ran under was *verified* tool-capable, not
assumed to be.

    1. cache             - previously determined, still fresh
    2. provider metadata - the provider itself tells us (authoritative, free)
    3. family registry   - known model/architecture families (offline, instant)
    4. live native probe - ask the model to call a trivial tool and see
    5. live text probe   - can it at least emit the fenced ```tool_call format?
    6. default           - assume native, low confidence, never blocks work

Rungs 1-3 are cheap and non-blocking; ``resolve()`` uses only those. The live
probes cost ~150 tokens once per model and are cached, so they only ever run from
an off-thread caller via ``probe()``.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# Bump when the probe logic changes in a way that invalidates stored verdicts.
PROBE_VERSION = 1

# A verdict older than this is re-derived (providers add function calling to
# existing models, and a local model can be re-quantized under the same name).
CACHE_TTL_SECONDS = 30 * 24 * 3600

# --- support ---------------------------------------------------------------
NATIVE = "native"                # real function calling
TEXT_PROTOCOL = "text_protocol"  # only the fenced ```tool_call format
NONE = "none"                    # cannot call tools at all
UNKNOWN = "unknown"

# --- confidence ------------------------------------------------------------
CONFIRMED = "confirmed"  # the provider said so, or we watched it happen
KNOWN = "known"          # a documented family/architecture behaviour
ASSUMED = "assumed"      # fallback; must NEVER change what the Eye sends

# --- source ----------------------------------------------------------------
SRC_CACHE = "cache"
SRC_METADATA = "provider_metadata"
SRC_REGISTRY = "family_registry"
SRC_PROBE = "live_probe"
SRC_DEFAULT = "default"

# Confidence levels trusted enough to change the outgoing request.
ACTIONABLE_CONFIDENCE = (CONFIRMED, KNOWN)


def _verdict(support, confidence, source, evidence, backend="", model="") -> Dict[str, Any]:
    return {
        "support": support,
        "confidence": confidence,
        "source": source,
        "evidence": evidence,
        "probed_at": time.time(),
        "backend": backend,
        "model": model,
        "probe_version": PROBE_VERSION,
    }


def is_actionable(verdict: Optional[Dict[str, Any]]) -> bool:
    """True when a verdict is solid enough to change what we send to the model.

    An ``assumed`` verdict is a guess; acting on it could disable native tools on
    a perfectly capable model, which is a worse failure than sending tools to one
    that ignores them.
    """
    return bool(verdict) and verdict.get("confidence") in ACTIONABLE_CONFIDENCE


def describe(verdict: Optional[Dict[str, Any]]) -> str:
    """Short human-readable provenance, e.g. 'confirmed by live probe'."""
    if not verdict:
        return "not determined"
    source = {
        SRC_CACHE: "cached result",
        SRC_METADATA: "the provider's own metadata",
        SRC_REGISTRY: "a known model family",
        SRC_PROBE: "a live probe",
        SRC_DEFAULT: "assumption (not verified)",
    }.get(verdict.get("source"), verdict.get("source") or "unknown")
    return f"{verdict.get('confidence', 'unknown')} by {source}"


# ---------------------------------------------------------------------------
# Rung 3: family / architecture registry
# ---------------------------------------------------------------------------

# Name fragments whose tool behaviour is documented. Checked against the model id
# (vendor prefix stripped) and, for local servers, the reported architecture.
_NO_NATIVE_TOOL_FAMILIES = (
    # Gemma on the Google Generative Language API supports neither
    # system_instruction nor function calling — see reference gemini/gemma notes.
    "gemma",
)
_EMBEDDING_MARKERS = ("embed", "embedding", "bert", "e5-", "bge-", "gte-", "minilm")

# Families with well-documented native function calling. Only used to SKIP a probe,
# never to override a provider's own metadata.
_NATIVE_TOOL_FAMILIES = (
    "gpt-4", "gpt-5", "o1", "o3", "o4",
    "claude-", "gemini-1.5", "gemini-2", "gemini-3",
    "mistral-large", "mistral-medium", "mistral-small",
    "llama-3.1", "llama-3.3", "qwen2.5", "qwen3",
    "deepseek-chat", "kimi-k2", "grok-",
)


def _normalize_model(model_name: str) -> str:
    name = (model_name or "").strip().lower()
    if name.startswith("models/"):
        name = name[len("models/"):]
    if "/" in name:  # vendor-prefixed ids (OpenRouter, NVIDIA, Groq)
        name = name.rsplit("/", 1)[-1]
    return name


def registry_lookup(backend: str, model_name: str, arch: str = "") -> Optional[Dict[str, Any]]:
    """Rung 3 — a documented family behaviour, or None if the family is unknown."""
    name = _normalize_model(model_name)
    arch = (arch or "").strip().lower()
    haystack = f"{name} {arch}".strip()

    if any(tag in haystack for tag in _EMBEDDING_MARKERS):
        return _verdict(NONE, KNOWN, SRC_REGISTRY,
                        f"'{name}' looks like an embedding model (no chat, no tools)",
                        backend, model_name)

    for family in _NO_NATIVE_TOOL_FAMILIES:
        if family in haystack:
            return _verdict(TEXT_PROTOCOL, KNOWN, SRC_REGISTRY,
                            f"'{family}' models do not support native function calling",
                            backend, model_name)

    for family in _NATIVE_TOOL_FAMILIES:
        if name.startswith(family):
            return _verdict(NATIVE, KNOWN, SRC_REGISTRY,
                            f"'{family}' is a documented function-calling family",
                            backend, model_name)
    return None


# ---------------------------------------------------------------------------
# Rung 2: provider metadata
# ---------------------------------------------------------------------------

def _openrouter_metadata(model_name: str, timeout: int = 8) -> Optional[Dict[str, Any]]:
    """OpenRouter publishes per-model ``supported_parameters`` containing "tools".

    The endpoint is public (no key), so this is free and authoritative — but only
    for models actually served BY OpenRouter. We deliberately do not use it to
    guess about the same weights hosted elsewhere: mapping e.g. Groq's
    ``llama-3.3-70b-versatile`` onto ``meta-llama/llama-3.3-70b-instruct`` is a
    fuzzy name match, and a wrong match would yield a CONFIRMED verdict about a
    different model — worse than admitting we don't know.
    """
    try:
        response = requests.get("https://openrouter.ai/api/v1/models", timeout=timeout)
        if response.status_code != 200:
            return None
        target = (model_name or "").strip().lower()
        for entry in (response.json() or {}).get("data", []):
            if (entry.get("id") or "").strip().lower() != target:
                continue
            params = entry.get("supported_parameters") or []
            if "tools" in params:
                return _verdict(NATIVE, CONFIRMED, SRC_METADATA,
                                "OpenRouter lists 'tools' in supported_parameters",
                                "openrouter", model_name)
            return _verdict(TEXT_PROTOCOL, CONFIRMED, SRC_METADATA,
                            "OpenRouter does NOT list 'tools' in supported_parameters",
                            "openrouter", model_name)
    except Exception:
        return None
    return None


def _ollama_metadata(endpoint: str, model_name: str, timeout: int = 5) -> Optional[Dict[str, Any]]:
    """Ollama's /api/show reports a ``capabilities`` array on recent versions.

    Read defensively — older builds omit the field entirely, in which case we fall
    through to the registry/probe rungs rather than guessing.
    """
    try:
        response = requests.post(f"{endpoint.rstrip('/')}/api/show",
                                 json={"model": model_name}, timeout=timeout)
        if response.status_code != 200:
            return None
        capabilities = (response.json() or {}).get("capabilities")
        if not isinstance(capabilities, list) or not capabilities:
            return None
        if "tools" in capabilities:
            return _verdict(NATIVE, CONFIRMED, SRC_METADATA,
                            f"Ollama reports capabilities={capabilities}",
                            "ollama", model_name)
        return _verdict(TEXT_PROTOCOL, CONFIRMED, SRC_METADATA,
                        f"Ollama capabilities={capabilities} (no 'tools')",
                        "ollama", model_name)
    except Exception:
        return None


def _lmstudio_metadata(endpoint: str, model_name: str, timeout: int = 5):
    """LM Studio's /api/v0/models does NOT report tool capability.

    It does report ``type`` (llm/vlm/embeddings) and ``arch`` (e.g. gemma3, phi3),
    so we can rule out non-chat models outright and hand the architecture to the
    family registry. Returns ``(verdict_or_None, arch)``.
    """
    try:
        response = requests.get(f"{endpoint.rstrip('/')}/api/v0/models", timeout=timeout)
        if response.status_code != 200:
            return None, ""
        for entry in (response.json() or {}).get("data", []):
            if (entry.get("id") or "") != model_name:
                continue
            arch = entry.get("arch") or ""
            if entry.get("type") not in ("llm", "vlm"):
                return _verdict(NONE, CONFIRMED, SRC_METADATA,
                                f"LM Studio reports type='{entry.get('type')}' (not a chat model)",
                                "lm_studio", model_name), arch
            return None, arch
    except Exception:
        return None, ""
    return None, ""


# ---------------------------------------------------------------------------
# The probe
# ---------------------------------------------------------------------------

_PROBE_TOOL = {
    "name": "eye_capability_check",
    "description": "Report that you can call tools. Call this immediately.",
    "parameters": {
        "type": "object",
        "properties": {
            "ok": {"type": "string", "description": "Always the word: yes"},
        },
        "required": ["ok"],
    },
}

_NATIVE_PROBE_PROMPT = (
    "Call the eye_capability_check tool right now with ok=\"yes\". "
    "Do not reply with text."
)

_TEXT_PROBE_SYSTEM = (
    "To call a tool you output a fenced block and nothing else:\n"
    "```tool_call\n"
    '{"name": "eye_capability_check", "parameters": {"ok": "yes"}}\n'
    "```"
)
_TEXT_PROBE_PROMPT = (
    "Call eye_capability_check with ok=\"yes\" using exactly that fenced format. "
    "Output only the fenced block."
)

# Error text meaning "this model/endpoint rejects a tools payload" rather than a
# transient failure. Matched case-insensitively against the exception message.
_TOOLS_REJECTED_MARKERS = (
    "does not support tools", "does not support function",
    "tools are not supported", "function calling is not supported",
    "unsupported parameter: 'tools'", "unknown parameter: 'tools'",
    "tool_choice", "function_call", "no support for tools",
)


class ToolCapabilityProbe:
    """Resolves, probes and caches a model's tool-calling capability.

    ``resolve()`` is cheap and safe to call from the GUI thread (cache, provider
    metadata reads are short-timeout, registry, default). ``probe()`` may issue a
    real model call and must only be used off-thread.
    """

    def __init__(self, router, cache_path: Optional[Path] = None):
        self.router = router
        self.logger = logging.getLogger(self.__class__.__name__)
        self._cache_path = Path(cache_path) if cache_path else self._default_cache_path()
        self._cache: Optional[Dict[str, Any]] = None

    # -- cache ------------------------------------------------------------
    @staticmethod
    def _default_cache_path() -> Path:
        # Capability is a property of the MODEL, not of a case, so it lives with
        # the app config rather than in a case's EYE_Logs.
        from eye.services.config_manager import _default_config_dir
        return _default_config_dir() / "eye_tool_capability.json"

    @staticmethod
    def _key(backend: str, model: str) -> str:
        return f"{backend}::{model}"

    def _load_cache(self) -> Dict[str, Any]:
        if self._cache is not None:
            return self._cache
        self._cache = {}
        try:
            if self._cache_path.exists():
                with open(self._cache_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self._cache = loaded
        except Exception as e:
            self.logger.debug(f"Tool-capability cache unreadable, starting fresh: {e}")
        return self._cache

    def _save_cache(self):
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache or {}, f, indent=2)
        except Exception as e:
            # A cache we cannot persist is a performance loss, never a failure.
            self.logger.debug(f"Could not persist tool-capability cache: {e}")

    def cached(self, backend: str, model: str) -> Optional[Dict[str, Any]]:
        entry = self._load_cache().get(self._key(backend, model))
        if not isinstance(entry, dict):
            return None
        if entry.get("probe_version") != PROBE_VERSION:
            return None
        if (time.time() - float(entry.get("probed_at") or 0)) > CACHE_TTL_SECONDS:
            return None
        return {**entry, "source": SRC_CACHE, "origin": entry.get("source")}

    def remember(self, verdict: Dict[str, Any]):
        cache = self._load_cache()
        key = self._key(verdict.get("backend", ""), verdict.get("model", ""))
        previous = cache.get(key)
        cache[key] = verdict
        self._save_cache()
        if not previous or previous.get("support") != verdict.get("support"):
            self._audit(verdict)

    def _audit(self, verdict: Dict[str, Any]):
        """Record the verdict in the case audit trail.

        Which capabilities the model actually had is part of how an investigation
        was conducted — a report should be able to show that tools were run
        natively, or that the model was known-degraded at the time. Best-effort:
        an unavailable auditor never blocks capability detection.
        """
        try:
            ref = getattr(self.router, "_context_manager_ref", None)
            context_manager = ref() if callable(ref) else None
            auditor = getattr(context_manager, "truncation_auditor", None)
            if auditor is None:
                return
            from eye.services.evidence_seal import EvidenceSeal
            summary = (f"{verdict.get('backend')}:{verdict.get('model')} -> "
                       f"{verdict.get('support')} ({describe(verdict)})")
            auditor.log_event(
                action="TOOL_CAPABILITY",
                message_id=f"capability-{verdict.get('backend')}-{verdict.get('model')}",
                token_count=0,
                reason="model_tool_capability_determined",
                message_hash=EvidenceSeal._sha256(summary),
                metadata={k: verdict.get(k) for k in
                          ("support", "confidence", "source", "evidence", "probed_at",
                           "backend", "model")},
            )
        except Exception as e:
            self.logger.debug(f"Capability audit skipped: {e}")

    def forget(self, backend: str, model: str):
        cache = self._load_cache()
        cache.pop(self._key(backend, model), None)
        self._save_cache()

    @classmethod
    def read_cached(cls, backend: str, model: str) -> Optional[Dict[str, Any]]:
        """Look up a stored verdict without needing a live router.

        For read-only surfaces (the Settings panel) that want to display what is
        already known without constructing a backend or issuing any call.
        """
        try:
            probe = cls(router=None)
            return probe.cached(backend, model)
        except Exception:
            return None

    # -- context ----------------------------------------------------------
    def _active(self):
        config = getattr(self.router, "config", {}) or {}
        return (config.get("backend") or ""), (config.get("model_name") or ""), config

    # -- rungs 1-3 (cheap, non-blocking) ----------------------------------
    def resolve(self, use_cache: bool = True) -> Dict[str, Any]:
        """Cheap verdict: cache -> provider metadata -> registry -> default.

        Never issues a model call, so this is safe on the GUI thread.
        """
        backend, model, config = self._active()

        if use_cache:
            hit = self.cached(backend, model)
            if hit:
                return hit

        try:
            verdict, arch = self._metadata(backend, model, config)
            if verdict:
                self.remember(verdict)
                return verdict

            from_registry = registry_lookup(backend, model, arch)
            if from_registry:
                self.remember(from_registry)
                return from_registry
        except Exception as e:
            self.logger.debug(f"Capability metadata/registry lookup failed: {e}")

        # Optimistic default. ASSUMED confidence, so it can never change what the
        # Eye sends — an unknown model is still given every chance to work.
        return _verdict(NATIVE, ASSUMED, SRC_DEFAULT,
                        "no metadata or known family; assuming native function calling",
                        backend, model)

    def _metadata(self, backend: str, model: str, config: Dict[str, Any]):
        """Rung 2. Returns ``(verdict_or_None, arch_hint)``."""
        if backend == "openrouter":
            return _openrouter_metadata(model), ""
        if backend == "ollama":
            endpoint = config.get("api_endpoint") or "http://localhost:11434"
            return _ollama_metadata(endpoint, model), ""
        if backend in ("lm_studio", "vllm"):
            endpoint = config.get("api_endpoint") or "http://localhost:1234"
            return _lmstudio_metadata(endpoint, model)

        # Gemini: the backend already owns Gemma detection — reuse it rather than
        # re-deriving the name check in a third place.
        is_gemma = getattr(getattr(self.router, "backend", None), "_is_gemma", None)
        if callable(is_gemma):
            try:
                if is_gemma():
                    return _verdict(
                        TEXT_PROTOCOL, KNOWN, SRC_REGISTRY,
                        "Gemma on the Gemini API supports neither system_instruction nor tools",
                        backend, model), ""
            except Exception:
                pass
        return None, ""

    # -- rungs 4-5 (live, off-thread only) --------------------------------
    def probe(self, force: bool = False) -> Dict[str, Any]:
        """Full ladder, including live probes. May issue up to two small model
        calls (~150 tokens each). Off-thread callers only."""
        backend, model, _ = self._active()

        if force:
            self.forget(backend, model)
        else:
            hit = self.cached(backend, model)
            if hit:
                return hit
            cheap = self.resolve(use_cache=False)
            # Metadata / registry already answered definitively — don't spend a call.
            if cheap.get("confidence") in ACTIONABLE_CONFIDENCE:
                return cheap

        verdict = self._probe_native(backend, model)

        if verdict["support"] != NATIVE:
            text_verdict = self._probe_text(backend, model)
            # Only let the text probe REPLACE the native finding when it actually
            # concluded something. A text probe that merely failed (network blip,
            # timeout) must not erase a CONFIRMED "this model rejects tools" and
            # downgrade it to an assumed "no tools at all" — that would be losing
            # evidence to noise.
            if text_verdict.get("confidence") == CONFIRMED:
                text_verdict["evidence"] = f"{verdict['evidence']}; {text_verdict['evidence']}"
                verdict = text_verdict
            else:
                verdict["evidence"] = (
                    f"{verdict['evidence']}; text-protocol probe inconclusive "
                    f"({text_verdict.get('evidence')})")

        self.remember(verdict)
        return verdict

    def _probe_native(self, backend: str, model: str) -> Dict[str, Any]:
        """Ask for one trivial tool call and see what actually comes back."""
        try:
            response = self.router.generate(
                system_prompt="You are a tool-calling assistant.",
                user_message=_NATIVE_PROBE_PROMPT,
                tools=[_PROBE_TOOL],
                gen_params={"temperature": 0.0, "max_output_tokens": 256},
                # The probe must actually send tools — gating it on a prior
                # verdict would make the result circular instead of observed.
                _bypass_capability_gate=True,
            )
        except Exception as exc:
            message = str(exc).lower()
            if any(marker in message for marker in _TOOLS_REJECTED_MARKERS):
                return _verdict(TEXT_PROTOCOL, CONFIRMED, SRC_PROBE,
                                f"provider rejected a tools payload: {str(exc)[:160]}",
                                backend, model)
            return _verdict(UNKNOWN, ASSUMED, SRC_PROBE,
                            f"probe call failed: {str(exc)[:160]}", backend, model)

        # The backend itself may report that it dropped the tools (Gemini/Gemma).
        if response.get("tools_unsupported"):
            return _verdict(TEXT_PROTOCOL, CONFIRMED, SRC_PROBE,
                            "backend reported the model cannot accept a tools payload",
                            backend, model)

        if self._parse_native(response):
            return _verdict(NATIVE, CONFIRMED, SRC_PROBE,
                            "model emitted a native tool call when asked",
                            backend, model)

        return _verdict(TEXT_PROTOCOL, CONFIRMED, SRC_PROBE,
                        "model accepted tools but emitted none when explicitly asked",
                        backend, model)

    def _probe_text(self, backend: str, model: str) -> Dict[str, Any]:
        """Can it at least produce a parseable fenced ```tool_call block?"""
        try:
            response = self.router.generate(
                system_prompt=_TEXT_PROBE_SYSTEM,
                user_message=_TEXT_PROBE_PROMPT,
                tools=None,
                gen_params={"temperature": 0.0, "max_output_tokens": 256},
            )
        except Exception as exc:
            return _verdict(NONE, ASSUMED, SRC_PROBE,
                            f"text-protocol probe failed: {str(exc)[:160]}", backend, model)

        if self._parse_text(response.get("content") or ""):
            return _verdict(TEXT_PROTOCOL, CONFIRMED, SRC_PROBE,
                            "model produced a parseable fenced tool_call block",
                            backend, model)
        return _verdict(NONE, CONFIRMED, SRC_PROBE,
                        "model produced neither a native tool call nor a parseable "
                        "fenced tool_call block",
                        backend, model)

    # -- parsing (reuses the production parsers) --------------------------
    @staticmethod
    def _parser():
        """A bare ContextManager — _parse_tool_calls/_parse_text_tool_calls need
        only a logger, and using the REAL parsers means the probe accepts exactly
        what the agentic loop accepts."""
        from eye.services.context_manager import ContextManager
        parser = ContextManager.__new__(ContextManager)
        parser.logger = logging.getLogger("tool-capability-parser")
        return parser

    @classmethod
    def _parse_native(cls, response: Dict[str, Any]) -> List[Dict]:
        raw = response.get("tool_calls") or []
        if not raw:
            return []
        # Only count NATIVE calls here — _parse_tool_calls also falls back to the
        # text protocol, which would make the native probe pass on a text-only model.
        return cls._parser()._parse_tool_calls({"tool_calls": raw})

    @classmethod
    def _parse_text(cls, content: str) -> List[Dict]:
        return cls._parser()._parse_text_tool_calls(content or "")
