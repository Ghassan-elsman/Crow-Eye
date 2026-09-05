"""
Model Router and Backend Infrastructure for EYE AI Forensic Assistant.

This module implements a Strategy-based architectural pattern to provide a unified
interface for multiple Large Language Model (LLM) providers. It abstracts away 
the complexity of different SDKs (OpenAI, Anthropic, Google) and local 
execution methods (CLI, REST).

COMPONENTS:
1. LLMBackend (Abstract): Defines the mandatory forensic interface.
2. Provider Backends: Concrete implementations for specific AI services.
3. ModelRouter: The central controller that manages backend instantiation and routing.

"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
import logging
import re
import time
import requests
import json

# Import base class and backends from new organized structure
from eye.backends.base import LLMBackend


# Transient (retryable) vs. permanent model-call failures. This lives here so
# retry/backoff sits at the single choke point for EVERY model call (main loop,
# map-reduce, history summarization).
#
# The status code is read FIRST and is decisive. Substring matching on the
# message alone was wrong in both directions: a genuine 503 whose text mentioned
# a previous 429 was treated as permanent and never retried, and a permanent 400
# complaining about `max_tokens: 500` was retried three times with backoff.
_TRANSIENT_STATUSES = frozenset({500, 502, 503, 504, 529})
_PERMANENT_STATUSES = frozenset({400, 401, 403, 404, 409, 413, 422, 429})

# Message fallback, used only when no status code is available.
#
# Numbers are anchored on BOTH sides, because that is where the false positives
# came from — `req_1500x` and `max_tokens: 500` must not read as a 500. Named
# markers are anchored on the left only, so provider variants like Anthropic's
# `overloaded_error` and `INTERNAL_ERROR` still match.
_TRANSIENT_MESSAGE_RE = re.compile(
    r"\b(?:500|502|503|504|529)\b"
    r"|\b(?:INTERNAL|UNAVAILABLE|DEADLINE_EXCEEDED|overloaded|timeout|timed out|"
    r"temporarily unavailable|connection reset|connection aborted)",
    re.IGNORECASE,
)
_PERMANENT_MESSAGE_RE = re.compile(
    r"\b(?:400|401|403|404|422|429)\b"
    r"|\b(?:INVALID_ARGUMENT|PERMISSION_DENIED|RESOURCE_EXHAUSTED|quota)",
    re.IGNORECASE,
)


def _error_status_code(exc: Exception) -> Optional[int]:
    """The HTTP status behind an exception, whichever SDK raised it.

    Providers disagree on where they put it: a bare ``status_code`` (Anthropic,
    Gemini), ``response.status_code`` (requests / httpx), or ``code``.
    """
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value

    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status
    return None


def is_transient_model_error(exc: Exception) -> bool:
    """True only for server-side hiccups worth retrying (e.g. Gemini 500/
    INTERNAL/overloaded). Auth/quota/bad-request are permanent and surface
    immediately so the investigator can act."""
    status = _error_status_code(exc)
    if status is not None:
        return status in _TRANSIENT_STATUSES

    s = str(exc)
    if _PERMANENT_MESSAGE_RE.search(s):
        return False
    return bool(_TRANSIENT_MESSAGE_RE.search(s))


# The model menu's "Connect to <provider>…" rows carry these names rather than a
# real model id. Persisting one literally leaves a name no provider accepts —
# and the switch's connectivity check still passes, because listing models says
# nothing about whether the configured one exists.
_PLACEHOLDER_MODEL_NAMES = {"", "default", "auto", "cli-default-model"}


def is_placeholder_model(model_name: Optional[str]) -> bool:
    """True when ``model_name`` is a stand-in that must be resolved before use."""
    if model_name is None:
        return True
    return str(model_name).strip().lower() in _PLACEHOLDER_MODEL_NAMES
from eye.backends.cloud_api.openai_backend import OpenAIBackend
from eye.backends.cloud_api.anthropic_backend import AnthropicBackend
from eye.backends.cloud_api.gemini_backend import GeminiBackend
from eye.backends.local_server.ollama_backend import OllamaBackend
from eye.backends.local_server.lmstudio_backend import LMStudioBackend
from eye.backends.local_cli.generic_cli_backend import GenericCLIBackend
from eye.backends.local_cli.cli_profiles import get_profile, list_supported_backends


# Backend classes are now imported from their dedicated directories:
# - Cloud API backends: eye/backends/cloud_api/ (OpenAI, Anthropic, Gemini)
# - Local Server backends: eye/backends/local_server/ (Ollama, LM Studio)
# - Local CLI backends: eye/backends/local_cli/ (GenericCLIBackend)


class ModelRouter:
    """
    Central Controller for the EYE AI Assistant's investigative intelligence.
    
    The Router is responsible for:
    1. Instantiating the correct Backend based on user configuration.
    2. Providing a unified generation/discovery interface to the ContextManager.
    3. Ensuring secure model switching without accidentally changing the Agent (Backend).
    """

    # How the active model can call forensic tools. The first two deliberately
    # carry the same strings as eye.services.tool_capability's verdicts, so a
    # verdict and a support level are never two vocabularies for one fact.
    TOOL_SUPPORT_NATIVE = "native"          # real function calling
    TOOL_SUPPORT_TEXT = "text_protocol"     # only the fenced ```tool_call format
    TOOL_SUPPORT_UNKNOWN = "unknown"        # could not be determined — say so

    def __init__(self, config, credential_manager=None):
        self.config = config
        self.credential_manager = credential_manager
        self.logger = logging.getLogger(self.__class__.__name__)
        self.backend = self._initialize_backend()
        # Built on first use and dropped on switch_model — see _capability_probe.
        self._tool_capability_probe = None

    def _initialize_backend(self):
        """
        Factory method to create the appropriate LLM strategy based on connection type.
        """
        bt = self.config.get("backend")
        mn = self.config.get("model_name")
        it = self.config.get("integration_type")
        
        # Validation for required fields - expected by tests
        if not bt:
            raise ValueError("Backend type not specified in configuration")
        if not mn:
            raise ValueError("Model name not specified in configuration")

        try:
            # Force re-inference if there's a clear mismatch to handle stale config after backend changes.
            # Persistent eye_config.json often holds a stale 'integration_type' that doesn't match a new 'backend'.
            if it and ((bt in list_supported_backends() and it != "local_cli") or \
               (bt in ["ollama", "lm_studio", "vllm"] and it not in ["local_server", "local_api"])):
                it = None

            # Infer integration_type if not explicitly provided
            if not it:
                if bt in list_supported_backends():
                    it = "local_cli"
                elif bt in ["ollama", "lm_studio", "vllm"]:
                    it = "local_server"
                else:
                    it = "cloud_api"
                self.config["integration_type"] = it
            
            # --- APPROACH 1: LOCAL CLI BACKENDS ---
            if it == "local_cli" or bt in list_supported_backends():
                profile = get_profile(bt)
                if mn in [None, "", "default", "cli-default-model"]:
                    mn = profile.get("display_name", "CLI Agent")
                    self.config["model_name"] = mn
                
                # Check for executable_path for Ollama/CLI backends if not inferred as server
                if bt == "ollama" and it == "local_cli" and not self.config.get("executable_path"):
                     raise ValueError("Executable path required for Ollama backend")
                     
                return GenericCLIBackend(self.config.get("executable_path", ""), backend_type=bt, model_name=mn)
                
            # --- APPROACH 2: DIRECT LOCAL SERVERS ---
            if it in ["local_server", "local_api"]:
                if bt == "ollama":
                    # Honor a configured server URL (LAN IP / custom port). The
                    # wizard stores it in api_endpoint; executable_path is a legacy
                    # fallback; localhost is the default so existing setups are
                    # unchanged. Passed as api_endpoint= so OllamaBackend takes the
                    # correct branch (positional executable_path was being ignored).
                    endpoint = (self.config.get("api_endpoint")
                                or self.config.get("executable_path")
                                or "http://localhost:11434")
                    return OllamaBackend(mn, api_endpoint=endpoint)
                if bt == "lm_studio": 
                    endpoint = self.config.get("api_endpoint")
                    if not endpoint:
                        raise ValueError("API endpoint required for LM Studio backend")
                    return LMStudioBackend(endpoint, mn)
                if bt == "vllm":
                    endpoint = self.config.get("api_endpoint")
                    if not endpoint:
                        raise ValueError("API endpoint required for vLLM backend")
                    return LMStudioBackend(endpoint, mn)
            
            # --- APPROACH 3: CLOUD API AGENTS ---
            if bt == "openai":
                if not self.credential_manager:
                    raise ValueError("CredentialManager required for OpenAI backend")
                return OpenAIBackend(mn, self.credential_manager)
            if bt == "anthropic": return AnthropicBackend(mn, self.credential_manager)
            if bt == "gemini": return GeminiBackend(mn, self.credential_manager)
            # OpenAI-compatible providers reuse OpenAIBackend with a base_url + their
            # own keyring credential. base_url is overridable via config["api_endpoint"]
            # (e.g. to reach the China endpoint api.moonshot.cn instead of .ai).
            if bt == "deepseek":
                if not self.credential_manager:
                    raise ValueError("CredentialManager required for DeepSeek backend")
                return OpenAIBackend(
                    mn, self.credential_manager,
                    base_url=self.config.get("api_endpoint") or "https://api.deepseek.com",
                    credential_key="deepseek_api_key", provider_label="DeepSeek")
            if bt in ("kimi", "moonshot"):
                if not self.credential_manager:
                    raise ValueError("CredentialManager required for Kimi backend")
                return OpenAIBackend(
                    mn, self.credential_manager,
                    base_url=self.config.get("api_endpoint") or "https://api.moonshot.ai/v1",
                    credential_key="kimi_api_key", provider_label="Kimi (Moonshot)")
            if bt == "openrouter":
                if not self.credential_manager:
                    raise ValueError("CredentialManager required for OpenRouter backend")
                # OpenRouter fans out to every model behind one key. The optional
                # attribution headers are what OpenRouter asks apps to send.
                return OpenAIBackend(
                    mn, self.credential_manager,
                    base_url=self.config.get("api_endpoint") or "https://openrouter.ai/api/v1",
                    credential_key="openrouter_api_key", provider_label="OpenRouter",
                    default_headers={"HTTP-Referer": "https://crow-eye.com", "X-Title": "Crow-Eye"})
            if bt == "nvidia":
                if not self.credential_manager:
                    raise ValueError("CredentialManager required for NVIDIA backend")
                return OpenAIBackend(
                    mn, self.credential_manager,
                    base_url=self.config.get("api_endpoint") or "https://integrate.api.nvidia.com/v1",
                    credential_key="nvidia_api_key", provider_label="NVIDIA")
            if bt == "groq":
                if not self.credential_manager:
                    raise ValueError("CredentialManager required for Groq backend")
                return OpenAIBackend(
                    mn, self.credential_manager,
                    base_url=self.config.get("api_endpoint") or "https://api.groq.com/openai/v1",
                    credential_key="groq_api_key", provider_label="Groq")
            if bt == "mistral":
                if not self.credential_manager:
                    raise ValueError("CredentialManager required for Mistral backend")
                return OpenAIBackend(
                    mn, self.credential_manager,
                    base_url=self.config.get("api_endpoint") or "https://api.mistral.ai/v1",
                    credential_key="mistral_api_key", provider_label="Mistral")
            if bt in ("xai", "grok"):
                if not self.credential_manager:
                    raise ValueError("CredentialManager required for xAI backend")
                return OpenAIBackend(
                    mn, self.credential_manager,
                    base_url=self.config.get("api_endpoint") or "https://api.x.ai/v1",
                    credential_key="xai_api_key", provider_label="xAI (Grok)")

            raise ValueError(f"Unsupported forensic AI backend: {bt} (Type: {it})")
            
        except ValueError:
            # Re-raise ValueErrors as-is (expected by tests)
            raise
        except Exception as e:
            self.logger.error(f"Failed to initialize backend {bt}: {e}", exc_info=True)
            if "ModuleNotFoundError" in str(e) or "ImportError" in str(e):
                raise RuntimeError(f"EYE Assistant is missing a required dependency for the '{bt}' agent. Please check the 'Diagnostics' tool in the setup wizard. Error: {str(e)}")
            raise RuntimeError(f"EYE Assistant could not initialize the '{bt}' agent. Details: {str(e)}")

    def generate(self, system_prompt, user_message, tools=None, history=None, on_retry=None,
                 gen_params=None, _bypass_capability_gate=False):
        """Delegate to the active backend with transient-error retry + backoff.

        Gemini (and others) intermittently return 500/INTERNAL/UNAVAILABLE under
        load or on large requests. We retry transient failures up to
        ``reasoning.model_retry_max_attempts`` (default 3) with exponential
        backoff (1s, 2s, 4s, capped) so a transient 500 doesn't surface to the
        investigator. Non-transient failures (auth/quota/bad-request) raise
        immediately. ``on_retry(attempt, exc)`` lets the caller log/seal each
        retry for the Compliance trail. This is the single choke point for every
        model call, so map-reduce and history-summarization get resilience too.

        ``gen_params`` (optional dict, e.g. ``{"temperature": 0.2,
        "max_output_tokens": 8192}``) is forwarded to the backend so callers can
        tune determinism per phase (planning vs answer). Backends that don't
        support a given knob ignore it; ``None`` keeps each backend's defaults.

        ``_bypass_capability_gate`` is for the capability probe itself, which has
        to send a tools payload to a model precisely to find out whether it can
        accept one. Nothing else should set it.
        """
        # CAPABILITY GATE. Sending a tools payload to a model that rejects it is
        # what produced the recurring Gemma 500 INTERNAL — an opaque server error
        # mid-investigation, with nothing pointing at the real cause.
        #
        # Only an ACTIONABLE verdict (confirmed by a live probe, or a known
        # family) may strip the payload. A merely ASSUMED verdict must never
        # change the request: guessing wrong here would silently disable native
        # tools on a model that supports them, which is the worse failure — it
        # degrades every answer instead of producing one loud error.
        if tools and not _bypass_capability_gate:
            try:
                from eye.services import tool_capability as tc
                verdict = self.get_tool_capability()
                if tc.is_actionable(verdict) and verdict.get("support") != tc.NATIVE:
                    self.logger.info(
                        "Tool payload withheld: %s (%s). Tools go through the text protocol.",
                        verdict.get("support"), tc.describe(verdict))
                    tools = None
            except Exception as e:
                self.logger.debug(f"Capability gate skipped: {e}")

        try:
            attempts = int((self.config.get("reasoning") or {}).get("model_retry_max_attempts", 3))
        except (TypeError, ValueError, AttributeError):
            attempts = 3
        attempts = max(1, min(attempts, 6))

        last_exc = None
        for attempt in range(1, attempts + 1):
            try:
                return self.backend.generate(system_prompt, user_message, tools, history, gen_params=gen_params)
            except Exception as exc:
                last_exc = exc
                if attempt >= attempts or not is_transient_model_error(exc):
                    raise
                if on_retry:
                    try:
                        on_retry(attempt, exc)
                    except Exception:
                        pass
                self.logger.warning(
                    f"Transient model error (attempt {attempt}/{attempts}), retrying: {exc}"
                )
                time.sleep(min(2 ** (attempt - 1), 8))
        if last_exc:  # pragma: no cover - loop always returns or raises above
            raise last_exc

    def validate_connectivity(self):
        """
        Checks if the currently active agent is online.
        """
        try:
            is_connected = self.backend.validate_connectivity()
        except Exception as e:
            self.logger.error(f"Connectivity validation failed: {str(e)}")
            return False

        integration_type = self.config.get("integration_type", "cloud_api")
        
        # --- APPROACH: LOCAL CLI AGENTS ---
        if integration_type == "local_cli":
            mn = self.config.get("model_name", "")
            is_generic = mn in [None, "", "default", "cli-default-model"] or "CLI Agent" in str(mn)
            
            if is_connected and is_generic and hasattr(self.backend, "list_models"):
                discovered = self.backend.list_models()
                if discovered and len(discovered) > 0:
                    target = discovered[0]
                    self.logger.info(f"Local CLI Approach: Auto-connecting to discovered model: {target}")
                    self.switch_model(target)
        
        return is_connected

    def list_models(self):
        """Lists valid model options for the currently active agent."""
        return self.backend.list_models()

    def get_context_window(self) -> Optional[int]:
        """Report the active backend model's real context window (tokens), or None.

        Delegates to the active backend's ``get_context_window`` (Gemini /
        Ollama / LM Studio self-report; others return None so the caller falls
        back to the static registry). Best-effort: never raises.
        """
        try:
            return self.backend.get_context_window()
        except Exception as e:
            self.logger.debug(f"get_context_window failed: {e}")
            return None

    def _capability_probe(self):
        """The ToolCapabilityProbe bound to this router, built on first use.

        Held on the router rather than constructed per call so the on-disk
        verdict cache is read once, and so ``switch_model`` has a single thing to
        invalidate. Imported lazily: ``tool_capability`` reaches back into the
        router, and importing it at module scope would close that loop.
        """
        probe = getattr(self, "_tool_capability_probe", None)
        if probe is None:
            from eye.services.tool_capability import ToolCapabilityProbe
            probe = ToolCapabilityProbe(self)
            self._tool_capability_probe = probe
        return probe

    def get_tool_capability(self, use_cache: bool = True) -> Dict[str, Any]:
        """Can the active model call forensic tools, and how do we know?

        Cheap rungs only — cache, provider metadata, family registry, then an
        optimistic default. Issues no model call, so this is safe on the GUI
        thread. Returns the verdict dict described in
        ``eye.services.tool_capability`` (``support`` / ``confidence`` /
        ``source`` / ``evidence``).

        Never raises. An undetermined capability must not stop an investigation,
        and the fallback is ASSUMED confidence, which the gate below ignores —
        so a detection failure can never disable tools on a model that has them.
        """
        try:
            return self._capability_probe().resolve(use_cache=use_cache)
        except Exception as e:
            self.logger.debug(f"Tool-capability resolve failed: {e}")
            from eye.services import tool_capability as tc
            return tc._verdict(
                tc.NATIVE, tc.ASSUMED, tc.SRC_DEFAULT,
                f"capability detection unavailable ({e}); assuming native function calling",
                self.config.get("backend") or "", self.config.get("model_name") or "")

    def probe_tool_capability(self, force: bool = False) -> Dict[str, Any]:
        """The full ladder, including live probes against the model.

        Costs up to two small model calls (~150 tokens each), so OFF-THREAD
        CALLERS ONLY — the Settings panel's "Re-test" button runs it in a worker.
        Unlike :meth:`get_tool_capability` this propagates, because a person
        asked for the test and is waiting to be told whether it worked.
        """
        return self._capability_probe().probe(force=force)

    def get_tool_support(self) -> str:
        """How the active model can call tools, as a plain string for callers
        that only branch on it (the system-prompt builder, the settings panel).

        A backend may declare ``tool_support`` itself — it knows things the
        ladder cannot, such as an endpoint that strips the tools payload. That
        declaration wins. Otherwise the capability ladder answers.

        Returns ``TOOL_SUPPORT_UNKNOWN`` if anything at all goes wrong, which is
        an honest "we could not determine this" rather than a guess presented as
        fact — the investigator sees the difference in Settings.
        """
        try:
            declared = getattr(self.backend, "tool_support", None)
            if declared:
                return declared

            from eye.services import tool_capability as tc
            support = (self.get_tool_capability() or {}).get("support")
            if support == tc.NATIVE:
                return self.TOOL_SUPPORT_NATIVE
            if support in (tc.TEXT_PROTOCOL, tc.NONE):
                return self.TOOL_SUPPORT_TEXT
            return self.TOOL_SUPPORT_UNKNOWN
        except Exception as e:
            self.logger.debug(f"Tool-support probe failed: {e}")
            return self.TOOL_SUPPORT_UNKNOWN

    def get_tool_support_warning(self) -> Optional[str]:
        """One sentence for the investigator when the active model is degraded,
        or ``None`` when it can function-call normally.

        Shown BEFORE an investigation starts. Finding out mid-query that the
        model cannot run forensic tools is finding out too late.
        """
        try:
            if self.get_tool_support() == self.TOOL_SUPPORT_NATIVE:
                return None
            model = self.config.get("model_name") or "The active model"
            return (f"{model} does not support native function calling — the Eye will run "
                    f"forensic tools through the text tool-call protocol instead. Results are "
                    f"the same, but tool calls are less reliable than with a native model.")
        except Exception as e:
            self.logger.debug(f"Tool-support warning failed: {e}")
            return None

    def get_models_with_quota(self):
        """
        Retrieves real-time usage stats and available models for the active session.
        """
        try:
            models = self.backend.get_models_with_quota()
            
            # If the list is empty (common for newly initialized CLI agents), 
            # we force a connectivity check to trigger the discovery logic.
            if not models:
                self.logger.info("Model list empty, triggering discovery approach...")
                self.validate_connectivity()
                models = self.backend.get_models_with_quota()
                
            return models
        except Exception as e:
            self.logger.error(f"Error retrieving models with quota: {e}")
            return []

    def get_grouped_backend_options(self, live: bool = False) -> Dict[str, List[Dict[str, Any]]]:
        """
        Aggregates available models from all configured backends into a
        grouped structure for the UI model menu.

        ``live=False`` (default) is a FAST, purely in-memory build safe to call on
        the GUI thread: the active backend's model list comes from the backend's
        cache (falling back to the curated catalog), and other providers' "Connect
        to…" discovery entries are decided from the credential manager's in-memory
        cache — NO network round-trips and NO OS-keychain reads. ``live=True`` does
        the authoritative refresh (live ``list_models()`` + real credential probes)
        and is meant to run on a background thread.
        """
        from eye.services.context_window_registry import curated_models

        groups = {
            "Cloud API": [],
            "Local Server": [],
            "Local CLI": []
        }

        active_bt = self.config.get("backend")
        # Dedup (backend, model_name) so a curated entry never duplicates a live one.
        seen = set()

        def add_opt(category, backend, model_name, label=None):
            key = (backend, model_name)
            if key in seen:
                return
            seen.add(key)
            active_mn = self.config.get("model_name")
            is_active = (backend == active_bt and model_name == active_mn)
            groups[category].append({
                "backend": backend,
                "model_name": model_name,
                "label": label or model_name,
                "is_active": is_active
            })

        # 1. Models from the CURRENT active backend. Live path hits the provider;
        # fast path reuses the backend's cached list (populated on the initial
        # connection / any prior live refresh) so opening the menu never blocks.
        try:
            if live:
                active_models = self.list_models()
            else:
                active_models = list(getattr(self.backend, "_model_cache", None) or [])

            # Map current backend to category
            category = "Cloud API"
            if active_bt in ["ollama", "lm_studio", "vllm"]:
                category = "Local Server"
            elif active_bt in list_supported_backends():
                category = "Local CLI"

            for m in active_models:
                add_opt(category, active_bt, m)
        except Exception as e:
            self.logger.error(f"Error listing active models: {e}")

        # 1b. Merge the curated catalog for the active backend (cloud only) so
        # current models are offered even if a live fetch returned nothing.
        for m in curated_models(active_bt):
            add_opt("Cloud API", active_bt, m)

        # 2. Add 'Discovery' options for other cloud backends if they have keys
        cloud_providers = [
            ("openrouter", "OpenRouter"),
            ("gemini", "Gemini (Google AI Studio)"),
            ("nvidia", "NVIDIA"),
            ("openai", "OpenAI"),
            ("anthropic", "Anthropic"),
            ("deepseek", "DeepSeek"),
            ("kimi", "Kimi (Moonshot)"),
            ("groq", "Groq"),
            ("mistral", "Mistral"),
            ("xai", "xAI (Grok)"),
        ]

        for bt, label in cloud_providers:
            if bt == active_bt: continue

            # If we have a key, show a discovery option. Fast path uses the
            # in-memory credential cache (no OS-keychain read per provider — that
            # was up to ~10 blocking keychain lookups every time the menu opened);
            # the live refresh does the authoritative probe.
            key_name = f"{bt}_api_key"
            if self.credential_manager:
                has_key = (self.credential_manager.get_credential(key_name) if live
                           else self.credential_manager.has_cached_credential(key_name))
                if has_key:
                    add_opt("Cloud API", bt, "default", f"Connect to {label}...")

            # Always surface the curated models for the provider so current
            # Claude models are selectable in the menu (selecting one switches
            # the backend; the user is prompted for a key if none is stored).
            for m in curated_models(bt):
                add_opt("Cloud API", bt, m)

        # 3. Add Local Server options if not active
        local_servers = [
            ("ollama", "Ollama"),
            ("lm_studio", "LM Studio"),
            ("vllm", "vLLM")
        ]
        for bt, label in local_servers:
            if bt == self.config.get("backend"): continue
            add_opt("Local Server", bt, "default", f"Connect to {label}...")
            
        return groups

    def _resolve_placeholder_model(self, target_model: str) -> str:
        """Turn a placeholder model name into an id the provider will accept.

        Deliberately NOT ``list_models()[0]``. A provider's catalogue includes
        ids that 404 on generate — Gemini lists ``gemini-2.5-flash-lite`` and
        then rejects it as no longer available to new users — so the pick is the
        intersection of what is live AND what we curate as recommended. Only if
        that is empty do we fall back to any live model, then to the curated list
        (for a provider whose listing is down or whose key is not set yet).

        Raises ValueError when nothing resolves, so the bridge reverts the switch
        and tells the investigator rather than leaving an unusable model behind.
        """
        bt = self.config.get("backend")

        # A CLI agent runs its own default when no model is given; resolving one
        # for it would override a deliberate choice.
        if self.config.get("integration_type") == "local_cli" or bt in list_supported_backends():
            return target_model

        try:
            live = list(self.backend.list_models() or [])
        except Exception as e:
            self.logger.debug(f"Could not list models while resolving '{target_model}': {e}")
            live = []

        from eye.services.context_window_registry import recommended_models
        recommended = list(recommended_models(bt) or [])

        for candidate in recommended:
            if candidate in live:
                self.logger.info(f"Resolved placeholder model to recommended+live '{candidate}'")
                return candidate

        for candidate in live:
            if not is_placeholder_model(candidate):
                self.logger.info(f"Resolved placeholder model to live '{candidate}'")
                return candidate

        if recommended:
            self.logger.info(f"Resolved placeholder model to curated '{recommended[0]}' "
                             f"(no live catalogue available)")
            return recommended[0]

        raise ValueError(
            f"Could not determine a model to use for '{bt}'. The provider returned no models "
            f"and Crow-Eye has no recommended list for it — choose a model explicitly.")

    def switch_model(self, model_name: str, backend: Optional[str] = None):
        """
        Updates the active model and optionally switches the backend provider.
        """
        old_bt = self.config.get("backend")
        target_model = model_name.strip()

        if backend and backend != old_bt:
            self.logger.info(f"Switching backend from {old_bt} to {backend}")
            self.config["backend"] = backend
            # Reset integration_type to trigger re-inference in _initialize_backend
            self.config["integration_type"] = None

        # A "Connect to <provider>…" row carries a placeholder, not a model id.
        # Resolve it to something the provider will actually accept, BEFORE it is
        # persisted — otherwise the switch appears to succeed (connectivity only
        # lists models) and every later request 404s.
        if is_placeholder_model(target_model):
            target_model = self._resolve_placeholder_model(target_model)

        # Update model_name for the next initialization
        self.config["model_name"] = target_model

        # Re-initialize the specific backend strategy
        self.backend = self._initialize_backend()

        # Drop the capability probe. It closes over the OLD backend (the Gemini
        # rung asks it directly), and its verdict is per backend+model — keeping
        # it would report the previous model's tool support for the new one. The
        # on-disk cache survives, so re-resolving is free for a model already seen.
        self._tool_capability_probe = None

        self.logger.info(f"Forensic Agent switched to {self.config.get('backend')}:{target_model}")
