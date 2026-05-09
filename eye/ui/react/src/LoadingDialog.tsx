import React, { useEffect, useState } from 'react';
import eyeIcon from './assets/eye_icon.png';
import './LoadingDialog.css';

interface LoadingDialogProps {
  visible: boolean;
  status?: string;    // Current status line (e.g. "Connecting to bridge...")
  phase?: 'init' | 'processing'; // init = startup, processing = query in-flight
}

/* Real EYE icon with rotating ring */
const EyeSpinner: React.FC = () => (
  <div className="ld-spinner-wrap" aria-hidden="true">
    <div className="ld-ring" />
    <img src={eyeIcon} alt="" className="ld-eye-img" />
  </div>
);

const INIT_STEPS = [
  'Initializing EYE engine...',
  'Connecting to Python bridge...',
  'Loading forensic context...',
  'Ready',
];

const LoadingDialog: React.FC<LoadingDialogProps> = ({
  visible,
  status,
  phase = 'init',
}) => {
  const [show, setShow] = useState(visible);
  const [exiting, setExiting] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);

  // Cycle through init steps when in init phase
  useEffect(() => {
    if (!visible || phase !== 'init') return;
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
            <span className="ld-title">EYE</span>
            <span className="ld-subtitle">Forensic Assistant</span>
          </div>
        </div>

        {/* Status line */}
        <div className="ld-status">
          <span className="ld-status-dot" />
          <span className="ld-status-text">{displayStatus}</span>
        </div>

        {/* Progress bar */}
        <div className="ld-progress-track">
          <div className="ld-progress-bar" />
        </div>
      </div>
    </div>
  );
};

export default LoadingDialog;
