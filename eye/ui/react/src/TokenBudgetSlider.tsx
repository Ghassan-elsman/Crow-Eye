import React, { useState, useEffect } from 'react';
import './TokenBudgetSlider.css';

interface TokenBudgetAllocation {
  conversation_history: number;
  system_prompt: number;
  rag_context: number;
  tool_results: number;
  max_total: number;
}

interface TokenBudgetSliderProps {
  currentBudget: TokenBudgetAllocation;
  onBudgetChange: (newBudget: TokenBudgetAllocation) => void;
  onClose: () => void;
}

/**
 * TokenBudgetSlider Component
 * 
 * Interactive slider interface for adjusting token budget allocation across
 * different components (conversation history, system prompt, RAG context, tool results).
 * Provides real-time preview of budget changes with visual feedback.
 * 
 */
const TokenBudgetSlider: React.FC<TokenBudgetSliderProps> = ({
  currentBudget,
  onBudgetChange,
  onClose,
}) => {
  const [budget, setBudget] = useState<TokenBudgetAllocation>(currentBudget);
  const [hasChanges, setHasChanges] = useState(false);

  useEffect(() => {
    setBudget(currentBudget);
  }, [currentBudget]);

  const handleSliderChange = (component: keyof Omit<TokenBudgetAllocation, 'max_total'>, value: number) => {
    const newBudget = { ...budget, [component]: value };
    setBudget(newBudget);
    setHasChanges(true);
  };

  const handleApply = () => {
    onBudgetChange(budget);
    setHasChanges(false);
  };

  const handleReset = () => {
    setBudget(currentBudget);
    setHasChanges(false);
  };

  const totalAllocated = 
    budget.conversation_history +
    budget.system_prompt +
    budget.rag_context +
    budget.tool_results;

  const isOverBudget = totalAllocated > budget.max_total;

  const getPercentage = (value: number): number => {
    return budget.max_total > 0 ? (value / budget.max_total) * 100 : 0;
  };

  return (
    <div className="token-budget-slider-overlay" onClick={onClose}>
      <div className="token-budget-slider" onClick={(e) => e.stopPropagation()}>
        <div className="slider-header">
          <h3 className="slider-title">Token Budget Allocation</h3>
          <button
            className="slider-close-btn"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="slider-content">
          <div className="budget-summary">
            <div className="summary-item">
              <span className="summary-label">Total Allocated:</span>
              <span className={`summary-value ${isOverBudget ? 'summary-value--error' : ''}`}>
                {totalAllocated.toLocaleString()} tokens
              </span>
            </div>
            <div className="summary-item">
              <span className="summary-label">Maximum Budget:</span>
              <span className="summary-value">{budget.max_total.toLocaleString()} tokens</span>
            </div>
            {isOverBudget && (
              <div className="budget-warning">
                ⚠️ Total allocation exceeds maximum budget by {(totalAllocated - budget.max_total).toLocaleString()} tokens
              </div>
            )}
          </div>

          <div className="budget-sliders">
            {/* Tool Results Slider */}
            <div className="slider-group">
              <div className="slider-label-row">
                <label htmlFor="tool-results-slider" className="slider-label">
                  Tool Results (Forensic Evidence)
                </label>
                <span className="slider-value">{budget.tool_results.toLocaleString()}</span>
              </div>
              <input
                id="tool-results-slider"
                type="range"
                min="4000"
                max="16000"
                step="500"
                value={budget.tool_results}
                onChange={(e) => handleSliderChange('tool_results', parseInt(e.target.value))}
                className="slider-input slider-input--priority-high"
              />
              <div className="slider-bar">
                <div
                  className="slider-fill slider-fill--priority-high"
                  style={{ width: `${getPercentage(budget.tool_results)}%` }}
                />
              </div>
              <div className="slider-hint">Minimum: 4,000 tokens (highest priority)</div>
            </div>

            {/* Conversation History Slider */}
            <div className="slider-group">
              <div className="slider-label-row">
                <label htmlFor="conversation-slider" className="slider-label">
                  Conversation History
                </label>
                <span className="slider-value">{budget.conversation_history.toLocaleString()}</span>
              </div>
              <input
                id="conversation-slider"
                type="range"
                min="2000"
                max="12000"
                step="500"
                value={budget.conversation_history}
                onChange={(e) => handleSliderChange('conversation_history', parseInt(e.target.value))}
                className="slider-input slider-input--priority-medium"
              />
              <div className="slider-bar">
                <div
                  className="slider-fill slider-fill--priority-medium"
                  style={{ width: `${getPercentage(budget.conversation_history)}%` }}
                />
              </div>
              <div className="slider-hint">Minimum: 2,000 tokens</div>
            </div>

            {/* System Prompt Slider */}
            <div className="slider-group">
              <div className="slider-label-row">
                <label htmlFor="system-prompt-slider" className="slider-label">
                  System Prompt
                </label>
                <span className="slider-value">{budget.system_prompt.toLocaleString()}</span>
              </div>
              <input
                id="system-prompt-slider"
                type="range"
                min="1000"
                max="8000"
                step="250"
                value={budget.system_prompt}
                onChange={(e) => handleSliderChange('system_prompt', parseInt(e.target.value))}
                className="slider-input slider-input--priority-low"
              />
              <div className="slider-bar">
                <div
                  className="slider-fill slider-fill--priority-low"
                  style={{ width: `${getPercentage(budget.system_prompt)}%` }}
                />
              </div>
              <div className="slider-hint">Minimum: 1,000 tokens</div>
            </div>

            {/* RAG Context Slider */}
            <div className="slider-group">
              <div className="slider-label-row">
                <label htmlFor="rag-context-slider" className="slider-label">
                  RAG Context (Knowledge Base)
                </label>
                <span className="slider-value">{budget.rag_context.toLocaleString()}</span>
              </div>
              <input
                id="rag-context-slider"
                type="range"
                min="500"
                max="6000"
                step="250"
                value={budget.rag_context}
                onChange={(e) => handleSliderChange('rag_context', parseInt(e.target.value))}
                className="slider-input slider-input--priority-lowest"
              />
              <div className="slider-bar">
                <div
                  className="slider-fill slider-fill--priority-lowest"
                  style={{ width: `${getPercentage(budget.rag_context)}%` }}
                />
              </div>
              <div className="slider-hint">Minimum: 500 tokens (lowest priority)</div>
            </div>
          </div>
        </div>

        <div className="slider-footer">
          <button
            className="slider-btn slider-btn--secondary"
            onClick={handleReset}
            disabled={!hasChanges}
          >
            Reset
          </button>
          <button
            className="slider-btn slider-btn--primary"
            onClick={handleApply}
            disabled={!hasChanges || isOverBudget}
          >
            Apply Changes
          </button>
        </div>
      </div>
    </div>
  );
};

export default TokenBudgetSlider;
