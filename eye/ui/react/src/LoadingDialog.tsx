import React, { useEffect, useState } from 'react';
import eyeIcon from './assets/eye_icon.png';
import './LoadingDialog.css';

export interface LoadingStep {
  label: string;
  state: 'pending' | 'active' | 'done' | 'failed';
  note?: string;      // "1.2 s", or the error when it failed
}

interface LoadingDialogProps {
  visible: boolean;
  status?: string;    // Current status line (e.g. "Connecting to bridge...")
  phase?: 'init' | 'processing'; // init = startup, processing = query in-flight
  steps?: LoadingStep[];         // the real steps, when known (no cycling text then)
}

/* Real Eye icon with rotating ring. Memoized (no props) so it is never
   reconciled while the parent chat tree re-renders during streaming. */
const EyeSpinner: React.FC = React.memo(() => (
  <div className="ld-spinner-wrap" aria-hidden="true">
    <div className="ld-ring" />
    <img src={eyeIcon} alt="" className="ld-eye-img" />
  </div>
));

const INIT_STEPS = [
  'Initializing Eye engine...',
  'Connecting to Python bridge...',
  'Loading forensic context...',
  'Ready',
];

const LoadingDialog: React.FC<LoadingDialogProps> = ({
  visible,
  status,
  phase = 'init',
  steps,
}) => {
  const [show, setShow] = useState(visible);
  const [exiting, setExiting] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);

  // Cycle through init steps when in init phase
  useEffect(() => {
    if (!visible || phase !== 'init' || (steps && steps.length)) return;
    const iv = setInterval(() => {
      setStepIndex(i => (i + 1) % (INIT_STEPS.length - 1));
    }, 900);
    return () => clearInterval(iv);
  }, [visible, phase]);

  // Handle show/hide with exit animation
  useEffect(() => {
    if (visible) {
      setShow(true);
      setExiting(false);
      setStepIndex(0);
    } else {
      setExiting(true);
      const t = setTimeout(() => setShow(false), 350);
      return () => clearTimeout(t);
    }
  }, [visible]);

  if (!show) return null;

  const displayStatus = status
    ? status
    : phase === 'init'
    ? INIT_STEPS[stepIndex]
    : 'Processing query...';

  return (
    <div className={`ld-backdrop ${exiting ? 'ld-backdrop--out' : ''}`} role="dialog" aria-modal="true" aria-label="Loading">
      <div className={`ld-card ${exiting ? 'ld-card--out' : ''}`}>
        {/* Header row */}
        <div className="ld-header">
          <EyeSpinner />
          <div className="ld-header-text">
            <span className="ld-title">Eye</span>
            <span className="ld-subtitle">Forensic Assistant</span>
          </div>
        </div>

        {/* Status line (the real steps below replace it when known) */}
        {!(steps && steps.length) && <div className="ld-status">
          <span className="ld-status-dot" />
          <span className="ld-status-text">{displayStatus}</span>
        </div>}

        {/* The real steps, each done / under way / failed, with its time */}
        {steps && steps.length > 0 && (
          <ol className="ld-steps">
            {steps.map((st) => (
              <li key={st.label} className={`ld-step ld-step--${st.state}`}>
                <span className="ld-step-mark" aria-hidden="true" />
                <span className="ld-step-label">{st.label}</span>
                {st.note && <span className="ld-step-note">{st.note}</span>}
              </li>
            ))}
          </ol>
        )}

        {/* Progress bar */}
        <div className="ld-progress-track">
          <div className="ld-progress-bar" />
        </div>
      </div>
    </div>
  );
};

/* Memoized: while a query streams, ChatInterface re-renders constantly but the
   dialog's props (visible/status/phase) stay stable — so its subtree (and its
   compositor-driven animations) are left untouched. */
export default React.memo(LoadingDialog);
