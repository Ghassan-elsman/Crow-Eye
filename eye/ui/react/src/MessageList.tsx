import React, { useEffect, useRef } from 'react';
import type { Message, ThinkingStep } from './types';
import DataViewer from './DataViewer';
import ActionChips from './ActionChips';
import OptionMenu from './OptionMenu';
import ThinkingTrace from './ThinkingTrace';
import MessagePinButton from './MessagePinButton';
import ReactMarkdown from 'react-markdown';
import eyeIcon from './assets/eye_icon.png';
import './MessageList.css';

interface MessageListProps {
  messages: Message[];
  onActionChipClick: (query: string) => void;
  onOptionSelect: (query: string, label: string) => void;
  isLoading?: boolean;
  thinkingSteps?: ThinkingStep[];
  onPinToggle?: (messageId: string, isPinned: boolean) => void;
}

const MessageList: React.FC<MessageListProps> = ({
  messages,
  onActionChipClick,
  onOptionSelect,
  isLoading,
  thinkingSteps = [],
  onPinToggle,
}) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading, thinkingSteps]);

  return (
    <div className="message-list" role="log" aria-live="polite" aria-label="Conversation">
      {messages.length === 0 && !isLoading && (
        <div className="message-list-empty">
          <div className="empty-icon-ring">
            <img src={eyeIcon} alt="EYE" className="empty-eye-img" />
          </div>
          <p className="empty-title">EYE Forensic Assistant</p>
          <p className="empty-subtitle">Ask about artifacts, timelines, or investigate a case.</p>
        </div>
      )}

      {messages.map((message) => (
        <div
          key={message.id}
          className={`message message--${message.role} ${
            message.metadata?.is_summary ? 'message--summary' : ''
          } ${message.metadata?.pinned ? 'message--pinned' : ''} ${
            message.metadata?.preserve_evidence ? 'message--evidence' : ''
          }`}
          aria-label={message.role === 'user' ? 'Your message' : 'EYE response'}
        >
          {message.role === 'assistant' && (
            <div className="message-avatar-col">
              <div className="message-avatar">
                <img src={eyeIcon} alt="EYE" className="avatar-eye-img" />
              </div>
            </div>
          )}


          <div className="message-body">
            <div className="message-meta">
              <span className="message-role-label">
                {message.role === 'user' ? 'You' : 'EYE'}
              </span>
              <span className="message-time">
                {new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
              {message.metadata?.pinned && (
                <span className="message-badge message-badge--pinned" title="Pinned message">
                  📌
                </span>
              )}
              {message.metadata?.preserve_evidence && (
                <span
                  className="message-badge message-badge--evidence"
                  title={`Evidence: ${message.metadata.evidence_patterns?.join(', ') || 'detected'}`}
                >
                  🔒
                </span>
              )}
              {message.metadata?.is_summary && (
                <span
                  className="message-badge message-badge--summary"
                  title={`Summary of ${message.metadata.summarized_count || 0} messages`}
                >
                  📝
                </span>
              )}
            </div>

            <div className="message-bubble">
              <div className="message-content">
                <ReactMarkdown>{message.content}</ReactMarkdown>
              </div>

              {message.option_menu && message.option_menu.length > 0 && (
                <OptionMenu
                  items={message.option_menu}
                  onSelect={onOptionSelect}
                />
              )}

              {message.data_viewer && (
                <DataViewer {...message.data_viewer} />
              )}

              {message.action_chips && message.action_chips.length > 0 && (
                <ActionChips
                  chips={message.action_chips}
                  onChipClick={onActionChipClick}
                />
              )}

              {/* Pin button for all messages */}
              {onPinToggle && (
                <div className="message-actions">
                  <MessagePinButton
                    messageId={message.id}
                    isPinned={message.metadata?.pinned || false}
                    onPinToggle={onPinToggle}
                  />
                </div>
              )}
            </div>
          </div>

          {message.role === 'user' && (
            <div className="message-avatar-col message-avatar-col--user">
              <div className="message-avatar message-avatar--user">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                  <circle cx="12" cy="7" r="4"/>
                </svg>
              </div>
            </div>
          )}
        </div>
      ))}

      {/* Live thinking trace for in-progress queries */}
      {isLoading && (
        <div className="message message--assistant message--thinking" aria-label="EYE is processing">
          <div className="message-avatar-col">
            <div className="message-avatar message-avatar--pulsing">
              <img src={eyeIcon} alt="EYE" className="avatar-eye-img" />
            </div>
          </div>
          <div className="message-body">
            <div className="message-meta">
              <span className="message-role-label">EYE</span>
            </div>
            <div className="message-bubble message-bubble--thinking">
              {thinkingSteps.length > 0 ? (
                <ThinkingTrace steps={thinkingSteps} />
              ) : (
                <div className="thinking-dots">
                  <span /><span /><span />
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
};

export default MessageList;
