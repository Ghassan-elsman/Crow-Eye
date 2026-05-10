"""
Anthropic Backend: Talking to Claude in the Cloud

This backend connects to Anthropic's servers (Claude AI) using their official Python SDK.
Like the OpenAI backend, it's the "phone call" approach - we send our forensic questions 
over the internet and get thoughtful answers back from Claude.

How it works:
1. We package up the system prompt, chat history, and tools into a JSON request
2. The Anthropic SDK sends it over HTTPS to their servers
3. Claude thinks about it and sends back a response (text + maybe tool calls)
4. We also grab the rate limit info from HTTP headers so you know how many requests you have left

What makes Claude special:
- Claude uses a slightly different format than OpenAI (system prompt is separate, not in messages)
- Tool definitions use 'input_schema' instead of 'parameters' (we handle the translation)
- Responses can have multiple content blocks (text blocks and tool_use blocks)

This is great for: Deep analysis where you need Claude's reasoning abilities and don't mind 
sending data to the cloud.
"""

from typing import Dict, List, Any, Optional
import logging
import json

from eye.backends.base import LLMBackend


class AnthropicBackend(LLMBackend):
    """
    Official Anthropic (Claude) Cloud Backend.
    Handles specialized tool-use schema conversion for Claude 3+.
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
        """Lazy-loaded Anthropic client."""
        if self._client is None:
            import anthropic
            api_key = self.credential_manager.get_credential("anthropic_api_key")
            self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def generate(self, system_prompt, user_message, tools=None, history=None):
        """Standardizes Claude's distinct message/system prompt structure."""
        try:
            # Build and sanitize the conversation history
            raw_messages = []
            if history:
                for msg in history:
                    raw_messages.append({
                        "role": msg.get("role", "user"), 
                        "content": msg.get("content", "")
                    })
            raw_messages.append({"role": "user", "content": user_message})
            
            # Sanitize to ensure alternating user/assistant roles (Claude is VERY strict)
            # This also pulls out any 'system' messages from history to be merged.
            sanitized = self._sanitize_messages(raw_messages)
            
            # Filter and merge system messages if any exist in sanitized history
            # The base system prompt is always used as the primary instruction.
            final_system = system_prompt
            final_history = []
            for msg in sanitized:
                if msg["role"] == "system":
                    if msg["content"] != system_prompt:
                        final_system += "\n\n" + msg["content"]
                else:
                    final_history.append(msg)
            
            api_params = {
                "model": self.model_name, 
                "max_tokens": 4096, 
                "system": final_system,
                "messages": final_history
            }
            if tools:
                # Claude uses 'input_schema' instead of 'parameters' - we're translating
                # from Eye's standard format to what Claude understands
                api_params["tools"] = [
                    {"name": t["name"], "description": t.get("description", ""), "input_schema": t.get("parameters", {})} 
                    for t in tools
                ]
            
            # Using with_raw_response to access rate-limit headers
            resp_raw = self.client.messages.with_raw_response.create(**api_params)
            
            # Extract Quota Telemetry
            if hasattr(resp_raw, 'headers'):
                rem = resp_raw.headers.get("anthropic-ratelimit-requests-remaining")
                reset = resp_raw.headers.get("anthropic-ratelimit-requests-reset")
                if rem:
                    self.quota_stats = f"{rem} requests remaining"
                    if reset: self.quota_stats += f" (resets at {reset})"

            resp = resp_raw.parse()
            content = ""
            tool_calls = []
            # Claude can return multiple content blocks - we need to process each one
            for block in resp.content:
                if block.type == "text": content += block.text
                elif block.type == "tool_use":
                    # Convert Claude's tool_use format to our standard format
                    tool_calls.append({
                        "id": block.id, "type": "function", 
                        "function": {"name": block.name, "arguments": json.dumps(block.input)}
                    })
            return {"content": content, "tool_calls": tool_calls}
        except Exception as e:
            self.logger.error(f"Anthropic API failure: {e}")
            raise

    def validate_connectivity(self):
        """
        Checks if the Anthropic API is reachable and key is valid.
        
        Attempts a minimal request. If no model name is configured, it tries
        to list models instead to verify the API key's validity.
        """
        try:
            if self.model_name and self.model_name not in ["", "default"]:
                # If we have a model name, try a 1-token generation (cheapest check)
                self.client.messages.create(
                    model=self.model_name, 
                    max_tokens=1, 
                    messages=[{"role": "user", "content": "t"}]
                )
            else:
                # If no model name yet, just try to list models
                self.list_models()
            return True
        except Exception as e:
            self.logger.error(f"Anthropic connectivity check failed: {e}")
            return False

    def list_models(self):
        """
        Anthropic discovery. 
        SDK method is primary; direct HTTP request used as fallback for older SDKs.
        """
        try:
            models = []
            if hasattr(self.client, 'models'):
                models = [m.id for m in self.client.models.list().data]
            
            # Fallback: If the SDK doesn't have a models endpoint, try direct HTTP
            if not models:
                import requests
                api_key = self.credential_manager.get_credential("anthropic_api_key")
                response = requests.get(
                    "https://api.anthropic.com/v1/models",
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                    timeout=10
                )
                if response.status_code == 200:
                    models = [m["id"] for m in response.json().get("data", [])]
            
            if models: self._model_cache = models
            return models
        except Exception as e:
            self.logger.error(f"Failed to list Anthropic models: {e}")
            return self._model_cache if self._model_cache else []

    def get_models_with_quota(self):
        models = self.list_models()
        return [{"id": m, "quota": self.quota_stats if m == self.model_name else "Unlimited (Discovery Mode)"} for m in models]
