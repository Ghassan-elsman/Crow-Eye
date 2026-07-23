/**
 * QWebChannel Bridge Integration for EYE Forensic Assistant
 * 
 * This module handles the initialization and communication with the Python backend
 * through PyQt5's QWebChannel. It provides TypeScript-safe access to Python methods
 * and handles async signal updates.
 * 
 */

import type { EYEBridge, EyeDialogueEntry } from './types';

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
export type DialogueUpdatedCallback = (entryJson: string) => void;
export type NarrativeMapUpdatedCallback = (envelopeJson: string) => void;
export type NarrativeInvestigationCompleteCallback = (narrativeId: string) => void;
export type NarrativeMapFocusCallback = (cardId: string) => void;

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
  dialogueUpdated: [] as DialogueUpdatedCallback[],
  narrativeMapUpdated: [] as NarrativeMapUpdatedCallback[],
  narrativeInvestigationComplete: [] as NarrativeInvestigationCompleteCallback[],
  narrativeMapFocus: [] as NarrativeMapFocusCallback[],
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

  // Connect to dialogue_updated signal (Eye<->LLM conversation stream)
  if (bridge.dialogue_updated && bridge.dialogue_updated.connect) {
    bridge.dialogue_updated.connect((entryJson: string) => {
      signalListeners.dialogueUpdated.forEach(callback => {
        try {
          callback(entryJson);
        } catch (error) {
          console.error('Error in dialogue_updated callback:', error);
        }
      });
    });
  }

  // Connect to narrative_map_updated signal (Eye or investigator changed the map)
  if (bridge.narrative_map_updated && bridge.narrative_map_updated.connect) {
    bridge.narrative_map_updated.connect((envelopeJson: string) => {
      signalListeners.narrativeMapUpdated.forEach(callback => {
        try {
          callback(envelopeJson);
        } catch (error) {
          console.error('Error in narrative_map_updated callback:', error);
        }
      });
    });
  }

  // Connect to narrative_map_focus signal (another window asked to focus a card:
  // open/raise the map and select + open that Verdict/Narrative/Evidence detail).
  if (bridge.narrative_map_focus && bridge.narrative_map_focus.connect) {
    bridge.narrative_map_focus.connect((cardId: string) => {
      signalListeners.narrativeMapFocus.forEach(callback => {
        try {
          callback(cardId);
        } catch (error) {
          console.error('Error in narrative_map_focus callback:', error);
        }
      });
    });
  }

  // Connect to narrativeInvestigationComplete signal (a double-click investigate finished)
  if (bridge.narrativeInvestigationComplete && bridge.narrativeInvestigationComplete.connect) {
    bridge.narrativeInvestigationComplete.connect((narrativeId: string) => {
      signalListeners.narrativeInvestigationComplete.forEach(callback => {
        try {
          callback(narrativeId);
        } catch (error) {
          console.error('Error in narrativeInvestigationComplete callback:', error);
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

export function onDialogueUpdated(callback: DialogueUpdatedCallback): () => void {
  signalListeners.dialogueUpdated.push(callback);
  return () => {
    signalListeners.dialogueUpdated = signalListeners.dialogueUpdated.filter(cb => cb !== callback);
  };
}

/**
 * Register a callback for narrative_map_updated signal. The payload is a JSON
 * envelope: { kind: 'graph'|'patch', graph?, change?, audit? }.
 *
 * @returns Unsubscribe function
 */
export function onNarrativeMapUpdated(callback: NarrativeMapUpdatedCallback): () => void {
  signalListeners.narrativeMapUpdated.push(callback);
  return () => {
    signalListeners.narrativeMapUpdated = signalListeners.narrativeMapUpdated.filter(cb => cb !== callback);
  };
}

/**
 * Register a callback fired when a background "investigate this narrative" run
 * finishes (payload: the narrative id). Used to clear the per-card spinner.
 *
 * @returns Unsubscribe function
 */
export function onNarrativeInvestigationComplete(callback: NarrativeInvestigationCompleteCallback): () => void {
  signalListeners.narrativeInvestigationComplete.push(callback);
  return () => {
    signalListeners.narrativeInvestigationComplete = signalListeners.narrativeInvestigationComplete.filter(cb => cb !== callback);
  };
}

/**
 * Register a callback fired when another window (e.g. the Compliance panel) asks
 * to focus a specific Verdict/Narrative/Evidence card in this Narrative Map.
 *
 * @returns Unsubscribe function
 */
export function onNarrativeMapFocus(callback: NarrativeMapFocusCallback): () => void {
  signalListeners.narrativeMapFocus.push(callback);
  return () => {
    signalListeners.narrativeMapFocus = signalListeners.narrativeMapFocus.filter(cb => cb !== callback);
  };
}

/**
 * Ask Crow-Eye to open/raise the Narrative Map window and focus a card by id
 * (opening its detail panel). Called from the Compliance window. Fire-and-forget.
 */
export function focusNarrativeMap(cardId: string): void {
  const b = getBridge() as any;
  if (!b || typeof b.focus_narrative_map !== 'function') return;
  try {
    b.focus_narrative_map(cardId);
  } catch (error) {
    console.error('Error invoking focus_narrative_map:', error);
  }
}

/**
 * Ask the Eye to investigate a narrative further in the background. New evidence
 * attaches to that narrative; no chat bubble is posted. Fire-and-forget.
 */
export function investigateNarrative(narrativeId: string): void {
  const b = getBridge() as any;
  if (!b || typeof b.investigateNarrative !== 'function') return;
  try {
    b.investigateNarrative(narrativeId);
  } catch (error) {
    console.error('Error invoking investigateNarrative:', error);
  }
}

/**
 * Fetch the active case's Narrative Map (MapGraph + recent audit) as a JSON string.
 * Returns null when the bridge / backend method is unavailable (standalone mode).
 */
export async function getNarrativeMap(): Promise<string | null> {
  const b = getBridge() as any;
  if (!b || typeof b.getNarrativeMap !== 'function') return null;
  try {
    return await b.getNarrativeMap();
  } catch (error) {
    console.error('Error getting narrative map:', error);
    return null;
  }
}

/**
 * Commit one Narrative Map mutation through the backend (validates GEP + seals).
 * Returns the parsed result { ok, seal_hash, ... } or null in standalone mode.
 */
export async function commitMapEdit(eventJson: string): Promise<any | null> {
  const b = getBridge() as any;
  if (!b || typeof b.commitMapEdit !== 'function') return null;
  try {
    const res = await b.commitMapEdit(eventJson);
    return typeof res === 'string' ? JSON.parse(res) : res;
  } catch (error) {
    console.error('Error committing map edit:', error);
    return null;
  }
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

export interface GroupedBackendOption {
  backend: string;
  model_name: string;
  label: string;
  is_active: boolean;
}

export interface GroupedBackendResponse {
  "Cloud API": GroupedBackendOption[];
  "Local Server": GroupedBackendOption[];
  "Local CLI": GroupedBackendOption[];
}

/**
 * Get all configured or active backend connections and their models, grouped by backend type.
 */
export async function getGroupedBackendConnections(): Promise<GroupedBackendResponse | null> {
  if (!window.bridge || typeof window.bridge.get_grouped_backend_connections !== 'function') {
    return null;
  }

  try {
    const responseJson = await window.bridge.get_grouped_backend_connections();
    const response = JSON.parse(responseJson);
    if (response.success && response.data) {
      return response.data as GroupedBackendResponse;
    }
    return null;
  } catch (error) {
    console.error('Error getting grouped backend connections:', error);
    return null;
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
 * Snapshot of whether the EYE is currently wired up to its AI backend.
 * Used by the chat "EYE Synchronization" step to decide whether to proceed
 * with the triage handshake or surface a clear disconnect message.
 */
export interface BackendStatus {
  connected: boolean;
  backend: string | null;
  model: string | null;
  integration_type: string | null;
  detail: string;
}

/**
 * Check whether the active AI backend (cloud or local) is reachable.
 *
 * Never throws — on bridge error returns `{ connected: false, ... }` so the
 * caller can render a single graceful disconnect message.
 */
export async function getBackendStatus(): Promise<BackendStatus> {
  const fallback: BackendStatus = {
    connected: false,
    backend: null,
    model: null,
    integration_type: null,
    detail: 'Bridge not initialized',
  };
  if (!window.bridge || typeof window.bridge.get_backend_status !== 'function') {
    return fallback;
  }
  try {
    const response = await window.bridge.get_backend_status();
    const parsed = JSON.parse(response);
    if (parsed && parsed.success && parsed.data) {
      return parsed.data as BackendStatus;
    }
    return { ...fallback, detail: parsed?.error || 'Backend status unavailable' };
  } catch (error) {
    console.error('Error checking backend status:', error);
    return { ...fallback, detail: error instanceof Error ? error.message : String(error) };
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
 * Open the "Add new evidence" import flow in the PyQt backend. The native file
 * picker, CSV/JSON→SQLite conversion, and case refresh all happen Python-side
 * (a QFileDialog cannot be hosted by the bridge QObject).
 */
export function openAddEvidence(): void {
  if (window.bridge && window.bridge.requestAddEvidence) {
    window.bridge.requestAddEvidence();
  }
}

/**
 * Open the GEP Compliance dashboard in its own OS window so the investigator
 * can view chat, report, and compliance side by side. Falls back to the
 * legacy URL-swap (in-app view replacement) if the PyQt bridge is unavailable
 * (e.g. running the React build in a plain browser for development).
 */
export function openComplianceWindow(): void {
  if (window.bridge && window.bridge.requestComplianceWindow) {
    window.bridge.requestComplianceWindow();
    return;
  }
  const url = new URL(window.location.href);
  url.searchParams.set('view', 'compliance');
  window.location.href = url.toString();
}

/**
 * Open the Narrative Map (the Eye's working memory) in its own OS window. Falls
 * back to the legacy URL-swap if the PyQt bridge is unavailable.
 */
export function openNarrativeMapWindow(): void {
  const b = window.bridge as any;
  if (b && b.requestNarrativeMapWindow) {
    b.requestNarrativeMapWindow();
    return;
  }
  const url = new URL(window.location.href);
  url.searchParams.set('view', 'map');
  window.location.href = url.toString();
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
 * GEP Rule 7 / Compliance dashboard: fetch the live Ghassan Elsman Protocol
 * compliance state for all 11 rules (8 read-side rules 0-7 + 3 write-side
 * rules 8-10 covering the correlation_create_* / correlation_edit_* tools).
 *
 * Returns the parsed envelope from the Python bridge:
 *   { success: true, data: { rules: [{id, name, status, detail}, ...] }, error: null }
 * On bridge failure, returns the same shape with success=false + error string.
 *
 * The frontend renders any rule id the backend emits — no enum gating —
 * so future rule additions only require backend changes plus
 * RULE_BLURB / RULE_GUIDANCE entries in ProtocolCompliancePanel.tsx.
 */
export interface GepRuleStatus {
  id: number | string;
  name: string;
  status: 'PASS' | 'PARTIAL' | 'FAIL' | 'N-A' | string;
  detail: string;
  /** GEP principle(s) this operating rule / Eye process upholds, e.g. ["GEP-6"]. */
  gep?: string[];
}
/** A live status for one of the 10 GEP protocol principles. */
export interface GepPrinciple {
  id: string;           // "GEP-1" .. "GEP-10"
  name: string;
  status: 'PASS' | 'PARTIAL' | 'FAIL' | 'N-A' | string;
  detail: string;
  upheld_by: string[];  // names of the rules/processes that uphold it
  /** Why the status is what it is: 'verified' | 'structural' | 'config' | 'per-answer'. */
  basis?: string;
}
export interface GepComplianceResponse {
  success: boolean;
  data: { rules: GepRuleStatus[]; gep_principles?: GepPrinciple[] } | null;
  error: string | null;
}

export async function getGepComplianceStatus(): Promise<GepComplianceResponse> {
  if (!window.bridge) {
    throw new Error('Bridge not initialized. Call initializeBridge() first.');
  }
  try {
    const raw = await window.bridge.get_gep_compliance_status();
    return JSON.parse(raw) as GepComplianceResponse;
  } catch (error) {
    console.error('Error fetching GEP compliance status:', error);
    return {
      success: false,
      data: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

/** Activity Audit — chronological log of every query the EYE made,
 * the evidence each tool call returned, and every change to the report. */
export type AuditEntryType =
  | 'user_query'
  | 'assistant_response'
  | 'tool_call'
  | 'tool_result'
  | 'report_added'
  | 'report_edited'
  | 'report_deleted'
  | 'report_other'
  | 'narrative_map';

export interface ActivityAuditEntry {
  timestamp: string;
  type: AuditEntryType;
  summary: string;
  detail: string;
  tools: string[] | null;
  block_id: string | null;
  iteration: number | null;
  // For narrative_map entries: the Verdict/Narrative/Evidence node id, used to
  // deep-link the entry to that card's detail panel in the Narrative Map window.
  card_id?: string | null;
}

export interface ActivityAuditResponse {
  success: boolean;
  data: { entries: ActivityAuditEntry[]; count: number } | null;
  error: string | null;
}

export async function getActivityAudit(): Promise<ActivityAuditResponse> {
  if (!window.bridge || typeof window.bridge.get_activity_audit !== 'function') {
    return {
      success: false,
      data: null,
      error: 'Bridge does not expose get_activity_audit (rebuild required).',
    };
  }
  try {
    const raw = await window.bridge.get_activity_audit();
    return JSON.parse(raw) as ActivityAuditResponse;
  } catch (error) {
    console.error('Error fetching activity audit:', error);
    return {
      success: false,
      data: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

/** Per-step execution history — each pipeline step (RAG lookup, tool
 * execution, synthesis, …) with the list of every time it ran and the
 * timestamp + status of each run. Shown in the Compliance window. */
export interface StepRun {
  timestamp: string;
  status: string;            // "active" | "done" | "error"
  iteration: number | null;
  query: string;
  detail: string | null;
  tool: string | null;
}

export interface StepHistoryGroup {
  key: string;
  type: string;              // "thinking" | "rag" | "tool_call" | "synthesis"
  label: string;
  run_count: number;
  last_status: string | null;
  last_timestamp: string | null;
  runs: StepRun[];
}

export interface StepHistoryResponse {
  success: boolean;
  data: { steps: StepHistoryGroup[]; total_runs: number } | null;
  error: string | null;
}

export async function getStepHistory(): Promise<StepHistoryResponse> {
  if (!window.bridge || typeof window.bridge.get_step_history !== 'function') {
    return {
      success: false,
      data: null,
      error: 'Bridge does not expose get_step_history (rebuild required).',
    };
  }
  try {
    const raw = await window.bridge.get_step_history();
    return JSON.parse(raw) as StepHistoryResponse;
  } catch (error) {
    console.error('Error fetching step history:', error);
    return {
      success: false,
      data: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

/** Full Eye<->LLM conversation (prompts, reasoning, tool calls + results)
 * grouped by the investigator question that produced it — shown in the
 * Compliance window. Reuses the EyeDialogueEntry shape from types.ts. */
export interface DialogueConversation {
  query: string;
  started: string;
  entry_count: number;
  entries: EyeDialogueEntry[];
}

export interface DialogueHistoryResponse {
  success: boolean;
  data: { conversations: DialogueConversation[]; total_entries: number } | null;
  error: string | null;
}

export async function getDialogueHistory(): Promise<DialogueHistoryResponse> {
  if (!window.bridge || typeof window.bridge.get_dialogue_history !== 'function') {
    return {
      success: false,
      data: null,
      error: 'Bridge does not expose get_dialogue_history (rebuild required).',
    };
  }
  try {
    const raw = await window.bridge.get_dialogue_history();
    return JSON.parse(raw) as DialogueHistoryResponse;
  } catch (error) {
    console.error('Error fetching dialogue history:', error);
    return {
      success: false,
      data: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

/** Per-answer behavioral GEP compliance — for each question, whether the Eye
 * followed the protocol (direct answer, dual output, timestamps, proactive
 * investigation). Shown in the Compliance window. */
export interface GepCheck {
  id: number | string;   // turn evaluators emit "GEP-1".."GEP-10"
  name: string;
  status: 'PASS' | 'FAIL' | 'PARTIAL' | 'N-A' | string;
  detail: string;
}

export interface GepTurn {
  query: string;
  timestamp: string;
  summary: string;
  checks: GepCheck[];
}

export interface GepTurnsResponse {
  success: boolean;
  data: { turns: GepTurn[]; total_turns: number } | null;
  error: string | null;
}

export async function getGepTurns(): Promise<GepTurnsResponse> {
  if (!window.bridge || typeof window.bridge.get_gep_turns !== 'function') {
    return {
      success: false,
      data: null,
      error: 'Bridge does not expose get_gep_turns (rebuild required).',
    };
  }
  try {
    const raw = await window.bridge.get_gep_turns();
    return JSON.parse(raw) as GepTurnsResponse;
  } catch (error) {
    console.error('Error fetching GEP turns:', error);
    return {
      success: false,
      data: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

/** Reasoning trace — for a decomposed question, WHY each sub-question was created
 * and WHY each conclusion follows from which evidence. Shown in the Compliance
 * window (GEP-8 Transparency, GEP-2 Traceability). */
export interface ReasoningEvidence {
  ref: string;
  note: string;
}

export interface ReasoningSubQuestion {
  id: string;
  q: string;
  why_created: string;
  conclusion: string;
  why_concluded: string;
  evidence: ReasoningEvidence[];
  status: string;
}

export interface ReasoningPremise {
  claim: string;
  verdict: string;
  why: string;
  evidence: ReasoningEvidence[];
}

export interface ReasoningTurn {
  query: string;
  timestamp: string;
  strategy: string;
  sub_questions: ReasoningSubQuestion[];
  premises: ReasoningPremise[];
  consolidation: string;
  knowledge_consulted: string[];
}

export interface ReasoningTurnsResponse {
  success: boolean;
  data: { turns: ReasoningTurn[]; total_turns: number } | null;
  error: string | null;
}

export async function getReasoningTurns(): Promise<ReasoningTurnsResponse> {
  if (!window.bridge || typeof window.bridge.get_reasoning_turns !== 'function') {
    return {
      success: false,
      data: null,
      error: 'Bridge does not expose get_reasoning_turns (rebuild required).',
    };
  }
  try {
    const raw = await window.bridge.get_reasoning_turns();
    return JSON.parse(raw) as ReasoningTurnsResponse;
  } catch (error) {
    console.error('Error fetching reasoning turns:', error);
    return {
      success: false,
      data: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

/** Chain-of-custody Evidence Seals — one per LLM payload — proving exactly
 * which bytes the model saw (SHA-256 + token count + provenance + hash chain). */
export interface EvidenceRef {
  tool?: string;
  database?: string;
  table?: string;
  sql?: string;
  row_count?: number;
  rowids?: any[];
  source_path?: string;
  record_number?: number;
  computed_file_offsets?: { record_number: number; computed_file_offset: number; record_size: number }[];
  row_index_range?: number[];
}

/** Explicit character range of a cut within the original message:
 * which chars were kept (processed) vs dropped. */
export interface CutRange {
  unit: string;            // "chars"
  total: number;
  processed: [number, number];
  dropped: [number, number];
}

export interface CutDetail {
  action: string;
  message_id?: string;
  role?: string;
  iteration?: number | null;
  token_count: number;
  sha256: string;
  cut_range?: CutRange;
  // Dropped portion: bounded inline preview + full length/hash/sidecar.
  cut_content: string;
  cut_content_len?: number;
  cut_content_sha256?: string;
  cut_content_sidecar?: string | null;
  // Surviving portion: bounded inline preview + full length/hash/sidecar.
  processed_content?: string;
  processed_content_len?: number;
  processed_content_sha256?: string;
  processed_content_sidecar?: string | null;
  processed_file_offsets?: any[];
  dropped_file_offsets?: any[];
}

/** A cut_detail flattened with its parent seal's context, for the dedicated
 * "Processed vs Dropped Payload" Compliance section. */
export interface FlatCutDetail extends CutDetail {
  seq?: number;
  timestamp?: string;
  phase?: string;
  query?: string;
  model?: string;
  // Set for synthesized entries: 'assembly_budget' (system prompt / RAG / history
  // budget trims) or 'refused' (the message the Eye refused to send).
  source?: string;
  payload_sha256?: string;
  payload_sidecar?: string | null;
  max_context_tokens?: number;
}

export interface PayloadCutDetailsResponse {
  success: boolean;
  data: { cuts: FlatCutDetail[]; total: number } | null;
  error: string | null;
}

/** Full dropped/processed bytes for one cut, fetched on demand from its
 * sidecar file (when the inline preview was bounded). */
export interface DroppedPayloadFullResponse {
  success: boolean;
  data: { sha256: string; len: number; content: string } | null;
  error: string | null;
}

export interface PayloadSeal {
  seq: number;
  timestamp: string;
  phase: string;
  iteration: number | null;
  query: string;
  model: string;
  max_context_tokens: number;
  payload_tokens: number;
  truncated: boolean;
  payload_sha256: string;
  prev_seal_hash: string;
  seal_hash: string;
  evidence_refs: EvidenceRef[];
  cut_details?: CutDetail[];
}

export interface PayloadSealsResponse {
  success: boolean;
  data: { seals: PayloadSeal[]; total_seals: number; chain_valid: boolean } | null;
  error: string | null;
}

export async function getPayloadSeals(): Promise<PayloadSealsResponse> {
  if (!window.bridge || typeof window.bridge.get_payload_seals !== 'function') {
    return {
      success: false,
      data: null,
      error: 'Bridge does not expose get_payload_seals (rebuild required).',
    };
  }
  try {
    const raw = await window.bridge.get_payload_seals();
    return JSON.parse(raw) as PayloadSealsResponse;
  } catch (error) {
    console.error('Error fetching payload seals:', error);
    return {
      success: false,
      data: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

/** Chain-of-custody audit events — every context-integrity decision the Eye
 * made (evidence preservation, self-heal summarize/drop, pin/unpin, hard
 * refusals). Backed by EYE_Logs/truncation_audit.log. */
export interface TruncationEvent {
  timestamp: string;
  action: string;   // PRESERVED | SUMMARIZED | TRUNCATED | PINNED | UNPINNED | REFUSED_OVERFLOW
  id: string;
  tokens: number;
  reason: string;
  hash: string;
  metadata: Record<string, any>;
}

export interface TruncationEventsResponse {
  success: boolean;
  data: { events: TruncationEvent[]; counts: Record<string, number>; total: number } | null;
  error: string | null;
}

export async function getTruncationEvents(): Promise<TruncationEventsResponse> {
  if (!window.bridge || typeof window.bridge.get_truncation_events !== 'function') {
    return {
      success: false,
      data: null,
      error: 'Bridge does not expose get_truncation_events (rebuild required).',
    };
  }
  try {
    const raw = await window.bridge.get_truncation_events();
    return JSON.parse(raw) as TruncationEventsResponse;
  } catch (error) {
    console.error('Error fetching truncation events:', error);
    return {
      success: false,
      data: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

/** Every per-payload cut (summarize / drop / tool-output cap) flattened across
 * all seals, for the dedicated "Processed vs Dropped Payload" section. */
export async function getPayloadCutDetails(): Promise<PayloadCutDetailsResponse> {
  if (!window.bridge || typeof window.bridge.get_payload_cut_details !== 'function') {
    return {
      success: false,
      data: null,
      error: 'Bridge does not expose get_payload_cut_details (rebuild required).',
    };
  }
  try {
    const raw = await window.bridge.get_payload_cut_details();
    return JSON.parse(raw) as PayloadCutDetailsResponse;
  } catch (error) {
    console.error('Error fetching payload cut details:', error);
    return {
      success: false,
      data: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

/** Fetch the COMPLETE dropped/processed bytes for one cut from its sidecar,
 * keyed by the content SHA-256 recorded on the cut detail. */
export async function getDroppedPayloadFull(sha256: string): Promise<DroppedPayloadFullResponse> {
  if (!window.bridge || typeof window.bridge.get_dropped_payload_full !== 'function') {
    return {
      success: false,
      data: null,
      error: 'Bridge does not expose get_dropped_payload_full (rebuild required).',
    };
  }
  try {
    const raw = await window.bridge.get_dropped_payload_full(sha256);
    return JSON.parse(raw) as DroppedPayloadFullResponse;
  } catch (error) {
    console.error('Error fetching dropped payload:', error);
    return {
      success: false,
      data: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

/** Fetch the COMPLETE sent payload (system prompt + history + tools + user
 * message) for one seal, keyed by its payload SHA-256. The backend decompresses
 * older (zstd/gzip) sidecars transparently. */
export async function getSealedPayloadFull(sha256: string): Promise<DroppedPayloadFullResponse> {
  if (!window.bridge || typeof window.bridge.get_sealed_payload_full !== 'function') {
    return {
      success: false,
      data: null,
      error: 'Bridge does not expose get_sealed_payload_full (rebuild required).',
    };
  }
  try {
    const raw = await window.bridge.get_sealed_payload_full(sha256);
    return JSON.parse(raw) as DroppedPayloadFullResponse;
  } catch (error) {
    console.error('Error fetching sealed payload:', error);
    return {
      success: false,
      data: null,
      error: error instanceof Error ? error.message : String(error),
    };
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
