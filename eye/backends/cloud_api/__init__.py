"""
Cloud API Backends: Talking to AI in the Cloud

This package contains backends that connect to AI services running in the cloud using their 
official SDKs. Think of this as the "phone call" approach - you send your forensic questions 
over the internet and get smart answers back from powerful cloud-based AI models.

How Cloud API Works:
--------------------
1. **Structured Communication**: We package up your question, chat history, and available 
   forensic tools into a clean JSON request
2. **Official SDKs**: We use each provider's official Python library (OpenAI's SDK, 
   Anthropic's SDK, Google's genai library) which handles all the HTTP complexity for us
3. **Native Function Calling**: The AI can directly invoke forensic tools like query_database 
   or search_artifacts - the API returns structured tool calls as JSON objects
4. **Quota Tracking**: We monitor your usage limits by reading HTTP headers, so you always 
   know how many requests you have left

Available Backends:
-------------------
- **OpenAIBackend**: Connects to OpenAI's GPT models (GPT-4, GPT-3.5, etc.)
  - Best for: Deep reasoning and complex forensic analysis
  - Tool calling: Native function calling with JSON Schema
  
- **AnthropicBackend**: Connects to Anthropic's Claude models (Claude 3, Claude 2, etc.)
  - Best for: Long context analysis and detailed report generation
  - Tool calling: Native tool-use schema with automatic conversion
  
- **GeminiBackend**: Connects to Google's Gemini models (Gemini 1.5 Pro, etc.)
  - Best for: Multimodal analysis and fast responses
  - Tool calling: Native function calling with Google's format

When to Use Cloud API:
----------------------
✓ You need the most powerful AI models for complex forensic analysis
✓ You have internet connectivity and can send data to the cloud
✓ You want the fastest setup (just need an API key)
✓ You need reliable, production-grade AI with high uptime

When NOT to Use Cloud API:
---------------------------
✗ Your forensic data must stay 100% local (use Local Server or Local CLI instead)
✗ You're working in an air-gapped environment (use Local CLI instead)
✗ You want to avoid per-request costs (use Local Server with your own models)

Example Usage:
--------------
```python
from eye.backends.cloud_api import OpenAIBackend

# Initialize with your API key
backend = OpenAIBackend(
    model_name="gpt-4",
    api_key="sk-..."
)

# Generate a response with forensic tools
response = backend.generate(
    system_prompt="You are EYE, the forensic assistant...",
    user_message="Show me all prefetch entries",
    tools=[query_database_tool, search_artifacts_tool]
)

# The AI might return tool calls to execute
if response.get("tool_calls"):
    for tool_call in response["tool_calls"]:
        print(f"AI wants to call: {tool_call['name']}")
```

Privacy Note:
-------------
When using Cloud API backends, your forensic queries and data are sent to the provider's 
servers over HTTPS. If you need to keep all data local, consider using the Local Server 
backends (Ollama, LM Studio) or Local CLI backends instead.
"""

from eye.backends.cloud_api.openai_backend import OpenAIBackend
from eye.backends.cloud_api.anthropic_backend import AnthropicBackend
from eye.backends.cloud_api.gemini_backend import GeminiBackend

__all__ = [
    'OpenAIBackend',
    'AnthropicBackend',
    'GeminiBackend',
]
