/**
 * EventDetailModal — Full-screen modal for displaying all raw database fields.
 */
import { memo, useEffect, useState } from 'react';
import { formatTime } from '../utils/formatters';
import { IconTag } from './Icons';

function EventDetailModal({ event, onClose, callBridge }) {
  const [fullData, setFullData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!event || !event.db || !event.table || !event.id) {
       setFullData(event); // Just show what we have
       return;
    }

    setLoading(true);
    callBridge('getEventDetail', event.db, event.table, String(event.id))
      .then(res => {
         if (res && !res.error) setFullData(res);
         else setFullData(event);
      })
      .catch((e) => {
         console.error('Failed to get full record:', e);
         setFullData(event);
      })
      .finally(() => setLoading(false));
  }, [event, callBridge]);

  if (!event) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal__header">
          <div className="modal__badge" style={{ background: 'var(--accent-blue)', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <IconTag size={14} color="currentColor" /> Event Record
          </div>
          <button className="modal__close" onClick={onClose}>×</button>
        </div>
        
        <div className="modal__body">
          {/*
            A registry KEY write time. Without this the record shows a
            `bounded_time` column among forty others and the analyst reads the
            timestamp as the moment this value changed. It is not: writing any
            value under a key updates the whole key, so the time is a ceiling
            shared by every value under it.
          */}
          {(event.bounded_time || event.boundedTime) && (
            <div className="modal__field" style={{
              borderLeft: '3px solid var(--accent-amber, #f59e0b)',
              paddingLeft: 10, marginBottom: 12
            }}>
              <div className="modal__field-label">Time</div>
              <div className="modal__field-value">
                &le; {formatTime(event.timestamp || event.access_date)}
                {' '}&mdash; the containing registry key&rsquo;s last-write time.
                It is an upper bound on every value under that key, not the
                moment this one changed.
                {event.time_basis ? ` (basis: ${event.time_basis})` : ''}
              </div>
            </div>
          )}
          {loading ? (
             <div className="loading__text">Loading full record from database...</div>
          ) : (
             Object.entries(fullData || {}).map(([k, v]) => (
                <div className="modal__field" key={k}>
                  <div className="modal__field-label">{k}</div>
                  <div className="modal__field-value">
                     {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                  </div>
                </div>
             ))
          )}
        </div>
        
        <div className="modal__footer">
           <button className="modal__btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

export default memo(EventDetailModal);
