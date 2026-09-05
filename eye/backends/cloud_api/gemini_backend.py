"""
Gemini Backend: Talking to Google's AI in the Cloud

This backend connects to Google's Gemini AI service using their official Python SDK.
It's the "phone call" approach - we send our forensic questions over the internet to
Google's servers and get smart answers back.

How it works:
1. We package up the system prompt, chat history, and tools into a structured request
2. The Google GenAI SDK sends it over HTTPS to their servers
3. Gemini thinks about it and sends back a response (text + maybe tool calls)
4. If Gemini wants to use a forensic tool, it tells us in a structured format

What makes Gemini special:
- Native function calling: Gemini can directly invoke our forensic tools (query_database,
  search_artifacts, etc.) without needing XML tags or text parsing
- Flexible tool format: We send tools as JSON Schema and get back structured tool calls
- Model discovery: We can ask Google what models are available and pick the best one
- Caching: We remember the model list so Eye can work offline if needed

This is great for: Deep forensic analysis where you need Google's most powerful models
and don't mind sending data to the cloud. Gemini excels at understanding complex
forensic artifacts and correlating evidence across multiple sources.

Technical details:
- Uses the modern google-genai SDK (not the older google.generativeai)
- Lazy-loads the client (only connects when you actually need it)
- Caches model lists for offline resilience
- Formats tools using Gemini's function_declarations structure
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
import logging
import json

from eye.backends.base import LLMBackend


class GeminiBackend(LLMBackend):
    """
    Official Google Gemini Cloud Backend.
    Uses the modern google-genai SDK for native function calling and tool execution.
    """
    def __init__(self, model_name: str, credential_manager):
        self.model_name = model_name
        self.credential_manager = credential_manager
        self.logger = logging.getLogger(self.__class__.__name__)
        self.quota_stats = "API Managed"
        self._client = None
        self._model_cache = []

    @property
    def client(self):
        """
        Lazy-loaded Google GenAI client.
        
        We don't connect to Google until you actually need it - this saves time during
        startup and prevents unnecessary API calls. The client is created once and
        reused for all subsequent requests.
        """
        if self._client is None:
            try:
                from google import genai
            except ImportError as e:
                self.logger.error(f"Critical: Failed to import 'google-genai' SDK. "
                                 f"Ensure it is installed in the virtual environment: {e}")
                raise ImportError("The 'google-genai' SDK is missing or broken. "
                                 "Please run 'pip install google-genai' in the Crow-Eye venv.") from e
            except Exception as e:
                self.logger.error(f"Unexpected error importing 'google-genai': {e}")
                raise

            api_key = self.credential_manager.get_credential("gemini_api_key")
            if not api_key:
                raise ValueError("Gemini API key not found. Please configure it in the Setup Wizard.")

            # Apply an explicit request timeout (ms) so a hung provider cannot
            # freeze the worker thread (parity with the other backends). Done
            # defensively: older google-genai signatures that don't accept
            # http_options fall back to the default client.
            try:
                self._client = genai.Client(
                    api_key=api_key,
                    http_options={"timeout": 120000},
                )
            except Exception as http_exc:
                self.logger.debug(f"Gemini http_options timeout unsupported; using default client: {http_exc}")
                self._client = genai.Client(api_key=api_key)
        return self._client

    # Keywords the Gemini function-calling schema (an OpenAPI 3.0 subset) does
    # NOT accept. Sending them yields 400 INVALID_ARGUMENT or, worse, a generic
    # 500 INTERNAL. They are valid JSON-Schema for the OpenAI/Anthropic backends,
    # so we strip them here (Gemini-only) rather than in configs/llm_config.json.
    _GEMINI_UNSUPPORTED_SCHEMA_KEYS = frozenset({
        "default", "additionalProperties", "$schema", "$id", "$ref", "$defs",
        "definitions", "title", "examples", "const", "patternProperties",
    })

    # Name fragments marking a model the Eye cannot hold a forensic conversation
    # with. `models.list()` returns the account's WHOLE catalogue — image, music,
    # audio, live-translate, robotics and research agents included — and every one
    # of those used to appear in the model menu as a selectable chat model.
    # Verified against a live account: lyria-3-* (music), nano-banana-* and
    # *-image (image generation), *native-audio*, *-live-*, *robotics*,
    # deep-research-*, computer-use and antigravity were all being offered.
    _NON_CHAT_MODEL_TAGS = (
        "embedding", "aqa", "imagen", "veo", "-tts", "image-generation",
        "-image", "nano-banana", "lyria",
        "native-audio", "-live-", "live-translate",
        "robotics", "computer-use", "deep-research", "antigravity",
    )

    def _is_gemma(self) -> bool:
        """Gemma models on the Gemini API support NEITHER system instructions NOR
        function calling. Detect them so we can build a request the server accepts
        (fold the system prompt into the first user turn; omit tools)."""
        name = (self.model_name or "").replace("models/", "").lower()
        return name.startswith("gemma")

    def _sanitize_gemini_schema(self, node):
        """Return a copy of a JSON-schema node with Gemini-unsupported keywords
        removed, recursing into ``properties`` and ``items``. Pure / non-mutating."""
        if isinstance(node, list):
            return [self._sanitize_gemini_schema(n) for n in node]
        if not isinstance(node, dict):
            return node
        clean = {}
        for k, v in node.items():
            if k in self._GEMINI_UNSUPPORTED_SCHEMA_KEYS:
                continue
            if k == "properties" and isinstance(v, dict):
                clean[k] = {pk: self._sanitize_gemini_schema(pv) for pk, pv in v.items()}
            elif k in ("items", "if", "then", "else"):
                clean[k] = self._sanitize_gemini_schema(v)
            elif k in ("anyOf", "oneOf", "allOf") and isinstance(v, list):
                clean[k] = [self._sanitize_gemini_schema(n) for n in v]
            else:
                clean[k] = v
        return clean

    def generate(self, system_prompt, user_message, tools=None, history=None, gen_params=None):
        """
        Translates EYE forensic state into Gemini's contents/config structure.
        
        This method takes Eye's standard format (system prompt, user message, tools, history)
        and converts it into the specific format that Gemini expects. It's like translating
        from Eye's language into Gemini's language.
        
        Args:
            system_prompt: The forensic assistant's personality and instructions
            user_message: The investigator's current question
            tools: List of forensic tools (query_database, search_artifacts, etc.)
            history: Previous conversation messages for context
            
        Returns:
            Dictionary with 'content' (Gemini's text response) and 'tool_calls' (any tools
            Gemini wants to invoke, formatted as structured objects)
        """
        try:
            # Build the configuration - this tells Gemini how to behave.
            # max_output_tokens bounds the REPLY (not the context window); 4096
            # silently clipped long forensic syntheses, so default to 8192 and
            # surface a marker when the model still hits the cap (see below).
            gp = gen_params or {}
            gemma = self._is_gemma()
            config = {
                "temperature": gp.get("temperature", 0.7),
                "max_output_tokens": gp.get("max_output_tokens", 8192),
            }
            if gp.get("top_p") is not None:
                config["top_p"] = gp["top_p"]

            # Gemma models on the Gemini API do NOT support function calling — sending
            # `tools` is a primary cause of the recurring 500 INTERNAL. Only attach
            # tools for non-Gemma models, and sanitize each schema to Gemini's subset.
            # True when the orchestrator asked for tools but this model can't use them,
            # so they were dropped. The orchestrator reads this to tell the investigator
            # the model can't run forensic tools (instead of silently looping on a model
            # that physically cannot emit a tool call).
            tools_unsupported = bool(tools and gemma)
            if tools_unsupported:
                self.logger.warning(
                    "Active Gemma model '%s' does not support function calling — %d tool(s) "
                    "were dropped; it cannot execute forensic tools this turn.",
                    self.model_name or "", len(tools or []),
                )
            if tools and not gemma:
                decls = [{
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": self._sanitize_gemini_schema(t.get("parameters", {})),
                } for t in tools]
                config["tools"] = [{"function_declarations": decls}]
            
            # Build the raw messages array
            raw_messages = []
            if history:
                for msg in history:
                    raw_messages.append({
                        "role": msg.get("role", "user"), 
                        "content": msg.get("content", "")
                    })
            raw_messages.append({"role": "user", "content": user_message})
            
            # Extract and collect all system-role messages from raw history BEFORE sanitization.
            # The base _sanitize_messages converts system→user, so we must grab them first.
            extra_system_parts = []
            for msg in (history or []):
                if msg.get("role") == "system":
                    extra = msg.get("content", "").strip()
                    if extra and extra != system_prompt:
                        extra_system_parts.append(extra)

            # Sanitize the remaining (non-system) messages for strict role alternation
            sanitized = self._sanitize_messages(raw_messages)

            # Build the final system instruction (base prompt + any system history messages)
            final_system = system_prompt
            if extra_system_parts:
                final_system += "\n\n" + "\n\n".join(extra_system_parts)

            # Convert sanitized messages to Gemini's contents format (skip system role,
            # which _sanitize_messages may preserve as the first item).
            # Empty-part guard: Gemini can 500 on parts:[{"text": ""}], so skip any
            # message whose text is empty.
            contents = []
            for msg in sanitized:
                if msg["role"] == "system":
                    # Merge any remaining system content into final_system
                    extra = msg.get("content", "").strip()
                    if extra and extra != system_prompt:
                        final_system += "\n\n" + extra
                else:
                    text = msg.get("content", "")
                    if not text.strip():
                        continue
                    contents.append({
                        "role": "user" if msg["role"] == "user" else "model",
                        "parts": [{"text": text}]
                    })

            # Guard: Gemini raises InvalidArgument if contents is empty.
            # This can happen when history is None/empty and all messages were stripped.
            if not contents:
                contents = [{"role": "user", "parts": [{"text": user_message or final_system}]}]

            if gemma:
                # Gemma does NOT support `system_instruction`. Fold the system prompt
                # into the FIRST user turn instead (contents always start with a user
                # role after _sanitize_messages), and leave system_instruction unset.
                if final_system.strip():
                    first = contents[0]
                    if first.get("role") != "user":
                        contents.insert(0, {"role": "user", "parts": [{"text": final_system}]})
                    else:
                        existing = (first["parts"][0].get("text", "") if first.get("parts") else "")
                        first["parts"] = [{"text": f"{final_system}\n\n{existing}".strip()}]
            else:
                # Update config with the fully merged system instruction
                config["system_instruction"] = final_system

            # Send the request to Gemini and get the response
            resp = self.client.models.generate_content(model=self.model_name, contents=contents, config=config)
            
            # Safely extract text — the SDK raises ValueError when the response contains
            # only function calls and no text part. We guard against that here.
            try:
                content = resp.text or ""
            except Exception as text_err:
                # This is expected when Gemini returns pure tool calls with no text
                self.logger.debug(f"resp.text unavailable (likely pure function-call response): {text_err}")
                content = ""
            
            tool_calls = []
            
            # Extract function calls from response parts
            # If Gemini wants to use a forensic tool, it returns structured function_calls
            if hasattr(resp, 'function_calls') and resp.function_calls:
                for fc in resp.function_calls:
                    # Convert Gemini's function call format to Eye's standard format
                    args = fc.args
                    if not isinstance(args, dict):
                        # Some Gemini responses use Pydantic models - convert to dict
                        args = args.model_dump() if hasattr(args, 'model_dump') else {}
                    tool_calls.append({
                        "id": f"c_{id(fc)}", "type": "function",
                        "function": {"name": fc.name, "arguments": json.dumps(args)}
                    })
            # Surface an output-length cut instead of letting it be silent.
            try:
                finish = getattr((resp.candidates or [None])[0], "finish_reason", None)
                if finish is not None and "MAX_TOKENS" in str(finish).upper() and content:
                    content += "\n\n[⚠ Output truncated at the model's max output tokens — ask for the remainder or narrow the request.]"
            except Exception:
                pass
            return {"content": content, "tool_calls": tool_calls,
                    "tools_unsupported": tools_unsupported}
        except Exception as e:
            self.logger.error(f"Cloud (Gemini) error: {e}")
            raise

    def validate_connectivity(self):
        """
        Checks if the Gemini API is reachable and key is valid.
        
        This is like pinging Google's servers to see if they're home. We try to list
        models - if that works, we know the API key is valid and the service is up.
        """
        try:
            self.client.models.list()
            return True
        except Exception as e:
            self.logger.error(f"Gemini connectivity check failed: {e}")
            return False

    def list_models(self):
        """
        Discovers available Google models and caches them for offline recovery.
        
        We ask Google what models are available. We include models that support 
        text generation (generateContent, generateMessage, etc.)
        """
        try:
            models = []
            # Iterate through the available models from the Google GenAI API
            for m in self.client.models.list():
                # Extract identifiers and capabilities. The MODERN google-genai SDK
                # exposes capabilities on `supported_actions`; the legacy SDK used
                # `supported_generation_methods`. Older code only checked the legacy
                # field, so with the modern SDK every model was filtered out and a
                # VALID key looked broken ("No supported models were found"). Read
                # both, and — when neither is populated (common on the modern SDK) —
                # be permissive: include the model and only exclude the obvious
                # non-chat families (embeddings / AQA / imagen / veo) by name.
                m_name = getattr(m, "name", "") or ""
                methods = getattr(m, "supported_generation_methods", None) or []
                actions = getattr(m, "supported_actions", None) or []
                caps = set(methods) | set(actions)
                generative = {"generateContent", "generateMessage", "generateText",
                              "chat", "bidiGenerateContent"}
                clean_name = m_name.replace("models/", "")
                low = clean_name.lower()
                non_chat = any(tag in low for tag in self._NON_CHAT_MODEL_TAGS)
                is_chat = (bool(caps & generative) or not caps) and not non_chat

                if is_chat and clean_name and clean_name not in models:
                    models.append(clean_name)

            if models:
                self._model_cache = models
                self.logger.info(f"Discovered {len(models)} Gemini models via Google GenAI API.")
            else:
                self.logger.warning("Gemini API returned no chat-capable models. Check API key permissions.")

            return models
        except Exception as e: 
            self.logger.error(f"Failed to list Cloud (Gemini) models: {e}")
            return self._model_cache if self._model_cache else []

    def get_context_window(self) -> Optional[int]:
        """Report the active model's real context window via Gemini's
        ``input_token_limit`` (e.g. 1,048,576 for 1.5 Flash, 2,097,152 for Pro).

        Best-effort: returns None on any failure so the caller falls back to the
        registry / default. Cached per instance after the first successful read.
        """
        if getattr(self, "_context_window_cache", None):
            return self._context_window_cache
        try:
            target = (self.model_name or "").replace("models/", "").lower()
            for m in self.client.models.list():
                name = (getattr(m, "name", "") or "").replace("models/", "").lower()
                if name == target:
                    limit = getattr(m, "input_token_limit", None)
                    if limit:
                        self._context_window_cache = int(limit)
                        self.logger.info(f"Gemini reported context window {self._context_window_cache:,} for {target}")
                        return self._context_window_cache
                    break
        except Exception as e:
            self.logger.debug(f"Gemini context-window lookup failed: {e}")
        return None

    def get_models_with_quota(self):
        """
        Returns available models with quota information.
        
        For Gemini, quota is managed by Google's API system. We show "API Managed" for
        the current model and "Unlimited (Discovery Mode)" for others since we don't
        have detailed quota info until you actually use a model.
        """
        models = self.list_models()
        return [{"id": m, "quota": self.quota_stats if m == self.model_name else "Unlimited (Discovery Mode)"} for m in models]


# Backward compatibility alias - old code might import CloudBackend
# This lets existing code keep working without changes
CloudBackend = GeminiBackend
