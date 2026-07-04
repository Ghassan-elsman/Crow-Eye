/**
 * NarrativeMap
 *
 * The Eye's persistent, court-defensible working memory for a case, rendered as an
 * interactive board. The Eye (a gemma-class LLM) is stateless between turns, so this
 * map is the single place where "what we know and what we have concluded" lives — and
 * its contents are injected into the Eye's prompt every turn.
 *
 * Strict hierarchy:
 *   Verdict   — the top-level conclusion the investigation drives toward (1 per case)
 *     ^ narratives roll up into it
 *   Narrative — a theme / claim being established; has a State (proven/open/negative/
 *               needs/absolute). An Eye narrative never asserts the unsupported.
 *     ^ contains
 *   Evidence  — an artifact-backed fact; inside a narrative, or free (floating in tray)
 *
 * Every mutation — by the Eye OR the investigator — flows through commitMapEdit, is
 * GEP-validated (R9 reason · R10 evidence-link · R11 eye-stamp) and sealed into a
 * backend hash-chained audit. The map hydrates from the active case and live-updates
 * whenever the Eye OR the investigator edits it.
 */
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  isBridgeReady, initializeBridge, getNarrativeMap, commitMapEdit as bridgeCommit, onNarrativeMapUpdated,
  investigateNarrative, onNarrativeInvestigationComplete,
} from './bridge';
import DataViewer from './DataViewer';
import type { DataViewerProps } from './types';
import eyeIcon from './assets/eye_icon.png';
import {
  IconBrain, IconDatabase, IconCircleCheck, IconCircleMinus, IconAlertTriangle,
  IconLockCheck, IconLock, IconFlag, IconLoader, IconPlus, IconMinus, IconMaximize,
  IconSearch, IconChevronRight, IconTrash, IconShieldCheck, IconNote, IconLink, IconUser,
} from './Icons';
import './NarrativeMap.css';

// ── Data model (spec §3) ───────────────────────────────────────────────
export type State = 'proven' | 'open' | 'negative' | 'needs' | 'absolute';
export type Actor = 'eye' | 'investigator';
export interface MapNote { by: Actor | 'system'; text: string; ts?: string }
export interface Evidence {
  id: string; kicker: string; data: string; reason: string; ref: string;
  authoredBy: string; sealed?: string; notes: MapNote[];
  free?: boolean; x?: number; y?: number;
  // Source query + database that produced this evidence (for "Load source rows").
  query?: string; database?: string;
}
export interface Narrative {
  id: string; state: State; title: string; reason: string; authoredBy: string;
  evs: string[]; notes: MapNote[]; collapsed?: boolean;
  // Provenance: how the narrative was raised (e.g. the originating sub-question).
  // Kept as metadata — never shown as the card title.
  meta?: { created_from?: string };
  // Free-form board position (undefined until the investigator drags the card).
  x?: number; y?: number;
}
export type VerdictState = 'open' | 'proven' | 'unproven';
export interface Verdict { id: string; title: string; reason: string; authoredBy: string; state?: VerdictState; x?: number; y?: number }
// A free-floating GLOBAL card — System Identity, Technical Observation, or a note.
// Unconnected by default; floats in the left zone; can be linked later.
export interface Global { id: string; kicker: string; title: string; body: string; authoredBy: string; notes: MapNote[]; x?: number; y?: number }
export interface Link { id: string; from: string; to: string }
export interface MapGraph {
  verdict: Verdict; narratives: Narrative[]; evidence: Record<string, Evidence>;
  globals: Global[]; links: Link[];
}

type MapAction =
  | 'CREATE' | 'EDIT' | 'STATE_CHANGE' | 'ATTACH' | 'DETACH' | 'MAKE_ABSOLUTE'
  | 'MAKE_BASE' | 'MARK_NEGATIVE' | 'NOTE' | 'LINK' | 'UNLINK' | 'DELETE' | 'MOVE';
interface AuditRow {
  seq: number; ts: string; action: string; actor: string; target: string; reason: string;
  gep: { r9: string; r10: string; r11: string };
  prevHash: string; hash: string;
}
type Sel = { k: 'n' | 'e' | 'v' | 'g'; id: string } | null;

// ── Verdict lifecycle (Phase 1): 3 states / 3 colors ────────────────────
const VERDICT_STATE_META: Record<VerdictState, { color: string; label: string }> = {
  open:     { color: 'var(--color-warning)', label: 'Under investigation' },
  proven:   { color: 'var(--color-success)', label: 'Proven' },
  unproven: { color: '#f43f5e',              label: 'Unproven' },
};
const verdictState = (v: Verdict): VerdictState =>
  (v.state === 'proven' || v.state === 'unproven') ? v.state : 'open';

// ── State system (spec §4) — single source of truth ────────────────────
const STATE_META: Record<State, { color: string; label: string; Icon: React.FC<any>; border: 'solid' | 'dashed' }> = {
  proven:   { color: 'var(--color-accent)',  label: 'Proven',   Icon: IconCircleCheck,  border: 'solid'  },
  open:     { color: '#94a3b8',              label: 'Open',     Icon: IconSearch,       border: 'dashed' },
  negative: { color: '#64748b',              label: 'Negative', Icon: IconCircleMinus,  border: 'solid'  },
  needs:    { color: 'var(--color-warning)', label: 'Needs',    Icon: IconAlertTriangle,border: 'dashed' },
  absolute: { color: 'var(--color-success)', label: 'Absolute', Icon: IconLockCheck,    border: 'solid'  },
};
const EV_COLOR = 'var(--color-cyan)';
const SUPPORT_LINK_COLOR = '#8b5cf6'; // narrative→narrative "supports" link
const ALL_STATES: State[] = ['proven', 'open', 'negative', 'needs', 'absolute'];
const EMPTY_NOTE: Record<State, string> = {
  proven: 'no evidence', open: 'investigating — no evidence yet',
  negative: 'checked — nothing found', needs: '⚠ hypothesis — no evidence',
  absolute: 'stipulated fact — no evidence required',
};

const clip = (s: string, n: number) => (s && s.length > n ? s.slice(0, n - 1) + '…' : s || '');

