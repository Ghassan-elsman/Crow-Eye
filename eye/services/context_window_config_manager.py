"""
Context Window Configuration Manager for EYE AI Forensic Assistant.

This module manages context window configuration with validation and persistence.
It handles loading presets, validating configurations, and saving to eye_config.json.

"""

import json
from pathlib import Path
from typing import Dict, Any


class ContextWindowConfigManager:
    """Manages context window configuration with validation and persistence."""
    
    def __init__(self, config_dir: str = "configs"):
        """
        Initialize configuration manager.
        
        Args:
            config_dir: Directory containing configuration files
        """
        self.config_dir = Path(config_dir)
        self.eye_config_path = self.config_dir / "eye_config.json"
        self.presets_path = self.config_dir / "context_window_presets.json"
        self.presets = self._load_presets()
    
    def _load_presets(self) -> Dict[str, Any]:
        """
        Load context window presets from file.
        
        Returns:
            Dict containing presets and history_management_defaults
            
        Raises:
            FileNotFoundError: If presets file doesn't exist
        """
        if not self.presets_path.exists():
            raise FileNotFoundError(f"Presets file not found: {self.presets_path}")
        
        with open(self.presets_path, 'r') as f:
            return json.load(f)
    
    def get_config_for_backend(self, backend: str) -> Dict[str, Any]:
        """
        Get context window configuration for backend.
        
        Tries to load from eye_config.json first, falls back to preset.
        
        Args:
            backend: LLM backend name (e.g., "gpt-4", "ollama")
            
        Returns:
            Context window configuration dict with keys:
            - max_total_tokens
            - token_budget
            - history_management
        """
        # Start from the full preset so the returned config ALWAYS has the keys
        # the dialog requires (max_total_tokens, token_budget.*, history_management.*).
        base = self._get_preset_for_backend(backend)

        # Overlay any stored context_window. The Eye-AI settings panel writes a
        # PARTIAL context_window (e.g. only max_total_tokens + store_full_payload),
        # so we deep-merge token_budget / history_management key-by-key instead of
        # returning the partial dict verbatim (which would KeyError in the dialog).
        if self.eye_config_path.exists():
            try:
                with open(self.eye_config_path, 'r') as f:
                    eye_config = json.load(f)
                stored = eye_config.get("context_window")
            except Exception:
                stored = None
            if isinstance(stored, dict):
                merged = dict(base)
                for key, value in stored.items():
                    if key in ("token_budget", "history_management") and isinstance(value, dict):
                        merged[key] = {**base.get(key, {}), **value}
                    else:
                        merged[key] = value
                return merged

        return base
    
    def _get_preset_for_backend(self, backend: str) -> Dict[str, Any]:
        """
        Get preset configuration for backend.
        
        Args:
            backend: Backend name
            
        Returns:
            Preset configuration with history_management defaults added
        """
        preset = self.presets["presets"].get(backend)
        if not preset:
            # Default to ollama preset for unknown backends
            preset = self.presets["presets"]["ollama"]
        
        # Add history management defaults
        config = preset.copy()
        config["history_management"] = self.presets["history_management_defaults"]
        
        return config
    
    def save_config(self, config: Dict[str, Any]) -> None:
        """
        Save context window configuration to eye_config.json.
        
        Validates configuration before saving. Updates only the context_window
        section of eye_config.json, preserving other settings.
        
        Args:
            config: Context window configuration dict
            
        Raises:
            ValueError: If configuration validation fails
        """
        # Validate configuration
        self._validate_config(config)
        
        # Load existing eye_config.json
        if self.eye_config_path.exists():
            with open(self.eye_config_path, 'r') as f:
                eye_config = json.load(f)
        else:
            eye_config = {}
        
        # Merge into the existing context_window (don't replace it) so keys the
        # Eye-AI settings panel owns — store_full_payload,
        # sealed_payload_recent_uncompressed, evidence_preservation, … — survive
        # a save from this advanced dialog.
        existing = eye_config.get("context_window")
        if isinstance(existing, dict):
            existing.update(config)
            eye_config["context_window"] = existing
        else:
            eye_config["context_window"] = config

        # Save back to file
        with open(self.eye_config_path, 'w') as f:
            json.dump(eye_config, f, indent=2)
    
    def _validate_config(self, config: Dict[str, Any]) -> None:
        """
        Validate context window configuration.
        
        - Required fields exist
        - Positive integers for token values
        - Budget sum doesn't exceed max_total_tokens
        - Boolean fields are booleans
        - Truncation strategy is valid
        
        Args:
            config: Configuration dict to validate
            
        Raises:
            ValueError: If configuration is invalid
        """
        # Required fields
        required_fields = ["max_total_tokens", "token_budget", "history_management"]
        for field in required_fields:
            if field not in config:
                raise ValueError(f"Missing required field: {field}")
        
        # Validate max_total_tokens
        if not isinstance(config["max_total_tokens"], int) or config["max_total_tokens"] <= 0:
            raise ValueError("max_total_tokens must be a positive integer")
        
        # Validate token_budget
        budget = config["token_budget"]
        required_budget_fields = [
            "system_prompt", "rag_context", "conversation_history",
            "tool_definitions", "response_buffer"
        ]
        for field in required_budget_fields:
            if field not in budget:
                raise ValueError(f"Missing token_budget field: {field}")
            if not isinstance(budget[field], int) or budget[field] < 0:
                raise ValueError(f"token_budget.{field} must be a non-negative integer")
        
        # Validate budget sum doesn't exceed max_total_tokens
        budget_sum = sum(budget.values())
        if budget_sum > config["max_total_tokens"]:
            raise ValueError(
                f"Token budget sum ({budget_sum}) exceeds max_total_tokens "
                f"({config['max_total_tokens']})"
            )
        
        # Validate history_management
        history = config["history_management"]
        required_history_fields = [
            "sliding_window_size", "preserve_first_message",
            "preserve_tool_messages", "truncation_strategy"
        ]
        for field in required_history_fields:
            if field not in history:
                raise ValueError(f"Missing history_management field: {field}")
        
        # Validate sliding_window_size
        if not isinstance(history["sliding_window_size"], int) or history["sliding_window_size"] <= 0:
            raise ValueError("sliding_window_size must be a positive integer")
        
        # Validate boolean fields
        for field in ["preserve_first_message", "preserve_tool_messages"]:
            if not isinstance(history[field], bool):
                raise ValueError(f"history_management.{field} must be a boolean")
        
        # Validate truncation_strategy
        valid_strategies = ["sliding_window", "summarization", "none"]
        if history["truncation_strategy"] not in valid_strategies:
            raise ValueError(
                f"Invalid truncation_strategy: {history['truncation_strategy']}. "
                f"Must be one of: {valid_strategies}"
            )
    
    def get_available_presets(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all available presets.
        
        Returns:
            Dict mapping backend names to preset configurations
        """
        return self.presets["presets"]
    
    def apply_preset(self, backend: str) -> Dict[str, Any]:
        """
        Apply preset for backend and save to eye_config.json.
        
        Args:
            backend: Backend name to apply preset for
            
        Returns:
            Applied configuration
        """
        config = self._get_preset_for_backend(backend)
        self.save_config(config)
        return config
