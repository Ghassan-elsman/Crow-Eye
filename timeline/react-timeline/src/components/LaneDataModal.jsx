import { memo, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';
import { formatTime, getPrimaryTimestamp, getForensicName, getForensicTimestamps, aiStepSubject } from '../utils/formatters';
import { heuristicFlatten } from '../utils/dataUtils';
import { windowRange, ROW_H } from '../utils/windowing';

function LaneDataModal({ laneKey, laneTitle, data, timeRange, initialSearch, onClose, callBridge, onShowInTimeline }) {
  const [searchTerm, setSearchTerm] = useState(initialSearch || '');
  const [contextMenu, setContextMenu] = useState(null);
  const [view, setView] = useState({ top: 0, h: 600 });
  const scroller = useRef(null);
  const frame = useRef(0);
  // The search filters a list built once per lane and range: every keystroke
  // re-expanded and re-sorted the whole lane before.
  const search = useDeferredValue(searchTerm);

  const laneItems = useMemo(() => {
    let allItems = [];
    if (!data || !timeRange) return allItems;

    const sTime = new Date(timeRange.start).getTime();
    const eTime = new Date(timeRange.end).getTime();

    const inBounds = (ts) => {
      if (!ts) return false;
      const cleanTs = (typeof ts === 'string' && !ts.includes('Z') && !ts.includes('+')) 
        ? ts.replace(' ', 'T') + 'Z' 
        : ts;
      const t = new Date(cleanTs).getTime();
      return t >= sTime && t <= eTime;
    };

    const expandArtifacts = (rawItems, typeLabel) => {
      const expanded = [];
      heuristicFlatten(rawItems).forEach(item => {
        const times = getForensicTimestamps(item);
        times.forEach(tsInfo => {
          if (inBounds(tsInfo.time)) {
            expanded.push({
              ...item,
              _display_time: tsInfo.time,
              _artifact_type: typeLabel,
              _ts_field: tsInfo.field
            });
          }
        });
      });
      return expanded;
    };

    if (laneKey === 'sessions') {
      allItems = [
        ...heuristicFlatten(data.sessions?.events).map(x => ({ ...x, _display_time: x.timestamp, _artifact_type: 'Session Event' })),
        ...heuristicFlatten(data.sessions?.bands).map(x => ({ ...x, _display_time: x.start, _artifact_type: 'Power/Logon State' }))
      ];
    } else if (laneKey === 'srum_app') {
      allItems = expandArtifacts(data.srum_app, 'SRUM App');
    } else if (laneKey === 'srum_net') {
      allItems = [
        ...expandArtifacts(data.srum_net?.connectivity, 'SRUM Network'),
        ...expandArtifacts(data.srum_net?.data_usage, 'SRUM Data Usage')
      ];
    } else if (laneKey === 'mft_usn') {
      allItems = expandArtifacts(data.mft_usn, 'MFT/USN');
    } else if (laneKey === 'browser') {
      // The browser lane's own rows, typed by the table each came from. The
      // modal had no branch for it, so it always said "No data found", and
      // listed them under Unified Artifacts, whose lane stopped drawing them
      // when Browser Activity became a lane of its own.
      allItems = expandArtifacts(data.browser, 'Browser').map(x => ({
        ...x, _artifact_type: x.bsource || 'Browser',
      }));
    } else if (laneKey === 'ai_agents') {
      // Named by the bridge's label, described by what was run, written or
      // asked, and tagged with what kind of step it was.
      allItems = expandArtifacts(data.ai_agents, 'AI Agent').map(x => ({
        ...x, _artifact_type: x.ai_what || 'AI Agent', description: aiStepSubject(x),
      }));
    } else if (laneKey === 'artifacts') {
      // Unified Data Discovery matching TimelineView
      const registry = data.registry || {};
      const artifactSources = [
        { items: data.prefetch || data.prefetch_data, label: 'Prefetch' },
        { items: data.lnk, label: 'LNK/JumpList' },
        { items: data.bam, label: 'BAM' },
        { items: data.dam, label: 'DAM' },
        { items: data.shimcache, label: 'ShimCache' },
        { items: data.recyclebin, label: 'RecycleBin' },
        { items: (data.amcache || data.amcache_applications)?.application_files, label: 'AmCache File' },
        { items: (data.amcache || data.amcache_applications)?.applications, label: 'AmCache App' },
        { items: (data.amcache || data.amcache_applications)?.drivers, label: 'AmCache Driver' },
        // Registry level sources
        ...Object.keys(registry).map(table => {
          const typeLabel = table.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
          return { items: registry[table], label: (table === 'usb_devices') ? 'USB Connection' : `Reg: ${typeLabel}` };
        })
      ];

      const processedSignatures = new Set();

      artifactSources.forEach(src => {
        if (!src.items) return;
        heuristicFlatten(src.items).forEach(p => {
          const times = getForensicTimestamps(p);
          times.forEach(tsInfo => {
            if (inBounds(tsInfo.time)) {
              const sig = `${src.label}-${tsInfo.time}-${tsInfo.field}-${getForensicName(p)}`.toLowerCase();
              if (processedSignatures.has(sig)) return;
              processedSignatures.add(sig);

              allItems.push({
                ...p,
                _display_time: tsInfo.time,
                _artifact_type: src.label,
                _ts_field: tsInfo.field
              });
            }
          });
        });
      });

      // 3. Salvaged Items
      Object.keys(data).forEach(key => {
        if (!['sessions', 'srum_app', 'srum_net', 'mft_usn', 'prefetch', 'bam', 'dam', 'lnk', 'shimcache', 'recyclebin', 'amcache', 'registry', 'browser', 'ai_agents', 'ai_links', 'aggregated'].includes(key)) {
          const salvaged = expandArtifacts(data[key], `Salvaged: ${key}`);
          if (salvaged.length > 0) allItems = [...allItems, ...salvaged];
        }
      });
    }

    // Sort by timestamp, each parsed once rather than twice per comparison.
    return allItems
      .map(item => [new Date(item._display_time).getTime() || 0, item])
      .sort((a, b) => a[0] - b[0])
      .map(pair => pair[1]);
  }, [laneKey, data, timeRange]);

  const items = useMemo(() => {
    if (!search) return laneItems;
    const lower = search.toLowerCase();
    return laneItems.filter(item => {
      const name = String(getForensicName(item) ?? '').toLowerCase();
      const details = String(item.description || item.reason || '').toLowerCase();
      return name.includes(lower) || details.includes(lower) || String(item._artifact_type || '').toLowerCase().includes(lower);
    });
  }, [laneItems, search]);

  // Only the rows on screen are drawn (a busy lane has tens of thousands).
  const empty = items.length === 0;
  useEffect(() => {
    const el = scroller.current;
    if (!el) return undefined;
    const measure = () => setView({ top: el.scrollTop, h: el.clientHeight });
    measure();
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
    if (ro) ro.observe(el);
    return () => { if (ro) ro.disconnect(); cancelAnimationFrame(frame.current); };
  }, [empty]);
  const onScroll = (e) => {
    const el = e.currentTarget;
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => setView({ top: el.scrollTop, h: el.clientHeight }));
  };
  // The table body starts below the 20 px padding and the header row.
  const win = windowRange(view.top - 20 - ROW_H, view.h, items.length);

  return (
    <div className="modal-overlay" onClick={() => { if (contextMenu) setContextMenu(null); else onClose(); }} style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.7)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div className="modal" onClick={e => { e.stopPropagation(); if (contextMenu) setContextMenu(null); }} style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 8, width: '90%', maxWidth: 1200, height: '80%', display: 'flex', flexDirection: 'column' }}>

        <div className="modal__header" style={{ padding: '16px 20px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 'bold', color: 'var(--text-primary)' }}>Lane Data: {laneTitle}</div>
            <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4 }}>Total Artifacts: {items.length.toLocaleString()}</div>
          </div>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: 24, cursor: 'pointer' }}>×</button>
        </div>

        <div style={{ padding: '12px 20px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-primary)' }}>
          <input
            type="text"
            placeholder="Search artifacts in this lane..."
            value={searchTerm}
            onChange={e => {
              setSearchTerm(e.target.value);
              if (scroller.current) scroller.current.scrollTop = 0;   // a new search starts at the top
            }}
            style={{ width: '100%', padding: '8px 12px', background: 'var(--bg-secondary)', border: '1px solid var(--border-subtle)', borderRadius: 4, color: 'var(--text-primary)' }}
          />
        </div>

        <div ref={scroller} onScroll={onScroll} style={{ flex: 1, overflow: 'auto', padding: 20 }}>
          {items.length === 0 ? (
            <div style={{ textAlign: 'center', color: 'var(--text-muted)', marginTop: 40 }}>No data found in this lane for the current view.</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, lineHeight: '16px', tableLayout: 'fixed' }}>
              <colgroup>
                <col style={{ width: 190 }} />
                <col style={{ width: '38%' }} />
                <col />
              </colgroup>
              <thead>
                <tr style={{ height: ROW_H, borderBottom: '2px solid var(--border-default)', textAlign: 'left', color: 'var(--text-secondary)' }}>
                  <th style={{ padding: '8px 4px' }}>Time (UTC)</th>
                  <th style={{ padding: '8px 4px' }}>Path/Name</th>
                  <th style={{ padding: '8px 4px' }}>Details</th>
                </tr>
              </thead>
              <tbody>
                {win.top > 0 && <tr aria-hidden="true" style={{ height: win.top }}><td colSpan={3} /></tr>}
                {items.slice(win.start, win.end).map((item, i) => {
                  const idx = win.start + i;
                  const t = item._display_time || getPrimaryTimestamp(item);
                  const name = item.ai_label || getForensicName(item);
                  const rawDetails = item.description || item.reason || item.Event_Description || item.EventType || '';
                  const details = rawDetails;

                  return (
                    <tr
                      key={idx}
                      style={{ height: ROW_H, borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer' }}
                      onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                      onClick={() => callBridge('openEventDetailDialog', JSON.stringify(item))}
                      onContextMenu={(e) => {
                        e.preventDefault();
                        setContextMenu({ x: e.clientX, y: e.clientY, item });
                      }}
                    >
                      <td style={{ padding: '8px 4px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{t ? formatTime(t) : 'N/A'}</td>
                      <td style={{ padding: '8px 4px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={name}>{name}</td>
                      <td style={{ padding: '8px 4px', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={details}>
                        {item._artifact_type && <span style={{ color: 'var(--accent-orange)', fontWeight: 600, marginRight: 6 }}>[{item._artifact_type}]</span>}
                        {rawDetails}
                      </td>
                    </tr>
                  );
                })}
                {win.bottom > 0 && <tr aria-hidden="true" style={{ height: win.bottom }}><td colSpan={3} /></tr>}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {contextMenu && (
        <div
          style={{ position: 'fixed', top: contextMenu.y, left: contextMenu.x, background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 4, zIndex: 10000, boxShadow: '0 4px 12px rgba(0,0,0,0.5)', padding: 4, minWidth: 150 }}
          onClick={(e) => e.stopPropagation()}
        >
          <div
            style={{ padding: '8px 12px', cursor: 'pointer', fontSize: 13, color: 'var(--text-primary)' }}
            onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            onClick={() => {
              if (onShowInTimeline) onShowInTimeline(contextMenu.item);
              setContextMenu(null);
            }}
          >
            Show in Timeline
          </div>
          <div
            style={{ padding: '8px 12px', cursor: 'pointer', fontSize: 13, color: 'var(--text-primary)' }}
            onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            onClick={() => {
              callBridge('openEventDetailDialog', JSON.stringify(contextMenu.item));
              setContextMenu(null);
            }}
          >
            Show Raw Data
          </div>
        </div>
      )}
    </div>
  );
}

export default memo(LaneDataModal);
