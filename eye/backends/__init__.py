"""
EYE AI Backend Infrastructure - The Three Paths to AI

This package provides a unified interface for multiple LLM providers organized by connection approach.
Think of these as three different ways to have a conversation with AI:

1. **Cloud API (cloud_api/)** - The "Phone Call" Approach
   Like calling a friend on the phone - you send your question over the internet and get an answer back.
   Uses official SDKs to talk to cloud services: OpenAI (GPT-4), Anthropic (Claude), Google (Gemini).
   Great for: Maximum power and intelligence, don't mind sending data to the cloud.

2. **Local CLI (local_cli/)** - The "Letter Under the Door" Approach
   Like writing a letter and sliding it under a door - you write everything down, pass it to a program,
   and read what it writes back. Uses command-line tools: gemini-cli, llama-cli, claude-code.
   Great for: Privacy-focused analysis, experimental tools, air-gapped environments.

3. **Local Server (local_server/)** - The "Office Assistant" Approach (The Hybrid)
   Like having a smart assistant in your office - they're always there, you can talk to them anytime,
   and they remember context. Connects to local AI services: Ollama, LM Studio.
   Great for: Best of both worlds - structured communication like Cloud API, but data stays local.
   Can run on the same machine (localhost) or a dedicated AI server in your lab (LAN).

All backends inherit from LLMBackend and implement the same interface, making them
interchangeable from Eye's perspective. You can switch between them without changing
your forensic analysis code.
"""

from eye.backends.base import LLMBackend

# Cloud API backends - Native SDK-based cloud services
from eye.backends.cloud_api.openai_backend import OpenAIBackend
from eye.backends.cloud_api.anthropic_backend import AnthropicBackend
from eye.backends.cloud_api.gemini_backend import GeminiBackend, CloudBackend

# Local Server backends - REST API services running locally or on LAN
from eye.backends.local_server.ollama_backend import OllamaBackend
from eye.backends.local_server.lmstudio_backend import LMStudioBackend

# Local CLI backends - Command-line executable wrappers
from eye.backends.local_cli.generic_cli_backend import GenericCLIBackend
from eye.backends.local_cli.cli_profiles import get_profile, list_supported_backends

__all__ = [
    # Base class
    'LLMBackend',
    
    # Cloud API backends
    'OpenAIBackend',
    'AnthropicBackend',
    'GeminiBackend',
    'CloudBackend',  # Backward compatibility alias for GeminiBackend
    
    # Local Server backends
    'OllamaBackend',
    'LMStudioBackend',
    
    # Local CLI backends
    'GenericCLIBackend',
    'get_profile',
    'list_supported_backends'
]
