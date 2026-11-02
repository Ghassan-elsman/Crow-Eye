import React, { useState, useEffect, useCallback, useRef } from 'react';
import type { Message, ContextStats, ThinkingStep, EyeDialogueEntry } from './types';
import MessageList from './MessageList';
import InputBar from './InputBar';
import LoadingDialog from './LoadingDialog';
import type { LoadingStep } from './LoadingDialog';
import ConnectPanel from './ConnectPanel';
import TruncationWarningBanner from './TruncationWarningBanner';
import TokenBudgetSlider from './TokenBudgetSlider';
import FullHistoryModal from './FullHistoryModal';
import ErrorBoundary from './ErrorBoundary';
import {
  initializeBridge,
  sendMessage as bridgeSendMessage,
  onQueryComplete,
  onReportUpdated,
  onErrorOccurred,
  isBridgeReady,
  getContextStats,
  getConversationHistory,
  clearConversationHistory,
  onStatusUpdated,
  onDialogueUpdated,
  getGroupedBackendConnections,
  onGroupedBackendsReady,
  switchActiveModel,
  showCaseContext,
  showCaseSummary,
  showSettings,
  openAddEvidence,
  openComplianceWindow,
  openNarrativeMapWindow,
  openEvidenceWindow,
  initializeTriage,
  startBackendCheck,
  onBackendStatusChanged,
  onTruncationWarning,
  pinMessage,
  unpinMessage,
  updateTokenBudget,
} from './bridge';
import type { GroupedBackendResponse, BackendStatus } from './bridge';
import { IconTrash, IconClipboardList, IconChartBar, IconSettings, IconLayers, IconBrain, IconDatabase } from './Icons';
import eyeIcon from './assets/eye_icon.png';
import './ChatInterface.css';

