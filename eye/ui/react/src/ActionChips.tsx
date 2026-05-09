import React from 'react';
import type { ActionChip } from './types';
import { IconZap } from './Icons';
import './ActionChips.css';

interface ActionChipsProps {
  chips: ActionChip[];
  onChipClick: (query: string) => void;
}

const ActionChips: React.FC<ActionChipsProps> = ({ chips, onChipClick }) => {
  if (!chips || chips.length === 0) return null;

  return (
    <div className="action-chips">
      <div className="action-chips-header">
        <IconZap size={11} color="var(--color-accent)" />
        <span className="action-chips-label">Suggested actions</span>
      </div>
      <div className="action-chips-list">
        {chips.map((chip) => (
          <button
            key={chip.id}
            className="action-chip"
            onClick={() => onChipClick(chip.query)}
            title={chip.query}
            aria-label={chip.label}
          >
            <span className="chip-label">{chip.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
};

export default ActionChips;
