import React, { useState, useEffect, useCallback } from 'react';
import type { Message, ContextStats, ThinkingStep } from './types';
import MessageList from './MessageList';
import InputBar from './InputBar';
import LoadingDialog from './LoadingDialog';
import TruncationWarningBanner from './TruncationWarningBanner';
import TokenBudgetSlider from './TokenBudgetSlider';
import FullHistoryModal from './FullHistoryModal';
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
  getAvailableModelsWithQuota,
  switchActiveModel,
  showCaseContext,
  showCaseSummary,
  showSettings,
  initializeTriage,
  onTruncationWarning,
  pinMessage,
  unpinMessage,
  updateTokenBudget,
} from './bridge';
import { IconTrash, IconClipboardList, IconChartBar, IconSettings } from './Icons';
import eyeIcon from './assets/eye_icon.png';
import './ChatInterface.css';

const ChatInterface: React.FC = () => {
  const [messages, setMessages]           = useState<Message[]>([]);
  const [inputValue, setInputValue]       = useState('');
  const [isLoading, setIsLoading]         = useState(false);
  const [bridgeReady, setBridgeReady]     = useState(false);
  const [contextStats, setContextStats]   = useState<ContextStats | null>(null);
  const [thinkingSteps, setThinkingSteps] = useState<ThinkingStep[]>([]);
  // Loading dialog: visible on startup until bridge is ready; also toggled by logo btn
  const [showLoading, setShowLoading]     = useState(true);
  const [loadingStatus, setLoadingStatus] = useState<string | undefined>(undefined);
  const [loadingPhase, setLoadingPhase]   = useState<'init' | 'processing'>('init');

  // Model Menu State
  const [showModelMenu, setShowModelMenu] = useState(false);
  const [availableModels, setAvailableModels] = useState<{id: string, quota: string}[]>([]);
  const [fetchingModels, setFetchingModels] = useState(false);

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
    let unsubTW: (() => void) | undefined;

    const setup = async () => {
      try {
        setLoadingStatus('Connecting to Python bridge...');
        await initializeBridge();
        setLoadingStatus('Loading forensic context...');
        setBridgeReady(true);
        await fetchContextStats();
        await loadHistory();
        
        // Set up signal listeners before triggering any queries
        unsubQC = onQueryComplete((json: string) => {
          try {
            const result = JSON.parse(json);
            if (result.error && !(result.data?.action_chips)) {
              appendAssistantMessage(`Error: ${result.error}`);
              setIsLoading(false);
              setThinkingSteps([]);
              return;
            }
            const data = result.data || result;
            const msg: Message = {
              id: `assistant-${Date.now()}`,
              role: 'assistant',
              content: data.response || data.content || (result.error ? `Connection Failed: ${result.error}` : ''),
              timestamp: new Date().toISOString(),
              data_viewer:  data.data_viewer  || undefined,
              action_chips: data.action_chips || undefined,
              option_menu:  data.option_menu  || undefined,
            };
            setMessages(prev => [...prev, msg]);
            setIsLoading(false);
            setThinkingSteps([]);
            fetchContextStats();
          } catch {
            setIsLoading(false);
            setThinkingSteps([]);
          }
        });

        unsubRU = onReportUpdated((_json: string) => {});

        unsubEO = onErrorOccurred((errMsg: string) => {
          appendAssistantMessage(`Backend error: ${errMsg}`);
        });

        unsubSU = onStatusUpdated((statusJson: string) => {
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
            setThinkingSteps(prev => [
              ...prev,
              { step_id: `fb-${Date.now()}`, type: 'thinking', label: statusJson, status: 'active' },
            ]);
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

        // Trigger automated triage report (only runs if report is empty)
        try {
          await initializeTriage();
        } catch (e) {
          console.error("Failed to trigger initial triage", e);
        }
        
        // Dismiss loading dialog after a brief pause so user sees the final state
        setTimeout(() => setShowLoading(false), 600);
      } catch {
        setBridgeReady(false);
        setLoadingStatus('Bridge connection failed');
        setTimeout(() => setShowLoading(false), 2000);
      }
    };

    setup();
    return () => { unsubQC?.(); unsubRU?.(); unsubEO?.(); unsubSU?.(); unsubTW?.(); };
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

  const handleModelMenuToggle = async () => {
    if (!showModelMenu) {
      // Opening menu, fetch models
      setFetchingModels(true);
      const models = await getAvailableModelsWithQuota();
      setAvailableModels(models);
      setFetchingModels(false);
    }
    setShowModelMenu(!showModelMenu);
  };

  const handleModelSelect = async (modelId: string) => {
    setShowModelMenu(false);
    const success = await switchActiveModel(modelId);
    if (success) {
      fetchContextStats();
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
            id: `history-${i}-${Date.now()}`,
            role: m.role,
            content: m.content,
            timestamp: new Date().toISOString(),
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
            id: `cleared-${i}-${Date.now()}`,
            role: m.role,
            content: m.content,
            timestamp: new Date().toISOString(),
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

  /* ── Send ──────────────────────────────────── */
  const sendMessage = async (query: string) => {
    if (!query.trim()) return;
    const userMsg: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: query,
      timestamp: new Date().toISOString(),
    };
    setMessages(prev => [...prev, userMsg]);
    setIsLoading(true);
    setThinkingSteps([]);

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
            content: d.response || '',
            timestamp: new Date().toISOString(),
            data_viewer:  d.data_viewer  || undefined,
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

  const handleOptionSelect = (query: string) => sendMessage(query);
  const handleActionChipClick = (query: string) => setInputValue(query);

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

  const handlePinToggle = async (messageId: string, shouldPin: boolean) => {
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
  };

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
      />

      {/* ════════════════════════════════════════
          TOP BAR — single 44px row, all info inline
      ════════════════════════════════════════ */}
      <header className="chat-header">

        {/* ── Brand cluster ── */}
        <div className="hdr-brand">
          <button
            className={`hdr-logo-btn${(isLoading || !bridgeReady) ? ' hdr-logo-btn--active' : ''}`}
            onClick={handleLogoClick}
            aria-label="EYE status"
            title={(isLoading || !bridgeReady) ? 'Click to see loading status' : 'EYE Forensic Assistant'}
          >
            <img src={eyeIcon} alt="EYE" className="hdr-logo-img" />
          </button>

          <div className="hdr-brand-text">
            <span className="hdr-title">EYE</span>
            <span className="hdr-subtitle">Forensic Assistant</span>
          </div>

          {/* Thin vertical rule */}
          <span className="hdr-rule" aria-hidden="true" />

          {/* Model / connection status */}
          <div className="hdr-model-container">
            <button 
              className={`hdr-model-pill${bridgeReady ? '' : ' hdr-model-pill--off'}`}
              onClick={handleModelMenuToggle}
              title="Click to switch active model"
            >
              <span className={`hdr-status-dot${bridgeReady ? ' hdr-status-dot--on' : ''}`} />
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
                  ) : availableModels.length === 0 ? (
                    <div className="model-menu-empty" style={{ color: '#f43f5e' }}>No models found. Check connection.</div>
                  ) : (
                    availableModels.map((m) => (
                      <button
                        key={m.id}
                        className={`model-menu-item ${m.id === contextStats?.model_name ? 'model-menu-item--active' : ''}`}
                        onClick={() => handleModelSelect(m.id)}
                      >
                        <span className="model-item-name">{m.id}</span>
                        <span className="model-item-quota" title={m.quota}>{m.quota}</span>
                      </button>
                    ))
                  )}
                </div>
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
                <span className="hdr-stat hdr-stat--warn">⚠ {statTruncated}x</span>
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



      {/* ── Messages ── */}
      <main className="chat-messages">
        <MessageList
          messages={messages}
          onActionChipClick={handleActionChipClick}
          onOptionSelect={handleOptionSelect}
          isLoading={isLoading}
          thinkingSteps={thinkingSteps}
          onPinToggle={handlePinToggle}
        />
      </main>

      {/* ── Input ── */}
      <InputBar
        onSend={sendMessage}
        disabled={isLoading}
        value={inputValue}
        onChange={setInputValue}
        contextStats={contextStats}
        bridgeReady={bridgeReady}
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
    </div>
  );
};

export default ChatInterface;
