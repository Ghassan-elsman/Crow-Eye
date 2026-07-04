import React, { useState, memo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { EyeDialogueEntry } from './types';
import './EyeDialogue.css';

/**
 * EyeDialogue — renders the Eye <-> LLM conversation so the investigator can
 * see exactly how the Eye is thinking: the full prompt the Eye sent the model
 * each turn, the model's reasoning + the tool calls it requested, the tool
 * results fed back, and the synthesis exchange. Used both live (streaming
 * during processing) and retained under a completed answer.
 */

interface EyeDialogueProps {
  entries: EyeDialogueEntry[];
  /** When true the whole panel renders open (used for the live stream). */
  live?: boolean;
}

const PHASE_META: Record<EyeDialogueEntry['phase'], { side: string; label: string }> = {
  request:            { side: 'eye',  label: 'Eye → LLM · prompt sent' },
  response:           { side: 'llm',  label: 'LLM → Eye · reply' },
  tool_result:        { side: 'tool', label: 'Tool → Eye · result' },
  synthesis_request:  { side: 'eye',  label: 'Eye → LLM · synthesis prompt' },
  synthesis_response: { side: 'llm',  label: 'LLM → Eye · synthesis' },
};

const Collapsible: React.FC<{ title: string; children: React.ReactNode; defaultOpen?: boolean }> = ({
  title, children, defaultOpen = false,
}) => {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="eyed-collapsible">
      <button className="eyed-collapsible-toggle" onClick={() => setOpen(!open)}>
        <span className="eyed-caret">{open ? '▾' : '▸'}</span> {title}
      </button>
      {open && <div className="eyed-collapsible-body">{children}</div>}
    </div>
  );
};

// memo: an entry only re-renders when its own `entry` reference changes. This
// keeps ReactMarkdown / JSON.stringify off the hot path when an unrelated part
// of the host (e.g. the Compliance panel) re-renders.
const EntryView = memo(function EntryView({ entry }: { entry: EyeDialogueEntry }) {
  const meta = PHASE_META[entry.phase] || { side: 'eye', label: entry.phase };
  return (
    <article className={`eyed-entry eyed-entry--${meta.side}`}>
      <header className="eyed-entry-head">
        <span className="eyed-entry-label">{meta.label}</span>
        {entry.iteration != null && <span className="eyed-entry-iter">step {entry.iteration}</span>}
        {typeof entry.success === 'boolean' && (
          <span className={`eyed-badge ${entry.success ? 'eyed-badge--ok' : 'eyed-badge--fail'}`}>
            {entry.success ? 'SUCCESS' : 'FAILED'}
          </span>
        )}
      </header>

      {/* Request / synthesis_request: what the Eye sent the model. */}
      {(entry.phase === 'request' || entry.phase === 'synthesis_request') && (
        <div className="eyed-entry-body">
          {entry.tools_offered && entry.tools_offered.length > 0 && (
            <div className="eyed-tools-offered">
              <span className="eyed-meta-label">Tools offered:</span>{' '}
              {entry.tools_offered.join(', ')}
            </div>
          )}
          {typeof entry.history_count === 'number' && (
            <div className="eyed-meta-line">History messages sent: {entry.history_count}</div>
          )}
          {entry.system_prompt && (
            <Collapsible title="System prompt (full)">
              <pre className="eyed-pre">{entry.system_prompt}</pre>
            </Collapsible>
          )}
          {entry.user_message && (
            <Collapsible title="Message sent" defaultOpen>
              <pre className="eyed-pre">{entry.user_message}</pre>
            </Collapsible>
          )}
        </div>
      )}

      {/* Response / synthesis_response: the model's reasoning + tool calls. */}
      {(entry.phase === 'response' || entry.phase === 'synthesis_response') && (
        <div className="eyed-entry-body">
          {entry.content ? (
            <div className="eyed-markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{entry.content}</ReactMarkdown>
            </div>
          ) : (
            <div className="eyed-muted">(no text — model returned tool calls only)</div>
          )}
          {entry.tool_calls && entry.tool_calls.length > 0 && (
            <div className="eyed-toolcalls">
              <span className="eyed-meta-label">Tool calls requested:</span>
              {entry.tool_calls.map((tc, i) => (
                <div key={i} className="eyed-toolcall">
                  <span className="eyed-toolcall-name">{tc.name}</span>
                  <pre className="eyed-pre eyed-pre--args">
                    {JSON.stringify(tc.arguments, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tool result fed back to the model. */}
      {entry.phase === 'tool_result' && (
        <div className="eyed-entry-body">
          <div className="eyed-meta-line">
            <span className="eyed-toolcall-name">{entry.tool_name}</span>
          </div>
          {entry.parameters && Object.keys(entry.parameters).length > 0 && (
            <Collapsible title="Parameters">
              <pre className="eyed-pre eyed-pre--args">
                {JSON.stringify(entry.parameters, null, 2)}
              </pre>
            </Collapsible>
          )}
          {entry.result && (
            <Collapsible title="Result returned">
              <pre className="eyed-pre">{entry.result}</pre>
            </Collapsible>
          )}
        </div>
      )}
    </article>
  );
});

// memo: the transcript re-renders only when its `entries`/`live` props change
// (a fetch), not on every render of the parent panel.
const EyeDialogue = memo(function EyeDialogue({ entries, live = false }: EyeDialogueProps) {
  if (!entries || entries.length === 0) return null;
  return (
    <div className={`eye-dialogue ${live ? 'eye-dialogue--live' : ''}`}>
      {entries.map((entry) => (
        <EntryView key={entry.seq} entry={entry} />
      ))}
    </div>
  );
});

export default EyeDialogue;
