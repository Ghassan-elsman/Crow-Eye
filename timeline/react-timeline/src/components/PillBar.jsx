/**
 * PillBar — Artifact type toggle filter pills.
 */
import { memo, useMemo } from 'react';
import { ARTIFACT_CONFIG, formatCount, getForensicTimestamps, getArtifactSources } from '../utils/formatters';
import { heuristicFlatten } from '../utils/dataUtils';

function PillBar({ state, data }) {
  const { activeArtifacts, toggleArtifact } = state;

  // Compute event counts per artifact type
  const counts = useMemo(() => {
    const c = {
      sessions: 0, srum_app: 0, srum_net: 0, mft_usn: 0,
      prefetch: 0, lnk: 0, bam: 0, registry: 0, amcache: 0,
      shimcache: 0, recyclebin: 0
    };

    const countDots = (arr) => {
      let dots = 0;
      heuristicFlatten(arr).forEach(item => {
        dots += getForensicTimestamps(item).length;
      });
      return dots;
    };

    // 1. Specialized Lane Counts
    c.sessions = countDots(data.sessions?.events) + heuristicFlatten(data.sessions?.bands).length;
    c.srum_app = countDots(data.srum_app);
    c.srum_net = countDots(data.srum_net?.connectivity) + countDots(data.srum_net?.data_usage);
    c.mft_usn = countDots(data.mft_usn);

    // 2. Artifact Lane - Global Discovery Summation
    const sources = getArtifactSources(data);
    sources.forEach(src => {
      const dots = countDots(src.items);
      // Map back to high-level categories for PillBar display
      if (src.type === 'prefetch') c.prefetch += dots;
      else if (src.type === 'lnk') c.lnk += dots;
      else if (src.type === 'bam' || src.type === 'dam') c.bam += dots;
      else if (src.type === 'amcache') c.amcache += dots;
      else if (src.type === 'shimcache') c.shimcache += dots;
      else if (src.type === 'recyclebin') c.recyclebin += dots;
      else {
        // Anything else in registry is counted towards 'Registry'
        c.registry += dots;
      }
    });

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
