import React from 'react';
import './TruncationWarningBanner.css';

interface TruncationWarningData {
  type: 'truncation_warning';
  count: number;
  total_tokens: number;
  budget: number;
  timestamp: string;
}

interface TruncationWarningBannerProps {
  warningData: TruncationWarningData | null;
  onDismiss: () => void;
  onViewHistory: () => void;
  onIncreaseBudget: () => void;
}

/**
 * TruncationWarningBanner Component
 * 
 * Displays a non-intrusive dismissible banner when forensic evidence is truncated
 * or summarized due to token budget limits. Provides action buttons for viewing
 * full history and adjusting token budget.
 * 
 */
const TruncationWarningBanner: React.FC<TruncationWarningBannerProps> = ({
  warningData,
  onDismiss,
  onViewHistory,
  onIncreaseBudget,
}) => {
  if (!warningData) return null;

  const formatTimestamp = (isoString: string): string => {
    try {
      const date = new Date(isoString);
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return '';
    }
  };

  return (
    <div className="truncation-warning-banner" role="alert" aria-live="polite">
      <div className="warning-icon" aria-hidden="true">⚠️</div>
      
      <div className="warning-content">
        <div className="warning-title">
          <strong>Warning: {warningData.count} tool result{warningData.count !== 1 ? 's' : ''} were summarized</strong>
        </div>
        <div className="warning-details">
          Token limit reached ({warningData.total_tokens.toLocaleString()} / {warningData.budget.toLocaleString()} tokens)
          {warningData.timestamp && (
            <span className="warning-time"> • {formatTimestamp(warningData.timestamp)}</span>
          )}
        </div>
      </div>

      <div className="warning-actions">
        <button
          className="warning-btn warning-btn--primary"
          onClick={onViewHistory}
          title="View complete conversation log"
        >
          View Full History
        </button>
        <button
          className="warning-btn warning-btn--secondary"
          onClick={onIncreaseBudget}
          title="Adjust token budget allocation"
        >
          Increase Budget
        </button>
        <button
          className="warning-btn warning-btn--dismiss"
          onClick={onDismiss}
          title="Dismiss warning"
          aria-label="Dismiss warning"
        >
          ×
        </button>
      </div>
    </div>
  );
};

export default TruncationWarningBanner;
