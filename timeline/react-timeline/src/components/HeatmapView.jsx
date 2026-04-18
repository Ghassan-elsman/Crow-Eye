import { memo, useMemo, useState } from 'react';
import { cleanForensicDate } from '../utils/formatters';

/**
 * HeatmapView — Calendar grid showing per-day forensic artifact density.
 * Click any active day to load detailed lane data for that day ± 3 days.
 */
function HeatmapView({ globalBounds, data, state, setLoading, setLoadingMessage }) {
  const { setTimeRange, setViewModeOverride } = state;
  const aggregated = data?.aggregated;

  const [hoveredDay, setHoveredDay] = useState(null);

  // Merge daily totals across all data sources
  const dailyTotals = useMemo(() => {
    if (!aggregated) return {};
    const totals = {};
    Object.entries(aggregated).forEach(([tableKey, tableRows]) => {
      if (!Array.isArray(tableRows)) return;
      tableRows.forEach(row => {
        if (!row.day) return;
        if (!totals[row.day]) {
          totals[row.day] = { total: 0, sources: {}, hours: {} };
        }
        totals[row.day].total += (row.count || 0);
        totals[row.day].sources[tableKey] = (totals[row.day].sources[tableKey] || 0) + (row.count || 0);
        
        if (row.hour != null) {
          totals[row.day].hours[row.hour] = (totals[row.day].hours[row.hour] || 0) + (row.count || 0);
        }
      });
    });
    return totals;
  }, [aggregated]);

  // FIX: Bug 10 - HeatmapView Date Calculation Edge Cases
  // Uses UTC-only date arithmetic to handle DST transitions, leap years, and month boundaries
  // Prevents missing days or off-by-one errors in heatmap calendar
  // Build array of contiguous days between global bounds
  // Task 10.1: All date arithmetic uses UTC methods to prevent DST issues
  // Task 10.2: DST boundary handling with validation
  // Task 10.3: Leap year handling
  // Task 10.4: Month boundary validation
  const days = useMemo(() => {
    if (!globalBounds?.start || !globalBounds?.end) return [];

    const start = new Date(cleanForensicDate(globalBounds.start));
    const end = new Date(cleanForensicDate(globalBounds.end));

    if (isNaN(start.getTime()) || isNaN(end.getTime())) return [];

    // Task 10.1.1: setUTCHours ensures we're working in UTC, not local time
    start.setUTCHours(0, 0, 0, 0);
    end.setUTCHours(23, 59, 59, 999);

    // Cap at 5 years max to avoid insane ranges
    const maxSpan = 5 * 365 * 24 * 60 * 60 * 1000;
    const actualStart = (end.getTime() - start.getTime() > maxSpan)
      ? new Date(end.getTime() - maxSpan)
      : start;

    const result = [];
    // Task 10.1.2: Use UTC-only arithmetic by working with year/month/day components
    // instead of millisecond arithmetic to avoid DST edge cases
    let currentYear = actualStart.getUTCFullYear();
    let currentMonth = actualStart.getUTCMonth();
    let currentDay = actualStart.getUTCDate();
    
    const endTime = end.getTime();
    let iterationCount = 0;
    const MAX_ITERATIONS = 2000;

    while (iterationCount < MAX_ITERATIONS) {
      // Create date from UTC components
      const current = new Date(Date.UTC(currentYear, currentMonth, currentDay, 0, 0, 0, 0));
      
      // Break if we've passed the end date
      if (current.getTime() > endTime) break;
      
      const iso = current.toISOString().split('T')[0];
      result.push({
        date: new Date(current),
        iso,
        count: dailyTotals[iso]?.total || 0,
        sources: dailyTotals[iso]?.sources || {},
        hours: dailyTotals[iso]?.hours || {}
      });

      // Task 10.1.2: Increment day using UTC component arithmetic
      // This handles month boundaries, leap years, and DST transitions correctly
      currentDay++;
      
      // Task 10.4: Month boundary validation
      // Check if we've exceeded the days in the current month
      const daysInMonth = new Date(Date.UTC(currentYear, currentMonth + 1, 0)).getUTCDate();
      if (currentDay > daysInMonth) {
        currentDay = 1;
        currentMonth++;
        
        // Year boundary
        if (currentMonth > 11) {
          currentMonth = 0;
          currentYear++;
        }
      }
      
      // Task 10.1.2: Validate day continuity
      // Ensure the next iteration will produce a valid date
      const nextDate = new Date(Date.UTC(currentYear, currentMonth, currentDay, 0, 0, 0, 0));
      if (isNaN(nextDate.getTime())) {
        console.error('HeatmapView: Invalid date generated during iteration', {
          currentYear, currentMonth, currentDay
        });
        break;
      }
      
      iterationCount++;
    }
    
    if (iterationCount >= MAX_ITERATIONS) {
      console.warn('HeatmapView: Reached maximum iteration limit, date range may be truncated');
    }
    
    return result;
  }, [globalBounds, dailyTotals]);

  // Still loading?
  if (!aggregated || Object.keys(aggregated).length === 0) {
    return (
      <div className="empty-state">
        <div className="loading__spinner" />
        <div style={{ marginTop: 12, fontSize: 13 }}>Aggregating forensic data...</div>
      </div>
    );
  }

  const maxCount = Math.max(...days.map(d => d.count), 1);

  // Click handler: zoom to day ± 3 days (7 days total)
  // Task 10.1: All date manipulation uses UTC methods
  const handleDayClick = (dateObj) => {
    if (setLoading) setLoading(true);
    if (setLoadingMessage) setLoadingMessage('Loading detailed forensic artifacts for selected range...');

    setTimeout(() => {
      // Force UTC-normalized start/end range
      const s = new Date(Date.UTC(dateObj.getUTCFullYear(), dateObj.getUTCMonth(), dateObj.getUTCDate(), 0, 0, 0));
      const e = new Date(Date.UTC(dateObj.getUTCFullYear(), dateObj.getUTCMonth(), dateObj.getUTCDate(), 23, 59, 59, 999));
      
      // Use toISOString() for consistent UTC transmission
      setTimeRange({ start: s.toISOString(), end: e.toISOString() });
      setViewModeOverride('24h');
    }, 10);
  };

  // Month names
  const mos = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

  // Safe date formatter - Task 10.1: Uses UTC methods
  const fmtDate = (d) => {
    try {
      if (!d || isNaN(d.getTime())) return 'Unknown';
      // Task 10.1: getUTCMonth, getUTCDate, getUTCFullYear ensure UTC display
      return `${mos[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
    } catch { return 'Unknown'; }
  };

  // Group days by month for better visual layout
  // Task 10.1: Uses UTC methods for month/year extraction
  const months = useMemo(() => {
    const map = {};
    days.forEach(d => {
      // Task 10.1: getUTCFullYear and getUTCMonth ensure UTC-based grouping
      const key = `${d.date.getUTCFullYear()}-${String(d.date.getUTCMonth()+1).padStart(2,'0')}`;
      if (!map[key]) {
         const fullMos = ['January','February','March','April','May','June','July','August','September','October','November','December'];
         map[key] = { label: `${fullMos[d.date.getUTCMonth()]} ${d.date.getUTCFullYear()}`, days: [] };
      }
      map[key].days.push(d);
    });
    return Object.values(map);
  }, [days]);

  return (
    <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
      {/* Left Panel for hover details */}
      <div style={{ width: 250, borderRight: '1px solid var(--border-default)', padding: 20, background: 'var(--bg-surface)', display: 'flex', flexDirection: 'column', overflowY: 'auto' }}>
        <h3 style={{ fontSize: 16, color: 'var(--accent-cyan)', marginBottom: 12 }}>Day Details</h3>
        {hoveredDay ? (
          <div>
            <div style={{ fontSize: 14, fontWeight: 'bold', marginBottom: 10, color: 'var(--text-primary)' }}>{fmtDate(hoveredDay.date)}</div>
            <div style={{ fontSize: 12, marginBottom: 15, color: 'var(--text-muted)' }}>Total Artifacts: {hoveredDay.count.toLocaleString()}</div>
            
            {/* Peak Activity Hour Badge */}
            {(() => {
              const sortedHours = Object.entries(hoveredDay.hours || {}).sort((a,b) => b[1] - a[1]);
              if (sortedHours.length === 0) return null;
              const [topHour, topCount] = sortedHours[0];
              const pct = hoveredDay.count > 0 ? Math.round((topCount / hoveredDay.count) * 100) : 0;
              const hourNum = parseInt(topHour, 10);
              const nextHourNum = (hourNum + 1) % 24;
              const hourLabel = `${hourNum.toString().padStart(2, '0')}:00 - ${nextHourNum.toString().padStart(2, '0')}:00`;
              return (
                <div style={{ 
                  marginBottom: 14, padding: '8px 10px', borderRadius: 6, 
                  background: 'rgba(255, 165, 0, 0.08)', border: '1px solid rgba(255, 165, 0, 0.25)' 
                }}>
                  <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Peak Activity Hour</div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: '#ffa500' }}>{hourLabel}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 2 }}>
                    {topCount.toLocaleString()} artifacts ({pct}%)
                  </div>
                </div>
              );
            })()}

            {/* Top Source Badge */}
            {(() => {
              const sorted = Object.entries(hoveredDay.sources || {}).sort((a,b) => b[1] - a[1]);
              if (sorted.length === 0) return null;
              const [topSource, topCount] = sorted[0];
              const pct = hoveredDay.count > 0 ? Math.round((topCount / hoveredDay.count) * 100) : 0;
              return (
                <div style={{ 
                  marginBottom: 14, padding: '8px 10px', borderRadius: 6, 
                  background: 'rgba(0, 255, 255, 0.08)', border: '1px solid rgba(0, 255, 255, 0.25)' 
                }}>
                  <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Most Active Source</div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent-cyan)' }}>{topSource}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 2 }}>
                    {topCount.toLocaleString()} artifacts ({pct}%)
                  </div>
                </div>
              );
            })()}

            {/* Granular Breakdown Sections */}
            {(() => {
              const src = hoveredDay.sources || {};
              const sourceLabels = {
                'prefetch': 'Prefetch Executions',
                'lnk': 'LNK/JumpList Activity',
                'amcache': 'Amcache App/Driver Activity',
                'shimcache': 'ShimCache AppCompat',
                'recyclebin': 'Recycle Bin Deletions',
                'registry_others': 'Registry/MRU Artifacts',
                'SystemLogs': 'Windows System Logs',
                'ApplicationLogs': 'Application Event Logs',
                'SecurityLogs': 'Security/Logon Logs',
                'srum_app': 'App Resource Usage (SRUM)',
                'srum_net': 'Network Data Usage (SRUM)',
                'mft_usn': 'MFT/USN Journal Ops'
              };

              const forensicKeys = ['prefetch', 'lnk', 'amcache', 'shimcache', 'recyclebin', 'registry_others'];
              const systemKeys = ['SystemLogs', 'ApplicationLogs', 'SecurityLogs', 'srum_app', 'srum_net', 'mft_usn'];

              const renderGroup = (title, keys, color) => {
                const groupItems = keys.filter(k => src[k] > 0).sort((a,b) => src[b] - src[a]);
                if (groupItems.length === 0) return null;
                return (
                  <div style={{ marginBottom: 20 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8, borderBottom: '1px solid var(--border-subtle)', paddingBottom: 4 }}>{title}</div>
                    {groupItems.map(k => {
                      const count = src[k];
                      const pct = hoveredDay.count > 0 ? Math.round((count / hoveredDay.count) * 100) : 0;
                      return (
                        <div key={k} style={{ marginBottom: 8 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 2 }}>
                            <span style={{ color: 'var(--text-secondary)' }}>{sourceLabels[k] || k}</span>
                            <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{count.toLocaleString()}</span>
                          </div>
                          <div style={{ height: 3, borderRadius: 2, background: 'rgba(255,255,255,0.05)', overflow: 'hidden' }}>
                            <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 2 }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                );
              };

              return (
                <>
                  {renderGroup('Forensic Artifact Hub', forensicKeys, 'var(--accent-cyan)')}
                  {renderGroup('System Activity & Logs', systemKeys, 'var(--accent-blue)')}
                </>
              );
            })()}

            {hoveredDay.count === 0 && (
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No activity detected for this date.</div>
            )}
          </div>
        ) : (
          <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Hover over a day to view details.</div>
        )}
      </div>

      <div style={{ flex: 1, padding: '24px', overflowY: 'auto' }}>
        <h2 style={{ fontSize: 18, marginBottom: 4, color: 'var(--accent-cyan)' }}>
          🦅 Global Case Overview
        </h2>
        <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 15 }}>
          Select a highlighted day to load full forensic lane details for that day and surrounding week.
        </p>

        {/* General Information & Statistics */}
        <div style={{ display: 'flex', gap: 20, marginBottom: 25, padding: '12px 16px', background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 8 }}>
           <div style={{ flex: 1 }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Time Span</div>
              <div style={{ fontSize: 13, fontWeight: 500, marginTop: 4 }}>
                 {fmtDate(new Date(cleanForensicDate(globalBounds.start)))} — {fmtDate(new Date(cleanForensicDate(globalBounds.end)))}
              </div>
           </div>
           <div style={{ flex: 1 }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Total Active Days</div>
              <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--accent-blue)', marginTop: 2 }}>
                 {days.filter(d => d.count > 0).length} days
              </div>
           </div>
           <div style={{ flex: 1 }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Total Events</div>
              <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--accent-green)', marginTop: 2 }}>
                 {days.reduce((acc, d) => acc + d.count, 0).toLocaleString()} artifacts
              </div>
           </div>
        </div>

        <div style={{ display: 'flex', gap: 4, marginBottom: 8, paddingLeft: 2 }}>
          {['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map(d => (
            <div key={d} style={{ width: 26, textAlign: 'center', fontSize: 10, color: 'var(--text-muted)', fontWeight: 600 }}>{d[0]}</div>
          ))}
        </div>

        {/* Color Legend */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16, fontSize: 10, color: 'var(--text-muted)' }}>
          <span>Low</span>
          <div style={{ 
            width: 150, height: 10, borderRadius: 5, 
            background: 'linear-gradient(to right, rgb(15, 25, 45), rgb(20, 45, 85), rgb(25, 65, 130), rgb(30, 90, 180), rgb(35, 115, 230))',
            border: '1px solid rgba(255,255,255,0.1)'
          }} />
          <span>High</span>
        </div>

        {months.map((month, mi) => (
          <div key={mi} style={{ marginBottom: 24 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent-cyan)', marginBottom: 10 }}>
              {month.label}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {/* Add padding so the 1st of the month aligns with the correct day of the week */}
              {Array.from({ length: month.days[0]?.date.getUTCDay() || 0 }).map((_, i) => (
                <div key={`pad-${i}`} style={{ width: 26, height: 26 }} />
              ))}
              {month.days.map((d) => {
                const hasData = d.count > 0;
                const intensity = hasData ? Math.log10(d.count + 1) / Math.log10(maxCount + 1) : 0;
                
                // Comfortable deep blue gradient: dark navy → medium blue → royal blue → vivid blue
                const getDensityColor = (t) => {
                  if (t <= 0) return { bg: 'rgba(255,255,255,0.04)', border: 'rgba(255,255,255,0.06)', text: 'rgba(255,255,255,0.2)' };
                  const stops = [
                    { t: 0.0, r: 15, g: 25, b: 45 },     // dark navy
                    { t: 0.25, r: 20, g: 45, b: 85 },    // muted blue
                    { t: 0.5, r: 25, g: 65, b: 130 },    // medium blue
                    { t: 0.75, r: 30, g: 90, b: 180 },   // royal blue
                    { t: 1.0, r: 35, g: 115, b: 230 },   // deep vivid blue
                  ];
                  let i = 0;
                  while (i < stops.length - 1 && stops[i + 1].t < t) i++;
                  const a = stops[i], b = stops[Math.min(i + 1, stops.length - 1)];
                  const localT = b.t === a.t ? 1 : (t - a.t) / (b.t - a.t);
                  const r = Math.round(a.r + (b.r - a.r) * localT);
                  const g = Math.round(a.g + (b.g - a.g) * localT);
                  const bl = Math.round(a.b + (b.b - a.b) * localT);
                  return {
                    bg: `rgb(${r}, ${g}, ${bl})`,
                    border: `rgba(${Math.min(255, r + 40)}, ${Math.min(255, g + 40)}, ${Math.min(255, bl + 40)}, 0.5)`,
                    text: t > 0.6 ? '#fff' : 'rgba(255,255,255,0.9)',
                  };
                };
                
                const colors = getDensityColor(intensity);
                return (
                  <div
                    key={d.iso}
                    onClick={() => hasData && setHoveredDay(d)}
                    onDoubleClick={() => hasData && handleDayClick(d.date)}
                    title={`${fmtDate(d.date)}: ${d.count.toLocaleString()} artifacts`}
                    style={{
                      width: 26,
                      height: 26,
                      borderRadius: 4,
                      cursor: hasData ? 'pointer' : 'default',
                      backgroundColor: colors.bg,
                      border: `1px solid ${colors.border}`,
                      transition: 'transform 0.1s, box-shadow 0.1s',
                      fontSize: 10,
                      fontWeight: 700,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: colors.text,
                    }}
                    onMouseEnter={(e) => {
                      setHoveredDay(d);
                      if (hasData) {
                        e.currentTarget.style.transform = 'scale(1.25)';
                        e.currentTarget.style.boxShadow = `0 0 10px ${colors.border}`;
                        e.currentTarget.style.zIndex = 10;
                      }
                    }}
                    onMouseLeave={(e) => {
                      setHoveredDay(null);
                      e.currentTarget.style.transform = 'scale(1)';
                      e.currentTarget.style.boxShadow = 'none';
                      e.currentTarget.style.zIndex = 1;
                    }}
                  >
                    {d.date.getUTCDate()}
                  </div>
                );
              })}
            </div>
          </div>
        ))}

        {days.length === 0 && (
          <div className="empty-state">No daily data detected across global bounds.</div>
        )}
      </div>
    </div>
  );
}

export default memo(HeatmapView);
