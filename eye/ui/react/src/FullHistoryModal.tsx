import React, { useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import './FullHistoryModal.css';

interface MessageMetadata {
  preserve_evidence?: boolean;
  evidence_patterns?: string[];
  pinned?: boolean;
  is_summary?: boolean;
  summarized_count?: number;
}

interface HistoryMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  metadata?: MessageMetadata;
}

interface FullHistoryModalProps {
  messages: HistoryMessage[];
  onClose: () => void;
}

/**
 * FullHistoryModal Component
 * 
 * Displays the complete conversation log in a modal, including all messages
 * that may have been summarized. Highlights summarized messages with a yellow
 * background and shows evidence preservation metadata.
 * 
 */
const FullHistoryModal: React.FC<FullHistoryModalProps> = ({ messages, onClose }) => {
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Focus trap for accessibility
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const formatTimestamp = (isoString: string): string => {
    try {
      const date = new Date(isoString);
      return date.toLocaleString([], {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
    } catch {
      return isoString;
    }
  };

  return (
    <div className="full-history-overlay" onClick={onClose}>
      <div
        className="full-history-modal"
        onClick={(e) => e.stopPropagation()}
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="history-modal-title"
      >
        <div className="history-header">
          <h2 id="history-modal-title" className="history-title">
            Complete Conversation History
          </h2>
          <button
            className="history-close-btn"
            onClick={onClose}
            aria-label="Close history"
          >
            ×
          </button>
        </div>

        <div className="history-content">
          {messages.length === 0 ? (
            <div className="history-empty">
              <p>No conversation history available.</p>
            </div>
          ) : (
            <div className="history-messages">
              {messages.map((message) => {
                const isSummary = message.metadata?.is_summary || false;
                const isPinned = message.metadata?.pinned || false;
                const hasEvidence = message.metadata?.preserve_evidence || false;
                const evidencePatterns = message.metadata?.evidence_patterns || [];

                return (
                  <div
                    key={message.id}
                    className={`history-message history-message--${message.role} ${
                      isSummary ? 'history-message--summary' : ''
                    } ${isPinned ? 'history-message--pinned' : ''} ${
                      hasEvidence ? 'history-message--evidence' : ''
                    }`}
                  >
                    <div className="history-message-header">
                      <div className="history-message-meta">
                        <span className="history-role">
                          {message.role === 'user' ? 'You' : message.role === 'assistant' ? 'EYE' : 'System'}
                        </span>
                        <span className="history-timestamp">
                          {formatTimestamp(message.timestamp)}
                        </span>
                      </div>

                      <div className="history-message-badges">
                        {isPinned && (
                          <span className="history-badge history-badge--pinned" title="Pinned message">
                            📌 Pinned
                          </span>
                        )}
                        {hasEvidence && (
                          <span
                            className="history-badge history-badge--evidence"
                            title={`Evidence detected: ${evidencePatterns.join(', ')}`}
                          >
                            🔒 Evidence
                          </span>
                        )}
                        {isSummary && (
                          <span
                            className="history-badge history-badge--summary"
                            title={`Summary of ${message.metadata?.summarized_count || 0} messages`}
                          >
                            📝 Summary ({message.metadata?.summarized_count || 0})
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="history-message-content">
                      <ReactMarkdown>{message.content}</ReactMarkdown>
                    </div>

                    {evidencePatterns.length > 0 && (
                      <div className="history-evidence-info">
                        <strong>Evidence patterns:</strong> {evidencePatterns.join(', ')}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="history-footer">
          <div className="history-stats">
            <span className="history-stat">
              Total messages: <strong>{messages.length}</strong>
            </span>
            <span className="history-stat">
              Pinned: <strong>{messages.filter((m) => m.metadata?.pinned).length}</strong>
            </span>
            <span className="history-stat">
              Evidence: <strong>{messages.filter((m) => m.metadata?.preserve_evidence).length}</strong>
            </span>
            <span className="history-stat">
              Summaries: <strong>{messages.filter((m) => m.metadata?.is_summary).length}</strong>
            </span>
          </div>
          <button className="history-btn history-btn--primary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
};

export default FullHistoryModal;
