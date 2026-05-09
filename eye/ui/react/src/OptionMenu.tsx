import React, { useState } from 'react';
import type { OptionMenuItem } from './types';
import { IconChevronRight, IconCheck } from './Icons';
import './OptionMenu.css';

interface OptionMenuProps {
  items: OptionMenuItem[];
  onSelect: (query: string, label: string) => void;
}

const OptionMenu: React.FC<OptionMenuProps> = ({ items, onSelect }) => {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const handleSelect = (item: OptionMenuItem) => {
    if (selectedId) return; // already selected
    setSelectedId(item.id);
    setTimeout(() => onSelect(item.query, item.label), 300);
  };

  if (selectedId) {
    const chosen = items.find(i => i.id === selectedId);
    return (
      <div className="option-menu option-menu--resolved">
        <span className="option-resolved-icon"><IconCheck size={13} color="var(--color-success)" /></span>
        <span className="option-resolved-label">{chosen?.label}</span>
      </div>
    );
  }

  return (
    <div className="option-menu" role="group" aria-label="Choose an option">
      <div className="option-menu-title">Select an option to continue</div>
      <div className="option-menu-list">
        {items.map((item, index) => (
          <button
            key={item.id}
            className="option-menu-item"
            onClick={() => handleSelect(item)}
            aria-label={item.label}
          >
            <span className="option-index">{index + 1}</span>
            <div className="option-content">
              <span className="option-label">{item.label}</span>
              {item.description && (
                <span className="option-description">{item.description}</span>
              )}
            </div>
            <span className="option-arrow"><IconChevronRight size={14} /></span>
          </button>
        ))}
      </div>
    </div>
  );
};

export default OptionMenu;
