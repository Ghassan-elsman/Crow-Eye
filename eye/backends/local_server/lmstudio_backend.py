"""
LM Studio Backend: Your OpenAI-Compatible Local AI Server

LM Studio is like having a professional AI assistant running on your computer (or another 
computer in your lab). It speaks the same language as OpenAI's API, but everything stays 
local and private.

How it works:
1. LM Studio runs as a background service (usually on port 1234)
2. We send it JSON requests using OpenAI's API format
3. It thinks using a local model (like Llama 3, Mistral, or others) and sends back JSON
4. If the model wants to use a tool, it tells us in the response (OpenAI-compatible function calling!)

Why this is awesome:
- Your forensic data never leaves your network (privacy!)
- Fast responses (no internet latency)
- Can run on the same machine or a dedicated AI server in your lab
- Uses OpenAI's standard API format (easy to work with)
- Compatible with many popular models

We've enhanced this with:
- Connection pooling (reuses HTTP connections for speed)
- Smart retry logic (if it fails, we try again with exponential backoff)
- Better error messages (tells you exactly what went wrong)
- Configurable timeouts (5s to connect, 120s to think)
- Health check endpoint (pings /v1/models to verify LM Studio is alive)
- OpenAI compatibility validation (ensures the server supports the right endpoints)
"""

import logging
import time
from typing import Dict, List, Any, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from eye.backends.base import LLMBackend


