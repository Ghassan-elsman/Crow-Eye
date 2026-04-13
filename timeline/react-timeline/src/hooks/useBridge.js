/**
 * useBridge — Hook wrapping QWebChannel bridge calls.
 * 
 * In production (inside QWebEngineView), window.bridge is set by QWebChannel.
 * In development, it falls back to mock data.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

// FIX: Bug 12 - Bridge Connection Race Condition
// Implements singleton pattern with timeout and retry logic to prevent race conditions
// Ensures reliable bridge initialization even with slow network or multiple component mounts
// Singleton pattern: module-level promise to prevent multiple simultaneous initializations
let bridgePromise = null;

/**
 * Wait for QWebChannel bridge to be available with timeout and retry logic.
 * Implements singleton pattern to prevent race conditions.
 * 
 * @param {number} attempt - Current retry attempt (1-based)
 * @returns {Promise<object|null>} Bridge object or null if failed
 */
function waitForBridge(attempt = 1) {
  const MAX_RETRIES = 3;
  const TIMEOUT_MS = 10000; // 10 seconds
  const RETRY_DELAYS = [1000, 2000, 4000]; // Exponential backoff: 1s, 2s, 4s

  // Return existing promise if initialization already in progress (singleton pattern)
  if (bridgePromise) {
    return bridgePromise;
  }

  bridgePromise = new Promise((resolve) => {
    // Check if bridge already exists
    if (window.bridge) {
      console.log('[useBridge] Bridge already initialized');
      resolve(window.bridge);
      return;
    }

    let timeoutId = null;
    let resolved = false;

    // Timeout handler
    const handleTimeout = () => {
      if (resolved) return;
      resolved = true;
      
      console.warn(`[useBridge] Bridge initialization timeout (attempt ${attempt}/${MAX_RETRIES})`);
      
      // Retry with exponential backoff
      if (attempt < MAX_RETRIES) {
        const delay = RETRY_DELAYS[attempt - 1];
        console.log(`[useBridge] Retrying in ${delay}ms...`);
        
        // Reset singleton promise for retry
        bridgePromise = null;
        
        setTimeout(() => {
          waitForBridge(attempt + 1).then(resolve);
        }, delay);
      } else {
        console.warn('[useBridge] Max retries reached, falling back to dev mode');
        resolve(null);
      }
    };

    // Set timeout
    timeoutId = setTimeout(handleTimeout, TIMEOUT_MS);

    // Load qwebchannel.js from the Qt internal resource
    const script = document.createElement('script');
    script.src = 'qrc:///qtwebchannel/qwebchannel.js';
    
    script.onload = () => {
      if (resolved) return;
      
      try {
        if (window.QWebChannel && window.qt && window.qt.webChannelTransport) {
          new window.QWebChannel(window.qt.webChannelTransport, (channel) => {
            if (resolved) return;
            resolved = true;
            clearTimeout(timeoutId);
            
            window.bridge = channel.objects.bridge;
            console.log('[useBridge] Bridge initialized successfully');
            resolve(window.bridge);
          });
        } else {
          if (resolved) return;
          resolved = true;
          clearTimeout(timeoutId);
          
          console.warn('[useBridge] QWebChannel loaded but transport not found.');
          resolve(null);
        }
      } catch (error) {
        if (resolved) return;
        resolved = true;
        clearTimeout(timeoutId);
        
        console.error('[useBridge] Error creating QWebChannel:', error);
        resolve(null);
      }
    };
    
    script.onerror = () => {
      if (resolved) return;
      resolved = true;
      clearTimeout(timeoutId);
      
      console.warn('[useBridge] No QWebChannel script available (qrc:// failed) — using dev mode');
      resolve(null);
    };
    
    document.head.appendChild(script);
  });

  return bridgePromise;
}

/**
 * Hook to access the QWebChannel bridge.
 * Returns { bridge, isLoading, isDev } 
 */
export function useBridge() {
  const [bridge, setBridge] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isDev, setIsDev] = useState(false);

  useEffect(() => {
    waitForBridge().then((b) => {
      if (b) {
        setBridge(b);
      } else {
        setIsDev(true);
      }
      setIsLoading(false);
    });
  }, []);

  /**
   * Call a bridge method. Returns parsed JSON.
   * In dev mode, returns null.
   */
  const callBridge = useCallback(async (method, ...args) => {
    if (!bridge) return null;

    return new Promise((resolve, reject) => {
      try {
        // QWebChannel slots return via callback
        const result = bridge[method](...args);
        // PyQt slots can return synchronously or via callback
        if (typeof result === 'string') {
          resolve(JSON.parse(result));
        } else if (result && typeof result.then === 'function') {
          result.then(r => resolve(JSON.parse(r))).catch(reject);
        } else {
          resolve(result);
        }
      } catch (e) {
        console.error(`[Bridge] Error calling ${method}:`, e);
        reject(e);
      }
    });
  }, [bridge]);

  return { bridge, callBridge, isLoading, isDev };
}
