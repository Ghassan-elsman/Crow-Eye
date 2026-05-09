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
                try:
                    error_detail = e.response.text
                except:
                    pass
                raise RuntimeError(
                    f"LM Studio returned error: {e.response.status_code} - {error_detail or str(e)}"
                )
    
    def generate(
        self, 
        system_prompt: str, 
        user_message: str, 
        tools: Optional[List[Dict]] = None, 
        history: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Uses standard OpenAI-compatible chat completion payload.
        
        Note: Per Ghassan Protocol v2.0, we perform a 'Pre-Flight Ping' 
        to ensure the backend is alive before sending forensic data.
        """
        if not self.validate_connectivity():
            self.logger.error(f"Pre-flight ping failed for LM Studio at {self.api_endpoint}")
            raise ConnectionError(
                f"Cannot reach LM Studio at {self.api_endpoint}. "
                f"Forensic investigation halted to prevent data loss or silent failure."
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
            # This is critical for LM Studio's Jinja templates which often fail
            # if roles don't alternate or if system messages appear in the middle.
            messages = self._sanitize_messages(raw_messages)
            
            # Build the request payload (OpenAI-compatible format)
            payload = {
                "model": self.model_name, 
                "messages": messages
            }
            
            if tools:
                # LM Studio uses OpenAI-compatible format - we pass tools directly
                # The model needs to support function calling for this to work
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
                payload["tools"] = formatted_tools
            
            # Make the request with retry logic
            response = self._make_request_with_retry(
                f"{self.api_endpoint}/v1/chat/completions",
                payload
            )
            
            # Parse the response (OpenAI-compatible format)
            data = response.json()
            
            # Extract content and tool calls from the response
            # OpenAI format: data["choices"][0]["message"]
            if "choices" not in data or len(data["choices"]) == 0:
                self.logger.error(f"LM Studio returned unexpected response format: {data}")
                raise RuntimeError(
                    f"LM Studio returned unexpected response format. "
                    f"Expected 'choices' array but got: {list(data.keys())}"
                )
            
            message = data["choices"][0]["message"]
            content = message.get("content", "")
            tool_calls = message.get("tool_calls", [])
            
            return {
                "content": content,
                "tool_calls": tool_calls
            }
            
        except (ConnectionError, TimeoutError, RuntimeError):
            # Re-raise our custom errors as-is
            raise
        except requests.exceptions.InvalidURL as e:
            # Invalid URL (e.g., invalid port number)
            self.logger.error(f"LM Studio invalid URL: {e}")
            raise ConnectionError(
                f"Invalid LM Studio endpoint URL: {self.api_endpoint}. "
                f"Please check the URL format and port number."
            )
        except Exception as e:
            # Catch any other unexpected errors
            self.logger.error(f"LM Studio generation failed with unexpected error: {e}")
            raise RuntimeError(f"Unexpected error during LM Studio generation: {e}")
    
    def validate_connectivity(self) -> bool:
        """
        Checks the model list endpoint for server availability.
        
        We ping the /v1/models endpoint to see if LM Studio is alive and responding.
        This is like knocking on the door to see if anyone's home.
        
        Also validates that the server supports OpenAI-compatible endpoints.
        
        Returns:
            bool: True if LM Studio is reachable and OpenAI-compatible, False otherwise
        """
        try:
            # Use a short timeout for health checks (5 seconds)
            response = self.session.get(
                f"{self.api_endpoint}/v1/models",
                timeout=self.connect_timeout
            )
            
            if response.status_code != 200:
                self.logger.debug(f"LM Studio health check failed: HTTP {response.status_code}")
                return False
            
            # Validate OpenAI compatibility by checking response format
            # OpenAI-compatible servers return {"data": [...], "object": "list"}
            try:
                data = response.json()
                if "data" not in data:
                    self.logger.warning(
                        f"LM Studio server at {self.api_endpoint} doesn't appear to be OpenAI-compatible. "
                        f"Expected 'data' field in /v1/models response."
                    )
                    return False
            except Exception as e:
                self.logger.warning(f"Failed to parse LM Studio /v1/models response: {e}")
                return False
            
            return True
            
        except Exception as e:
            self.logger.debug(f"LM Studio connectivity check failed: {e}")
            return False
    
    def list_models(self) -> List[str]:
        """
        Returns the list of currently loaded models in LM Studio.
        
        Queries the /v1/models endpoint to see what models are available.
        This is like checking what's in your toolbox.
        
        Returns:
            List[str]: List of model IDs (e.g., ["llama-3-8b", "mistral-7b"])
        """
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
