/**
 * ProtocolCompliancePanel
 *
 * GEP (Ghassan Elsman Protocol) compliance dashboard.  Shows the live status
 * of all 8 protocol rules with a colour-coded badge (PASS / PARTIAL / FAIL /
 * N-A), the human-readable diagnostic detail returned by the bridge, plus a
 * "Refresh" button (re-fetches) and an "Export Audit JSON" button (writes
 * audit_trail.json into the active case's EYE_Logs directory and shows a
 * toast).
 *
 * Wires to:
 *   - bridge.ts -> getGepComplianceStatus()  (Python: eye_bridge.get_gep_compliance_status)
 *   - bridge.ts -> exportAuditTrail()        (Python: eye_bridge.export_audit_trail)
 */
import React, { useEffect, useState, useCallback, useMemo, useDeferredValue, memo } from 'react';
import {
  initializeBridge,
  getGepComplianceStatus,
  exportAuditTrail,
  getActivityAudit,
  getStepHistory,
  getDialogueHistory,
  getGepTurns,
  getReasoningTurns,
  getPayloadSeals,
  getTruncationEvents,
  getPayloadCutDetails,
  getDroppedPayloadFull,
  getSealedPayloadFull,
  onNarrativeMapUpdated,
  focusNarrativeMap,
  type GepRuleStatus,
  type GepPrinciple,
  type ActivityAuditEntry,
  type AuditEntryType,
  type StepHistoryGroup,
  type DialogueConversation,
  type GepTurn,
  type ReasoningTurn,
  type PayloadSeal,
  type TruncationEvent,
  type FlatCutDetail,
} from './bridge';
import EyeDialogue from './EyeDialogue';
import { IconRefresh, IconDownload } from './Icons';

type Toast = { message: string; type: 'success' | 'error' | 'info' } | null;

const STATUS_STYLE: Record<string, { bg: string; fg: string; border: string }> = {
  PASS:    { bg: 'rgba(16,185,129,0.12)',  fg: '#10b981', border: 'rgba(16,185,129,0.45)' },
  PARTIAL: { bg: 'rgba(245,158,11,0.12)',  fg: '#f59e0b', border: 'rgba(245,158,11,0.45)' },
  FAIL:    { bg: 'rgba(244,63,94,0.14)',   fg: '#f43f5e', border: 'rgba(244,63,94,0.5)'  },
  'N-A':   { bg: 'rgba(148,163,184,0.12)', fg: '#94a3b8', border: 'rgba(148,163,184,0.4)' },
  INFO:    { bg: 'rgba(59,130,246,0.12)',  fg: '#3b82f6', border: 'rgba(59,130,246,0.45)' },
};

// Pipeline-step status ("active" | "done" | "error") -> the same colour
// vocabulary used by the GEP badges so the panel reads consistently.
const STEP_STATUS_STYLE = (status: string) => {
  if (status === 'done') return { ...STATUS_STYLE.PASS, label: 'DONE' };
  if (status === 'error') return { ...STATUS_STYLE.FAIL, label: 'ERROR' };
  if (status === 'active') return { ...STATUS_STYLE.PARTIAL, label: 'RUNNING' };
  return { ...STATUS_STYLE['N-A'], label: (status || 'STEP').toUpperCase() };
};

// Chain-of-custody audit action -> badge colour.
const AUDIT_ACTION_STYLE = (action: string) => {
  if (action === 'PRESERVED' || action === 'PINNED') return STATUS_STYLE.PASS;
  if (action === 'SUMMARIZED' || action === 'TRUNCATED' || action === 'BUDGET_REDUCED'
      || action === 'RETRY') return STATUS_STYLE.PARTIAL;
  if (action === 'REFUSED_OVERFLOW' || action === 'SEAL_FAILED') return STATUS_STYLE.FAIL;
  // Automatic resilience actions (v0.11.2): question segmentation + auto map-reduce.
  if (action === 'SEGMENTED' || action === 'AUTO_MAPREDUCE') return STATUS_STYLE.INFO;
  return STATUS_STYLE['N-A'];
};

// Per-step GEP turn records use internal command strings as their `query`.
// Map those to human labels for the Compliance list header; ordinary questions
// (and refusal / overflow-recovery turns, which carry the real user query) fall
// through unchanged. Display-only — the persisted record keeps the raw query.
const GEP_TURN_LABEL: Record<string, string> = {
  initialize_case_report: 'Automated Triage',
  analyze_case_context: 'Context Analysis',
};
const gepTurnLabel = (q: string) => GEP_TURN_LABEL[q] || q || '(question)';

const RULE_BLURB: Record<number | string, string> = {
  0: 'Initial blueprinting of case context injected into the system prompt.',
  1: 'Validates backend connectivity before each query.',
  2: 'Auto-tags raw forensic context (hashes, IPs, timestamps) into history.',
  3: 'Append-only audit log of preservation + truncation events.',
  4: 'Deterministic content-hashed IDs prevent silent record alteration.',
  5: 'Pinned / evidence-flagged messages excluded from AI summarization.',
  6: 'Tool names + iteration counts injected into LLM-visible history.',
  7: 'Structured JSON audit trail for automated compliance review.',
  // Write-side rules — apply to the four correlation_create_* and
  // correlation_edit_* tools.
  8: 'Every Wing or Mapping EYE authors must carry a non-empty forensic reason.',
  9: 'Every authored artifact must cite at least one database:table:rowid evidence ref (soft-warning on unresolvable refs).',
  10: 'Every EYE-authored artifact carries a populated EyeAuthorship block (model, time, reason, evidence, edit history).',
};

/**
 * Plain-English guidance per rule + status. Tells the investigator *why*
 * the rule is in its current state and what to do if it's not PASS.
 * Keys: rule id → { PASS | PARTIAL | FAIL | 'N-A' → guidance string }.
 */
const RULE_GUIDANCE: Record<number | string, Partial<Record<string, string>>> = {
  0: {
    PASS: 'Case context is loaded and injected into every prompt the EYE sends.',
    FAIL: 'No case context is loaded. Open / create a case in Crow-Eye so the EYE can ground its answers in real evidence.',
  },
  1: {
    PASS: 'The configured AI backend responded to the last connectivity ping.',
    FAIL: 'The EYE cannot reach its AI backend. Check the API key, network, or local model service in Settings.',
    PARTIAL: 'The backend answered, but with a degraded signal. Verify the model service is healthy.',
  },
  2: {
    PASS: 'Recent messages carry inline <evidence anchor="…"> tags — raw artifacts travel with the text and survive summarization.',
    PARTIAL: 'Evidence is flagged in metadata but no in-content anchor tags were found in the last 25 messages. Confirm the evidence detector is enabled.',
    'N-A': 'The session has not produced messages containing detectable evidence yet. Ask the EYE a forensic question to populate this rule.',
  },
  3: {
    PASS: 'Every preservation, summarization, and pin event is appended to EYE_Logs/truncation_audit.log.',
    PARTIAL: 'The audit log file exists but is empty. The first auditable event will populate it.',
    FAIL: 'The audit log was not found. Confirm EYE_Logs is writable for the active case directory.',
  },
  4: {
    PASS: 'All recent message IDs are 16-char SHA-chained — any tampering would break the chain on the next message.',
    PARTIAL: 'Some recent messages use the legacy ID format. They will be re-hashed on the next history rewrite; new messages already use SHA.',
    FAIL: 'No message IDs match the SHA-16 chain format. Restart the EYE so history_manager._generate_message_id runs on new turns.',
    'N-A': 'No messages have been added to history yet.',
  },
  5: {
    PASS: 'One or more messages are pinned / evidence-preserved and will be skipped by the summarizer.',
    FAIL: 'The pin handler is missing from history_manager. This is a build issue — reinstall / restart the EYE.',
    'N-A': 'The pin handler is present but no messages have been pinned yet. Use the pin icon on a chat bubble to lock it.',
  },
  6: {
    PASS: 'The most recent tool-result message starts with a [Tool i/N: name, iteration X] header, so the LLM can see exactly which tool produced which evidence.',
    PARTIAL: 'Tool-result messages exist but the trace header is only in metadata. Restart the EYE so the next iteration uses the in-content header.',
    'N-A': 'The EYE has not run any tools yet in this session.',
  },
  7: {
    PASS: 'EYE_Logs/audit_trail.json is up to date — auto-exported on every preservation and summarization event.',
    FAIL: 'audit_trail.json has not been written yet. It is created automatically when the EYE preserves evidence or summarizes history. You can also force one with Export Audit JSON.',
  },
  8: {
    PASS: 'Every EYE-authored Wing and Semantic Mapping in this case carries a non-empty forensic reason. Hover an item in the Wings or Mappings panel to see its full justification.',
    FAIL: 'One or more EYE-authored artifacts lack a populated reason — handler bug; expected to be impossible. Review the latest audit-trail entries.',
    'N-A': 'EYE has not authored any Wings or Mappings in this case yet. The rule is dormant until the first correlation_create_* call.',
  },
  9: {
    PASS: 'Every EYE-authored artifact in this case has fully resolved evidence references — each cited database:table:rowid still resolves to a live row.',
    PARTIAL: 'At least one EYE-authored artifact has unresolved evidence refs (soft-warning model). The artifact was still persisted; refs are recorded in eye_authorship.unresolved_evidence_refs. Common causes: row deleted post-write, DB locked at write time, archived case.',
    FAIL: 'One or more EYE-authored artifacts cite no evidence at all — handler bug; should be impossible. Review the audit trail.',
    'N-A': 'No EYE-authored artifacts yet in this case.',
  },
  10: {
    PASS: 'Every EYE-authored artifact carries a complete EyeAuthorship block (model name, timestamp, reason, evidence, GEP per-rule status). Analysts can trace each artifact back to its EYE conversation.',
    FAIL: 'One or more EYE-authored artifacts have an incomplete EyeAuthorship block — likely a partially-written file. Re-run the EYE turn that produced it, or delete it and re-author.',
    'N-A': 'No EYE-authored artifacts yet in this case.',
  },
};

const TYPE_STYLE: Record<AuditEntryType, { label: string; color: string; bg: string; border: string }> = {
  user_query:         { label: 'USER QUERY',    color: '#60a5fa', bg: 'rgba(96,165,250,0.10)',  border: 'rgba(96,165,250,0.40)'  },
  assistant_response: { label: 'EYE RESPONSE',  color: '#e2e8f0', bg: 'rgba(226,232,240,0.08)', border: 'rgba(226,232,240,0.25)' },
  tool_call:          { label: 'QUERY RUN',     color: '#a78bfa', bg: 'rgba(167,139,250,0.12)', border: 'rgba(167,139,250,0.45)' },
  tool_result:        { label: 'EVIDENCE',      color: '#10b981', bg: 'rgba(16,185,129,0.10)',  border: 'rgba(16,185,129,0.45)'  },
  report_added:       { label: 'REPORT +',      color: '#34d399', bg: 'rgba(52,211,153,0.12)',  border: 'rgba(52,211,153,0.45)'  },
  report_edited:      { label: 'REPORT ✎',      color: '#f59e0b', bg: 'rgba(245,158,11,0.12)',  border: 'rgba(245,158,11,0.45)'  },
  report_deleted:     { label: 'REPORT −',      color: '#f43f5e', bg: 'rgba(244,63,94,0.12)',   border: 'rgba(244,63,94,0.45)'   },
  report_other:       { label: 'REPORT',        color: '#94a3b8', bg: 'rgba(148,163,184,0.08)', border: 'rgba(148,163,184,0.30)' },
  narrative_map:      { label: 'MAP',           color: '#a855f7', bg: 'rgba(168,85,247,0.12)',  border: 'rgba(168,85,247,0.45)'  },
  evidence_import:    { label: 'IMPORT',        color: '#67e8f9', bg: 'rgba(103,232,249,0.10)', border: 'rgba(103,232,249,0.45)' },
};

const formatTs = (ts: string): string => {
  if (!ts) return '—';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString();
};

// Toggle a key in a Set-based "expanded groups" state. Module-level so the
// per-section callbacks built from it can be made referentially stable.
const toggleInSet = (setter: React.Dispatch<React.SetStateAction<Set<string>>>) => (k: string) =>
  setter(prev => { const n = new Set(prev); n.has(k) ? n.delete(k) : n.add(k); return n; });

/* ── Group-by-question helpers ───────────────────────────────────────────
 * Several chain-of-custody sections (seals, cuts, events, steps) emit many
 * records per question. These helpers fold them into collapsible groups keyed
 * by the investigator question so the analyst can navigate behavior per
 * question and search for a specific one. */
type QGroup<T> = { key: string; query: string; items: T[]; latestTs: string };

function groupByQuestion<T>(
  items: T[],
  getQuery: (t: T) => string,
  getTs: (t: T) => string,
): QGroup<T>[] {
  const map = new Map<string, QGroup<T>>();
  for (const it of items) {
    const q = ((getQuery(it) || '').trim()) || '(unattributed)';
    let g = map.get(q);
    if (!g) { g = { key: q, query: q, items: [], latestTs: '' }; map.set(q, g); }
    g.items.push(it);
    const ts = getTs(it) || '';
    if (ts > g.latestTs) g.latestTs = ts;
  }
  const groups = Array.from(map.values());
  for (const g of groups) g.items.sort((a, b) => (getTs(b) || '').localeCompare(getTs(a) || ''));
  groups.sort((a, b) => (b.latestTs || '').localeCompare(a.latestTs || ''));
  return groups;
}

