/**
 * Report Block Component for Eye Forensic Assistant
 * 
 * Individual block rendering with inline editing capabilities for each block type.
 * Includes category-based styling for consistent forensic pillars.
 */

import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useSortable } from '@dnd-kit/sortable';
import { getBridge } from './bridge';
import { ChartBlockContent, TimelineBlockContent, HeatmapBlockContent } from './ReportCharts';
import './ReportBlockComponent.css';


import { 
  type AnyBlock, 
  type TextBlock, 
  type TableBlock, 
  type ImageBlock, 
  type ReferenceBlock, 
  type ChatBlock, 
  type ChartBlock,
  type TimelineBlock,
  type HeatmapBlock,
  type ChainOfCustodyBlock
} from './types';


// --- Helpers ---

interface ReportBlockComponentProps {
  block: AnyBlock;
  onDelete?: (blockId: string) => void;
  onUpdate?: (blockId: string, updatedBlock: AnyBlock) => void;
  /** 1-based section number shown on the block and used as its anchor (sec-N). */
  sectionNumber?: number;
  /** 'half' when two small charts share a row (wide screens only). */
  layout?: 'full' | 'half';
}

// --- Helpers ---

/**
 * Colour in the report carries meaning only (Crow-Eye rule: red = urgent).
 * Every block shares the neutral accent; a block the Eye marked with a
 * severity gets amber (high / medium) or red (critical). The old per-category
 * rainbow (pink security, orange USB, purple persistence...) said nothing.
 */
const getCategoryColor = (_category?: string, _title: string = "", _index: number = 0) => 'var(--accent)';

export const severityTone = (severity?: string): string | undefined => {
  const s = (severity || '').toLowerCase();
  if (s === 'critical') return '#f87171';
  if (s === 'high' || s === 'medium') return '#fbbf24';
  return undefined;
};

export const KIND_NAMES: Record<string, string> = {
  text: 'Finding', table: 'Table', chart: 'Chart', timeline: 'Timeline', heatmap: 'Heatmap',
  image: 'Image', reference: 'Evidence', chat: 'Conversation', chain_of_custody: 'Chain of custody',
};

// --- Sub-Components ---

const TextBlockContent: React.FC<{ block: TextBlock, onUpdate?: any }> = ({ block, onUpdate }) => {
  const [isEditing, setIsEditing] = useState(false);
  const [title, setTitle] = useState(block.title);
  const [content, setContent] = useState(block.markdown_content);

  const handleSave = async () => {
    const bridge = getBridge();
    if (!bridge) return;
    const res = await bridge.report_edit_section(block.block_id, JSON.stringify({ title, markdown_content: content }));
    if (JSON.parse(res).success) {
      setIsEditing(false);
      if (onUpdate) onUpdate(block.block_id, { ...block, title, markdown_content: content });
    }
  };

  if (isEditing) return (
    <div className="text-block-edit">
      <input className="title-input" value={title} onChange={e => setTitle(e.target.value)} />
      <textarea className="content-textarea" value={content} onChange={e => setContent(e.target.value)} />
      <div className="edit-actions">
        <button className="save-button" onClick={handleSave}>Save</button>
        <button className="cancel-button" onClick={() => setIsEditing(false)}>Cancel</button>
      </div>
    </div>
  );

  return (
    <div className="text-block-view" onClick={() => setIsEditing(true)}>
      <h3 className="text-block-title">{block.title}</h3>
      <div className="text-block-content markdown-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{block.markdown_content}</ReactMarkdown>
      </div>
      <div className="edit-hint">Click to edit</div>
    </div>
  );
};

