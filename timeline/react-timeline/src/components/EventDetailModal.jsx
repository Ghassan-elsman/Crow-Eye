/**
 * EventDetailModal — Full-screen modal for displaying all raw database fields.
 */
import { memo, useEffect, useState } from 'react';
import { formatTime } from '../utils/formatters';

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
          <div className="modal__badge" style={{ background: 'var(--accent-blue)' }}>
            🏷️ Event Record
          </div>
          <button className="modal__close" onClick={onClose}>×</button>
        </div>
        
        <div className="modal__body">
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
