import React, { useEffect, useRef, useState } from 'react';
import type { ActionChip } from './types';
import { IconZap, IconLoader } from './Icons';
import './ActionChips.css';

interface ActionChipsProps {
  chips: ActionChip[];
  onChipClick: (query: string) => void;
  /** Double-click: run the action immediately (no compose step). */
  onChipExecute?: (query: string) => void;
  /** True while a query is running — chips disable and the executed one spins. */
  disabled?: boolean;
}

const ActionChips: React.FC<ActionChipsProps> = ({ chips, onChipClick, onChipExecute, disabled }) => {
  // Chip whose action is currently running (shows the spinner).
  const [runningId, setRunningId] = useState<string | null>(null);
  // Pending single-click insert; cancelled when the second click of a
  // double-click arrives, so double-click executes instantly with no
  // insert-then-clear flash in the input bar.
  const clickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // When the query finishes (disabled flips back off), clear the spinner.
  useEffect(() => {
    if (!disabled) setRunningId(null);
  }, [disabled]);
  useEffect(() => () => {
    if (clickTimerRef.current) clearTimeout(clickTimerRef.current);
  }, []);

  if (!chips || chips.length === 0) return null;

  const handleClick = (chip: ActionChip) => {
    if (disabled) return;
    if (clickTimerRef.current) clearTimeout(clickTimerRef.current);
    clickTimerRef.current = setTimeout(() => {
      clickTimerRef.current = null;
      onChipClick(chip.query);
    }, 230);
  };

  const handleDoubleClick = (chip: ActionChip) => {
    if (disabled || !onChipExecute) return;
    if (clickTimerRef.current) {           // cancel the pending insert
      clearTimeout(clickTimerRef.current);
      clickTimerRef.current = null;
    }
    setRunningId(chip.id);                 // immediate visual feedback
    onChipExecute(chip.query);
  };

  return (
    <div className="action-chips">
      <div className="action-chips-header">
        <IconZap size={11} color="var(--color-accent)" />
        <span className="action-chips-label">Suggested actions</span>
      </div>
      <div className="action-chips-list">
        {chips.map((chip) => {
          const running = runningId === chip.id && disabled;
          return (
            <button
              key={chip.id}
              className={`action-chip${running ? ' action-chip--running' : ''}`}
              onClick={() => handleClick(chip)}
              onDoubleClick={() => handleDoubleClick(chip)}
              disabled={!!disabled}
              title={`${chip.query}\n\nClick to insert · Double-click to run`}
              aria-label={running ? `${chip.label} (running)` : chip.label}
            >
              {running && <IconLoader size={11} className="chip-spinner" />}
              <span className="chip-label">{running ? 'Running…' : chip.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
};

export default ActionChips;