function QuestionGroupsInner<T>(props: {
  groups: QGroup<T>[];
  openKeys: Set<string>;
  onToggle: (k: string) => void;
  search: string;
  setSearch: (s: string) => void;
  placeholder: string;
  unit: string;
  emptyText: string;
  renderItem: (item: T, idx: number) => React.ReactNode;
}): React.ReactElement {
  const { groups, openKeys, onToggle, search, setSearch, placeholder, unit, emptyText, renderItem } = props;
  // Defer filtering so the input stays responsive while large group lists filter.
  const deferredSearch = useDeferredValue(search);
  const needle = deferredSearch.trim().toLowerCase();
  const filtered = useMemo(
    () => (needle ? groups.filter(g => g.query.toLowerCase().includes(needle)) : groups),
    [groups, needle],
  );
  // Window the group list too, so cases with very many questions don't mount
  // hundreds of group headers at once.
  const groupsPaged = usePaged(filtered);
  return (
    <div style={styles.timeline}>
      <input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder={placeholder}
        style={qStyles.search}
      />
      {filtered.length === 0 && <div style={styles.timelineEmpty}>{emptyText}</div>}
      {groupsPaged.visible.map((g) => {
        const open = openKeys.has(g.key);
        return (
          <div key={g.key} style={qStyles.groupWrap}>
            <button onClick={() => onToggle(g.key)} style={qStyles.groupHeader} title={open ? 'Collapse' : 'Expand'}>
              <span style={qStyles.caret}>{open ? '▾' : '▸'}</span>
              <span style={qStyles.query}>{g.query}</span>
              <span style={styles.timelineTools}>{g.items.length} {unit}</span>
              <span style={styles.timelineTs}>{formatTs(g.latestTs)}</span>
            </button>
            {open && <OpenGroupBody items={g.items} unit={unit} renderItem={renderItem} />}
          </div>
        );
      })}
      <ShowMore paged={groupsPaged} unit="questions" />
    </div>
  );
}
// memo so a section only re-renders when ITS props change (its groups/search/
// openKeys/renderItem) — interacting with one section no longer re-renders the
// others. The cast restores the generic call signature memo() erases.
const QuestionGroups = memo(QuestionGroupsInner) as unknown as typeof QuestionGroupsInner;

// Body of an expanded question group — windows its items so opening a group
// with thousands of seals/events/steps only mounts a page at a time.
function OpenGroupBodyInner<T>(props: {
  items: T[];
  unit: string;
  renderItem: (item: T, idx: number) => React.ReactNode;
}): React.ReactElement {
  const { items, unit, renderItem } = props;
  const paged = usePaged(items);
  return (
    <div style={{ padding: '2px 0 6px 10px' }}>
      {paged.visible.map((it, i) => renderItem(it, i))}
      <ShowMore paged={paged} unit={unit} />
    </div>
  );
}
const OpenGroupBody = memo(OpenGroupBodyInner) as unknown as typeof OpenGroupBodyInner;

// ── Windowed rendering: render only a page of large lists ("load what we
//    need", like the Data Viewer's virtual table) so the panel stays snappy
//    instead of mounting thousands of rows at once. ──────────────────────────
const PAGE_SIZE = 25;

function usePaged<T>(items: T[] | null | undefined, pageSize = PAGE_SIZE) {
  const [shown, setShown] = useState(pageSize);
  // Reset to the first page whenever the underlying list is replaced (a fetch).
  useEffect(() => { setShown(pageSize); }, [items, pageSize]);
  const list = items || [];
  const total = list.length;
  const visibleCount = Math.min(shown, total);
  return {
    visible: shown >= total ? list : list.slice(0, shown),
    total,
    visibleCount,
    hasMore: total > visibleCount,
    showMore: () => setShown((s) => s + pageSize),
    showAll: () => setShown(total),
  };
}

const _showMoreBtn: React.CSSProperties = {
  background: 'rgba(99,102,241,0.15)', color: '#c7d2fe',
  border: '1px solid rgba(99,102,241,0.4)', borderRadius: '6px',
  padding: '4px 12px', fontSize: '12px', cursor: 'pointer',
};

const ShowMore: React.FC<{
  paged: { total: number; visibleCount: number; hasMore: boolean; showMore: () => void; showAll: () => void };
  unit?: string;
}> = ({ paged, unit = 'rows' }) => {
  if (!paged.hasMore) return null;
  return (
    <div style={{ display: 'flex', gap: '10px', alignItems: 'center', padding: '8px 4px', color: '#94a3b8', fontSize: '12.5px' }}>
      <span>Showing {paged.visibleCount} of {paged.total} {unit}</span>
      <button style={_showMoreBtn} onClick={paged.showMore}>Show more</button>
      <button style={_showMoreBtn} onClick={paged.showAll}>Show all</button>
    </div>
  );
};

