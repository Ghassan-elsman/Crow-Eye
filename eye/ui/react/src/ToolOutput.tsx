import React, { useState, memo } from 'react';
import type { ToolOutputEntry } from './types';
import './ToolOutput.css';

/**
 * ToolOutput — a dedicated, collapsed-by-default "🔧 Tool output" section under an
 * assistant message. It keeps the (often large) raw tool results — including the
 * text-protocol tool calls used by models without native function-calling (Gemma) —
 * out of the main chat bubble, one expand away. Each entry shows the tool name, the
 * call parameters, a success/failed badge, and the raw result text.
 */

interface ToolOutputProps {
  entries: ToolOutputEntry[];
}

const ToolEntry: React.FC<{ entry: ToolOutputEntry; index: number }> = ({ entry, index }) => {
  const [open, setOpen] = useState(false);
  const hasParams = entry.parameters && Object.keys(entry.parameters).length > 0;
  return (
    <div className="tool-output-entry">
      <button className="tool-output-entry-head" onClick={() => setOpen(!open)}>
        <span className="tool-output-caret">{open ? '▾' : '▸'}</span>
        <span className="tool-output-index">{index + 1}.</span>
        <span className="tool-output-name">{entry.name}</span>
        <span className={`tool-output-badge ${entry.success ? 'tool-output-badge--ok' : 'tool-output-badge--fail'}`}>
          {entry.success ? 'SUCCESS' : 'FAILED'}
        </span>
      </button>
      {open && (
        <div className="tool-output-entry-body">
          {hasParams && (
            <>
              <div className="tool-output-sublabel">Parameters</div>
              <pre className="tool-output-pre tool-output-pre--args">
                {JSON.stringify(entry.parameters, null, 2)}
              </pre>
            </>
          )}
          <div className="tool-output-sublabel">Result</div>
          <pre className="tool-output-pre">{entry.result_text || '(no result text)'}</pre>
        </div>
      )}
    </div>
  );
};

const ToolOutput: React.FC<ToolOutputProps> = memo(({ entries }) => {
  const [open, setOpen] = useState(false);
  if (!entries || entries.length === 0) return null;
  return (
    <div className="tool-output">
      <button className="tool-output-toggle" onClick={() => setOpen(!open)}>
        {open ? '▾' : '▸'} 🔧 {open ? 'Hide' : 'Show'} tool output ({entries.length} call{entries.length === 1 ? '' : 's'})
      </button>
      {open && (
        <div className="tool-output-list">
          {entries.map((e, i) => (
            <ToolEntry key={i} entry={e} index={i} />
          ))}
        </div>
      )}
    </div>
  );
});

export default ToolOutput;
