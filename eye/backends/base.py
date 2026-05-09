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


class LLMBackend(ABC):
    """
    Abstract base class for all LLM backend implementations.
    
    This class defines the mandatory interface that every AI backend must implement,
    regardless of whether it's a cloud service, local server, or CLI tool.
    
    The interface ensures that Eye can work with any AI provider without needing to
    know the specific details of how to communicate with it. Each backend handles
    the translation between Eye's standard format and the provider's specific API.
    """
    
    @abstractmethod
    def generate(
        self, 
        system_prompt: str, 
        user_message: str,
        tools: Optional[List[Dict]] = None,
        history: Optional[List[Dict[str, Any]]] = None
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
                - 'model': Model name/ID
                - 'quota_info': Human-readable quota status
                  (e.g., "1000 requests remaining" or "Unlimited (local)")
        
        Note:
            Not all backends support quota tracking. Local backends typically return
            "Unlimited (local)" since there's no external rate limiting.
        
        Example:
            models_with_quota = backend.get_models_with_quota()
            for model_info in models_with_quota:
                print(f"{model_info['model']}: {model_info['quota_info']}")
            
            # Output:
            # gpt-4: 500 requests remaining (resets in 1 hour)
            # gpt-3.5-turbo: 5000 requests remaining (resets in 1 hour)
        """
        pass
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
