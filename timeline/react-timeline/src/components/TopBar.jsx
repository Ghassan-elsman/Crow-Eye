/**
 * TopBar — Search, zoom controls, view-mode toggle, event count.
 */
import { memo, useState, useEffect } from 'react';

function TopBar({ state, loading, stats }) {
  const {
    zoomIn, zoomOut, zoomLabel,
    viewMode, setViewModeOverride,
    searchTerm, setSearchTerm,
    timeRange,
  } = state;

  const [localSearch, setLocalSearch] = useState(searchTerm);

  useEffect(() => {
    const timer = setTimeout(() => {
      setSearchTerm(localSearch);
    }, 400);
    return () => clearTimeout(timer);
  }, [localSearch, setSearchTerm]);

  // Safe date formatting — never crash on null/invalid
  let rangeLabel = 'No data loaded';
  try {
    if (timeRange.start && timeRange.end) {
      const s = new Date(timeRange.start);
      const e = new Date(timeRange.end);
      if (!isNaN(s.getTime()) && !isNaN(e.getTime())) {
        rangeLabel = `${s.toLocaleDateString('en-GB', {timeZone: 'UTC', day:'numeric', month:'short', year:'numeric'})} — ${e.toLocaleDateString('en-GB', {timeZone: 'UTC', day:'numeric', month:'short', year:'numeric'})}`;
      }
    }
  } catch (err) {
    rangeLabel = 'Invalid range';
  }

  return (
    <div className="topbar">
      <div className="topbar__title">CROW-EYE TIMELINE</div>

      {viewMode === '24h' && (
        <div className="topbar__search-wrapper">
          <span className="topbar__search-icon">🔍</span>
          <input
            className="topbar__search"
            type="text"
            placeholder="Search events, files, apps…"
            value={localSearch}
            onChange={(e) => setLocalSearch(e.target.value)}
          />
        </div>
      )}

      <div className="topbar__zoom">
        <button className="topbar__zoom-btn" onClick={zoomOut} title="Zoom Out">−</button>
        <span className="topbar__zoom-label">{zoomLabel}</span>
        <button className="topbar__zoom-btn" onClick={zoomIn} title="Zoom In">+</button>
      </div>

      <div className="topbar__view-toggle">
        {['24h', 'week', 'heatmap'].map(mode => (
          <button
            key={mode}
            className={`topbar__view-btn ${viewMode === mode ? 'topbar__view-btn--active' : ''}`}
            onClick={() => {
              if (mode === 'week' && timeRange.start) {
                const s = new Date(timeRange.start);
                s.setUTCHours(0,0,0,0);
                const e = new Date(s);
                e.setUTCDate(s.getUTCDate() + 6);
                e.setUTCHours(23, 59, 59, 999);
                state.setTimeRange({ start: s.toISOString(), end: e.toISOString() });
              }
              setViewModeOverride(mode);
            }}
          >
            {mode === '24h' ? '24H Detail' : mode === 'week' ? 'Week' : 'Heatmap'}
          </button>
        ))}
      </div>

      <div className="topbar__spacer" />

      {/* Reactive Forensic Stats */}
      {stats && stats.loaded && (
        <div className="topbar__stats" style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-end',
          marginRight: 20,
          fontFamily: 'var(--font-mono)',
          lineHeight: 1
        }}>
          <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--accent-blue)' }}>
            {stats.hasSearch ? `${stats.visibleEvents.toLocaleString()} FOUND` : `${stats.totalEvents.toLocaleString()} TOTAL`}
          </div>
          {stats.hasSearch && (
            <div style={{ fontSize: 9, color: 'var(--text-subtle)', marginTop: 2 }}>
              FROM {stats.totalEvents.toLocaleString()} LOADED
            </div>
          )}
        </div>
      )}

      {/* Explicit Day/Week Navigation */}
      {(viewMode === '24h' || viewMode === 'week') && timeRange.start && (
        <div className="topbar__day-nav" style={{ 
          display: 'flex', 
          alignItems: 'center', 
          gap: 8,
          marginRight: 20,
          background: 'rgba(255, 255, 255, 0.05)',
          padding: '2px 8px',
          borderRadius: 6,
          border: '1px solid var(--border-subtle)'
        }}>
          <button 
            className="topbar__zoom-btn" 
            style={{ width: 28, height: 28, fontSize: 16 }}
            onClick={() => {
              const s = new Date(timeRange.start);
              if (viewMode === '24h') {
                s.setUTCDate(s.getUTCDate() - 1);
              } else {
                s.setUTCDate(s.getUTCDate() - 7);
              }
              s.setUTCHours(0, 0, 0, 0);

              const e = new Date(s);
              if (viewMode === '24h') {
                e.setUTCHours(23, 59, 59, 999);
              } else {
                e.setUTCDate(s.getUTCDate() + 6);
                e.setUTCHours(23, 59, 59, 999);
              }
              
              state.setTimeRange({ start: s.toISOString(), end: e.toISOString() });
            }}
            title={viewMode === '24h' ? "Previous Day" : "Previous Week"}
          >
            ←
          </button>
          
          <div className="topbar__info" style={{ margin: 0, minWidth: viewMode === 'week' ? 220 : 180, textAlign: 'center' }}>
            {rangeLabel}
          </div>

          <button 
            className="topbar__zoom-btn" 
            style={{ width: 28, height: 28, fontSize: 16 }}
            onClick={() => {
              const s = new Date(timeRange.start);
              if (viewMode === '24h') {
                s.setUTCDate(s.getUTCDate() + 1);
              } else {
                s.setUTCDate(s.getUTCDate() + 7);
              }
              s.setUTCHours(0, 0, 0, 0);

              const e = new Date(s);
              if (viewMode === '24h') {
                e.setUTCHours(23, 59, 59, 999);
              } else {
                e.setUTCDate(s.getUTCDate() + 6);
                e.setUTCHours(23, 59, 59, 999);
              }

              state.setTimeRange({ start: s.toISOString(), end: e.toISOString() });
            }}
            title={viewMode === '24h' ? "Next Day" : "Next Week"}
          >
            →
          </button>
        </div>
      )}

      {loading && <div className="loading__spinner" style={{ width: 18, height: 18, borderWidth: 2 }} />}

      {/* Task 5.7.1: Add "All times in UTC" label for forensic clarity */}
      <div className="topbar__info" style={{ 
        fontSize: 11, 
        color: 'var(--accent-cyan)', 
        fontWeight: 600,
        padding: '4px 10px',
        background: 'rgba(0, 255, 255, 0.1)',
        borderRadius: 4,
        border: '1px solid rgba(0, 255, 255, 0.3)',
        marginRight: 15
      }}>
        🌐 UTC
      </div>

      {(viewMode !== '24h' && viewMode !== 'week') && <div className="topbar__info">{rangeLabel}</div>}
    </div>
  );
}

export default memo(TopBar);
