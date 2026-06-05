import React, { useRef, useEffect, type KeyboardEvent } from 'react';
import ModelBadge from './ModelBadge';
import type { ContextStats } from './types';
import { IconSend } from './Icons';
import './InputBar.css';

interface InputBarProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  value: string;
  onChange: (value: string) => void;
  contextStats: ContextStats | null;
  bridgeReady: boolean;
  switchingTo?: string | null;
}

const InputBar: React.FC<InputBarProps> = ({
  onSend,
  disabled = false,
  value,
  onChange,
  contextStats,
  bridgeReady,
  switchingTo = null,
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-grow textarea height up to max-height set in CSS
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 150)}px`;
  }, [value]);

  const handleSend = () => {
    if (value.trim() && !disabled) {
      onSend(value.trim());
      onChange('');
      // Reset height after send
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const canSend = value.trim().length > 0 && !disabled;

  return (
    <div className={`input-bar ${disabled ? 'input-bar--loading' : ''}`}>
      {switchingTo && (
        <div
          style={{
            padding: '6px 14px',
            fontSize: 12,
            color: '#fbbf24',
            background: 'rgba(245,158,11,0.08)',
            borderBottom: '1px solid rgba(245,158,11,0.25)',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
        >
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: '#fbbf24',
              animation: 'pulse 1.2s ease-in-out infinite',
            }}
          />
          <span>
            Switching to <strong>{switchingTo}</strong>… messages you send will queue and fire automatically when synchronization completes.
          </span>
        </div>
      )}
      <div className="input-bar-inner">
        <ModelBadge stats={contextStats} bridgeReady={bridgeReady} />
        <div className="input-field-wrap">
          <textarea
            ref={textareaRef}
            className="input-field"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={switchingTo
              ? `Queue a message for ${switchingTo}… (will send when sync completes)`
              : 'Ask EYE about forensic artifacts... (Shift+Enter for new line)'}
            disabled={disabled}
            rows={1}
            aria-label="Message input"
          />
        </div>
        <button
          className={`send-button ${canSend ? 'send-button--ready' : ''}`}
          onClick={handleSend}
          disabled={!canSend}
          aria-label={switchingTo ? 'Queue message' : 'Send message'}
          title={switchingTo ? 'Queue (will send after sync)' : 'Send (Enter)'}
        >
          <IconSend size={18} />
        </button>
      </div>
      <div className="input-bar-hint">
        Press <kbd>Enter</kbd> to send · <kbd>Shift+Enter</kbd> for new line
      </div>
    </div>
  );
};

export default InputBar;
