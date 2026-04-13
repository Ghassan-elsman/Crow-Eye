import { memo, useMemo, useState } from 'react';
import { formatTime, formatDuration, formatBytes } from '../utils/formatters';

function LaneDataModal({ laneKey, laneTitle, data, onClose, callBridge, onShowInTimeline }) {
  const [searchTerm, setSearchTerm] = useState('');
  const [contextMenu, setContextMenu] = useState(null);

  const items = useMemo(() => {
    let allItems = [];
    if (!data) return allItems;

    if (laneKey === 'sessions') {
      allItems = [...(data.sessions?.events || []), ...(data.sessions?.bands || [])];
    } else if (laneKey === 'srum_app') {
      allItems = data.srum_app || [];
    } else if (laneKey === 'srum_net') {
      allItems = [...(data.srum_net?.connectivity || []), ...(data.srum_net?.data_usage || [])];
    } else if (laneKey === 'mft_usn') {
      allItems = data.mft_usn || [];
    } else if (laneKey === 'execution') {
      allItems = [
        ...(data.prefetch || []),
        ...(data.bam || []),
        ...(data.lnk || []),
        ...(data.registry?.open_save_mru || []),
        ...(data.registry?.last_save_mru || []),
        ...(data.registry?.shellbags || []),
        ...(data.registry?.recent_docs || []),
        ...(data.registry?.user_assist || [])
      ];
    } else if (laneKey === 'cache') {
      allItems = [
        ...(data.shimcache || []),
        ...(data.recyclebin || []),
        ...(data.amcache?.application_files || []),
        ...(data.amcache?.applications || []),
        ...(data.amcache?.drivers || [])
      ];
    }

    if (searchTerm) {
      const lower = searchTerm.toLowerCase();
      allItems = allItems.filter(item => {
        const str = JSON.stringify(item).toLowerCase();
        return str.includes(lower);
      });
    }
    
    // Sort by timestamp if available
    allItems.sort((a, b) => {
      const ta = new Date(a.timestamp || a.start || a.EventTimestampUTC || a.link_date || a.last_executed).getTime() || 0;
      const tb = new Date(b.timestamp || b.start || b.EventTimestampUTC || b.link_date || b.last_executed).getTime() || 0;
      return ta - tb;
    });

    return allItems;
  }, [laneKey, data, searchTerm]);

  return (
    <div className="modal-overlay" onClick={() => { if(contextMenu) setContextMenu(null); else onClose(); }} style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.7)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div className="modal" onClick={e => { e.stopPropagation(); if(contextMenu) setContextMenu(null); }} style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 8, width: '90%', maxWidth: 1200, height: '80%', display: 'flex', flexDirection: 'column' }}>
        
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
            onChange={e => setSearchTerm(e.target.value)}
            style={{ width: '100%', padding: '8px 12px', background: 'var(--bg-secondary)', border: '1px solid var(--border-subtle)', borderRadius: 4, color: 'var(--text-primary)' }}
          />
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: 20 }}>
          {items.length === 0 ? (
            <div style={{ textAlign: 'center', color: 'var(--text-muted)', marginTop: 40 }}>No data found in this lane for the current view.</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--border-default)', textAlign: 'left', color: 'var(--text-secondary)' }}>
                  <th style={{ padding: '8px 4px' }}>Time (UTC)</th>
                  <th style={{ padding: '8px 4px' }}>Path/Name</th>
                  <th style={{ padding: '8px 4px' }}>Details</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item, idx) => {
                  const t = item.timestamp || item.start || item.EventTimestampUTC || item.link_date || item.last_executed || item.creation_time || item.deletion_time;
                  const name = item.app_name || item.filename || item.name || item.executable_name || item.app_path || 'N/A';
                  const details = item.description || item.reason || item.Event_Description || '';
                  
                  return (
                    <tr 
                      key={idx} 
                      style={{ borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer' }}
                      onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                      onClick={() => callBridge('openEventDetailDialog', JSON.stringify(item))}
                      onContextMenu={(e) => {
                        e.preventDefault();
                        setContextMenu({ x: e.clientX, y: e.clientY, item });
                      }}
                    >
                      <td style={{ padding: '8px 4px', whiteSpace: 'nowrap' }}>{t ? formatTime(t) : 'N/A'}</td>
                      <td style={{ padding: '8px 4px', maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={name}>{name}</td>
                      <td style={{ padding: '8px 4px', color: 'var(--text-muted)', maxWidth: 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={details}>{details}</td>
                    </tr>
                  );
                })}
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
