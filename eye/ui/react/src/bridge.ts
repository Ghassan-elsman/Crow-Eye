/**
 * QWebChannel Bridge Integration for EYE Forensic Assistant
 * 
 * This module handles the initialization and communication with the Python backend
 * through PyQt5's QWebChannel. It provides TypeScript-safe access to Python methods
 * and handles async signal updates.
 * 
 */

import type { EYEBridge } from './types';

// Extend Window interface to include QWebChannel
declare global {
  interface Window {
    qt?: {
      webChannelTransport: any;
    };
    QWebChannel?: any;
    bridge?: EYEBridge;
  }
}

/**
 * Signal listener callback types
 */
export type QueryCompleteCallback = (responseJson: string) => void;
export type ReportUpdatedCallback = (reportJson: string) => void;
export type ErrorOccurredCallback = (errorMessage: string) => void;
export type StatusUpdatedCallback = (statusMessage: string) => void;

/**
 * Bridge initialization state
 */
let bridgeInitialized = false;
let bridgeInitPromise: Promise<EYEBridge> | null = null;

/**
 * Signal listeners storage
 */
const signalListeners = {
  queryComplete: [] as QueryCompleteCallback[],
  reportUpdated: [] as ReportUpdatedCallback[],
  errorOccurred: [] as ErrorOccurredCallback[],
  statusUpdated: [] as StatusUpdatedCallback[],
};

/**
 * Initialize QWebChannel bridge connection to Python backend.
 * 
 * This function establishes the bidirectional communication channel between
 * the React frontend and PyQt5 backend. It should be called once during
 * application initialization.
 * 
 * @returns Promise that resolves to the EYEBridge interface
 * @throws Error if QWebChannel is not available or initialization fails
 */
export function initializeBridge(): Promise<EYEBridge> {
  // Return existing promise if already initializing
  if (bridgeInitPromise) {
    return bridgeInitPromise;
  }

  bridgeInitPromise = new Promise((resolve, reject) => {
    // Check if running in PyQt5 QWebEngineView
    if (!window.qt || !window.qt.webChannelTransport) {
      console.warn('QWebChannel transport not available - running in standalone mode');
      reject(new Error('QWebChannel not available'));
      return;
    }

    // Check if QWebChannel constructor is available
    if (!window.QWebChannel) {
      console.error('QWebChannel constructor not found');
      reject(new Error('QWebChannel constructor not available'));
      return;
    }

    try {
      // Initialize QWebChannel with the transport provided by PyQt5
      new window.QWebChannel(window.qt.webChannelTransport, (channel: any) => {
        // Extract bridge object from channel
        const bridge = channel.objects.bridge as EYEBridge;

        if (!bridge) {
          console.error('Bridge object not found in QWebChannel');
          reject(new Error('Bridge object not available'));
          return;
        }

        // Store bridge globally for easy access
        window.bridge = bridge;

        // Connect signal listeners
        connectSignalListeners(bridge);

        bridgeInitialized = true;
        console.log('QWebChannel bridge initialized successfully');
        resolve(bridge);
      });
    } catch (error) {
      console.error('Failed to initialize QWebChannel:', error);
      reject(error);
    }
  });

  return bridgeInitPromise;
}

/**
 * Connect signal listeners to Python backend signals.
 * 
 * The Python backend emits signals for async operations:
 * - query_complete: Emitted when a query finishes processing
 * - report_updated: Emitted when the report state changes
 * - error_occurred: Emitted when an error occurs in the backend
 * - truncation_warning: Emitted when messages are truncated/summarized
 * 
 * @param bridge The initialized EYEBridge object
 */
function connectSignalListeners(bridge: any) {
  // Connect to query_complete signal
  if (bridge.query_complete && bridge.query_complete.connect) {
    bridge.query_complete.connect((responseJson: string) => {
      console.log('Signal received: query_complete');
      signalListeners.queryComplete.forEach(callback => {
        try {
          callback(responseJson);
        } catch (error) {
          console.error('Error in query_complete callback:', error);
        }
      });
    });
  }

  // Connect to report_updated signal
  if (bridge.report_updated && bridge.report_updated.connect) {
    bridge.report_updated.connect((reportJson: string) => {
      console.log('Signal received: report_updated');
      signalListeners.reportUpdated.forEach(callback => {
        try {
          callback(reportJson);
        } catch (error) {
          console.error('Error in report_updated callback:', error);
        }
      });
    });
  }

  // Connect to error_occurred signal
  if (bridge.error_occurred && bridge.error_occurred.connect) {
    bridge.error_occurred.connect((errorMessage: string) => {
      console.log('Signal received: error_occurred');
      signalListeners.errorOccurred.forEach(callback => {
        try {
          callback(errorMessage);
        } catch (error) {
          console.error('Error in error_occurred callback:', error);
        }
      });
    });
  }

  // Connect to status_updated signal
  if (bridge.status_updated && bridge.status_updated.connect) {
    bridge.status_updated.connect((message: string) => {
      console.log('Signal received: status_updated', message);
      signalListeners.statusUpdated.forEach(callback => {
        try {
          callback(message);
        } catch (error) {
          console.error('Error in status_updated callback:', error);
        }
      });
    });
  }

  // Connect to truncation_warning signal
  if (bridge.truncation_warning && bridge.truncation_warning.connect) {
    bridge.truncation_warning.connect((warningJson: string) => {
      console.log('Signal received: truncation_warning');
      truncationWarningListeners.forEach(callback => {
        try {
          callback(warningJson);
        } catch (error) {
          console.error('Error in truncation_warning callback:', error);
        }
      });
    });
  }
}

