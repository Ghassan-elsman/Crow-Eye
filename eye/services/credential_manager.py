"""
Credential Manager for EYE AI Forensic Assistant.

This module provides a unified, thread-safe interface for secure credential storage 
across Windows, macOS, and Linux. It serves as the primary vault for API keys 
(OpenAI, Anthropic, Google) used by the AI backends.

DESIGN RATIONALE:
The 'keyring' library can occasionally hang indefinitely if the OS-native 
credential manager (e.g., Windows Vault) is locked or unresponsive. To prevent 
this from hanging the entire EYE Assistant UI, this manager implements:
1. Lazy Importing: 'keyring' is imported only inside background workers.
2. Daemon Threads: All OS calls are wrapped in daemon threads.
3. Safety Timeouts: Retrieval calls have a strict timeout (default 2s) to ensure responsiveness.
4. Circuit Breaker: If a hang is detected, the OS keychain is bypassed for the session.
"""

import logging
import threading
from typing import Optional, Dict


class CredentialManager:
    """
    Manages secure credential storage using OS-native keychains.
    
    Provides an OS-agnostic interface for storing and retrieving secrets.
    Optimized for forensic environments where system stability and 
    responsiveness are critical.
    """
    
    # Identifier used by the OS keychain to partition secrets for this app
    SERVICE_NAME = "CrowEye_EYE_Assistant"
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        # Local cache to avoid repeated (and potentially slow) OS keychain hits
        self._cache: Dict[str, str] = {}
        # Thread lock for memory cache access
        self._lock = threading.Lock()
        # Circuit breaker flag to disable keyring if it hangs once
        self._keyring_disabled = False 

    def store_credential(self, key: str, value: str):
        """
        Store a credential in OS-native secure storage and update the memory cache.
        
        This operation is non-blocking; the actual write to the OS keychain happens 
        in a background daemon thread.
        """
        with self._lock:
            self._cache[key] = value
            
        if self._keyring_disabled:
            self.logger.debug(f"Keyring disabled; {key} stored only in memory cache.")
            return
            
        def _store_worker():
            """Worker to perform the actual OS-level store."""
            try:
                # Lazy import to avoid blocking the main thread during module load
                import keyring
                keyring.set_password(self.SERVICE_NAME, key, value)
            except Exception as e:
                self.logger.error(f"Failed to persist credential {key} to OS keychain: {e}")
                
        # Start storage in a daemon thread so it doesn't block app exit
        threading.Thread(target=_store_worker, daemon=True).start()

    def get_credential(self, key: str, timeout: float = 2.0) -> Optional[str]:
        """
        Retrieve a credential with a mandatory safety timeout.
        
        Logic Flow:
        1. Check memory cache (Immediate).
        2. If not in cache, spawn a daemon thread to query the OS keychain.
        3. Wait for the thread up to 'timeout' seconds.
        4. If it times out, trigger the circuit breaker to stop future hangs.
        
        Args:
            key: Credential identifier (e.g., 'gemini_api_key')
            timeout: Max seconds to wait for OS keychain response.
        """
        # Step 1: Memory cache check (Fastest)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
                
        # Skip OS call if the circuit breaker is active
        if self._keyring_disabled:
            return None

        # Step 2: OS Keychain Retrieval (Potentially Slow/Blocking)
        result_container = []
        
        def _fetch_worker():
            """Worker to perform the actual OS-level fetch."""
            try:
                import keyring
                val = keyring.get_password(self.SERVICE_NAME, key)
                result_container.append(val)
            except Exception as e:
                result_container.append(e)
                
        t = threading.Thread(target=_fetch_worker, daemon=True)
        t.start()
        t.join(timeout=timeout) # Blocking join with safety timeout
        
        # Step 3: Handle Timeout (Circuit Breaker)
        if t.is_alive():
            self.logger.warning(
                f"OS Keychain timed out while fetching '{key}'. "
                "Disabling OS-native storage for this session to prevent UI hangs."
            )
            self._keyring_disabled = True
            return None
            
        # Step 4: Process Result
        if not result_container:
            return None
            
        res = result_container[0]
        if isinstance(res, Exception):
            self.logger.error(f"OS Keychain error during fetch: {res}")
            return None
            
        if res:
            with self._lock:
                self._cache[key] = res # Sync back to cache for next call
        return res

    def delete_credential(self, key: str):
        """
        Permanently delete a credential from both memory cache and OS storage.
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
        
        if self._keyring_disabled:
            return
            
        def _delete_worker():
            try:
                import keyring
                keyring.delete_password(self.SERVICE_NAME, key)
            except Exception:
                # Silently fail if key doesn't exist or keychain is locked
                pass
                
        threading.Thread(target=_delete_worker, daemon=True).start()

    def clear_all_credentials(self):
        """
        Utility to purge all forensic AI credentials.
        Used primarily during 'Log Out' or 'Reset' operations.
        """
        known_keys = ["openai_api_key", "anthropic_api_key", "gemini_api_key"]
        for key in known_keys:
            self.delete_credential(key)
