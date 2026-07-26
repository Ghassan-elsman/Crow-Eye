import React, { useEffect, useState } from 'react';
import type { ActionChip } from './types';
import { IconZap, IconLoader } from './Icons';
import './ActionChips.css';

interface ActionChipsProps {
  chips: ActionChip[];
  /** Insert the query into the input for editing (the small pencil affordance). */
  onChipClick: (query: string) => void;
  /** Run the action immediately (single click on the chip body). */
  onChipExecute?: (query: string) => void;
  /** True while a query is running — chips disable and the launched one spins. */
  disabled?: boolean;
}

// Small inline pencil (no matching glyph in the icon set); "insert to edit".
const PencilIcon: React.FC<{ size?: number }> = ({ size = 11 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 20h9" />
    <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
  </svg>
);

const ActionChips: React.FC<ActionChipsProps> = ({ chips, onChipClick, onChipExecute, disabled }) => {
  // Chip whose action was launched (shows the spinner until the query finishes).
  const [runningId, setRunningId] = useState<string | null>(null);

  // When the query finishes (disabled flips back off), clear the spinner.
  useEffect(() => {
    if (!disabled) setRunningId(null);
  }, [disabled]);

  if (!chips || chips.length === 0) return null;

  const run = (chip: ActionChip) => {
    if (disabled || !onChipExecute) return;
    setRunningId(chip.id);           // instant visual feedback on the click itself
    onChipExecute(chip.query);
  };

  const edit = (e: React.MouseEvent, chip: ActionChip) => {
    e.stopPropagation();             // don't also run
    if (disabled) return;
    onChipClick(chip.query);
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
            <span key={chip.id} className={`action-chip-wrap${running ? ' action-chip-wrap--running' : ''}`}>
              <button
                className="action-chip"
                onClick={() => run(chip)}
                disabled={!!disabled}
                title={`Run: ${chip.query}`}
                aria-label={running ? `${chip.label} (running)` : `Run ${chip.label}`}
              >
                {running && <IconLoader size={11} className="chip-spinner" />}
                <span className="chip-label">{running ? 'Running…' : chip.label}</span>
              </button>
              <button
                className="action-chip-edit"
                onClick={(e) => edit(e, chip)}
                disabled={!!disabled}
                title="Insert into the message box to edit before sending"
                aria-label={`Edit ${chip.label} before sending`}
              >
                <PencilIcon size={11} />
              </button>
            </span>
          );
        })}
      </div>
    </div>
  );
};

export default ActionChips;
