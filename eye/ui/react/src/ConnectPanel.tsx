import React, { useEffect, useState } from 'react';
import type { BackendStatus, DoctorCheck, DoctorFix, DoctorReport } from './bridge';
import { applyBackendFix, onBackendDoctor, runBackendDoctor } from './bridge';
import './ConnectPanel.css';

interface ConnectPanelProps {
  status: BackendStatus | null;
  onOpenSetup: () => void;
  onRetry: () => void;
}

const MARK: Record<DoctorCheck['status'], string> = { ok: '✓', warn: '!', fail: '✕', skip: '–' };

/**
 * Shown before the chat when the Eye has no model backend that answers: what is
 * configured, what went wrong in plain words, each setup check with its fix, and the
 * ways out. While a check runs it says so, with the seconds waited, so a slow provider
 * is never mistaken for a frozen window.
 */
const ConnectPanel: React.FC<ConnectPanelProps> = ({ status, onOpenSetup, onRetry }) => {
  const state = status?.state ?? 'checking';
  const checking = state === 'checking';
  const configured = !!status?.backend;
  const seconds = status?.seconds ?? 0;
  const [full, setFull] = useState<DoctorReport | null>(null);
  const [running, setRunning] = useState(false);
  const [applying, setApplying] = useState<string | null>(null);
  const [note, setNote] = useState('');

  useEffect(() => onBackendDoctor(rep => { setFull(rep); setRunning(false); }), []);
  // A new check makes an older full report stale.
  useEffect(() => { if (checking) setFull(null); }, [checking]);

  const report = full ?? status?.doctor ?? null;
  const title = checking
    ? 'Checking the model backend'
    : configured
    ? 'The Eye cannot use its model yet'
    : 'Connect a model to start';

  const doFix = async (fix: DoctorFix) => {
    if (fix.action === 'open_setup') { onOpenSetup(); return; }
    if (fix.action === 'retry') { onRetry(); return; }
    setApplying(fix.label);
    setNote('');
    const res = await applyBackendFix(fix);
    setApplying(null);
    setNote(res.ok ? `${res.detail} Checking again...` : res.detail || 'The fix could not be applied.');
  };

  const runFull = async () => {
    setRunning(true);
    setNote('');
    if (!(await runBackendDoctor())) {
      setRunning(false);
      setNote('This version of the Eye cannot run the full check.');
    }
  };

  return (
    <div className="cp-overlay" role="dialog" aria-modal="false" aria-label={title}>
      <div className={`cp-card cp-card--${state}`}>
        <div className="cp-head">
          <span className={`cp-dot cp-dot--${state}`} aria-hidden="true" />
          <h2 className="cp-title">{title}</h2>
        </div>

        <dl className="cp-facts">
          <dt>Backend</dt>
          <dd>{status?.backend ?? 'not set up'}</dd>
          <dt>Model</dt>
          <dd>{status?.model ?? '-'}</dd>
          {(checking || seconds > 0) && (
            <>
              <dt>{checking ? 'Waiting' : 'Took'}</dt>
              <dd>{seconds.toFixed(0)} s</dd>
            </>
          )}
        </dl>

        {checking ? (
          <p className="cp-detail">
            {seconds >= 10
              ? `Still waiting for an answer after ${seconds.toFixed(0)} s - the provider or the local model service is slow to respond.`
              : 'Asking the model backend whether it answers...'}
          </p>
        ) : !report ? (
          <p className="cp-detail cp-detail--error">
            {status?.detail || 'The model backend did not answer.'}
          </p>
        ) : null}

        {!checking && report && report.checks.length > 0 && (
          <ul className="cp-checks" aria-label="Setup checks">
            {report.checks.map(c => (
              <li key={c.id} className={`cp-check cp-check--${c.status}`}>
                <span className="cp-check-mark" aria-label={c.status}>{MARK[c.status]}</span>
                <div className="cp-check-body">
                  <div className="cp-check-title">{c.title}</div>
                  <div className="cp-check-detail">{c.detail}</div>
                </div>
                {c.fix && c.status !== 'ok' && (
                  <button
                    className={`cp-btn cp-btn--small${c.status === 'fail' ? ' cp-btn--primary' : ''}`}
                    onClick={() => doFix(c.fix as DoctorFix)}
                    disabled={applying !== null}
                  >
                    {applying === c.fix.label ? 'Applying...' : c.fix.label}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}

        {note && <p className="cp-note">{note}</p>}

        <p className="cp-hint">
          The Eye needs a language model to answer questions: a cloud API key, a local server,
          or a command-line agent. It checks the setup before every session and says what to fix.
        </p>

        <div className="cp-actions">
          <button className="cp-btn" onClick={runFull} disabled={checking || running}>
            {running ? 'Checking everything...' : 'Check everything'}
          </button>
          <button className="cp-btn" onClick={onRetry} disabled={checking}>
            {checking ? 'Checking...' : 'Retry'}
          </button>
          <button className="cp-btn cp-btn--primary" onClick={onOpenSetup}>Open setup</button>
        </div>
      </div>
    </div>
  );
};

export default ConnectPanel;