const ChatInterface: React.FC = () => {
  const [messages, setMessages]           = useState<Message[]>([]);
  const [inputValue, setInputValue]       = useState('');
  const [isLoading, setIsLoading]         = useState(false);
  const [bridgeReady, setBridgeReady]     = useState(false);
  const [contextStats, setContextStats]   = useState<ContextStats | null>(null);
  const [thinkingSteps, setThinkingSteps] = useState<ThinkingStep[]>([]);
  // Live Eye<->LLM conversation for the in-progress query (retained onto the
  // assistant message when the answer arrives). The ref mirrors the state so
  // the (once-registered) query-complete callback can read the latest value.
  const [dialogue, setDialogue] = useState<EyeDialogueEntry[]>([]);
  const dialogueRef = useRef<EyeDialogueEntry[]>([]);
  // Loading dialog: visible on startup until bridge is ready; also toggled by logo btn
  const [showLoading, setShowLoading]     = useState(true);
  const [loadingStatus, setLoadingStatus] = useState<string | undefined>(undefined);
  // The real startup steps the loading screen shows (no cycling text).
  const [initSteps, setInitSteps] = useState<LoadingStep[]>([
    { label: 'Connect to Crow-Eye', state: 'pending' },
    { label: 'Load the case context', state: 'pending' },
    { label: 'Load the conversation history', state: 'pending' },
  ]);
  const markStep = useCallback((label: string, state: LoadingStep['state'], note?: string) => {
    setInitSteps(prev => prev.map(st => (st.label === label ? { ...st, state, note } : st)));
  }, []);
  // The model backend's state, checked off the GUI thread (start_backend_check).
  const [backendStatus, setBackendStatus] = useState<BackendStatus | null>(null);
  const backendStatusHandlerRef = useRef<(st: BackendStatus) => void>(() => {});
  const triageStartedRef = useRef(false);
  const syncMsgIdRef = useRef<string | null>(null);
  // A slow answer is said, never left as a silent spinner.
  const lastActivityRef = useRef<number>(Date.now());
  const [slowSeconds, setSlowSeconds] = useState(0);
  const [loadingPhase, setLoadingPhase]   = useState<'init' | 'processing'>('init');

  // Model Menu State
  const [showModelMenu, setShowModelMenu] = useState(false);
  const [groupedBackends, setGroupedBackends] = useState<GroupedBackendResponse | null>(null);
  const [fetchingModels, setFetchingModels] = useState(false);

  // Model-switch synchronization: when the user picks a new model, the post-switch
  // analyze_case_context query runs before the new model is fully "ready". Any
  // send during that window is held in pendingSendRef and flushed once the
  // sync-prefixed message in chat is resolved by the query_complete listener.
  const [switchingTo, setSwitchingTo] = useState<string | null>(null);
  const switchingRef = useRef(false);            // mirror of switchingTo for listeners
  const isLoadingRef = useRef(false);            // mirror of isLoading for stable callbacks
  const pendingSendRef = useRef<string | null>(null);
  const sendMessageRef = useRef<((q: string) => void) | null>(null);
  const syncRecentMessageIdsRef = useRef<(() => void) | null>(null);
  // Watchdog: if a model-switch's post-sync query_complete never fires (e.g.
  // Python silently dies during analyze_case_context), switchingTo would stay
  // set forever and the input would be stuck. This timer force-clears the
  // state after a reasonable grace period and releases any queued send.
  const switchWatchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Last observed block count from a report_updated signal; null = no baseline yet.
  // Used to suppress "new evidence" toasts when the report changes for any reason
  // other than a genuine block addition (edits, saves, internal syncs).
  const lastReportBlockCountRef = useRef<number | null>(null);
  useEffect(() => { switchingRef.current = switchingTo !== null; }, [switchingTo]);
  useEffect(() => () => {
    if (switchWatchdogRef.current) clearTimeout(switchWatchdogRef.current);
  }, []);

  // Toast notification state
  const [toast, setToast] = useState<{message: string, type: 'success' | 'info' | 'error'} | null>(null);

  const showToast = useCallback((message: string, type: 'success' | 'info' | 'error' = 'info') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4000);
  }, []);

  // Evidence Preservation State
  const [truncationWarning, setTruncationWarning] = useState<any>(null);
  const [showBudgetSlider, setShowBudgetSlider] = useState(false);
  const [showFullHistory, setShowFullHistory] = useState(false);
  const [fullHistoryMessages, setFullHistoryMessages] = useState<any[]>([]);

  /* ── Bridge init ───────────────────────────── */
  useEffect(() => {
    let unsubQC: (() => void) | undefined;
    let unsubRU: (() => void) | undefined;
    let unsubEO: (() => void) | undefined;
    let unsubSU: (() => void) | undefined;
    let unsubDU: (() => void) | undefined;
    let unsubTW: (() => void) | undefined;
    let unsubBS: (() => void) | undefined;

    const setup = async () => {
      try {
        const secs = (t: number) => `${((performance.now() - t) / 1000).toFixed(1)} s`;
        const t0 = performance.now();
        markStep('Connect to Crow-Eye', 'active');
        try {
          await initializeBridge();
        } catch (err) {
          markStep('Connect to Crow-Eye', 'failed', err instanceof Error ? err.message : String(err));
          throw err;
        }
        markStep('Connect to Crow-Eye', 'done', secs(t0));
        setBridgeReady(true);
        // The two independent loads run side by side; each reports its own time.
        const t1 = performance.now();
        markStep('Load the case context', 'active');
        markStep('Load the conversation history', 'active');
        await Promise.all([
          Promise.resolve(fetchContextStats()).then(
            () => markStep('Load the case context', 'done', secs(t1)),
            (e) => markStep('Load the case context', 'failed', String(e))),
          Promise.resolve(loadHistory()).then(
            () => markStep('Load the conversation history', 'done', secs(t1)),
            (e) => markStep('Load the conversation history', 'failed', String(e))),
        ]);

        // Set up signal listeners before triggering any queries
        unsubQC = onQueryComplete((json: string) => {
          try {
            const result = JSON.parse(json);
            const data = result.data || result;

            // Show a plain error message only if there is no recoverable data at all
            if (result.error && !data?.response && !data?.content && !data?.action_chips) {
              appendAssistantMessage(`Error: ${result.error}`);
              setIsLoading(false);
              setThinkingSteps([]);
              // If this error landed during a model-switch sync, release the queue
              // so the user's held message still fires (against the previous model).
              if (switchingRef.current) {
                if (switchWatchdogRef.current) {
                  clearTimeout(switchWatchdogRef.current);
                  switchWatchdogRef.current = null;
                }
                setSwitchingTo(null);
                const queued = pendingSendRef.current;
                pendingSendRef.current = null;
                if (queued) setTimeout(() => sendMessageRef.current?.(queued), 0);
              }
              return;
            }

            // Resolve the text content — fall back to a placeholder so the bubble
            // is never blank even when the cloud API returns an empty text part
            // alongside action chips (e.g. Gemini function-call-only responses).
            // Resolve the text content
            let responseText = (
              data.response ||
              data.content ||
              (result.error ? `Error: ${result.error}` : '')
            ).trim();

            // SAFETY: Truncate massive text responses to prevent UI thread lock
            const MAX_CHAT_LENGTH = 50000;
            if (responseText.length > MAX_CHAT_LENGTH) {
              responseText = responseText.substring(0, MAX_CHAT_LENGTH) + 
                "\n\n---\n**[Forensic Notice: Output Truncated for UI Stability]**\n" +
                "The response length exceeded the real-time visualization limit. " +
                "Full forensic findings have been preserved in the Report Builder panel.";
            }

            // Retain the full Eye<->LLM conversation so the investigator can
            // review how the Eye reasoned. Prefer the authoritative transcript
            // returned by the backend; fall back to the live-streamed entries.
            const transcript: EyeDialogueEntry[] =
              (data.eye_llm_conversation && data.eye_llm_conversation.length)
                ? data.eye_llm_conversation
                : dialogueRef.current;

            const msg: Message = {
              id: `assistant-${Date.now()}`,
              role: 'assistant',
              content: responseText || "The forensic operation was performed, but no text summary was provided by the model. Please check the reporting pane for updates.",
              timestamp: new Date().toISOString(),
              data_viewer:  data.data_viewer  || undefined,
              data_viewers: data.data_viewers || undefined,
              action_chips: data.action_chips || undefined,
              option_menu:  data.option_menu  || undefined,
              eye_dialogue: transcript.length ? transcript : undefined,
              tool_output: (data.tool_output && data.tool_output.length) ? data.tool_output : undefined,
            };
            setMessages(prev => {
              const updated = prev.map(m => {
                if (m.id.startsWith('sync-')) {
                   return { ...m, content: "**Synchronization Complete**: Forensic context verified. Automated triage report initialized." };
                }
                return m;
              });
              return [...updated, msg];
            });

            setIsLoading(false);
            setThinkingSteps([]);
            setDialogue([]);
            dialogueRef.current = [];
            fetchContextStats();
            // Realign the just-appended message IDs with Python's HistoryManager
            // so pin / unpin actually find them on the backend.
            syncRecentMessageIdsRef.current?.();

            // Model-switch sync just completed — release any queued send.
            if (switchingRef.current) {
              if (switchWatchdogRef.current) {
                clearTimeout(switchWatchdogRef.current);
                switchWatchdogRef.current = null;
              }
              setSwitchingTo(null);
              const queued = pendingSendRef.current;
              pendingSendRef.current = null;
              if (queued) {
                // Defer to next tick so state updates flush before re-entering sendMessage
                setTimeout(() => { sendMessageRef.current?.(queued); }, 0);
              }
            }
          } catch (err) {
            console.error('Failed to parse query result:', err);
            setIsLoading(false);
            setThinkingSteps([]);
            showToast('Bridge synchronization error. Payload might be truncated.', 'error');
          }
        });

        unsubRU = onReportUpdated((_json: string) => {});

        unsubEO = onErrorOccurred((errMsg: string) => {
          appendAssistantMessage(`Backend error: ${errMsg}`);
        });

        unsubSU = onStatusUpdated((statusJson: string) => {
          lastActivityRef.current = Date.now();
          try {
            const data = JSON.parse(statusJson);
            
            const step: ThinkingStep = data;
            setThinkingSteps(prev => {
              const idx = prev.findIndex(s => s.step_id === step.step_id);
              if (idx >= 0) {
                const updated = [...prev];
                updated[idx] = step;
                return updated;
              }
              return [...prev, step];
            });
          } catch {
            // Check if it's a raw string or corrupted JSON
            const label = statusJson.startsWith('{') ? "Processing forensic artifacts..." : statusJson;
            setThinkingSteps(prev => [
              ...prev,
              { step_id: `fb-${Date.now()}`, type: 'thinking', label: label, status: 'active' },
            ]);
          }
        });

        // Stream the Eye<->LLM conversation as it happens.
        unsubDU = onDialogueUpdated((entryJson: string) => {
          lastActivityRef.current = Date.now();
          try {
            const entry: EyeDialogueEntry = JSON.parse(entryJson);
            setDialogue(prev => {
              const next = [...prev, entry];
              dialogueRef.current = next;
              return next;
            });
          } catch {
            /* ignore malformed dialogue entries */
          }
        });

        // Listen for truncation warnings
        unsubTW = onTruncationWarning((warningJson: string) => {
          try {
            const warning = JSON.parse(warningJson);
            setTruncationWarning(warning);
            fetchContextStats(); // Refresh stats to show updated truncation count
          } catch (error) {
            console.error('Error parsing truncation warning:', error);
          }
        });

        // The chat opens now. The model backend is checked on a worker thread in
        // Python and reports here as it goes (checking N s -> connected / failed),
        // so a slow or unreachable provider can never hold the loading screen -
        // or Crow-Eye - again. The triage starts once the backend answers.
        setTimeout(() => setShowLoading(false), 450);
        const syncMsgId = `sync-${Date.now()}`;
        syncMsgIdRef.current = syncMsgId;
        setMessages(prev => [...prev, {
          id: syncMsgId,
          role: 'assistant',
          content: "**Eye Synchronization**: Checking the model backend...",
          timestamp: new Date().toISOString()
        }]);
        unsubBS = onBackendStatusChanged((st) => backendStatusHandlerRef.current(st));
        const first = await startBackendCheck();
        if (first) backendStatusHandlerRef.current(first);
      } catch {
        setBridgeReady(false);
        setLoadingStatus('Bridge connection failed');
        setTimeout(() => setShowLoading(false), 2000);
      }
    };

    setup();
    // Toast only when the report actually GAINS a block. The bridge's
    // report_updated signal also fires on edits, deletions, and internal
    // saves the Eye triggers mid-investigation, which produced misleading
    // "new evidence" toasts while the AI was just working.
    const unsubscribeReport = onReportUpdated((reportJson: string) => {
      try {
        const parsed = JSON.parse(reportJson);
        const data = parsed?.data ?? parsed;
        const blocks = data?.blocks;
        const count = Array.isArray(blocks) ? blocks.length : null;
        if (count === null) return;
        const prev = lastReportBlockCountRef.current;
        lastReportBlockCountRef.current = count;
        if (prev === null) return;             // first signal — establish baseline silently
        if (count > prev) {
          const added = count - prev;
          showToast(
            added === 1
              ? 'Forensic report: 1 new block added.'
              : `Forensic report: ${added} new blocks added.`,
            'success'
          );
        }
        // Edits / deletions / saves with no growth: stay silent.
      } catch {
        // Malformed payload — say nothing rather than fire a false alarm.
      }
    });

    const unsubscribeError = onErrorOccurred((msg: string) => {
      showToast(msg, 'error');
    });

    // Background live-refresh of the model menu: replace the fast cached grouping
    // with the authoritative one (fresh models + is_active) whenever it arrives.
    const unsubGrouped = onGroupedBackendsReady((grouped) => {
      setGroupedBackends(grouped);
      setFetchingModels(false);
    });

    // Listen for reflow-charts signal from bridge. The bridge is registered as
    // window.bridge by bridge.ts (not window.eyeBridge — that property was a
    // long-standing typo that silently disabled chart reflow on splitter resize).
    const bridge = window.bridge as any;
    if (bridge && bridge.reflow_charts && typeof bridge.reflow_charts.connect === 'function') {
      bridge.reflow_charts.connect(() => {
        window.dispatchEvent(new Event('resize'));                    // Chart.js ResizeObserver path
        window.dispatchEvent(new CustomEvent('reflow-forensic-charts')); // ReportBlockComponent path
      });
    }

    return () => {
      unsubQC?.(); unsubRU?.(); unsubEO?.(); unsubSU?.(); unsubDU?.(); unsubTW?.(); unsubBS?.();
      unsubscribeReport();
      unsubscribeError();
      unsubGrouped();
    };
  }, []);

  /* ── Helpers ───────────────────────────────── */
  const appendAssistantMessage = (content: string) => {
    setMessages(prev => [
      ...prev,
      { id: `assistant-${Date.now()}`, role: 'assistant', content, timestamp: new Date().toISOString() },
    ]);
  };

  const fetchContextStats = useCallback(async () => {
    if (!isBridgeReady()) return;
    try {
      const json = await getContextStats();
      const r = JSON.parse(json);
      if (r.success && r.data) setContextStats(r.data);
    } catch { /* silent */ }
  }, []);

  const handleModelMenuToggle = () => {
    if (showModelMenu) { setShowModelMenu(false); return; }
    // Open INSTANTLY — never block the open on a fetch. Show cached options at once
    // (kept across opens); only show the loading row when nothing is cached yet. The
    // bridge returns a fast in-memory grouping synchronously and pushes the live
    // refresh via onGroupedBackendsReady (subscribed in the bridge-init effect),
    // which updates the menu in place.
    setShowModelMenu(true);
    setFetchingModels(!groupedBackends);
    getGroupedBackendConnections()
      .then((grouped) => { if (grouped) setGroupedBackends(grouped); })
      .catch(() => { /* keep whatever we had */ })
      .finally(() => setFetchingModels(false));
  };

  const handleModelSelect = async (modelId: string) => {
    setShowModelMenu(false);
    if (switchingRef.current || isLoading) return;  // ignore overlapping switches

    setSwitchingTo(modelId);
    // sync-prefixed message; query_complete listener flips it to "Synchronization Complete"
    const syncId = `sync-switch-${Date.now()}`;
    setMessages(prev => [...prev, {
      id: syncId,
      role: 'assistant',
      content: `Switching to **${modelId}**… synchronizing case context.`,
      timestamp: new Date().toISOString(),
    }]);

    // Arm the watchdog. 90 s is generous enough for a real triage sync but
    // short enough that the user isn't stuck if the backend hangs silently.
    if (switchWatchdogRef.current) clearTimeout(switchWatchdogRef.current);
    switchWatchdogRef.current = setTimeout(() => {
      switchWatchdogRef.current = null;
      // Only fire if we're still stuck — query_complete may have already
      // cleared switchingTo, in which case there's nothing to recover.
      if (!switchingRef.current) return;
      setSwitchingTo(null);
      setMessages(prev => prev.map(m =>
        m.id === syncId
          ? { ...m, content: `Switch to **${modelId}** is taking unusually long — releasing the queued message anyway. Check backend logs if this repeats.` }
          : m
      ));
      const queued = pendingSendRef.current;
      pendingSendRef.current = null;
      if (queued) setTimeout(() => sendMessageRef.current?.(queued), 0);
    }, 90_000);

    const failAndFlush = (reason: string) => {
      if (switchWatchdogRef.current) {
        clearTimeout(switchWatchdogRef.current);
        switchWatchdogRef.current = null;
      }
      setSwitchingTo(null);
      setMessages(prev => prev.map(m =>
        m.id === syncId
          ? { ...m, content: `Could not switch to **${modelId}** — ${reason}. Staying on the current model.` }
          : m
      ));
      const queued = pendingSendRef.current;
      pendingSendRef.current = null;
      if (queued) setTimeout(() => sendMessageRef.current?.(queued), 0);
    };

    try {
      const success = await switchActiveModel(modelId);
      if (!success) {
        failAndFlush('the backend rejected the switch');
        return;
      }
      // Success: leave switchingTo set; the post-switch analyze_case_context
      // (auto-fired by the Python slot) will produce a query_complete that the
      // existing listener catches, clears switchingTo, and flushes pendingSend.
      fetchContextStats();
      // Refresh the menu grouping so the active-model marker follows the switch
      // (fast cached return + background live refresh via onGroupedBackendsReady).
      getGroupedBackendConnections().then((g) => { if (g) setGroupedBackends(g); }).catch(() => {});
    } catch (err) {
      failAndFlush(err instanceof Error ? err.message : 'unknown error');
    }
  };

  const loadHistory = async () => {
    if (!isBridgeReady()) return;
    try {
      const json = await getConversationHistory();
      const r = JSON.parse(json);
      if (r.success && r.data) {
        const hist: Message[] = r.data
          .filter((m: any) => m.role !== 'system')
          .map((m: any, i: number) => ({
            // Preserve Python's HistoryManager id so pin / unpin can find this
            // message in the backend. Falling back to a synthetic id only when
            // the backend payload pre-dates the id field.
            id: m.id || `history-${i}-${Date.now()}`,
            role: m.role,
            content: (m.content || "").trim() || "No content provided.",
            timestamp: m.timestamp || new Date().toISOString(),
            metadata: m.metadata || undefined,
            // Restore the per-message thinking transcript so the "Show the
            // Eye's thinking" dropdown reappears for EVERY message on reopen.
            eye_dialogue: m.metadata?.eye_dialogue || undefined,
            tool_output: m.metadata?.tool_output || undefined,
          }));
        setMessages(hist);
      }
    } catch { /* silent */ }
  };

  const handleClearHistory = async () => {
    if (!isBridgeReady()) return;
    try {
      const json = await clearConversationHistory();
      const r = JSON.parse(json);
      if (r.success && r.data) {
        const hist: Message[] = r.data
          .filter((m: any) => m.role !== 'system')
          .map((m: any, i: number) => ({
            // Preserve Python's id so pin/unpin can find these messages.
            id: m.id || `cleared-${i}-${Date.now()}`,
            role: m.role,
            content: (m.content || "").trim() || "No content provided.",
            timestamp: m.timestamp || new Date().toISOString(),
            metadata: m.metadata || undefined,
            eye_dialogue: m.metadata?.eye_dialogue || undefined,
            tool_output: m.metadata?.tool_output || undefined,
          }));
        setMessages(hist);
      } else {
        setMessages([]);
      }
      await fetchContextStats();
    } catch (err) {
      appendAssistantMessage(`Error clearing history: ${err instanceof Error ? err.message : 'Unknown'}`);
    }
  };

  /**
   * Sync the IDs of recently-added React messages with the canonical IDs that
   * Python's HistoryManager assigned. The two sides generate IDs independently
   * (React: `user-<ts>` / `assistant-<ts>`, Python: hash-chained per content),
   * which silently breaks pin / unpin because pin_message looks up by id in the
   * Python history and never finds the React-generated ones.
   *
   * Strategy: pull the live Python history, walk from the tail, and rewrite the
   * id of the most-recent React message of each role to match. Other fields
   * (action_chips, data_viewer, option_menu, content) are preserved.
   */
  const syncRecentMessageIds = useCallback(async () => {
    if (!isBridgeReady()) return;
    try {
      const json = await getConversationHistory();
      const r = JSON.parse(json);
      if (!r.success || !Array.isArray(r.data)) return;
      const pyHistory: any[] = r.data.filter((m: any) => m.role !== 'system' && !m.metadata?.internal);
      if (pyHistory.length === 0) return;

      setMessages(prev => {
        // Walk from the tail of both lists and rewrite IDs by role match. The
        // Python list may contain extra system/tool entries that the React list
        // skips, so for each React message we hunt backwards on the Python
        // side until we find an entry with a matching role.
        const next = [...prev];
        let pyIdx = pyHistory.length - 1;
        for (let i = next.length - 1; i >= 0 && pyIdx >= 0; i--) {
          const r1 = next[i];
          while (pyIdx >= 0 && pyHistory[pyIdx].role !== r1.role) pyIdx--;
          if (pyIdx < 0) break;
          const pyMsg = pyHistory[pyIdx];
          if (pyMsg.id && pyMsg.id !== r1.id) {
            next[i] = {
              ...r1,
              id: pyMsg.id,
              metadata: { ...(r1.metadata || {}), ...(pyMsg.metadata || {}) },
            };
          }
          pyIdx--;
        }
        return next;
      });
    } catch { /* silent — pin will still work for previously-loaded messages */ }
  }, []);

  /* ── Model backend status ─────────────────── */
  backendStatusHandlerRef.current = (st: BackendStatus) => {
    setBackendStatus(st);
    const id = syncMsgIdRef.current;
    const label = st.backend ? `**${st.backend}**${st.model ? ` · ${st.model}` : ''}` : 'the model backend';
    const say = (content: string) => {
      if (!id) return;
      setMessages(prev => prev.map(m => (m.id === id ? { ...m, content } : m)));
    };
    if (st.state === 'checking') {
      const waited = st.seconds ?? 0;
      say(waited >= 1
        ? `**Eye Synchronization**: Checking ${label}... ${waited.toFixed(0)} s`
        : `**Eye Synchronization**: Checking ${label}...`);
      return;
    }
    if (st.state === 'connected') {
      say(`**Eye Synchronization**: Connected to ${label} in ${(st.seconds ?? 0).toFixed(1)} s. Transmitting case context and starting the triage...`);
      if (!triageStartedRef.current) {
        triageStartedRef.current = true;
        lastActivityRef.current = Date.now();
        setIsLoading(true);
        initializeTriage().catch((e) => {
          const msg = e instanceof Error ? e.message : String(e);
          say(`**Eye Synchronization**: the triage could not start - ${msg}`);
          setIsLoading(false);
        });
      }
      return;
    }
    say(`**Eye not connected**: ${st.detail || 'the model backend did not answer.'}`);
    setIsLoading(false);
  };

  useEffect(() => {
    if (!isLoading) { setSlowSeconds(0); return; }
    lastActivityRef.current = Date.now();
    const iv = setInterval(() => {
      const quiet = (Date.now() - lastActivityRef.current) / 1000;
      setSlowSeconds(quiet >= 20 ? Math.floor(quiet) : 0);
    }, 1000);
    return () => clearInterval(iv);
  }, [isLoading]);

  /* ── Send ──────────────────────────────────── */
  const sendMessage = async (query: string) => {
    if (!query.trim()) return;
    // If a model switch is in-flight, hold the message and let the sync-completion
    // path in onQueryComplete flush it. Only the latest queued message wins —
    // earlier ones are dropped so the user can revise while waiting.
    if (switchingRef.current) {
      pendingSendRef.current = query.trim();
      setInputValue('');
      return;
    }
    const userMsg: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: query,
      timestamp: new Date().toISOString(),
    };
    setMessages(prev => [...prev, userMsg]);
    setIsLoading(true);
    setThinkingSteps([]);
    setDialogue([]);
    dialogueRef.current = [];

    try {
      if (isBridgeReady()) {
        const json = await bridgeSendMessage(query);
        const r = JSON.parse(json);
        if (!r.success || r.error) {
          appendAssistantMessage(`Error: ${r.error || 'Unknown error'}`);
          setIsLoading(false);
          setThinkingSteps([]);
        } else if (r.data?.status === 'processing') {
          // Wait for onQueryComplete signal
        } else if (r.data) {
          const d = r.data;
          setMessages(prev => [...prev, {
            id: `assistant-${Date.now()}`,
            role: 'assistant',
            content: (d.response || '').trim() || "The forensic operation was performed, but no text summary was provided.",
            timestamp: new Date().toISOString(),
            data_viewer:  d.data_viewer  || undefined,
            data_viewers: d.data_viewers || undefined,
            action_chips: d.action_chips || undefined,
            option_menu:  d.option_menu  || undefined,
          }]);
          setIsLoading(false);
          setThinkingSteps([]);
          fetchContextStats();
        }
        await fetchContextStats();
      } else {
        // Standalone dev mock
        await new Promise(r => setTimeout(r, 500));
        setMessages(prev => [...prev, {
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          content: `**Dev mode** — Bridge not connected.\n\nYour query: *"${query}"*`,
          timestamp: new Date().toISOString(),
          action_chips: [
            { id: '1', label: 'Show Timeline', query: 'Show me the event timeline' },
            { id: '2', label: 'Search Artifacts', query: 'Search for suspicious artifacts' },
          ],
        }]);
        setIsLoading(false);
        setThinkingSteps([]);
      }
    } catch (err) {
      appendAssistantMessage(`Error: ${err instanceof Error ? err.message : 'Unknown error'}`);
      setIsLoading(false);
      setThinkingSteps([]);
    }
  };

  sendMessageRef.current = sendMessage;             // keep listener-accessible reference fresh
  syncRecentMessageIdsRef.current = syncRecentMessageIds;
  isLoadingRef.current = isLoading;                 // mirror for identity-stable callbacks

  // Identity-stable handlers (via refs) so the memoized MessageList doesn't
  // re-render on every keystroke / unrelated state change.
  const handleOptionSelect = useCallback((query: string) => { sendMessageRef.current?.(query); }, []);
  const handleActionChipClick = useCallback((query: string) => setInputValue(query), []);
  // Double-click on a suggested-action chip: run it immediately (no compose step).
  const handleActionChipExecute = useCallback((query: string) => {
    if (isLoadingRef.current) return;               // a query is already running
    setInputValue('');                              // clear anything the single-click inserted
    sendMessageRef.current?.(query);
  }, []);

  // Logo button handler — re-shows loading dialog when clicked while something is loading
  const handleLogoClick = () => {
    if (isLoading || !bridgeReady) {
      setLoadingPhase(isLoading ? 'processing' : 'init');
      setShowLoading(true);
    }
  };

  // Evidence preservation handlers
  const handleDismissWarning = () => {
    setTruncationWarning(null);
  };

  const handleViewFullHistory = async () => {
    try {
      const json = await getConversationHistory();
      const result = JSON.parse(json);
      if (result.success && result.data) {
        setFullHistoryMessages(result.data);
        setShowFullHistory(true);
      }
    } catch (error) {
      console.error('Error loading full history:', error);
    }
  };

  const handleIncreaseBudget = () => {
    setShowBudgetSlider(true);
  };

  const handleBudgetChange = async (newBudget: any) => {
    try {
      const budgetJson = JSON.stringify(newBudget);
      const response = await updateTokenBudget(budgetJson);
      const result = JSON.parse(response);
      if (result.success) {
        setShowBudgetSlider(false);
        await fetchContextStats();
      }
    } catch (error) {
      console.error('Error updating budget:', error);
    }
  };

  const handlePinToggle = useCallback(async (messageId: string, shouldPin: boolean) => {
    try {
      const response = shouldPin
        ? await pinMessage(messageId)
        : await unpinMessage(messageId);
      const result = JSON.parse(response);
      if (result.success) {
        // Update message in local state
        setMessages(prev => prev.map(msg =>
          msg.id === messageId
            ? { ...msg, metadata: { ...msg.metadata, pinned: shouldPin } }
            : msg
        ));
        await fetchContextStats();
      }
    } catch (error) {
      console.error('Error toggling pin:', error);
    }
  }, [fetchContextStats]);

  // Safe numeric reads for stats bar
  const statTokens    = contextStats?.total_tokens    ?? 0;
  const statMaxTokens = contextStats?.max_total_tokens ?? 0;
  const statMessages  = contextStats?.total_messages   ?? 0;
  const statTruncated = contextStats?.truncation_count ?? 0;

  /* ── Render ────────────────────────────────── */
  return (
    <div className="chat-interface">

      {/* ── Loading Dialog ── */}
      <LoadingDialog
        visible={showLoading}
        status={loadingStatus}
        phase={loadingPhase}
        steps={loadingPhase === 'init' ? initSteps : undefined}
      />

      {/* ── Connect a model: the first view while no backend answers ── */}
      {!showLoading && backendStatus && (
        backendStatus.state === 'failed' || backendStatus.state === 'not_configured' ||
        (backendStatus.state === 'checking' && (backendStatus.seconds ?? 0) >= 5 && !triageStartedRef.current)
      ) && (
        <ConnectPanel
          status={backendStatus}
          onOpenSetup={() => showSettings()}
          onRetry={() => { startBackendCheck(); }}
        />
      )}

      {/* ════════════════════════════════════════
          TOP BAR — single 44px row, all info inline
      ════════════════════════════════════════ */}
      <header className="chat-header">

        {/* ── Brand cluster ── */}
        <div className="hdr-brand">
          <button
            className={`hdr-logo-btn${(isLoading || !bridgeReady) ? ' hdr-logo-btn--active' : ''}`}
            onClick={handleLogoClick}
            aria-label="Eye status"
            title={(isLoading || !bridgeReady) ? 'Click to see loading status' : 'Eye Forensic Assistant'}
          >
            <img src={eyeIcon} alt="Eye" className="hdr-logo-img" />
          </button>

          <div className="hdr-brand-text">
            <span className="hdr-title">Eye</span>
            <span className="hdr-subtitle">Forensic Assistant</span>
          </div>

          {/* Thin vertical rule */}
          <span className="hdr-rule" aria-hidden="true" />

          {/* Model / connection status */}
          <div className="hdr-model-container">
            <button 
              className={`hdr-model-pill${bridgeReady ? '' : ' hdr-model-pill--off'}${
                backendStatus?.state === 'checking' ? ' hdr-model-pill--checking'
                : (backendStatus?.state === 'failed' || backendStatus?.state === 'not_configured') ? ' hdr-model-pill--failed'
                : ''}`}
              onClick={handleModelMenuToggle}
              title="Click to switch active model"
            >
              <span className={`hdr-status-dot${bridgeReady ? ' hdr-status-dot--on' : ''}${
                backendStatus?.state === 'checking' ? ' hdr-status-dot--checking'
                : (backendStatus?.state === 'failed' || backendStatus?.state === 'not_configured') ? ' hdr-status-dot--failed'
                : ''}`} title={backendStatus?.detail || ''} />
              <span className="hdr-model-label">
                {bridgeReady
                  ? contextStats?.backend
                    ? `${contextStats.backend.toUpperCase()} · ${contextStats.model_name ?? ''}`
                    : 'Connected'
                  : 'Offline'}
              </span>
            </button>
            
            {showModelMenu && (
              <div className="model-menu-dropdown">
                <div className="model-menu-header">Select AI Model</div>
                <div className="model-menu-list">
                  {fetchingModels ? (
                    <div className="model-menu-empty">Loading models...</div>
                  ) : (!groupedBackends || 
                       (groupedBackends["Cloud API"].length === 0 && 
                        groupedBackends["Local Server"].length === 0 && 
                        groupedBackends["Local CLI"].length === 0)) ? (
                    <div className="model-menu-empty" style={{ color: '#f43f5e' }}>No models found. Check connection.</div>
                  ) : (
                    (Object.keys(groupedBackends) as Array<keyof GroupedBackendResponse>).map((category) => {
                      const list = groupedBackends[category];
                      if (!list || list.length === 0) return null;
                      return (
                        <React.Fragment key={category}>
                          <div className="model-group-header">{category}</div>
                          {list.map((m) => (
                            <button
                              key={`${m.backend}:${m.model_name}`}
                              className={`model-menu-item ${m.is_active ? 'model-menu-item--active' : ''}`}
                              onClick={() => handleModelSelect(`${m.backend}:${m.model_name}`)}
                            >
                              <span className="model-item-name">{m.label}
                                {m.model_name === 'claude-haiku-5-5' && (
                                  <span className="model-item-cost" title="The lowest-cost Claude model">lowest cost</span>
                                )}
                              </span>
                              <span className="model-item-quota">{m.backend.toUpperCase()}</span>
                            </button>
                          ))}
                        </React.Fragment>
                      );
                    })
                  )}
                </div>
                <button
                  className="model-menu-item model-menu-doctor"
                  title="Check the provider, model name, key, connection, tool use and effort, and offer fixes"
                  onClick={() => { setShowModelMenu(false); sendMessage('Check model setup'); }}
                >
                  <span className="model-item-name">Check model setup</span>
                  <span className="model-item-quota">DOCTOR</span>
                </button>
              </div>
            )}
          </div>
        </div>

        {/* ── Centre — context stats (only when ready) ── */}
        {bridgeReady && contextStats && (
          <div className="hdr-stats" role="status" aria-label="Context stats">
            <span className="hdr-stat">{statMessages} msg</span>
            <span className="hdr-stat-sep" />
            <span className="hdr-stat">
              {statTokens.toLocaleString()} / {statMaxTokens.toLocaleString()} tok
            </span>
            {statTruncated > 0 && (
              <>
                <span className="hdr-stat-sep" />
                <span className="hdr-stat hdr-stat--warn">! {statTruncated}x</span>
              </>
            )}
          </div>
        )}

        {/* ── Actions ── */}
        <div className="hdr-actions">
          {bridgeReady && (
            <>
              <button
                className="hdr-action-btn"
                onClick={showSettings}
                title="Settings & Onboarding"
                aria-label="Settings"
              >
                <IconSettings size={13} />
                <span>Settings</span>
              </button>
              <span className="hdr-rule" style={{ height: '14px', margin: '0 4px' }} aria-hidden="true" />
              <button
                className="hdr-action-btn"
                onClick={openAddEvidence}
                title="Import external forensics evidence (SQLite, CSV or JSON) into this case"
                aria-label="Add Evidence"
              >
                <IconDatabase size={13} />
                <span>Add Evidence</span>
              </button>
              <button
                className="hdr-action-btn"
                onClick={showCaseContext}
                title="View case context and objectives"
              >
                <IconClipboardList size={13} />
                <span>Context</span>
              </button>
              <button
                className="hdr-action-btn"
                onClick={showCaseSummary}
                title="View current case summary"
              >
                <IconChartBar size={13} />
                <span>Summary</span>
              </button>
              <button
                className="hdr-action-btn"
                onClick={openComplianceWindow}
                title="Open GEP Protocol Compliance dashboard in a separate window"
                aria-label="Compliance"
              >
                <IconLayers size={13} />
                <span>Compliance</span>
              </button>
              <button
                className="hdr-action-btn"
                onClick={openNarrativeMapWindow}
                title="Open the Narrative Map — the Eye's persistent case memory"
                aria-label="Narrative Map"
              >
                <IconBrain size={13} />
                <span>Narrative Map</span>
              </button>
              <button
                className="hdr-action-btn"
                onClick={openEvidenceWindow}
                title="Open Imported Evidence — all imported databases and documents with SHA-256 hashes and integrity verification"
                aria-label="Imported Evidence"
              >
                <IconDatabase size={13} />
                <span>Evidence</span>
              </button>
              <button
                className="hdr-action-btn hdr-action-btn--danger"
                onClick={handleClearHistory}
                title="Clear conversation history"
                aria-label="Clear"
              >
                <IconTrash size={13} />
              </button>
            </>
          )}
        </div>
      </header>

      {/* ── Truncation Warning Banner ── */}
      {truncationWarning && (
        <TruncationWarningBanner
          warningData={truncationWarning}
          onDismiss={handleDismissWarning}
          onViewHistory={handleViewFullHistory}
          onIncreaseBudget={handleIncreaseBudget}
        />
      )}



      {slowSeconds > 0 && (
        <div className="slow-notice" role="status">
          The model is taking longer than usual to answer ({slowSeconds} s). The Eye is still
          waiting; nothing has failed. If it stays like this, check the network or the model service.
        </div>
      )}

      {/* ── Messages ── */}
      <main className="chat-messages">
        <ErrorBoundary componentName="Message List">
          <MessageList
            messages={messages}
            onActionChipClick={handleActionChipClick}
            onActionChipExecute={handleActionChipExecute}
            onOptionSelect={handleOptionSelect}
            isLoading={isLoading}
            thinkingSteps={thinkingSteps}
            liveDialogue={dialogue}
            onPinToggle={handlePinToggle}
          />
        </ErrorBoundary>
      </main>

      {/* ── Input ── */}
      <InputBar
        onSend={sendMessage}
        disabled={isLoading}
        value={inputValue}
        onChange={setInputValue}
        contextStats={contextStats}
        bridgeReady={bridgeReady}
        switchingTo={switchingTo}
      />

      {/* ── Token Budget Slider Modal ── */}
      {showBudgetSlider && contextStats && (
        <TokenBudgetSlider
          currentBudget={{
            conversation_history: 8000,
            system_prompt: 4000,
            rag_context: 2000,
            tool_results: 4000,
            max_total: statMaxTokens,
          }}
          onBudgetChange={handleBudgetChange}
          onClose={() => setShowBudgetSlider(false)}
        />
      )}

      {/* ── Full History Modal ── */}
      {showFullHistory && (
        <FullHistoryModal
          messages={fullHistoryMessages}
          onClose={() => setShowFullHistory(false)}
        />
      )}
      {/* ── Toast Notification ── */}
      {toast && (
        <div className={`chat-toast ${toast.type}`}>
          <span className="toast-message">{toast.message}</span>
        </div>
      )}
    </div>
  );
};

export default ChatInterface;
