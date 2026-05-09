import React, { useState } from 'react';
import type { ContextStats } from './types';
import { IconCpu } from './Icons';
import './ModelBadge.css';

interface ModelBadgeProps {
  stats: ContextStats | null;
  bridgeReady: boolean;
}

const ModelBadge: React.FC<ModelBadgeProps> = ({ stats, bridgeReady }) => {
  const [showTooltip, setShowTooltip] = useState(false);

  const backend  = stats?.backend?.toUpperCase() ?? '—';
  const model    = stats?.model_name ?? 'Not connected';

  // Guard against undefined numeric fields
  const tokens    = stats?.total_tokens    ?? 0;
  const maxTokens = stats?.max_total_tokens ?? 1;
  const usedPct   = maxTokens > 0 ? Math.round((tokens / maxTokens) * 100) : 0;

  const statusClass = !bridgeReady
    ? 'model-badge--offline'
    : usedPct > 80
    ? 'model-badge--warn'
    : 'model-badge--online';

  return (
    <div
      className={`model-badge ${statusClass}`}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
      aria-label={`Model: ${model}`}
    >
      <IconCpu size={12} />
      <span className="model-badge-text">
        {bridgeReady ? `${backend} · ${model}` : 'Offline'}
      </span>

      {showTooltip && bridgeReady && stats && (
        <div className="model-badge-tooltip" role="tooltip">
          <div className="tooltip-row">
            <span className="tooltip-key">Backend</span>
            <span className="tooltip-val">{stats.backend ?? '—'}</span>
          </div>
          <div className="tooltip-row">
            <span className="tooltip-key">Model</span>
            <span className="tooltip-val">{stats.model_name ?? '—'}</span>
          </div>
          <div className="tooltip-row">
            <span className="tooltip-key">Tokens</span>
            <span className="tooltip-val">
              {(tokens).toLocaleString()} / {(maxTokens).toLocaleString()}
            </span>
          </div>
          <div className="tooltip-row">
            <span className="tooltip-key">Messages</span>
            <span className="tooltip-val">{stats.total_messages ?? 0}</span>
          </div>
          {(stats.truncation_count ?? 0) > 0 && (
            <div className="tooltip-row tooltip-row--warn">
              <span className="tooltip-key">Truncations</span>
              <span className="tooltip-val">{stats.truncation_count}</span>
            </div>
          )}
          <div className="tooltip-usage-bar">
            <div
              className="tooltip-usage-fill"
              style={{ width: `${Math.min(usedPct, 100)}%` }}
            />
          </div>
          <div className="tooltip-usage-label">{usedPct}% context used</div>
        </div>
      )}
    </div>
  );
};

export default ModelBadge;
