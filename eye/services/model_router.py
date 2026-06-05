"""
Model Router and Backend Infrastructure for EYE AI Forensic Assistant.

This module implements a Strategy-based architectural pattern to provide a unified
interface for multiple Large Language Model (LLM) providers. It abstracts away 
the complexity of different SDKs (OpenAI, Anthropic, Google) and local 
execution methods (CLI, REST).

COMPONENTS:
1. LLMBackend (Abstract): Defines the mandatory forensic interface.
2. Provider Backends: Concrete implementations for specific AI services.
3. ModelRouter: The central controller that manages backend instantiation and routing.

"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
import logging
import requests
import json

# Import base class and backends from new organized structure
from eye.backends.base import LLMBackend
from eye.backends.cloud_api.openai_backend import OpenAIBackend
from eye.backends.cloud_api.anthropic_backend import AnthropicBackend
from eye.backends.cloud_api.gemini_backend import GeminiBackend
from eye.backends.local_server.ollama_backend import OllamaBackend
from eye.backends.local_server.lmstudio_backend import LMStudioBackend
from eye.backends.local_cli.generic_cli_backend import GenericCLIBackend
from eye.backends.local_cli.cli_profiles import get_profile, list_supported_backends


# Backend classes are now imported from their dedicated directories:
# - Cloud API backends: eye/backends/cloud_api/ (OpenAI, Anthropic, Gemini)
# - Local Server backends: eye/backends/local_server/ (Ollama, LM Studio)
# - Local CLI backends: eye/backends/local_cli/ (GenericCLIBackend)


class ModelRouter:
    """
    Central Controller for the EYE AI Assistant's investigative intelligence.
    
    The Router is responsible for:
    1. Instantiating the correct Backend based on user configuration.
    2. Providing a unified generation/discovery interface to the ContextManager.
    3. Ensuring secure model switching without accidentally changing the Agent (Backend).
    """
    def __init__(self, config, credential_manager=None):
        self.config = config
        self.credential_manager = credential_manager
        self.logger = logging.getLogger(self.__class__.__name__)
        self.backend = self._initialize_backend()

    def _initialize_backend(self):
        """
        Factory method to create the appropriate LLM strategy based on connection type.
        """
        bt = self.config.get("backend")
        mn = self.config.get("model_name")
        it = self.config.get("integration_type")
        
        # Validation for required fields - expected by tests
        if not bt:
            raise ValueError("Backend type not specified in configuration")
        if not mn:
            raise ValueError("Model name not specified in configuration")

        try:
            # Force re-inference if there's a clear mismatch to handle stale config after backend changes.
            # Persistent eye_config.json often holds a stale 'integration_type' that doesn't match a new 'backend'.
            if it and ((bt in list_supported_backends() and it != "local_cli") or \
               (bt in ["ollama", "lm_studio", "vllm"] and it not in ["local_server", "local_api"])):
                it = None

            # Infer integration_type if not explicitly provided
            if not it:
                if bt in list_supported_backends():
                    it = "local_cli"
                elif bt in ["ollama", "lm_studio", "vllm"]:
                    it = "local_server"
                else:
                    it = "cloud_api"
                self.config["integration_type"] = it
            
            # --- APPROACH 1: LOCAL CLI BACKENDS ---
            if it == "local_cli" or bt in list_supported_backends():
                profile = get_profile(bt)
                if mn in [None, "", "default", "cli-default-model"]:
                    mn = profile.get("display_name", "CLI Agent")
                    self.config["model_name"] = mn
                
                # Check for executable_path for Ollama/CLI backends if not inferred as server
                if bt == "ollama" and it == "local_cli" and not self.config.get("executable_path"):
                     raise ValueError("Executable path required for Ollama backend")
                     
                return GenericCLIBackend(self.config.get("executable_path", ""), backend_type=bt, model_name=mn)
                
            # --- APPROACH 2: DIRECT LOCAL SERVERS ---
            if it in ["local_server", "local_api"]:
                if bt == "ollama": return OllamaBackend(mn, self.config.get("executable_path", ""))
                if bt == "lm_studio": 
                    endpoint = self.config.get("api_endpoint")
                    if not endpoint:
                        raise ValueError("API endpoint required for LM Studio backend")
                    return LMStudioBackend(endpoint, mn)
                if bt == "vllm":
                    endpoint = self.config.get("api_endpoint")
                    if not endpoint:
                        raise ValueError("API endpoint required for vLLM backend")
                    return LMStudioBackend(endpoint, mn)
            
            # --- APPROACH 3: CLOUD API AGENTS ---
            if bt == "openai": 
                if not self.credential_manager:
                    raise ValueError("CredentialManager required for OpenAI backend")
                return OpenAIBackend(mn, self.credential_manager)
            if bt == "anthropic": return AnthropicBackend(mn, self.credential_manager)
            if bt == "gemini": return GeminiBackend(mn, self.credential_manager)
            
            raise ValueError(f"Unsupported forensic AI backend: {bt} (Type: {it})")
            
        except ValueError:
            # Re-raise ValueErrors as-is (expected by tests)
            raise
        except Exception as e:
            self.logger.error(f"Failed to initialize backend {bt}: {e}", exc_info=True)
            if "ModuleNotFoundError" in str(e) or "ImportError" in str(e):
                raise RuntimeError(f"EYE Assistant is missing a required dependency for the '{bt}' agent. Please check the 'Diagnostics' tool in the setup wizard. Error: {str(e)}")
            raise RuntimeError(f"EYE Assistant could not initialize the '{bt}' agent. Details: {str(e)}")

    def generate(self, system_prompt, user_message, tools=None, history=None):
        """Delegates generation to the active backend."""
        return self.backend.generate(system_prompt, user_message, tools, history)

    def validate_connectivity(self):
        """
        Checks if the currently active agent is online.
        """
        try:
            is_connected = self.backend.validate_connectivity()
        except Exception as e:
            self.logger.error(f"Connectivity validation failed: {str(e)}")
            return False

        integration_type = self.config.get("integration_type", "cloud_api")
        
        # --- APPROACH: LOCAL CLI AGENTS ---
        if integration_type == "local_cli":
            mn = self.config.get("model_name", "")
            is_generic = mn in [None, "", "default", "cli-default-model"] or "CLI Agent" in str(mn)
            
            if is_connected and is_generic and hasattr(self.backend, "list_models"):
                discovered = self.backend.list_models()
                if discovered and len(discovered) > 0:
                    target = discovered[0]
                    self.logger.info(f"Local CLI Approach: Auto-connecting to discovered model: {target}")
                    self.switch_model(target)
        
        return is_connected

    def list_models(self):
        """Lists valid model options for the currently active agent."""
        return self.backend.list_models()

    def get_context_window(self) -> Optional[int]:
        """Report the active backend model's real context window (tokens), or None.

        Delegates to the active backend's ``get_context_window`` (Gemini /
        Ollama / LM Studio self-report; others return None so the caller falls
        back to the static registry). Best-effort: never raises.
        """
        try:
            return self.backend.get_context_window()
        except Exception as e:
            self.logger.debug(f"get_context_window failed: {e}")
            return None

    def get_models_with_quota(self):
        """
        Retrieves real-time usage stats and available models for the active session.
        """
        try:
            models = self.backend.get_models_with_quota()
            
            # If the list is empty (common for newly initialized CLI agents), 
            # we force a connectivity check to trigger the discovery logic.
            if not models:
                self.logger.info("Model list empty, triggering discovery approach...")
                self.validate_connectivity()
                models = self.backend.get_models_with_quota()
                
            return models
        except Exception as e:
            self.logger.error(f"Error retrieving models with quota: {e}")
            return []

    def get_grouped_backend_options(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Aggregates available models from all configured backends into a 
        grouped structure for the UI model menu.
        """
        groups = {
            "Cloud API": [],
            "Local Server": [],
            "Local CLI": []
        }
        
        def add_opt(category, backend, model_name, label=None):
            active_bt = self.config.get("backend")
            active_mn = self.config.get("model_name")
            is_active = (backend == active_bt and model_name == active_mn)
            groups[category].append({
                "backend": backend,
                "model_name": model_name,
                "label": label or model_name,
                "is_active": is_active
            })

        # 1. Models from the CURRENT active backend (Live Discovery)
        try:
            active_bt = self.config.get("backend")
            active_models = self.list_models()
            
            # Map current backend to category
            category = "Cloud API"
            if active_bt in ["ollama", "lm_studio", "vllm"]:
                category = "Local Server"
            elif active_bt in list_supported_backends():
                category = "Local CLI"
                
            for m in active_models:
                add_opt(category, active_bt, m)
        except Exception as e:
            self.logger.error(f"Error listing active models: {e}")

        # 2. Add 'Discovery' options for other cloud backends if they have keys
        cloud_providers = [
            ("openai", "OpenAI"),
            ("anthropic", "Anthropic"),
            ("gemini", "Gemini")
        ]
        
        for bt, label in cloud_providers:
            if bt == self.config.get("backend"): continue
            
            # If we have a key, show a discovery option
            key_name = f"{bt}_api_key"
            if self.credential_manager and self.credential_manager.get_credential(key_name):
                add_opt("Cloud API", bt, "default", f"Connect to {label}...")

        # 3. Add Local Server options if not active
        local_servers = [
            ("ollama", "Ollama"),
            ("lm_studio", "LM Studio"),
            ("vllm", "vLLM")
        ]
        for bt, label in local_servers:
            if bt == self.config.get("backend"): continue
            add_opt("Local Server", bt, "default", f"Connect to {label}...")
            
        return groups

    def switch_model(self, model_name: str, backend: Optional[str] = None):
        """
        Updates the active model and optionally switches the backend provider.
        """
        old_bt = self.config.get("backend")
        target_model = model_name.strip()
        
        if backend and backend != old_bt:
            self.logger.info(f"Switching backend from {old_bt} to {backend}")
            self.config["backend"] = backend
            # Reset integration_type to trigger re-inference in _initialize_backend
            self.config["integration_type"] = None
        
        # Update model_name for the next initialization
        self.config["model_name"] = target_model
        
        # Re-initialize the specific backend strategy
        self.backend = self._initialize_backend()
        self.logger.info(f"Forensic Agent switched to {self.config.get('backend')}:{target_model}")
