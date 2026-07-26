/**
 * ImportedEvidencePanel — chain-of-custody view of ALL imported evidence.
 *
 * Lists every externally-imported item in the case (converted databases AND
 * verbatim documents — third-party reports, e-mail exports, browser-forensics
 * output) with SHA-256 hashes of the source file and the in-case copy, plus a
 * LIVE integrity verdict: the backend re-hashes each file in the background and
 * pushes the verified listing via the imported_evidence_ready signal.
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  initializeBridge, getImportedEvidence, onImportedEvidenceReady, openAddEvidence,
  type ImportedEvidenceEntry,
} from './bridge';
import {
  IconDatabase, IconFileText, IconRefresh, IconShieldCheck, IconAlertTriangle,
  IconLoader, IconLock, IconPlus,
} from './Icons';
import './ImportedEvidencePanel.css';

const fmtBytes = (n: number | null | undefined): string => {
  if (n == null) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
};

const fmtTs = (ts: string): string => {
  if (!ts) return '—';
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
};

const IntegrityBadge: React.FC<{ status?: string }> = ({ status }) => {
  if (status === 'verified') {
    return <span className="iev-badge iev-badge--ok"><IconShieldCheck size={11} /> Verified</span>;
  }
  if (status === 'mismatch') {
    return <span className="iev-badge iev-badge--bad"><IconAlertTriangle size={11} /> HASH MISMATCH</span>;
  }
  if (status === 'missing') {
    return <span className="iev-badge iev-badge--bad"><IconAlertTriangle size={11} /> File missing</span>;
  }
  return <span className="iev-badge iev-badge--wait"><IconLoader size={11} className="iev-spin" /> Verifying…</span>;
};

const HashCell: React.FC<{ hash: string | null; label: string }> = ({ hash, label }) => {
  const [copied, setCopied] = useState(false);
  if (!hash) return <span className="iev-dim">—</span>;
  const copy = () => {
    try {
      navigator.clipboard?.writeText(hash);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard unavailable */ }
  };
  return (
    <button className="iev-hash" onClick={copy} title={`${label} SHA-256 (click to copy):\n${hash}`}>
      <IconLock size={10} /> {hash.slice(0, 12)}…{copied ? ' ✓ copied' : ''}
    </button>
  );
};

const ImportedEvidencePanel: React.FC = () => {
  const [entries, setEntries] = useState<ImportedEvidenceEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const applyPayload = useCallback((json: string | null) => {
    if (!json) { setError('Bridge unavailable — open a case in the Eye first.'); setLoading(false); return; }
    try {
      const res = JSON.parse(json);
      if (!res.success) { setError(res.error || 'Could not load imported evidence.'); setLoading(false); return; }
      setEntries(res.data?.entries || []);
      setError(null);
    } catch (e) {
      setError('Malformed response from the backend.');
    }
    setLoading(false);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    applyPayload(await getImportedEvidence());
  }, [applyPayload]);

  useEffect(() => {
    let off: (() => void) | undefined;
    initializeBridge()
      .then(() => {
        off = onImportedEvidenceReady(applyPayload);  // verified listing (async re-hash)
        refresh();
      })
      .catch(() => { setError('Bridge unavailable — open this window from the Eye.'); setLoading(false); });
    return () => { if (off) off(); };
  }, [refresh, applyPayload]);

  const dbCount = entries.filter(e => e.kind === 'database').length;
  const docCount = entries.filter(e => e.kind === 'document').length;
  const badCount = entries.filter(e => e.integrity === 'mismatch' || e.integrity === 'missing').length;

  return (
    <div className="iev-root">
      <header className="iev-head">
        <div className="iev-title">
          <IconDatabase size={16} /> Imported Evidence
          <span className="iev-sub">chain of custody · SHA-256 verified</span>
        </div>
        <div className="iev-head-right">
          <span className="iev-stat">{dbCount} database{dbCount === 1 ? '' : 's'}</span>
          <span className="iev-stat">{docCount} document{docCount === 1 ? '' : 's'}</span>
          {badCount > 0 && <span className="iev-stat iev-stat--bad">{badCount} integrity issue{badCount === 1 ? '' : 's'}</span>}
          <button
            className="iev-btn iev-btn--primary"
            onClick={openAddEvidence}
            title="Import new evidence — SQLite/CSV/JSON, or a report / e-mail export / browser-tool output (stored verbatim). The list refreshes automatically when the import finishes."
          >
            <IconPlus size={13} /> Add Evidence
          </button>
          <button className="iev-btn" onClick={refresh} disabled={loading} title="Re-list and re-verify all hashes">
            <IconRefresh size={13} /> {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>
      </header>

      {error && <div className="iev-error">{error}</div>}

      {!error && entries.length === 0 && !loading && (
        <div className="iev-empty">
          No imported evidence yet. Use <strong>Add Evidence</strong> in the Eye top bar to import a
          SQLite/CSV/JSON dataset — or a report, e-mail export (.eml/.mbox), or browser-forensics
          output, which is stored verbatim (no conversion) and hashed.
        </div>
      )}

      {entries.length > 0 && (
        <div className="iev-table-wrap">
          <table className="iev-table">
            <thead>
              <tr>
                <th>Evidence</th>
                <th>Kind</th>
                <th>Rows / Size</th>
                <th>Imported</th>
                <th>SHA-256 (in-case)</th>
                <th>SHA-256 (source)</th>
                <th>Integrity</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id} className={e.integrity === 'mismatch' || e.integrity === 'missing' ? 'iev-row--bad' : ''}>
                  <td>
                    <div className="iev-name">
                      {e.kind === 'database' ? <IconDatabase size={13} /> : <IconFileText size={13} />}
                      <span title={`In-case: ${e.dest_path}\nSource: ${e.source_path || '(pre-manifest import)'}`}>{e.name}</span>
                    </div>
                    {e.source_path && <div className="iev-src" title={e.source_path}>{e.source_path}</div>}
                  </td>
                  <td>
                    <span className={`iev-kind iev-kind--${e.kind}`}>
                      {e.kind === 'database' ? (e.source_type || 'DB') : (e.source_type || 'DOC')}
                    </span>
                  </td>
                  <td>{e.kind === 'database' && e.row_count != null ? `${e.row_count.toLocaleString()} rows` : fmtBytes(e.size_bytes)}</td>
                  <td>{fmtTs(e.imported_at)}{e.hashed_late && <span className="iev-dim" title="Imported before hashing existed — hash recorded later"> · late hash</span>}</td>
                  <td><HashCell hash={e.sha256} label="In-case copy" /></td>
                  <td><HashCell hash={e.sha256_source} label="Original source" /></td>
                  <td><IntegrityBadge status={e.integrity} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <footer className="iev-foot">
        Hashes are computed at import time for the original source AND the in-case copy; opening this
        window re-hashes every file and compares. A <strong>HASH MISMATCH</strong> means the in-case
        copy changed after import — investigate before relying on it.
      </footer>
    </div>
  );
};

export default ImportedEvidencePanel;
