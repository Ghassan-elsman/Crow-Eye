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
        {isPinned ? '📌' : '📍'}
      </span>
      <span className="pin-label">
        {isPinned ? 'Pinned' : 'Pin'}
      </span>
    </button>
  );
};

export default MessagePinButton;
