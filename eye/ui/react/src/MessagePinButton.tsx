import React, { useState } from 'react';
import './MessagePinButton.css';

interface MessagePinButtonProps {
  messageId: string;
  isPinned: boolean;
  onPinToggle: (messageId: string, isPinned: boolean) => void;
}

/**
 * MessagePinButton Component
 * 
 * Toggle button for pinning/unpinning messages to prevent them from being
 * summarized during token budget management. Pinned messages are preserved
 * in conversation history regardless of token limits.
 * 
 */
const MessagePinButton: React.FC<MessagePinButtonProps> = ({
  messageId,
  isPinned,
  onPinToggle,
}) => {
  const [isProcessing, setIsProcessing] = useState(false);

  const handleClick = async () => {
    if (isProcessing) return;

    setIsProcessing(true);
    try {
      await onPinToggle(messageId, !isPinned);
    } catch (error) {
      console.error('Error toggling pin:', error);
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <button
      className={`message-pin-button ${isPinned ? 'message-pin-button--pinned' : ''} ${isProcessing ? 'message-pin-button--processing' : ''}`}
      onClick={handleClick}
      disabled={isProcessing}
      title={isPinned ? 'Unpin message' : 'Pin message to preserve from summarization'}
      aria-label={isPinned ? 'Unpin message' : 'Pin message'}
      aria-pressed={isPinned}
    >
      <span className="pin-icon" aria-hidden="true">
        {isPinned ? (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 4.5l-3 3M16 11l-3 3M19.5 4.5L16 8M4.5 19.5L10 14M16 8l-3 3"></path>
            <path d="M21 4.5L19.5 6M18 7.5L16.5 9M15 10.5L13.5 12M12 13.5L10.5 15"></path>
            <path d="M12 13l-4 4-2-2 4-4"></path>
            <path d="M12 13l3 3"></path>
            <line x1="12" y1="13" x2="15" y2="16"></line>
          </svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 13L4 21"></path>
            <path d="M16 11L13 14"></path>
            <path d="M10 8L7 11"></path>
            <path d="M12 5l-7 7 3 3 7-7"></path>
          </svg>
        )}
      </span>
      <span className="pin-label">
        {isPinned ? 'Pinned' : 'Pin'}
      </span>
    </button>
  );
};

export default MessagePinButton;
