/**
 * Report Block Component for EYE Forensic Assistant
 * 
 * Individual block rendering with inline editing capabilities for each block type:
 * - TextBlock: Inline editing for title and markdown content
 * - TableBlock: Static rendering with DataTables.js for sorting/filtering
 * - ImageBlock: Image display with caption
 * - ReferenceBlock: Expandable evidence sections
 * - ChartBlock: Data visualizations (Bar, Line, Pie)
 * 
 * All blocks include delete functionality.
 */

import React, { useState } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { getBridge } from './bridge';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  ArcElement
} from 'chart.js';
import { Bar, Line, Pie } from 'react-chartjs-2';
import './ReportBlockComponent.css';

// Register Chart.js components
ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  PointElement,
  LineElement,
  ArcElement,
  Title,
  Tooltip,
  Legend
);

/**
 * Report block type definitions
 */
interface ReportBlock {
  block_id: string;
  block_type: 'text' | 'table' | 'image' | 'reference' | 'chat' | 'chart';
  metadata: {
    timestamp: string;
    author?: string;
    last_modified?: string;
    last_modified_by?: string;
  };
}

interface TextBlock extends ReportBlock {
  block_type: 'text';
  title: string;
  markdown_content: string;
}

interface TableBlock extends ReportBlock {
  block_type: 'table';
  sql_query: string;
  columns: string[];
  rows: Record<string, any>[];
  caption: string;
}

interface ImageBlock extends ReportBlock {
  block_type: 'image';
  image_path: string;
  caption: string;
}

interface ReferenceBlock extends ReportBlock {
  block_type: 'reference';
  reference_text: string;
  source_link: string;
  evidence_data?: Record<string, any>[];
}

interface ChatBlock extends ReportBlock {
  block_type: 'chat';
  messages: { role: string; content: string }[];
}

interface ChartBlock extends ReportBlock {
  block_type: 'chart';
  chart_type: 'bar' | 'line' | 'pie';
  title: string;
  labels: string[];
  datasets: { label: string; data: number[]; backgroundColor?: string }[];
}

type AnyBlock = TextBlock | TableBlock | ImageBlock | ReferenceBlock | ChatBlock | ChartBlock;

/**
 * Props for ReportBlockComponent
 */
interface ReportBlockComponentProps {
  block: AnyBlock;
  onDelete?: (blockId: string) => void;
  onUpdate?: (blockId: string, updatedBlock: AnyBlock) => void;
}

/**
 * Main Report Block Component with editing capabilities
 */
const ReportBlockComponent: React.FC<ReportBlockComponentProps> = ({
  block,
  onDelete,
  onUpdate,
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

  const renderBlockContent = () => {
    switch (block.block_type) {
      case 'text': return <TextBlockContent block={block as TextBlock} onUpdate={onUpdate} />;
      case 'table': return <TableBlockContent block={block as TableBlock} />;
      case 'image': return <ImageBlockContent block={block as ImageBlock} />;
      case 'reference': return <ReferenceBlockContent block={block as ReferenceBlock} />;
      case 'chat': return <ChatBlockContent block={block as ChatBlock} />;
      case 'chart': return <ChartBlockContent block={block as ChartBlock} />;
      default: return <div className="unknown-block">Unknown block type</div>;
    }
  };

  return (
    <div ref={setNodeRef} style={style} className={`report-block ${block.block_type}-block ${isDragging ? 'dragging' : ''}`}>
      <div className="block-header">
        <div className="drag-handle" {...attributes} {...listeners} title="Drag to reorder">⋮⋮</div>
        <div className="block-type-badge">{block.block_type}</div>
        <div className="block-meta">
          <span className="block-author">{block.metadata.author || 'unknown'}</span>
          {block.metadata.last_modified && (
            <span className="block-timestamp">{new Date(block.metadata.last_modified).toLocaleString()}</span>
          )}
        </div>
        <button className="delete-button" onClick={handleDelete}>🗑️</button>
      </div>
      <div className="block-body">{renderBlockContent()}</div>
    </div>
  );
};

const ChartBlockContent: React.FC<{ block: ChartBlock }> = ({ block }) => {
  const data = {
    labels: block.labels,
    datasets: block.datasets.map((ds, i) => ({
      ...ds,
      backgroundColor: ds.backgroundColor || ['#f97316', '#06b6d4', '#ec4899', '#10b981', '#ff4d6a'][i % 5],
    }))
  };
  const options = {
    responsive: true, maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: '#e8edf5', font: { family: 'Space Mono' } } },
      title: { display: true, text: block.title, color: '#f97316', font: { size: 18, family: 'Syne' } }
    },
    scales: block.chart_type !== 'pie' ? {
      y: { ticks: { color: '#8899aa' }, grid: { color: '#1e2a3a' } },
      x: { ticks: { color: '#8899aa' }, grid: { color: '#1e2a3a' } }
    } : undefined
  };
  return (
    <div className="chart-block-view">
      <div className="chart-container">
        {block.chart_type === 'bar' && <Bar data={data} options={options} />}
        {block.chart_type === 'line' && <Line data={data} options={options} />}
        {block.chart_type === 'pie' && <Pie data={data} options={options} />}
      </div>
    </div>
  );
};

