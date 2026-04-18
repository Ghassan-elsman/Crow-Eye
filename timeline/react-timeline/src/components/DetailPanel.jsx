import { memo } from 'react';
import { formatTime, formatBytes, formatDuration, formatCycleTime } from '../utils/formatters';

const USN_REASONS = {
  0x00000001: 'Data Extend',
  0x00000002: 'Data Overwrite',
  0x00000004: 'Data Truncation',
  0x00000010: 'Named Data Extend',
  0x00000020: 'Named Data Overwrite',
  0x00000040: 'Named Data Truncation',
  0x00000100: 'File Create',
  0x00000200: 'File Delete',
  0x00000400: 'EA Change',
  0x00000800: 'Security Change',
  0x00001000: 'Rename Old Name',
  0x00002000: 'Rename New Name',
  0x00004000: 'Indexable Change',
  0x00008000: 'Basic Info Change',
  0x00010000: 'Hard Link Change',
  0x00020000: 'Compression Change',
  0x00040000: 'Encryption Change',
  0x00080000: 'Object ID Change',
  0x00100000: 'Reparse Point Change',
  0x00200000: 'Stream Change',
  0x80000000: 'Close'
};

function DetailPanel({ state, data, links, callBridge }) {
  const { selectedEvent, detailPanelCollapsed, setDetailPanelCollapsed, setDetailEvent, setSelectedEvent } = state;

  if (!selectedEvent) return null;

  // Find related events using links
  let relatedEvents = [];
  if (links && links.length > 0 && selectedEvent.id) {
    const relatedLinks = (links || []).filter(lk => lk.source?.id === selectedEvent.id || lk.target?.id === selectedEvent.id);
    relatedEvents = relatedLinks.map(lk => lk.source?.id === selectedEvent.id ? lk.target : lk.source);
    
    // Remove duplicates based on ID
    const seen = new Set();
    relatedEvents = relatedEvents.filter(ev => {
        if (seen.has(ev.id)) return false;
        seen.add(ev.id);
        return true;
    });
  }

  // FIX: Bug 9 - MFT/USN Duration Display in Detail Panel
  // Suppresses "End Time" and "Duration" fields for instantaneous events (MFT, Prefetch, Registry)
  // Only shows duration for time-span events (SRUM, sessions) to maintain forensic accuracy
  // Task 9.1.1: Define instantaneous artifact types (point-in-time events)
  const INSTANTANEOUS_TYPES = ['mft_create', 'mft_usn', 'prefetch', 'registry'];
  
  // Task 9.1.2: Check if current event is instantaneous
  const isInstantaneous = INSTANTANEOUS_TYPES.includes(selectedEvent.type);
  
  // Task 9.3.1: Calculate duration for time-span events (SRUM, sessions)
  let duration = null;
  if (!isInstantaneous && selectedEvent.start && selectedEvent.end) {
    const startTime = new Date(selectedEvent.start).getTime();
    const endTime = new Date(selectedEvent.end).getTime();
    const durationSeconds = Math.floor((endTime - startTime) / 1000);
    duration = durationSeconds;
  }

  const usnReason = (selectedEvent.type?.includes('usn') && selectedEvent.usn_reason) 
    ? (USN_REASONS[selectedEvent.usn_reason] || `0x${selectedEvent.usn_reason.toString(16)}`) 
    : null;

  return (
    <div className={`detail-panel ${detailPanelCollapsed ? 'detail-panel--collapsed' : ''}`}>
      <div className="detail-panel__header" onClick={() => setDetailPanelCollapsed(!detailPanelCollapsed)} style={{ cursor: 'pointer' }}>
        <div className="detail-panel__title" style={detailPanelCollapsed ? { writingMode: 'vertical-rl', transform: 'rotate(180deg)', margin: 'auto', padding: '10px 0' } : {}}>
          {detailPanelCollapsed ? '▶ Details' : '▶ Event Details'}
        </div>
        {!detailPanelCollapsed && (
          <button 
            className="modal__btn modal__btn--primary" 
            onClick={(e) => { e.stopPropagation(); if(callBridge) callBridge('openEventDetailDialog', JSON.stringify(selectedEvent)); else setDetailEvent(selectedEvent); }}
            style={{ padding: '2px 8px', fontSize: 10 }}
          >
            Open Original
          </button>
        )}
      </div>
      
      {!detailPanelCollapsed && (
        <div className="detail-panel__content">
           {/* Main Detail Timestamp */}
           <Field label="Timestamp (UTC)" val={formatTime(selectedEvent.timestamp || selectedEvent.start)} />
           
           {/* Detailed Forensic Timestamps (for LNK/Registry/Artifacts) */}
           {selectedEvent.Time_Creation && <Field label="Created (UTC)" val={formatTime(selectedEvent.Time_Creation)} />}
           {selectedEvent.Time_Modification && <Field label="Modified (UTC)" val={formatTime(selectedEvent.Time_Modification)} />}
           {selectedEvent.Time_Access && <Field label="Accessed (UTC)" val={formatTime(selectedEvent.Time_Access)} />}
           
           {/* Task 9.2: Conditionally render "End Time" only for time-span events */}
           {!isInstantaneous && selectedEvent.end && (
             <Field label="End Time (UTC)" val={formatTime(selectedEvent.end)} />
           )}
           {/* Task 9.3.2: Display duration for time-span events */}
           {!isInstantaneous && duration !== null && (
             <Field label="Duration" val={formatDuration(duration)} />
           )}
           
           <div className="detail-panel__section">Identification</div>
           <Field label="App / File" val={selectedEvent.app_name || selectedEvent.fn_filename || selectedEvent.fileName || selectedEvent.file_name || selectedEvent.filename || selectedEvent.Source_Name || selectedEvent.name || selectedEvent.executable_name} />
           <Field label="Path" val={selectedEvent.program_path || selectedEvent.network_name || selectedEvent.app_path || selectedEvent.reconstructed_path || selectedEvent.Source_Path || selectedEvent.lower_case_long_path || selectedEvent.path || selectedEvent.target_path || selectedEvent.file_path} />
           
           <div className="detail-panel__section">Context</div>
           <Field label="Type / Event" val={selectedEvent.type || selectedEvent.op || selectedEvent.src || selectedEvent.EventID || selectedEvent.artifact_type} />
           <Field label="Action / Reason" val={usnReason} />
           <Field label="User" val={selectedEvent.user || selectedEvent.username || selectedEvent.user_sid || selectedEvent.Account} />
           <Field label="Description" val={selectedEvent.description || selectedEvent.Event_Description} />
           
           <div className="detail-panel__section">Additional</div>
           <Field label="Record ID" val={selectedEvent.id || selectedEvent.row_id || selectedEvent.record_id} />
           <Field label="Source" val={selectedEvent.source_db || selectedEvent.source_table} />
           <Field label="File Size" val={(selectedEvent.FileSize || selectedEvent.File_Size || selectedEvent.file_size) ? formatBytes(selectedEvent.FileSize || selectedEvent.File_Size || selectedEvent.file_size) : null} />
           <Field label="Run Count" val={selectedEvent.run_count || selectedEvent.execution_count || selectedEvent.ExecutionCount} />
           <Field label="Bytes Sent" val={selectedEvent.bytes_sent ? formatBytes(selectedEvent.bytes_sent) : null} />
           <Field label="Bytes Recv" val={selectedEvent.bytes_received ? formatBytes(selectedEvent.bytes_received) : null} />
           <Field label="CPU Cycles" val={selectedEvent.cpu_cycles ? formatCycleTime(selectedEvent.cpu_cycles) : null} />
           <Field label="Face Time" val={selectedEvent.face_time ? formatDuration(selectedEvent.face_time) : null} />
           <Field label="Background Time" val={selectedEvent.background_time ? formatDuration(selectedEvent.background_time) : (selectedEvent.background_cycle_time ? formatDuration(selectedEvent.background_cycle_time) : null)} />
           <Field label="Connect Time" val={selectedEvent.connected_time ? formatDuration(selectedEvent.connected_time) : null} />
           <Field label="Vendor" val={selectedEvent.vendor_id} />
           <Field label="Product" val={selectedEvent.product_id} />
           <Field label="Serial" val={selectedEvent.serial_number} />
           <Field label="IP Address" val={selectedEvent.ip_address} />
           <Field label="MAC Address" val={selectedEvent.mac_address} />
           <Field label="GUID / SID" val={selectedEvent.guid || selectedEvent.sid} />

           {relatedEvents.length > 0 && (
             <>
               <div className="detail-panel__section">Analytical Links</div>
               <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
                 {relatedEvents.map((ev, i) => (
                   <div 
                     key={i} 
                     className="detail-panel__link-card"
                     onClick={() => setSelectedEvent(ev)}
                     style={{
                       background: 'var(--bg-elevated)',
                       border: '1px solid var(--border-default)',
                       borderRadius: 4,
                       padding: '6px 8px',
                       cursor: 'pointer',
                       transition: 'background var(--transition-fast)'
                     }}
                     onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                     onMouseLeave={e => e.currentTarget.style.background = 'var(--bg-elevated)'}
                   >
                     <div style={{ fontSize: 10, color: 'var(--accent-blue)', fontWeight: 600, textTransform: 'uppercase', marginBottom: 2 }}>{ev.type.replace('_', ' ')}</div>
                     <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', wordBreak: 'break-all', color: 'var(--text-primary)' }}>{ev.rawName || 'Unknown'}</div>
                     <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>{formatTime(ev.timestamp, 'short')}</div>
                   </div>
                 ))}
               </div>
             </>
           )}
        </div>
      )}
    </div>
  );
}

function Field({ label, val }) {
    if (val === undefined || val === null || val === '') return null;
    return (
        <div className="detail-panel__field">
            <div className="detail-panel__label">{label}</div>
            <div className="detail-panel__value">{String(val)}</div>
        </div>
    );
}

export default memo(DetailPanel);