const TableBlockContent: React.FC<{ block: TableBlock }> = ({ block }) => {
  const [filter, setFilter] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const rowsPerPage = 25; // Smaller page size for report blocks

  const filtered = block.rows.filter(r => 
    Object.values(r).some(v => String(v).toLowerCase().includes(filter.toLowerCase()))
  );

  const themeColor = getCategoryColor(block.category, block.caption);
  const totalPages = Math.ceil(filtered.length / rowsPerPage);
  const paginatedRows = filtered.slice((currentPage - 1) * rowsPerPage, currentPage * rowsPerPage);

  // Reset to first page when filtering
  const handleFilterChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFilter(e.target.value);
    setCurrentPage(1);
  };

  return (
    <div className="table-block-view">
      {block.caption && <h4 className="table-caption" style={{ color: themeColor }}>{block.caption}</h4>}
      <div className="table-controls">
        <input 
          className="table-filter" 
          placeholder="Search table..." 
          value={filter} 
          onChange={handleFilterChange} 
        />
        <div className="table-pagination-controls">
          <button 
            disabled={currentPage === 1} 
            onClick={() => setCurrentPage(p => p - 1)}
            className="pagination-btn"
          >
            &lt;
          </button>
          <span className="table-info">Page {currentPage} of {totalPages || 1} ({filtered.length} items)</span>
          <button 
            disabled={currentPage === totalPages || totalPages === 0} 
            onClick={() => setCurrentPage(p => p + 1)}
            className="pagination-btn"
          >
            &gt;
          </button>
        </div>
      </div>
      <div className="table-wrapper">
        <table className="data-table">
          <thead>
            <tr style={{ borderColor: themeColor }}>
              {block.columns.map((col, i) => (
                <th key={i} style={{ color: themeColor }}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paginatedRows.length > 0 ? (
              paginatedRows.map((r, i) => (
                <tr key={i}>
                  {block.columns.map(c => {
                    // Resilient key matching: try exact, then normalized (lowercase, no spaces/underscores)
                    const normalizedCol = c.toLowerCase().replace(/[\s_]/g, '');
                    const rowKey = Object.keys(r).find(k => 
                      k === c || 
                      k.toLowerCase() === c.toLowerCase() ||
                      k.toLowerCase().replace(/[\s_]/g, '') === normalizedCol
                    ) || c;
                    
                    return <td key={c}>{String(r[rowKey] ?? '')}</td>;
                  })}
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={block.columns.length} style={{ textAlign: 'center', padding: '20px', color: '#64748b' }}>
                  No matching results found
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {block.sql_query && (
        <details className="query-details">
          <summary>View SQL Source</summary>
          <pre className="sql-query">{block.sql_query}</pre>
        </details>
      )}
    </div>
  );
};

const ImageBlockContent: React.FC<{ block: ImageBlock }> = ({ block }) => (
  <div className="image-block-view">
    <img src={block.image_path} alt={block.caption} className="block-image" />
    {block.caption && <p className="image-caption">{block.caption}</p>}
  </div>
);

const ReferenceBlockContent: React.FC<{ block: ReferenceBlock }> = ({ block }) => {
  const [open, setOpen] = useState(false);
  const themeColor = getCategoryColor(block.category, block.reference_text);

  // Use explicit columns if provided, otherwise infer from first row
  const columns: string[] = (block.columns && block.columns.length > 0)
    ? block.columns 
    : (block.evidence_data && block.evidence_data.length > 0 ? Object.keys(block.evidence_data[0]) : []);

  return (
    <div className="reference-block-view">
      <div className="reference-summary">
        <p style={{ borderLeftColor: themeColor }}>{block.reference_text}</p>
        <button className="view-evidence-button" style={{ borderColor: themeColor, color: themeColor }} onClick={() => setOpen(!open)}>
          {open ? 'Hide' : 'View'} Evidence
        </button>
      </div>
      {open && block.evidence_data && (
        <div className="evidence-details">
          <div className="evidence-table-wrapper">
            <table className="evidence-table">
              <thead>
                <tr>{columns.map((k: string) => <th key={k} style={{ color: themeColor }}>{k}</th>)}</tr>
              </thead>
              <tbody>
                {block.evidence_data.map((r: Record<string, any>, i: number) => (
                  <tr key={i}>
                    {columns.map((c: string, j: number) => {
                       // Use resilient matching similar to TableBlock
                       const normalizedCol = c.toLowerCase().replace(/[\s_]/g, '');
                       const rowKey = Object.keys(r).find(k => 
                         k === c || 
                         k.toLowerCase() === c.toLowerCase() ||
                         k.toLowerCase().replace(/[\s_]/g, '') === normalizedCol
                       ) || c;
                       return <td key={j}>{String(r[rowKey] ?? '')}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

const CustodyBlockContent: React.FC<{ block: ChainOfCustodyBlock }> = ({ block }) => (
  <div className="custody-block-view">
    <table className="custody-table">
      <thead>
        <tr>
          <th>Evidence ID</th>
          <th>Action</th>
          <th>Handler</th>
          <th>Timestamp</th>
        </tr>
      </thead>
      <tbody>
        {block.entries.map((entry, i) => (
          <tr key={i}>
            <td>{entry.evidence_id}</td>
            <td>{entry.action}</td>
            <td>{entry.handler_name}</td>
            <td>{new Date(entry.timestamp).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const ChatBlockContent: React.FC<{ block: ChatBlock }> = ({ block }) => (
  <div className="chat-block-view">
    {block.messages.map((msg, idx) => (
      <div key={idx} className={`chat-bubble-container ${msg.role}`}>
        <div className="chat-bubble-role">{msg.role.toUpperCase()}</div>
        <div className="chat-bubble-content markdown-body">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
        </div>
      </div>
    ))}
  </div>
);

// --- Main Component ---

const ReportBlockComponent: React.FC<ReportBlockComponentProps> = ({
  block,
  onDelete,
  onUpdate,
  sectionNumber,
  layout = 'full',
}) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: block.block_id });

  const style = {
    transform: transform
      ? `translate3d(${transform.x}px, ${transform.y}px, 0)`
      : undefined,
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const handleDelete = async () => {
    if (!confirm('Are you sure you want to delete this block?')) return;
    try {
      const bridge = getBridge();
      if (!bridge) throw new Error('Bridge not initialized');
      const responseJson = await bridge.report_delete_section(block.block_id);
      const response = JSON.parse(responseJson);
      if (response.success && onDelete) onDelete(block.block_id);
    } catch (error) {
      console.error('Failed to delete block:', error);
    }
  };

  const severity = String((block.metadata as any)?.severity || '').toLowerCase();
  const tone = severityTone(severity);

  const provenanceGeneratedAt = block.metadata?.timestamp
    ? new Date(block.metadata.timestamp).toLocaleString()
    : 'Unknown';
  const provenanceQuestion = block.metadata?.source_query || 'Unknown / Manual';
  const provenanceAuthor = block.metadata?.author || 'Unknown';

  const renderBlockContent = () => {
    switch (block.block_type) {
      case 'text': return <TextBlockContent block={block as TextBlock} onUpdate={onUpdate} />;
      case 'table': return <TableBlockContent block={block as TableBlock} />;
      case 'image': return <ImageBlockContent block={block as ImageBlock} />;
      case 'reference': return <ReferenceBlockContent block={block as ReferenceBlock} />;
      case 'chat': return <ChatBlockContent block={block as ChatBlock} />;
      case 'chart': return <ChartBlockContent block={block as ChartBlock} />;
      case 'timeline': return <TimelineBlockContent block={block as TimelineBlock} />;
      case 'heatmap': return <HeatmapBlockContent block={block as HeatmapBlock} />;
      case 'chain_of_custody': return <CustodyBlockContent block={block as ChainOfCustodyBlock} />;
      default: return <div className="unknown-block">Unknown block type</div>;
    }
  };

  return (
    <div
      ref={setNodeRef}
      id={sectionNumber ? `sec-${sectionNumber}` : undefined}
      style={tone ? { ...style, ['--block-accent' as any]: tone } : style}
      className={`report-block ${block.block_type}-block layout-${layout} ${tone ? 'has-severity' : ''} ${isDragging ? 'dragging' : ''}`}
      data-severity={tone ? severity : undefined}
      {...attributes}
    >
      {sectionNumber ? (
        <div className="block-sec-label">
          <span className="block-sec-num">{sectionNumber}</span>
          <span className="block-sec-kind">{KIND_NAMES[block.block_type] || block.block_type}</span>
          {tone && <span className="block-sec-severity">{severity}</span>}
        </div>
      ) : null}
      {/* Styled provenance hover card: reveals when this block was generated
          and by which investigator question. Replaces the plain browser
          tooltip; revealed on .report-block:hover (see .css). */}
      <div className="block-provenance-card" role="tooltip">
        <div className="block-provenance-row">
          <span className="block-provenance-label">Generated</span>
          <span className="block-provenance-value">{provenanceGeneratedAt}</span>
        </div>
        <div className="block-provenance-row">
          <span className="block-provenance-label">From question</span>
          <span className="block-provenance-value">{provenanceQuestion}</span>
        </div>
        <div className="block-provenance-row">
          <span className="block-provenance-label">Author</span>
          <span className="block-provenance-value">{provenanceAuthor}</span>
        </div>
      </div>
      {/* Block headers (Chart AI / Text AI / Table AI etc.) intentionally
          removed for a clean report appearance. Drag-to-reorder is bound
          to a small handle revealed on hover so the block surface stays
          unobstructed; delete is a hover-revealed corner action. */}
      <span className="block-drag-handle" {...listeners} title="Drag to reorder" aria-label="Drag to reorder">⋮⋮</span>
      <button
        className="block-delete-action"
        onClick={handleDelete}
        title="Delete block"
        aria-label="Delete block"
      >
        ×
      </button>
      <div className="block-body">{renderBlockContent()}</div>
    </div>
  );
};

export default ReportBlockComponent;
