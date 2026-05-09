"""
Token Counter Service for EYE AI Forensic Assistant

This module provides token counting and text truncation utilities for managing
LLM context windows across different backends.


"""

import logging
from typing import Optional

try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    logging.warning("tiktoken not available, using character-based estimation")


class TokenCounter:
    """
    Utility for counting tokens compatible with different LLM backends.
    
    Uses tiktoken library for accurate token counting when available,
    with fallback to character-based estimation (~4 characters per token).
    
    Attributes:
        backend: LLM backend name (e.g., "gpt-4", "claude-2", "ollama")
        encoding: tiktoken encoding object (if available)
    """
    
    # Mapping of backend names to tiktoken encoding names
    ENCODING_MAP = {
        "gpt-4": "cl100k_base",
        "gpt-4-32k": "cl100k_base",
        "gpt-4-turbo": "cl100k_base",
        "gpt-3.5-turbo": "cl100k_base",
        "claude-2": "cl100k_base",  # Approximate
        "claude-3": "cl100k_base",  # Approximate
        "gemini-pro": "cl100k_base",  # Approximate
        "gemini": "cl100k_base",  # Approximate
        "ollama": "cl100k_base",  # Approximate
        "llama": "cl100k_base",  # Approximate
        "lm_studio": "cl100k_base",  # Approximate
        "vllm": "cl100k_base",  # Approximate
        "openai": "cl100k_base",
        "anthropic": "cl100k_base",  # Approximate
    }
    
    # Character-to-token ratio for fallback estimation
    CHARS_PER_TOKEN = 4
    
    def __init__(self, backend: str = "gpt-4"):
        """
        Initialize token counter for specific backend.
        
        Args:
            backend: LLM backend name (gpt-4, claude-2, ollama, etc.)
        """
        self.backend = backend
        self.logger = logging.getLogger(__name__)
        self.encoding = self._get_encoding()
        
        if not TIKTOKEN_AVAILABLE:
            self.logger.warning(
                f"TokenCounter initialized for {backend} without tiktoken. "
                "Using character-based estimation."
            )
    
    def _get_encoding(self) -> Optional[object]:
        """
        Get tiktoken encoding for backend.
        
        Returns:
            tiktoken encoding object if available, None otherwise
        """
        if not TIKTOKEN_AVAILABLE:
            return None
        
        encoding_name = self.ENCODING_MAP.get(self.backend, "cl100k_base")
        
        try:
            return tiktoken.get_encoding(encoding_name)
        except Exception as e:
            self.logger.error(
                f"Failed to load tiktoken encoding '{encoding_name}': {e}"
            )
            return None
    
    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text.
        
        Uses tiktoken for accurate counting when available, otherwise falls back
        to character-based estimation (~4 characters per token).
        
        Args:
            text: Text to count tokens for
            
        Returns:
            Number of tokens (estimated if tiktoken unavailable)
        """
        if not text:
            return 0
        
        # Try tiktoken first
        if self.encoding is not None:
            try:
                tokens = self.encoding.encode(text)
                return len(tokens)
            except Exception as e:
                self.logger.warning(
                    f"tiktoken encoding failed: {e}. Using fallback estimation."
                )
        
        # Fallback: character-based estimation
        return len(text) // self.CHARS_PER_TOKEN
    
    def truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        """
        Truncate text to fit within token limit.
        
        Uses tiktoken for token-aware truncation when available, otherwise falls
        back to character-based truncation.
        
        Args:
            text: Text to truncate
            max_tokens: Maximum number of tokens
            
        Returns:
            Truncated text that fits within max_tokens
        """
        if not text:
            return text
        
        if max_tokens <= 0:
            return ""
        
        # Try tiktoken first
        if self.encoding is not None:
            try:
                tokens = self.encoding.encode(text)
                
                # Already within limit
                if len(tokens) <= max_tokens:
                    return text
                
                # Truncate tokens and decode
                truncated_tokens = tokens[:max_tokens]
                return self.encoding.decode(truncated_tokens)
                
            except Exception as e:
                self.logger.warning(
                    f"tiktoken truncation failed: {e}. Using fallback truncation."
                )
        
        # Fallback: character-based truncation
        estimated_chars = max_tokens * self.CHARS_PER_TOKEN
        return text[:estimated_chars]

    def truncate_text(self, text: str, max_tokens: int) -> str:
        """Alias for truncate_to_tokens."""
        return self.truncate_to_tokens(text, max_tokens)
