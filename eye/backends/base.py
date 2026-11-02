"""
LLMBackend: The Universal Translator for AI Conversations

Think of this as the "contract" that all AI backends must follow. Whether we're 
talking to OpenAI in the cloud, Ollama on your machine, or a CLI tool, they all 
need to speak the same language to Eye.

Every backend must be able to:
1. generate() - Take a question and give back an answer (maybe with tool calls)
2. validate_connectivity() - Check if the AI is reachable (like pinging a server)
3. list_models() - Tell us what models are available (like checking a menu)
4. get_models_with_quota() - Show models with usage limits (how many requests left)

This is an abstract class, which means you can't use it directly - you need to 
create a specific backend (like OpenAIBackend) that implements these methods.

The Three Connection Approaches:
- Cloud API (eye/backends/cloud_api/): Native SDKs talking to cloud services over HTTPS
- Local CLI (eye/backends/local_cli/): Subprocess wrappers for command-line AI tools
- Local Server (eye/backends/local_server/): REST API clients for local AI services

All three approaches inherit from this base class and implement the same interface,
making them interchangeable from Eye's perspective.
"""

from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod


# The system prompt is a stable core (identity, schema, tools) followed by context rebuilt
# for every call (pinned evidence, the report so far, queries already run, retrieved
# knowledge). ContextManager joins the two under this heading so a backend that caches
# prompts can keep the core byte-identical and move the rest after the conversation:
# 2026-11-01, one question on Claude re-sent ~230K uncached tokens on each of 66 calls
# because the rebuilt part sat in front of the whole history.
STEP_CONTEXT_HEADING = "## Context for this step"


def split_step_context(system_prompt):
    """(stable core, per-call context or "") from a system prompt built by ContextManager."""
    marker = "\n\n" + STEP_CONTEXT_HEADING + "\n"
    text = system_prompt or ""
    i = text.find(marker)
    if i < 0:
        return text, ""
    return text[:i], text[i + len(marker):]


def describe_backend_error(exc) -> str:
    """One sentence an investigator can act on, for any backend failure.

    Every SDK raises its own classes, and ``str(exc)`` alone read as noise
    ("Error code: 401 - {...}") or nothing at all (a timeout). Matched by class
    name so the Anthropic, OpenAI and Gemini SDKs need not all be importable;
    the original class and text are kept at the end so nothing is hidden.
    """
    if exc is None:
        return ""
    name = type(exc).__name__
    text = str(exc).strip() or name
    if name == "ClaudeCodeError":
        # Already one plain sentence (claude_code_backend._plain_error).
        return text
    status = getattr(exc, "status_code", None)
    plain = None
    low = text.lower()
    # Billing first: providers send it as a 400 or 402 or a 429 ("insufficient_quota"), and
    # "the provider rejected the request" left the investigator checking the key.
    if status == 402 or any(k in low for k in ("credit balance", "insufficient_quota", "billing",
                                                "payment required", "exceeded your current quota")):
        plain = ("The provider account has run out of credit - add credit in the provider's "
                 "billing page, or switch to another model.")
    elif name in ("AuthenticationError", "PermissionDeniedError") or status in (401, 403):
        plain = "The API key was refused - check it in Settings -> Eye AI."
    elif name == "NotFoundError" or status == 404:
        plain = "The model was not found - pick another model or check its name."
    elif name in ("RateLimitError",) or status == 429:
        plain = "The provider is rate-limiting this key - wait a moment and try again."
    elif name in ("APITimeoutError", "Timeout", "ReadTimeout", "ConnectTimeout", "TimeoutError",
                  "TimeoutExpired"):
        plain = "The model did not answer in time."
    elif name in ("APIConnectionError", "ConnectionError", "ConnectError"):
        plain = "Could not reach the provider - check the network or the local model service."
    elif name in ("FileNotFoundError",):
        plain = "The command-line tool for this backend was not found."
    elif isinstance(status, int) and status >= 500:
        plain = "The provider had a server error (%d) - try again shortly." % status
    elif name in ("BadRequestError",) or status == 400:
        plain = "The provider rejected the request."
    if plain is None:
        return "%s: %s" % (name, text)
    return "%s (%s: %s)" % (plain, name, text[:300])


USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def _get(obj, name, default=0):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _num(obj, name) -> int:
    """A token count from an SDK usage object, 0 when absent or not a number
    (providers leave fields out; test doubles return mocks)."""
    v = _get(obj, name, 0)
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


