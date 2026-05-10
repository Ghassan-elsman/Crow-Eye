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
        
        try:
            # Infer integration_type if not explicitly provided
            if not it:
                if bt in list_supported_backends():
                    it = "local_cli"
                elif bt in ["ollama", "lm_studio"]:
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
                return GenericCLIBackend(self.config.get("executable_path", ""), backend_type=bt, model_name=mn)
                
            # --- APPROACH 2: DIRECT LOCAL SERVERS ---
            if it in ["local_server", "local_api"]:
                if bt == "ollama": return OllamaBackend(mn, self.config.get("executable_path", ""))
                if bt == "lm_studio": return LMStudioBackend(self.config.get("api_endpoint", ""), mn)
            
            # --- APPROACH 3: CLOUD API AGENTS ---
            if bt == "openai": return OpenAIBackend(mn, self.credential_manager)
            if bt == "anthropic": return AnthropicBackend(mn, self.credential_manager)
            if bt == "gemini": return GeminiBackend(mn, self.credential_manager)
            
            raise ValueError(f"Unsupported forensic AI backend: {bt} (Type: {it})")
            
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
        
        This method handles two distinct approaches based on 'integration_type':
        1. LOCAL CLI AGENTS: Checks if the executable exists and performs an 
           'Auto-Discovery' phase to find valid models if the user hasn't selected one.
        2. CLOUD AGENTS / OTHERS: Validates the API key and service reachability.
        """
        is_connected = self.backend.validate_connectivity()
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
        
        # --- APPROACH: CLOUD / REMOTE AGENTS ---
        # Cloud backends typically handle their own validation during self.backend.validate_connectivity()
                
        return is_connected

    def list_models(self):
        """Lists valid model options for the currently active agent."""
        return self.backend.list_models()

    def get_models_with_quota(self):
        """
        Retrieves real-time usage stats and available models for the active session.
        
        Approach differs by backend type:
        - CLI AGENTS: Models are discovered via probing; quota is 'Unlimited (Local)'.
        - CLOUD AGENTS: Models are fetched via API; quota is parsed from HTTP headers.
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

    def switch_model(self, model_name: str):
        """
        Updates the active model name strictly within the currently configured backend.
        
        SECURITY NOTE: To prevent accidental data leakage or cost shifts, this method 
        CANNOT change the Backend (Agent) type. Backend changes must be initiated 
        manually via the EYE Settings/Wizard.
        """
        old_bt = self.config.get("backend")
        target_model = model_name.strip()
        
        # Update model_name for the next initialization
        self.config["model_name"] = target_model
        
        # Re-initialize the specific backend strategy with the same agent type
        self.backend = self._initialize_backend()
        self.logger.info(f"Forensic Agent {old_bt} switched to model: {target_model}")
