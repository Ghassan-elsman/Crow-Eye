"""
Ollama Backend: Your Local AI Server

Ollama is like having a smart assistant running on your computer (or another computer 
in your lab). Instead of sending data to the cloud, we talk to Ollama over HTTP - 
just like a web browser talks to a website, but everything stays local.

How it works:
1. Ollama runs as a background service (usually on port 11434)
2. We send it JSON requests with our questions and available tools
3. It thinks using a local model (like Llama 3 or Mistral) and sends back JSON
4. If the model wants to use a tool, it tells us in the response (native function calling!)

Why this is awesome:
- Your forensic data never leaves your network (privacy!)
- Fast responses (no internet latency)
- Can run on the same machine or a dedicated AI server in your lab
- Uses modern web standards (JSON/REST) so it's reliable

We've enhanced this with:
- Connection pooling (reuses HTTP connections for speed)
- Smart retry logic (if it fails, we try again with exponential backoff)
- Better error messages (tells you exactly what went wrong)
- Configurable timeouts (5s to connect, 120s to think)
- Health check endpoint (pings /api/tags to verify Ollama is alive)
"""

import logging
import time
from typing import Dict, List, Any, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from eye.backends.base import LLMBackend


class OllamaBackend(LLMBackend):
    """
    Backend for local Ollama instances.
    
    Communicates via the Ollama REST API (default port 11434) using HTTP requests.
    This is the "Direct Local Server" approach - combining Cloud API's structured
    communication with local network privacy.
    
    Enhanced Features:
    - Connection pooling for improved performance
    - Exponential backoff retry logic for transient failures
    - Robust error handling with meaningful messages
    - Configurable timeouts for different operations
    - Health check endpoint for connectivity validation
    """
    
    def __init__(self, model_name: str, executable_path: str = None, api_endpoint: str = None):
        """
        Initialize the Ollama backend.
        
        Args:
            model_name: The name of the Ollama model to use (e.g., "llama3:latest")
            executable_path: (DEPRECATED) Use api_endpoint instead.
                           Path to Ollama executable or API endpoint URL
            api_endpoint: API endpoint URL for Ollama service
                         Can be http://localhost:11434 (same machine)
                         or http://192.168.1.100:11434 (different machine on LAN)
                         If a file path is provided, defaults to http://localhost:11434
        
        Note: For backward compatibility, executable_path is still supported but
              api_endpoint is the preferred parameter name.
        """
        import warnings
        
        self.model_name = model_name
        
        # Handle parameter naming: support both old (executable_path) and new (api_endpoint)
        if api_endpoint is not None:
            endpoint = api_endpoint
        elif executable_path is not None:
            endpoint = executable_path
            # Emit deprecation warning if using old parameter name
            if not executable_path.startswith('http'):
                warnings.warn(
                    "Parameter 'executable_path' is deprecated for HTTP URLs. "
                    "Use 'api_endpoint' instead. executable_path will be used for file paths only in future versions.",
                    DeprecationWarning,
                    stacklevel=2
                )
        else:
            raise ValueError("Either api_endpoint or executable_path must be provided")
        
        # Heuristically determine API endpoint from provided path/URL
        self.api_endpoint = self._normalize_endpoint(endpoint)
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
    
    def _normalize_endpoint(self, executable_path: str) -> str:
        """
        Convert executable path to API endpoint URL.
        
        If the path looks like a URL, use it directly.
        Otherwise, assume it's a file path and default to localhost:11434.
        
        Args:
            executable_path: Path to Ollama executable or API endpoint URL
        
        Returns:
            str: Normalized API endpoint URL (e.g., "http://localhost:11434")
        """
        if executable_path.startswith("http://") or executable_path.startswith("https://"):
            return executable_path.rstrip('/')
        
        # Default to localhost if it's a file path
        return "http://localhost:11434"
    
    def _make_request_with_retry(
        self, 
        url: str, 
        payload: Dict[str, Any], 
        max_retries: int = 3
    ) -> requests.Response:
        """
        Make HTTP request with exponential backoff retry logic.
        
        If the request fails, we wait a bit and try again. Each retry waits longer (1s, 2s, 4s).
        This handles transient failures like temporary network issues or Ollama being busy.
        
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
                    self.logger.error(f"Ollama connection failed after {max_retries} attempts: {e}")
                    raise ConnectionError(
                        f"Cannot connect to Ollama at {self.api_endpoint}. "
                        f"Is the Ollama service running? Check that Ollama is started and listening on the correct port."
                    )
                
                # Wait before retrying (exponential backoff: 1s, 2s, 4s)
                wait_time = 2 ** attempt
                self.logger.warning(
                    f"Ollama connection failed (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {wait_time}s... Error: {e}"
                )
                time.sleep(wait_time)
                
            except requests.exceptions.Timeout as e:
                if attempt == max_retries - 1:
                    # Last attempt failed - give up
                    self.logger.error(f"Ollama request timeout after {max_retries} attempts: {e}")
                    raise TimeoutError(
                        f"Ollama request timed out after {self.read_timeout} seconds. "
                        f"The model might be too slow or the query too complex. Try a smaller model or simpler query."
                    )
                
                # Wait before retrying
                wait_time = 2 ** attempt
                self.logger.warning(
                    f"Ollama request timeout (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {wait_time}s... Error: {e}"
                )
                time.sleep(wait_time)
                
            except requests.exceptions.HTTPError as e:
                # HTTP errors (4xx, 5xx) - don't retry, just fail immediately
                self.logger.error(f"Ollama HTTP error: {e}")
                error_detail = ""
                try:
                    error_detail = e.response.text
                except:
                    pass
                raise RuntimeError(
                    f"Ollama returned error: {e.response.status_code} - {error_detail or str(e)}"
                )
    
    def generate(
        self, 
        system_prompt: str, 
        user_message: str, 
        tools: Optional[List[Dict]] = None, 
        history: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Standardizes Ollama chat completion requests.
        
        Sends a forensic question to Ollama and gets back an answer (possibly with tool calls).
        Uses the Ollama /api/chat endpoint with JSON payloads.
        
        Args:
            system_prompt: Instructions for the AI (who it is, how to behave)
            user_message: The actual forensic question
            tools: Optional list of Eye forensic tools the AI can invoke
            history: Optional conversation history for context
        
        Returns:
            Dict containing:
                - 'content': The AI's text response
                - 'tool_calls': List of tools the AI wants to invoke (if any)
        
        Raises:
            ConnectionError: If Ollama is unreachable
            TimeoutError: If the request times out
            RuntimeError: If Ollama returns an error
        """
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
            # This is critical for local models (like Llama 3) which often fail
            # if roles don't alternate or if system messages appear in the middle.
            messages = self._sanitize_messages(raw_messages)
            
            # Build the request payload
            payload = {
                "model": self.model_name, 
                "messages": messages, 
                "stream": False  # We want the complete response, not streaming
            }
            
            if tools:
                # Ollama expects tools wrapped in a specific format - we're translating from 
                # Eye's standard format to what Ollama understands
                # Format: [{"type": "function", "function": tool}, ...]
                payload["tools"] = [{"type": "function", "function": tool} for tool in tools]
            
            # Make the request with retry logic
            response = self._make_request_with_retry(
                f"{self.api_endpoint}/api/chat",
                payload
            )
            
            # Parse the response
            data = response.json()
            
            # Extract content and tool calls from the response
            message = data.get("message", {})
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
            self.logger.error(f"Ollama invalid URL: {e}")
            raise ConnectionError(
                f"Invalid Ollama endpoint URL: {self.api_endpoint}. "
                f"Please check the URL format and port number."
            )
        except Exception as e:
            # Catch any other unexpected errors
            self.logger.error(f"Ollama generation failed with unexpected error: {e}")
            raise RuntimeError(f"Unexpected error during Ollama generation: {e}")
    
    def validate_connectivity(self) -> bool:
        """
        Pings the Ollama service tags endpoint.
        
        We ping the /api/tags endpoint to see if Ollama is alive and responding.
        This is like knocking on the door to see if anyone's home.
        
        Returns:
            bool: True if Ollama is reachable, False otherwise
        """
        try:
            # Use a short timeout for health checks (5 seconds)
            response = self.session.get(
                f"{self.api_endpoint}/api/tags",
                timeout=self.connect_timeout
            )
            return response.status_code == 200
        except Exception as e:
            self.logger.debug(f"Ollama connectivity check failed: {e}")
            return False
    
    def list_models(self) -> List[str]:
        """
        Discovers locally pulled Ollama models.
        
        Queries the /api/tags endpoint to see what models are available.
        This is like checking what's in your toolbox.
        
        Returns:
            List[str]: List of model names (e.g., ["llama3:latest", "mistral:7b"])
        """
        try:
            response = self.session.get(
                f"{self.api_endpoint}/api/tags",
                timeout=self.connect_timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                models = data.get("models", [])
                return [m["name"] for m in models]
            else:
                self.logger.warning(f"Failed to list Ollama models: HTTP {response.status_code}")
                return []
                
        except Exception as e:
            self.logger.error(f"Error listing Ollama models: {e}")
            return []
    
    def get_models_with_quota(self) -> List[Dict[str, str]]:
        """
        Ollama is local, so quota is effectively unlimited.
        
        Since Ollama runs on your own hardware, there's no external rate limiting
        or token quotas. You're only limited by your machine's resources.
        
        Returns:
            List[Dict[str, str]]: List of models with "Unlimited (Local)" quota
        """
        models = self.list_models()
        return [{"id": m, "quota": "Unlimited (Local)"} for m in models]
