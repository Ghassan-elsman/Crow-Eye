/**
 * PillBar — Artifact type toggle filter pills.
 */
import { memo, useMemo } from 'react';
import { ARTIFACT_CONFIG, formatCount } from '../utils/formatters';

function PillBar({ state, data }) {
  const { activeArtifacts, toggleArtifact } = state;

  // Compute event counts per artifact type
  const counts = useMemo(() => {
    const c = {};
    c.sessions = data.sessions?.events?.length || 0;
    c.srum_app = Array.isArray(data.srum_app) ? data.srum_app.length : 0;
    c.srum_net =
      (data.srum_net?.connectivity?.length || 0) +
      (data.srum_net?.data_usage?.length || 0);
    c.mft_usn = Array.isArray(data.mft_usn) ? data.mft_usn.length : 0;
    c.prefetch = Array.isArray(data.prefetch) ? data.prefetch.length : 0;
    c.lnk = Array.isArray(data.lnk) ? data.lnk.length : 0;
    c.bam = Array.isArray(data.bam) ? data.bam.length : 0;
    c.registry =
      (data.registry?.open_save_mru?.length || 0) +
      (data.registry?.last_save_mru?.length || 0) +
      (data.registry?.shellbags?.length || 0);
    c.amcache =
      (data.amcache?.application_files?.length || 0) +
      (data.amcache?.applications?.length || 0) +
      (data.amcache?.drivers?.length || 0);
    c.shimcache = Array.isArray(data.shimcache) ? data.shimcache.length : 0;
    c.recyclebin = Array.isArray(data.recyclebin) ? data.recyclebin.length : 0;
    return c;
  }, [data]);

  return (
    <div className="pillbar">
      {Object.entries(ARTIFACT_CONFIG).map(([key, cfg]) => (
        <button
          key={key}
          className={`pill ${activeArtifacts[key] ? 'pill--active' : ''}`}
          style={{ '--pill-color': cfg.color }}
          onClick={() => toggleArtifact(key)}
        >
          <span className="pill__dot" />
          <span>{cfg.icon} {cfg.label}</span>
          {counts[key] > 0 && (
            <span className="pill__count">{formatCount(counts[key])}</span>
          )}
        </button>
      ))}

      {/* SRUM Legend inline */}
      <div className="srum-legend" style={{ marginLeft: 'auto' }}>
        <div className="srum-legend__item">
          <div className="srum-legend__swatch" style={{ background: 'var(--srum-fg)' }} />
          <span>Foreground</span>
        </div>
        <div className="srum-legend__item">
          <div className="srum-legend__swatch" style={{ background: 'var(--srum-bg)' }} />
          <span>Background</span>
        </div>
        <div className="srum-legend__item">
          <div className="srum-legend__swatch" style={{ background: 'var(--srum-face)' }} />
          <span>Face Time</span>
        </div>
      </div>
    </div>
  );
}

export default memo(PillBar);
