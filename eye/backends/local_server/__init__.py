"""
Local Server Backends: The "Hybrid" Approach - Best of Both Worlds

This package contains backends that connect to local AI "hubs" running as persistent 
background services with REST APIs. Think of this as the "office assistant" approach - 
they're always there, you can talk to them anytime, and everything stays local.

WHY USE LOCAL SERVER?
=====================
This is the most "professional" way to run local AI in Eye because it combines the best 
features of both Cloud API and Local CLI:

✓ **Structured Communication**: Uses modern web standards (JSON/REST) like Cloud API
✓ **Local Privacy**: All data stays within your local network (never goes to cloud)
✓ **Network Flexibility**: Can run on same machine (localhost) or dedicated AI server (LAN)
✓ **Persistent Service**: Always running in background (no process start overhead)
✓ **Native Function Calling**: Supports structured tool calls (no XML extraction needed)
✓ **High Stability**: Reliable, production-grade local AI deployment

HOW IT WORKS (The "Hybrid" Method)
===================================
1. **Background Service**: Ollama or LM Studio runs as a persistent service (like a web server)
2. **HTTP Communication**: We send JSON requests over HTTP (just like Cloud API, but local)
3. **Structured Responses**: The service returns clean JSON with content and tool_calls
4. **Connection Pooling**: We reuse HTTP connections for better performance
5. **Retry Logic**: Automatic retry with exponential backoff for transient failures

NETWORK DEPLOYMENT OPTIONS
===========================
**Same Machine (Localhost)**:
- Endpoint: http://localhost:11434 (Ollama) or http://localhost:1234 (LM Studio)
- Use case: Simple setup, AI runs on your forensic workstation
- Privacy: 100% local, never leaves your machine

**Different Machine (LAN)**:
- Endpoint: http://192.168.1.100:11434 (your AI server's IP)
- Use case: Dedicated AI server in your lab, forensic workstation connects to it
- Privacy: Data stays within your local network, never goes to internet
- Benefits: Offload AI processing, share AI server across multiple workstations

AVAILABLE BACKENDS
==================
**OllamaBackend**: Connects to Ollama service (default port 11434)
- Best for: Running open-source models locally (Llama 3, Mistral, etc.)
- Tool calling: Native function calling (model-dependent)
- Models: Download from Ollama library (ollama pull llama3)
- Setup: Install Ollama, run `ollama serve`, point Eye at http://localhost:11434

**LMStudioBackend**: Connects to LM Studio service (default port 1234)
- Best for: User-friendly local AI with GUI model management
- Tool calling: OpenAI-compatible function calling
- Models: Download via LM Studio's GUI
- Setup: Install LM Studio, start local server, point Eye at http://localhost:1234

ENHANCED FEATURES
=================
Both backends include production-grade enhancements:
- **Connection Pooling**: Reuses HTTP connections for 10x faster requests
- **Retry Logic**: Exponential backoff (1s, 2s, 4s) for transient failures
- **Error Handling**: Catches ConnectionError, Timeout, HTTPError with helpful messages
- **Health Checks**: Validates service is running before sending requests
- **Configurable Timeouts**: 5s to connect, 120s for complex forensic queries

COMPARISON TO OTHER APPROACHES
===============================
**Cloud API** (cloud_api/):
- Pros: Most powerful models, fastest setup (just API key)
- Cons: Data goes to cloud, requires internet, per-request costs

**Local CLI** (local_cli/):
- Pros: Maximum privacy (air-gapped), simple setup (just executable)
- Cons: Text-based protocol (XML), process spawn overhead, same machine only

**Local Server** (this package):
- Pros: Structured JSON (like Cloud API) + Local privacy (like CLI) + LAN support
- Cons: Requires persistent service, slightly more complex setup than CLI

WHEN TO USE LOCAL SERVER
=========================
✓ You want local AI with modern, reliable communication (JSON/REST)
✓ You need to keep forensic data within your local network
✓ You want to run AI on a dedicated server in your lab (LAN deployment)
✓ You need production-grade stability and performance
✓ You want native function calling (no XML extraction)

✗ You need the absolute most powerful models (use Cloud API instead)
✗ You're working in a completely air-gapped environment (use Local CLI instead)
✗ You want the simplest possible setup (use Local CLI instead)

EXAMPLE USAGE
=============
```python
from eye.backends.local_server import OllamaBackend

# Same machine deployment
backend = OllamaBackend(
    model_name="llama3:latest",
    api_endpoint="http://localhost:11434"
)

# Or LAN deployment (dedicated AI server)
backend = OllamaBackend(
    model_name="llama3:latest",
    api_endpoint="http://192.168.1.100:11434"  # Your AI server's IP
)

# Generate a response with forensic tools
response = backend.generate(
    system_prompt="You are EYE, the forensic assistant...",
    user_message="Show me all prefetch entries",
    tools=[query_database_tool, search_artifacts_tool]
)

# The AI returns structured tool calls (no XML extraction needed!)
if response.get("tool_calls"):
    for tool_call in response["tool_calls"]:
        print(f"AI wants to call: {tool_call['function']['name']}")
```

TECHNICAL DETAILS
=================
**Ollama API**:
- Endpoint: http://<host>:11434/api/chat
- Format: JSON with messages array and tools
- Tool calling: Native (model-dependent, works with Llama 3, Mistral, etc.)
- Health check: GET /api/tags

**LM Studio API**:
- Endpoint: http://<host>:1234/v1/chat/completions
- Format: OpenAI-compatible JSON
- Tool calling: OpenAI-compatible function calling
- Health check: GET /v1/models

**Connection Pooling**:
- Uses requests.Session() with HTTPAdapter
- Pool size: 10 connections per host, max 20 connections
- Retry strategy: 3 attempts with exponential backoff

**Error Handling**:
- ConnectionError: "Cannot reach Ollama at <endpoint>. Is the service running?"
- Timeout: "Request timed out after 120s. Try a simpler query or faster model."
- HTTPError: "Ollama returned error: <status> - <message>"

SETUP GUIDE
===========
**Ollama Setup**:
1. Install: https://ollama.ai/download
2. Pull a model: `ollama pull llama3`
3. Start service: `ollama serve` (or it auto-starts)
4. Configure Eye: Point to http://localhost:11434

**LM Studio Setup**:
1. Install: https://lmstudio.ai/
2. Download models via GUI
3. Start local server (button in GUI)
4. Configure Eye: Point to http://localhost:1234

**LAN Deployment**:
1. Install Ollama/LM Studio on dedicated server
2. Start service and note server's IP (e.g., 192.168.1.100)
3. Configure Eye on forensic workstation: http://192.168.1.100:11434
4. Ensure firewall allows connections on port 11434/1234

"""

from eye.backends.local_server.ollama_backend import OllamaBackend
from eye.backends.local_server.lmstudio_backend import LMStudioBackend

__all__ = ['OllamaBackend', 'LMStudioBackend']