const ChatBlockContent: React.FC<{ block: ChatBlock }> = ({ block }) => (
  <div className="chat-block-view">
    {block.messages.map((msg, idx) => (
      <div key={idx} className={`chat-bubble-container ${msg.role}`}>
        <div className="chat-bubble-role">{msg.role.toUpperCase()}</div>
        <div className="chat-bubble-content">
          {msg.content.split('\n').map((line, i) => <React.Fragment key={i}>{line}<br/></React.Fragment>)}
        </div>
      </div>
    ))}
  </div>
);

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
      <div className="text-block-content">{block.markdown_content.split('\n').map((l, i) => <p key={i}>{l}</p>)}</div>
      <div className="edit-hint">Click to edit</div>
    </div>
  );
};

const TableBlockContent: React.FC<{ block: TableBlock }> = ({ block }) => {
  const [filter, setFilter] = useState('');
  const filtered = block.rows.filter(r => Object.values(r).some(v => String(v).toLowerCase().includes(filter.toLowerCase())));
  return (
    <div className="table-block-view">
      {block.caption && <h4 className="table-caption">{block.caption}</h4>}
      <div className="table-controls">
        <input className="table-filter" placeholder="Search table..." value={filter} onChange={e => setFilter(e.target.value)} />
        <span className="table-info">Showing {filtered.length} of {block.rows.length}</span>
      </div>
      <div className="table-wrapper">
        <table className="data-table">
          <thead><tr>{block.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>{filtered.map((r, i) => <tr key={i}>{block.columns.map(c => <td key={c}>{String(r[c] ?? '')}</td>)}</tr>)}</tbody>
        </table>
      </div>
      {block.sql_query && <details className="query-details"><summary>View SQL</summary><pre className="sql-query">{block.sql_query}</pre></details>}
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
  return (
    <div className="reference-block-view">
      <div className="reference-summary">
        <p>{block.reference_text}</p>
        <button className="view-evidence-button" onClick={() => setOpen(!open)}>{open ? 'Hide' : 'View'} Evidence</button>
      </div>
      {open && block.evidence_data && (
        <div className="evidence-details">
          <div className="evidence-table-wrapper">
            <table className="evidence-table">
              <thead><tr>{Object.keys(block.evidence_data[0] || {}).map(k => <th key={k}>{k}</th>)}</tr></thead>
              <tbody>{block.evidence_data.map((r, i) => <tr key={i}>{Object.values(r).map((v: any, j) => <td key={j}>{String(v)}</td>)}</tr>)}</tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

export default ReportBlockComponent;
export type { AnyBlock };
