import { memo } from 'react';
import { formatTime, formatBytes, formatDuration, formatCycleTime, cleanForensicDate } from '../utils/formatters';
import FlowBadge from './FlowBadge';
import { buildAiIndex, aiHitsFor, linksOfStep, AI_COLOR } from '../utils/aiLinks';

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

// A link end holds its row in `.source`; open it as the lane would - the full
// row with the mark's id, type and time - so the panel shows every field and
// lists the row's own links.
function linkedRow(ev) {
  return {
    ...(ev.source || {}),
    id: ev.id,
    type: ev.type,
    subType: ev.type,
    _artifact_type: ev.type,
    timestamp: ev.rawTimestamp || ev.timestamp,
  };
}

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
           
           {/* An AI agent step: who took it, what it was, where, in which
               session. "Open Original" reads the whole row, `text` included. */}
           {selectedEvent.type === 'ai_agent' && (
             <>
               <div className="detail-panel__section">AI Agent Step</div>
               <Field label="Agent" val={selectedEvent.agent ? `${selectedEvent.agent}${selectedEvent.is_sidechain ? ' (sub-agent)' : ''}` : null} />
               <Field label="Step" val={selectedEvent.ai_what || selectedEvent.kind} />
               <Field label="Session" val={selectedEvent.session_name} />
               <Field label="Order in the session" val={selectedEvent.seq ? `step ${selectedEvent.seq}${selectedEvent.turn ? `, answering instruction ${selectedEvent.turn}` : ''}` : null} />
               <Field label="Ordered by" val={selectedEvent.kind !== 'prompt' ? selectedEvent.ordered_by : null} />
               <Field label="The instruction" val={selectedEvent.kind !== 'prompt' ? selectedEvent.instruction : null} />
               <Field label="Command" val={selectedEvent.command} />
               <Field label="Command length" val={selectedEvent.command_length > 1000 ? `${selectedEvent.command_length} characters - the first 1000 are shown; Open Original reads it whole` : null} />
               <Field label="File / Target" val={selectedEvent.kind !== 'command' ? selectedEvent.target : null} />
               <Field label="Description" val={selectedEvent.kind === 'command' ? selectedEvent.target : null} />
               <Field label="Prompt (opening)" val={selectedEvent.prompt_preview} />
               <Field label="Sent by" val={selectedEvent.kind === 'prompt' ? selectedEvent.origin : null} />
               <Field label="Programs started" val={selectedEvent.program} />
               <Field label="Allowed" val={selectedEvent.approval} />
               <Field label="Exit code" val={selectedEvent.exit_code !== null && selectedEvent.exit_code !== undefined ? String(selectedEvent.exit_code) : null} />
               <Field label="Took" val={selectedEvent.duration_ms ? (selectedEvent.duration_ms >= 1000 ? `${(selectedEvent.duration_ms / 1000).toFixed(1)} s` : `${selectedEvent.duration_ms} ms`) : null} />
               <Field label="Working Folder" val={selectedEvent.cwd} />
               <Field label="User" val={selectedEvent.user_name} />
               <Field label="Session id" val={selectedEvent.session_id} />
               <Field label="Tool" val={selectedEvent.tool} />
               <Field label="Status" val={selectedEvent.status === 'rejected' ? 'rejected - the call was refused and did not run' : selectedEvent.status} />
               {selectedEvent.output ? (
                 <div className="detail-panel__field">
                   <div className="detail-panel__label">Output{selectedEvent.output_length > 600 ? ' (opening; Open Original reads the whole result)' : ''}</div>
                   <pre className="detail-panel__output">{selectedEvent.output}</pre>
                 </div>
               ) : null}
               <Field label="Source" val={selectedEvent.db && selectedEvent.table ? `${selectedEvent.db} / ${selectedEvent.table} #${selectedEvent.row_id}` : null} />
             </>
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
           {(Number(selectedEvent.bytes_sent) > 0 || Number(selectedEvent.bytes_received) > 0) && (
             <div className="detail-panel__field">
               <div className="detail-panel__label">Network</div>
               <div className="detail-panel__value detail-panel__flow flow-host">
                 {Number(selectedEvent.bytes_sent) > 0 && <FlowBadge dir="up" value={formatBytes(Number(selectedEvent.bytes_sent))} />}
                 {Number(selectedEvent.bytes_received) > 0 && <FlowBadge dir="down" value={formatBytes(Number(selectedEvent.bytes_received))} />}
               </div>
             </div>
           )}
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

           <AiLinksSection event={selectedEvent} aiLinks={data?.ai_links} callBridge={callBridge} />

           {relatedEvents.length > 0 && (
             <>
               <div className="detail-panel__section">Analytical Links</div>
               <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
                 {relatedEvents.map((ev, i) => (
                   <div 
                     key={i} 
                     className="detail-panel__link-card"
                     onClick={() => setSelectedEvent(linkedRow(ev))}
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

// An AI step and the Windows record of the same act, both openable in their
// own tab. On a Windows mark: which AI agent's step this was. On an AI step:
// what Windows recorded of it. Each line names the rule that matched them.
function AiLinksSection({ event, aiLinks, callBridge }) {
  if (!event || !aiLinks || aiLinks.length === 0) return null;
  const isStep = event.type === 'ai_agent';
  const found = isStep ? linksOfStep(event, aiLinks) : (aiHitsFor(event, buildAiIndex(aiLinks)) || []);
  if (found.length === 0) return null;
  const show = (db, table, rid) => callBridge && callBridge('showInTable', db, table, String(rid));
  const btn = { padding: '1px 6px', fontSize: 9, marginTop: 4, marginRight: 6 };
  return (
    <>
      <div className="detail-panel__section" style={{ color: AI_COLOR }}>
        {isStep ? `What Windows recorded of this step (${found.length})` : 'Done by an AI agent'}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 6 }}>
        {found.slice(0, 40).map((l, i) => (
          <div key={i} className="detail-panel__ai-link"
            style={{ border: `1px solid ${AI_COLOR}55`, borderRadius: 4, padding: '6px 8px', background: 'var(--bg-elevated)' }}>
            <div style={{ fontSize: 10, color: AI_COLOR, fontWeight: 700, textTransform: 'uppercase' }}>
              {isStep ? l.source : `${l.ai_agent} - ${l.ai_kind}`}
            </div>
            <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', wordBreak: 'break-all', color: 'var(--text-primary)' }}>
              {isStep ? `${l.name}${l.detail ? '  (' + l.detail + ')' : ''}` : (l.ai_text || '')}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
              {isStep ? formatTime(cleanForensicDate(l.ts), 'short') : `step at ${formatTime(cleanForensicDate(l.ai_ts), 'short')}`}
              {l.delta_s !== null && l.delta_s !== undefined ? `  ·  ${l.delta_s > 0 ? '+' : ''}${l.delta_s} s` : ''}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 2 }}>{l.rule_text}</div>
            <div>
              <button className="modal__btn" style={btn} onClick={() => show('ai_agents.db', 'ai_agent_steps', l.ai_rowid)}>AI step in table</button>
              <button className="modal__btn" style={btn} onClick={() => show(l.db, l.table, l.rowid)}>{l.source} in table</button>
            </div>
          </div>
        ))}
        {found.length > 40 && <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{found.length - 40} more</div>}
      </div>
    </>
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