/**
 * Register a callback for query_complete signal.
 * 
 * @param callback Function to call when query completes
 * @returns Unsubscribe function
 */
export function onQueryComplete(callback: QueryCompleteCallback): () => void {
  signalListeners.queryComplete.push(callback);
  return () => {
    const index = signalListeners.queryComplete.indexOf(callback);
    if (index > -1) {
      signalListeners.queryComplete.splice(index, 1);
    }
  };
}

/**
 * Register a callback for report_updated signal.
 * 
 * @param callback Function to call when report is updated
 * @returns Unsubscribe function
 */
export function onReportUpdated(callback: ReportUpdatedCallback): () => void {
  signalListeners.reportUpdated.push(callback);
  return () => {
    const index = signalListeners.reportUpdated.indexOf(callback);
    if (index > -1) {
      signalListeners.reportUpdated.splice(index, 1);
    }
  };
}

/**
 * Register a callback for error_occurred signal.
 * 
 * @param callback Function to call when an error occurs
 * @returns Unsubscribe function
 */
export function onErrorOccurred(callback: ErrorOccurredCallback): () => void {
  signalListeners.errorOccurred.push(callback);
  return () => {
    const index = signalListeners.errorOccurred.indexOf(callback);
    if (index > -1) {
      signalListeners.errorOccurred.splice(index, 1);
    }
  };
}

export function onStatusUpdated(callback: StatusUpdatedCallback): () => void {
  signalListeners.statusUpdated.push(callback);
  return () => {
    signalListeners.statusUpdated = signalListeners.statusUpdated.filter(cb => cb !== callback);
  };
}

/**
 * Send natural language query to backend.
 * 
 * This is a convenience wrapper around window.bridge.process_query()
 * that handles bridge availability and error cases.
 * 
 * @param query Natural language query string
 * @returns Promise resolving to JSON response string
 * @throws Error if bridge is not initialized
 */
export async function sendMessage(query: string): Promise<string> {
  if (!window.bridge) {
    throw new Error('Bridge not initialized. Call initializeBridge() first.');
  }

  try {
    const response = await window.bridge.process_query(query);
    return response;
  } catch (error) {
    console.error('Error sending message to bridge:', error);
    throw error;
  }
}

/**
 * Check if the bridge is initialized and ready.
 * 
 * @returns true if bridge is available, false otherwise
 */
export function isBridgeReady(): boolean {
  return bridgeInitialized && window.bridge !== undefined;
}

/**
 * Get the bridge instance if available.
 * 
 * @returns EYEBridge instance or undefined if not initialized
 */
export function getBridge(): EYEBridge | undefined {
  return window.bridge;
}

/**
 * Get context statistics from the backend.
 * 
 * This function retrieves conversation history statistics including
 * message count, token usage, and truncation information.
 * 
 * @returns Promise resolving to JSON string with context stats
 * @throws Error if bridge is not initialized
 */
export async function getContextStats(): Promise<string> {
  if (!window.bridge) {
    throw new Error('Bridge not initialized. Call initializeBridge() first.');
  }

  try {
    const response = await window.bridge.get_context_stats();
    return response;
  } catch (error) {
    console.error('Error getting context stats from bridge:', error);
    throw error;
  }
}

/**
 * Clear conversation history except the first message.
 * 
 * This function clears the conversation history in the backend,
 * preserving only the initial context-setting message.
 * 
 * @returns Promise resolving to JSON string with operation result
 * @throws Error if bridge is not initialized
 */
export async function clearConversationHistory(): Promise<string> {
  if (!window.bridge) {
    throw new Error('Bridge not initialized. Call initializeBridge() first.');
  }

  try {
    const response = await window.bridge.clear_conversation_history();
    return response;
  } catch (error) {
    console.error('Error clearing conversation history:', error);
    throw error;
  }
}

/**
 * Get the full conversation history from backend.
 * 
 * @returns Promise resolving to JSON string with history
 */
export async function getConversationHistory(): Promise<string> {
  if (!window.bridge) {
    throw new Error('Bridge not initialized. Call initializeBridge() first.');
  }

  try {
    const response = await window.bridge.get_conversation_history();
    return response;
  } catch (error) {
    console.error('Error getting conversation history from bridge:', error);
    throw error;
  }
}

/**
 * Request to show or hide the report pane.
 * 
 * @param visible True to show, False to hide
 */
export function setReportPaneVisible(visible: boolean): void {
  if (window.bridge && window.bridge.set_report_pane_visible) {
    window.bridge.set_report_pane_visible(visible);
  } else {
    console.warn('Bridge not available or set_report_pane_visible not supported');
  }
}