class LMStudioBackend(LLMBackend):
    """
    Backend for LM Studio or any OpenAI-compatible local server.
    
    Communicates via OpenAI-compatible REST API (default port 1234) using HTTP requests.
    This is the "Direct Local Server" approach - combining Cloud API's structured
    communication with local network privacy.
    
    Enhanced Features:
    - Connection pooling for improved performance
    - Exponential backoff retry logic for transient failures
    - Robust error handling with meaningful messages
    - Configurable timeouts for different operations
    - Health check endpoint for connectivity validation
    - OpenAI compatibility validation
    """
    
    def __init__(self, api_endpoint: str, model_name: str):
        """
        Initialize the LM Studio backend.
        
        Args:
            api_endpoint: The base URL of the LM Studio server
                         Examples: "http://localhost:1234" or "http://192.168.1.100:1234"
            model_name: The name of the model loaded in LM Studio
        """
        self.api_endpoint = api_endpoint.rstrip('/')
        self.model_name = model_name
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Connection pooling for performance
        # We reuse HTTP connections instead of creating new ones each time - much faster!
        self.session = requests.Session()
        
        # Configure connection pooling with HTTPAdapter
        # pool_connections: Number of connection pools to cache (one per host)
        # pool_maxsize: Maximum number of connections to save in the pool
        # max_retries: Number of retries for failed connections (handled by urllib3)
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[500, 502, 503, 504],
                allowed_methods=["GET", "POST"]
            )
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        
        # Timeout configuration
        # 5 seconds to connect, 120 seconds to think - plenty of time for complex forensic queries
        self.connect_timeout = 5
        self.read_timeout = 120
    
    def _make_request_with_retry(
        self, 
        url: str, 
        payload: Dict[str, Any], 
        max_retries: int = 3
    ) -> requests.Response:
        """
        Make HTTP request with exponential backoff retry logic.
        
        If the request fails, we wait a bit and try again. Each retry waits longer (1s, 2s, 4s).
        This handles transient failures like temporary network issues or LM Studio being busy.
        
        Args:
            url: The full URL to send the request to
            payload: The JSON payload to send
            max_retries: Maximum number of retry attempts
        
        Returns:
            requests.Response: The successful response
        
        Raises:
            ConnectionError: If all retries fail due to connection issues
            TimeoutError: If all retries fail due to timeout
            RuntimeError: If the server returns an HTTP error
        """
        for attempt in range(max_retries):
            try:
                response = self.session.post(
                    url,
                    json=payload,
                    timeout=(self.connect_timeout, self.read_timeout)
                )
                response.raise_for_status()
                return response
                
            except requests.exceptions.ConnectionError as e:
                if attempt == max_retries - 1:
                    # Last attempt failed - give up
                    self.logger.error(f"LM Studio connection failed after {max_retries} attempts: {e}")
                    raise ConnectionError(
                        f"Cannot connect to LM Studio at {self.api_endpoint}. "
                        f"Is LM Studio running with the local server enabled? "
                        f"Check that LM Studio is started and the server is listening on the correct port."
                    )
                
                # Wait before retrying (exponential backoff: 1s, 2s, 4s)
                wait_time = 2 ** attempt
                self.logger.warning(
                    f"LM Studio connection failed (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {wait_time}s... Error: {e}"
                )
                time.sleep(wait_time)
                
            except requests.exceptions.Timeout as e:
                if attempt == max_retries - 1:
                    # Last attempt failed - give up
                    self.logger.error(f"LM Studio request timeout after {max_retries} attempts: {e}")
                    raise TimeoutError(
                        f"LM Studio request timed out after {self.read_timeout} seconds. "
                        f"The model might be too slow or the query too complex. "
                        f"Try a smaller model or simpler query."
                    )
                
                # Wait before retrying
                wait_time = 2 ** attempt
                self.logger.warning(
                    f"LM Studio request timeout (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {wait_time}s... Error: {e}"
                )
                time.sleep(wait_time)
                
            except requests.exceptions.HTTPError as e:
                # HTTP errors (4xx, 5xx) - don't retry, just fail immediately
                self.logger.error(f"LM Studio HTTP error: {e}")
                error_detail = ""
                no_models_loaded = False
                # NOTE: the "no models loaded" case is only FLAGGED here and raised
                # after the except block. Raising inside this try meant the bare
                # `except` below caught our own RuntimeError and replaced the
                # actionable instructions with the generic status-code message.
                try:
                    error_json = e.response.json()
                    error_msg = error_json.get("error", {}).get("message", "")
                    no_models_loaded = "No models loaded" in error_msg
                    error_detail = error_msg or e.response.text
                except Exception:
                    try:
                        error_detail = e.response.text
                    except Exception:
                        pass

                if no_models_loaded:
                    raise RuntimeError(
                        "LM Studio Error: No AI model is currently loaded in the server.\n\n"
                        "To fix this:\n"
                        "1. Open LM Studio on the host machine.\n"
                        "2. Go to the 'AI Chat' or 'Local Server' tab.\n"
                        "3. Select and LOAD a model into memory at the top of the window.\n"
                        "4. Ensure the server is STARTED on port 1234."
                    )

                raise RuntimeError(
                    f"LM Studio returned error: {e.response.status_code} - {error_detail or str(e)}"
                )

        # Unreachable for max_retries >= 1 (every branch above returns or raises),
        # but a caller passing 0 would otherwise fall through and return None,
        # producing an opaque AttributeError on `.json()` at the call site.
        raise RuntimeError(
            f"LM Studio request to {url} was never attempted (max_retries={max_retries})."
        )


    def generate(
        self,
        system_prompt: str,
        user_message: str,
        tools: Optional[List[Dict]] = None,
        history: Optional[List[Dict[str, Any]]] = None,
        gen_params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Uses standard OpenAI-compatible chat completion payload.

        Pre-flight connectivity is NOT re-checked here: ContextManager already
        gates every query on a TTL-cached ``validate_connectivity()`` (GEP-1), so
        pinging again per model call added a second ``/v1/models`` round-trip to
        every iteration of the agentic loop. A server that dies mid-turn still
        surfaces clearly through _make_request_with_retry's connection handling.
        """
        # Ensure we have a model name. If not, try to pick one from the server.
        target_model = self.model_name
        if not target_model or target_model in ["", "default", "auto"]:
            loaded_models = self.list_models()
            if loaded_models:
                target_model = loaded_models[0]
                # Persist the resolution so get_context_window() and any later
                # call look up the model we are ACTUALLY using, not the placeholder.
                self.model_name = target_model
                self.logger.info(f"LM Studio: No model configured. Auto-selecting first loaded: {target_model}")
            else:
                self.logger.error("LM Studio: No models are currently loaded in the server.")
                raise RuntimeError(
                    "LM Studio Error: No models are loaded. "
                    "Please open LM Studio and load a model into memory before starting the investigation."
                )

        try:
            # Build the raw messages array (system + history + user)
            raw_messages = [{"role": "system", "content": system_prompt}]
            
            if history:
                for msg in history:
                    raw_messages.append({
                        "role": msg.get("role", "user"), 
                        "content": msg.get("content", "")
                    })
            
            raw_messages.append({"role": "user", "content": user_message})
            
            # Sanitize messages to ensure alternating user/assistant roles
            messages = self._sanitize_messages(raw_messages)
            
            # Build the request payload (OpenAI-compatible format)
            payload = {
                "model": target_model,
                "messages": messages
            }

            gp = gen_params or {}
            if gp.get("temperature") is not None:
                payload["temperature"] = gp["temperature"]
            if gp.get("max_output_tokens") is not None:
                payload["max_tokens"] = gp["max_output_tokens"]
            if gp.get("top_p") is not None:
                payload["top_p"] = gp["top_p"]

            if tools:
                # Format tools to strict OpenAI specification
                formatted_tools = []
                for tool in tools:
                    if "type" in tool and tool["type"] == "function" and "function" in tool:
                        formatted_tools.append(tool)
                    else:
                        formatted_tools.append({
                            "type": "function",
                            "function": tool
                        })
                payload["tools"] = formatted_tools
            
            # Make the request with retry logic
            response = self._make_request_with_retry(
                f"{self.api_endpoint}/v1/chat/completions",
                payload
            )
            
            # Parse the response (OpenAI-compatible format)
            data = response.json()
            
            # Extract content and tool calls from the response
            if "choices" not in data or len(data["choices"]) == 0:
                self.logger.error(f"LM Studio returned unexpected response format: {data}")
                raise RuntimeError(
                    f"LM Studio returned unexpected response format. "
                    f"Expected 'choices' array but got: {list(data.keys())}"
                )
            
            message = data["choices"][0]["message"]
            content = message.get("content", "")
            tool_calls = message.get("tool_calls", [])

            # LM Studio does NOT reject an unknown model id — it answers with
            # whatever model is currently loaded and returns HTTP 200 (verified
            # live: a request for "definitely-not-a-real-model-xyz" was served by
            # microsoft/phi-4-reasoning). For a forensic tool that seals the model
            # name into the chain of custody, silently attributing an answer to a
            # model that never produced it is not acceptable — so detect the
            # substitution, warn, and report the model that ACTUALLY answered.
            actual_model = data.get("model") or target_model
            substituted = bool(actual_model and actual_model != target_model)
            if substituted:
                self.logger.warning(
                    "LM Studio served this request with '%s', NOT the requested '%s'. "
                    "The loaded model differs from the configured one.",
                    actual_model, target_model,
                )

            return {
                "content": content,
                "tool_calls": tool_calls,
                "model": actual_model,
                "model_substituted": substituted,
            }
            
        except (ConnectionError, TimeoutError, RuntimeError):
            # Re-raise our custom errors as-is
            raise
        except Exception as e:
            # Catch any other unexpected errors
            self.logger.error(f"LM Studio generation failed with unexpected error: {e}")
            raise RuntimeError(f"Unexpected error during LM Studio generation: {e}")
    
    def validate_connectivity(self) -> bool:
        """
        Checks the model list endpoint for server availability and loaded models.
        
        Returns:
            bool: True if LM Studio is reachable and has at least one model loaded.
        """
        try:
            response = self.session.get(
                f"{self.api_endpoint}/v1/models",
                timeout=self.connect_timeout
            )
            
            if response.status_code != 200:
                self.logger.debug(f"LM Studio health check failed: HTTP {response.status_code}")
                return False
            
            data = response.json()
            # Validates that 'data' exists and is not empty (at least one model loaded)
            if "data" not in data or not data["data"]:
                self.logger.warning(f"LM Studio at {self.api_endpoint} is online, but no models are loaded.")
                # We return False here, but generate() will provide the detailed instructions
                return False
            
            return True
            
        except Exception as e:
            self.logger.debug(f"LM Studio connectivity check failed: {e}")
            return False
    
    def list_models(self) -> List[str]:
        """
        Returns the chat-capable models available in LM Studio.

        The OpenAI-compatible ``/v1/models`` endpoint lists EVERYTHING the server
        holds — including embedding models, which cannot answer a forensic
        question at all. Verified live: a server holding an embedding model
        offered ``text-embedding-nomic-embed-text-v1.5`` in the Eye's model menu
        as though it were a chat model. So we prefer LM Studio's native
        ``/api/v0/models``, which reports a per-model ``type``, and keep only
        ``llm``/``vlm`` entries. Older servers without ``/api/v0`` fall back to
        the unfiltered OpenAI-compatible list.

        Returns:
            List[str]: List of chat-capable model IDs (e.g., ["llama-3-8b"])
        """
        try:
            native = self.session.get(
                f"{self.api_endpoint}/api/v0/models",
                timeout=self.connect_timeout,
            )
            if native.status_code == 200:
                entries = (native.json() or {}).get("data", []) or []
                chat = [m for m in entries
                        if m.get("id") and m.get("type") in ("llm", "vlm")]
                if chat:
                    # Already-loaded models first: auto-selection takes the first
                    # entry, and picking a model the investigator has actually
                    # loaded avoids a slow cold JIT load (and a model that may
                    # fail to load at all).
                    chat.sort(key=lambda m: 0 if m.get("state") == "loaded" else 1)
                    return [m["id"] for m in chat]
                # /api/v0 answered but nothing is chat-capable — that is a real,
                # actionable answer, not a reason to fall back to a noisier list.
                if entries:
                    self.logger.warning(
                        "LM Studio holds no chat-capable models (only %s).",
                        ", ".join(sorted({str(m.get('type')) for m in entries})))
                    return []
        except Exception as e:
            self.logger.debug(f"LM Studio /api/v0/models unavailable, using /v1/models: {e}")

        try:
            response = self.session.get(
                f"{self.api_endpoint}/v1/models",
                timeout=self.connect_timeout
            )

            if response.status_code == 200:
                data = response.json()
                models = data.get("data", [])
                return [m["id"] for m in models]
            else:
                self.logger.warning(f"Failed to list LM Studio models: HTTP {response.status_code}")
                return []

        except Exception as e:
            self.logger.error(f"Error listing LM Studio models: {e}")
            return []
    
    def get_context_window(self) -> Optional[int]:
        """Report the active model's context window via LM Studio's native REST
        endpoint ``/api/v0/models``, which exposes ``loaded_context_length`` and
        ``max_context_length`` (the OpenAI-compatible ``/v1/models`` does not).

        Prefers the loaded window (the real usable size for this instance) over
        the model's max. Best-effort: returns None on any failure (e.g. an older
        LM Studio without ``/api/v0``). Cached per instance.
        """
        if getattr(self, "_context_window_cache", None):
            return self._context_window_cache
        try:
            response = self.session.get(
                f"{self.api_endpoint}/api/v0/models",
                timeout=self.connect_timeout,
            )
            if response.status_code == 200:
                models = (response.json() or {}).get("data", []) or []
                target = (self.model_name or "").lower()
                for m in models:
                    if (m.get("id", "") or "").lower() == target:
                        limit = m.get("loaded_context_length") or m.get("max_context_length")
                        if limit:
                            self._context_window_cache = int(limit)
                            self.logger.info(f"LM Studio reported context window {self._context_window_cache:,} for {self.model_name}")
                            return self._context_window_cache
                        break
        except Exception as e:
            self.logger.debug(f"LM Studio context-window lookup failed: {e}")
        return None

    def get_models_with_quota(self) -> List[Dict[str, str]]:
        """
        LM Studio is local, so quota is effectively unlimited.
        
        Since LM Studio runs on your own hardware, there's no external rate limiting
        or token quotas. You're only limited by your machine's resources.
        
        Returns:
            List[Dict[str, str]]: List of models with "Unlimited (Local)" quota
        """
        models = self.list_models()
        return [{"id": m, "quota": "Unlimited (Local)"} for m in models]