// Strip markdown syntax for the compact card/verdict previews: keep them short
// single-line previews without raw **/#/-/`` symbols (and without rendering
// headings/lists that would blow up a small fixed card).
const stripMd = (s: string) => (s || '')
  .replace(/```[\s\S]*?```/g, ' ')
  .replace(/`([^`]*)`/g, '$1')
  .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
  .replace(/^\s{0,3}#{1,6}\s+/gm, '')
  .replace(/^\s{0,3}>\s?/gm, '')
  .replace(/^\s*[-*+]\s+/gm, '')
  .replace(/^\s*\d+\.\s+/gm, '')
  .replace(/(\*\*|__|\*|_|~~)/g, '')
  .replace(/\s+/g, ' ')
  .trim();

// Full markdown render for the detail-modal / notes / inspector surfaces (where
// the complete reason/evidence text is shown). Reuses the app-wide react-markdown
// + remark-gfm pattern (MessageList / EyeDialogue / ReportBlockComponent).
const Md: React.FC<{ children?: string }> = ({ children }) => (
  <div className="nm-md"><ReactMarkdown remarkPlugins={[remarkGfm]}>{children || ''}</ReactMarkdown></div>
);
function fnv1a(s: string): string {
  let x = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { x ^= s.charCodeAt(i); x = Math.imul(x, 0x01000193) >>> 0; }
  return ('0000000' + x.toString(16)).slice(-8);
}
let _uid = 1000;
const nid = (p: string) => `${p}_${Date.now().toString(36)}_${_uid++}`;
const stampOf = (a: Actor) => (a === 'eye' ? 'eye:gemma-4-31b-it' : 'investigator');
const isEye = (s: string) => (s || '').startsWith('eye');

// ── Empty graph (shown until the active case hydrates from the backend) ──
const EMPTY_GRAPH = (): MapGraph => ({
  verdict: { id: 'verdict', title: 'Overall verdict', reason: 'Synthesis of the narratives below.', authoredBy: 'eye', state: 'open' },
  narratives: [],
  evidence: {},
  globals: [],
  links: [],
});

// ── Component ───────────────────────────────────────────────────────────
export default function NarrativeMap() {
  const init = useMemo(() => EMPTY_GRAPH(), []);
  const [graph, setGraph] = useState<MapGraph>(init);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [actor, setActor] = useState<Actor>('eye');
  const [sel, setSel] = useState<Sel>(null);
  const [tab, setTab] = useState<'inspector' | 'audit'>('inspector');
  const [z, setZ] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [filters, setFilters] = useState<Set<State>>(new Set(ALL_STATES));
  const [search, setSearch] = useState('');
  const [wires, setWires] = useState<{ id: string; d: string; color: string; dashed: boolean; dim: boolean; support?: boolean; from: string; to: string }[]>([]);
  const [pulse, setPulse] = useState<Set<string>>(new Set());
  const [menu, setMenu] = useState<{ x: number; y: number; kind: 'narrative' | 'evidence'; id: string; mode: 'root' | 'note' | 'link' | 'unlink' } | null>(null);
  const [menuNote, setMenuNote] = useState('');
  const [caseName, setCaseName] = useState<string>('');
  const [chainOk, setChainOk] = useState(true);
  // Evidence-detail window (double-click an evidence card).
  const [evDetail, setEvDetail] = useState<Evidence | null>(null);
  // Narrative currently being (re)investigated by the Eye (right-click "Dive deeper") — spinner.
  const [investigatingId, setInvestigatingId] = useState<string | null>(null);
  // Narrative-detail window (double-click a narrative card).
  const [narrDetail, setNarrDetail] = useState<Narrative | null>(null);

  // edit drafts
  const [titleDraft, setTitleDraft] = useState('');
  const [reasonDraft, setReasonDraft] = useState('');
  const [noteDraft, setNoteDraft] = useState('');

  // Live link-drag (connector handle → target).
  const [linkDrag, setLinkDrag] = useState<{ from: string; x0: number; y0: number; x: number; y: number } | null>(null);

  const worldRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const prevHashRef = useRef('GENESIS');
  const seqRef = useRef(0);
  const seenHashes = useRef<Set<string>>(new Set());
  const dragRef = useRef<any>(null);
  const panRef = useRef<any>(null);
  // Distinguishes single-click (select) from double-click (detail window) in onUp,
  // since the drag captures the pointer and suppresses native click/dblclick.
  const lastTapRef = useRef<{ id: string; t: number } | null>(null);

  const [live, setLive] = useState(isBridgeReady());

  // ── helpers ────────────────────────────────────────────────────────
  const narrativeOf = useCallback((id: string) => graph.narratives.find(n => n.id === id), [graph]);
  const ownerOf = useCallback((eid: string) => graph.narratives.find(n => n.evs.includes(eid)), [graph]);
  const freeEvidence = useMemo(() => Object.values(graph.evidence).filter(e => e.free || !graph.narratives.some(n => n.evs.includes(e.id))), [graph]);
  const provenCount = useMemo(() => graph.narratives.filter(n => n.state === 'proven' || n.state === 'absolute').length, [graph]);

  // Real rendered card heights (measured after paint, see the effect below), so the
  // column de-overlap stacks cards by their TRUE height and can never leave two cards
  // overlapping. Empty on first paint → computeTreeLayout falls back to its estimate.
  const [cardH, setCardH] = useState<Record<string, number>>({});

  // Auto tree-layout (default positions); an explicit dragged x/y overrides it.
  const layout = useMemo(() => computeTreeLayout(graph, cardH), [graph, cardH]);

  // Clamp the canvas pan so the cards can never be dragged fully out of view — the
  // reachable area is the content bounding box (which grows with card density).
  const clampPan = useCallback((p: { x: number; y: number }, zoom: number) => {
    const canvas = canvasRef.current; if (!canvas) return p;
    const W = canvas.clientWidth, H = canvas.clientHeight;
    const bb = contentBBox(graph, layout);
    const KEEP = 160; // always keep at least this many px of content on screen
    const minPx = KEEP - bb.maxX * zoom, maxPx = W - KEEP - bb.minX * zoom;
    const minPy = KEEP - bb.maxY * zoom, maxPy = H - KEEP - bb.minY * zoom;
    return {
      x: minPx <= maxPx ? Math.max(minPx, Math.min(maxPx, p.x)) : p.x,
      y: minPy <= maxPy ? Math.max(minPy, Math.min(maxPy, p.y)) : p.y,
    };
  }, [graph, layout]);

  // Trace: when a narrative is selected, the set of ids on its branch (itself +
  // ancestors up to the verdict + descendants) so we can highlight it and dim the rest.
  const traceSet = useMemo(() => {
    if (!sel || sel.k !== 'n') return null;
    const parentOf: Record<string, string> = {};
    graph.links.forEach(l => { if (l.from && !(l.from in parentOf)) parentOf[l.from] = l.to; });
    const childrenOf: Record<string, string[]> = {};
    graph.links.forEach(l => { (childrenOf[l.to] ||= []).push(l.from); });
    const set = new Set<string>([sel.id]);
    // ancestors → verdict
    let cur: string | undefined = sel.id;
    const guard = new Set<string>();
    while (cur && parentOf[cur] && !guard.has(cur)) { guard.add(cur); cur = parentOf[cur]; set.add(cur); }
    // descendants
    const stack = [sel.id];
    while (stack.length) {
      const id = stack.pop()!;
      (childrenOf[id] || []).forEach(c => { if (!set.has(c)) { set.add(c); stack.push(c); } });
    }
    return set;
  }, [sel, graph.links]);

  const pulseCards = useCallback((ids: string[]) => {
    if (!ids.length) return;
    setPulse(new Set(ids));
    window.setTimeout(() => setPulse(new Set()), 1100);
  }, []);

  // ── connect to the Python bridge, then hydrate from the active case ──
  // The map opens in its own window, so it must initialize the QWebChannel
  // bridge itself (ChatInterface does the same for the main window). Once the
  // bridge is ready we load the real case graph and subscribe to live updates;
  // every edit (Eye or investigator) is then persisted + sealed by the backend.
  useEffect(() => {
    try {
      const p = new URLSearchParams(window.location.search);
      setCaseName(p.get('case') || '');
    } catch { /* */ }

    let off: (() => void) | undefined;
    let cancelled = false;

    const hydrate = () => {
      getNarrativeMap().then((raw) => {
        if (cancelled || !raw) return;
        try {
          const d = JSON.parse(raw);
          if (d && (d.narratives || d.verdict)) {
            setGraph(normalize(d));
            if (Array.isArray(d.audit)) setAudit(d.audit.map(fromBackendAudit));
            if (typeof d.chain_intact === 'boolean') setChainOk(d.chain_intact);
          }
        } catch (e) { console.error('hydrate failed', e); }
      });
      off = onNarrativeMapUpdated((env) => {
        try {
          const e = JSON.parse(env);
          if (e.kind === 'graph' && e.graph) setGraph(normalize(e.graph));
          if (e.audit) addAuditRow(fromBackendAudit(e.audit));
          const ids = e.change?.ids || [];
          if (ids.length) pulseCards(ids);
        } catch (err) { console.error('live update failed', err); }
      });
    };

    initializeBridge()
      .then(() => { if (cancelled) return; setLive(true); hydrate(); })
      .catch((err) => { console.error('Narrative Map: bridge init failed', err); });

    const offInvestigate = onNarrativeInvestigationComplete((id) => {
      setInvestigatingId(cur => (cur === id ? null : cur));
    });

    return () => { cancelled = true; if (off) off(); offInvestigate(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── compliance choke point: every mutation goes through here ────────
  const addAuditRow = useCallback((row: AuditRow) => {
    if (row.hash && seenHashes.current.has(row.hash)) return;
    if (row.hash) seenHashes.current.add(row.hash);
    setAudit(a => [row, ...a].slice(0, 400));
  }, []);

  const record = useCallback((action: MapAction, target: string, reason: string, evRefs: string[], event: any) => {
    seqRef.current += 1;
    const seq = seqRef.current;
    const ts = new Date().toISOString();
    const gep = {
      r9: reason.trim() ? 'PASS' : 'FAIL',
      r10: evRefs.length ? 'PASS' : (event.kind === 'narrative' && action !== 'NOTE' ? 'PARTIAL' : 'N-A'),
      r11: actor === 'eye' ? 'PASS' : 'N-A',
    };
    const body = [seq, action, actor, target, reason, evRefs.join(','), gep.r9 + gep.r10 + gep.r11].join('|');
    const finish = (hash: string) => {
      const row: AuditRow = { seq, ts, action, actor, target, reason, gep, prevHash: prevHashRef.current, hash };
      prevHashRef.current = hash;
      addAuditRow(row);
    };
    const payload = JSON.stringify({ ...event, action, actor, reason, evidence: evRefs, label: target });
    if (live) {
      bridgeCommit(payload).then((res) => {
        if (res && res.ok) finish(res.seal_hash || fnv1a(prevHashRef.current + '::' + body));
        else if (res && !res.ok) { /* backend rejected — surface as a failed row */ finish(fnv1a(prevHashRef.current + '::REJECT::' + body)); }
        else finish(fnv1a(prevHashRef.current + '::' + body));
      }).catch(() => finish(fnv1a(prevHashRef.current + '::' + body)));
    } else {
      finish(fnv1a(prevHashRef.current + '::' + body));
    }
  }, [actor, live, addAuditRow]);

  // ── wire measurement (narrative → verdict roll-up + narrative → narrative support) ──
  const computeWires = useCallback(() => {
    const world = worldRef.current;
    if (!world) return;
    const vEl = world.querySelector<HTMLElement>('[data-verdict]');
    const vx = vEl ? vEl.offsetLeft : 0, vy = vEl ? vEl.offsetTop + vEl.offsetHeight / 2 : 0;
    const q = search.trim().toLowerCase();
    const next = graph.links.map((lk) => {
      // The link source may be a narrative OR a (later-linked) global card.
      const gFrom = graph.globals.find(c => c.id === lk.from);
      const a = world.querySelector<HTMLElement>(`[data-narr="${lk.from}"]`)
        || (gFrom ? world.querySelector<HTMLElement>(`[data-global="${lk.from}"]`) : null);
      if (!a) return null;
      const n = narrativeOf(lk.from);
      if (!gFrom && (!n || !filters.has(n.state))) return null;
      const srcColor = gFrom ? '#64748b' : STATE_META[n!.state].color;
      const srcDashed = gFrom ? true : (n!.state === 'open' || n!.state === 'needs');
      const dim = !gFrom && !!q && !(`${n!.title} ${n!.reason}`.toLowerCase().includes(q));
      const toVerdict = lk.to === graph.verdict.id;
      if (toVerdict) {
        if (!vEl) return null;
        const x1 = a.offsetLeft + a.offsetWidth, y1 = a.offsetTop + a.offsetHeight / 2;
        const dx = Math.max(40, (vx - x1) / 2);
        const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${vx - dx} ${vy}, ${vx} ${vy}`;
        return { id: lk.id, d, color: srcColor, dashed: srcDashed, dim, support: false, from: lk.from, to: lk.to };
      }
      // narrative → narrative branch link (child → parent). Flow from the child's
      // edge that FACES the parent into the parent's facing edge, so the branch
      // reads correctly whichever side the parent is on (a child sits left of its
      // parent in the auto tree-layout, but a manual drag can flip that).
      const b = world.querySelector<HTMLElement>(`[data-narr="${lk.to}"]`);
      const tn = narrativeOf(lk.to);
      if (!b || !tn || !filters.has(tn.state)) return null;
      const ay = a.offsetTop + a.offsetHeight / 2, by = b.offsetTop + b.offsetHeight / 2;
      const parentRight = b.offsetLeft >= a.offsetLeft;
      const x1 = parentRight ? a.offsetLeft + a.offsetWidth : a.offsetLeft;
      const x2 = parentRight ? b.offsetLeft : b.offsetLeft + b.offsetWidth;
      const dx = Math.max(40, Math.abs(x2 - x1) / 2) * (parentRight ? 1 : -1);
      const d = `M ${x1} ${ay} C ${x1 + dx} ${ay}, ${x2 - dx} ${by}, ${x2} ${by}`;
      return { id: lk.id, d, color: gFrom ? srcColor : SUPPORT_LINK_COLOR, dashed: gFrom ? true : false, dim, support: true, from: lk.from, to: lk.to };
    }).filter(Boolean) as any[];
    setWires(next);
  }, [graph, filters, search, narrativeOf]);
  useLayoutEffect(() => { computeWires(); }, [computeWires, z, pan, cardH]);

  // ── measure real card heights → feed the column de-overlap so cards can never
  //    stack on top of each other (an expanded card with lots of evidence is much
  //    taller than any fixed guess). offsetHeight is the card's unscaled layout
  //    height (the world's zoom transform doesn't affect it). The change-guard
  //    (only setState when a height actually differs) makes this converge in ~2
  //    passes and prevents a render loop. ──
  useLayoutEffect(() => {
    const world = worldRef.current; if (!world) return;
    const next: Record<string, number> = {};
    world.querySelectorAll<HTMLElement>('[data-narr],[data-global]').forEach(el => {
      const id = el.getAttribute('data-narr') || el.getAttribute('data-global');
      if (id) next[id] = el.offsetHeight;
    });
    setCardH(prev => {
      const keys = new Set([...Object.keys(prev), ...Object.keys(next)]);
      for (const k of keys) {
        if (Math.abs((prev[k] || 0) - (next[k] || 0)) > 1) return next;
      }
      return prev;
    });
  }, [graph, filters]);

  // ── selection ──────────────────────────────────────────────────────
  const select = useCallback((s: Sel) => {
    setSel(s);
    setTab('inspector');
    if (!s) return;
    const o: any = s.k === 'n' ? narrativeOf(s.id) : s.k === 'e' ? graph.evidence[s.id] : s.k === 'g' ? graph.globals.find(c => c.id === s.id) : graph.verdict;
    if (o) { setTitleDraft(o.title ?? o.data ?? ''); setReasonDraft(o.reason ?? o.body ?? ''); setNoteDraft(''); }
  }, [graph, narrativeOf]);

  const selObj: any = sel ? (sel.k === 'n' ? narrativeOf(sel.id) : sel.k === 'e' ? graph.evidence[sel.id] : sel.k === 'g' ? graph.globals.find(c => c.id === sel.id) : graph.verdict) : null;

  // ── mutations ──────────────────────────────────────────────────────
  const addNarrative = () => {
    const id = nid('n');
    // An Eye narrative may not assert the unsupported: a brand-new Eye narrative
    // starts 'open' (investigating). Investigator narratives start as 'needs'.
    const state: State = actor === 'eye' ? 'open' : 'needs';
    const n: Narrative = {
      id, state, title: 'New narrative', reason: 'Describe the claim and why it matters.',
      authoredBy: stampOf(actor), evs: [], notes: [],
    };
    setGraph(g => ({ ...g, narratives: [...g.narratives, n], links: [...g.links, { id: nid('l'), from: id, to: g.verdict.id }] }));
    select({ k: 'n', id }); pulseCards([id]);
    record('CREATE', n.title, n.reason, [], { kind: 'narrative', id, object: n });
  };
  // Investigator-added global card — floats in the left zone, unconnected.
  const addGlobalNote = () => {
    const id = nid('g');
    const c: Global = { id, kicker: 'note', title: 'New note', body: 'A global observation not tied to a narrative.', authoredBy: stampOf(actor), notes: [] };
    setGraph(g => ({ ...g, globals: [...g.globals, c] }));
    select({ k: 'g', id }); pulseCards([id]);
    record('CREATE', c.title, c.body, [], { kind: 'global', id, object: c });
  };
  const addEvidence = (hostId?: string) => {
    const host = hostId ? narrativeOf(hostId)
      : sel?.k === 'n' ? narrativeOf(sel.id) : sel?.k === 'e' ? ownerOf(sel.id) : graph.narratives[0];
    const id = nid('e');
    const e: Evidence = {
      id, kicker: 'artifact', data: 'New evidence', reason: 'Why this supports the narrative.',
      ref: 'db:table:rowid', authoredBy: stampOf(actor), notes: [], free: !host,
    };
    setGraph(g => {
      const evidence = { ...g.evidence, [id]: e };
      const narratives = host ? g.narratives.map(n => n.id === host.id ? { ...n, evs: [...n.evs, id] } : n) : g.narratives;
      return { ...g, evidence, narratives };
    });
    select({ k: 'e', id }); if (host) pulseCards([host.id]);
    record('CREATE', e.data, e.reason, [e.ref], { kind: 'evidence', id, object: e, to: host?.id });
  };
  const saveEdits = () => {
    if (!sel) return;
    const stamp = stampOf(actor);
    if (sel.k === 'n') setGraph(g => ({ ...g, narratives: g.narratives.map(n => n.id === sel.id ? { ...n, title: titleDraft, reason: reasonDraft, authoredBy: stamp } : n) }));
    else if (sel.k === 'e') setGraph(g => ({ ...g, evidence: { ...g.evidence, [sel.id]: { ...g.evidence[sel.id], data: titleDraft, reason: reasonDraft, authoredBy: stamp } } }));
    else if (sel.k === 'g') setGraph(g => ({ ...g, globals: g.globals.map(c => c.id === sel.id ? { ...c, title: titleDraft, body: reasonDraft, authoredBy: stamp } : c) }));
    else setGraph(g => ({ ...g, verdict: { ...g.verdict, title: titleDraft, reason: reasonDraft, authoredBy: stamp } }));
    const refs = sel.k === 'e' ? [graph.evidence[sel.id].ref] : [];
    record('EDIT', titleDraft, reasonDraft, refs,
      { kind: sel.k === 'n' ? 'narrative' : sel.k === 'e' ? 'evidence' : sel.k === 'g' ? 'global' : 'verdict',
        id: sel.id, patch: sel.k === 'g' ? { title: titleDraft, body: reasonDraft } : { title: titleDraft, reason: reasonDraft } });
    pulseCards([sel.id]);
  };
  // Explicit-target state change (works from the Inspector AND the context menu,
  // independent of the async `sel` state). Returns false if blocked by a GEP rule.
  const changeState = (next: State, targetId?: string, reasonArg?: string): boolean => {
    const id = targetId ?? (sel?.k === 'n' ? sel.id : undefined);
    if (!id) return false;
    const n = narrativeOf(id); if (!n) return false;
    // Authorship rule: an Eye narrative cannot be 'proven' with zero evidence.
    if (isEye(n.authoredBy) && next === 'proven' && n.evs.length === 0) {
      window.alert('An Eye narrative cannot be marked proven with no evidence (GEP R10). Attach evidence first.');
      return false;
    }
    // Only investigator may move a narrative into needs/absolute (0-evidence states).
    if ((next === 'needs' || next === 'absolute') && actor !== 'investigator') {
      window.alert('Only the investigator may stipulate a hypothesis (needs) or absolute fact.');
      return false;
    }
    setGraph(g => ({ ...g, narratives: g.narratives.map(x => x.id === n.id ? { ...x, state: next } : x) }));
    const action: MapAction = next === 'negative' ? 'MARK_NEGATIVE' : next === 'absolute' ? 'MAKE_ABSOLUTE' : next === 'needs' ? 'MAKE_BASE' : 'STATE_CHANGE';
    const reason = reasonArg || (targetId ? n.reason : (reasonDraft || n.reason)) || `State set to ${next}.`;
    record(action, n.title, reason, n.evs.map(eid => graph.evidence[eid]?.ref).filter(Boolean) as string[], { kind: 'narrative', id: n.id, state: next });
    pulseCards([n.id]);
    return true;
  };
  // Explicit-target note (context menu); the Inspector wraps it with sel + draft.
  const addNoteTo = (target: { k: 'n' | 'e'; id: string }, text: string) => {
    const t = text.trim(); if (!t) return;
    const note: MapNote = { by: actor, text: t, ts: new Date().toISOString() };
    let label = '';
    if (target.k === 'n') {
      const n = narrativeOf(target.id); label = n?.title ?? '';
      setGraph(g => ({ ...g, narratives: g.narratives.map(x => x.id === target.id ? { ...x, notes: [...x.notes, note] } : x) }));
    } else {
      const e = graph.evidence[target.id]; label = e?.data ?? '';
      setGraph(g => ({ ...g, evidence: { ...g.evidence, [target.id]: { ...g.evidence[target.id], notes: [...g.evidence[target.id].notes, note] } } }));
    }
    record('NOTE', label, `note: ${t}`, [], { kind: target.k === 'n' ? 'narrative' : 'evidence', id: target.id, note });
    pulseCards([target.id]);
  };
  const addNote = () => {
    if (!sel || sel.k === 'v' || sel.k === 'g' || !noteDraft.trim()) return;
    addNoteTo({ k: sel.k, id: sel.id }, noteDraft);
    setNoteDraft('');
  };
  const deleteCard = (k: 'n' | 'e' | 'g', id: string) => {
    if (k === 'g') {
      const c = graph.globals.find(g => g.id === id); if (!c) return;
      setGraph(g => ({ ...g, globals: g.globals.filter(gc => gc.id !== id), links: g.links.filter(l => l.from !== id && l.to !== id) }));
      record('DELETE', c.title, 'Removed the global card.', [], { kind: 'global', id });
      setSel(null);
      return;
    }
    if (k === 'n') {
      const n = narrativeOf(id); if (!n) return;
      setGraph(g => ({ ...g, narratives: g.narratives.filter(x => x.id !== id), links: g.links.filter(l => l.from !== id) }));
      record('DELETE', n.title, reasonDraft || 'Removed narrative.', [], { kind: 'narrative', id });
    } else {
      const e = graph.evidence[id]; if (!e) return;
      setGraph(g => {
        const evidence = { ...g.evidence }; delete evidence[id];
        return { ...g, evidence, narratives: g.narratives.map(n => ({ ...n, evs: n.evs.filter(x => x !== id) })) };
      });
      record('DELETE', e.data, 'Removed evidence.', [e.ref], { kind: 'evidence', id });
    }
    if (sel?.id === id) setSel(null);
  };
  const toggleCollapse = (id: string) => setGraph(g => ({ ...g, narratives: g.narratives.map(n => n.id === id ? { ...n, collapsed: !n.collapsed } : n) }));

  // evidence move between narratives / tray (ATTACH / DETACH)
  const moveEvidence = (eid: string, toNarrative: string | null, index?: number) => {
    const from = ownerOf(eid);
    if (from?.id === toNarrative) {
      // reorder within same narrative
      setGraph(g => ({ ...g, narratives: g.narratives.map(n => {
        if (n.id !== from.id) return n;
        const arr = n.evs.filter(x => x !== eid); arr.splice(index ?? arr.length, 0, eid); return { ...n, evs: arr };
      }) }));
      return;
    }
    setGraph(g => {
      let narratives = g.narratives.map(n => n.evs.includes(eid) ? { ...n, evs: n.evs.filter(x => x !== eid) } : n);
      const evidence = { ...g.evidence, [eid]: { ...g.evidence[eid], free: !toNarrative } };
      if (toNarrative) narratives = narratives.map(n => {
        if (n.id !== toNarrative) return n;
        const arr = n.evs.slice(); arr.splice(index ?? arr.length, 0, eid); return { ...n, evs: arr };
      });
      // Auto-convert a checked Eye narrative that just lost its last evidence.
      narratives = narratives.map(n => (from && n.id === from.id && isEye(n.authoredBy) && n.evs.length === 0 && n.state === 'proven')
        ? { ...n, state: 'negative' } : n);
      return { ...g, narratives, evidence };
    });
    const ev = graph.evidence[eid];
    if (toNarrative) {
      const to = narrativeOf(toNarrative);
      record('ATTACH', ev?.data ?? eid, `Attached to “${clip(to?.title ?? '', 24)}”.`, [ev?.ref].filter(Boolean) as string[], { kind: 'narrative', id: toNarrative, evidenceId: eid, from: from?.id });
    } else {
      record('DETACH', ev?.data ?? eid, `Detached from “${clip(from?.title ?? '', 24)}” (now free).`, [ev?.ref].filter(Boolean) as string[], { kind: 'evidence', id: eid, evidenceId: eid, from: from?.id });
    }
    pulseCards([toNarrative, from?.id].filter(Boolean) as string[]);
  };

  // General narrative→narrative / narrative→verdict link.
  const linkNarratives = (from: string, to: string) => {
    if (!from || !to || from === to) return;
    if (graph.links.some(l => l.from === from && l.to === to)) return;
    const id = nid('l');
    setGraph(g => ({ ...g, links: [...g.links, { id, from, to }] }));
    const fn = narrativeOf(from);
    const toLabel = to === graph.verdict.id ? 'the verdict' : `“${clip(narrativeOf(to)?.title ?? '', 24)}”`;
    record('LINK', fn?.title ?? from, `Linked narrative to ${toLabel}.`, [], { kind: 'narrative', id: from, from, to });
    pulseCards([from, to]);
  };
  const unlink = (linkId: string) => {
    const lk = graph.links.find(l => l.id === linkId); if (!lk) return;
    setGraph(g => ({ ...g, links: g.links.filter(l => l.id !== linkId) }));
    const fn = narrativeOf(lk.from);
    record('UNLINK', fn?.title ?? lk.from, 'Removed a narrative link.', [], { kind: 'narrative', id: lk.from, link_id: linkId, from: lk.from, to: lk.to });
  };
  // Free-form placement: drop a narrative card at an absolute (x, y) on the board.
  const moveNarrativePos = (id: string, x: number, y: number) => {
    const node = narrativeOf(id); if (!node) return;
    x = Math.round(x); y = Math.round(y);
    setGraph(g => ({ ...g, narratives: g.narratives.map(n => n.id === id ? { ...n, x, y } : n) }));
    record('MOVE', node.title, 'Moved on the board.', [], { kind: 'narrative', id, x, y });
  };
  const moveVerdictPos = (x: number, y: number) => {
    x = Math.round(x); y = Math.round(y);
    setGraph(g => ({ ...g, verdict: { ...g.verdict, x, y } }));
    record('MOVE', graph.verdict.title, 'Moved the verdict on the board.', [], { kind: 'verdict', id: graph.verdict.id, x, y });
  };
  const moveGlobalPos = (id: string, x: number, y: number) => {
    const c = graph.globals.find(g => g.id === id); if (!c) return;
    x = Math.round(x); y = Math.round(y);
    setGraph(g => ({ ...g, globals: g.globals.map(gc => gc.id === id ? { ...gc, x, y } : gc) }));
    record('MOVE', c.title, 'Moved the global card on the board.', [], { kind: 'global', id, x, y });
  };
  // Set the verdict's lifecycle state (under-investigation / proven / unproven).
  const setVerdictState = (state: VerdictState) => {
    setGraph(g => ({ ...g, verdict: { ...g.verdict, state } }));
    record('STATE_CHANGE', graph.verdict.title, `Verdict marked ${state}.`, [], { kind: 'verdict', id: graph.verdict.id, state });
  };
  // Double-click a narrative → the Eye investigates it deeper in the background
  // (new evidence attaches to this card; no chat bubble). Spinner shows on the card.
  const investigate = (id: string) => {
    if (!live || investigatingId) return;
    setInvestigatingId(id);
    investigateNarrative(id);
    // Safety: clear the spinner if the completion signal is somehow missed.
    window.setTimeout(() => setInvestigatingId(cur => (cur === id ? null : cur)), 150000);
  };

  // ── pointer: pan · evidence drag · card free-drag (2D) · link drag ───
  const onCanvasPointerDown = (e: React.PointerEvent) => {
    if (menu) setMenu(null);
    if (e.button !== 0) return; // only the left button drags/selects; right-click → context menu
    const t = e.target as Element;
    // 1) link connector handle → start a link drag
    const linkH = t.closest<HTMLElement>('[data-linkfrom]');
    if (linkH) {
      const from = linkH.getAttribute('data-linkfrom')!;
      dragRef.current = { kind: 'link', from, sx: e.clientX, sy: e.clientY, moved: false };
      setLinkDrag({ from, x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY });
      try { (canvasRef.current as any)?.setPointerCapture?.(e.pointerId); } catch { /* */ }
      return;
    }
    // 2) evidence card → attach/detach drag
    const evCard = t.closest<HTMLElement>('[data-ev]');
    if (evCard) {
      const id = evCard.getAttribute('data-ev')!;
      dragRef.current = { kind: 'ev', id, el: evCard, sx: e.clientX, sy: e.clientY, moved: false };
      try { evCard.setPointerCapture(e.pointerId); } catch { /* */ }
      return;
    }
    // 3) narrative card → free 2D drag (grab anywhere on the card except a button)
    const narrCard = t.closest<HTMLElement>('[data-narr]');
    if (narrCard && !t.closest('button')) {
      const id = narrCard.getAttribute('data-narr')!;
      dragRef.current = { kind: 'narr', id, el: narrCard, sx: e.clientX, sy: e.clientY, moved: false };
      try { (canvasRef.current as any)?.setPointerCapture?.(e.pointerId); } catch { /* */ }
      return;
    }
    // 4) verdict card → free 2D drag
    const vCard = t.closest<HTMLElement>('[data-verdict]');
    if (vCard && !t.closest('button')) {
      dragRef.current = { kind: 'verdict', id: graph.verdict.id, el: vCard, sx: e.clientX, sy: e.clientY, moved: false };
      try { (canvasRef.current as any)?.setPointerCapture?.(e.pointerId); } catch { /* */ }
      return;
    }
    // 4b) global card → free 2D drag
    const gCard = t.closest<HTMLElement>('[data-global]');
    if (gCard && !t.closest('button')) {
      dragRef.current = { kind: 'global', id: gCard.getAttribute('data-global')!, el: gCard, sx: e.clientX, sy: e.clientY, moved: false };
      try { (canvasRef.current as any)?.setPointerCapture?.(e.pointerId); } catch { /* */ }
      return;
    }
    // 5) pan on EMPTY canvas only. A press inside a card/verdict/global that reached
    // here is on an interactive child (e.g. the collapse chevron) — let it click;
    // don't start a pan (which would capture the pointer and swallow the click).
    if (t.closest('[data-narr]') || t.closest('[data-verdict]') || t.closest('[data-global]')) return;
    panRef.current = { sx: e.clientX, sy: e.clientY, ox: pan.x, oy: pan.y };
    (canvasRef.current as any)?.setPointerCapture?.(e.pointerId);
  };

  useEffect(() => {
    const canvas = canvasRef.current; if (!canvas) return;
    const dropTarget = (x: number, y: number): { kind: 'narr' | 'tray'; id?: string } | null => {
      const el = document.elementFromPoint(x, y);
      const body = el?.closest<HTMLElement>('[data-body]');
      if (body) return { kind: 'narr', id: body.getAttribute('data-body')! };
      if (el?.closest('[data-tray]')) return { kind: 'tray' };
      return null;
    };
    const narrAt = (x: number, y: number): string | null => {
      const el = document.elementFromPoint(x, y);
      const card = el?.closest<HTMLElement>('[data-narr]');
      if (card) return card.getAttribute('data-narr');
      if (el?.closest('[data-verdict]')) return graph.verdict.id;
      return null;
    };
    const onMove = (e: PointerEvent) => {
      if (panRef.current) {
        setPan(clampPan({ x: panRef.current.ox + (e.clientX - panRef.current.sx), y: panRef.current.oy + (e.clientY - panRef.current.sy) }, z));
        return;
      }
      const d = dragRef.current; if (!d) return;
      const dx = e.clientX - d.sx, dy = e.clientY - d.sy;
      const movedNow = Math.abs(dx) + Math.abs(dy) > 4;

      if (d.kind === 'link') {
        if (movedNow) d.moved = true;
        setLinkDrag(ld => ld ? { ...ld, x: e.clientX, y: e.clientY } : null);
        const tgt = narrAt(e.clientX, e.clientY);
        canvas.querySelectorAll('[data-narr],[data-verdict]').forEach(b => {
          const bid = b.getAttribute('data-narr') || (b.hasAttribute('data-verdict') ? graph.verdict.id : '');
          b.classList.toggle('nm-link-target', !!tgt && bid === tgt && tgt !== d.from);
        });
        return;
      }
      if (d.kind === 'narr' || d.kind === 'verdict' || d.kind === 'global') {
        // Free 2D move — card follows the cursor. The world is scaled by `z`, so
        // divide the screen delta by z to keep the card under the pointer.
        if (movedNow) { d.moved = true; d.el.classList.add('nm-dragging'); }
        if (d.moved) d.el.style.transform = `translate(${dx / z}px, ${dy / z}px)`;
        return;
      }
      // evidence drag
      if (movedNow) {
        d.moved = true;
        d.el.classList.add('nm-dragging');
        d.el.style.transform = `translate(${dx / z}px,${dy / z}px) scale(1.04)`;
        const tgt = dropTarget(e.clientX, e.clientY);
        canvas.querySelectorAll('[data-body]').forEach(b => b.classList.toggle('nm-drop', tgt?.kind === 'narr' && b.getAttribute('data-body') === tgt.id));
        canvas.querySelectorAll('[data-tray]').forEach(b => b.classList.toggle('nm-drop', tgt?.kind === 'tray'));
      }
    };
    const onUp = (e: PointerEvent) => {
      if (panRef.current) { panRef.current = null; return; }
      const d = dragRef.current; if (!d) return; dragRef.current = null;
      const dx = e.clientX - d.sx, dy = e.clientY - d.sy;

      if (d.kind === 'link') {
        setLinkDrag(null);
        canvas.querySelectorAll('.nm-link-target').forEach(b => b.classList.remove('nm-link-target'));
        const tgt = narrAt(e.clientX, e.clientY);
        if (tgt && tgt !== d.from) linkNarratives(d.from, tgt);
        return;
      }
      if (d.kind === 'narr' || d.kind === 'verdict' || d.kind === 'global') {
        d.el.classList.remove('nm-dragging'); d.el.style.transform = '';
        if (!d.moved) {
          // Tap: single-click selects, double-click (same card <350ms) opens detail.
          if (d.kind === 'verdict') { select({ k: 'v', id: graph.verdict.id }); return; }
          if (d.kind === 'global') { select({ k: 'g', id: d.id }); return; }
          const now = Date.now(); const lt = lastTapRef.current;
          if (lt && lt.id === d.id && now - lt.t < 350) {
            lastTapRef.current = null; setNarrDetail(narrativeOf(d.id) || null);
          } else {
            lastTapRef.current = { id: d.id, t: now }; select({ k: 'n', id: d.id });
          }
          return;
        }
        const nx = d.el.offsetLeft + dx / z, ny = d.el.offsetTop + dy / z;
        if (d.kind === 'verdict') moveVerdictPos(nx, ny);
        else if (d.kind === 'global') moveGlobalPos(d.id, nx, ny);
        else moveNarrativePos(d.id, nx, ny);
        return;
      }
      // evidence drag
      d.el.classList.remove('nm-dragging'); d.el.style.transform = '';
      canvas.querySelectorAll('.nm-drop').forEach(b => b.classList.remove('nm-drop'));
      if (!d.moved) { select({ k: 'e', id: d.id }); return; }
      const tgt = dropTarget(e.clientX, e.clientY);
      if (tgt?.kind === 'narr') moveEvidence(d.id, tgt.id!);
      else if (tgt?.kind === 'tray') moveEvidence(d.id, null);
    };
    canvas.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => { canvas.removeEventListener('pointermove', onMove); window.removeEventListener('pointerup', onUp); };
  }, [pan, z, select, moveEvidence, linkNarratives, moveNarrativePos, moveVerdictPos, narrativeOf, graph.verdict.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── zoom (wheel toward cursor) ─────────────────────────────────────
  // Attached as a NON-passive native listener (React's onWheel is passive in
  // React 19, so calling preventDefault there throws "Unable to preventDefault
  // inside passive event listener" and breaks zoom-to-cursor).
  const onWheel = useCallback((e: WheelEvent) => {
    e.preventDefault();
    const rect = canvasRef.current!.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
    setZ(prevZ => {
      const nz = Math.min(1.6, Math.max(0.4, prevZ * factor));
      const k = nz / prevZ;
      setPan(p => clampPan({ x: mx - (mx - p.x) * k, y: my - (my - p.y) * k }, nz));
      return nz;
    });
  }, [clampPan]);
  useEffect(() => {
    const canvas = canvasRef.current; if (!canvas) return;
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', onWheel);
  }, [onWheel]);
  const zoomBy = (f: number) => setZ(v => Math.min(1.6, Math.max(0.4, +(v * f).toFixed(3))));
  const fitView = () => { setZ(1); setPan({ x: 0, y: 0 }); };

  // ── keyboard ───────────────────────────────────────────────────────
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
      if (e.key === 'Escape') { setSel(null); setMenu(null); }
      if ((e.key === 'Delete' || e.key === 'Backspace') && sel && sel.k !== 'v') deleteCard(sel.k, sel.id);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [sel]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── render helpers ─────────────────────────────────────────────────
  const q = search.trim().toLowerCase();
  const matches = (n: Narrative) => !q || `${n.title} ${n.reason}`.toLowerCase().includes(q) || n.evs.some(eid => `${graph.evidence[eid]?.data} ${graph.evidence[eid]?.kicker}`.toLowerCase().includes(q));

  const StateBadge = ({ s }: { s: State }) => {
    const m = STATE_META[s];
    return <span className="nm-badge" style={{ color: m.color, background: `color-mix(in srgb, ${m.color} 15%, transparent)` }}>
      <m.Icon size={12} /> {m.label}
    </span>;
  };

  const renderEvidence = (e: Evidence, inTray = false) => (
    <div key={e.id} data-ev={e.id}
      className={`nm-ev ${sel?.k === 'e' && sel.id === e.id ? 'sel' : ''} ${inTray ? 'tray' : ''} ${pulse.has(e.id) ? 'pulse' : ''}`}
      title="Double-click to inspect this evidence"
      onDoubleClick={(ev) => { ev.preventDefault(); ev.stopPropagation(); setEvDetail(e); }}
      onContextMenu={(ev) => { ev.preventDefault(); ev.stopPropagation(); setMenuNote(''); setMenu({ x: ev.clientX, y: ev.clientY, kind: 'evidence', id: e.id, mode: 'root' }); }}>
      <div className="nm-ev-kicker"><IconDatabase size={11} /> {e.kicker?.toUpperCase()}</div>
      <div className="nm-ev-data">{clip(stripMd(e.data), inTray ? 40 : 64)}</div>
      {e.sealed && <span className="nm-sealed" title={`sealed ${e.sealed}`}><IconLock size={10} /> {e.sealed}</span>}
      {e.notes?.length > 0 && <span className="nm-ev-note"><IconNote size={10} /> {e.notes.length}</span>}
    </div>
  );

  return (
    <div className="nm">
      {/* HEADER */}
      <header className="nm-header">
        <div className="nm-title"><span className="nm-logo nm-logo-eye"><img src={eyeIcon} alt="Eye AI" width={22} height={22} /></span>
          <b>Narrative Map</b>{caseName && <span className="nm-case">· {caseName}</span>}
          {!live && <span className="nm-connecting">connecting…</span>}
        </div>
        <div className="nm-header-right">
          <div className="nm-zoom">
            <button className="nm-icon-btn" onClick={() => zoomBy(1 / 1.1)} title="Zoom out"><IconMinus size={14} /></button>
            <span className="nm-zoom-val">{Math.round(z * 100)}%</span>
            <button className="nm-icon-btn" onClick={() => zoomBy(1.1)} title="Zoom in"><IconPlus size={14} /></button>
            <button className="nm-icon-btn" onClick={fitView} title="Fit to view"><IconMaximize size={14} /></button>
          </div>
          <button className={`nm-actor ${actor}`} onClick={() => setActor(a => a === 'eye' ? 'investigator' : 'eye')}
            title="Toggle who authors subsequent edits">
            {actor === 'eye' ? <IconBrain size={14} /> : <IconUser size={14} />}
            {actor === 'eye' ? 'The Eye' : 'Investigator'}
          </button>
        </div>
      </header>

      {/* TOOLBAR */}
      <div className="nm-toolbar">
        <div className="nm-search"><IconSearch size={14} />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search narratives & evidence…" />
        </div>
        <div className="nm-chips">
          {ALL_STATES.map(s => (
            <button key={s} className={`nm-chip ${filters.has(s) ? 'on' : ''}`}
              style={filters.has(s) ? { color: STATE_META[s].color, borderColor: STATE_META[s].color, background: `color-mix(in srgb, ${STATE_META[s].color} 14%, transparent)` } : undefined}
              onClick={() => setFilters(f => { const n = new Set(f); n.has(s) ? n.delete(s) : n.add(s); return n; })}>
              {STATE_META[s].label}
            </button>
          ))}
        </div>
        <div className="nm-add">
          <button className="nm-btn" onClick={addNarrative}><IconPlus size={13} /> Narrative</button>
          <button className="nm-btn" onClick={() => addEvidence()}><IconPlus size={13} /> Evidence</button>
          <button className="nm-btn" onClick={addGlobalNote} title="Add a floating global note (not tied to a narrative)"><IconNote size={13} /> Note</button>
          <button className="nm-btn" onClick={() => select({ k: 'v', id: graph.verdict.id })} title="Define / edit the case verdict"><IconFlag size={13} /> Verdict</button>
        </div>
      </div>

      {/* BODY: canvas + side panel */}
      <div className="nm-body">
        <div ref={canvasRef} className="nm-canvas" onPointerDown={onCanvasPointerDown}>
          <div ref={worldRef} className="nm-world" style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${z})` }}>
            <svg className="nm-wires">
              {wires.map(w => {
                const tracedWire = traceSet ? (traceSet.has(w.from) && traceSet.has(w.to)) : null;
                const opacity = tracedWire === true ? 0.95 : tracedWire === false ? 0.06 : (w.dim ? 0.12 : 0.75);
                return (
                  <path key={w.id} d={w.d} fill="none" stroke={w.color} strokeWidth={tracedWire === true ? 3 : 2}
                    strokeLinecap="round" opacity={opacity}
                    className={w.dashed ? 'nm-wire-flow' : ''} strokeDasharray={w.dashed ? '6 6' : undefined} />
                );
              })}
            </svg>

            {/* Narratives — tree-positioned cards (drag to override) */}
            {graph.narratives.map((n) => {
              if (!filters.has(n.state)) return null;
              const m = STATE_META[n.state];
              const dim = q && !matches(n);
              const left = n.x ?? layout[n.id]?.x ?? 48;
              const top = n.y ?? layout[n.id]?.y ?? 48;
              const traced = traceSet ? traceSet.has(n.id) : null;
              return (
                <div key={n.id} data-narr={n.id}
                  className={`nm-card ${sel?.k === 'n' && sel.id === n.id ? 'sel' : ''} ${pulse.has(n.id) ? 'pulse' : ''} ${dim ? 'dim' : ''} ${investigatingId === n.id ? 'nm-investigating' : ''} ${traced === true ? 'nm-trace' : ''} ${traced === false ? 'nm-untrace' : ''}`}
                  style={{ ['--st' as any]: m.color, borderStyle: m.border, left, top }}
                  title="Drag to move · double-click for details · right-click → Dive deeper"
                  onContextMenu={(e) => { e.preventDefault(); setMenuNote(''); setMenu({ x: e.clientX, y: e.clientY, kind: 'narrative', id: n.id, mode: 'root' }); }}>
                  {/* link connector (drag to another card / verdict) */}
                  <span className="nm-linkout" data-linkfrom={n.id} title="Drag to link this narrative to another or to the verdict"><IconLink size={11} /></span>
                  {investigatingId === n.id && (
                    <span className="nm-investigating-badge" title="The Eye is investigating this further…">
                      <IconLoader size={12} /> investigating…
                    </span>
                  )}
                  <div className="nm-card-head">
                    <StateBadge s={n.state} />
                    <div className="nm-card-meta">
                      <span className={`nm-author ${isEye(n.authoredBy) ? 'eye' : 'inv'}`}>{isEye(n.authoredBy) ? '◆ EYE' : '⬡ INV'}</span>
                      <button className="nm-chevron" onClick={(e) => { e.stopPropagation(); toggleCollapse(n.id); }}
                        style={{ transform: n.collapsed ? 'rotate(0deg)' : 'rotate(90deg)' }}><IconChevronRight size={14} /></button>
                    </div>
                  </div>
                  <div className="nm-card-title">{stripMd(n.title)}</div>
                  <div className="nm-card-reason">{clip(stripMd(n.reason), 120)}</div>
                  <div className="nm-meter">
                    {n.evs.length > 0
                      ? <>{n.evs.map((_, i2) => <span key={i2} className="nm-dot" />)}<span className="nm-meter-n">{n.evs.length} evidence</span></>
                      : <span className="nm-meter-empty" style={{ color: m.color }}>{EMPTY_NOTE[n.state]}</span>}
                    {n.notes.length > 0 && <span className="nm-meter-note"><IconNote size={11} /> {n.notes.length}</span>}
                  </div>
                  {!n.collapsed && (
                    <div className="nm-card-body" data-body={n.id}>
                      {n.evs.length === 0 && <div className="nm-drop-hint">drop evidence here</div>}
                      {n.evs.map(eid => graph.evidence[eid] ? renderEvidence(graph.evidence[eid]) : null)}
                    </div>
                  )}
                </div>
              );
            })}
            {/* Global cards — floating, unconnected by default, draggable + linkable (left zone) */}
            {graph.globals.map((c) => {
              const left = c.x ?? layout[c.id]?.x ?? 48;
              const top = c.y ?? layout[c.id]?.y ?? 48;
              return (
                <div key={c.id} data-global={c.id}
                  className={`nm-global ${sel?.k === 'g' && sel.id === c.id ? 'sel' : ''} ${pulse.has(c.id) ? 'pulse' : ''}`}
                  style={{ left, top }}
                  title="Global note — drag to move · drag the link icon to attach it to a narrative or the verdict">
                  <span className="nm-linkout" data-linkfrom={c.id} title="Drag to link this card to a narrative or the verdict"><IconLink size={11} /></span>
                  <div className="nm-global-kicker"><IconNote size={11} /> {(c.kicker || 'note').toUpperCase()}</div>
                  <div className="nm-global-title">{stripMd(c.title)}</div>
                  {c.body && <div className="nm-global-body">{clip(stripMd(c.body), 160)}</div>}
                  <span className={`nm-author ${isEye(c.authoredBy) ? 'eye' : 'inv'} nm-global-author`}>{isEye(c.authoredBy) ? '◆ EYE' : '⬡ INV'}</span>
                </div>
              );
            })}
            {graph.narratives.length === 0 && (
              <div className="nm-empty" style={{ left: 48, top: 48 }}><IconBrain size={40} color="var(--color-text-muted)" />
                <p>No narratives yet — ask the Eye a question, or add one.</p></div>
            )}

            {/* Verdict — tree-positioned, draggable node (3-state color) */}
            <div data-verdict className={`nm-verdict ${sel?.k === 'v' ? 'sel' : ''} ${pulse.has(graph.verdict.id) ? 'pulse' : ''} ${traceSet ? (traceSet.has(graph.verdict.id) ? 'nm-trace' : 'nm-untrace') : ''}`}
              style={{ ['--st' as any]: VERDICT_STATE_META[verdictState(graph.verdict)].color, left: graph.verdict.x ?? layout[graph.verdict.id]?.x ?? 760, top: graph.verdict.y ?? layout[graph.verdict.id]?.y ?? 220 }}
              title="Drag to move the verdict">
              <div className="nm-verdict-kicker"><IconFlag size={12} /> VERDICT · {VERDICT_STATE_META[verdictState(graph.verdict)].label.toUpperCase()}</div>
              <div className="nm-verdict-title">{stripMd(graph.verdict.title)}</div>
              {graph.verdict.reason && <div className="nm-verdict-reason">{clip(stripMd(graph.verdict.reason), 220)}</div>}
              <div className="nm-verdict-count">← {provenCount} proven narrative{provenCount === 1 ? '' : 's'}</div>
            </div>
          </div>

          {/* Live link-drag line (screen-space overlay, above the transformed world) */}
          {linkDrag && (
            <svg className="nm-linkdrag">
              <line x1={linkDrag.x0} y1={linkDrag.y0} x2={linkDrag.x} y2={linkDrag.y}
                stroke={SUPPORT_LINK_COLOR} strokeWidth={2} strokeDasharray="5 5" strokeLinecap="round" />
            </svg>
          )}
        </div>

        {/* SIDE PANEL */}
        <aside className="nm-side">
          <div className="nm-tabs">
            <button className={tab === 'inspector' ? 'on' : ''} onClick={() => setTab('inspector')}>Inspector</button>
            <button className={tab === 'audit' ? 'on' : ''} onClick={() => setTab('audit')}>Audit</button>
          </div>

          {tab === 'inspector' ? (
            <div className="nm-inspector">
              {!selObj ? <p className="nm-muted">Select a narrative, evidence card, or the verdict to edit its data, change its state, and add notes.</p> : (
                <>
                  <div className="nm-insp-kind" style={{ color: sel!.k === 'e' ? EV_COLOR : sel!.k === 'v' ? VERDICT_STATE_META[verdictState(graph.verdict)].color : sel!.k === 'g' ? 'var(--color-cyan)' : STATE_META[(selObj as Narrative).state].color }}>
                    {sel!.k === 'e' ? `${(selObj as Evidence).kicker} · Evidence` : sel!.k === 'v' ? 'Verdict' : sel!.k === 'g' ? `${(selObj as Global).kicker} · Global card` : 'Narrative'}
                  </div>
                  <label className="nm-lbl">{sel!.k === 'e' ? 'evidence data' : 'title / claim'}</label>
                  <input className="nm-input" value={titleDraft} onChange={e => setTitleDraft(e.target.value)} />
                  <label className="nm-lbl">reason / justification (GEP R9)</label>
                  <textarea className="nm-input nm-area" value={reasonDraft} onChange={e => setReasonDraft(e.target.value)} rows={2} />

                  {sel!.k === 'n' && (
                    <>
                      <label className="nm-lbl">state</label>
                      <div className="nm-seg">
                        {ALL_STATES.map(s => (
                          <button key={s} className={(selObj as Narrative).state === s ? 'on' : ''}
                            style={(selObj as Narrative).state === s ? { color: STATE_META[s].color, borderColor: STATE_META[s].color } : undefined}
                            onClick={() => changeState(s)} title={STATE_META[s].label}>
                            {React.createElement(STATE_META[s].Icon, { size: 13 })}
                          </button>
                        ))}
                      </div>
                    </>
                  )}

                  {sel!.k === 'v' && (
                    <>
                      <label className="nm-lbl">verdict state</label>
                      <div className="nm-seg">
                        {(['open', 'proven', 'unproven'] as VerdictState[]).map(s => (
                          <button key={s} className={verdictState(graph.verdict) === s ? 'on' : ''}
                            style={verdictState(graph.verdict) === s ? { color: VERDICT_STATE_META[s].color, borderColor: VERDICT_STATE_META[s].color } : undefined}
                            onClick={() => setVerdictState(s)} title={VERDICT_STATE_META[s].label}>
                            {VERDICT_STATE_META[s].label}
                          </button>
                        ))}
                      </div>
                    </>
                  )}

                  <div className="nm-meta-line">
                    {sel!.k === 'e' && <><span className="nm-dim">ref</span> <code>{(selObj as Evidence).ref}</code> · </>}
                    <span className="nm-dim">by</span> {selObj.authoredBy === 'system' ? 'System (parser)' : isEye(selObj.authoredBy) ? `The Eye · ${String(selObj.authoredBy).split(':')[1] || ''}` : 'Investigator'}
                    {(selObj as Evidence).sealed && <span className="nm-sealed-inline"><IconLock size={10} /> {(selObj as Evidence).sealed}</span>}
                  </div>
                  {sel!.k === 'n' && (selObj as Narrative).meta?.created_from && (
                    <div className="nm-meta-line nm-raised-from">
                      <span className="nm-dim">raised from:</span> <em>{(selObj as Narrative).meta!.created_from}</em>
                    </div>
                  )}

                  <label className="nm-lbl">notes (added to the Eye's context)</label>
                  <div className="nm-notes">
                    {(!selObj.notes || selObj.notes.length === 0) && <div className="nm-nonote">no notes yet</div>}
                    {selObj.notes?.map((nt: MapNote, i: number) => (
                      <div className="nm-note" key={i}>
                        <span className={`nm-note-by ${nt.by}`}>{nt.by === 'eye' ? '◆ Eye' : nt.by === 'system' ? 'System' : '⬡ Investigator'}</span>
                        <Md>{nt.text}</Md>
                      </div>
                    ))}
                  </div>
                  {sel!.k !== 'v' && (
                    <div className="nm-note-add">
                      <input className="nm-input" value={noteDraft} onChange={e => setNoteDraft(e.target.value)}
                        placeholder="add a note…" onKeyDown={e => { if (e.key === 'Enter') addNote(); }} />
                      <button className="nm-btn" onClick={addNote}><IconNote size={13} /> Note</button>
                    </div>
                  )}

                  <div className="nm-insp-actions">
                    <button className="nm-btn primary" onClick={saveEdits}>Save edits</button>
                    {sel!.k !== 'v' && <button className="nm-btn danger" onClick={() => deleteCard(sel!.k as 'n' | 'e' | 'g', sel!.id)}><IconTrash size={13} /> Delete</button>}
                  </div>
                </>
              )}
            </div>
          ) : (
            <div className="nm-audit">
              <div className="nm-audit-head">
                <span>Compliance audit · hash-chained</span>
                <span className={`nm-chain ${chainOk ? 'ok' : 'bad'}`}><IconShieldCheck size={13} /> {chainOk ? 'intact' : 'broken'}</span>
              </div>
              <div className="nm-audit-list">
                {audit.length === 0 && <p className="nm-muted">No changes recorded yet. Every edit appends a sealed row.</p>}
                {audit.map(a => (
                  <div key={a.hash + a.seq} className="nm-audit-row" style={{ borderLeftColor: ACTION_COLOR[a.action] || '#94a3b8' }}>
                    <div className="nm-audit-top">
                      <span className="nm-audit-act" style={{ color: ACTION_COLOR[a.action] || '#94a3b8' }}>#{a.seq} {a.action}</span>
                      <span className="nm-dim">{a.actor === 'eye' ? '◆ Eye' : '⬡ Inv'} · {clip(a.target, 18)}</span>
                    </div>
                    <div className="nm-audit-reason">{a.reason ? `“${clip(a.reason, 60)}”` : <span className="nm-fail">no reason</span>}</div>
                    <div className="nm-gep">
                      {(['r9', 'r10', 'r11'] as const).map(r => {
                        const v = (a.gep as any)[r];
                        const c = v === 'PASS' ? 'var(--color-success)' : v === 'FAIL' ? 'var(--color-error)' : v === 'PARTIAL' ? 'var(--color-warning)' : 'var(--color-text-muted)';
                        return <span key={r} className="nm-gep-badge" style={{ color: c, background: `color-mix(in srgb, ${c} 16%, transparent)` }}>{r.toUpperCase()}</span>;
                      })}
                    </div>
                    <div className="nm-hashline">{clip(a.prevHash, 7)} → <span className="nm-hash">{clip(a.hash, 12)}</span></div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </aside>
      </div>

      {/* FREE-EVIDENCE TRAY */}
      <div className="nm-tray" data-tray>
        <span className="nm-tray-label"><IconDatabase size={12} /> Free evidence</span>
        <div className="nm-tray-scroll">
          {freeEvidence.length === 0 && <span className="nm-tray-empty">drag evidence here to detach it from a narrative</span>}
          {freeEvidence.map(e => renderEvidence(e, true))}
        </div>
      </div>

      {/* FOOTER */}
      <footer className="nm-footer">
        <div className="nm-legend">
          {ALL_STATES.map(s => <span key={s} className="nm-leg"><span className="nm-leg-dot" style={{ background: STATE_META[s].color }} /> {STATE_META[s].label}</span>)}
          <span className="nm-leg"><span className="nm-leg-dot" style={{ background: EV_COLOR }} /> Evidence</span>
        </div>
        <div className="nm-counts">{graph.narratives.length} narratives · {Object.keys(graph.evidence).length} evidence</div>
      </footer>

      {/* CONTEXT MENU */}
      {menu && (() => {
        const closeMenu = () => { setMenu(null); setMenuNote(''); };
        // Clamp to viewport so the menu never opens offscreen.
        const W = menu.kind === 'narrative' ? 230 : 210;
        const H = menu.mode === 'note' ? 150 : (menu.mode === 'link' || menu.mode === 'unlink') ? 320 : (menu.kind === 'narrative' ? 380 : 170);
        const left = Math.min(menu.x, window.innerWidth - W - 8);
        const top = Math.min(menu.y, window.innerHeight - H - 8);
        const n = menu.kind === 'narrative' ? narrativeOf(menu.id) : null;
        const ev = menu.kind === 'evidence' ? graph.evidence[menu.id] : null;
        const submitNote = () => { if (menuNote.trim()) { addNoteTo({ k: menu.kind === 'narrative' ? 'n' : 'e', id: menu.id }, menuNote); } closeMenu(); };
        return (
          <>
            <div className="nm-menu-backdrop" onClick={closeMenu} onContextMenu={(e) => { e.preventDefault(); closeMenu(); }} />
            <div className="nm-menu" style={{ left, top }}>
              <div className="nm-menu-title">{menu.kind === 'narrative' ? 'Narrative' : 'Evidence'}</div>
              {menu.mode === 'note' ? (
                <div className="nm-menu-note">
                  <input autoFocus className="nm-input" value={menuNote} onChange={e => setMenuNote(e.target.value)}
                    placeholder="note text… (fed to the Eye)" onKeyDown={e => { if (e.key === 'Enter') submitNote(); if (e.key === 'Escape') closeMenu(); }} />
                  <div className="nm-menu-note-actions">
                    <button className="nm-btn primary" onClick={submitNote}>Save note</button>
                    <button className="nm-btn" onClick={() => setMenu({ ...menu, mode: 'root' })}>Back</button>
                  </div>
                </div>
              ) : menu.mode === 'link' ? (
                <div className="nm-menu-list">
                  <div className="nm-menu-subtitle">Link “{clip(n?.title ?? '', 18)}” to…</div>
                  <button onClick={() => { linkNarratives(menu.id, graph.verdict.id); closeMenu(); }}
                    disabled={graph.links.some(l => l.from === menu.id && l.to === graph.verdict.id)}><IconFlag size={13} /> Verdict</button>
                  {graph.narratives.filter(t => t.id !== menu.id).map(t => (
                    <button key={t.id} onClick={() => { linkNarratives(menu.id, t.id); closeMenu(); }}
                      disabled={graph.links.some(l => l.from === menu.id && l.to === t.id)}><IconLink size={13} /> {clip(t.title, 24)}</button>
                  ))}
                  <div className="nm-menu-sep" />
                  <button onClick={() => setMenu({ ...menu, mode: 'root' })}>Back</button>
                </div>
              ) : menu.mode === 'unlink' ? (
                <div className="nm-menu-list">
                  <div className="nm-menu-subtitle">Remove a link from “{clip(n?.title ?? '', 18)}”</div>
                  {graph.links.filter(l => l.from === menu.id).map(l => (
                    <button key={l.id} className="danger" onClick={() => { unlink(l.id); closeMenu(); }}>
                      <IconTrash size={13} /> {l.to === graph.verdict.id ? 'Verdict' : clip(narrativeOf(l.to)?.title ?? l.to, 24)}
                    </button>
                  ))}
                  {graph.links.filter(l => l.from === menu.id).length === 0 && <div className="nm-nonote">no links</div>}
                  <div className="nm-menu-sep" />
                  <button onClick={() => setMenu({ ...menu, mode: 'root' })}>Back</button>
                </div>
              ) : menu.kind === 'narrative' ? (
                <div className="nm-menu-list">
                  <button onClick={() => { investigate(menu.id); closeMenu(); }} disabled={!live || !!investigatingId}><IconSearch size={13} /> Dive deeper (ask the Eye)</button>
                  <button onClick={() => setMenu({ ...menu, mode: 'note' })}><IconNote size={13} /> Add note</button>
                  <button onClick={() => { addEvidence(menu.id); closeMenu(); }}><IconDatabase size={13} /> Add evidence</button>
                  <div className="nm-menu-sep" />
                  <button onClick={() => { if (changeState('proven', menu.id)) closeMenu(); }} style={{ color: STATE_META.proven.color }}><IconCircleCheck size={13} /> Mark proven</button>
                  <button onClick={() => { if (changeState('open', menu.id)) closeMenu(); }} style={{ color: STATE_META.open.color }}><IconLoader size={13} /> Mark open</button>
                  <button onClick={() => { if (changeState('negative', menu.id)) closeMenu(); }} style={{ color: STATE_META.negative.color }}><IconCircleMinus size={13} /> Mark negative</button>
                  <button onClick={() => { setActor('investigator'); if (changeState('absolute', menu.id)) closeMenu(); }} style={{ color: STATE_META.absolute.color }}><IconLockCheck size={13} /> Make absolute</button>
                  <button onClick={() => { setActor('investigator'); if (changeState('needs', menu.id)) closeMenu(); }} style={{ color: STATE_META.needs.color }}><IconAlertTriangle size={13} /> Make base (hypothesis)</button>
                  <div className="nm-menu-sep" />
                  <button onClick={() => setMenu({ ...menu, mode: 'link' })}><IconLink size={13} /> Link to…</button>
                  {graph.links.some(l => l.from === menu.id) && (
                    <button onClick={() => setMenu({ ...menu, mode: 'unlink' })}><IconLink size={13} /> Unlink…</button>
                  )}
                  <button className="danger" onClick={() => { deleteCard('n', menu.id); closeMenu(); }}><IconTrash size={13} /> Delete narrative</button>
                </div>
              ) : (
                <div className="nm-menu-list">
                  <button onClick={() => setMenu({ ...menu, mode: 'note' })}><IconNote size={13} /> Add note</button>
                  {ev && !ev.free && ownerOf(menu.id) && (
                    <button onClick={() => { moveEvidence(menu.id, null); closeMenu(); }}><IconDatabase size={13} /> Detach to tray</button>
                  )}
                  <div className="nm-menu-sep" />
                  <button className="danger" onClick={() => { deleteCard('e', menu.id); closeMenu(); }}><IconTrash size={13} /> Delete evidence</button>
                </div>
              )}
            </div>
          </>
        );
      })()}

      {/* EVIDENCE DETAIL WINDOW (double-click an evidence card) */}
      {evDetail && (
        <EvidenceDetailModal
          evidence={evDetail}
          ownerTitle={ownerOf(evDetail.id)?.title ?? null}
          live={live}
          onClose={() => setEvDetail(null)}
        />
      )}

      {/* NARRATIVE DETAIL WINDOW (double-click a narrative card) */}
      {narrDetail && (
        <NarrativeDetailModal
          narrative={narrDetail}
          evidence={graph.evidence}
          live={live}
          investigating={investigatingId === narrDetail.id}
          onClose={() => setNarrDetail(null)}
          onDiveDeeper={() => { investigate(narrDetail.id); setNarrDetail(null); }}
        />
      )}
    </div>
  );
}

// ── Evidence detail window ──────────────────────────────────────────────
// Opens on double-click. Shows the evidence record as a Field/Value table, its
// notes, and — when the reference is a `db:table:rowid` pointer — a "Load source
// rows" button that pulls the underlying artifact row(s) from the case database
// and renders them with the shared DataViewer.
const EV_REF_RE = /^([\w.\-]+):([\w]+):(\d+)$/;

const EvidenceDetailModal: React.FC<{
  evidence: Evidence;
  ownerTitle: string | null;
  live: boolean;
  onClose: () => void;
}> = ({ evidence: e, ownerTitle, live, onClose }) => {
  const [rows, setRows] = useState<DataViewerProps | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const refMatch = EV_REF_RE.exec((e.ref || '').trim());
  const hasQuery = !!(e.query && e.database);          // SQL + db stored by the Eye
  const canLoad = hasQuery || !!refMatch;

  const runQuery = async (db: string, sql: string): Promise<DataViewerProps | null> => {
    const bridge: any = (window as any).bridge;
    if (!live || !bridge || typeof bridge.query_database !== 'function') return null;
    const tryDb = async (d: string) => {
      try {
        const raw = await bridge.query_database(d, sql);
        const res = typeof raw === 'string' ? JSON.parse(raw) : raw;
        const data = res?.data || res;
        const r = data?.rows || data?.data;
        if (res?.success !== false && Array.isArray(r) && r.length) {
          return { columns: data.columns || (r[0] ? Object.keys(r[0]) : []), rows: r, query: sql, database: d, table: '' } as DataViewerProps;
        }
      } catch { /* */ }
      return null;
    };
    return (await tryDb(db)) || (await tryDb(db.endsWith('.db') ? db : db + '.db'));
  };

  const loadSource = async () => {
    setErr(null); setRows(null);
    if (!live) { setErr('Bridge unavailable — open a live case to query the source database.'); return; }
    setLoading(true);
    let data: DataViewerProps | null = null;
    if (hasQuery) {
      data = await runQuery(e.database!, e.query!);
      if (!data) { setLoading(false); setErr('The source query returned no rows (the data may have changed or the query needs a smaller scope).'); return; }
    } else if (refMatch) {
      const [, dbTok, table, rowid] = refMatch;
      data = await runQuery(dbTok, `SELECT * FROM ${table} WHERE rowid = ${rowid}`);
      if (!data) { setLoading(false); setErr(`No rows found for ${table} (rowid ${rowid}) in “${dbTok}”.`); return; }
    } else {
      setLoading(false); setErr('No queryable source recorded for this evidence.'); return;
    }
    setLoading(false);
    setRows(data);
  };

  const kv: [string, React.ReactNode][] = [
    ['Source', (e.kicker || 'artifact').toUpperCase()],
    ['Detail', e.data ? <Md>{e.data}</Md> : '—'],
    ['Why it matters', e.reason ? <Md>{e.reason}</Md> : '—'],
    ...(e.query ? [['Query', <code className="nm-ev-query">{e.query}</code>] as [string, React.ReactNode]] : []),
    ['Reference', e.database ? `${e.database}` : (e.ref || '—')],
    ['Author', e.authoredBy || '—'],
    ['Sealed', e.sealed || 'unsealed'],
    ['Attached to', ownerTitle || 'Free (unattached)'],
  ];

  return (
    <div className="nm-modal-overlay" onClick={onClose}>
      <div className="nm-modal" onClick={ev => ev.stopPropagation()}>
        <div className="nm-modal-head">
          <span className="nm-modal-title"><IconDatabase size={14} /> Evidence · {(e.kicker || 'artifact').toUpperCase()}</span>
          <button className="nm-icon-btn" onClick={onClose} title="Close">✕</button>
        </div>
        <div className="nm-modal-body">
          <table className="nm-kv-table">
            <tbody>
              {kv.map(([k, v]) => (<tr key={k}><th>{k}</th><td>{v}</td></tr>))}
            </tbody>
          </table>

          {e.notes && e.notes.length > 0 && (
            <div className="nm-modal-notes">
              <div className="nm-modal-subhead">Notes</div>
              {e.notes.map((n, i) => (
                <div key={i} className="nm-modal-note">
                  <span className="nm-dim">{n.by}{n.ts ? ` · ${clip(n.ts, 19)}` : ''}</span>
                  <Md>{n.text}</Md>
                </div>
              ))}
            </div>
          )}

          <div className="nm-modal-src">
            <div className="nm-modal-subhead">Source artifact</div>
            <button className="nm-btn" onClick={loadSource} disabled={loading || !canLoad}>
              {loading ? 'Loading…' : 'Load source rows'}
            </button>
            {!canLoad && <span className="nm-dim nm-modal-srchint">No queryable source recorded for this evidence (it came from a non-database tool).</span>}
            {err && <div className="nm-modal-err">{err}</div>}
            {rows && <DataViewer {...rows} />}
          </div>
        </div>
      </div>
    </div>
  );
};

// ── Narrative detail window ─────────────────────────────────────────────
// Opens on double-click. Shows the finding (claim), its state, the originating
// question (provenance), notes, and the attached evidence — plus a "dive deeper"
// action that asks the Eye to investigate the finding further.
const NarrativeDetailModal: React.FC<{
  narrative: Narrative;
  evidence: Record<string, Evidence>;
  live: boolean;
  investigating: boolean;
  onClose: () => void;
  onDiveDeeper: () => void;
}> = ({ narrative: n, evidence, live, investigating, onClose, onDiveDeeper }) => {
  const evs = n.evs.map(id => evidence[id]).filter(Boolean) as Evidence[];
  const author = n.authoredBy === 'system' ? 'System (parser)'
    : isEye(n.authoredBy) ? `The Eye · ${String(n.authoredBy).split(':')[1] || ''}` : 'Investigator';
  const kv: [string, React.ReactNode][] = [
    ['Claim', n.title],
    ['State', STATE_META[n.state].label],
    ['Why', n.reason ? <Md>{n.reason}</Md> : '—'],
    ['Author', author],
    ['Raised from', n.meta?.created_from || '—'],
    ['Evidence', `${evs.length} item${evs.length === 1 ? '' : 's'}`],
  ];
  return (
    <div className="nm-modal-overlay" onClick={onClose}>
      <div className="nm-modal" onClick={ev => ev.stopPropagation()}>
        <div className="nm-modal-head">
          <span className="nm-modal-title"><IconBrain size={14} /> Narrative · {STATE_META[n.state].label}</span>
          <button className="nm-icon-btn" onClick={onClose} title="Close">✕</button>
        </div>
        <div className="nm-modal-body">
          <table className="nm-kv-table">
            <tbody>{kv.map(([k, v]) => (<tr key={k}><th>{k}</th><td>{v}</td></tr>))}</tbody>
          </table>

          {n.notes && n.notes.length > 0 && (
            <div className="nm-modal-notes">
              <div className="nm-modal-subhead">Notes</div>
              {n.notes.map((nt, i) => (
                <div key={i} className="nm-modal-note">
                  <span className="nm-dim">{nt.by}{nt.ts ? ` · ${clip(nt.ts, 19)}` : ''}</span>
                  <Md>{nt.text}</Md>
                </div>
              ))}
            </div>
          )}

          <div className="nm-modal-src">
            <div className="nm-modal-subhead">Evidence ({evs.length})</div>
            {evs.length === 0 && <div className="nm-dim">No evidence attached.</div>}
            {evs.map(e => (
              <div key={e.id} className="nm-modal-note">
                <span className="nm-dim">{(e.kicker || 'artifact').toUpperCase()}{e.ref ? ` · ${e.ref}` : ''}</span>
                <Md>{e.data}</Md>
              </div>
            ))}
          </div>

          <div className="nm-modal-src">
            <button className="nm-btn primary" onClick={onDiveDeeper} disabled={!live || investigating}>
              <IconSearch size={13} /> {investigating ? 'Investigating…' : 'Ask the Eye to dive deeper'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

const ACTION_COLOR: Record<string, string> = {
  CREATE: '#22d3ee', EDIT: '#f59e0b', STATE_CHANGE: '#a855f7', ATTACH: '#10b981',
  DETACH: '#f43f5e', NOTE: '#60a5fa', LINK: '#a855f7', DELETE: '#f43f5e', MOVE: '#64748b',
  MARK_NEGATIVE: '#64748b', MAKE_ABSOLUTE: '#10b981', MAKE_BASE: '#f59e0b',
};

// ── auto tree-layout ────────────────────────────────────────────────────
// Lays the verdict + narratives out as a right-to-left layered tree (verdict on
// the right; sub-narratives branch leftward off their parent). Returns a default
// position per node; an explicit dragged x/y always overrides this.
const TREE = { X0: 1700, Y0: 100, COL: 400, ROW: 220, GLOBAL_GAP: 210 };
// Card footprint used for the pannable-bounds bbox so cards stay reachable.
export const CARD_W = 300, CARD_H = 170;
function computeTreeLayout(graph: MapGraph, heights: Record<string, number> = {}): Record<string, { x: number; y: number }> {
  const pos: Record<string, { x: number; y: number }> = {};
  const verdictId = graph.verdict.id;
  const narrIds = new Set(graph.narratives.map(n => n.id));
  // First outgoing link defines a narrative's parent (a narrative or the verdict).
  const parentOf: Record<string, string> = {};
  graph.links.forEach(l => { if (l.from && !(l.from in parentOf)) parentOf[l.from] = l.to; });
  const childrenOf: Record<string, string[]> = {};
  graph.narratives.forEach(n => {
    const p = (parentOf[n.id] && (narrIds.has(parentOf[n.id]) || parentOf[n.id] === verdictId)) ? parentOf[n.id] : verdictId;
    (childrenOf[p] ||= []).push(n.id);
  });
  let leafY = TREE.Y0;
  let maxDepth = 0;
  const seen = new Set<string>();
  const place = (id: string, depth: number): number => {
    if (seen.has(id)) return pos[id]?.y ?? TREE.Y0; // guard against cycles
    seen.add(id);
    maxDepth = Math.max(maxDepth, depth);
    const kids = (childrenOf[id] || []).filter(k => narrIds.has(k));
    let y: number;
    if (kids.length === 0) { y = leafY; leafY += TREE.ROW; }
    else { const ys = kids.map(k => place(k, depth + 1)); y = (ys[0] + ys[ys.length - 1]) / 2; }
    // Right→left columns: verdict (depth 0, rightmost) → narrative → sub-narrative.
    pos[id] = { x: TREE.X0 - depth * TREE.COL, y };
    return y;
  };
  place(verdictId, 0);
  // Orphans (no path to the verdict) get a left-edge column (unique Y → no overlap).
  graph.narratives.forEach(n => { if (!pos[n.id]) { maxDepth = Math.max(maxDepth, 1); pos[n.id] = { x: TREE.X0 - TREE.COL, y: leafY }; leafY += TREE.ROW; } });

  // Global cards (System Identity, Technical Observations, notes): leftmost zone,
  // beyond the deepest narrative column, stacked top-down so they never overlap.
  // Unconnected by default — they just float here until linked.
  const gx = TREE.X0 - (maxDepth + 1) * TREE.COL;
  let gy = TREE.Y0;
  graph.globals.forEach(c => { if (!pos[c.id]) { pos[c.id] = { x: gx, y: gy }; gy += TREE.GLOBAL_GAP; } });

  // De-overlap safety net: within each column (same x), stack cards using an
  // ESTIMATED height per card instead of a single fixed CARD_H. A collapsed card is
  // short; an expanded card grows with its inline evidence — so a tall expanded card
  // no longer overlaps the card beneath it (the root cause of cards stacking on top
  // of each other). Push down only (tree shape stays intact); dragged cards (explicit
  // x/y) override this in the render, so it never fights a manual placement.
  const GAP = 30;
  const narrById: Record<string, Narrative> = {};
  graph.narratives.forEach(n => { narrById[n.id] = n; });
  const globalIds = new Set(graph.globals.map(c => c.id));
  const estHeight = (id: string): number => {
    // Prefer the REAL measured height (exact — guarantees no overlap once the card
    // has rendered once). The estimate below only covers the very first frame,
    // before measurement, so there's no initial overlap flash.
    if (heights[id] != null && heights[id] > 0) return heights[id];
    const n = narrById[id];
    if (n) {
      // head + title + reason + meter ≈ 172; expanded body adds ~74px per inline
      // evidence card (or ~36 for the empty "drop evidence here" hint).
      const body = n.collapsed ? 0 : (n.evs.length > 0 ? 16 + n.evs.length * 74 : 36);
      return 172 + body;
    }
    if (globalIds.has(id)) return 140;
    return CARD_H; // verdict / fallback
  };
  const byCol: Record<number, string[]> = {};
  Object.keys(pos).forEach(id => { (byCol[pos[id].x] ||= []).push(id); });
  Object.values(byCol).forEach(ids => {
    ids.sort((a, b) => pos[a].y - pos[b].y);
    for (let i = 1; i < ids.length; i++) {
      const minY = pos[ids[i - 1]].y + estHeight(ids[i - 1]) + GAP;
      if (pos[ids[i]].y < minY) pos[ids[i]].y = minY;
    }
  });
  return pos;
}

// Bounding box of all placed cards (computed/dragged positions) + margin, so the
// canvas pan can be clamped — the investigator can't drag the cards out of view,
// and the reachable area grows with card density.
export function contentBBox(graph: MapGraph, layout: Record<string, { x: number; y: number }>) {
  const xs: number[] = [], ys: number[] = [];
  const add = (id: string, x?: number, y?: number) => {
    const p = layout[id]; const px = x ?? p?.x; const py = y ?? p?.y;
    if (px != null && py != null) { xs.push(px); ys.push(py); }
  };
  add(graph.verdict.id, graph.verdict.x, graph.verdict.y);
  graph.narratives.forEach(n => add(n.id, n.x, n.y));
  graph.globals.forEach(c => add(c.id, c.x, c.y));
  Object.values(graph.evidence).forEach(e => { if (e.free && e.x != null && e.y != null) { xs.push(e.x); ys.push(e.y); } });
  if (!xs.length) return { minX: 0, minY: 0, maxX: TREE.X0 + CARD_W, maxY: TREE.Y0 + CARD_H };
  const M = 400; // breathing margin around the cards
  return {
    minX: Math.min(...xs) - M, minY: Math.min(...ys) - M,
    maxX: Math.max(...xs) + CARD_W + M, maxY: Math.max(...ys) + CARD_H + M,
  };
}

// ── hydration normalizers ──────────────────────────────────────────────
function normalize(d: any): MapGraph {
  const vState = (s: any): VerdictState => (s === 'proven' || s === 'unproven') ? s : 'open';
  const verdict: Verdict = d.verdict
    ? { id: d.verdict.id || 'verdict', title: d.verdict.title || d.verdict.data || 'Overall verdict', reason: d.verdict.reason || '', authoredBy: d.verdict.authoredBy || 'eye', state: vState(d.verdict.state), x: d.verdict.x, y: d.verdict.y }
    : (Array.isArray(d.conclusions) && d.conclusions[0]
      ? { id: d.conclusions[0].id || 'verdict', title: d.conclusions[0].data || d.conclusions[0].title || 'Overall verdict', reason: d.conclusions[0].reason || '', authoredBy: d.conclusions[0].authoredBy || 'eye', state: 'open' }
      : { id: 'verdict', title: 'Overall verdict', reason: '', authoredBy: 'eye', state: 'open' });
  const narratives: Narrative[] = (d.narratives || d.reasonings || []).map((n: any) => ({
    id: n.id, state: (ALL_STATES as string[]).includes(n.state) ? n.state : 'open',
    title: n.title || n.data || 'Narrative', reason: n.reason || n.summary || '',
    authoredBy: n.authoredBy || 'eye', evs: n.evs || [], notes: n.notes || [], collapsed: !!n.collapsed,
    meta: n.meta && typeof n.meta === 'object' ? n.meta : undefined,
  }));
  const evidence: Record<string, Evidence> = {};
  Object.entries(d.evidence || {}).forEach(([k, e]: any) => {
    evidence[k] = {
      id: e.id || k, kicker: e.kicker || 'artifact', data: e.data || '', reason: e.reason || '',
      ref: e.ref || (Array.isArray(e.evidence) ? e.evidence[0] : '') || '', authoredBy: e.authoredBy || 'system',
      sealed: e.sealed, notes: e.notes || [], free: !!e.free, x: e.x, y: e.y,
    };
  });
  const globals: Global[] = (d.globals || []).map((c: any) => ({
    id: c.id, kicker: c.kicker || 'note', title: c.title || c.data || 'Note',
    body: c.body || c.reason || '', authoredBy: c.authoredBy || 'eye',
    notes: c.notes || [], x: c.x, y: c.y,
  }));
  const links: Link[] = (d.links || []).map((l: any) => ({ id: l.id || `l_${l.from || l.source}`, from: l.from || l.source, to: l.to || l.target || verdict.id }));
  return { verdict, narratives, evidence, globals, links };
}

function fromBackendAudit(a: any): AuditRow {
  return {
    seq: a.seq || 0, ts: a.ts || '', action: a.action || '', actor: a.actor || 'investigator',
    target: a.target || '', reason: a.reason || '',
    gep: a.gep || { r9: 'N-A', r10: 'N-A', r11: 'N-A' },
    prevHash: a.prevHash || '', hash: a.hash || '',
  };
}