const qStyles: Record<string, React.CSSProperties> = {
  search: {
    width: '100%', boxSizing: 'border-box', margin: '0 0 10px',
    padding: '8px 12px', fontSize: 13,
    background: 'rgba(255,255,255,0.04)', color: '#e5e7eb',
    border: '1px solid rgba(255,255,255,0.12)', borderRadius: 8,
    fontFamily: "'Inter','Segoe UI',system-ui,sans-serif",
  },
  groupWrap: {
    border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8,
    marginBottom: 8, background: 'rgba(255,255,255,0.02)',
  },
  groupHeader: {
    display: 'flex', alignItems: 'center', gap: 12, width: '100%',
    padding: '10px 14px', background: 'transparent', border: 'none',
    cursor: 'pointer', color: '#e5e7eb', textAlign: 'left',
  },
  caret: { color: '#64748b', minWidth: 12 },
  query: {
    flex: 1, fontWeight: 700, fontSize: 13, color: '#e6edf3',
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
};

const ARTIFACT_STYLES: Record<string, { bg: string; fg: string }> = {
  MFT_RECORD:  { bg: 'rgba(16,185,129,0.12)', fg: '#10b981' },
  FILE_OFFSET: { bg: 'rgba(59,130,246,0.12)',  fg: '#3b82f6' },
  EVENT_ID:    { bg: 'rgba(245,158,11,0.12)',  fg: '#f59e0b' },
  DB_ROW:      { bg: 'rgba(139,92,246,0.12)',  fg: '#8b5cf6' },
  NETWORK_IP:  { bg: 'rgba(236,72,153,0.12)',  fg: '#ec4899' },
  REGISTRY_KEY:{ bg: 'rgba(20,184,166,0.12)',  fg: '#14b8a6' },
  PATH:        { bg: 'rgba(20,184,166,0.12)',  fg: '#14b8a6' },
  SHA1_HASH:   { bg: 'rgba(6,182,212,0.12)',   fg: '#06b6d4' },
  USN_SEQ:     { bg: 'rgba(99,102,241,0.12)',  fg: '#6366f1' },
  APP_ID:      { bg: 'rgba(217,70,239,0.12)',  fg: '#d946ef' },
  DEFAULT:     { bg: 'rgba(148,163,184,0.12)', fg: '#94a3b8' },
};

// Module-level + memoized: hoisted out of the panel so it is not recreated on
// every render (a perf hot spot — it's rendered in many expandable rows).
const ForensicDiff = memo(function ForensicDiff(props: {
  processed?: string;
  dropped?: string;
  processedOffsets?: any[];
  droppedOffsets?: any[];
  action?: string;
  onCopyOffset: (offset: number, label: string) => void;
}) {
  const { processed, dropped, processedOffsets, droppedOffsets, action, onCopyOffset } = props;

  const renderBadges = (artifacts: any[]) => (artifacts || []).map((o, i) => {
    const style = ARTIFACT_STYLES[o.type] || ARTIFACT_STYLES.DEFAULT;
    const val = o.computed_file_offset || o.record_number || o.event_id || o.row_id || o.ip || o.path;
    return (
      <span
        key={i}
        style={{ ...styles.offsetBadge, background: style.bg, color: style.fg, border: `1px solid ${style.fg}44` }}
        onClick={() => onCopyOffset(val, o.type || 'Artifact')}
        title={`Click to copy: ${o.label || val}`}
      >
        {o.label || val}
      </span>
    );
  });

  // For a SUMMARIZED message the "dropped" side is the ORIGINAL message and the
  // "processed" side is the SUMMARY the model saw — relabel + show original first.
  const isSummary = action === 'SUMMARIZED';
  const keptLabel = isSummary ? '✓ SUMMARIZED VERSION (AI-VISIBLE)' : '✓ PROCESSED (AI-VISIBLE)';
  const dropLabel = isSummary ? '↺ ORIGINAL MESSAGE (REPLACED BY SUMMARY)' : '⚠ DROPPED (TRUNCATED)';
  const dropColor = isSummary ? '#f59e0b' : '#f43f5e';
  const dropBg = isSummary ? 'rgba(245,158,11,0.05)' : 'rgba(244,63,94,0.05)';

  const keptBlock = processed ? (
    <div key="kept">
      <div style={{ ...styles.diffHeader, color: '#10b981', background: 'rgba(16,185,129,0.05)' }}>
        <span>{keptLabel}</span>
        <span>{processed.length} chars</span>
      </div>
      <div style={{ ...styles.diffContent, ...styles.keptText }}>
        {processed}
        {(processedOffsets || []).length > 0 && (
          <div style={{ marginTop: '8px', borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '6px' }}>
            <div style={{ fontSize: '10px', color: '#64748b', marginBottom: '4px' }}>Forensic Markers:</div>
            {renderBadges(processedOffsets || [])}
          </div>
        )}
      </div>
    </div>
  ) : null;

  const dropBlock = dropped ? (
    <div key="drop" style={{ borderTop: '1px solid rgba(255,255,255,0.08)' }}>
      <div style={{ ...styles.diffHeader, color: dropColor, background: dropBg }}>
        <span>{dropLabel}</span>
        <span>{dropped.length} chars</span>
      </div>
      <div style={{ ...styles.diffContent, ...styles.droppedText }}>
        {dropped}
        {(droppedOffsets || []).length > 0 && (
          <div style={{ marginTop: '8px', borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '6px' }}>
            <div style={{ fontSize: '10px', color: '#64748b', marginBottom: '4px' }}>Forensic Markers:</div>
            {renderBadges(droppedOffsets || [])}
          </div>
        )}
      </div>
    </div>
  ) : null;

  return (
    <div style={styles.diffContainer}>
      {isSummary ? <>{dropBlock}{keptBlock}</> : <>{keptBlock}{dropBlock}</>}
    </div>
  );
});

const ProtocolCompliancePanel: React.FC = () => {
  const [rules, setRules] = useState<GepRuleStatus[] | null>(null);
  const [gepPrinciples, setGepPrinciples] = useState<GepPrinciple[] | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<Toast>(null);
  const [exporting, setExporting] = useState<boolean>(false);

  // Activity Audit window
  const [audit, setAudit] = useState<ActivityAuditEntry[] | null>(null);
  const [auditLoading, setAuditLoading] = useState<boolean>(true);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [auditFilter, setAuditFilter] = useState<'all' | 'queries' | 'evidence' | 'report' | 'map'>('all');
  const [rulesExpanded, setRulesExpanded] = useState<boolean>(false);

  // Per-step execution history (grouped). Shown expanded by default so the
  // investigator sees each step's run-by-run timestamps without a click;
  // the GEP rules above stay collapsed by default.
  const [steps, setSteps] = useState<StepHistoryGroup[] | null>(null);
  const [stepsLoading, setStepsLoading] = useState<boolean>(true);
  const [stepsError, setStepsError] = useState<string | null>(null);
  const [stepsExpanded, setStepsExpanded] = useState<boolean>(true);
  const [openStepKey, setOpenStepKey] = useState<string | null>(null);
  // Execution Steps grouping: by investigator question (default) or by step type.
  const [stepsGroupMode, setStepsGroupMode] = useState<'question' | 'step'>('question');
  const [stepGroupsOpen, setStepGroupsOpen] = useState<Set<string>>(new Set());
  const [stepSearch, setStepSearch] = useState<string>('');

  // Full Eye<->LLM conversation (prompts, reasoning, tool calls + results),
  // grouped by the investigator question that produced it.
  const [conversations, setConversations] = useState<DialogueConversation[] | null>(null);
  const [convLoading, setConvLoading] = useState<boolean>(false); // lazy: loads on first expand
  const [convError, setConvError] = useState<string | null>(null);
  const [convExpanded, setConvExpanded] = useState<boolean>(false);
  const [openConvIdx, setOpenConvIdx] = useState<number | null>(null);

  // Per-answer behavioral GEP compliance (did each answer follow the protocol).
  const [gepTurns, setGepTurns] = useState<GepTurn[] | null>(null);
  const [gepTurnsLoading, setGepTurnsLoading] = useState<boolean>(true);
  const [gepTurnsError, setGepTurnsError] = useState<string | null>(null);
  const [gepTurnsExpanded, setGepTurnsExpanded] = useState<boolean>(true);
  const [openTurnIdx, setOpenTurnIdx] = useState<number | null>(null);

  // Per-answer reasoning traces (why each sub-question + why each conclusion).
  const [reasoningTurns, setReasoningTurns] = useState<ReasoningTurn[] | null>(null);
  const [reasoningLoading, setReasoningLoading] = useState<boolean>(false);
  const [reasoningError, setReasoningError] = useState<string | null>(null);
  const [reasoningExpanded, setReasoningExpanded] = useState<boolean>(false);
  const [openReasoningIdx, setOpenReasoningIdx] = useState<number | null>(null);

  // Chain-of-custody Evidence Seals (exact bytes the model saw).
  const [seals, setSeals] = useState<PayloadSeal[] | null>(null);
  const [sealsChainValid, setSealsChainValid] = useState<boolean>(true);
  const [sealsLoading, setSealsLoading] = useState<boolean>(false); // lazy: loads on first expand
  const [sealsError, setSealsError] = useState<string | null>(null);
  const [sealsExpanded, setSealsExpanded] = useState<boolean>(false);
  const [openSealKey, setOpenSealKey] = useState<string | null>(null);
  const [sealGroupsOpen, setSealGroupsOpen] = useState<Set<string>>(new Set());
  const [sealSearch, setSealSearch] = useState<string>('');

  // Chain-of-custody audit events (preserve / summarize / truncate / refuse).
  const [events, setEvents] = useState<TruncationEvent[] | null>(null);
  const [eventCounts, setEventCounts] = useState<Record<string, number>>({});
  const [eventsLoading, setEventsLoading] = useState<boolean>(false); // lazy: loads on first expand
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [eventsExpanded, setEventsExpanded] = useState<boolean>(false);
  const [openEventKey, setOpenEventKey] = useState<string | null>(null);
  const [eventGroupsOpen, setEventGroupsOpen] = useState<Set<string>>(new Set());
  const [eventSearch, setEventSearch] = useState<string>('');

  // Processed vs Dropped Payload — every per-payload cut (summarize / drop /
  // tool-output cap) with its byte-range, offsets, and recoverable full bytes.
  const [cuts, setCuts] = useState<FlatCutDetail[] | null>(null);
  const [cutsLoading, setCutsLoading] = useState<boolean>(false); // lazy: loads on first expand
  const [cutsError, setCutsError] = useState<string | null>(null);
  const [cutsExpanded, setCutsExpanded] = useState<boolean>(false);
  const [openCutKey, setOpenCutKey] = useState<string | null>(null);
  const [cutGroupsOpen, setCutGroupsOpen] = useState<Set<string>>(new Set());
  const [cutSearch, setCutSearch] = useState<string>('');
  // Full sidecar bytes fetched on demand, keyed by content SHA-256.
  const [fullPayloads, setFullPayloads] = useState<Record<string, string>>({});

  // Stable per-section group togglers so a memoized section isn't invalidated
  // when another section's state changes (the setters are stable → [] is safe).
  const toggleSealGroups  = useCallback((k: string) => toggleInSet(setSealGroupsOpen)(k), []);
  const toggleCutGroups   = useCallback((k: string) => toggleInSet(setCutGroupsOpen)(k), []);
  const toggleEventGroups = useCallback((k: string) => toggleInSet(setEventGroupsOpen)(k), []);
  const toggleStepGroups  = useCallback((k: string) => toggleInSet(setStepGroupsOpen)(k), []);

  // Context Events carry no query; attribute each to the question whose seal
  // window contains it (latest seal at/before the event time). Memoized so it
  // recomputes only when seals change.
  const sealTimeline = useMemo(
    () => (seals || [])
      .filter(s => s.timestamp)
      .map(s => ({ ts: s.timestamp, query: s.query || '' }))
      .sort((a, b) => a.ts.localeCompare(b.ts)),
    [seals],
  );
  const eventQueryFor = useCallback((ts: string): string => {
    let q = '';
    if (!ts) return q;
    for (const e of sealTimeline) { if (e.ts <= ts) q = e.query; else break; }
    return q || 'Earlier / session start';
  }, [sealTimeline]);

  // Memoized question groupings — recompute only when their source data changes,
  // NOT on every keystroke/expand (search filtering is cheap, inside QuestionGroups).
  const sealGroups = useMemo(
    () => groupByQuestion(seals || [], (s) => s.query, (s) => s.timestamp), [seals]);
  const cutGroups = useMemo(
    () => groupByQuestion(cuts || [], (c) => c.query || c.phase || '', (c) => c.timestamp || ''), [cuts]);
  const eventGroups = useMemo(
    () => groupByQuestion(events || [], (ev) => eventQueryFor(ev.timestamp), (ev) => ev.timestamp),
    [events, eventQueryFor]);
  const stepQuestionGroups = useMemo(
    () => groupByQuestion(
      (steps || []).flatMap((g) => g.runs.map((r) => ({ ...r, stepType: g.type, stepLabel: g.label }))),
      (r: any) => r.query, (r: any) => r.timestamp,
    ),
    [steps]);

  const showToast = useCallback((msg: string, t: 'success' | 'error' | 'info' = 'info') => {
    setToast({ message: msg, type: t });
    setTimeout(() => setToast(null), 4000);
  }, []);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getGepComplianceStatus();
      if (res.success && res.data) {
        setRules(res.data.rules);
        setGepPrinciples(res.data.gep_principles || null);
      } else {
        setError(res.error || 'Unknown bridge error');
        setRules(null);
        setGepPrinciples(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setRules(null);
      setGepPrinciples(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchAudit = useCallback(async () => {
    setAuditLoading(true);
    setAuditError(null);
    try {
      const res = await getActivityAudit();
      if (res.success && res.data) {
        setAudit(res.data.entries);
      } else {
        setAuditError(res.error || 'Unable to load activity audit');
        setAudit([]);
      }
    } catch (e) {
      setAuditError(e instanceof Error ? e.message : String(e));
      setAudit([]);
    } finally {
      setAuditLoading(false);
    }
  }, []);

  // Live-refresh the activity log when the Narrative Map changes (Eye or
  // investigator edit), so sealed map events appear without a manual refresh.
  useEffect(() => {
    const off = onNarrativeMapUpdated(() => { if (audit !== null) fetchAudit(); });
    return off;
  }, [audit, fetchAudit]);

  const fetchSteps = useCallback(async () => {
    setStepsLoading(true);
    setStepsError(null);
    try {
      const res = await getStepHistory();
      if (res.success && res.data) {
        setSteps(res.data.steps);
      } else {
        setStepsError(res.error || 'Unable to load step history');
        setSteps([]);
      }
    } catch (e) {
      setStepsError(e instanceof Error ? e.message : String(e));
      setSteps([]);
    } finally {
      setStepsLoading(false);
    }
  }, []);

  const fetchConversations = useCallback(async () => {
    setConvLoading(true);
    setConvError(null);
    try {
      const res = await getDialogueHistory();
      if (res.success && res.data) {
        setConversations(res.data.conversations);
      } else {
        setConvError(res.error || 'Unable to load Eye ↔ LLM conversation');
        setConversations([]);
      }
    } catch (e) {
      setConvError(e instanceof Error ? e.message : String(e));
      setConversations([]);
    } finally {
      setConvLoading(false);
    }
  }, []);

  const fetchGepTurns = useCallback(async () => {
    setGepTurnsLoading(true);
    setGepTurnsError(null);
    try {
      const res = await getGepTurns();
      if (res.success && res.data) {
        setGepTurns(res.data.turns);
      } else {
        setGepTurnsError(res.error || 'Unable to load per-answer GEP compliance');
        setGepTurns([]);
      }
    } catch (e) {
      setGepTurnsError(e instanceof Error ? e.message : String(e));
      setGepTurns([]);
    } finally {
      setGepTurnsLoading(false);
    }
  }, []);

  const fetchReasoning = useCallback(async () => {
    setReasoningLoading(true);
    setReasoningError(null);
    try {
      const res = await getReasoningTurns();
      if (res.success && res.data) {
        setReasoningTurns(res.data.turns);
      } else {
        setReasoningError(res.error || 'Unable to load reasoning traces');
        setReasoningTurns([]);
      }
    } catch (e) {
      setReasoningError(e instanceof Error ? e.message : String(e));
      setReasoningTurns([]);
    } finally {
      setReasoningLoading(false);
    }
  }, []);

  const fetchSeals = useCallback(async () => {
    setSealsLoading(true);
    setSealsError(null);
    try {
      const res = await getPayloadSeals();
      if (res.success && res.data) {
        setSeals(res.data.seals);
        setSealsChainValid(res.data.chain_valid);
      } else {
        setSealsError(res.error || 'Unable to load evidence seals');
        setSeals([]);
      }
    } catch (e) {
      setSealsError(e instanceof Error ? e.message : String(e));
      setSeals([]);
    } finally {
      setSealsLoading(false);
    }
  }, []);

  const fetchEvents = useCallback(async () => {
    setEventsLoading(true);
    setEventsError(null);
    try {
      const res = await getTruncationEvents();
      if (res.success && res.data) {
        setEvents(res.data.events);
        setEventCounts(res.data.counts || {});
      } else {
        setEventsError(res.error || 'Unable to load chain-of-custody events');
        setEvents([]);
      }
    } catch (e) {
      setEventsError(e instanceof Error ? e.message : String(e));
      setEvents([]);
    } finally {
      setEventsLoading(false);
    }
  }, []);

  const fetchCuts = useCallback(async () => {
    setCutsLoading(true);
    setCutsError(null);
    try {
      const res = await getPayloadCutDetails();
      if (res.success && res.data) {
        setCuts(res.data.cuts);
      } else {
        setCutsError(res.error || 'Unable to load processed/dropped payload cuts');
        setCuts([]);
      }
    } catch (e) {
      setCutsError(e instanceof Error ? e.message : String(e));
      setCuts([]);
    } finally {
      setCutsLoading(false);
    }
  }, []);

  // Pull the COMPLETE bytes of a bounded preview from its sidecar (by hash).
  const loadFullPayload = useCallback(async (sha256?: string | null) => {
    if (!sha256 || fullPayloads[sha256] !== undefined) return;
    try {
      const res = await getDroppedPayloadFull(sha256);
      if (res.success && res.data) {
        setFullPayloads(prev => ({ ...prev, [sha256]: res.data!.content }));
      } else {
        showToast(res.error || 'Could not load full payload', 'error');
      }
    } catch (e) {
      showToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }, [fullPayloads, showToast]);

  // Pull the COMPLETE refused payload (the message the Eye refused to send) from
  // its sealed-payload sidecar (separate dir from dropped cuts).
  const loadSealedPayload = useCallback(async (sha256?: string | null) => {
    if (!sha256 || fullPayloads[sha256] !== undefined) return;
    try {
      const res = await getSealedPayloadFull(sha256);
      if (res.success && res.data) {
        setFullPayloads(prev => ({ ...prev, [sha256]: res.data!.content }));
      } else {
        showToast(res.error || 'Could not load refused payload', 'error');
      }
    } catch (e) {
      showToast(e instanceof Error ? e.message : String(e), 'error');
    }
  }, [fullPayloads, showToast]);

  // On mount fetch only what's visible by default (status + the always-on
  // Activity audit + the default-expanded GEP turns and steps). The heavy
  // collapsed sections (seals / cuts / events / conversations) load lazily on
  // first expand — see the effects below. This is the main fix for open-lag.
  useEffect(() => {
    (async () => {
      try { await initializeBridge(); } catch { /* bridge may already be init */ }
      fetchStatus();
      fetchAudit();
      fetchSteps();
      fetchGepTurns();
    })();
  }, [fetchStatus, fetchAudit, fetchSteps, fetchGepTurns]);

  // Lazy-load each heavy section the first time it is expanded.
  useEffect(() => {
    if (sealsExpanded && seals === null && !sealsLoading) fetchSeals();
  }, [sealsExpanded, seals, sealsLoading, fetchSeals]);
  useEffect(() => {
    if (cutsExpanded && cuts === null && !cutsLoading) fetchCuts();
  }, [cutsExpanded, cuts, cutsLoading, fetchCuts]);
  useEffect(() => {
    if (eventsExpanded) {
      if (events === null && !eventsLoading) fetchEvents();
      // Context Events grouping correlates by seal timestamps — ensure seals too.
      if (seals === null && !sealsLoading) fetchSeals();
    }
  }, [eventsExpanded, events, eventsLoading, seals, sealsLoading, fetchEvents, fetchSeals]);
  useEffect(() => {
    if (convExpanded && conversations === null && !convLoading) fetchConversations();
  }, [convExpanded, conversations, convLoading, fetchConversations]);
  useEffect(() => {
    if (reasoningExpanded && reasoningTurns === null && !reasoningLoading) fetchReasoning();
  }, [reasoningExpanded, reasoningTurns, reasoningLoading, fetchReasoning]);

  const filteredAudit = useMemo(() => (audit || []).filter(e => {
    if (auditFilter === 'all') return true;
    if (auditFilter === 'queries') {
      return e.type === 'user_query' || e.type === 'assistant_response' || e.type === 'tool_call';
    }
    if (auditFilter === 'evidence') return e.type === 'tool_result' || e.type === 'evidence_import';
    if (auditFilter === 'report') return e.type.startsWith('report_');
    if (auditFilter === 'map') return e.type === 'narrative_map';
    return true;
  }), [audit, auditFilter]);

  // Windowed views of the large lists — render a page at a time (the bridge
  // already caps each log; this keeps the DOM small and the panel responsive).
  const gepTurnsPaged = usePaged(gepTurns);
  const reasoningPaged = usePaged(reasoningTurns);
  const convPaged = usePaged(conversations);
  const auditPaged = usePaged(filteredAudit);

  const handleExport = useCallback(async () => {
    setExporting(true);
    try {
      // Default destination: the bridge writes into the active case's EYE_Logs
      // directory.  Pass a relative filename; the Python side resolves it.
      const raw = await exportAuditTrail('audit_trail.json');
      let parsed: any = null;
      try { parsed = JSON.parse(raw); } catch { /* ignore */ }
      if (parsed && parsed.success) {
        const path =
          (parsed.data && (parsed.data.output_path || parsed.data.path)) ||
          'audit_trail.json';
        showToast(`Audit JSON exported to ${path}`, 'success');
        // After an export the audit_trail.json now exists -> refresh Rule 7.
        fetchStatus();
      } else {
        showToast(parsed?.error || 'Audit JSON export failed', 'error');
      }
    } catch (e) {
      showToast(e instanceof Error ? e.message : String(e), 'error');
    } finally {
      setExporting(false);
    }
  }, [showToast, fetchStatus]);

  const handleOffsetClick = useCallback((offset: number, label: string) => {
    navigator.clipboard.writeText(String(offset));
    showToast(`Copied ${label} offset: ${offset}`, 'info');
  }, [showToast]);

  // Stable per-section item renderers. Hoisting these out of the JSX (instead of
  // inline `renderItem={(x)=>…}`) keeps their identity stable across unrelated
  // parent re-renders, so the memoized QuestionGroups for a section only
  // re-renders when ITS own inputs change — not when another section's state
  // (search/expand) changes. The heavy JSON.stringify only runs for an open row.
  const renderSeal = useCallback((s: PayloadSeal) => {
    const key = s.seal_hash || String(s.seq);
    const isOpen = openSealKey === key;
    const over = s.payload_tokens > s.max_context_tokens;
    return (
      <article
        key={key}
        style={{ ...styles.timelineItem, borderLeftColor: over ? STATUS_STYLE.FAIL.fg : STATUS_STYLE.PASS.fg }}
      >
        <button
          onClick={() => setOpenSealKey(isOpen ? null : key)}
          style={styles.timelineRow}
          title={isOpen ? 'Collapse' : 'Show seal detail'}
        >
          <span style={styles.timelineTs}>{formatTs(s.timestamp)}</span>
          <span style={styles.timelineBadge}>{s.phase}</span>
          {s.truncated && (
            <span style={{ ...styles.timelineBadge, color: STATUS_STYLE.PARTIAL.fg, background: STATUS_STYLE.PARTIAL.bg, border: `1px solid ${STATUS_STYLE.PARTIAL.border}` }}>
              AUTO-COMPACTED
            </span>
          )}
          <span style={styles.timelineTools}>{s.payload_tokens}/{s.max_context_tokens} tok · iter {String(s.iteration)}</span>
          <span style={styles.timelineCaret}>{isOpen ? '▾' : '▸'}</span>
        </button>
        {isOpen && (
          <div style={{ padding: '6px 16px 10px', fontSize: '12px', color: '#cbd5e1' }}>
            <div><span style={{ color: '#64748b' }}>model:</span> {s.model} &nbsp; <span style={{ color: '#64748b' }}>iteration:</span> {String(s.iteration)}</div>
            <div style={{ wordBreak: 'break-all', marginTop: 4 }}>
              <span style={{ color: '#64748b' }}>payload SHA-256:</span> <code>{s.payload_sha256}</code>
            </div>
            <div style={{ wordBreak: 'break-all' }}>
              <span style={{ color: '#64748b' }}>seal hash:</span> <code>{s.seal_hash}</code>
            </div>
            {s.evidence_refs && s.evidence_refs.length > 0 && (
              <div style={{ marginTop: 6 }}>
                <span style={{ color: '#64748b' }}>evidence provenance:</span>
                <pre style={{ ...styles.helpNote, whiteSpace: 'pre-wrap', margin: '4px 0 0', padding: 8 } as any}>
                  {JSON.stringify(s.evidence_refs, null, 2)}
                </pre>
              </div>
            )}
            {s.cut_details && s.cut_details.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <details style={{ border: '1px solid rgba(255,255,255,0.08)', borderRadius: '4px', background: 'rgba(0,0,0,0.2)' }}>
                  <summary style={{ cursor: 'pointer', padding: '6px 10px', fontWeight: 'bold', color: '#f43f5e', outline: 'none' }}>
                    Truncated Payload Details ({s.cut_details.length})
                  </summary>
                  <div style={{ padding: '0 10px 10px' }}>
                    {s.cut_details.map((detail, dIdx) => (
                      <div key={dIdx} style={{ marginTop: 8, borderTop: dIdx > 0 ? '1px solid rgba(255,255,255,0.08)' : 'none', paddingTop: dIdx > 0 ? 8 : 0 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                          <strong>Action: <span style={{ color: detail.action === 'SUMMARIZED' ? '#10b981' : '#f43f5e' }}>{detail.action}</span></strong>
                          <span style={{ color: '#64748b' }}>{detail.token_count} chars/tokens</span>
                        </div>
                        <ForensicDiff
                          processed={detail.processed_content}
                          dropped={detail.cut_content}
                          processedOffsets={detail.processed_file_offsets}
                          droppedOffsets={detail.dropped_file_offsets}
                          action={detail.action}
                          onCopyOffset={handleOffsetClick}
                        />
                      </div>
                    ))}
                  </div>
                </details>
              </div>
            )}
          </div>
        )}
      </article>
    );
  }, [openSealKey, handleOffsetClick]);

  const renderCut = useCallback((cut: FlatCutDetail, idx: number) => {
    const key = `${cut.seq}-${cut.message_id || idx}`;
    const isOpen = openCutKey === key;
    const cutColor = cut.action === 'SUMMARIZED' ? STATUS_STYLE.PARTIAL : STATUS_STYLE.FAIL;
    const range = cut.cut_range;
    const rangeLabel = range
      ? `kept [${range.processed[0]}–${range.processed[1]}] · dropped [${range.dropped[0]}–${range.dropped[1]}] of ${range.total}`
      : '';
    return (
    <article
      key={key}
      style={{ ...styles.timelineItem, borderLeftColor: cutColor.fg }}
    >
      <button
        onClick={() => setOpenCutKey(isOpen ? null : key)}
        style={styles.timelineRow}
        title={isOpen ? 'Collapse' : 'Show processed/dropped detail'}
      >
        <span style={styles.timelineTs}>{formatTs(cut.timestamp || '')}</span>
        <span style={{ ...styles.timelineBadge, color: cutColor.fg, background: cutColor.bg, border: `1px solid ${cutColor.border}` }}>
          {cut.action}
        </span>
        <span style={styles.timelineSummary}>{cut.query || cut.phase || '(payload)'}</span>
        <span style={styles.timelineTools}>
          {cut.source === 'refused'
            ? `${cut.token_count} tok refused (> ${cut.max_context_tokens ?? '?'} window)`
            : `${cut.cut_content_len ?? (cut.cut_content || '').length} dropped chars`}
        </span>
        <span style={styles.timelineCaret}>{isOpen ? '▾' : '▸'}</span>
      </button>
      {isOpen && (
        <div style={{ padding: '6px 16px 10px', fontSize: '12px', color: '#cbd5e1' }}>
          {cut.source === 'refused' ? (
            <>
              <div>
                The Eye <strong style={{ color: '#f43f5e' }}>refused to send</strong> this payload — the
                irreducible evidence core ({cut.token_count} tok) still exceeded the model window
                ({cut.max_context_tokens ?? '?'} tok) after auto-compaction. Evidence was preserved,
                never truncated.
              </div>
              <div style={{ wordBreak: 'break-all', marginTop: 4 }}>
                <span style={{ color: '#64748b' }}>payload SHA-256:</span> <code>{cut.payload_sha256}</code>
              </div>
              {cut.cut_content && (
                <div style={{ marginTop: 8 }}>
                  <div style={{ ...styles.diffHeader, color: '#f59e0b', background: 'rgba(245,158,11,0.05)' }}>
                    <span>↺ ORIGINAL MESSAGE (REFUSED — NOT SENT)</span>
                    <span>preview</span>
                  </div>
                  <div style={{ ...styles.diffContent, ...styles.droppedText }}>{cut.cut_content}</div>
                </div>
              )}
              {cut.payload_sidecar && (
                <div style={{ marginTop: 8 }}>
                  {fullPayloads[cut.payload_sha256 || ''] === undefined ? (
                    <button
                      style={{ ...styles.btn, ...styles.btnSecondary }}
                      onClick={() => loadSealedPayload(cut.payload_sha256)}
                      title="Read the complete payload the Eye refused to send"
                    >
                      <IconDownload /> Load the full refused payload (the message itself)
                    </button>
                  ) : (
                    <details open>
                      <summary style={{ cursor: 'pointer', color: '#f43f5e' }}>
                        Full refused payload · SHA-256 <code>{cut.payload_sha256}</code>
                      </summary>
                      <pre style={{ ...styles.helpNote, whiteSpace: 'pre-wrap', margin: '4px 0 0', padding: 8 } as any}>
                        {fullPayloads[cut.payload_sha256 || '']}
                      </pre>
                    </details>
                  )}
                </div>
              )}
            </>
          ) : (
            <>
              <div style={{ wordBreak: 'break-all' }}>
                {cut.message_id && (<><span style={{ color: '#64748b' }}>message id:</span> <code>{cut.message_id}</code> &nbsp;</>)}
                {cut.seq != null && (<><span style={{ color: '#64748b' }}>seal #:</span> <code>{String(cut.seq)}</code> &nbsp;</>)}
                <span style={{ color: '#64748b' }}>phase:</span> {cut.phase}
              </div>
              {rangeLabel && (
                <div style={{ marginTop: 4 }}>
                  <span style={{ color: '#64748b' }}>cut range ({range?.unit}):</span> {rangeLabel}
                </div>
              )}
              <div style={{ marginTop: '8px' }}>
                <ForensicDiff
                  processed={cut.processed_content}
                  dropped={cut.cut_content}
                  processedOffsets={cut.processed_file_offsets}
                  droppedOffsets={cut.dropped_file_offsets}
                  action={cut.action}
                  onCopyOffset={handleOffsetClick}
                />
              </div>
              {/* Full recoverable bytes — only when a sidecar exists (content exceeded the inline cap). */}
              {cut.cut_content_sidecar && (
                <div style={{ marginTop: 8 }}>
                  {fullPayloads[cut.cut_content_sha256 || ''] === undefined ? (
                    <button
                      style={{ ...styles.btn, ...styles.btnSecondary }}
                      onClick={() => loadFullPayload(cut.cut_content_sha256)}
                      title="Read the complete dropped bytes from the sidecar"
                    >
                      <IconDownload /> Load full dropped bytes ({cut.cut_content_len} chars)
                    </button>
                  ) : (
                    <details open>
                      <summary style={{ cursor: 'pointer', color: '#f43f5e' }}>
                        Full dropped bytes ({cut.cut_content_len} chars) · SHA-256 <code>{cut.cut_content_sha256}</code>
                      </summary>
                      <pre style={{ ...styles.helpNote, whiteSpace: 'pre-wrap', margin: '4px 0 0', padding: 8 } as any}>
                        {fullPayloads[cut.cut_content_sha256 || '']}
                      </pre>
                    </details>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </article>
    );
  }, [openCutKey, fullPayloads, loadSealedPayload, loadFullPayload, handleOffsetClick]);

  const renderEvent = useCallback((ev: TruncationEvent, idx: number) => {
    const s = AUDIT_ACTION_STYLE(ev.action);
    const key = `${ev.timestamp}-${ev.id || idx}`;
    const isOpen = openEventKey === key;
    return (
      <article
        key={key}
        style={{ ...styles.timelineItem, borderLeftColor: s.fg }}
      >
        <button
          onClick={() => setOpenEventKey(isOpen ? null : key)}
          style={styles.timelineRow}
          title={isOpen ? 'Collapse' : 'Show event detail'}
        >
          <span style={styles.timelineTs}>{formatTs(ev.timestamp)}</span>
          <span style={{ ...styles.timelineBadge, color: s.fg, background: s.bg, border: `1px solid ${s.border}` }}>
            {ev.action}
          </span>
          <span style={styles.timelineSummary}>{ev.reason}</span>
          <span style={styles.timelineTools}>{ev.tokens} tok</span>
          <span style={styles.timelineCaret}>{isOpen ? '▾' : '▸'}</span>
        </button>
        {isOpen && (
          <div style={{ padding: '6px 16px 10px', fontSize: '12px', color: '#cbd5e1' }}>
            <div style={{ wordBreak: 'break-all' }}>
              <span style={{ color: '#64748b' }}>message id:</span> <code>{ev.id}</code> &nbsp;
              <span style={{ color: '#64748b' }}>content hash:</span> <code>{ev.hash}</code>
            </div>
            {ev.metadata && Object.keys(ev.metadata).length > 0 && (
              <div style={{ marginTop: '8px' }}>
                <ForensicDiff
                  processed={ev.metadata.processed_content}
                  dropped={ev.metadata.cut_content}
                  processedOffsets={ev.metadata.processed_file_offsets}
                  droppedOffsets={ev.metadata.dropped_file_offsets}
                  action={ev.action}
                  onCopyOffset={handleOffsetClick}
                />
                <details style={{ marginTop: '8px' }}>
                  <summary style={{ cursor: 'pointer', color: '#64748b' }}>Raw Metadata JSON</summary>
                  <pre style={{ ...styles.helpNote, whiteSpace: 'pre-wrap', margin: '4px 0 0', padding: 8 } as any}>
                    {JSON.stringify(ev.metadata, null, 2)}
                  </pre>
                </details>
              </div>
            )}
          </div>
        )}
      </article>
    );
  }, [openEventKey, handleOffsetClick]);

  const renderStepRun = useCallback((run: any, ri: number) => {
    const rs = STEP_STATUS_STYLE(run.status);
    return (
      <div
        key={`${run.stepType}-${run.timestamp}-${ri}`}
        style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '4px 16px 4px 12px', fontSize: '12px' }}
      >
        <span style={{ ...styles.timelineBadge, color: rs.fg, background: rs.bg, border: `1px solid ${rs.border}` }}>
          {(run.stepType || 'step').toUpperCase()}
        </span>
        <span style={{ ...styles.timelineTs, minWidth: '150px' }}>{formatTs(run.timestamp)}</span>
        <span style={styles.timelineSummary}>{run.stepLabel || '(step)'}</span>
        <span style={{ ...styles.timelineBadge, color: rs.fg, background: rs.bg, border: `1px solid ${rs.border}` }}>
          {rs.label}
        </span>
        {run.iteration ? (<span style={{ color: '#94a3b8' }}>Loop {run.iteration}</span>) : null}
        {run.tool ? (<span style={styles.timelineTools}>{run.tool}</span>) : null}
        {run.detail ? (<span style={{ color: '#94a3b8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{run.detail}</span>) : null}
      </div>
    );
  }, []);

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <div>
          <div style={styles.eyebrow}>Ghassan Elsman Protocol</div>
          <h1 style={styles.title}>GEP Compliance</h1>
          <p style={styles.subtitle}>
            Live status of the forensic-integrity rules and Eye processes the AI agent enforces,
            each mapped to the GEP principle it upholds — plus a status for all 10 GEP principles.
            Diagnostics are read from <code style={styles.code}>EYE_Logs/</code> and
            the live <code style={styles.code}>ContextManager</code> state.
          </p>
        </div>
        <div style={styles.actions}>
          <button
            style={{ ...styles.btn, ...styles.btnSecondary }}
            onClick={() => {
              // Refresh only the visible/loaded sections (lazy ones stay lazy).
              fetchStatus(); fetchAudit(); fetchSteps(); fetchGepTurns();
              if (sealsExpanded) fetchSeals();
              if (cutsExpanded) fetchCuts();
              if (eventsExpanded) { fetchEvents(); fetchSeals(); }
              if (convExpanded) fetchConversations();
            }}
            disabled={loading || auditLoading}
            title="Re-fetch compliance status and activity audit"
          >
            <IconRefresh size={13} />
            <span>{(loading || auditLoading) ? 'Refreshing…' : 'Refresh'}</span>
          </button>
          <button
            style={{ ...styles.btn, ...styles.btnPrimary }}
            onClick={handleExport}
            disabled={exporting}
            title="Export audit_trail.json into the case's EYE_Logs"
          >
            <IconDownload size={13} />
            <span>{exporting ? 'Exporting…' : 'Export Audit JSON'}</span>
          </button>
        </div>
      </header>

      {error && (
        <div style={styles.errorBox}>
          <strong>Bridge error:</strong> {error}
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', marginBottom: '10px' }} onClick={() => setRulesExpanded(!rulesExpanded)}>
        <h2 style={{ fontSize: '16px', margin: 0 }}>{rulesExpanded ? '▼' : '▶'} View Protocol Compliance Rules</h2>
      </div>

      {rulesExpanded && (
        <>
          {/* How to read the compliance dashboard */}
          <div style={styles.helpNote}>
            <span style={styles.helpNoteIcon}>ⓘ</span>
            <div>
              <strong>How to read this dashboard.</strong> Each row is one forensic-integrity rule or Eye process
              the EYE enforces while answering, tagged with the GEP principle(s) it upholds.
              <span style={styles.tagPass}>PASS</span> means the rule is
              actively in force right now. <span style={styles.tagPartial}>PARTIAL</span> means it is wired in
              but only partially observed. <span style={styles.tagFail}>FAIL</span> means a precondition is
              missing — see the note under the row for the fix. <span style={styles.tagNa}>N-A</span> means the
              rule has nothing to grade yet because no qualifying activity has happened in this session.
            </div>
          </div>

          <div style={styles.table}>
            <div style={styles.tableHead}>
              <div style={styles.colId}>#</div>
              <div style={styles.colName}>Rule</div>
              <div style={styles.colStatus}>Status</div>
              <div style={styles.colDetail}>Detail</div>
            </div>
            {(rules || []).map((r) => {
              const s = STATUS_STYLE[r.status] || STATUS_STYLE['N-A'];
              return (
                <div key={r.id} style={styles.row}>
                  <div style={styles.colId}>{r.id}</div>
                  <div style={styles.colName}>
                    <div style={styles.ruleName}>{r.name}</div>
                    <div style={styles.ruleBlurb}>{RULE_BLURB[r.id] || ''}</div>
                    {r.gep && r.gep.length > 0 && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '4px' }}>
                        {r.gep.map((g) => (
                          <span key={g} style={{
                            fontSize: '10px', fontWeight: 700, color: '#c7d2fe',
                            background: 'rgba(99,102,241,0.15)', border: '1px solid rgba(99,102,241,0.4)',
                            borderRadius: '999px', padding: '1px 7px',
                          }}>{g}</span>
                        ))}
                      </div>
                    )}
                  </div>
                  <div style={styles.colStatus}>
                    <span
                      style={{
                        background: s.bg,
                        color: s.fg,
                        border: `1px solid ${s.border}`,
                        ...styles.badge,
                      }}
                    >
                      {r.status}
                    </span>
                  </div>
                  <div style={{ ...styles.colDetail, color: '#cbd5e1' }}>
                    <div>{r.detail || '—'}</div>
                    {(() => {
                      const guidance = RULE_GUIDANCE[r.id]?.[r.status];
                      if (!guidance) return null;
                      return (
                        <div style={styles.ruleGuidance}>
                          <span style={styles.ruleGuidanceIcon}>ⓘ</span>
                          <span>{guidance}</span>
                        </div>
                      );
                    })()}
                  </div>
                </div>
              );
            })}
            {loading && !rules && (
              <div style={{ ...styles.row, justifyContent: 'center', color: '#94a3b8' }}>
                Loading compliance status…
              </div>
            )}
            {!loading && rules && rules.length === 0 && (
              <div style={{ ...styles.row, justifyContent: 'center', color: '#94a3b8' }}>
                No rules returned.
              </div>
            )}
          </div>
        </>
      )}

      {/* ── GEP Protocol — 10 Principles ─────────────────────────────── */}
      {gepPrinciples && gepPrinciples.length > 0 && (
        <section style={styles.auditWindow}>
          <header style={styles.auditHeader}>
            <div>
              <div style={styles.eyebrow}>The Ghassan Elsman Protocol</div>
              <h2 style={styles.auditTitle}>GEP Protocol — 10 Principles</h2>
              <p style={styles.auditSubtitle}>
                Live status of every GEP principle and the Eye mechanisms that uphold it.
              </p>
            </div>
          </header>
          <div style={styles.table}>
            <div style={styles.tableHead}>
              <div style={styles.colId}>#</div>
              <div style={styles.colName}>Principle</div>
              <div style={styles.colStatus}>Status</div>
              <div style={styles.colDetail}>Upheld by</div>
            </div>
            {gepPrinciples.map((p) => {
              const s = STATUS_STYLE[p.status] || STATUS_STYLE['N-A'];
              return (
                <div key={p.id} style={styles.row}>
                  <div style={styles.colId}>{p.id}</div>
                  <div style={styles.colName}>
                    <div style={styles.ruleName}>
                      {p.name}
                      {p.basis && (
                        <span style={{
                          marginLeft: '8px', fontSize: '10px', fontWeight: 700,
                          textTransform: 'uppercase', letterSpacing: '0.04em', color: '#a5b4fc',
                          background: 'rgba(99,102,241,0.12)', border: '1px solid rgba(99,102,241,0.35)',
                          borderRadius: '4px', padding: '1px 6px',
                        }}>{p.basis}</span>
                      )}
                    </div>
                    <div style={styles.ruleBlurb}>{p.detail}</div>
                  </div>
                  <div style={styles.colStatus}>
                    <span style={{ background: s.bg, color: s.fg, border: `1px solid ${s.border}`, ...styles.badge }}>
                      {p.status}
                    </span>
                  </div>
                  <div style={{ ...styles.colDetail, color: '#cbd5e1' }}>
                    {p.upheld_by && p.upheld_by.length > 0 ? p.upheld_by.join(', ') : '—'}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* ── Per-Answer GEP Compliance ─────────────────────────────── */}
      <section style={styles.auditWindow}>
        <header style={styles.auditHeader}>
          <div>
            <div style={styles.eyebrow}>Per-Answer GEP Compliance</div>
            <h2
              style={{ ...styles.auditTitle, cursor: 'pointer' }}
              onClick={() => setGepTurnsExpanded(!gepTurnsExpanded)}
              title={gepTurnsExpanded ? 'Collapse' : 'Expand'}
            >
              {gepTurnsExpanded ? '▼' : '▶'} Did Each Answer Follow the Protocol?
            </h2>
            <p style={styles.auditSubtitle}>
              For every question, whether that specific answer upheld <strong>all 10 GEP
              principles</strong> — evidence primacy (GEP-1), traceability (GEP-2), specificity &amp;
              chronology (GEP-3), cross-corroboration (GEP-4), premise verification (GEP-5),
              completeness &amp; coverage (GEP-6), integrity/dual-output (GEP-7), transparency
              (GEP-8), human authority (GEP-9), and defensibility/direct answer (GEP-10) — marked
              N-A where a principle doesn't apply to that turn.
            </p>
          </div>
          <button
            style={{ ...styles.btn, ...styles.btnSecondary }}
            onClick={() => fetchGepTurns()}
            title="Refresh per-answer GEP compliance"
          >
            <IconRefresh /> Refresh
          </button>
        </header>

        {gepTurnsError && (
          <div style={styles.errorBox}>
            <strong>Per-answer GEP error:</strong> {gepTurnsError}
          </div>
        )}

        {gepTurnsExpanded && (
          <div style={styles.timeline}>
            {gepTurnsLoading && !gepTurns && (
              <div style={styles.timelineEmpty}>Loading per-answer GEP compliance…</div>
            )}
            {!gepTurnsLoading && (gepTurns || []).length === 0 && (
              <div style={styles.timelineEmpty}>
                No answered turns recorded yet. Ask the EYE a question to populate this.
              </div>
            )}
            {gepTurnsPaged.visible.map((turn, idx) => {
              const isOpen = openTurnIdx === idx;
              const anyFail = turn.checks.some(c => c.status === 'FAIL');
              const accent = anyFail ? STATUS_STYLE.FAIL.fg : STATUS_STYLE.PASS.fg;
              return (
                <article
                  key={`${turn.timestamp}-${idx}`}
                  style={{ ...styles.timelineItem, borderLeftColor: accent }}
                >
                  <button
                    onClick={() => setOpenTurnIdx(isOpen ? null : idx)}
                    style={styles.timelineRow}
                    title={isOpen ? 'Collapse' : 'Show per-rule result'}
                  >
                    <span style={styles.timelineTs}>{formatTs(turn.timestamp)}</span>
                    <span style={styles.timelineSummary}>{gepTurnLabel(turn.query)}</span>
                    <span style={styles.timelineTools}>{turn.summary}</span>
                    <span style={styles.timelineCaret}>{isOpen ? '▾' : '▸'}</span>
                  </button>
                  {isOpen && (
                    <div style={{ padding: '6px 16px 10px' }}>
                      {turn.checks.map((c) => {
                        const s = STATUS_STYLE[c.status] || STATUS_STYLE['N-A'];
                        return (
                          <div
                            key={c.id}
                            style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '3px 0', fontSize: '12.5px' }}
                          >
                            <span
                              style={{ background: s.bg, color: s.fg, border: `1px solid ${s.border}`, ...styles.badge, minWidth: '64px', textAlign: 'center' }}
                            >
                              {c.status}
                            </span>
                            <span style={{ color: '#e6edf3', minWidth: '210px' }}>{c.name}</span>
                            <span style={{ color: '#94a3b8' }}>{c.detail}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </article>
              );
            })}
            <ShowMore paged={gepTurnsPaged} unit="answers" />
          </div>
        )}
      </section>

      {/* ── Reasoning: how each question was decomposed & concluded ──── */}
      <section style={styles.auditWindow}>
        <header style={styles.auditHeader}>
          <div>
            <div style={styles.eyebrow}>Transparency · Reasoning Trace</div>
            <h2
              style={{ ...styles.auditTitle, cursor: 'pointer' }}
              onClick={() => setReasoningExpanded(!reasoningExpanded)}
              title={reasoningExpanded ? 'Collapse' : 'Expand'}
            >
              {reasoningExpanded ? '▼' : '▶'} How Each Question Was Decomposed &amp; Concluded
            </h2>
            <p style={styles.auditSubtitle}>
              For every decomposed question: WHY each sub-question was created from the main question
              (GEP-8), and WHY each conclusion follows from which evidence (GEP-2), with the
              <code> database:table:rowid</code> refs it rests on.
            </p>
          </div>
          <button
            style={{ ...styles.btn, ...styles.btnSecondary }}
            onClick={() => fetchReasoning()}
            title="Refresh reasoning traces"
          >
            <IconRefresh /> Refresh
          </button>
        </header>

        {reasoningError && (
          <div style={styles.errorBox}>
            <strong>Reasoning trace error:</strong> {reasoningError}
          </div>
        )}

        {reasoningExpanded && (
          <div style={styles.timeline}>
            {reasoningLoading && !reasoningTurns && (
              <div style={styles.timelineEmpty}>Loading reasoning traces…</div>
            )}
            {!reasoningLoading && (reasoningTurns || []).length === 0 && (
              <div style={styles.timelineEmpty}>
                No reasoning traces yet. Ask the EYE a multi-part question to populate this.
              </div>
            )}
            {reasoningPaged.visible.map((turn, idx) => {
              const isOpen = openReasoningIdx === idx;
              const subCount = (turn.sub_questions || []).length;
              const premCount = (turn.premises || []).length;
              return (
                <article
                  key={`${turn.timestamp}-${idx}`}
                  style={{ ...styles.timelineItem, borderLeftColor: '#a371f7' }}
                >
                  <button
                    onClick={() => setOpenReasoningIdx(isOpen ? null : idx)}
                    style={styles.timelineRow}
                    title={isOpen ? 'Collapse' : 'Show reasoning'}
                  >
                    <span style={styles.timelineTs}>{formatTs(turn.timestamp)}</span>
                    <span style={styles.timelineSummary}>{gepTurnLabel(turn.query)}</span>
                    <span style={styles.timelineTools}>
                      {subCount} sub-question{subCount === 1 ? '' : 's'}
                      {premCount ? ` · ${premCount} premise${premCount === 1 ? '' : 's'}` : ''}
                    </span>
                    <span style={styles.timelineCaret}>{isOpen ? '▾' : '▸'}</span>
                  </button>
                  {isOpen && (
                    <div style={{ padding: '6px 16px 12px' }}>
                      {turn.strategy && (
                        <p style={{ color: '#c9d1d9', fontSize: '12.5px', margin: '4px 0 12px' }}>
                          <strong style={{ color: '#a371f7' }}>Strategy:</strong> {turn.strategy}
                        </p>
                      )}

                      {(turn.sub_questions || []).map((sq) => (
                        <div
                          key={sq.id}
                          style={{
                            border: '1px solid #21262d', borderRadius: '8px',
                            padding: '10px 12px', margin: '0 0 10px',
                            background: 'rgba(163,113,247,0.05)',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                            <span style={{ ...styles.badge, background: 'rgba(163,113,247,0.15)', color: '#a371f7', border: '1px solid #a371f7', minWidth: '40px', textAlign: 'center' }}>
                              {sq.id}
                            </span>
                            <span style={{ color: '#e6edf3', fontSize: '13px', fontWeight: 600 }}>{sq.q}</span>
                            <span style={{ marginLeft: 'auto', ...styles.badge, background: sq.status === 'answered' ? 'rgba(63,185,80,0.12)' : 'rgba(210,153,34,0.12)', color: sq.status === 'answered' ? '#3fb950' : '#d29922', border: `1px solid ${sq.status === 'answered' ? '#3fb950' : '#d29922'}` }}>
                              {sq.status}
                            </span>
                          </div>
                          {sq.why_created && (
                            <p style={{ margin: '4px 0', fontSize: '12.5px', color: '#94a3b8' }}>
                              <strong style={{ color: '#c9d1d9' }}>Why this sub-question:</strong> {sq.why_created}
                            </p>
                          )}
                          {sq.conclusion && (
                            <p style={{ margin: '4px 0', fontSize: '12.5px', color: '#e6edf3' }}>
                              <strong style={{ color: '#c9d1d9' }}>Conclusion:</strong> {sq.conclusion}
                            </p>
                          )}
                          {sq.why_concluded && (
                            <p style={{ margin: '4px 0', fontSize: '12.5px', color: '#94a3b8' }}>
                              <strong style={{ color: '#c9d1d9' }}>Why concluded:</strong> {sq.why_concluded}
                            </p>
                          )}
                          {(sq.evidence || []).length > 0 && (
                            <div style={{ marginTop: '6px' }}>
                              <span style={{ fontSize: '11.5px', color: '#8b949e' }}>Evidence:</span>
                              {(sq.evidence || []).map((ev, i) => (
                                <div key={i} style={{ display: 'flex', gap: '8px', marginTop: '3px', fontSize: '12px' }}>
                                  <code style={{ color: '#58a6ff', background: '#0d1117', padding: '1px 6px', borderRadius: '4px', whiteSpace: 'nowrap' }}>{ev.ref || '(unref)'}</code>
                                  {ev.note && <span style={{ color: '#94a3b8' }}>{ev.note}</span>}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}

                      {(turn.premises || []).map((pr, i) => {
                        const vcolor = pr.verdict === 'CONFIRMED' ? '#3fb950'
                          : pr.verdict === 'REFUTED' ? '#f85149' : '#d29922';
                        return (
                          <div
                            key={`p${i}`}
                            style={{ border: '1px solid #21262d', borderRadius: '8px', padding: '10px 12px', margin: '0 0 10px', background: 'rgba(248,81,73,0.04)' }}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                              <span style={{ ...styles.badge, background: 'transparent', color: vcolor, border: `1px solid ${vcolor}`, minWidth: '96px', textAlign: 'center' }}>
                                {pr.verdict}
                              </span>
                              <span style={{ color: '#e6edf3', fontSize: '13px' }}>Premise: {pr.claim}</span>
                            </div>
                            {pr.why && (
                              <p style={{ margin: '4px 0', fontSize: '12.5px', color: '#94a3b8' }}>{pr.why}</p>
                            )}
                            {(pr.evidence || []).map((ev, j) => (
                              <div key={j} style={{ display: 'flex', gap: '8px', marginTop: '3px', fontSize: '12px' }}>
                                <code style={{ color: '#58a6ff', background: '#0d1117', padding: '1px 6px', borderRadius: '4px', whiteSpace: 'nowrap' }}>{ev.ref || '(unref)'}</code>
                                {ev.note && <span style={{ color: '#94a3b8' }}>{ev.note}</span>}
                              </div>
                            ))}
                          </div>
                        );
                      })}

                      {turn.consolidation && (
                        <p style={{ margin: '10px 0 6px', fontSize: '12.5px', color: '#e6edf3' }}>
                          <strong style={{ color: '#a371f7' }}>Consolidation:</strong> {turn.consolidation}
                        </p>
                      )}

                      {(turn.knowledge_consulted || []).length > 0 && (
                        <div style={{ marginTop: '8px', display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
                          <span style={{ fontSize: '11.5px', color: '#8b949e' }}>Knowledge consulted:</span>
                          {(turn.knowledge_consulted || []).map((k, i) => (
                            <span key={i} style={{ ...styles.badge, background: '#161b22', color: '#8b949e', border: '1px solid #21262d' }}>{k}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </article>
              );
            })}
            <ShowMore paged={reasoningPaged} unit="answers" />
          </div>
        )}
      </section>

      {/* ── Evidence Seals (chain of custody for what the AI saw) ──── */}
      <section style={styles.auditWindow}>
        <header style={styles.auditHeader}>
          <div>
            <div style={styles.eyebrow}>Chain of Custody · Evidence Seals</div>
            <h2
              style={{ ...styles.auditTitle, cursor: 'pointer' }}
              onClick={() => setSealsExpanded(!sealsExpanded)}
              title={sealsExpanded ? 'Collapse' : 'Expand'}
            >
              {sealsExpanded ? '▼' : '▶'} Exactly What the Model Saw (SHA-256 Sealed)
            </h2>
            <p style={styles.auditSubtitle}>
              One tamper-evident seal per LLM call: the SHA-256 of the exact payload injected,
              token count vs. the model's limit, and the provenance of the evidence rows. The
              records are hash-chained — altering or removing one breaks the chain.
            </p>
          </div>
          <button
            style={{ ...styles.btn, ...styles.btnSecondary }}
            onClick={() => fetchSeals()}
            title="Refresh evidence seals"
          >
            <IconRefresh /> Refresh
          </button>
        </header>

        {sealsError && (
          <div style={styles.errorBox}><strong>Evidence seal error:</strong> {sealsError}</div>
        )}

        {sealsExpanded && (
          <>
            {seals && seals.length > 0 && (
              <div style={{ ...styles.helpNote, margin: '12px 22px 0' }}>
                <span style={styles.helpNoteIcon}>{sealsChainValid ? '✓' : '⚠'}</span>
                <div>
                  <strong>Hash chain {sealsChainValid ? 'VERIFIED' : 'BROKEN'}.</strong>{' '}
                  {sealsChainValid
                    ? 'Every seal links to the previous one — the record of what the AI analyzed is intact.'
                    : 'The seal chain does not verify — the payload-seal log may have been altered. Investigate before relying on these answers.'}
                </div>
              </div>
            )}
            {sealsLoading && !seals ? (
              <div style={styles.timeline}><div style={styles.timelineEmpty}>Loading evidence seals…</div></div>
            ) : (
              <QuestionGroups
                groups={sealGroups}
                openKeys={sealGroupsOpen}
                onToggle={toggleSealGroups}
                search={sealSearch}
                setSearch={setSealSearch}
                placeholder="Search seals by question…"
                unit="seals"
                emptyText="No payloads sealed yet. Ask the EYE a question to generate sealed records."
                renderItem={renderSeal}
              />
            )}
          </>
        )}
      </section>

      {/* ── Processed vs Dropped Payload (per-cut, with full recoverable bytes) ── */}
      <section style={styles.auditWindow}>
        <header style={styles.auditHeader}>
          <div>
            <div style={styles.eyebrow}>Chain of Custody · Context Adaptation</div>
            <h2
              style={{ ...styles.auditTitle, cursor: 'pointer' }}
              onClick={() => setCutsExpanded(!cutsExpanded)}
              title={cutsExpanded ? 'Collapse' : 'Expand'}
            >
              {cutsExpanded ? '▼' : '▶'} Processed vs Dropped Payload
            </h2>
            <p style={styles.auditSubtitle}>
              Every drop the Eye made to fit the context window, grouped by question:
              self-heal cuts (summarize / drop), the tool-output cap, the
              <strong> budget trims</strong> of the system prompt / RAG / history, and
              the <strong> message itself</strong> for any payload that was
              <strong> REFUSED</strong> for overflow. Each shows the processed-vs-dropped
              split and offsets where available; full dropped/refused bytes are
              recoverable on demand from the per-hash sidecars in
              <code style={styles.code}>EYE_Logs/</code>.
            </p>
          </div>
          <button
            style={{ ...styles.btn, ...styles.btnSecondary }}
            onClick={() => fetchCuts()}
            title="Refresh processed/dropped payload cuts"
          >
            <IconRefresh /> Refresh
          </button>
        </header>

        {cutsError && (
          <div style={styles.errorBox}><strong>Context-adaptation error:</strong> {cutsError}</div>
        )}

        {cutsExpanded && (
          cutsLoading && !cuts ? (
            <div style={styles.timeline}><div style={styles.timelineEmpty}>Loading processed/dropped payload cuts…</div></div>
          ) : (
            <QuestionGroups
              groups={cutGroups}
              openKeys={cutGroupsOpen}
              onToggle={toggleCutGroups}
              search={cutSearch}
              setSearch={setCutSearch}
              placeholder="Search payload cuts by question…"
              unit="cuts"
              emptyText="No drops yet — every payload fit the context window intact (no budget trims, self-heal cuts, or refusals)."
              renderItem={renderCut}
            />
          )
        )}
      </section>

      {/* ── Chain-of-Custody Events (context-integrity decisions) ──── */}
      <section style={styles.auditWindow}>
        <header style={styles.auditHeader}>
          <div>
            <div style={styles.eyebrow}>Chain of Custody · Context Events</div>
            <h2
              style={{ ...styles.auditTitle, cursor: 'pointer' }}
              onClick={() => setEventsExpanded(!eventsExpanded)}
              title={eventsExpanded ? 'Collapse' : 'Expand'}
            >
              {eventsExpanded ? '▼' : '▶'} Preservation, Self-Heal &amp; Refusal Events
            </h2>
            <p style={styles.auditSubtitle}>
              Every context-integrity decision the Eye made, from the append-only audit log:
              evidence <strong>PRESERVED</strong>, auto-compaction (<strong>SUMMARIZED</strong> /
              <strong> TRUNCATED</strong>), manual <strong>PINNED</strong>/<strong>UNPINNED</strong>,
              and hard <strong>REFUSED_OVERFLOW</strong> refusals — each with its reason and content hash.
            </p>
          </div>
          <button
            style={{ ...styles.btn, ...styles.btnSecondary }}
            onClick={() => fetchEvents()}
            title="Refresh chain-of-custody events"
          >
            <IconRefresh /> Refresh
          </button>
        </header>

        {eventsError && (
          <div style={styles.errorBox}><strong>Chain-of-custody error:</strong> {eventsError}</div>
        )}

        {eventsExpanded && (
          <>
            {events && events.length > 0 && (
              <div style={{ ...styles.helpNote, margin: '12px 22px 0' }}>
                <span style={styles.helpNoteIcon}>ⓘ</span>
                <div>
                  {Object.entries(eventCounts).map(([a, n]) => `${a}: ${n}`).join('  ·  ') || 'No events.'}
                </div>
              </div>
            )}
            {eventsLoading && !events ? (
              <div style={styles.timeline}><div style={styles.timelineEmpty}>Loading chain-of-custody events…</div></div>
            ) : (
              <QuestionGroups
                groups={eventGroups}
                openKeys={eventGroupsOpen}
                onToggle={toggleEventGroups}
                search={eventSearch}
                setSearch={setEventSearch}
                placeholder="Search context events by question…"
                unit="events"
                emptyText="No context-integrity events yet (no preservation, compaction, or refusal has occurred)."
                renderItem={renderEvent}
              />
            )}
          </>
        )}
      </section>

      {/* ── Execution Steps (per-step timestamped run history) ─────── */}
      <section style={styles.auditWindow}>
        <header style={styles.auditHeader}>
          <div>
            <div style={styles.eyebrow}>EYE Execution Steps</div>
            <h2
              style={{ ...styles.auditTitle, cursor: 'pointer' }}
              onClick={() => setStepsExpanded(!stepsExpanded)}
              title={stepsExpanded ? 'Collapse' : 'Expand'}
            >
              {stepsExpanded ? '▼' : '▶'} Per-Step Timeline &amp; Timestamps
            </h2>
            <p style={styles.auditSubtitle}>
              Every pipeline step the EYE ran. Group by the investigator <strong>question</strong>
              to see each question's steps in order, or by <strong>step type</strong> for
              run-count aggregates. Each run keeps its exact timestamp and status.
            </p>
            <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
              {(['question', 'step'] as const).map(m => (
                <button
                  key={m}
                  onClick={() => setStepsGroupMode(m)}
                  style={{ ...styles.btn, ...(stepsGroupMode === m ? styles.btnPrimary : styles.btnSecondary), padding: '6px 12px' }}
                  title={m === 'question' ? 'Group steps by the question they ran for' : 'Group steps by step type'}
                >
                  {m === 'question' ? 'Group by Question' : 'Group by Step Type'}
                </button>
              ))}
            </div>
          </div>
          <button
            style={{ ...styles.btn, ...styles.btnSecondary }}
            onClick={() => fetchSteps()}
            title="Refresh step history"
          >
            <IconRefresh /> Refresh
          </button>
        </header>

        {stepsError && (
          <div style={styles.errorBox}>
            <strong>Step history error:</strong> {stepsError}
          </div>
        )}

        {stepsExpanded && (
          stepsLoading && !steps ? (
            <div style={styles.timeline}><div style={styles.timelineEmpty}>Loading execution steps…</div></div>
          ) : stepsGroupMode === 'question' ? (
            <QuestionGroups
              groups={stepQuestionGroups}
              openKeys={stepGroupsOpen}
              onToggle={toggleStepGroups}
              search={stepSearch}
              setSearch={setStepSearch}
              placeholder="Search steps by question…"
              unit="steps"
              emptyText="No steps recorded yet. Run an investigation query to populate this timeline."
              renderItem={renderStepRun}
            />
          ) : (
          <div style={styles.timeline}>
            {(steps || []).length === 0 && (
              <div style={styles.timelineEmpty}>
                No steps recorded yet. Run an investigation query to populate this timeline.
              </div>
            )}
            {(steps || []).map((g) => {
              const last = STEP_STATUS_STYLE(g.last_status || '');
              const isOpen = openStepKey === g.key;
              return (
                <article
                  key={g.key}
                  style={{ ...styles.timelineItem, borderLeftColor: last.fg }}
                >
                  <button
                    onClick={() => setOpenStepKey(isOpen ? null : g.key)}
                    style={styles.timelineRow}
                    title={isOpen ? 'Collapse runs' : 'Show every run of this step'}
                  >
                    <span
                      style={{
                        ...styles.timelineBadge,
                        color: last.fg,
                        background: last.bg,
                        border: `1px solid ${last.border}`,
                      }}
                    >
                      {(g.type || 'step').toUpperCase()}
                    </span>
                    <span style={styles.timelineSummary}>{g.label || '(unnamed step)'}</span>
                    <span style={styles.timelineTools}>
                      {g.run_count} run{g.run_count === 1 ? '' : 's'}
                    </span>
                    <span style={styles.timelineTs}>{formatTs(g.last_timestamp || '')}</span>
                    <span style={styles.timelineCaret}>{isOpen ? '▾' : '▸'}</span>
                  </button>
                  {isOpen && (
                    <div style={{ padding: '4px 0 8px' }}>
                      {g.runs.map((run, ri) => {
                        const rs = STEP_STATUS_STYLE(run.status);
                        return (
                          <div
                            key={`${g.key}-${ri}`}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: '10px',
                              padding: '4px 16px 4px 22px',
                              fontSize: '12px',
                            }}
                          >
                            <span style={{ color: '#64748b', minWidth: '20px' }}>#{ri + 1}</span>
                            <span style={{ ...styles.timelineTs, minWidth: '150px' }}>
                              {formatTs(run.timestamp)}
                            </span>
                            <span
                              style={{
                                ...styles.timelineBadge,
                                color: rs.fg,
                                background: rs.bg,
                                border: `1px solid ${rs.border}`,
                              }}
                            >
                              {rs.label}
                            </span>
                            {run.iteration ? (
                              <span style={{ color: '#94a3b8' }}>Loop {run.iteration}</span>
                            ) : null}
                            {run.tool ? (
                              <span style={styles.timelineTools}>{run.tool}</span>
                            ) : null}
                            {run.detail ? (
                              <span style={{ color: '#94a3b8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {run.detail}
                              </span>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
          )
        )}
      </section>

      {/* ── Eye ↔ LLM Conversation (full reasoning / tools / calls) ── */}
      <section style={styles.auditWindow}>
        <header style={styles.auditHeader}>
          <div>
            <div style={styles.eyebrow}>EYE ↔ LLM Conversation</div>
            <h2
              style={{ ...styles.auditTitle, cursor: 'pointer' }}
              onClick={() => setConvExpanded(!convExpanded)}
              title={convExpanded ? 'Collapse' : 'Expand'}
            >
              {convExpanded ? '▼' : '▶'} Reasoning, Tool Calls &amp; Model Exchange
            </h2>
            <p style={styles.auditSubtitle}>
              The complete exchange between the EYE and the language model for every question:
              the full prompt sent (including the system prompt), the model's reasoning, each tool
              call with its arguments, the results returned, and the final synthesis.
            </p>
          </div>
          <button
            style={{ ...styles.btn, ...styles.btnSecondary }}
            onClick={() => fetchConversations()}
            title="Refresh conversation history"
          >
            <IconRefresh /> Refresh
          </button>
        </header>

        {convError && (
          <div style={styles.errorBox}>
            <strong>Conversation log error:</strong> {convError}
          </div>
        )}

        {convExpanded && (
          <div style={styles.timeline}>
            {convLoading && !conversations && (
              <div style={styles.timelineEmpty}>Loading Eye ↔ LLM conversation…</div>
            )}
            {!convLoading && (conversations || []).length === 0 && (
              <div style={styles.timelineEmpty}>
                No conversation recorded yet. Ask the EYE a question to populate this transcript.
              </div>
            )}
            {convPaged.visible.map((conv, idx) => {
              const isOpen = openConvIdx === idx;
              return (
                <article
                  key={`${conv.started}-${idx}`}
                  style={{ ...styles.timelineItem, borderLeftColor: '#a78bfa' }}
                >
                  <button
                    onClick={() => setOpenConvIdx(isOpen ? null : idx)}
                    style={styles.timelineRow}
                    title={isOpen ? 'Collapse conversation' : 'Show full Eye ↔ LLM exchange'}
                  >
                    <span style={styles.timelineTs}>{formatTs(conv.started)}</span>
                    <span style={styles.timelineSummary}>
                      {conv.query || '(question)'}
                    </span>
                    <span style={styles.timelineTools}>
                      {conv.entry_count} exchange{conv.entry_count === 1 ? '' : 's'}
                    </span>
                    <span style={styles.timelineCaret}>{isOpen ? '▾' : '▸'}</span>
                  </button>
                  {isOpen && (
                    <div style={{ padding: '4px 12px 10px' }}>
                      <EyeDialogue entries={conv.entries} />
                    </div>
                  )}
                </article>
              );
            })}
            <ShowMore paged={convPaged} unit="conversations" />
          </div>
        )}
      </section>

      {/* ── EYE Activity Window ───────────────────────────────────── */}
      <section style={styles.auditWindow}>
        <header style={styles.auditHeader}>
          <div>
            <div style={styles.eyebrow}>EYE Activity Window</div>
            <h2 style={styles.auditTitle}>Queries, Evidence &amp; Report Changes</h2>
            <p style={styles.auditSubtitle}>
              Chronological audit of every query the EYE issued, the evidence each tool call returned,
              and every change made to the forensic report during this session.
            </p>
          </div>
          <div style={styles.auditFilters}>
            {(['all', 'queries', 'evidence', 'report', 'map'] as const).map(f => (
              <button
                key={f}
                onClick={() => setAuditFilter(f)}
                style={{
                  ...styles.filterBtn,
                  ...(auditFilter === f ? styles.filterBtnActive : {}),
                }}
              >
                {f}
              </button>
            ))}
          </div>
        </header>

        {auditError && (
          <div style={styles.errorBox}>
            <strong>Activity log error:</strong> {auditError}
          </div>
        )}

        <div style={{ ...styles.helpNote, margin: '12px 22px 0' }}>
          <span style={styles.helpNoteIcon}>ⓘ</span>
          <div>
            <strong>What you are looking at.</strong> A chronological log of everything the EYE did while
            answering you: every <span style={{ color: '#60a5fa' }}>question</span> you asked, every
            <span style={{ color: '#a78bfa' }}> query the EYE ran</span> (with parameters), the
            <span style={{ color: '#10b981' }}> evidence</span> each query returned, and every
            <span style={{ color: '#34d399' }}> block added</span> /
            <span style={{ color: '#f59e0b' }}> edited</span> /
            <span style={{ color: '#f43f5e' }}> deleted</span> in the report. Click any row to see the full
            content. Use the filter pills above to focus on one stream.
          </div>
        </div>

        <div style={styles.timeline}>
          {auditLoading && !audit && (
            <div style={styles.timelineEmpty}>Loading activity audit…</div>
          )}
          {!auditLoading && filteredAudit.length === 0 && (
            <div style={styles.timelineEmpty}>
              {auditFilter === 'all'
                ? 'No activity recorded yet for this session.'
                : `No "${auditFilter}" activity in this session.`}
            </div>
          )}
          {auditPaged.visible.map((entry, idx) => {
            const s = TYPE_STYLE[entry.type] || TYPE_STYLE.report_other;
            const isOpen = expandedIdx === idx;
            return (
              <article
                key={`${entry.timestamp}-${idx}`}
                style={{ ...styles.timelineItem, borderLeftColor: s.color }}
              >
                <button
                  onClick={() => setExpandedIdx(isOpen ? null : idx)}
                  style={styles.timelineRow}
                  title={isOpen ? 'Collapse' : 'Expand details'}
                >
                  <span style={styles.timelineTs}>{formatTs(entry.timestamp)}</span>
                  <span
                    style={{
                      ...styles.timelineBadge,
                      color: s.color,
                      background: s.bg,
                      border: `1px solid ${s.border}`,
                    }}
                  >
                    {s.label}
                  </span>
                  <span style={styles.timelineSummary}>
                    {entry.iteration ? `[Loop ${entry.iteration}] ` : ''}
                    {entry.summary || '—'}
                  </span>
                  {entry.tools && entry.tools.length > 0 && (
                    <span style={styles.timelineTools}>{entry.tools.join(', ')}</span>
                  )}
                  <span style={styles.timelineCaret}>{isOpen ? '▾' : '▸'}</span>
                </button>
                {isOpen && (
                  <div>
                    <pre style={styles.timelineDetail}>{entry.detail || '(no further detail)'}</pre>
                    {entry.type === 'narrative_map' && entry.card_id && (
                      <button
                        onClick={() => focusNarrativeMap(entry.card_id as string)}
                        title="Open this card's detail panel in the Narrative Map window"
                        style={{
                          margin: '2px 0 8px 12px', padding: '4px 10px', cursor: 'pointer',
                          fontSize: '12px', color: '#a855f7',
                          background: 'rgba(168,85,247,0.12)',
                          border: '1px solid rgba(168,85,247,0.45)', borderRadius: '4px',
                        }}
                      >
                        ↗ View in Narrative Map
                      </button>
                    )}
                  </div>
                )}
              </article>
            );
          })}
          <ShowMore paged={auditPaged} unit="events" />
        </div>
      </section>

      {toast && (
        <div
          style={{
            ...styles.toast,
            borderLeft: `4px solid ${
              toast.type === 'success' ? '#10b981' :
              toast.type === 'error'   ? '#f43f5e' : '#3b82f6'
            }`,
          }}
        >
          {toast.message}
        </div>
      )}
    </div>
  );
};

/* ── Inline styles (kept here so the panel is one self-contained file) ── */
const styles: Record<string, React.CSSProperties> = {
  page: {
    // index.css pins html/body/#root to overflow: hidden for the chat layout's
    // internal scroll containers — so the compliance page must own its own
    // scroll region rather than rely on the browser to scroll the body.
    height: '100vh',
    overflowY: 'auto',
    overflowX: 'hidden',
    background: 'linear-gradient(180deg,#0b1220 0%, #050810 100%)',
    color: '#e5e7eb',
    fontFamily: "'Inter','Segoe UI',system-ui,sans-serif",
    padding: '32px 40px',
    position: 'relative',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 24,
    marginBottom: 28,
    flexWrap: 'wrap',
  },
  eyebrow: {
    fontFamily: "'Space Mono','JetBrains Mono',monospace",
    fontSize: 11,
    letterSpacing: '0.18em',
    textTransform: 'uppercase',
    color: '#3b82f6',
    marginBottom: 6,
  },
  title: {
    margin: 0,
    fontSize: 32,
    fontWeight: 800,
    lineHeight: 1.1,
    background: 'linear-gradient(135deg,#fff 0%,#94a3b8 100%)',
    WebkitBackgroundClip: 'text',
    WebkitTextFillColor: 'transparent',
  },
  subtitle: {
    margin: '10px 0 0',
    fontSize: 14,
    color: '#94a3b8',
    maxWidth: 720,
    lineHeight: 1.6,
  },
  code: {
    fontFamily: "'Space Mono',monospace",
    fontSize: 12,
    background: 'rgba(255,255,255,0.05)',
    padding: '1px 6px',
    borderRadius: 4,
    color: '#60a5fa',
    border: '1px solid rgba(255,255,255,0.08)',
  },
  actions: { display: 'flex', gap: 10, flexWrap: 'wrap' },
  btn: {
    padding: '10px 16px',
    fontSize: 12,
    fontFamily: "'Space Mono','JetBrains Mono',monospace",
    fontWeight: 700,
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
    borderRadius: 8,
    border: '1px solid transparent',
    cursor: 'pointer',
    transition: 'all 0.2s',
    display: 'inline-flex',
    alignItems: 'center',
    gap: 8,
    lineHeight: 1,
  },
  btnPrimary: {
    background: 'rgba(59,130,246,0.15)',
    color: '#60a5fa',
    borderColor: 'rgba(59,130,246,0.5)',
    boxShadow: '0 0 12px rgba(59,130,246,0.18)',
  },
  btnSecondary: {
    background: 'rgba(255,255,255,0.05)',
    color: '#e5e7eb',
    borderColor: 'rgba(255,255,255,0.12)',
  },
  errorBox: {
    background: 'rgba(244,63,94,0.10)',
    border: '1px solid rgba(244,63,94,0.5)',
    color: '#fecaca',
    padding: '12px 16px',
    borderRadius: 10,
    marginBottom: 16,
    fontSize: 13,
  },
  /* How-to-read help banner shown above the rules table and timeline */
  helpNote: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 10,
    background: 'rgba(96,165,250,0.06)',
    border: '1px solid rgba(96,165,250,0.30)',
    color: '#cbd5e1',
    padding: '12px 16px',
    borderRadius: 10,
    marginBottom: 16,
    fontSize: 12.5,
    lineHeight: 1.55,
  },
  helpNoteIcon: {
    color: '#60a5fa',
    fontSize: 14,
    flexShrink: 0,
    lineHeight: 1.55,
  },
  /* Inline mini-badges used in the help banner text */
  tagPass:    { color: '#10b981', fontWeight: 700 },
  tagPartial: { color: '#f59e0b', fontWeight: 700 },
  tagFail:    { color: '#f43f5e', fontWeight: 700 },
  tagNa:      { color: '#94a3b8', fontWeight: 700 },
  /* Per-rule guidance note (rendered under each rule's detail column) */
  ruleGuidance: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 6,
    marginTop: 8,
    padding: '8px 10px',
    background: 'rgba(255,255,255,0.025)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: 6,
    color: '#94a3b8',
    fontSize: 12,
    lineHeight: 1.5,
  },
  ruleGuidanceIcon: {
    color: '#60a5fa',
    fontSize: 12,
    flexShrink: 0,
    lineHeight: 1.5,
  },
  table: {
    background: 'rgba(15,18,24,0.6)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: 14,
    overflow: 'hidden',
    boxShadow: '0 10px 32px rgba(0,0,0,0.4)',
  },
  tableHead: {
    display: 'grid',
    gridTemplateColumns: '50px 1.4fr 130px 2fr',
    gap: 12,
    padding: '14px 18px',
    background: 'rgba(255,255,255,0.04)',
    borderBottom: '1px solid rgba(255,255,255,0.08)',
    fontFamily: "'Space Mono',monospace",
    fontSize: 10,
    letterSpacing: '0.18em',
    textTransform: 'uppercase',
    color: '#94a3b8',
  },
  row: {
    display: 'grid',
    gridTemplateColumns: '50px 1.4fr 130px 2fr',
    gap: 12,
    padding: '16px 18px',
    borderBottom: '1px solid rgba(255,255,255,0.04)',
    alignItems: 'center',
    fontSize: 14,
  },
  colId: { color: '#64748b', fontFamily: "'Space Mono',monospace", fontSize: 12 },
  colName: { display: 'flex', flexDirection: 'column', gap: 4 },
  colStatus: { display: 'flex', justifyContent: 'flex-start' },
  colDetail: { fontSize: 13, lineHeight: 1.5 },
  ruleName: { fontWeight: 700, color: '#f1f5f9', fontSize: 14 },
  ruleBlurb: { fontSize: 12, color: '#94a3b8', lineHeight: 1.45 },
  badge: {
    padding: '4px 10px',
    borderRadius: 999,
    fontFamily: "'Space Mono','JetBrains Mono',monospace",
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
    whiteSpace: 'nowrap',
  },
  toast: {
    position: 'fixed',
    bottom: 30,
    left: '50%',
    transform: 'translateX(-50%)',
    background: '#0f172a',
    color: '#f1f5f9',
    border: '1px solid rgba(255,255,255,0.1)',
    padding: '12px 20px',
    borderRadius: 10,
    fontSize: 13,
    boxShadow: '0 10px 30px rgba(0,0,0,0.6)',
    zIndex: 2000,
  },

  /* ── Activity Audit Window ─────────────────────────────────── */
  auditWindow: {
    marginTop: 28,
    background: 'rgba(15,18,24,0.6)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: 14,
    overflow: 'hidden',
    boxShadow: '0 10px 32px rgba(0,0,0,0.4)',
  },
  auditHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-end',
    gap: 16,
    padding: '18px 22px 14px',
    borderBottom: '1px solid rgba(255,255,255,0.06)',
    background: 'rgba(255,255,255,0.02)',
    flexWrap: 'wrap',
  },
  auditTitle: {
    margin: '4px 0 0',
    fontSize: 18,
    fontWeight: 700,
    color: '#f1f5f9',
    letterSpacing: 0.2,
  },
  auditSubtitle: {
    margin: '6px 0 0',
    fontSize: 12.5,
    color: '#94a3b8',
    maxWidth: 720,
    lineHeight: 1.5,
  },
  auditFilters: {
    display: 'flex',
    gap: 6,
    flexWrap: 'wrap',
  },
  filterBtn: {
    padding: '6px 12px',
    fontSize: 10.5,
    fontFamily: "'Segoe UI','Inter',system-ui,sans-serif",
    fontWeight: 600,
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
    borderRadius: 6,
    border: '1px solid rgba(255,255,255,0.10)',
    background: 'rgba(255,255,255,0.03)',
    color: '#94a3b8',
    cursor: 'pointer',
    transition: 'background 0.15s, color 0.15s, border-color 0.15s',
  },
  filterBtnActive: {
    background: 'rgba(96,165,250,0.12)',
    color: '#60a5fa',
    borderColor: 'rgba(96,165,250,0.45)',
  },
  timeline: {
    maxHeight: 'calc(100vh - 480px)',
    minHeight: 240,
    overflowY: 'auto',
    padding: '8px 0',
  },
  timelineEmpty: {
    padding: '40px 22px',
    textAlign: 'center',
    color: '#64748b',
    fontSize: 13,
  },
  timelineItem: {
    borderLeft: '3px solid #4a90e2',
    margin: '6px 14px',
    background: 'rgba(255,255,255,0.015)',
    borderRadius: 6,
    overflow: 'hidden',
  },
  timelineRow: {
    display: 'grid',
    gridTemplateColumns: '160px 110px 1fr auto 16px',
    gap: 12,
    alignItems: 'center',
    width: '100%',
    background: 'transparent',
    border: 'none',
    color: '#e2e8f0',
    padding: '10px 14px',
    cursor: 'pointer',
    textAlign: 'left',
    fontFamily: "'Segoe UI','Inter',system-ui,sans-serif",
    fontSize: 13,
  },
  timelineTs: {
    fontFamily: "'Space Mono','JetBrains Mono',monospace",
    fontSize: 11,
    color: '#94a3b8',
    whiteSpace: 'nowrap',
  },
  timelineBadge: {
    padding: '3px 8px',
    borderRadius: 999,
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
    textAlign: 'center',
    fontFamily: "'Segoe UI','Inter',system-ui,sans-serif",
  },
  timelineSummary: {
    color: '#e2e8f0',
    fontSize: 13,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  timelineTools: {
    fontFamily: "'Space Mono','JetBrains Mono',monospace",
    fontSize: 10.5,
    color: '#10b981',
    padding: '2px 8px',
    background: 'rgba(16,185,129,0.08)',
    border: '1px solid rgba(16,185,129,0.3)',
    borderRadius: 4,
    whiteSpace: 'nowrap',
  },
  timelineCaret: {
    color: '#64748b',
    fontSize: 12,
    textAlign: 'center',
  },
  timelineDetail: {
    margin: 0,
    padding: '12px 14px 14px 18px',
    background: 'rgba(0,0,0,0.25)',
    borderTop: '1px solid rgba(255,255,255,0.04)',
    color: '#cbd5e1',
    fontFamily: "'Space Mono','JetBrains Mono',monospace",
    fontSize: 11.5,
    lineHeight: 1.55,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    maxHeight: 320,
    overflowY: 'auto',
  },
  diffContainer: {
    marginTop: '8px',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: '6px',
    overflow: 'hidden',
    background: 'rgba(0,0,0,0.2)',
  },
  diffHeader: {
    padding: '6px 12px',
    background: 'rgba(255,255,255,0.03)',
    borderBottom: '1px solid rgba(255,255,255,0.08)',
    fontSize: '11px',
    fontWeight: 'bold',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  diffContent: {
    padding: '8px 12px',
    fontFamily: "'Space Mono','JetBrains Mono',monospace",
    fontSize: '12px',
    lineHeight: '1.5',
    maxHeight: '300px',
    overflowY: 'auto',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-all',
  },
  keptText: {
    color: '#10b981',
    background: 'rgba(16,185,129,0.05)',
  },
  droppedText: {
    color: '#f43f5e',
    background: 'rgba(244,63,94,0.05)',
  },
  offsetBadge: {
    display: 'inline-block',
    padding: '2px 6px',
    borderRadius: '4px',
    fontSize: '10px',
    fontWeight: 'bold',
    cursor: 'pointer',
    marginRight: '6px',
    marginTop: '4px',
    transition: 'all 0.2s',
  },
};

export default ProtocolCompliancePanel;