/**
 * Get the list of available models and their quota status.
 * 
 * @returns Promise resolving to an array of model objects with id and quota properties
 */
export async function getAvailableModelsWithQuota(): Promise<{id: string, quota: string}[]> {
  if (!window.bridge) {
    throw new Error('Bridge not initialized. Call initializeBridge() first.');
  }

  try {
    const responseJson = await window.bridge.get_available_models_with_quota();
    const response = JSON.parse(responseJson);
    if (response.success && response.data) {
      return response.data;
    }
    return [];
  } catch (error) {
    console.error('Error getting available models with quota:', error);
    return [];
  }
}

/**
 * Switch the actively connected AI model.
 * 
 * @param modelName The ID of the model to switch to
 * @returns Promise resolving to true if successful, false otherwise
 */
export async function switchActiveModel(modelName: string): Promise<boolean> {
  if (!window.bridge) {
    throw new Error('Bridge not initialized. Call initializeBridge() first.');
  }

  try {
    const success = await window.bridge.switch_active_model(modelName);
    return success;
  } catch (error) {
    console.error('Error switching active model:', error);
    return false;
  }
}

/**
 * Trigger the automated forensic triage report if it doesn't exist.
 * 
 * @returns Promise resolving to JSON string with operation result
 */
export async function initializeTriage(): Promise<string> {
  if (!window.bridge) {
    throw new Error('Bridge not initialized. Call initializeBridge() first.');
  }

  try {
    const response = await window.bridge.initialize_triage();
    return response;
  } catch (error) {
    console.error('Error triggering initial triage:', error);
    throw error;
  }
}

/**
 * Show the Case Context dialog in the PyQt backend.
 */
export function showCaseContext(): void {
  if (window.bridge && window.bridge.requestCaseContext) {
    window.bridge.requestCaseContext();
  }
}

/**
 * Show the Case Summary dialog in the PyQt backend.
 */
export function showCaseSummary(): void {
  if (window.bridge && window.bridge.requestCaseSummary) {
    window.bridge.requestCaseSummary();
  }
}

/**
 * Show the Settings/Onboarding wizard in the PyQt backend.
 */
export function showSettings(): void {
  if (window.bridge && window.bridge.requestSettings) {
    window.bridge.requestSettings();
  }
}

/**
 * Pin a message to prevent it from being summarized.
 * 
 * @param messageId The ID of the message to pin
 * @returns Promise resolving to JSON string with operation result
 */
export async function pinMessage(messageId: string): Promise<string> {
  if (!window.bridge) {
    throw new Error('Bridge not initialized. Call initializeBridge() first.');
  }

  try {
    const response = await window.bridge.pin_message(messageId);
    return response;
  } catch (error) {
    console.error('Error pinning message:', error);
    throw error;
  }
}

/**
 * Unpin a message to allow it to be summarized.
 * 
 * @param messageId The ID of the message to unpin
 * @returns Promise resolving to JSON string with operation result
 */
export async function unpinMessage(messageId: string): Promise<string> {
  if (!window.bridge) {
    throw new Error('Bridge not initialized. Call initializeBridge() first.');
  }

  try {
    const response = await window.bridge.unpin_message(messageId);
    return response;
  } catch (error) {
    console.error('Error unpinning message:', error);
    throw error;
  }
}

/**
 * Export the truncation audit trail to a file.
 * 
 * @param outputPath The path where the audit trail should be exported
 * @returns Promise resolving to JSON string with operation result
 */
export async function exportAuditTrail(outputPath: string): Promise<string> {
  if (!window.bridge) {
    throw new Error('Bridge not initialized. Call initializeBridge() first.');
  }

  try {
    const response = await window.bridge.export_audit_trail(outputPath);
    return response;
  } catch (error) {
    console.error('Error exporting audit trail:', error);
    throw error;
  }
}

/**
 * Update the token budget allocation.
 * 
 * @param budgetJson JSON string with new budget allocation
 * @returns Promise resolving to JSON string with operation result
 */
export async function updateTokenBudget(budgetJson: string): Promise<string> {
  if (!window.bridge) {
    throw new Error('Bridge not initialized. Call initializeBridge() first.');
  }

  try {
    const response = await window.bridge.update_token_budget(budgetJson);
    return response;
  } catch (error) {
    console.error('Error updating token budget:', error);
    throw error;
  }
}

/**
 * Signal listener callback for truncation warnings
 */
export type TruncationWarningCallback = (warningJson: string) => void;

/**
 * Storage for truncation warning listeners
 */
const truncationWarningListeners: TruncationWarningCallback[] = [];

/**
 * Register a callback for truncation_warning signal.
 * 
 * @param callback Function to call when truncation warning is emitted
 * @returns Unsubscribe function
 */
export function onTruncationWarning(callback: TruncationWarningCallback): () => void {
  truncationWarningListeners.push(callback);
  return () => {
    const index = truncationWarningListeners.indexOf(callback);
    if (index > -1) {
      truncationWarningListeners.splice(index, 1);
    }
  };
}