class LLMBackend(ABC):
    """
    Abstract base class for all LLM backend implementations.
    
    This class defines the mandatory interface that every AI backend must implement,
    regardless of whether it's a cloud service, local server, or CLI tool.
    
    The interface ensures that Eye can work with any AI provider without needing to
    know the specific details of how to communicate with it. Each backend handles
    the translation between Eye's standard format and the provider's specific API.
    """
    
    def record_usage(self, input_tokens=0, output_tokens=0, cache_read=0, cache_write=0,
                     cost_usd=0.0, model=None) -> Dict[str, Any]:
        """One reply's token use, in the same shape for every backend.

        Only Claude Code reported usage before (2026-11-02), so the model badge and
        the eval runner showed nothing for the API and local backends. Kept as
        ``last_usage`` and summed into ``session_usage``; returned so the backend
        can put it in its reply as ``usage``."""
        u = {"input_tokens": int(input_tokens or 0), "output_tokens": int(output_tokens or 0),
             "cache_read_input_tokens": int(cache_read or 0),
             "cache_creation_input_tokens": int(cache_write or 0),
             "cost_usd": float(cost_usd or 0.0)}
        if model:
            u["model"] = str(model)
        self.last_usage = u
        s = getattr(self, "session_usage", None)
        if not isinstance(s, dict):
            s = {"calls": 0, "cost_usd": 0.0}
            s.update({k: 0 for k in USAGE_KEYS})
        s["calls"] = s.get("calls", 0) + 1
        for k in USAGE_KEYS:
            s[k] = s.get(k, 0) + u[k]
        s["cost_usd"] = s.get("cost_usd", 0.0) + u["cost_usd"]
        self.session_usage = s
        return u

    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_message: str,
        tools: Optional[List[Dict]] = None,
        history: Optional[List[Dict[str, Any]]] = None,
        gen_params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate a response from the AI model.
        
        This is the core method that sends a forensic question to the AI and gets back
        an answer. The AI might also decide to call tools (like querying a database or
        searching artifacts) to help answer the question.
        
        How it works:
        1. You give it a system prompt (who the AI should be), a user message (the question),
           optional tools (what actions the AI can take), and optional history (previous conversation)
        2. The backend translates this into whatever format its provider expects
           - Cloud API: Structured JSON sent via SDK
           - Local Server: JSON sent via HTTP POST
           - Local CLI: Text block piped to stdin
        3. The AI thinks about it and generates a response
        4. The backend translates the response back into Eye's standard format
        
        Args:
            system_prompt: Instructions telling the AI who it is and how to behave
                          (e.g., "You are EYE, a forensic analysis assistant...")
            user_message: The actual question or request from the user
                         (e.g., "Show me all prefetch entries from yesterday")
            tools: Optional list of forensic tools the AI can invoke
                  Each tool is a dict with 'name', 'description', and 'parameters'
                  Format varies by backend:
                  - Cloud API: Native function calling (JSON Schema)
                  - Local Server: Native function calling (provider-specific format)
                  - Local CLI: XML protocol (converted to text instructions)
            history: Optional conversation history for context
                    List of dicts with 'role' and 'content' keys
                    (e.g., [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}])
        
        Returns:
            Dict containing the AI's response with these keys:
            - 'content': The text response from the AI
            - 'tool_calls': Optional list of tools the AI wants to invoke
                           Each tool call has 'name' and 'arguments'
            - 'model': The model that generated the response
            - 'usage': Optional token usage statistics
        
        Raises:
            ConnectionError: If the backend can't reach the AI service
            TimeoutError: If the request takes too long
            RuntimeError: If the AI returns an error or invalid response
        
        Example:
            response = backend.generate(
                system_prompt="You are EYE, a forensic assistant",
                user_message="What prefetch files were accessed today?",
                tools=[{
                    "name": "query_database",
                    "description": "Execute SQL query",
                    "parameters": {...}
                }]
            )
            
            # Response might look like:
            # {
            #     "content": "I'll query the prefetch database for you.",
            #     "tool_calls": [{
            #         "name": "query_database",
            #         "arguments": {"database_name": "prefetch.db", "sql_query": "SELECT ..."}
            #     }],
            #     "model": "gpt-4",
            #     "usage": {"prompt_tokens": 150, "completion_tokens": 50}
            # }
        """
        pass
    
    @abstractmethod
    def validate_connectivity(self) -> bool:
        """
        Check if the AI backend is reachable and working.
        
        This is like pinging a server - we're just checking if we can talk to the AI
        before we try to send it a real forensic question. Different backends check
        connectivity in different ways:
        
        - Cloud API: Try to authenticate with API key and maybe list models
        - Local Server: Send a health check request to the REST API endpoint
        - Local CLI: Check if the executable exists and can be run
        
        This is especially useful during onboarding when we're setting up a new backend,
        or when troubleshooting why an AI isn't responding.
        
        Returns:
            bool: True if the backend is reachable and working, False otherwise
        
        Example:
            if backend.validate_connectivity():
                print("AI is online and ready!")
            else:
                print("Can't reach the AI - check your configuration")
        """
        pass

    @abstractmethod
    def list_models(self) -> List[str]:
        """
        Get a list of available AI models from this backend.
        
        This is like checking a restaurant menu - what models can we order from this
        provider? Different backends discover models in different ways:
        
        - Cloud API: Query the provider's API for available models
        - Local Server: Ask the server what models it has loaded
        - Local CLI: Probe the executable or parse its help output
        
        This is used in the onboarding wizard and settings dialog to show users what
        models they can choose from.
        
        Returns:
            List[str]: List of model names/IDs available from this backend
                      (e.g., ["gpt-4", "gpt-3.5-turbo"] or ["llama3:latest", "mistral:7b"])
        
        Example:
            models = backend.list_models()
            print(f"Available models: {', '.join(models)}")
            # Output: Available models: gpt-4, gpt-4-turbo, gpt-3.5-turbo
        """
        pass

    @abstractmethod
    def get_models_with_quota(self) -> List[Dict[str, str]]:
        """
        Get available models along with usage quota information.
        
        This is like checking your restaurant menu AND seeing how many orders you have
        left on your meal plan. For cloud services, this shows rate limits and remaining
        requests. For local services, this might show resource availability.
        
        This is particularly important for cloud APIs where you have rate limits or
        token quotas. It helps users understand if they're about to hit a limit.
        
        Returns:
            List[Dict[str, str]]: List of dicts, each containing:
                - 'id': Model name/ID
                - 'quota': Human-readable quota status
                  (e.g., "1000 requests remaining" or "Unlimited (Local)")

            These exact key names are the contract consumed by
            EYEBridge.get_available_models_with_quota and the React model menu —
            do not rename them in an implementation.

        Note:
            Not all backends support quota tracking. Local backends typically return
            "Unlimited (Local)" since there's no external rate limiting.

        Example:
            models_with_quota = backend.get_models_with_quota()
            for model_info in models_with_quota:
                print(f"{model_info['id']}: {model_info['quota']}")

            # Output:
            # gpt-4: 500 requests remaining (resets in 1 hour)
            # gpt-3.5-turbo: 5000 requests remaining (resets in 1 hour)
        """
        pass

    def get_context_window(self) -> Optional[int]:
        """Report the active model's real context window in tokens, or None.

        Default: None — meaning "this backend can't self-report; the caller
        should fall back to the static registry / default". Backends whose
        provider exposes the window (Gemini ``input_token_limit``, Ollama /
        LM Studio model info) override this. Implementations MUST be best-effort:
        any error/timeout returns None and never raises, since this runs during
        ContextManager init and model switches.
        """
        return None

    def _sanitize_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        Sanitize messages for strict role-alternation backends.
        
        1. Merges all 'system' messages into a single message at the start.
        2. Ensures non-system roles alternate strictly (user -> assistant -> user).
        3. Merges consecutive messages with the same role.
        4. Ensures the first non-system message is a 'user' message.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'
            
        Returns:
            Sanitized list of messages
        """
        if not messages:
            return []
            
        sanitized = []
        system_contents = []
        
        # 1. Collect all system messages
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "").strip()
                if content:
                    system_contents.append(content)
        
        # Add a single merged system message at the beginning
        if system_contents:
            sanitized.append({
                "role": "system", 
                "content": "\n\n".join(system_contents)
            })
            
        # 2. Filter out system messages and handle role alternation for the rest
        remaining = []
        for msg in messages:
            role = msg.get("role", "user")
            if role == "system":
                continue
            
            # Map non-standard roles to standard user/assistant
            if role not in ["user", "assistant"]:
                # 'tool' messages are often treated as 'assistant' responses or 'user' feedback
                # depending on the provider. For generic sanitization, we map to 'user'.
                role = "user"
            
            content = msg.get("content", "").strip()
            if not content:
                continue # Skip empty messages
                
            if remaining and remaining[-1]["role"] == role:
                # Merge consecutive messages with same role
                remaining[-1]["content"] += "\n\n" + content
            else:
                remaining.append({"role": role, "content": content})
                
        # 3. Ensure the sequence starts with 'user' if it exists
        if remaining and remaining[0]["role"] == "assistant":
            # Add a dummy user message if history starts with an assistant response
            # (can happen after summarization/pruning)
            remaining.insert(0, {"role": "user", "content": "[Continuing previous investigation...]"})
            
        sanitized.extend(remaining)
        return sanitized
