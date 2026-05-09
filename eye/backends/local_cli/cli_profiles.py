"""
CLI Profiles - Configuration for Local CLI Approach

This module contains configuration profiles for different AI CLI agents that Crow-eye can
talk to via command-line interfaces. Think of this as a "phone book" that tells us how to
call each CLI tool - what command to run, what flags to use, and how to discover models.

The Local CLI approach is the "letter under the door" method - we write everything down
in text, pipe it to a subprocess, and read what it prints back. This configuration makes
the GenericCLIBackend extensible without hardcoding logic for each agent.

Each profile defines:
- display_name: Human-friendly name shown in the UI
- default_executable: The command to run (e.g., "gemini", "llama-cli")
- default_flags: Command-line flags to pass
- model_flag: How to specify which model to use
- discovery_method: How to find available models ("probe" means we try running it)
- model_pattern: Regex to extract model names from output
- use_stdin: Whether to pipe input via stdin (almost always True)
- description: What this CLI tool is for
"""

from typing import Dict, Any, List

CLI_PROFILES: Dict[str, Dict[str, Any]] = {
    "gemini_cli": {
        "display_name": "Gemini CLI",
        "default_executable": "gemini",
        "default_flags": ["--yolo", "-p", "Respond to forensic request:"],
        "model_flag": "--model",
        "discovery_method": "probe",
        "model_pattern": r"((?:gemini|meta|mistral|claude|gpt)-[a-z0-9.-]*(?:flash|pro|haiku|sonnet|opus|llama|preview|exp)[a-z0-9.-]*)",
        "use_stdin": True,
        "description": "Google's Gemini CLI agent"
    },
    "llama": {
        "display_name": "Llama.cpp",
        "default_executable": "llama-cli",
        "default_flags": ["-p"],
        "model_flag": "-m",
        "system_flag": "--system-prompt",
        "discovery_method": "probe",
        "use_stdin": True,
        "description": "Local LLaMA models via llama.cpp"
    },
    "claude_code": {
        "display_name": "Claude Code",
        "default_executable": "claude",
        "default_flags": ["--prompt"],
        "model_flag": "--model",
        "system_flag": "--system-prompt",
        "discovery_method": "probe",
        "model_pattern": r"(claude-[a-z0-9.-]+)",
        "use_stdin": True,
        "description": "Anthropic's Claude Code CLI"
    },
    "jules_cli": {
        "display_name": "Jules CLI",
        "default_executable": "jules",
        "default_flags": ["-p"],
        "model_flag": "-m",
        "system_flag": "--system",
        "discovery_method": "probe",
        "use_stdin": True,
        "description": "Multi-model CLI supporting GPT and others"
    },
    "gpt_cli": {
        "display_name": "ChatGPT CLI (aichat/gpt-cli)",
        "default_executable": "aichat",
        "default_flags": ["-p"],
        "use_stdin": True,
        "description": "Common CLI interfaces for ChatGPT models"
    },
    "ollama_cli": {
        "display_name": "Ollama CLI",
        "default_executable": "ollama",
        "default_flags": ["run", "llama3"],
        "use_stdin": True,
        "description": "Local models via Ollama CLI"
    },
    "custom_cli": {
        "display_name": "Custom CLI Agent",
        "default_executable": "",
        "default_flags": [],
        "use_stdin": True,
        "description": "Manually configured CLI agent"
    }
}

def get_profile(backend_type: str) -> Dict[str, Any]:
    """
    Retrieve a CLI profile by its backend ID, falling back to custom if not found.
    
    This is like looking up someone in a phone book - if we know their name (backend_type),
    we get their contact info (profile). If we don't recognize the name, we give back the
    "custom_cli" profile which is a blank template you can fill in yourself.
    
    Args:
        backend_type: The ID of the CLI backend (e.g., "gemini_cli", "llama")
        
    Returns:
        Dictionary containing the profile configuration for that backend
    """
    return CLI_PROFILES.get(backend_type, CLI_PROFILES["custom_cli"])

def list_supported_backends() -> List[str]:
    """
    Return a list of all supported CLI backend IDs.
    
    This gives you all the "names in the phone book" - every CLI tool we know how to talk to.
    Useful for checking if a backend_type is a CLI agent or for showing available options.
    
    Returns:
        List of backend ID strings (e.g., ["gemini_cli", "llama", "claude_code", ...])
    """
    return list(CLI_PROFILES.keys())
