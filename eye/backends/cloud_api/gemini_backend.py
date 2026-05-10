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
                
            self._client = genai.Client(api_key=api_key)
        return self._client

    def generate(self, system_prompt, user_message, tools=None, history=None):
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
            # Build the configuration - this tells Gemini how to behave
            config = {"temperature": 0.7, "max_output_tokens": 4096, "system_instruction": system_prompt}
            
            if tools:
                # Convert Eye's tool format to Gemini's function_declarations format
                # We're teaching Gemini what forensic capabilities are available
                decls = [{"name": t["name"], "description": t.get("description", ""), "parameters": t.get("parameters", {})} for t in tools]
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
            # which _sanitize_messages may preserve as the first item)
            contents = []
            for msg in sanitized:
                if msg["role"] == "system":
                    # Merge any remaining system content into final_system
                    extra = msg.get("content", "").strip()
                    if extra and extra != system_prompt:
                        final_system += "\n\n" + extra
                else:
                    contents.append({
                        "role": "user" if msg["role"] == "user" else "model",
                        "parts": [{"text": msg["content"]}]
                    })

            # Guard: Gemini raises InvalidArgument if contents is empty.
            # This can happen when history is None/empty and all messages were stripped.
            if not contents:
                contents = [{"role": "user", "parts": [{"text": user_message}]}]

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
            return {"content": content, "tool_calls": tool_calls}
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
        
        We ask Google what models are available (like checking a menu). We only show
        models that support "generateContent" (text generation) - no point showing
        embedding models or other non-chat models.
        
        The model list is cached so Eye can still show options even if you go offline.
        """
        try:
            # Detect models using both modern (supported_generation_methods) and legacy (supported_actions) properties
            # This ensures compatibility across different versions of the Google GenAI SDKs
            models = []
            for m in self.client.models.list():
                # Check for modern SDK property
                methods = getattr(m, "supported_generation_methods", []) or []
                # Check for legacy SDK property
                actions = getattr(m, "supported_actions", []) or []
                
                # If either contains "generateContent", it's a chat-capable model
                if "generateContent" in methods or "generateContent" in actions:
                    models.append(m.name.replace("models/", ""))
            
            if models: self._model_cache = models  # Cache for offline use
            return models
        except Exception as e: 
            self.logger.error(f"Failed to list Cloud models: {e}")
            return self._model_cache if self._model_cache else []

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
