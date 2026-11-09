/**
 * What Windows recorded of what an AI agent did, matched to the timeline's marks.
 *
 * The bridge (getAiLinks -> data/ai_agent_links.py) returns one link per AI
 * step and Windows record of the same act: the AI step's row (ai_rowid, ai_ts)
 * and the Windows record's name and time. A mark on the timeline shows that
 * Windows record when its name and second are the link's - the same name
 * normalisation the lane's own links use, so "PYTHON.EXE" and "python.exe",
 * "C:\x\app.py" and "app.py" meet.
 *
 * Shared by the lanes (the AI badge, the line to the AI step) and the detail
 * panel (who did this), so the two never disagree about which marks an AI
 * agent touched.
 */
import { normalizeForensicName, cleanForensicDate, getForensicId, getForensicName } from './formatters';

// Actor colour for AI agents (people blue, AI agents cyan, apps fuchsia).
export const AI_COLOR = '#22d3ee';

function secondOf(ts) {
  const t = Date.parse(cleanForensicDate(ts));
  return Number.isNaN(t) ? null : Math.floor(t / 1000);
}

/** name|second -> [link], for the Windows end of every link. */
export function buildAiIndex(aiLinks) {
  const index = new Map();
  (aiLinks || []).forEach(l => {
    const sec = secondOf(l.ts);
    if (sec === null) return;
    const key = `${normalizeForensicName(String(l.name || ''))}|${sec}`;
    if (!index.has(key)) index.set(key, []);
    index.get(key).push(l);
  });
  return index;
}

/** The links whose Windows record this mark shows, or null. */
export function aiHitsFor(mark, index) {
  if (!mark || !index || index.size === 0 || mark.type === 'ai_agent') return null;
  const sec = secondOf(mark.timestamp);
  if (sec === null) return null;
  const hits = index.get(`${normalizeForensicName(String(getForensicName(mark) || ''))}|${sec}`);
  return hits && hits.length ? hits : null;
}

/** The id the AI lane gave the step's mark (TimelineView, lane 6). */
export function aiMarkId(link) {
  return getForensicId('ai_agent', cleanForensicDate(link.ai_ts), 'ts', `step${link.ai_rowid}`);
}

/** The Windows records linked to an AI step mark (its row id). */
export function linksOfStep(step, aiLinks) {
  const rid = step?.row_id ?? step?.id;
  if (rid === undefined || rid === null) return [];
  return (aiLinks || []).filter(l => String(l.ai_rowid) === String(rid));
}
