/**
 * WeekView — Aggregated daily columns for exactly 7 days.
 */
import { memo, useMemo } from 'react';

function WeekView({ data, state }) {
  const { timeRange, setTimeRange, setViewModeOverride } = state;

  // Task 5.5.1: All date bucketing uses UTC methods for forensic accuracy
  const days = useMemo(() => {
    if (!timeRange.start) return [];
    const start = new Date(timeRange.start);
    // Task 5.5.1: setUTCHours ensures UTC-based day boundaries
    start.setUTCHours(0, 0, 0, 0);

    const dayArray = [];
    let curr = new Date(start);

    // We expect a 7 day window, generate 7 buckets
    for (let i = 0; i < 7; i++) {
      // Task 5.5.1: toISOString() returns UTC format for day bucketing
      const dStr = curr.toISOString().split('T')[0];
      dayArray.push({
        date: new Date(curr),
        // Task 5.5.1: toLocaleDateString with timeZone: 'UTC' for display
        label: curr.toLocaleDateString('en-US', { timeZone: 'UTC', weekday: 'short', day: 'numeric' }),
        iso: dStr,
        srum: 0,
        mft: 0,
        exec: 0,
        amcache: 0,
        shimcache: 0,
        recyclebin: 0,
        registry: 0,
        sessions: 0,
        _artifactNames: {},  // Track artifact name frequencies
        _hasDetailedData: {} // Track which categories have detailed data loaded
      });
      // Task 5.5.1: setUTCDate and getUTCDate for UTC-based day increment
      curr.setUTCDate(curr.getUTCDate() + 1);
    }

    // Task 5.5.3: Initialize with aggregated statistics if available
    // This provides "stable" bars even while background detailed data is loading
    if (data.aggregated) {
      Object.entries(data.aggregated).forEach(([source, rows]) => {
        if (!Array.isArray(rows)) return;
        rows.forEach(row => {
          const day = dayArray.find(da => da.iso === row.day);
          if (day) {
            const count = row.count || 0;
            if (source.includes('Logs')) day.sessions += count;
            else if (source.startsWith('srum')) day.srum += count;
            else if (source.startsWith('mft')) day.mft += count;
            else if (['prefetch', 'bam', 'lnk'].includes(source)) day.exec += count;
            else if (source === 'amcache') day.amcache += count;
            else if (source === 'shimcache') day.shimcache += count;
            else if (source === 'recyclebin') day.recyclebin += count;
            else if (source === 'registry') day.registry += count;
          }
        });
      });
      
      // Zero out detailed counts if we're using aggregated as the base
      // We will only use count() for topArtifacts and names
      dayArray.forEach(d => {
        d._srumDetail = 0; d._mftDetail = 0; d._execDetail = 0;
        d._amcacheDetail = 0; d._shimcacheDetail = 0; d._recyclebinDetail = 0;
        d._registryDetail = 0; d._sessionsDetail = 0;
      });
    }

    // FIX: Bug 11 - WeekView Timestamp Fallback Chain
    // Implements artifact-type-specific timestamp extraction instead of fragile fallback chain
    // Ensures consistent timestamp selection per artifact type for accurate event counts
    /**
     * Extract timestamp for a specific artifact type.
     * Uses consistent primary timestamp field per artifact type.
     * 
     * Timestamp field mapping per artifact type:
     * - srum: timestamp (SRUM app and network data)
     * - mft: usn_timestamp (primary), si_creation_time (fallback)
     * - exec: last_executed (Prefetch), last_execution (BAM), Time_Access (LNK)
     * - amcache: link_date (application_files), install_date (applications), driver_time_stamp (drivers)
     * - shimcache: last_modified
     * - recyclebin: deletion_time
     * - registry: access_date (primary), accessed_date, modified_date (fallbacks)
     * - sessions: timestamp or start
     * 
     * @param {Object} artifact - The artifact object
     * @param {string} type - The artifact type identifier
     * @returns {string|null} The timestamp value or null if not found
     */
    const getTimestampForArtifact = (artifact, type) => {
      if (!artifact) return null;
      
      // Use switch/case for type-specific extraction
      switch (type) {
        case 'srum':
          // SRUM: timestamp (primary field for SRUM app and network data)
          return artifact.timestamp;
        
        case 'mft':
          // MFT/USN: usn_timestamp (primary), fallback to si_creation_time
          return artifact.usn_timestamp || artifact.si_creation_time;
        
        case 'exec':
          // Execution artifacts: last_executed (Prefetch), last_execution (BAM), Time_Access (LNK)
          return artifact.last_executed || artifact.last_execution || artifact.Time_Access;
        
        case 'amcache':
          // Amcache: link_date (application_files), install_date (applications), driver_time_stamp (drivers)
          return artifact.link_date || artifact.install_date || artifact.driver_time_stamp;
        
        case 'shimcache':
          // Shimcache: last_modified (primary field)
          return artifact.last_modified;
        
        case 'recyclebin':
          // RecycleBin: deletion_time (primary field)
          return artifact.deletion_time;
        
        case 'registry':
          // Registry: access_date (primary), fallback to accessed_date, modified_date
          return artifact.access_date || artifact.accessed_date || artifact.modified_date;
        
        case 'sessions':
          // Sessions: timestamp or start (for session events)
          return artifact.timestamp || artifact.start;
        
        default:
          // Fallback: try common timestamp fields
          return artifact.timestamp || artifact.start;
      }
    };

    // Extract displayable artifact name
    const getArtifactName = (item) => {
      const raw = item.executable_name || item.fn_filename || item.filename || 
                  item.app_name || item.name || item.Source_Name || item.target_path || 
                  item.path || item.file_path || item.original_filename || item.driver_name ||
                  item.process_path || item.file_name || null;
      if (!raw) return null;
      // Extract just the filename from full paths
      return raw.split('\\').pop().split('/').pop();
    };

    // Task 5.5.2: Count function uses UTC-based date bucketing with artifact-type-specific timestamp extraction
    const count = (arr, type) => {
      if (!arr || !Array.isArray(arr)) return;
      arr.forEach(item => {
        const ts = getTimestampForArtifact(item, type);
        if (!ts) return;
        try {
          const tsMs = new Date(ts).getTime();
          if (isNaN(tsMs)) return;
          // Task 5.5.2: toISOString() returns UTC format for day matching
          const d = new Date(ts).toISOString().split('T')[0];
          const day = dayArray.find(da => da.iso === d);
          if (day) {
            // Task 5.5.3: Avoid double-counting if aggregated stats are already present
            if (!data.aggregated) {
              day[type]++;
            }
            // Always track detailed counts for local breakdown if needed
            const detailKey = `_${type}Detail`;
            if (day[detailKey] !== undefined) day[detailKey]++;
            
            // Track artifact name frequency and time range
            const name = getArtifactName(item);
            if (name) {
              if (!day._artifactNames[name]) {
                day._artifactNames[name] = { count: 0, first: tsMs, last: tsMs };
              }
              const entry = day._artifactNames[name];
              entry.count++;
              if (tsMs < entry.first) entry.first = tsMs;
              if (tsMs > entry.last) entry.last = tsMs;
            }
          }
        } catch (e) {
          // Ignore invalid dates
        }
      });
    };

    count(data.srum_app, 'srum');
    count(data.mft_usn, 'mft');
    count(data.prefetch, 'exec');
    count(data.bam, 'exec');
    count(data.lnk, 'exec');
    
    if (data.srum_net) {
      count(data.srum_net.connectivity, 'srum');
      count(data.srum_net.data_usage, 'srum');
    }
    
    if (data.amcache) {
      count(data.amcache.application_files, 'amcache');
      count(data.amcache.applications, 'amcache');
      count(data.amcache.drivers, 'amcache');
    }
    
    count(data.shimcache, 'shimcache');
    count(data.recyclebin, 'recyclebin');
    
    if (data.registry) {
      count(data.registry.open_save_mru, 'registry');
      count(data.registry.last_save_mru, 'registry');
      count(data.registry.shellbags, 'registry');
      count(data.registry.recent_docs, 'registry');
      count(data.registry.user_assist, 'registry');
    }
    
    if (data.sessions) {
      count(data.sessions.events, 'sessions');
    }

    // Compute top artifacts for each day with time ranges
    const fmtTime = (ms) => {
      const d = new Date(ms);
      return d.toLocaleTimeString('en-GB', { timeZone: 'UTC', hour: '2-digit', minute: '2-digit' });
    };
    dayArray.forEach(day => {
      const sorted = Object.entries(day._artifactNames)
        .sort((a, b) => b[1].count - a[1].count)
        .slice(0, 5)
        .map(([name, info]) => ({
          name,
          count: info.count,
          firstSeen: fmtTime(info.first),
          lastSeen: fmtTime(info.last),
          sameTime: info.first === info.last,
        }));
      day.topArtifacts = sorted;
      delete day._artifactNames; // Clean up
    });

    return dayArray;
  }, [data, timeRange]);

  const maxOnDay = Math.max(1, ...days.map(d => d.srum + d.mft + d.exec + d.amcache + d.shimcache + d.recyclebin + d.registry + d.sessions));

  // Task 5.5.1: Day click handler uses UTC methods
  const handleDayClick = (dayDate) => {
    const s = new Date(dayDate);
    // Task 5.5.1: setUTCHours ensures forensic alignment to UTC day boundaries
    s.setUTCHours(0, 0, 0, 0);
    const e = new Date(dayDate);
    e.setUTCHours(23, 59, 59, 999);
    // Task 5.5.1: toISOString() returns UTC format
    setTimeRange({ start: s.toISOString(), end: e.toISOString() });
    setViewModeOverride('24h');
  };

  return (
    <div className="week-view" style={{ flex: 1, padding: '20px', overflowY: 'auto', background: 'var(--bg-app)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h2 style={{ color: 'var(--accent-cyan)', fontSize: 18, margin: 0 }}>📊 Weekly Distribution</h2>
          <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Detailed artifact density per day</div>
        </div>
        <button className="topbar__btn" onClick={() => setViewModeOverride('heatmap')}>
          Back to Heatmap
        </button>
      </div>

      <div style={{ display: 'flex', gap: 12, height: 'calc(100% - 80px)', minHeight: 400 }}>
        {days.map((d) => {
          const total = d.srum + d.mft + d.exec + d.amcache + d.shimcache + d.recyclebin + d.registry + d.sessions;
          const hSrum = (d.srum / maxOnDay) * 100;
          const hMft = (d.mft / maxOnDay) * 100;
          const hExec = (d.exec / maxOnDay) * 100;
          const hAmcache = (d.amcache / maxOnDay) * 100;
          const hShimcache = (d.shimcache / maxOnDay) * 100;
          const hRecyclebin = (d.recyclebin / maxOnDay) * 100;
          const hRegistry = (d.registry / maxOnDay) * 100;
          const hSessions = (d.sessions / maxOnDay) * 100;

          return (
            <div key={d.iso} onClick={() => handleDayClick(d.date)} 
                 style={{ flex: 1, display: 'flex', flexDirection: 'column', cursor: 'pointer', minWidth: 60 }}>
              
              {/* Bars container */}
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column-reverse', background: 'rgba(255,255,255,0.03)', borderRadius: 4, position: 'relative', overflow: 'hidden', border: '1px solid var(--border-subtle)' }}>
                <div style={{ height: `${hSrum}%`, background: 'var(--lane-srum-app)', opacity: 0.7 }} title={`SRUM: ${d.srum}`} />
                <div style={{ height: `${hMft}%`, background: 'var(--lane-mft-usn)', opacity: 0.7 }} title={`MFT: ${d.mft}`} />
                <div style={{ height: `${hExec}%`, background: 'var(--lane-execution)', opacity: 0.7 }} title={`Execution: ${d.exec}`} />
                <div style={{ height: `${hAmcache}%`, background: 'var(--lane-cache)', opacity: 0.7 }} title={`Amcache: ${d.amcache}`} />
                <div style={{ height: `${hShimcache}%`, background: 'var(--lane-cache)', opacity: 0.7 }} title={`Shimcache: ${d.shimcache}`} />
                <div style={{ height: `${hRecyclebin}%`, background: 'var(--lane-cache)', opacity: 0.7 }} title={`RecycleBin: ${d.recyclebin}`} />
                <div style={{ height: `${hRegistry}%`, background: 'var(--lane-execution)', opacity: 0.7 }} title={`Registry: ${d.registry}`} />
                <div style={{ height: `${hSessions}%`, background: 'var(--lane-sessions)', opacity: 0.7 }} title={`Sessions: ${d.sessions}`} />
                
                {total > 0 && (
                  <div style={{ position: 'absolute', top: 10, width: '100%', textAlign: 'center', fontSize: 10, fontWeight: 700, color: 'white', textShadow: '0 1px 2px black' }}>
                    {total.toLocaleString()}
                  </div>
                )}
              </div>

              {/* Day Labels */}
              <div style={{ marginTop: 10, textAlign: 'center' }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)' }}>{d.label.split(' ')[0]}</div>
                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--accent-cyan)' }}>{d.label.split(' ')[1]}</div>
              </div>

              {/* Breakdown */}
              {total > 0 && (
                <div style={{ marginTop: 10, fontSize: 10, color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: 2, padding: '4px', background: 'rgba(0,0,0,0.2)', borderRadius: 4 }}>
                  {d.srum > 0 && <div style={{display: 'flex', justifyContent: 'space-between'}}><span>SRUM:</span> <span>{d.srum}</span></div>}
                  {d.mft > 0 && <div style={{display: 'flex', justifyContent: 'space-between'}}><span>MFT:</span> <span>{d.mft}</span></div>}
                  {d.exec > 0 && <div style={{display: 'flex', justifyContent: 'space-between'}}><span>Exec:</span> <span>{d.exec}</span></div>}
                  {d.amcache > 0 && <div style={{display: 'flex', justifyContent: 'space-between'}}><span>Amcache:</span> <span>{d.amcache}</span></div>}
                  {d.shimcache > 0 && <div style={{display: 'flex', justifyContent: 'space-between'}}><span>Shimcache:</span> <span>{d.shimcache}</span></div>}
                  {d.recyclebin > 0 && <div style={{display: 'flex', justifyContent: 'space-between'}}><span>Recycle:</span> <span>{d.recyclebin}</span></div>}
                  {d.registry > 0 && <div style={{display: 'flex', justifyContent: 'space-between'}}><span>Registry:</span> <span>{d.registry}</span></div>}
                  {d.sessions > 0 && <div style={{display: 'flex', justifyContent: 'space-between'}}><span>Sessions:</span> <span>{d.sessions}</span></div>}
                </div>
              )}

              {/* Top Artifacts */}
              {d.topArtifacts && d.topArtifacts.length > 0 && (
                <div style={{ marginTop: 6, fontSize: 9, padding: '5px', background: 'rgba(0, 255, 255, 0.05)', borderRadius: 4, border: '1px solid rgba(0, 255, 255, 0.15)' }}>
                  <div style={{ color: 'var(--accent-cyan)', fontWeight: 700, fontSize: 9, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Top Artifacts</div>
                  {d.topArtifacts.map((art, idx) => (
                    <div key={idx} style={{ marginBottom: 4, paddingBottom: 3, borderBottom: idx < d.topArtifacts.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 4, color: idx === 0 ? 'var(--accent-cyan)' : 'var(--text-muted)' }}>
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: idx === 0 ? 700 : 400 }} title={art.name}>{art.name}</span>
                        <span style={{ flexShrink: 0, fontWeight: 600 }}>×{art.count}</span>
                      </div>
                      <div style={{ fontSize: 8, color: 'var(--text-muted)', marginTop: 1, fontFamily: 'var(--font-mono)', opacity: 0.8 }}>
                        {art.sameTime ? `@ ${art.firstSeen}` : `${art.firstSeen} – ${art.lastSeen}`}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default memo(WeekView);