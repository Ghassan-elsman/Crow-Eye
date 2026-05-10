"""
OpenAI Backend: Talking to GPT in the Cloud

This backend connects to OpenAI's servers (like ChatGPT) using their official Python SDK.
It's the "phone call" approach - we send our forensic questions over the internet and 
get smart answers back.

How it works:
1. We package up the system prompt, chat history, and tools into a JSON request
2. The OpenAI SDK sends it over HTTPS to their servers
3. Their AI thinks about it and sends back a response (text + maybe tool calls)
4. We also grab the rate limit info from HTTP headers so you know how many requests you have left

This is great for: Deep analysis where you need the most powerful models and don't mind 
sending data to the cloud.
"""

from typing import Dict, List, Any, Optional
import logging
import json

from eye.backends.base import LLMBackend


class OpenAIBackend(LLMBackend):
    """
    Official OpenAI Cloud Backend.
    Includes real-time quota tracking via HTTP header inspection.
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
        """Lazy-loaded OpenAI client."""
        if self._client is None:
            try:
                import openai
            except ImportError as e:
                self.logger.error(f"Critical: Failed to import 'openai' SDK: {e}")
                raise ImportError("The 'openai' SDK is missing. "
                                 "Please run 'pip install openai' in the Crow-Eye venv.") from e
            
            api_key = self.credential_manager.get_credential("openai_api_key")
            if not api_key:
                raise ValueError("OpenAI API key not found. Please configure it in the Setup Wizard.")
                
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def generate(self, system_prompt, user_message, tools=None, history=None):
        """Performs generation and captures rate-limit headers for UI feedback."""
        try:
            # Build the raw messages array (system + history + user)
            raw_messages = [{"role": "system", "content": system_prompt}]
            if history:
                for msg in history:
                    raw_messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
            raw_messages.append({"role": "user", "content": user_message})
            
            # Sanitize messages to ensure alternating user/assistant roles
            # This prevents 400 errors in strict local/cloud model templates
            messages = self._sanitize_messages(raw_messages)
            
            params = {"model": self.model_name, "messages": messages}
            if tools:
                # Format tools to strict OpenAI specification: {"type": "function", "function": {...}}
                formatted_tools = []
                for tool in tools:
                    if "type" in tool and tool["type"] == "function" and "function" in tool:
                        formatted_tools.append(tool)
                    else:
                        formatted_tools.append({
                            "type": "function",
                            "function": tool
                        })
                params["tools"] = formatted_tools
            
            # Using with_raw_response to access rate-limit headers
            resp_raw = self.client.chat.completions.with_raw_response.create(**params)
            
            # Extract Quota Telemetry
            if hasattr(resp_raw, 'headers'):
                rem = resp_raw.headers.get("x-ratelimit-remaining-requests")
                reset = resp_raw.headers.get("x-ratelimit-reset-requests")
                if rem:
                    self.quota_stats = f"{rem} requests remaining"
                    if reset: self.quota_stats += f" (resets in {reset})"

            msg = resp_raw.parse().choices[0].message
            tool_calls = []
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_calls.append({
                        "id": tc.id, "type": "function", 
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                    })
            return {"content": msg.content or "", "tool_calls": tool_calls}
        except Exception as e:
            self.logger.error(f"OpenAI API failure: {e}")
            raise

    def validate_connectivity(self):
        """Checks if the API key is valid and service is reachable."""
        try:
            self.client.models.list()
            return True
        except Exception as e:
            self.logger.error(f"OpenAI connectivity check failed: {e}")
            return False

    def list_models(self):
        """Discovers available models for the provided key and caches results."""
        try:
            models = [m.id for m in self.client.models.list().data]
            if models: self._model_cache = models
            return models
        except Exception as e: 
            self.logger.error(f"Failed to list OpenAI models: {e}")
            return self._model_cache if self._model_cache else []

    def get_models_with_quota(self):
        models = self.list_models()
        return [{"id": m, "quota": self.quota_stats if m == self.model_name else "Unlimited (Discovery Mode)"} for m in models]
